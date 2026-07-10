# Final Spec — Gen AI 自動回覆平台後端系統（整合版設計文件）

**日期：** 2026-07-10
**定位：** 本文件整合並取代下列四份迭代 spec 的「修正紀錄」交叉引用，為實作階段的唯一權威依據（single source of truth）。原始四份文件保留供設計脈絡與決策過程參考：

1. [對話管理](2026-07-08-conversation-management-design.md)（spec1）
2. [AI 自動回覆流程](2026-07-09-ai-auto-reply-design.md)（spec2）
3. [API 與管理介面](2026-07-09-api-admin-design.md)（spec3）
4. [擴充性 — 多 AI 模型路由](2026-07-10-scalability-model-routing-design.md)（spec4）

**本次整合新增的修正（相對於四份原始 spec）：**

- **[修正 A1]** Celery task 改呼叫同步 `generate()`（原 spec4 程式碼在同步 `@shared_task` 內 `await agenerate(...)`，語法不成立；Celery 原生不支援 async task）。
- **[修正 A2]** 明確定義 `DelayedFailureSimulator` 在 `litellm.Router` 架構下的模擬方式（原 spec4 只把 router 傳進 simulator，未定義如何避免真實 API 呼叫、如何模擬特定候選失敗）。
- **[修正 B1]** 補上對 `CLOSED` / `PENDING_HUMAN` 狀態 Conversation 提交查詢的行為定義（皆回 409）。
- **[修正 B2/B3]** 補上 `ModelRoute.order` 為 SQL 保留字、`litellm.Router` 參數未實測的風險註記。
- 統一資料合約：`messages.model_used`、`model_routes` 表併入同一份 DBML。
- `GET /api/scenes/` 對一般使用者的欄位限制明確化。

## PRD 需求對照

| PRD 需求 | 本文件章節 |
|---|---|
| 對話管理 | 資料模型 |
| AI 自動回覆流程 | 高階流程、AI 呼叫抽象層、Celery 任務設計 |
| API 與管理介面 | API 設計、認證與授權、Django Admin |
| 擴充性 | 多模型路由（ModelRoute + litellm.Router）、未來擴充摘要 |
| 附加挑戰：進階搜尋 | `messages.search_vector` + GIN index + `?q=` 查詢參數 |
| 附加挑戰：多 AI 模型支持 | 多模型路由（模型部分；「回覆模板」路由不在範圍） |

## 整體架構

專案基於 cookiecutter-django，新增四個 LOCAL_APPS，WSGI + ASGI 並存：

- **`conversations`** — 資料模型（`SceneConfig` / `Conversation` / `Message` / `ModelRoute`）與 Celery 任務 `generate_ai_reply`。不感知 API 或推送層。
- **`ai_providers`** — 純邏輯層（無 model）。封裝「呼叫 AI 生成回覆」能力：`interfaces.py`（`AIProvider` 抽象介面）、`litellm_provider.py`、`simulator.py`、`factory.py`。
- **`api`** — DRF serializers / views / permissions / throttles。跑在既有 WSGI（Gunicorn），同步即可。
- **`realtime`** — Channels consumer、routing、SSE ticket 發放邏輯。只有 SSE 長連線端點跑在 ASGI，`asgi.py` 用 `ProtocolTypeRouter` 依路徑分流（`/sse/...` 走 Channels，其餘走 Django 原生 view）。

```
瀏覽器
  ├─(1) POST /api/conversations/{id}/messages/  ──▶ WSGI ──▶ 同步建立 USER + AI(PENDING) Message
  │                                                          └─▶ 觸發 Celery task generate_ai_reply(ai_message_id)
  ├─(2) POST /api/conversations/{id}/sse-ticket/ ──▶ WSGI ──▶ 發一次性短效 ticket（存 Redis）
  ├─(3) GET  /sse/conversations/{id}/?ticket=xxx ──▶ ASGI Channels consumer
  │                                                  ├─ 驗證 ticket（一次性、TTL）
  │                                                  ├─ group_add(f"conv_{id}")
  │                                                  └─ 查 DB 送初始快照，之後等待 group_send 事件
  └─(4) 其他 REST API（查詢紀錄 / 場景設定）        ──▶ WSGI 一般 view

Celery worker: generate_ai_reply
  └─▶ 依 ModelRoute 建 litellm.Router → 呼叫 provider.generate()
       ├─ 成功 → Message: COMPLETED（含 model_used）
       └─ Router 所有候選皆失敗 → Message: FAILED、Conversation → PENDING_HUMAN
       └─▶ channel_layer.group_send(f"conv_{id}", {...}) 推送給訂閱中的 SSE consumer
```

