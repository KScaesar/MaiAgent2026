# AI 自動回覆流程（AI Auto-Reply Flow）設計文件

**日期：** 2026-07-09
**範圍：** PRD「功能需求 - AI 自動回覆流程」— 非同步生成 AI 回覆的 Celery 任務設計、AI 呼叫抽象層設計
**不涵蓋：** API endpoint 實作與細節（提交查詢、查詢會話紀錄、更新場景設定 — 屬於「API 與管理介面」需求，將另外討論）、Django Admin 介面
**依賴：** [對話管理設計文件](2026-07-08-conversation-management-design.md)（`SceneConfig`/`Conversation`/`Message` model 定義）
**修正紀錄（2026-07-10）：** 本文件假設「一個 Scene 固定對應一個模型」已被 [擴充性（多 AI 模型路由）設計文件](2026-07-10-scalability-model-routing-design.md) 修正——`AIProvider.agenerate` 拿掉 `model` 參數、改用 `litellm.Router` 處理多模型選擇與 failover、Celery 層的 `autoretry` 已取消（改由 Router 的跨模型 fallback 取代）。下方「AI 呼叫抽象層設計」「修正版高階流程」「Celery 任務設計」章節中與此衝突的部分，請以新文件為準；本文件保留供歷史脈絡參考。

## 背景

PRD 要求：使用者送出訊息時，系統先記錄查詢內容，再透過非同步任務模擬呼叫外部生成式 AI API 生成回覆，回覆後更新對話記錄。對話管理設計文件（下稱 spec1）已定義好資料模型，並在流程圖中畫出雛形，但明確標記「重試機制」「失敗後是否轉真人」尚未設計。本文件補上這兩塊，並新增 AI 呼叫抽象層的設計，讓 Celery 任務不直接耦合任何特定 AI provider 的實作細節。

## 整體架構

新增一個獨立 app：`maiagent_ai_django/ai_providers`，加入 `LOCAL_APPS`。這個 app 沒有 model，純邏輯層，負責封裝「呼叫 AI 生成回覆」這個能力，讓 `conversations` app 完全不需要知道底層是呼叫真實的 liteLLM 還是模擬替身。

```
ai_providers/
├── interfaces.py        # AIProvider 抽象介面
├── litellm_provider.py  # LiteLLMProvider：包裝 liteLLM 真實呼叫
├── simulator.py          # DelayedFailureSimulator：模擬延遲 + 隨機失敗
└── factory.py            # 依設定選擇要使用的 provider 實例
```

`conversations/tasks.py` 新增 Celery 任務 `generate_ai_reply(ai_message_id)`，透過 `ai_providers.factory` 取得 provider 實例並呼叫其抽象介面方法，不直接 import liteLLM 或 Simulator 的具體類別。

## AI 呼叫抽象層設計

### 介面命名

liteLLM 的公開 API（`completion`/`acompletion`/`batch_completion`）遵循 OpenAI SDK 命名慣例，而非 LangChain 的 `Runnable`（`invoke`/`ainvoke`）慣例。為了讓抽象介面與底層實作語意一致、降低認知負擔，`AIProvider` 介面採用貼近 liteLLM 原生命名的方法：

- `generate(model, messages, **kwargs)` — 同步生成
- `agenerate(model, messages, **kwargs)` — 非同步生成（Celery task 主要呼叫此方法）
- `stream(model, messages, **kwargs)` — 同步串流
- `astream(model, messages, **kwargs)` — 非同步串流
- `batch_generate(model, messages_list, **kwargs)` — 批次生成

現階段（本次作業）Celery 任務只使用 `agenerate`；`stream`/`astream`/`batch_generate` 定義在介面中但不強制所有實作都完整支援，供未來串流回覆、批次處理等需求擴充。

> **修正（2026-07-10）：** 上述方法簽名的 `model` 參數已被移除。原因是一個 Scene 可能對應多個候選模型（`ModelRoute`），「該用哪些模型」在建構 provider 時就已由 `litellm.Router` 設定決定，不再是呼叫當下由外部傳入的字串。詳見 [擴充性（多 AI 模型路由）設計文件](2026-07-10-scalability-model-routing-design.md)。

### `LiteLLMProvider`

