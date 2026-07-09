# AI Context Handoff: 本機執行專案並確認 Admin 頁面

## 1. 任務摘要 (What & Flow)

- **目標**：專案用 cookiecutter-django 生成時漏帶 Docker 相關檔案，導致無法 `docker compose up` 起整個環境（Django + Postgres + Redis + Mailpit）。任務是把這些檔案補回來，並驗證整個環境能跑起來、Admin 頁面能登入。
- **成功指標**：`docker compose -f docker-compose.local.yml up` 能一次啟動四個服務、migration 自動套用成功、能用瀏覽器登入 `/admin/` 並看到正常的 Site administration 首頁。
- **邏輯流**：
  1. 找出當初生成專案時用的 cookiecutter 參數（`use_docker`、`use_celery` 等）。
  2. 用這組參數重新跑一次 cookiecutter-django，生成到暫存目錄（不動現有專案）。
  3. 只從暫存目錄複製 Docker/Compose 相關檔案回現有專案，程式碼本身不動。
  4. `docker compose up` 啟動服務 → migration 自動跑 → 建 superuser → 瀏覽器登入驗證。
- **輸入**：現有專案內容（`pyproject.toml`、`.envs/.local/.django` 等既有設定檔）、cookiecutter-django 模板。
- **輸出**：`docker-compose.local.yml`、`compose/` 目錄下的檔案、`.dockerignore`；一個可執行的本機開發環境。

## 2. 決策背景 (Why)

- **決策依據**：`~/.cookiecutter_replay/cookiecutter-django.json`（cookiecutter 記錄上次問答的全域快取）裡存的是預設值（`use_docker: "n"`、`use_celery: "n"`），跟專案實際內容矛盾（`pyproject.toml` 有 celery、whitenoise；`.envs/.local/.django` 有 `USE_DOCKER=yes`；README 提到 Mailpit）。因此改用「反向推測」的方式：比對現有專案的既有內容（依賴、環境變數、README），手動組出一組更接近真實的 cookiecutter 參數（`use_docker=y`、`use_celery=y`、`use_mailpit=y`、`use_whitenoise=y`、`rest_api=DRF`、`postgresql_version=18`），重新產生一份完整專案來抽取 Docker 檔案。
- **已排除方案**：直接套用 `cookiecutter_replay` 裡的預設值——因為那組值跟專案實際使用的技術（celery/whitenoise/docker）明顯不符，用了會生成錯誤或缺漏的 Docker 設定。

## 3. 邊界與假設 (Boundary & Assumption)

- **範疇外事項**：沒有修改任何既有的應用程式碼；只補 Docker/Compose 基礎設施檔案。沒有處理正式環境（production）部署，只做本機開發環境。
- **基礎假設**：
  - 假設用「反向推測」組出的 cookiecutter 參數與當初生成專案時的真實參數一致或高度相近——這點**未經 100% 驗證**，只是透過 `docker compose config` 語法檢查、以及確認 `.envs/.local/*` 檔案能對應得上來間接佐證。
  - 假設 Postgres 版本用 18 是合理猜測（未從專案內找到明確版本紀錄）。

## 4. 風險與壓力測試 (Failure & Robustness)

- **失敗路徑**：若當初生成參數與這次反推的參數有出入（例如當初其實選了不同的 Postgres 版本、或用了不同的 CI 設定），現在補回的 Docker 檔案可能與其他既有設定（如 CI pipeline）產生版本不一致，目前尚未逐一比對過。
- **反例測試**：`docker compose exec` 直接進容器跑指令時，因為不會經過 `/entrypoint` 腳本（該腳本負責把 `POSTGRES_*` 環境變數組成 `DATABASE_URL`），預設會嘗試走 Unix socket 連線而失敗。已知解法是額外用 `-e DATABASE_URL=...` 手動帶入完整連線字串。
- **抗壓能力**：這次補檔案的方式是「一次性」的，並未建立自動化腳本或文件記錄「如何重新生成/驗證」，若專案後續需要再次調整 cookiecutter 參數（例如換 Postgres 版本），需要重複這次的人工比對流程。

