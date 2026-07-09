# 對話管理（Conversation Management）設計文件

**日期：** 2026-07-08
**範圍：** PRD「功能需求 - 對話管理」— 設計儲存用戶會話歷史的 model
**不涵蓋：** AI 自動回覆的 Celery 任務實作、API endpoint 實作、Django Admin 介面（屬於後續需求，將另外討論）
**修正紀錄（2026-07-09）：** 下方「高階流程」與「設計決策 6、7」已被 [AI 自動回覆流程設計文件](2026-07-09-ai-auto-reply-design.md) 修正/補完，修正原因見該文件；本文件保留供歷史脈絡參考，實作請以修正版為準。

## 背景

PRD 要求設計一個 model 儲存用戶的會話歷史，每筆會話需包含使用者資訊、會話狀態、時間戳記、對話內容。本文件聚焦資料模型設計，作為後續「AI 自動回覆流程」與「API 與管理介面」需求的基礎。

## 整體架構

新增一個獨立 app：`maiagent_ai_django/conversations`，加入 `LOCAL_APPS`。包含三個 model：

- **SceneConfig** — 場景設定（客服 / KM），決定 AI 處理邏輯要用的參數來源
- **Conversation** — 一次會話，掛使用者、場景、狀態
- **Message** — 會話中的單則訊息（USER 或 AI 發送），含生成狀態、內容、全文檢索索引

關聯：`SceneConfig (1) ← Conversation (N) ← Message`。此 app 只負責資料儲存與查詢，不含 AI 呼叫邏輯。

## 高階流程

> **此流程圖已由 [AI 自動回覆流程設計文件](2026-07-09-ai-auto-reply-design.md) 修正**，主要差異：AI Message(PENDING) 改為在 API 同步處理查詢的當下就建立（而非等非同步任務開始執行後才建立），消除前端查不到任何 AI 訊息行的空窗期；並補上重試機制與失敗後轉真人（`PENDING_HUMAN`）的規則。以下保留原始版本供歷史脈絡參考，實作請以修正版文件為準。

```
使用者發送查詢
      │
      ▼
[API] 接收查詢
      │
      ├─ 若無現有 Conversation → 建立 Conversation(status=OPEN, scene=<場景>)
      │
      ▼
建立 Message(sender_type=USER, status=COMPLETED, content=<查詢內容>)
      │
      ▼
觸發 Celery 非同步任務(conversation_id, user_message_id)
      │
      ▼
[回應前端] 202 Accepted，回傳 conversation_id / user_message_id
      │
      ▼ (非同步背景執行)
建立 Message(sender_type=AI, status=PENDING, content="")
      │
      ▼
依 Conversation.scene 取得處理設定 → 呼叫（模擬的）外部生成式 AI API
      │
      ├─ 成功 → 更新該 AI Message：status=COMPLETED, content=<AI回覆>, metadata=<model/tokens>
      │
      └─ 失敗 → 更新該 AI Message：status=FAILED, error_message=<錯誤原因>
      │
      ▼
更新 Conversation.modified（TimeStampedModel 自動處理）
      │
      ▼
前端透過 GET /conversations/{id}/messages 輪詢或另建通知機制取得結果
```

## 資料合約（DBML）

```dbml
// 既有表（cookiecutter-django users app），僅列出本設計會關聯到的欄位，非本次異動範圍
Table users {
  id integer [pk]
  email varchar [unique, not null]
}

Table scene_configs {
  id uuid [pk]
  name varchar(100) [unique, not null]
  scene_type varchar(32) [not null, note: 'enum: customer_service | knowledge_management']
  default_settings jsonb [not null, default: '{}']
  is_active boolean [not null, default: true]
  created timestamptz [not null]
  modified timestamptz [not null]
}

Table conversations {
  id uuid [pk]
  user_id integer [not null, ref: > users.id]
  scene_id uuid [not null, ref: > scene_configs.id]
  status varchar(32) [not null, default: 'open', note: 'enum: open | pending_human | closed']
  is_deleted boolean [not null, default: false]
  deleted_at timestamptz [null]
  created timestamptz [not null]
  modified timestamptz [not null]

  indexes {
    (user_id, created) [name: 'idx_conversations_user_created']
  }
}

Table messages {
  id uuid [pk]
  conversation_id uuid [not null, ref: > conversations.id]
  sender_type varchar(16) [not null, note: 'enum: user | ai']
  content text [not null]
  status varchar(16) [not null, default: 'completed', note: 'enum: pending | completed | failed']
  error_message text [null]
  metadata jsonb [not null, default: '{}']
  search_vector tsvector [null]
  is_deleted boolean [not null, default: false]
  deleted_at timestamptz [null]
  created timestamptz [not null]
  modified timestamptz [not null]

  indexes {
    (conversation_id, created) [name: 'idx_messages_conversation_created']
    search_vector [type: gin, name: 'idx_messages_search_vector']
  }
}
```