## 資料合約（DBML，整合版）

```dbml
// 既有表（cookiecutter-django users app），僅列關聯欄位，非本設計異動範圍
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
  model_used varchar [null, note: '成功的 AI Message 才有值，取自 litellm ModelResponse.model']
  metadata jsonb [not null, default: '{}', note: 'token 數等彈性資訊']
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

Table model_routes {
  id uuid [pk]
  scene_id uuid [not null, ref: > scene_configs.id]
  model_name varchar [not null, note: 'litellm 相容模型名稱字串，如 gpt-4o-mini']
  order integer [not null, note: '對應 litellm.Router 的 order：數字越小越優先，同 order 為同一層']
  weight integer [not null, default: 1, note: '對應 litellm.Router 的 weight：同層內加權隨機的相對權重']
  is_enabled boolean [not null, default: true]
  created timestamptz [not null]
  modified timestamptz [not null]

  indexes {
    (scene_id, order, is_enabled) [name: 'idx_model_routes_scene_order']
  }
}
```

**資料模型設計決策（彙整自 spec1/spec4，僅列結論）：**

1. **Conversation + Message 兩層設計**：單則訊息需要獨立狀態機（PENDING → COMPLETED/FAILED），JSONField 或單表無法乾淨表達且有並發寫入 race condition。
2. **UUID 主鍵**：資料經 REST API 曝露給前端，避免連續整數 ID 的 IDOR 枚舉風險。`user_id` 維持既有 integer pk 不變更。
3. **Message 排序 `created` + `id`**：實際查詢模式都是整個 Conversation 一次拉出，不需獨立 sequence 欄位；`id` 作為同微秒的穩定 tie-breaker（YAGNI）。
4. **軟刪除**（`is_deleted`/`deleted_at`）：客服/KM 記錄有稽核合規需求。`Conversation.user`/`scene` 的 `on_delete=PROTECT`；`Message.conversation` 為 `CASCADE`（僅作 DB 層完整性保底）。
5. **全文檢索欄位放 `messages`**：檢索目標是訊息內容，命中後回推 `conversation_id`。填值機制（signal 或 Postgres trigger）留待實作階段。
6. **`ModelRoute` 為結構化關聯表**而非塞進 `default_settings` JSONField：管理人員可在 Admin 直接編輯權重/啟用狀態，可做欄位層級驗證與查詢統計。
7. **`model_used` 為獨立欄位**而非藏在 `metadata`：是權重調整的核心分析依據，需要可查詢、可聚合。
8. **不加 `(scene_id, model_name)` 唯一限制**：允許同一模型出現在不同 order 層（YAGNI，不主動禁止）。

> **風險註記 [B2]：** `order` 是 SQL 保留字。Django ORM 會自動 quote identifier 所以功能正常，但撰寫 raw SQL 或在 psql 除錯時需記得加引號。仍採用此名是為了與 litellm 術語完全對齊，避免自創詞彙（如 `priority`）造成對照成本。

## 高階流程（最終版）

```
使用者發送查詢
      │
      ▼
[API] POST /api/conversations/{id}/messages/（WSGI，同步）
      │
      ├─ Conversation.status 為 CLOSED 或 PENDING_HUMAN → 409（見「併發與狀態控制」）
      ├─ 已存在 PENDING AI Message → 409
      │
      ▼
同一 transaction 內同步建立兩筆 Message：
  - USER Message(status=COMPLETED, content=<查詢內容>)
  - AI  Message(status=PENDING, content="")
      │
      ▼
觸發 Celery task：generate_ai_reply(ai_message_id)
      │
      ▼ [回應前端 202，回傳 user/ai message id；前端可換 ticket 建 SSE 連線]
      │
      ▼ (非同步背景執行)
task：transaction 內 SELECT ... FOR UPDATE 鎖定 AI Message
      ├─ status != PENDING → 直接 return（idempotency guard）
      ▼
反查 conversation，查歷史訊息：
  conversation.messages.exclude(id=ai_message_id)
                       .filter(status="completed")   ← 防禦性過濾
                       .order_by("created", "id")
      ▼
factory.get_provider(conversation.scene)
  └─ 從 ModelRoute（is_enabled=True）即時組出 litellm.Router
      ▼
provider.generate(messages=<歷史+查詢>, timeout=30)   ← 同步呼叫 [修正 A1]
      │
      ├─ 成功（Router 內部可能已 failover 過若干候選）
      │    → AI Message: status=COMPLETED, content=<回覆>,
      │       model_used=response.model, metadata={tokens...}
      │
      └─ Router 所有候選皆失敗、拋出例外
           → AI Message: status=FAILED, error_message=<原因>
           → Conversation.status = PENDING_HUMAN
      ▼
channel_layer.group_send(f"conv_{id}",
  {"message_id", "status", "content" 或 "error_message"})
```