## 5. 延續執行 (Continuity)

- **目前狀態**：
  - 已完成：Docker/Compose 檔案已補回專案（`docker-compose.local.yml`、`compose/local/django/`、`compose/production/django/entrypoint`、`compose/production/postgres/`、`.dockerignore`）。
  - 已完成：四個容器（postgres、redis、mailpit、django）成功啟動，migration 自動套用，Django dev server 正常運作於 `http://localhost:8000`。
  - 已完成：建立測試 superuser（`admin@example.com` / `AdminPass123!`），用瀏覽器驗證登入 `/admin/` 成功。
  - 待處理：Docker 服務目前仍在背景執行中，尚未關閉。
- **待解決問題**：
  - 建立的 superuser 帳密只存在本機測試資料庫，屬暫時性測試帳號，正式環境需另外建立。
  - 未驗證反推的 cookiecutter 參數是否與當初真實生成參數完全一致。
- **下一步指令建議**：
  1. 若不需要繼續跑，執行 `docker compose -f docker-compose.local.yml down`（加 `-v` 會連同資料庫資料一起清掉）。
  2. 若要長期使用這組 Docker 設定，建議找機會跟原始開發者確認當初實際的 cookiecutter 參數，比對這次反推的結果是否一致。

---

# AI Context Handoff: 對話管理（Conversation Management）設計討論

## 1. 任務摘要 (What & Flow)

- **目標**：針對 `prd.md` 第一項功能需求「對話管理」，設計一個（或一組）model 來儲存使用者的會話歷史，每筆記錄需包含使用者資訊、會話狀態、時間戳記、對話內容，並產出設計文件供後續實作使用。
- **成功指標**：產出一份經使用者逐步確認、涵蓋架構/流程/資料合約/決策理由的設計文件（spec），使用者審閱後可直接進入 `writing-plans` 產生實作計畫。
- **邏輯流**：透過 `/brainstorming` 流程，逐一釐清需求（Session/Message 分層 → 使用者模型 → 場景設定 → 主鍵型別 → 排序策略 → 狀態機 → 軟刪除 → 全文檢索），每個決策點都先解釋權衡再讓使用者確認，最後彙整成高階流程圖 + DBML 資料合約 + 決策理由文件。
- **輸入**：`prd.md` 第一項需求文字、現有專案結構（cookiecutter-django，已有 `users.User`、DRF、Celery beat、`django-model-utils` 依賴）。
- **輸出**：`docs/superpowers/specs/2026-07-08-conversation-management-design.md`。

## 2. 決策背景 (Why)

- **決策依據**：
  - **Session + Message 兩層架構**（而非單表或 JSONField）：因為 PRD 要求「先記錄查詢內容，再非同步生成回覆，回覆後更新對話記錄」，需要對單則訊息有獨立狀態機（PENDING/COMPLETED/FAILED），JSONField 難以乾淨表達單筆狀態轉換且有並發寫入風險。
  - **UUID 當主鍵**：`Conversation`/`Message`/`SceneConfig` 會透過 RESTful API 曝露給前端，UUID 避免用連續整數 ID 枚舉他人對話記錄（IDOR 風險）。
  - **Message 排序用 `created` + `id`，不加額外 `sequence` 欄位**：實際查詢模式（組 LLM context、API 回傳列表）都是整個 Conversation 一次拉出再排序，不存在逐筆單獨定位需求，加欄位是過度設計。
  - **`Conversation` 現在就掛 `scene` FK**：場景決定 AI 處理邏輯（提示詞/模型/是否查知識庫），是會話的內在屬性，若晚點才加會需要對既有資料做 migration 補值。
  - **軟刪除**（`is_deleted`/`deleted_at`）：客服/KM 對話記錄有稽核/合規需求，不應被硬刪除。
