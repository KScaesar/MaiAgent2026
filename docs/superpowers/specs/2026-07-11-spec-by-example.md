# Specification by Example — Gen AI 自動回覆平台後端系統

**日期：** 2026-07-11
**依據：** [2026-07-10-final-design.md](2026-07-10-final-design.md)（整合版設計文件）、[prd.md](../../../prd.md)
**目的：** 將設計文件中的抽象規則轉化為具體、可獨立閱讀的情境範例，供開發、測試、PO 三方對齊理解。本文件不重複設計文件的架構說明，只聚焦「規則 → 具體情境 → 預期結果」。

---

## 功能一：提交查詢與對話狀態控制

```
功能：提交查詢（POST /api/conversations/{id}/messages/）
作為：已登入使用者
我想要：對我的對話提交一則查詢
以便於：取得 AI 自動生成的回覆
```

### 規則摘要

- R1：對話狀態為 `CLOSED` 時，禁止提交，回 409 `conversation_closed`。
- R2：對話狀態為 `PENDING_HUMAN` 時，禁止提交，回 409 `pending_human`；需客服在 Admin 將狀態改回 `OPEN` 才能再提交。
- R3：對話內已存在 `status=PENDING` 的 AI Message 時，禁止提交，回 409 `reply_in_progress`（一次只能有一則生成中的回覆）。
- R4：檢查與建立資料（USER Message + AI Message PENDING）在同一個 DB transaction 內完成；任一檢查不過 → 不建立任何資料、不觸發 Celery task。
- R5：成功提交 → 回 202，並回傳 `user_message_id` 與 `ai_message_id`。
- R6：僅對話擁有者可提交；存取他人對話回 403。
- R7：提交頻率受 DRF throttling 限制，超過回 429。

### Examples 表格

| # | 情境類型 | Given（前置條件） | When（操作） | Then（預期結果） |
|---|---|---|---|---|
| 1 | Happy Path | 對話狀態 `OPEN`，無 PENDING AI Message | 使用者提交查詢「你好」 | 202；建立 USER(COMPLETED) + AI(PENDING) 兩筆 Message；觸發 `generate_ai_reply` task |
| 2 | Negative | 對話狀態 `CLOSED` | 使用者提交查詢 | 409，`code=conversation_closed`；不建立任何 Message；不觸發 task |
| 3 | Negative | 對話狀態 `PENDING_HUMAN` | 使用者提交查詢 | 409，`code=pending_human`；不建立任何 Message |
| 4 | Negative | 對話狀態 `OPEN`，但已有一則 AI Message `status=PENDING` | 使用者再次提交查詢 | 409，`code=reply_in_progress`；不建立新 Message |
| 5 | Edge Case（併發） | 對話狀態 `OPEN`，無 PENDING Message | 兩個請求「同時」對同一對話提交查詢 | 僅一個請求成功建立 Message 並觸發 task；另一個因 transaction 內狀態已變為 `reply_in_progress` 而收到 409 |
| 6 | Negative（權限） | 對話屬於使用者 A | 使用者 B 對該對話提交查詢 | 403 |
| 7 | Negative（流量） | 使用者於一分鐘內已提交達上限次數 N | 使用者再次提交 | 429 |
| 8 | Edge Case | 對話狀態 `PENDING_HUMAN`，客服已在 Admin 將狀態改回 `OPEN` | 使用者提交查詢 | 202；正常走 Happy Path 流程 |

### Given-When-Then