## AI 呼叫抽象層（最終版）

### `AIProvider` 介面

方法命名貼近 liteLLM / OpenAI SDK 慣例（非 LangChain `invoke` 系列）。選模資訊在**建構 provider 時**由 `ModelRoute` 資料決定，方法簽名不帶 `model` 參數：

- `generate(messages, **kwargs)` — 同步生成（**Celery task 呼叫此方法** [修正 A1]）
- `agenerate(messages, **kwargs)` — 非同步生成（供未來 ASGI 情境使用）
- `stream(messages, **kwargs)` / `astream(messages, **kwargs)` — 串流（定義介面，暫不實作使用場景）
- `batch_generate(messages_list, **kwargs)` — 批次（同上）

> **[修正 A1] 為何 Celery task 用同步 `generate()`：** Celery task 是同步函式，原 spec2/spec4 設計呼叫 `agenerate` 需要 `asyncio.run()` 包裝，而 task 一次只處理一則訊息、無並發 IO 需求，async 沒有實際收益。同步版直接呼叫 `router.completion(...)`，最簡單正確。`agenerate` 保留在介面供未來（如 ASGI 內直接呼叫）使用。

### `LiteLLMProvider`

```python
class LiteLLMProvider(AIProvider):
    def __init__(self, router: litellm.Router, model_group: str):
        self._router = router
        self._model_group = model_group

    def generate(self, messages: list[dict], **kwargs) -> ModelResponse:
        return self._router.completion(model=self._model_group, messages=messages, **kwargs)
```

### `DelayedFailureSimulator` [修正 A2]

本次作業以模擬替身取代真實 API 呼叫（無真實 API key，`AI_BACKEND` 預設 `simulator`）。在 Router 架構下的模擬方式明確定義為：

- 與 `LiteLLMProvider` 相同建構參數（`router`, `model_group`），走**同一個 `router.completion()` 呼叫路徑**，但一律額外帶 `mock_response=...` 參數——liteLLM 原生支援 `mock_response` 且 Router 會透傳給底層 completion，保證回傳結構（`ModelResponse`）與真實呼叫完全一致，且**絕不會真的打外部 API**。
- 人工延遲：每次呼叫前 `time.sleep(random.uniform(lo, hi))`（範圍可設定，預設 1~3 秒）。
- 失敗模擬兩種模式，皆透過建構子參數/設定注入：
  - **全域失敗機率**（預設 10%）：擲中時改帶 `mock_response=Exception(...)`，litellm 會將其轉為拋出例外，觸發 Router failover 或最終失敗路徑。
  - **指定候選必敗清單**（`fail_models: set[str]`，預設空）：供 failover 整合測試使用——模擬「特定 model_name 的候選必定失敗」，驗證 Router 確實換到下一個候選、且 `model_used` 記錄的是最終成功的模型。
- **實作註記：** 若實測發現 Router 對 `mock_response` 的透傳行為與預期不符（例如 failover 路徑上無法逐候選注入不同結果），fallback 方案是 simulator 不經過真實 Router，改為在 simulator 內部依 `ModelRoute` 資料自行走「逐候選嘗試」的等價邏輯、每一步用 `litellm.completion(mock_response=...)` 產生回應。此為實作階段驗證點，不影響介面簽名。

### `factory.get_provider(scene)`

```python
def get_provider(scene) -> AIProvider:
    routes = scene.model_routes.filter(is_enabled=True)
    model_group = f"scene-{scene.id}"
    model_list = [
        {
            "model_name": model_group,
            "litellm_params": {"model": r.model_name},
            "order": r.order,
            "weight": r.weight,
        }
        for r in routes
    ]
    router = litellm.Router(model_list=model_list, enable_weighted_failover=True)
    if settings.AI_BACKEND == "litellm":
        return LiteLLMProvider(router, model_group)
    return DelayedFailureSimulator(router, model_group)
```