- **已排除方案**：
  - 單一 model 一問一答存一筆——排除，因為無法表達多輪對話與跨訊息的上下文關聯。
  - 單一 Conversation + JSONField 存整串訊息——排除，因為單則訊息無法有獨立的資料庫層級狀態，且並發更新同一 JSON 欄位有 race condition 風險。
  - `SceneConfig` 用 `scene_type` 當 pk——排除，因為使用者提出未來可能需要同一場景類型有多組不同設定（例如不同客戶各自客製化），改回 `id`(uuid) 當 pk、`name` 唯一。
  - Message 加獨立 `BigAutoField sequence` 欄位保證嚴格順序——排除，因重新檢視查詢模式後判斷不必要（見上）。
  - `scene_type` 加 index——排除，因為只有兩三種值，低基數欄位加 index 對效能助益有限。

## 3. 邊界與假設 (Boundary & Assumption)

- **範疇外事項**：本次設計**不涵蓋** AI 自動回覆的 Celery 任務實作、API endpoint 實作、Django Admin 介面——這些屬於 PRD 後續需求（「AI 自動回覆流程」「API 與管理介面」「擴充性」），將另外討論。也不包含實際的 Python model 程式碼（使用者要求先用高階流程圖 + DBML 呈現，未落地成程式碼）。
- **基礎假設**：
  - 假設現階段所有發訊者都是已登入的 Django `users.User`，不需要處理匿名/外部終端使用者（該情境已設計「影子帳號」擴充方案但未實作，見決策依據）。
  - 假設 `search_vector` 的實際填值機制（signal 或 Postgres trigger）留到實作階段再處理，設計文件只建立欄位與 GIN index。
  - 假設 `django-model-utils` 的 `TimeStampedModel` 會被用來提供 `created`/`modified` 時間戳記（專案已有此依賴但尚未在既有 model 使用過，未實際驗證整合方式）。

## 4. 風險與壓力測試 (Failure & Robustness)

- **失敗路徑**：
  - 若 AI API 呼叫失敗，對應的 AI `Message` 應更新為 `status=FAILED` 並填 `error_message`；但目前只是設計文件層級的約定，實際的重試機制、失敗後是否要轉 `Conversation.status=PENDING_HUMAN`，尚未設計（下一階段「AI 自動回覆流程」需求要處理）。
  - 若兩則訊息在同一微秒內建立（極端並發），`created`+`id` 排序的 tie-break 不具時序意義，可能導致顯示順序與實際發生順序不完全一致；設計文件裡評估此風險機率極低且不影響系統正確性，故接受此限制而非加欄位解決。
- **反例測試**：目前設計文件未包含具體的反例測試案例（例如「超長訊息內容」「非 UTF-8 內容」等邊界輸入），屬於實作階段測試考量的一部分，設計文件的「測試考量」章節只列了高層次方向（狀態轉換、軟刪除排除、全文檢索）。
- **抗壓能力**：`SceneConfig.default_settings` 用 JSONField 存放彈性設定，未來要擴充路由/權重邏輯時只需加欄位或新增關聯表，不影響 `Conversation`/`Message` 既有資料；但目前完全沒有實測過資料量成長（例如單一 Conversation 累積上萬則 Message）時，`Meta.ordering = ["created", "id"]` 搭配 `(conversation_id, created)` index 的查詢效能表現。

## 5. 延續執行 (Continuity)

- **目前狀態**：
  - 已完成：需求逐項釐清（8 輪以上問答）、高階流程圖、DBML 資料合約、9 點設計決策與理由、未來擴充摘要表、測試考量方向，皆已寫入 `docs/superpowers/specs/2026-07-08-conversation-management-design.md`。
  - 已完成：自我審查修正了 DBML 裡一處重複且表名不一致的 `Ref` 宣告；使用者事後再指出 DBML 缺少 `users` 表定義（造成懸空參照），已補上最小化 `users` table 示意（標註為既有表、非本次異動範圍）。
  - 已完成：設計文件已 git commit（commit `e3c74f5`）。
  - 待處理：使用者尚未完成「審閱已寫入的 spec 檔案」這一步（`/brainstorming` 流程要求使用者確認 spec 內容後才進入 `writing-plans`）。
