# API 與管理介面（API & Admin Interface）設計文件

**日期：** 2026-07-09
**範圍：** PRD「功能需求 - API 與管理介面」— 提交查詢、查詢會話紀錄、更新場景設定 API；Django Admin 管理介面
**不涵蓋：** AI 呼叫細節與 Celery 任務內部邏輯（見 spec2）、資料模型定義本身（見 spec1）、擴充性需求（PRD 第四項，將另外討論）
**依賴：**
- [對話管理設計文件](2026-07-08-conversation-management-design.md)（spec1，`SceneConfig`/`Conversation`/`Message` model）
- [AI 自動回覆流程設計文件](2026-07-09-ai-auto-reply-design.md)（spec2，Celery 任務 `generate_ai_reply`、重試/失敗轉真人規則）

## 背景

spec1、spec2 已完成資料模型與非同步生成流程設計，並明確留下三個待這次需求解決的缺口：

1. 「同一 Conversation 一次只能一則 PENDING AI Message」規則的 enforce 責任。
2. 前端如何取得非同步生成的 AI 回覆結果（spec1 原本假設「輪詢或另建通知機制」）。
3. 業務人員檢視/管理對話紀錄的介面。

本文件設計三支 REST API（提交查詢、查詢會話紀錄、更新場景設定）、一個即時推送機制、以及 Django Admin 管理介面，補齊這些缺口。

## 整體架構

專案從純 WSGI 架構，擴充為 **WSGI（既有 REST API）+ ASGI（Channels，僅負責即時推送）並存**：

- 一般 REST API（提交查詢、查詢會話紀錄、更新場景設定）維持同步、走 Django 原生 view + DRF，跑在既有 WSGI/Gunicorn 進程，不需要 async，改動最小。
- 新增一個只負責「AI 回覆狀態即時推送」的 SSE 端點，因為需要長連線 hold 住等待事件，独立跑在 ASGI 進程，使用 `channels` + `channels_redis`（複用既有 Redis，不需新增基礎設施）。
- `asgi.py` 用 `ProtocolTypeRouter` 依路徑分流：一般 HTTP 走 Django 原生 view，`/sse/...` 走 Channels consumer。

```
瀏覽器
  ├─(1) POST /api/conversations/{id}/messages/  ──▶ Django (WSGI) ──▶ 同步建立 USER+AI(PENDING) Message
  │                                                                  └─▶ 觸發 Celery task (generate_ai_reply)
  ├─(2) POST /api/conversations/{id}/sse-ticket/ ──▶ Django (WSGI) ──▶ 發一次性短效 ticket（存 Redis）
  ├─(3) GET  /sse/conversations/{id}/?ticket=xxx ──▶ Channels consumer
  │        │                                        ├─ 驗證 ticket（一次性、TTL）
  │        │                                        ├─ group_add(f"conv_{id}")
  │        │                                        └─ 查 DB 送出目前狀態作為初始快照
  │        │                                        （之後持續等待 group_send 事件）
  └─(4) 其他 REST API（查詢紀錄/場景設定）           ──▶ Django (WSGI) 一般 view

Celery worker (generate_ai_reply，見 spec2)
  └─▶ 更新 AI Message 狀態（COMPLETED / FAILED）
       └─▶ channel_layer.group_send(f"conv_{id}", {"message_id", "status", "content"/"error_message"})
            ──▶ 推送給訂閱該對話的 SSE consumer
```

新增一個獨立 app：`maiagent_ai_django/api`（DRF serializers/views/permissions/throttles）與 `maiagent_ai_django/realtime`（Channels consumer、routing、ticket 發放邏輯）。兩者皆依賴 `conversations` app 的 model，`conversations` app 本身不感知 API 或推送層存在。

## 認證與授權（RBAC）

採用 Django 內建 **Group + Permission** 機制，不新增自訂角色欄位：

| 角色 | 實現方式 | 權限範圍 |
|---|---|---|
| 一般使用者 | 一般已登入 `users.User`，不屬於任何特殊 Group | 只能對自己的 `Conversation`/`Message` 讀寫；只能 `GET /api/scenes/`（選擇場景用，不可寫） |
| 客服人員 | 屬於 `customer_service` Group | 可檢視所屬場景（`scene_type=customer_service`）下的所有 `Conversation`；可在 Django Admin 修改 `Conversation.status`（例如 `PENDING_HUMAN` 改回 `OPEN`/`CLOSED`） |
| 管理者 | `is_superuser` 或屬於 `admin` Group | 可讀寫 `SceneConfig`；可檢視/調整任何 `Conversation.status` |

理由：PRD 明確要求「業務人員能用 Django Admin 檢視管理對話記錄」，這正是 Django Group/Permission 系統的原生應用場景（Admin 本身就是用這套權限系統控制可見範圍），且未來要加更細粒度權限不需要修改 model schema。

## API Endpoint 清單