- `AI_BACKEND`（`litellm` | `simulator`）為環境層級全域設定，不放 `SceneConfig`（業務設定與後端串接細節分離）。
- **Router 重建策略：** 每次 task 執行時即時從 `ModelRoute` 重建 Router（輕量物件，建構成本低），管理人員在 Admin 改權重後下一次 task 即生效，不需 cache 失效機制。流量大時可加短 TTL cache，列入未來擴充。

> **風險註記 [B3]：** `enable_weighted_failover` 與 `order`/`weight` 的組合行為是依 liteLLM 官方文件與原始碼研究得出，**未在本專案實際執行驗證**（含「同層只剩一個候選」等 edge case）。若實作時發現實際參數名或行為不同（例如需改用 `routing_strategy` + `fallbacks` 組合），選模語意（分層優先度 + 層內加權隨機 + 跨層 fallback）維持不變，僅調整 Router 設定寫法，不影響資料模型與介面設計。

### 失敗處理（Router 為唯一容錯層）

- Router 預設行為：同層某候選失敗 → 立即換同層下一個候選；同層試完 → fallback 到下一個 order 層；**所有已啟用候選都試過仍失敗**才拋出例外。
- 不設 per-deployment `retry_policy`（一失敗就換候選，最貼近套件開箱行為）。
- 不設程式層級的 fallback 層數上限——候選層數由管理人員透過 `ModelRoute` 筆數決定。
- **不使用 Celery `autoretry`**：Router 已試遍所有候選，整流程重跑對系統性故障（API 本身掛掉）無幫助，只拉長延遲。task 捕捉例外即判定 `FAILED`、Conversation 轉 `PENDING_HUMAN`。

## Celery 任務設計

- **任務簽名：** `generate_ai_reply(ai_message_id)`。只傳 primitive ID：ORM 物件不可序列化；執行時才查 DB 保證資料新鮮。不傳 `conversation_id`——同 Conversation 若存在多筆 PENDING AI Message（規則被違反時）將無法定位目標。
- **併發安全（idempotency guard）：** task 開始時 transaction 內 `select_for_update()` 鎖定 AI Message 並檢查 `status`，非 `PENDING` 直接 return，防重複排程與多 worker 競態。
- **歷史查詢防禦性過濾：** 強制 `filter(status="completed")`——不論業務規則是否被違反，未完成/失敗訊息永不進入 LLM context。
- **timeout：** 每次呼叫帶明確 timeout（例如 30 秒），由 Router/litellm 層處理。

## API 設計

### 認證與授權（RBAC）

採 Django 內建 Group + Permission（不自訂 role 欄位——Admin 原生用這套權限系統，未來加細粒度權限不需改 schema）：

| 角色 | 實現方式 | 權限範圍 |
|---|---|---|
| 一般使用者 | 已登入 `users.User`，無特殊 Group | 只能讀寫自己的 Conversation/Message；`GET /api/scenes/` 唯讀 |
| 客服人員 | `customer_service` Group | 檢視所屬場景（`scene_type=customer_service`）全部 Conversation；Admin 內只能改 `Conversation.status` |
| 管理者 | `is_superuser` 或 `admin` Group | 讀寫 SceneConfig；檢視/調整任何 Conversation.status |

### Endpoint 清單

| Endpoint | 方法 | 用途 | 權限 / 備註 |
|---|---|---|---|
| `/api/conversations/` | POST | 建立新對話（指定 `scene`） | 已登入使用者 |
| `/api/conversations/` | GET | 列表（cursor 分頁、`scene`/`status`/時間區間過濾、`?q=` 全文檢索） | 一般使用者只看自己的；客服看所屬場景全部 |
| `/api/conversations/{id}/messages/` | POST | 提交查詢 | 對話所有者；DRF throttling；狀態檢查見下 |
| `/api/conversations/{id}/messages/` | GET | 對話內訊息列表（cursor 分頁） | 同 Conversation 權限 |
| `/api/messages/{id}/` | GET | 單筆訊息狀態（SSE 初始快照 / SSE 不可用時的輪詢 fallback） | 同 Conversation 權限 |
| `/api/conversations/{id}/sse-ticket/` | POST | 換發一次性短效 SSE ticket | 同 Conversation 權限 |
| `/sse/conversations/{id}/` | GET (SSE) | 訂閱 AI 回覆狀態事件 | 帶有效 ticket |
| `/api/scenes/` | GET | 場景列表（建立對話時選擇用） | 已登入使用者；**一般使用者的 serializer 只回傳 `id`/`name`/`scene_type`**，不曝露 `default_settings`（內含模型設定等內部資訊）；管理者可見完整欄位 |
| `/api/scenes/` | POST | 建立場景設定 | 管理者 |
| `/api/scenes/{id}/` | PATCH | 更新場景設定 | 管理者；不記修改歷程（PRD 未要求，未來可引入 `django-simple-history` 不影響介面） |