- **待解決問題**：
  - PRD 其餘三項需求（AI 自動回覆流程、API 與管理介面、擴充性）尚未開始討論。
- **下一步指令建議**：接手的 AI 應該先請使用者審閱 `docs/superpowers/specs/2026-07-08-conversation-management-design.md`，確認無誤後呼叫 `writing-plans` 產出實作計畫；若使用者想繼續談其他需求，則回到 `/brainstorming` 流程處理 PRD 下一項需求。

---

# AI Context Handoff: AI 自動回覆流程（AI Auto-Reply Flow）設計討論

## 1. 任務摘要 (What & Flow)

- **目標**：針對 `prd.md` 第二項功能需求「AI 自動回覆流程」，設計非同步生成 AI 回覆的 Celery 任務與 AI 呼叫抽象層，同時檢查並修正第一項需求 spec（`2026-07-08-conversation-management-design.md`，下稱 spec1）裡明確標記「尚未設計」的重試機制與失敗轉真人規則。
- **成功指標**：產出一份經使用者逐步確認的設計文件（spec2），並回頭修正 spec1 裡與 spec2 衝突/過時的部分；使用者審閱後可進入 `writing-plans`。
- **邏輯流**：透過 `/brainstorming` 流程，先確認範圍界線（本次完全不談 API endpoint，只談 Celery 任務）→ 逐一釐清重試策略、失敗轉人工、AI Message 建立時機、AI 呼叫抽象層架構、歷史訊息查詢的一致性問題 → 分段呈現架構/流程/任務細節/測試考量並取得確認 → 寫入 spec2 → 回頭修正 spec1。
- **輸入**：`prd.md` 第二項需求文字、spec1 全文、liteLLM 官方文件（透過 subagent 研究）。
- **輸出**：
  - 新增 `docs/superpowers/specs/2026-07-09-ai-auto-reply-design.md`（spec2）
  - 修正 `docs/superpowers/specs/2026-07-08-conversation-management-design.md`（spec1：標註修正紀錄、更新流程圖說明、決策 6/7 補上修正備註）

## 2. 決策背景 (Why)