```gherkin
Scenario: 對已關閉的對話提交查詢應被拒絕
  Given 對話 "conv-1" 狀態為 CLOSED
  When  使用者對 "conv-1" 提交查詢 "還在嗎？"
  Then  回應為 409 Conflict
  And   回應 body 的 code 為 "conversation_closed"
  And   資料庫未新增任何 Message
  And   未觸發 generate_ai_reply task

Scenario: 對已轉真人處理的對話提交查詢應被拒絕
  Given 對話 "conv-2" 狀態為 PENDING_HUMAN
  When  使用者對 "conv-2" 提交查詢
  Then  回應為 409 Conflict，code 為 "pending_human"

Scenario: 同一對話已有生成中的回覆時應被拒絕
  Given 對話 "conv-3" 狀態為 OPEN
  And   對話內存在一則 AI Message，status = PENDING
  When  使用者對 "conv-3" 再次提交查詢
  Then  回應為 409 Conflict，code 為 "reply_in_progress"

Scenario: 併發提交同一對話僅一則成功
  Given 對話 "conv-4" 狀態為 OPEN，無 PENDING AI Message
  When  兩個請求幾乎同時對 "conv-4" 提交查詢
  Then  恰好一個請求回傳 202 並建立 Message
  And   另一個請求回傳 409（code = "reply_in_progress"）

Scenario: 提交查詢成功建立訊息並觸發生成任務
  Given 對話 "conv-5" 狀態為 OPEN，無 PENDING AI Message
  When  使用者提交查詢 "產品退貨流程是什麼？"
  Then  回應為 202
  And   回應包含 user_message_id 與 ai_message_id
  And   新建立的 USER Message status 為 COMPLETED，content 為查詢內容
  And   新建立的 AI Message status 為 PENDING，content 為空字串
  And   generate_ai_reply(ai_message_id) 被排入 Celery 佇列
```

---

## 功能二：AI 自動回覆生成（Celery Task）

```
功能：generate_ai_reply(ai_message_id)
作為：系統（Celery worker）
我想要：依場景設定呼叫 AI 產生回覆並更新訊息狀態
以便於：使用者查詢能得到自動回覆，失敗時能轉交真人
```

### 規則摘要

- R1：task 開始時以 `select_for_update()` 鎖定 AI Message；若 `status != PENDING`，直接 return（idempotency guard，無副作用）。
- R2：歷史訊息查詢強制 `filter(status="completed")`，排除該對話內任何 PENDING/FAILED 訊息，不論業務規則是否被違反。
- R3：呼叫 `provider.generate()` 成功 → AI Message 更新為 `COMPLETED`，寫入 `content`、`model_used`、`metadata`。
- R4：Router 所有候選模型皆失敗 → AI Message 更新為 `FAILED`（`model_used` 為 null），寫入 `error_message`；Conversation 狀態轉為 `PENDING_HUMAN`。
- R5：不論成功或失敗，皆透過 `channel_layer.group_send` 推送 Message 層級事件；`PENDING_HUMAN` 狀態轉換本身不推送。
- R6：不使用 Celery autoretry；Router 已試遍所有候選，整流程重跑無意義。

### Examples 表格

| # | 情境類型 | Given | When | Then |
|---|---|---|---|---|
| 1 | Happy Path | AI Message status=PENDING；Router 第一候選即成功 | task 執行 | Message → COMPLETED；`model_used` = 該候選模型名；SSE 推送 `completed` 事件 |
| 2 | Happy Path（Failover） | ModelRoute 設定兩層候選，`fail_models` 指定第一層候選必敗 | task 執行 | Router 換至下一候選成功；`model_used` 為最終成功的模型名，非第一層 |
| 3 | Negative | 所有已啟用候選皆失敗（模擬全域失敗機率擲中或 `fail_models` 涵蓋全部） | task 執行 | Message → FAILED，`model_used` 為 null，`error_message` 有值；Conversation → PENDING_HUMAN |
| 4 | Edge Case（Idempotency） | AI Message 已被前一次 task 執行更新為 COMPLETED | 同一 task 因訊息重複投遞被再次執行 | task 於 select_for_update 後發現 status != PENDING，直接 return，無任何欄位被覆寫 |
| 5 | Edge Case（防禦性過濾） | 對話內混有其他 PENDING 或 FAILED 的舊訊息（規則被違反的情形） | task 查詢歷史訊息 | 傳給 AI 的 messages 列表不包含這些 PENDING/FAILED 訊息 |
| 6 | Edge Case | Scene 的 ModelRoute 全數 `is_enabled=False` | task 執行 | Router 無可用候選，呼叫立即失敗 → 依規則 3 走 FAILED + PENDING_HUMAN |