| Endpoint | 方法 | 用途 | 權限 |
|---|---|---|---|
| `/api/conversations/` | POST | 建立新對話（需指定 `scene`） | 已登入使用者 |
| `/api/conversations/` | GET | 列表（cursor 分頁、`scene`/`status`/時間區間過濾、`?q=` 全文檢索） | 一般使用者只看自己的；客服看所屬場景全部 |
| `/api/conversations/{id}/messages/` | POST | 提交查詢 | 對話所有者；DRF throttling；已有 PENDING AI Message 時回 409 |
| `/api/conversations/{id}/messages/` | GET | 列表對話內訊息（cursor 分頁） | 同 Conversation 權限 |
| `/api/messages/{id}/` | GET | 查詢單筆訊息目前狀態（SSE 連線前的初始快照，亦作 SSE 不可用時 fallback） | 同 Conversation 權限 |
| `/api/conversations/{id}/sse-ticket/` | POST | 換發一次性短效 SSE ticket | 同 Conversation 權限 |
| `/sse/conversations/{id}/` | GET（SSE） | 訂閱該對話後續 AI 回覆狀態事件 | 帶有效 ticket |
| `/api/scenes/` | GET | 列表場景設定 | 已登入使用者（建立對話時選擇用） |
| `/api/scenes/` | POST | 建立場景設定 | 管理者 |
| `/api/scenes/{id}/` | PATCH | 更新場景設定 | 管理者 |

## 併發控制：409 Conflict

提交查詢 API 在建立新 Message 前，先檢查該 Conversation 是否存在 `status=PENDING` 的 AI Message：若存在，回傳 `409 Conflict`（不建立任何新 Message、不觸發 Celery task），前端需等待上一則回覆完成（`COMPLETED`/`FAILED`）才能再送出下一則查詢。此檢查與 Message 建立需在同一個 DB transaction 內完成，避免併發請求繞過檢查。

此規則的 enforce 責任明確畫在本 API 層，補上 spec2「歷史查詢防禦性過濾」之外，主動阻止規則被違反的機制。

## 即時推送（SSE + Channels）設計

### 為何不用前端輪詢

spec1 原本假設前端透過輪詢取得結果。輪詢的缺點是延遲與請求量的取捨難兩全（頻率高則浪費資源、頻率低則使用者等待感明顯）。改用伺服器主動推送可讓使用者在生成完成的瞬間就看到結果。

### 為何用 Channels group 而非單一 channel 廣播

若用一個固定字串 channel 承載所有事件、由每個消費者自行過濾 `conversation_id`/`user_id`，會有兩個問題：每個事件都廣播給所有連線中的消費者（連線數越多、無關流量越大）；且未解決「多個 SSE consumer instance 時，使用者連到哪一個」的路由問題。

改用 Channels 內建的 **group** 機制（每個 Conversation 一個 group，group 名稱為 `conv_{conversation_id}`）：

- SSE consumer 連線建立時執行 `channel_layer.group_add(f"conv_{conversation_id}", self.channel_name)`——底層是對 Redis 一個 sorted set（`asgi:group:conv_{id}`）做 `ZADD`，成本等同寫入一個 key；沒人訂閱時這個 group 不存在，零成本。
- Celery task 更新完 Message 後執行 `channel_layer.group_send(f"conv_{conversation_id}", {...})`——底層查該 sorted set 的成員（`ZRANGE`），逐一 `RPUSH` 進每個成員各自的 channel（Redis list），consumer 端用 `BLPOP` 等待取出。
- 沒人在看的對話，其 group 是空的，`group_send` 等同 no-op，不會浪費頻寬廣播給無關連線；天生支援多個 consumer instance（水平擴展），Redis 幫忙做路由，不需要應用層自己維護「使用者連到哪個消費者」的對應表。

### SSE 連線的身份驗證

瀏覽器原生 `EventSource` API 不支援自訂 `Authorization` header，不能直接沿用一般 API 的 token 認證方式。設計為：

1. 前端先呼叫 `POST /api/conversations/{id}/sse-ticket/`（走一般 WSGI API，可用正常 session/token 認證），後端產生一次性、短 TTL（例如 60 秒）的 ticket 存入 Redis（key 綁定 `user_id` + `conversation_id`），回傳 ticket 字串。
2. 前端用 `new EventSource(`/sse/conversations/{id}/?ticket=${ticket}`)` 建立連線。
3. Channels consumer 在 `connect()` 時驗證 ticket：存在、未過期、綁定的 `user_id`/`conversation_id` 與請求路徑一致 → 驗證通過後立即刪除該 ticket（一次性），再走一般的 Conversation 權限檢查。

一次性 + 短 TTL 設計降低了 ticket 出現在 URL/瀏覽器歷史/伺服器 access log 中被重用的風險——即使洩漏，時間窗口極短且只能用一次。

### 初始快照時序（避免漏接事件）