- **決策依據**：
  - **範圍排除 API endpoint**：PRD 把「提交查詢」「查詢回覆結果」寫在第二項需求裡，但使用者判斷這些 API 的實作細節（權限、序列化、分頁）應該留給第三項需求「API 與管理介面」一起講，這次只談 Celery 任務本身。
  - **AI Message(PENDING) 改為 API 同步建立**：原 spec1 流程圖是「非同步任務開始執行後才建立 AI Message」，會讓前端在 task 真正開始跑之前查不到任何 AI 訊息行（worker 忙、排隊中的空窗期）。改為 API 接到查詢當下就同步建好 USER + AI(PENDING) 兩筆 Message，AI Message 的 id 傳進 Celery task，task 只負責更新它。
  - **有限次數自動重試 + 失敗轉 `PENDING_HUMAN`**：補上 spec1 明確標記「尚未設計」的缺口——重試期間 Message 維持 `PENDING`（不新增 RETRYING 狀態，前端體感沒差別）；重試用盡才寫 `FAILED` 並自動把 `Conversation.status` 轉 `PENDING_HUMAN`。
  - **獨立 `ai_providers` app + 抽象介面（`generate`/`agenerate`/`stream`/`astream`/`batch_generate`）**：使用者計畫用 liteLLM 包裝真實呼叫，並另外設計一個獨立介面讓 liteLLM 實作與模擬用的 `DelayedFailureSimulator` 都能滿足它。命名選用貼近 liteLLM/OpenAI SDK 慣例（`generate`系列）而非 LangChain 的 `invoke` 系列，因為底層實作目標就是 liteLLM，命名一致可降低認知負擔（此結論來自派出的研究 subagent，發現 liteLLM 本身沒有正式 ABC/Protocol，是一組扁平函數，且內建 `mock_response` 參數可直接用於構造結構一致的模擬回應）。
  - **`DelayedFailureSimulator` 內部包一層 `litellm.completion(mock_response=...)`**：而非手刻假的 `ModelResponse` 結構，確保模擬回應與真實 API 回應結構完全一致，未來替換成真實 provider 時呼叫端不用改。
  - **Celery task 只傳 `ai_message_id`，不傳 `conversation_id` 或整包對話內容**：`ai_message_id` 可透過 FK 反查 `conversation_id`，資訊不會遺失；反之若只傳 `conversation_id`，當同一 Conversation 同時有多筆 `PENDING` AI Message 時會無法判斷該更新哪一筆。整包對話內容不當參數傳遞，因為 Celery 參數會序列化進 broker、且 task 真正執行時間可能晚於觸發時間，改成 task 執行時才即時查 DB 才能保證資料新鮮度。
  - **歷史查詢強制 `filter(status="completed")`**：使用者提出「如何確保拿到 PENDING 訊息時，其實歷史對話已經完成」的資料一致性疑慮。解法不是靠時間點檢查（有競態窗口），而是查詢條件本身做防禦性過濾——不論是否有其他流程違反「同一 Conversation 一次只能一則 PENDING」的業務規則，未完成/失敗的訊息永遠不會被當作上下文送進 LLM。
  - **任務執行採 `select_for_update()` 鎖 + 執行前檢查狀態（idempotency guard）**：防止同一任務被重複排程執行、或多個 worker 同時處理同一筆訊息的競態。
- **已排除方案**：
  - 這次一併設計「提交查詢」「查詢回覆結果」API 的高階行為——排除，範圍完全留給第三項需求。
  - 重試期間新增 `RETRYING` 狀態——排除，前端/管理者體感上跟 `PENDING` 沒有實際用途差異。
  - 重試次數用盡後 `Conversation.status` 保持 `OPEN` 不自動轉換——排除，會讓 `PENDING_HUMAN` 狀態變成永遠不會被觸發的死狀態。
  - Celery task 直接把整包對話內容當參數傳遞——排除，序列化成本高且有資料過期風險。
  - 只傳 `conversation_id` 給 task——排除，同一 Conversation 有多筆 PENDING 訊息時無法精確定位目標。
  - AI Provider 抽象介面命名採 LangChain 的 `invoke`/`ainvoke`——排除，底層實作目標是 liteLLM（OpenAI SDK 風格），命名不一致會增加認知負擔。
  - `Simulator` 自己手刻假的 response 結構，不依賴 liteLLM——排除，難以保證跟真實 API 結構一致。

## 3. 邊界與假設 (Boundary & Assumption)

- **範疇外事項**：本次設計**不涵蓋** API endpoint 實作與細節、Django Admin 介面——留給「API 與管理介面」需求。不包含實際的 Python/Celery 程式碼（使用者明確要求這階段只做設計文件，不落地實作）。
- **基礎假設**：
  - 假設「同一 Conversation 一次只能有一則 PENDING AI Message」這個業務規則會在未來的 API 層被 enforce（例如拒絕新請求或排隊），本次設計只做防禦性過濾（歷史查詢排除非 COMPLETED 訊息），沒有主動阻止規則被違反。
  - 假設訊息一旦建立即不可變（immutable）——使用者提出「使用者取消訊息或重新編輯」的延伸考量，經討論後判斷這是全新功能需求（PRD 未提及），列入未來擴充/邊界條件，本次不設計。
  - 假設 LLM KV cache 最佳化（prompt prefix 穩定性）暫不處理，與「訊息不可變」假設相輔相成，留待未來效能調優階段。
  - 假設 `AI_BACKEND`（litellm | simulator）是環境層級的全域設定，不放進 `SceneConfig.default_settings`（`SceneConfig` 只放業務參數如 model 名稱），這個切分未經使用者以外的人驗證。