### Given-When-Then

```gherkin
Scenario: AI 生成成功更新訊息並推送事件
  Given AI Message "msg-1" status 為 PENDING
  And   Scene 的 ModelRoute 只有一個啟用中的候選 "gpt-4o-mini"
  When  generate_ai_reply("msg-1") 執行
  Then  "msg-1" status 變為 COMPLETED
  And   "msg-1".model_used 為 "gpt-4o-mini"
  And   "msg-1".content 為 AI 回覆內容
  And   conv_{id} group 收到 {message_id: "msg-1", status: "completed", content: ...}

Scenario: 第一層候選失敗時應 failover 至下一候選
  Given ModelRoute 設定：order=0 的 "model-a"、order=1 的 "model-b"，皆啟用
  And   simulator 設定 fail_models = {"model-a"}
  When  generate_ai_reply("msg-2") 執行
  Then  "msg-2" status 變為 COMPLETED
  And   "msg-2".model_used 為 "model-b"（而非 "model-a"）

Scenario: 所有候選皆失敗時訊息轉為 FAILED 且對話轉真人
  Given ModelRoute 所有啟用候選皆會失敗
  When  generate_ai_reply("msg-3") 執行
  Then  "msg-3" status 變為 FAILED
  And   "msg-3".model_used 為 null
  And   "msg-3".error_message 有值
  And   所屬 Conversation.status 變為 PENDING_HUMAN
  And   conv_{id} group 收到 {message_id: "msg-3", status: "failed", error_message: ...}
  And   Conversation 狀態轉換本身未觸發任何 SSE 推送

Scenario: 已完成的訊息重複執行 task 不產生副作用
  Given AI Message "msg-4" status 已為 COMPLETED
  When  generate_ai_reply("msg-4") 被重複呼叫一次
  Then  "msg-4" 的所有欄位維持不變
  And   不會再次呼叫 AI provider
  And   不會再次推送 SSE 事件

Scenario: 歷史查詢排除未完成訊息
  Given 對話內有訊息序列：USER(COMPLETED) → AI(FAILED) → USER(COMPLETED) → AI(PENDING, 目標訊息)
  When  generate_ai_reply(目標訊息 id) 查詢歷史訊息
  Then  傳給 AI 的 messages 只包含兩則 COMPLETED 的 USER 訊息
  And   不包含該筆 FAILED 的 AI 訊息
```

---

## 功能三：模擬 AI 呼叫（DelayedFailureSimulator）

```
功能：DelayedFailureSimulator
作為：開發/測試者
我想要：在沒有真實 API key 的情況下模擬 AI 呼叫的延遲與失敗
以便於：驗證 Celery task 與 Router failover 邏輯的正確性
```

### 規則摘要

- R1：一律透過 `router.completion(mock_response=...)`，絕不觸發真實外部 API 呼叫。
- R2：每次呼叫前有隨機延遲（預設 1~3 秒）。
- R3：全域失敗機率（預設 10%）擲中時，該次呼叫改帶 `mock_response=Exception(...)`。
- R4：`fail_models` 清單內的候選一定失敗，供 failover 測試使用。
- R5：回傳結構（`ModelResponse`）與 `LiteLLMProvider` 完全一致。

### Examples 表格