### 併發與狀態控制 [修正 B1]

提交查詢（`POST /api/conversations/{id}/messages/`）在**同一個 DB transaction 內**依序檢查並建立資料，任一檢查不過即回 `409 Conflict`（不建立資料、不觸發任務），response body 帶機器可判別的 `code` 與人類可讀訊息：

| 檢查 | 409 `code` | 理由 |
|---|---|---|
| `Conversation.status == CLOSED` | `conversation_closed` | 已關閉的對話不應再觸發 AI 生成 |
| `Conversation.status == PENDING_HUMAN` | `pending_human` | 已轉真人處理，AI 不應繼續介入；待客服在 Admin 將狀態改回 `OPEN` 後方可續問 |
| 存在 `status=PENDING` 的 AI Message | `reply_in_progress` | 一次只能一則 PENDING（enforce 點在此 API 層；spec2 的歷史過濾為第二道防線） |

### 效能與流量控制

- **提交查詢加 DRF throttling**（`UserRateThrottle`，每使用者每分鐘上限 N 次）：每次提交觸發外部 AI 呼叫（金錢成本、佔用 worker），防帳單暴增與隊列堵塞。
- **cursor-based pagination**（基於 `created`/`id`）：資料只增不改，避免 offset 分頁的重複/遺漏，效能不隨頁深下降。
- **全文檢索**：`?q=` 轉 `SearchQuery` 比對 `search_vector`（GIN index）。中文分詞支援度（Postgres 預設 config 對中文有限）留待實作階段驗證。

## 即時推送（SSE + Channels）

- **為何不用輪詢：** 延遲與請求量難兩全；伺服器主動推送讓使用者在生成完成瞬間看到結果。`GET /api/messages/{id}/` 保留作 fallback。
- **路由用 Channels group**（每個 Conversation 一個 group `conv_{id}`，底層 Redis sorted set）：沒人訂閱時 `group_send` 為 no-op；天生支援多 consumer instance 水平擴展，不需應用層維護連線對應表。排除「單一固定 channel + payload 手動過濾」方案（廣播浪費、未解決多 instance 路由）。
- **身份驗證（一次性 ticket）：** 瀏覽器 `EventSource` 不支援自訂 header → 前端先以正常認證呼叫 ticket API，取得短 TTL（60 秒）、綁定 `user_id`+`conversation_id` 的一次性 ticket（存 Redis），放在 SSE URL query param。Consumer `connect()` 時驗證並**原子性地取出即刪**（實作用 `GETDEL` 或 Lua script，避免驗證與刪除間的 race condition），再走一般 Conversation 權限檢查。
- **初始快照時序（避免漏接）：** `connect()` 固定順序 = 先 `group_add` → 再查 DB 送初始快照 → 進入等待迴圈。保證 task 無論何時完成，最終狀態不漏接。
- **推送範圍：** 只推 Message 層級狀態（`completed`/`failed`，payload 含 `message_id`、`status`、`content` 或 `error_message`）。`Conversation.status → PENDING_HUMAN` 不推送——那是給客服/管理者的內部分派旗標，使用者已由 `failed` 事件得知結果，兩種受眾不混流。
- **已知未定案：** SSE 斷線後的重連策略（重新換票流程、`EventSource` 自動重連會帶已用過的 ticket 而失敗）留待實作階段設計；輪詢 fallback API 已保證功能不中斷。

## Django Admin 管理介面

- `ConversationAdmin`：`list_display`（使用者、場景、狀態、建立時間）、`list_filter`（`scene`、`status`）、inline 唯讀顯示 Message 列表。
- `MessageAdmin`：`list_display`、全文檢索 `search_fields`、`readonly_fields` 涵蓋 `content`/`metadata`/`error_message`/`model_used`（訊息不可變）。
- `SceneConfigAdmin`：`ModelRoute` 以 `TabularInline` 掛在編輯頁（`model_name`/`order`/`weight`/`is_enabled`），管理人員直接調整路由，儲存即生效（下次 task 重建 Router 時讀到）。`ModelRoute` 不另開 DRF API（目前唯一情境是後台手動操作）。
- 客服人員經 Permission 限制：只見所屬場景 Conversation、只能修改 `Conversation.status`（如 `PENDING_HUMAN` → `OPEN`/`CLOSED`），訊息內容不可編輯（稽核完整性）。