Consumer 的 `connect()` 邏輯順序固定為：**先 `group_add`，再查一次 DB 送出目前狀態作為第一個 SSE event，之後才進入等待迴圈**。此順序保證不論 Celery task 是在 `group_add` 之前或之後完成，最終狀態都不會被漏接——先訂閱再查詢，確保訂閱期間發生的任何 `group_send` 都不會錯過；若 task 早已完成，訂閱之後也不會再有新事件，但初始快照的 DB 查詢會補上這個狀態。

### 推送事件的範圍

只推送 Message 層級的狀態變化（`status` 轉為 `completed` 或 `failed`，payload 包含 `message_id`、`status`、`content` 或 `error_message`）。`Conversation.status` 轉為 `PENDING_HUMAN` 這個內部分派旗標**不**透過 SSE 推送——那是給客服/管理者在 Django Admin 看的狀態，使用者只需要知道「這則訊息失敗了」（已透過 `status=failed` 事件告知），不需要感知後端「已標記轉真人處理」這層內部細節，避免 SSE payload 語意混雜兩種不同受眾的資訊。

## 場景設定 API

`PATCH /api/scenes/{id}/` 直接更新，不記修改歷程/審核（PRD 未要求審核流程，維持簡單）。若未來需要稽核（例如設定變更影響 AI 行為需要回溯），可再引入 `django-simple-history`，不影響現有 API 介面。

## 效能與流量控制

- **提交查詢 API 加 DRF throttling**（`UserRateThrottle`，例如每使用者每分鐘上限 N 次）：每次提交查詢都會觸發 Celery task 呼叫外部 AI API（有成本、佔用 worker），需防止濫用或程式錯誤造成的高頻請求導致 API 帳單暴增或 worker 隊列堵塞。
- **列表查詢採 cursor-based pagination**（DRF `CursorPagination`，基於 `created`/`id`）：`Conversation`/`Message` 資料只會持續新增不會大量變動，cursor pagination 避免 offset pagination 在資料量增長或新資料插入時的重複/遺漏問題，且效能不會隨頁數加深而下降。
- **全文檢索**透過既有的 `messages.search_vector`（GIN index，見 spec1）在 `GET /api/conversations/?q=關鍵字` 中實作，查詢時關鍵字轉換為 `SearchQuery` 比對 `search_vector`。

## Django Admin 管理介面

直接使用 Django Admin（不自建管理 UI），符合 PRD「可利用 Django Admin」的提示：

- `ConversationAdmin`：`list_display`（使用者、場景、狀態、建立時間）、`list_filter`（`scene`、`status`）、inline 顯示所屬 `Message` 列表（唯讀）。
- `MessageAdmin`：`list_display`、`search_fields` 接 `search_vector`（全文檢索）、`readonly_fields` 涵蓋 `content`/`metadata`/`error_message`（訊息不可變，見 spec2 假設）。
- 客服人員（`customer_service` Group）透過 Django 內建 Permission 只能看到所屬場景的 `Conversation`，且**只能修改 `Conversation.status`**（例如手動將 `PENDING_HUMAN` 改回 `OPEN`/`CLOSED`），訊息內容本身不可編輯，維持「訊息一旦建立即不可變」的假設與稽核完整性。

## 錯誤處理總覽

| 情境 | 處理方式 |
|---|---|
| 對已有 PENDING AI Message 的對話提交新查詢 | `409 Conflict`，不建立新資料、不觸發任務 |
| 提交查詢頻率超過限制 | `429 Too Many Requests`（DRF throttling） |
| SSE ticket 不存在/過期/已使用過 | Consumer 拒絕連線（`close()`） |
| AI 生成重試用盡仍失敗（見 spec2） | Message 更新為 `FAILED`，透過 SSE 推送 `status=failed` + `error_message`；`Conversation.status` 轉 `PENDING_HUMAN`（不推送，見上） |
| 存取他人 Conversation | `403 Forbidden`（權限檢查於 view 層） |

## 測試考量

- **權限矩陣**：一般使用者/客服/管理者對每個 endpoint 的存取結果（含跨使用者存取他人 Conversation 應回 403）。
- **併發控制**：對已有 PENDING AI Message 的對話併發送出多個提交查詢請求，驗證只有一個成功、其餘回 409。
- **Throttling**：短時間內超過限制次數應回 429。
- **SSE**：用 Channels 的 `ApplicationCommunicator` 測試 consumer 的 `group_add`、初始快照正確性、收到 `group_send` 後正確轉發給前端；ticket 一次性與 TTL 過期測試。
- **全文檢索**：`?q=關鍵字` 能查到 `search_vector` 命中的訊息所屬對話。

## 未來擴充摘要

| 項目 | 現況 | 未來擴充方式 |
|---|---|---|
| SceneConfig 修改歷程 | 不記錄 | 引入 `django-simple-history` 或手寫 AuditLog model |
| 訊息取消/重新編輯（Admin 可編輯內容） | 不支援，維持不可變假設 | 屬全新功能需求，需重新評估歷史查詢與 SSE 事件語意 |
| 多 SSE consumer instance 水平擴展 | Channels group 機制天生支援，尚未實際壓測 | 需壓測 Redis channel layer 在高並發連線下的表現 |