| # | 情境類型 | Given | When | Then |
|---|---|---|---|---|
| 1 | Happy Path | `fail_models` 為空，全域失敗機率設為 0 | 呼叫 `generate()` | 恆定成功，回傳 `ModelResponse`，延遲落在 1~3 秒範圍 |
| 2 | Edge Case | 全域失敗機率設為 100% | 呼叫 `generate()` | 恆定拋出例外（透過 mock_response=Exception 觸發） |
| 3 | Edge Case | `fail_models = {"model-a"}`，候選只有 "model-a" 一個（同層單一候選） | 呼叫 `generate()` | Router 無其他候選可 failover，整體呼叫失敗 |
| 4 | Negative | 統計大量呼叫下的失敗次數 | 觀察 1000 次呼叫結果 | 失敗比例應接近設定的全域失敗機率（容許統計誤差） |

### Given-When-Then

```gherkin
Scenario: 模擬呼叫不觸發真實外部 API
  Given AI_BACKEND 設定為 "simulator"
  When  provider.generate() 被呼叫
  Then  底層呼叫帶有 mock_response 參數
  And   沒有任何真實網路請求送往外部 AI 服務端點

Scenario: 指定候選必敗時觸發同層無候選可用的失敗
  Given ModelRoute 同一層（同 order）只有一個候選 "model-a"
  And   simulator 設定 fail_models = {"model-a"}
  When  provider.generate() 被呼叫
  Then  該次呼叫最終拋出例外（無其他同層候選可切換）
```

---

## 功能四：API 權限矩陣（RBAC）

```
功能：對話與訊息的存取控制
作為：一般使用者 / 客服人員 / 管理者
我想要：依角色限制可存取的資料範圍
以便於：保護使用者隱私並讓客服/管理者能監控與調整
```

### 規則摘要

- R1：一般使用者只能讀寫「自己的」Conversation/Message。
- R2：客服人員（`customer_service` Group）可檢視所屬場景（`scene_type=customer_service`）全部 Conversation；在 Admin 只能改 `Conversation.status`。
- R3：管理者（`is_superuser` 或 `admin` Group）可讀寫 SceneConfig，並可檢視/調整任何 Conversation.status。
- R4：`GET /api/scenes/` 一般使用者只回傳 `id`/`name`/`scene_type`，不含 `default_settings`；管理者可見完整欄位。
- R5：存取他人 Conversation 一律 403。

### Examples 表格

| # | 角色 | Endpoint | 情境 | 預期結果 |
|---|---|---|---|---|
| 1 | 一般使用者 | `GET /api/conversations/{id}/` | 存取自己的對話 | 200，正常回傳 |
| 2 | 一般使用者 | `GET /api/conversations/{id}/` | 存取他人的對話 | 403 |
| 3 | 一般使用者 | `GET /api/scenes/` | 任一情境 | 200，欄位只含 `id`/`name`/`scene_type` |
| 4 | 客服人員 | `GET /api/conversations/?scene=customer_service_scene_id` | 所屬客服場景，非自己建立的對話 | 200，可見清單中的所有對話 |
| 5 | 客服人員 | `PATCH` Django Admin 上的 `Conversation.content` | 嘗試修改訊息內容 | 被拒絕（欄位唯讀，稽核完整性） |
| 6 | 客服人員 | Django Admin 上的 `Conversation.status` | 將 `PENDING_HUMAN` 改為 `OPEN` | 成功；下次使用者提交查詢恢復正常流程 |
| 7 | 管理者 | `POST /api/scenes/` | 建立新場景設定 | 201 |
| 8 | 一般使用者 | `POST /api/scenes/` | 嘗試建立場景設定 | 403 |
| 9 | 管理者 | `GET /api/scenes/` | 任一情境 | 200，欄位含完整 `default_settings` |

### Given-When-Then