> 註：上方 `users` 為 cookiecutter-django 既有的 `users_user` 表（app label `users`）之簡化示意，僅列出本設計關聯到的欄位，此設計文件不變更該表結構。

## 設計決策與理由

### 1. Session + Message 兩層設計，而非單表或 JSONField

Conversation 代表一次完整的對話情境，Message 代表其中單一則訊息（USER 或 AI）。理由：

- PRD 明確要求「先記錄查詢內容，再非同步生成回覆，回覆後更新對話記錄」— 這需要對「單一則訊息」有獨立的狀態機（PENDING → COMPLETED / FAILED），JSONField 或單表設計無法乾淨地表達這種單筆狀態轉換，且並發更新同一個 JSON 欄位容易產生 race condition。
- 兩層設計也讓全文檢索、分頁載入歷史訊息、未來多輪上下文管理更自然。

### 2. 使用者模型：現階段僅支援 Django User，預留外部使用者擴充路徑

現階段 `Conversation.user` 直接 FK 到 `users.User`（cookiecutter-django 既有 model），因為題目範圍內發訊者都是已登入的系統使用者。

**未來擴充（不在本次實作範圍）：** 若要支援外部終端使用者（如網站嵌入的訪客、LINE 用戶），採用「影子帳號」模式 — 新增 `ExternalIdentity(user FK, channel, external_id)` model，`unique_together(channel, external_id)`。外部使用者首次來訊時，以 `channel + external_id` 查找或自動建立一個 `User`（`is_active=True`、無可用密碼），並建立對應的 `ExternalIdentity` 記錄。如此 `Conversation.user` 欄位維持穩定，不需要因為支援外部使用者而修改 schema 或搬遷既有資料。

### 3. SceneConfig 獨立於 Conversation 之外

`scene` 是會話的內在屬性 —— 建立 Conversation 時就決定了要用哪套 AI 處理邏輯（提示詞、模型、是否查知識庫），因此現在就設計為 Conversation 的必要 FK，而非留到後續需求才加。

`SceneConfig` 現階段僅有最小欄位集合（`name`、`scene_type`、`default_settings` JSONField 作為彈性擴充位），複雜的路由邏輯與動態權重（PRD 附加挑戰）留待後續需求設計，屆時只需在 `SceneConfig` 上擴充欄位或新增關聯 model，不影響 `Conversation`/`Message` 既有資料。

`id` 維持 UUID 型別 pk（不用 `scene_type` 當 pk），原因是未來可能需要同一場景類型存在多組不同設定（例如不同客戶各自客製化的 customer_service 設定），因此 `name` 唯一即可，`scene_type` 不加索引（低基數欄位，加索引對查詢效能助益有限）。

### 4. 主鍵型別：UUID

`Conversation` 與 `Message` 皆使用 UUID 當主鍵，而非預設自增整數。理由：這兩張表的資料會透過 RESTful API 直接曝露給前端，UUID 可避免使用者透過連續整數 ID 猜測或枚舉他人的對話記錄（IDOR 風險）。`SceneConfig` 同樣採 UUID 以維持一致性。`conversations.user_id` 則維持 `users.User` 既有的 integer pk，不變更既有 model。

### 5. Message 排序：`created` + `id`，不額外加排序欄位