## 4. 風險與壓力測試 (Failure & Robustness)

- **失敗路徑**：AI provider 呼叫失敗 → Celery 有限次數重試（3 次、exponential backoff + jitter）→ 仍失敗則 Message 標記 `FAILED`、Conversation 轉 `PENDING_HUMAN`。此路徑已設計但**未實作驗證**，重試次數/backoff 參數是否合理未經實測調校。
- **反例測試**：
  - 若「一次只能一則 PENDING」規則未來未被 API 層正確 enforce，歷史查詢的防禦性過濾（`filter(status="completed")`）可保證系統不會把未完成訊息送進 LLM context，但**不會**阻止規則被違反本身（例如浪費運算資源同時處理多筆查詢）——此為已知限制，非本次設計要解決的問題。
  - `select_for_update()` 鎖的併發安全設計目前只是文件層級的約定，未透過實際併發測試（例如兩個 worker 同時搶同一筆 task）驗證鎖是否真正生效。
- **抗壓能力**：AI 呼叫抽象層（`ai_providers` app）與 `conversations` app 解耦，未來要換真實 provider、加新 provider（例如直接接 OpenAI SDK 而非透過 liteLLM）、或加串流/批次功能，都只需在 `ai_providers` 內擴充，不影響 `conversations` 既有邏輯；但目前完全沒有實測過 `DelayedFailureSimulator` 的失敗機率分佈是否真的符合統計預期，也沒驗證過 liteLLM 版本升級是否會改變 `mock_response` 的行為。

## 5. 延續執行 (Continuity)

- **目前狀態**：
  - 已完成：範圍界定（排除 API）、重試/失敗轉人工策略、AI Message 建立時機修正、AI 呼叫抽象層架構（含派 subagent 研究 liteLLM 命名慣例與 `mock_response` 機制）、Celery 任務參數與併發安全設計、歷史查詢一致性問題討論，皆已寫入 `docs/superpowers/specs/2026-07-09-ai-auto-reply-design.md`。
  - 已完成：回頭修正 spec1（`2026-07-08-conversation-management-design.md`）——加註修正紀錄、流程圖說明、決策 6/7 補上修正備註，原文保留供歷史脈絡參考。
  - 已完成：spec2 自我審查（無 TBD/佔位文字、架構與流程/決策一致、範圍聚焦）。
  - 已完成：spec1、spec2 已 git commit。
  - 待處理：使用者尚未完成「審閱已寫入的 spec2 檔案」這一步（`/brainstorming` 流程要求使用者確認後才進入 `writing-plans`）；目前使用者選擇先不進入實作，改為繼續討論 PRD 第三項需求。
- **待解決問題**：
  - PRD 第三項需求「API 與管理介面」（提交查詢/查詢會話紀錄/更新場景設定 API、Django Admin 管理介面）與第四項「擴充性」尚未開始討論。
  - 「一次只能一則 PENDING AI Message」規則的 enforce 點（拒絕新請求還是排隊）需要在第三項需求討論時決定。
  - AI Provider 抽象介面的具體方法簽名（例如 `messages` 參數的確切格式）尚未定案，屬於實作階段才會確定的細節。
- **下一步指令建議**：接手的 AI 應該透過 `/brainstorming` 流程處理 PRD 第三項需求「API 與管理介面」，開始前建議先讀 spec1、spec2 全文，特別留意「同一 Conversation 一次只能一則 PENDING」規則的 enforce 責任已明確畫給這一項需求。使用者目前傾向先把四項需求都討論完、產出完整設計後才進入實作階段，暫不呼叫 `writing-plans`。