直接包裝 `litellm.acompletion(model, messages, timeout=..., **kwargs)`，回傳值即為 liteLLM 原生的 `ModelResponse` 物件（`response.choices[0].message.content`、`response.usage`）。

### `DelayedFailureSimulator`

本次作業用於取代真實 API 呼叫的替身，內部實作策略：

- 呼叫 `litellm.completion(model, messages, mock_response=<可設定的模板文字或依查詢內容 echo>)`，確保回傳結構與真實 API 完全一致（liteLLM 原生支援 `mock_response` 用於測試，見延伸閱讀）
- 額外包一層人工延遲（可設定範圍，例如 1~3 秒 `sleep`，模擬非同步版本則用 `asyncio.sleep`）
- 依可設定的失敗機率（例如 10%），改為呼叫 `litellm.completion(mock_response=Exception(...))` 模擬失敗，交由呼叫端（Celery task）的重試機制處理
- 延遲與失敗機率透過建構子參數或全域設定注入，不寫死在類別內，方便測試時覆寫

### `factory.get_provider(scene_config)`

依全域設定 `AI_BACKEND`（`litellm` | `simulator`）決定要 instantiate 哪一個實作類別；`model` 等呼叫參數則來自 `SceneConfig.default_settings`（例如 `{"provider": "litellm", "model": "gpt-4o-mini"}`）。`AI_BACKEND` 是環境層級設定（本次作業預設 `simulator`，因無真實 API key），不放在 `SceneConfig` 裡，避免業務設定與後端串接細節混在一起。

> **修正（2026-07-10）：** `factory.get_provider` 改吃 `scene`（而非 `scene_config` 單一設定），從 `scene.model_routes`（`ModelRoute`）組出 `litellm.Router` 的 `model_list`，回傳已綁定路由設定的 provider 實例；`model` 不再是單一字串。詳見 [擴充性（多 AI 模型路由）設計文件](2026-07-10-scalability-model-routing-design.md)。

## 修正版高階流程

取代 spec1 原本的流程圖：

```
使用者發送查詢
      │
      ▼
[Celery task 觸發點，API 細節留給「API 與管理介面」需求]
      │
      ├─ 若無現有 Conversation → 建立 Conversation(status=OPEN, scene=<場景>)
      │
      ▼
同步建立兩筆 Message：
  - USER Message(status=COMPLETED, content=<查詢內容>)
  - AI Message(status=PENDING, content="")
      │
      ▼
觸發 Celery task：generate_ai_reply(ai_message_id=<AI Message.id>)
      │
      ▼ (非同步背景執行)
task 開始：SELECT ... FOR UPDATE 鎖定並讀取 AI Message
      │
      ├─ status != PENDING → 直接 return（idempotency guard）
      │
      ▼
反查 conversation = ai_message.conversation
      │
      ▼
查歷史：conversation.messages.exclude(id=ai_message_id)
                              .filter(status="completed")
                              .order_by("created", "id")
      │
      ▼
依 Conversation.scene.default_settings → factory.get_provider(...) 取得 provider
      │
      ▼
呼叫 provider.agenerate(model, messages=<歷史+查詢>, timeout=...)
      │
      ├─ 成功 → 更新 AI Message：status=COMPLETED, content=<回覆>,
      │          metadata={model, prompt_tokens, completion_tokens, attempt_count}
      │
      └─ 失敗 → Celery autoretry（有限次數 + exponential backoff + jitter）
              │
              ├─ 重試期間 → Message 維持 PENDING
              │
              └─ 重試次數用盡仍失敗
                      │
                      ▼
              更新 AI Message：status=FAILED, error_message=<原因>
                      │
                      ▼
              Conversation.status → PENDING_HUMAN
```

## Celery 任務設計

**任務簽名：** `generate_ai_reply(ai_message_id)` — 只傳 primitive ID，不傳整包對話內容或 ORM 物件（Celery 任務參數會被序列化進 broker，且 ORM 物件不可序列化；task 執行時才查 DB 可確保拿到當下最新狀態，避免排隊延遲造成的資料過期問題）。

**為何不傳 `conversation_id` 取代 `ai_message_id`：** `ai_message_id` 可透過 FK（`ai_message.conversation`）反查得到 `conversation_id`，資訊沒有損失；反之若只傳 `conversation_id`，當同一 Conversation 同時存在多筆 `PENDING` AI Message 時（例如業務規則被違反、或未來允許併發送出多則查詢），task 將無法判斷該更新哪一筆，會有精確度損失。