最初考慮用獨立的 `BigAutoField` sequence 欄位保證嚴格順序（避免 UUID 主鍵不具時序性、且極端並發下 timestamp 可能撞值的問題）。但重新檢視實際查詢模式後，發現無論是組裝 LLM context 或 API 回傳訊息列表，都是把整個 Conversation 底下的訊息一次性拉出再排序，不存在逐筆單獨定位的需求。因此改採 `Meta.ordering = ["created", "id"]`：`created`（PostgreSQL timestamp 具微秒精度）為主要排序依據，`id` 作為並列時的穩定 tie-breaker，避免同一次查詢多次執行結果順序不一致。同一 Conversation 內兩則訊息撞到同一微秒的機率極低，即使發生也只影響顯示順序、不影響系統正確性，故不另加欄位（YAGNI）。

### 6. Message 狀態機：PENDING / COMPLETED / FAILED

- USER 發送的訊息寫入時直接是 `COMPLETED`（內容當下就完整）。
- AI 回覆訊息由 API 同步建立時先是 `PENDING`，Celery 任務呼叫 AI API 成功後更新為 `COMPLETED` 並填入內容與 `metadata`（模型名稱、token 數、重試次數等，彈性存放於 JSONField，不預先固定欄位）；失敗則更新為 `FAILED` 並記錄 `error_message` 供除錯與重試判斷。

> **修正（2026-07-09）：** 當時本節標記「重試機制」「失敗後是否轉 `PENDING_HUMAN`」尚未設計，現已在 [AI 自動回覆流程設計文件](2026-07-09-ai-auto-reply-design.md) 中定義：有限次數自動重試（3 次、exponential backoff + jitter），重試期間狀態維持 `PENDING`；重試用盡仍失敗才寫入 `FAILED`。

### 7. Conversation 狀態：OPEN / PENDING_HUMAN / CLOSED

涵蓋客服場景常見的三種狀態，`PENDING_HUMAN` 為 AI 無法處理、需轉真人客服介入時使用，也為未來人工客服接手功能預留位置。

> **修正（2026-07-09）：** 轉換條件現已定義——AI Message 重試用盡仍失敗時，所屬 Conversation 自動由 `OPEN` 轉為 `PENDING_HUMAN`，詳見 [AI 自動回覆流程設計文件](2026-07-09-ai-auto-reply-design.md)。

### 8. 軟刪除

`Conversation` 與 `Message` 皆採軟刪除（`is_deleted` / `deleted_at`），不做硬刪除。客服與知識管理場景的對話記錄通常有合規、稽核需求，不應被真正刪除。

- `Conversation.user` / `Conversation.scene` 的 `on_delete` 設為 `PROTECT`：防止誤刪使用者或場景設定時，連帶清空其歷史對話記錄。
- `Message.conversation` 的 `on_delete` 設為 `CASCADE`：訊息離開所屬對話沒有意義；但主要的刪除路徑是軟刪除，此設定僅作為資料庫層級的完整性保底。

### 9. 全文檢索

`messages.search_vector`（`SearchVectorField` + GIN index）預先建立，對應 PRD 附加挑戰「為對話記錄提供全文檢索功能」。全文檢索欄位放在 `messages` 而非 `conversations`，因為檢索目標是「訊息內容」本身，查到符合的訊息後可再回推所屬 `conversation_id` 定位整個對話。`search_vector` 的實際填值機制（透過 signal 或 Postgres trigger 在 `content` 寫入/更新時同步）屬於實作細節，將在後續實作階段處理。

## 未來擴充摘要

| 項目 | 現況 | 未來擴充方式 |
|---|---|---|
| 外部終端使用者 | 未實作 | 新增 `ExternalIdentity` model，維持 `Conversation.user` 不變 |
| 多 AI 模型 / 動態路由權重 | `SceneConfig.default_settings` 為彈性 JSONField | 於 `SceneConfig` 擴充欄位或新增關聯 model（如路由規則表） |
| 全文檢索填值機制 | 已建立欄位與索引 | 實作 signal/trigger 同步 `search_vector` |

## 測試考量

- Model 層級：驗證 `Conversation`/`Message` 的預設值、狀態轉換是否符合預期（如新建 AI Message 預設 `PENDING`）。
- 軟刪除行為：確認 `is_deleted=True` 的記錄在預設 queryset 中被排除（需自訂 Manager，將在實作階段設計）。
- 全文檢索：驗證 `search_vector` 更新後可用中文/英文關鍵字查到對應訊息。