```gherkin
Scenario: 一般使用者無法存取他人對話
  Given 對話 "conv-9" 屬於使用者 A
  When  使用者 B 呼叫 GET /api/conversations/conv-9/
  Then  回應為 403

Scenario: 一般使用者的場景列表不曝露內部設定
  Given 使用者為一般使用者（無特殊 Group）
  When  呼叫 GET /api/scenes/
  Then  回應 200
  And   回傳的每個場景物件只含 id、name、scene_type
  And   不含 default_settings 欄位

Scenario: 客服人員可檢視所屬場景的全部對話
  Given 客服人員屬於 customer_service Group
  And   場景 "cs-scene-1" 的 scene_type 為 customer_service
  And   該場景下存在多筆不同使用者建立的對話
  When  客服人員呼叫 GET /api/conversations/?scene=cs-scene-1
  Then  回應 200，清單包含所有使用者在該場景下的對話

Scenario: 客服人員將對話轉回 OPEN 後使用者可繼續提問
  Given 對話 "conv-10" 狀態為 PENDING_HUMAN
  When  客服人員在 Django Admin 將 "conv-10" 狀態改為 OPEN
  And   對話擁有者提交新查詢
  Then  提交成功，回應 202（不再回 409 pending_human）
```

---

## 功能五：全文檢索（?q=）

```
功能：對話/訊息全文檢索
作為：客服/管理者
我想要：以關鍵字搜尋歷史訊息內容
以便於：快速找到特定對話紀錄
```

### 規則摘要

- R1：`?q=` 轉換為 `SearchQuery`，比對 `messages.search_vector`（GIN index）。
- R2：搜尋結果命中訊息後回推對應的 `conversation_id`。
- R3：搜尋範圍仍受權限矩陣限制（一般使用者只搜自己的對話）。

### Examples 表格

| # | 情境類型 | Given | When | Then |
|---|---|---|---|---|
| 1 | Happy Path | 使用者對話內某訊息 content 含「退貨」 | `GET /api/conversations/?q=退貨` | 回傳包含該對話的清單 |
| 2 | Edge Case | 關鍵字不存在於任何訊息 | `GET /api/conversations/?q=不存在的詞` | 回傳空清單，200 |
| 3 | Negative（權限） | 關鍵字命中他人對話內的訊息 | 一般使用者以該關鍵字搜尋 | 結果不包含他人對話（權限過濾優先於搜尋） |
| 4 | Edge Case（中文分詞，待驗證） | 訊息含中文長句「請問退貨流程為何」 | 以子詞「退貨流程」搜尋 | 命中或未命中依 Postgres 分詞設定而定 —— 見 Open Questions |

### Given-When-Then

```gherkin
Scenario: 依關鍵字搜尋命中歷史對話
  Given 使用者的對話 "conv-11" 內有一則訊息 content 為 "請協助退貨"
  When  使用者呼叫 GET /api/conversations/?q=退貨
  Then  回應 200，清單包含 "conv-11"

Scenario: 搜尋結果不含他人對話
  Given 使用者 A 的對話 "conv-12" 內含關鍵字 "退貨"
  And   使用者 B 的對話中無此關鍵字
  When  使用者 B 呼叫 GET /api/conversations/?q=退貨
  Then  回應 200，清單為空（不因關鍵字命中他人資料而洩漏）
```

---

## 功能六：SSE 即時推送

```
功能：訂閱 AI 回覆狀態（SSE）
作為：已登入使用者
我想要：即時收到 AI 回覆完成或失敗的通知
以便於：不需輪詢即可獲得結果
```

### 規則摘要

- R1：需先呼叫 `POST /sse-ticket/` 取得一次性、短 TTL（60 秒）、綁定 `user_id`+`conversation_id` 的 ticket。
- R2：Ticket 使用後即失效（原子性取出即刪）；不存在/過期/已使用皆拒絕連線。
- R3：`connect()` 順序固定：先 `group_add` → 查 DB 送初始快照 → 進入等待迴圈（避免漏接）。
- R4：只推送 Message 層級事件（`completed`/`failed`）；`PENDING_HUMAN` 狀態轉換不推送。

### Examples 表格