**重試策略：**
- 僅針對 provider 呼叫失敗（逾時、外部 API 錯誤）觸發重試，資料本身錯誤（例如 AI Message 不存在）不重試
- 最多重試 3 次，exponential backoff + jitter
- 每次呼叫帶明確 `timeout`（例如 30 秒）

> **修正（2026-07-10）：** 上述 Celery 層重試已取消。改由 `litellm.Router` 內部處理多模型 failover（同層一失敗即換下一個候選，同層試完才跨層），Router 把所有候選模型都試過仍失敗才拋出例外，task 捕捉到即直接判定 `FAILED`，不再對整個流程重跑。理由：疊加整流程重試對系統性故障（如 API 本身掛掉）沒有幫助，只會拉長延遲。詳見 [擴充性（多 AI 模型路由）設計文件](2026-07-10-scalability-model-routing-design.md)。

**併發安全：** 任務開始時在一個 transaction 內對 AI Message row 做 `select_for_update()` 並檢查 `status`，非 `PENDING` 則直接 return。此鎖同時防止「同一任務被重複排程執行」與「多個 worker 同時處理同一筆訊息」的競態。

**歷史查詢的防禦性過濾：** 查詢條件強制 `filter(status="completed")`，不論實際是否有其他流程違反「同一 Conversation 一次只能有一則 PENDING AI Message」的業務規則，未完成或失敗的訊息永遠不會被當作上下文送進 LLM。該業務規則本身的 enforce 點（例如 API 層拒絕新請求）留給「API 與管理介面」需求設計，本文件僅記錄此依賴假設。

## 未來擴充 / 已知邊界條件

| 項目 | 現況 | 說明 |
|---|---|---|
| 訊息取消 / 重新編輯 | 未設計，假設訊息一旦建立即不可變（immutable） | 若未來支援，需重新設計歷史查詢與狀態機（例如加 `CANCELLED` 狀態或版本鏈） |
| LLM KV cache 最佳化 | 每次即時查 DB 組 context，未考慮 prompt prefix 快取穩定性 | 需確保同一 Conversation 的歷史 prefix 順序穩定不變動，與「訊息不可變」假設相輔相成 |
| 「一次只能一則 PENDING AI Message」規則 enforce | 本文件僅做防禦性過濾，未 enforce | 留給「API 與管理介面」需求設計（例如拒絕新請求或排隊） |
| 串流回覆 | `AIProvider.stream`/`astream` 已定義介面但未實作使用場景 | 未來若要支援前端即時串流顯示，Celery 任務模式需改為 WebSocket/SSE 推送 |
| 批次生成 | `AIProvider.batch_generate` 已定義介面但未使用 | 對應 PRD 附加挑戰的多模型/多場景批次處理可能用到 |

## 測試考量

- **`ai_providers` 層**
  - `LiteLLMProvider`：mock `litellm.completion`/`acompletion`，驗證參數轉換、回傳解析正確
  - `DelayedFailureSimulator`：驗證失敗機率統計上符合設定值（多次取樣）、延遲落在設定範圍、回傳結構與 `LiteLLMProvider` 一致
  - `factory`：不同 `AI_BACKEND` 與 `SceneConfig.default_settings` 組合下回傳正確的 provider 實例
- **Celery task 層**
  - Idempotency guard：AI Message 已是 `COMPLETED`/`FAILED` 時，task 執行後無任何更新、無呼叫 provider
  - 歷史查詢過濾：混入 `PENDING`/`FAILED` 訊息時，驗證不會出現在送給 provider 的 messages 參數裡
  - 重試行為：模擬 provider 拋出可重試例外，驗證重試次數與 backoff 符合設定
  - 最終失敗路徑：重試用盡後，AI Message 變 `FAILED` 且 `Conversation.status` 變 `PENDING_HUMAN`
  - 成功路徑：AI Message 正確寫入 `content`/`metadata`

## 延伸閱讀

- liteLLM Mock Completion Responses: https://docs.litellm.ai/docs/completion/mock_requests
- liteLLM Completion / Streaming / Batching docs: https://docs.litellm.ai/docs/completion/input , https://docs.litellm.ai/docs/completion/stream , https://docs.litellm.ai/docs/completion/batching