## 錯誤處理總覽

| 情境 | 處理 |
|---|---|
| 對 CLOSED / PENDING_HUMAN 對話提交查詢 | `409`（code: `conversation_closed` / `pending_human`） |
| 對已有 PENDING AI Message 的對話提交查詢 | `409`（code: `reply_in_progress`） |
| 提交頻率超限 | `429`（DRF throttling） |
| SSE ticket 不存在/過期/已使用 | consumer 拒絕連線（`close()`） |
| Router 所有候選模型皆失敗 | Message → `FAILED`（SSE 推送 `failed` + `error_message`）；Conversation → `PENDING_HUMAN`（不推送） |
| 存取他人 Conversation | `403` |
| AI Message 已非 PENDING 時 task 重複執行 | idempotency guard 直接 return，無副作用 |

## 已知風險與未驗證假設（實作階段驗證清單）

1. **[B3]** `litellm.Router` 的 `enable_weighted_failover` / `order` / `weight` 行為未實測（含同層單一候選 edge case、動態重建的初始化成本）。語意不變、僅設定寫法可能需調整。
2. **[A2]** Router 對 `mock_response` 的透傳行為未實測；已定義 fallback 方案（simulator 內部自行走等價逐候選邏輯）。
3. **[B2]** `ModelRoute.order` 為 SQL 保留字，raw SQL 需 quote。
4. Postgres 全文檢索對中文分詞支援有限，`search_vector` 的 config 選擇留待實作。
5. SSE 斷線重連策略未定案（有輪詢 fallback 保底）。
6. `TimeStampedModel`（django-model-utils）在本專案尚未實際使用過，整合方式未驗證。
7. Channels group 高並發連線表現未壓測。

## 測試考量（彙整）

- **Model 層**：預設值、狀態轉換、軟刪除排除（自訂 Manager）、全文檢索中英文命中。
- **`ai_providers` 層**：`factory` 依 `ModelRoute` 正確組 `model_list`（order/weight 對應）；simulator 回傳結構與 `LiteLLMProvider` 一致、失敗機率統計符合設定、延遲落在範圍、`fail_models` 指定候選必敗生效。
- **Celery task 層**：idempotency guard、歷史過濾（混入 PENDING/FAILED 不進 context）、成功路徑（content/metadata/model_used 正確）、全部候選失敗路徑（FAILED + PENDING_HUMAN、不整流程重試）。
- **Failover**：指定候選必敗 → 驗證換到下一候選、`model_used` 為最終成功模型；`FAILED` 訊息 `model_used` 為 null。
- **API 層**：權限矩陣（三角色 × 各 endpoint，含跨使用者 403）；三種 409（closed / pending_human / reply_in_progress）與併發提交只有一個成功；429 throttling；一般使用者的 scenes serializer 不含 `default_settings`。
- **SSE**：`ApplicationCommunicator` 測 `group_add`、初始快照、`group_send` 轉發；ticket 一次性與 TTL 過期。
- **Admin**：inline 改權重後下次 task 讀到最新設定（「即時生效」假設）。

## 未來擴充摘要

| 項目 | 現況 | 擴充方式 |
|---|---|---|
| 外部終端使用者（訪客/LINE） | 未實作 | 「影子帳號」：新增 `ExternalIdentity(user FK, channel, external_id)`，`Conversation.user` 不變 |
| 回覆模板路由 | 未設計（PRD 附加挑戰提及） | 範圍與模型路由不同，另立需求 |
| Router 效能 | 每次 task 即時重建 | 短 TTL cache（同 Scene 60 秒共用實例） |
| `model_group` 命名 | `scene-{id}` 一對一綁定 | 多 Scene 共用路由設定時需重設計對應 |
| ModelRoute 程式化調整 | 僅 Admin inline | 於場景設定 API 上擴充 |
| SceneConfig 修改歷程 | 不記錄 | `django-simple-history`，不影響介面 |
| 訊息取消/重新編輯 | 不支援（immutable 假設） | 全新需求，需重評歷史查詢與 SSE 事件語意 |
| 串流回覆 | 介面已留 `stream`/`astream` | 需改為 SSE/WebSocket 逐 token 推送 |
| 高並發 SSE | 未壓測 | 壓測 Redis channel layer |