| # | 情境類型 | Given | When | Then |
|---|---|---|---|---|
| 1 | Happy Path | 使用者換得有效 ticket | 帶 ticket 連線 SSE endpoint | 連線成功，收到初始快照，之後收到 task 完成事件 |
| 2 | Negative | ticket 已被使用過一次 | 再次用同一 ticket 連線 | 連線被拒絕（`close()`） |
| 3 | Negative | ticket 已超過 60 秒 TTL | 用該 ticket 連線 | 連線被拒絕 |
| 4 | Edge Case（時序） | 使用者連線 SSE 前，task 已經完成生成 | 使用者稍後才連上 SSE | 仍能透過初始快照得知最終狀態（不漏接） |
| 5 | Edge Case | AI 生成失敗，Conversation 轉 PENDING_HUMAN | task 完成 | SSE 只推送 `failed` 事件；不會推送任何 PENDING_HUMAN 相關訊息 |

### Given-When-Then

```gherkin
Scenario: 一次性 ticket 使用後即失效
  Given 使用者已取得 SSE ticket "ticket-1"
  When  使用者用 "ticket-1" 成功連線一次
  And   同一使用者再次用 "ticket-1" 連線
  Then  第二次連線被拒絕

Scenario: 連線前任務已完成仍可透過初始快照得知結果
  Given AI Message "msg-5" 已於使用者連線前完成生成（status=COMPLETED）
  When  使用者取得新 ticket 並連線 SSE endpoint
  Then  連線建立後立即收到初始快照事件，內容反映 "msg-5" 的最新狀態

Scenario: 失敗事件推送不包含內部分派旗標
  Given AI Message "msg-6" 生成失敗，Conversation 轉為 PENDING_HUMAN
  When  使用者透過 SSE 訂閱該對話
  Then  使用者收到 {message_id: "msg-6", status: "failed", error_message: ...}
  And   使用者未收到任何提及 Conversation.status 或 PENDING_HUMAN 的事件
```

---

## 待釐清問題（Open Questions）

1. **併發提交的鎖定策略**：R1 的 409 檢查與 Message 建立在同一 transaction 內，但「檢查是否存在 PENDING AI Message」若無額外鎖定（如 `select_for_update` 鎖 Conversation 列），在高併發下是否仍可能出現兩個 transaction 都通過檢查後各自建立一筆 PENDING Message？需與 Dev 確認實際鎖定範圍。
2. **`reply_in_progress` 解除時機**：若 Celery task 因 worker crash 導致訊息永久卡在 `PENDING`（未 COMPLETED 也未 FAILED），使用者將永遠無法再提交查詢。是否需要逾時機制（如超過 N 分鐘自動轉 FAILED）？目前設計文件未提及。
3. **中文全文檢索分詞**：`search_vector` 使用的 Postgres text search config 尚未決定，中文關鍵字的部分詞命中行為（如「退貨」是否能從「退貨流程」中被檢索到）需要在實作階段以實際 config 驗證，目前範例僅為預期行為的佔位。
4. **`enable_weighted_failover` 實際行為**（設計文件風險註記 B3）：同層僅剩一個候選、或全部候選皆停用（`is_enabled=False`）時 Router 的具體報錯訊息/行為未經實測，`error_message` 的內容格式待確認。
5. **SSE 斷線重連**：設計文件明確標示未定案。使用者連線中斷後，若 `EventSource` 自動重連帶著已使用過的 ticket，目前規則會直接拒絕連線——這段時間內若 task 剛好完成，使用者要如何得知結果（除輪詢 fallback API 外）？需要定義重連時的換票流程。
6. **`PENDING_HUMAN` 解除後的歷史查詢**：客服將 `PENDING_HUMAN` 改回 `OPEN` 後，先前那則 `FAILED` 的 AI Message 是否應排除在下一次生成的歷史 context 之外（依現有規則會被 `filter(status="completed")` 自然排除），但使用者後續在對話清單 UI 上看到這則 FAILED 訊息的呈現方式（是否標示為「已轉真人處理」）未在本設計中定義，屬於前端呈現範疇但可能需要後端提供額外欄位。

---

以上範例是否符合您的預期？有哪些情境需要補充或修正？
