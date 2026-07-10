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

---

# AI Context Handoff: API 與管理介面（API & Admin Interface）設計討論

## 1. 任務摘要 (What & Flow)

- **目標**：針對 `prd.md` 第三項功能需求「API 與管理介面」，設計提交查詢、查詢會話紀錄、更新場景設定三支 REST API，補上 spec2 明確留下的缺口（「一次只能一則 PENDING AI Message」的 enforce 責任、前端如何取得非同步生成結果），並設計 Django Admin 管理介面。
- **成功指標**：產出一份經使用者逐步確認的設計文件（spec3），使用者審閱後可進入 `writing-plans` 或繼續討論 PRD 第四項需求。
- **邏輯流**：透過 `/brainstorming` 流程，先確認認證/授權模型（RBAC，比較自訂 role 欄位 vs Django Group/Permission）→ 逐一釐清三支 API 的細節（提交查詢的建立層次與併發控制、查詢會話紀錄的分頁/全文檢索、場景設定的修改歷程）→ 深入討論前端取得 AI 回覆結果的機制（使用者提出 SSE，過程中糾正了「用兩個 Celery task 轉發 SSE」的技術誤解，並比較「單一 channel 手動過濾」vs「Django Channels group」的路由設計，用 redis-cli 指令實例驗證後定案）→ 安全性/效能考量（rate limiting）→ Django Admin 範圍 → 分段呈現架構/流程/endpoint 清單/錯誤處理並取得確認 → 寫入 spec3。
- **輸入**：`prd.md` 第三項需求文字、spec1、spec2 全文。
- **輸出**：新增 `docs/superpowers/specs/2026-07-09-api-admin-design.md`（spec3）。

## 2. 決策背景 (Why)

- **決策依據**：
  - **RBAC 採 Django 內建 Group/Permission，不用自訂 role 欄位**：PRD 明確要求「業務人員能用 Django Admin 檢視管理對話記錄」，這正是 Group/Permission 系統的原生應用場景（Admin 本身就是用這套權限系統控制可見範圍），未來要加更細粒度權限不需要修改 model schema；自訂 role 欄位則需要手刻字串比對邏輯，且與 Admin 整合較弱。
  - **提交查詢 API 分成兩支**（`POST /api/conversations/` 建立對話、`POST /api/conversations/{id}/messages/` 提交訊息）：責任分離清楚，符合 REST 資源層級概念，避免單一 API 語意不單一（upsert 邏輯容易出錯處理）。
  - **409 Conflict 拒絕併發提交**（而非排隊）：實作最簡單、行為最可預測，補上 spec2 明確標記「規則本身的 enforce 點留給本需求」的缺口——本次設計主動在 API 層阻止規則被違反，而非僅依賴 spec2 的歷史查詢防禦性過濾。
  - **前端取得 AI 回覆結果改用 SSE + Django Channels group**（而非輪詢）：使用者一開始提出 SSE 構想，但對 Celery 生命週期有誤解（以為可以用第二個 Celery task 轉發 SSE 訊息給瀏覽器）——已在對話中糾正：Celery worker 不持有、也不可能持有瀏覽器的 HTTP/SSE 連線，兩者是完全不同的 process。真正可行的橋接方式是 Celery task 完成後 publish 事件到 Redis，由**持有該 SSE 連線的 ASGI process** 訂閱並轉發。
  - **Pub/Sub 路由採 Channels 內建 group 機制（每個 Conversation 一個 group），而非單一固定 channel + 手動過濾**：使用者一開始提出「單一固定字串 channel，payload 帶 conversation_id/user_id 供消費者自行過濾路由」，並自陳擔心「多消費者時不知道使用者連到哪個消費者」——這正是 Channels group 已經解決的問題。經解釋 group 底層是 Redis sorted set（`ZADD`/`ZRANGE`，成本等同一個 key，沒人訂閱時零成本），並用具體 `redis-cli` 指令（`ZADD`/`ZRANGE`/`RPUSH`/`BLPOP`）模擬驗證整個流程後，使用者確定改採 Channels group。
  - **架構上維持 WSGI + ASGI 並存**（而非全面轉 ASGI）：一般 REST API 不需要 async，維持既有 WSGI/Gunicorn 改動最小；只有需要長連線的 SSE 端點獨立跑在 ASGI，透過 `asgi.py` 的 `ProtocolTypeRouter` 依路徑分流。
  - **SSE 連線驗證採一次性短效 ticket（透過額外 API 換發），而非直接把長效 token 放 URL query param**：因為瀏覽器原生 `EventSource` 不支援自訂 `Authorization` header，必須透過 URL 傳遞身份資訊；但長效 token 若出現在 URL 容易被 log/瀏覽器歷史記錄留存造成重用風險，改為短 TTL（例如 60 秒）、用過即刪的 ticket，把風險窗口壓到最小。
  - **SSE 推送只包含 Message 層級狀態變化（completed/failed），不推送 `Conversation.status` 轉 `PENDING_HUMAN`**：使用者質疑「這樣使用者會不會忙等、不知道發生什麼事」——已澄清 `FAILED` 事件本身就會推送給使用者（帶 error_message），使用者不會不明所以；`PENDING_HUMAN` 是給客服/管理者看的內部分派旗標，不是使用者關心的資訊，兩者受眾不同故分層。
  - **提交查詢 API 加 DRF throttling**：因為每次提交都會觸發 Celery task 呼叫外部 AI API（有金錢成本、佔用 worker），需防止高頻請求造成帳單暴增或隊列堵塞——此點使用者一開始沒理解「為什麼提交查詢會觸發 AI API 呼叫」，經解釋 spec2 的流程（API 同步建 Message → 觸發 Celery task → task 呼叫 ai_providers.generate）後才確認需要。
  - **列表查詢採 cursor-based pagination**：Conversation/Message 資料只會持續新增，cursor pagination 避免 offset pagination 在資料量增長/新資料插入時的重複遺漏問題，效能不隨頁數加深而下降。
  - **場景設定 API 不記修改歷程/審核**：PRD 未要求審核流程，先維持簡單，未來若需要稽核可再引入 `django-simple-history`，不影響現有 API 介面。
  - **Django Admin 管理範圍：客服人員只能改 `Conversation.status`，訊息內容不可編輯**：延續 spec2「訊息一旦建立即不可變（immutable）」的假設，PRD 提到的「監控與調整」具體收斂為狀態調整（例如手動將 `PENDING_HUMAN` 改回 `OPEN`/`CLOSED`），不開放編輯歷史訊息內容，維持稽核完整性。
- **已排除方案**：
  - 提交查詢 API 合一支自動 upsert Conversation——排除，API 語意不單一、錯誤處理邏輯較粗糙。
  - 併發提交採「接受並排隊」——排除，會推翻 spec2 當初「同一時間點只能一則 PENDING」的假設，需要重新設計歷史查詢過濾邏輯。
  - SSE 用兩個 Celery task 轉發訊息給瀏覽器——排除，技術上不可行（Celery worker 沒有、也不可能拿到瀏覽器的連線 socket）。
  - SSE pub/sub 用單一固定 channel + payload 帶 id 手動過濾——排除，每個事件廣播給所有連線造成無關流量浪費，且未解決多 consumer instance 時的路由問題（使用者自己也點出這個未解問題）。
  - 全面轉 ASGI（拿掉 WSGI）——排除，一般 REST API 不需要 async，全面轉換是不必要的架構變動。
  - SSE 直接用長效 token 當 URL query param——排除，token 出現在 URL/log 中的重用風險較高。
  - `PENDING_HUMAN` 轉換也透過 SSE 推送給使用者——排除，這是給客服/管理者看的內部狀態，非使用者關心的事件，混在一起會讓 SSE payload 語意複雜。
  - SceneConfig 更新加修改歷程/審核機制——排除，PRD 未要求，先求簡單，需要時可後補不影響介面。

## 3. 邊界與假設 (Boundary & Assumption)

- **範疇外事項**：本次設計**不涵蓋** AI 呼叫細節與 Celery 任務內部邏輯（見 spec2）、資料模型定義本身（見 spec1）、PRD 第四項「擴充性」需求（將另外討論）。不包含實際的 Python/DRF/Channels 程式碼。
- **基礎假設**：
  - 假設 Redis channel layer（`channels_redis`）的 group 機制行為與文件描述一致（ZADD/ZRANGE/RPUSH/BLPOP 模式）——這是根據 `channels_redis` 已知實作原理的說明，並非在本次對話中實際跑過 Python/Channels 驗證，僅用 redis-cli 指令模擬邏輯層面驗證，未跑過真正的 Channels consumer。
  - 假設 SSE 連線驗證用的 one-time ticket 存於 Redis、TTL 60 秒足夠涵蓋「換票到建立 SSE 連線」的正常時間差，未實測極端網路延遲下是否會過期失敗。
  - 假設「客服人員」與「管理者」的 Group 劃分（`customer_service`、`admin`）足以涵蓋 PRD 描述的業務人員需求，未考慮更細的部門/團隊層級隔離（PRD 未提及多租戶情境）。
  - 假設全文檢索 `?q=` 參數的查詢實作（`SearchQuery` 比對 `search_vector`）不需要額外處理中文分詞（PostgreSQL 預設 `simple`/`english` config 對中文支援有限），此細節留待實作階段處理。

## 4. 風險與壓力測試 (Failure & Robustness)

- **失敗路徑**：
  - 提交查詢遇到已有 PENDING AI Message → 回 409，前端需自行處理重試/等待邏輯，此行為僅在設計文件層級約定，未實測前端實際串接體感。
  - AI 生成重試用盡失敗 → Message 轉 FAILED 並透過 SSE 推送，`Conversation.status` 轉 `PENDING_HUMAN` 不推送——此分層設計已與使用者確認合理，但依賴「前端會正確處理 `status=failed` 事件並顯示錯誤訊息」這個前端行為假設，本次設計未涉及前端實作。
- **反例測試**：
  - 目前設計文件未討論「SSE 連線中途斷線後前端如何重新換票、重新連線」的重試策略細節，只設計了初始連線的驗證流程與初始快照時序，斷線重連屬於實作階段需要補的細節。
  - Ticket 一次性機制依賴 Redis 操作的原子性（驗證+刪除需為單一操作避免 race condition，例如用 `GETDEL` 或 Lua script），設計文件僅提及「驗證通過後立即刪除」，未明確指定要用哪個 Redis 原子操作實現，此為實作階段的坑。
- **抗壓能力**：
  - Channels group 機制設計上天生支援多 consumer instance 水平擴展（Redis 幫忙做路由），但完全沒有實際壓測過高並發連線下的表現，已列入 spec3「未來擴充摘要」。
  - `api` app 與 `realtime` app 皆依賴 `conversations` app 的 model、彼此獨立，理論上可分別擴充，但兩者之間目前沒有實際程式碼驗證過整合是否順暢（例如 Channels consumer 如何共用 DRF 的權限檢查邏輯，避免重複寫兩份權限判斷）。

## 5. 延續執行 (Continuity)

- **目前狀態**：
  - 已完成：RBAC 模型、三支 API 細節、SSE+Channels 即時推送架構（含糾正使用者對 Celery 生命週期的誤解、用 redis-cli 驗證 group 機制）、安全性/效能考量、Django Admin 範圍，皆已寫入 `docs/superpowers/specs/2026-07-09-api-admin-design.md`。
  - 已完成：spec3 自我審查（無 TBD、架構與流程/決策一致、範圍聚焦在 API+Admin）。
  - 已完成：spec3 已 git commit（commit `cf00994`）。
  - 待處理：使用者尚未完成「審閱已寫入的 spec3 檔案」這一步（`/brainstorming` 流程要求使用者確認後才進入 `writing-plans`）。
- **待解決問題**：
  - PRD 第四項需求「擴充性」（多 AI 模型/複雜路由邏輯、動態調整權重）尚未開始討論。
  - SSE 斷線重連策略、ticket 刪除的原子性實作方式，尚未定案，留待實作階段或後續補充討論。
  - 全文檢索中文分詞支援程度未驗證。
- **下一步指令建議**：接手的 AI 應該先請使用者審閱 `docs/superpowers/specs/2026-07-09-api-admin-design.md`，確認無誤後可呼叫 `writing-plans` 產出實作計畫；若使用者想繼續談，則透過 `/brainstorming` 流程處理 PRD 第四項需求「擴充性」。開始前建議先讀 spec1/spec2/spec3 全文，特別留意 spec3 裡「多 AI 模型/路由邏輯」目前僅停留在 spec1 的 `SceneConfig.default_settings` JSONField 彈性欄位層級，尚未有具體路由機制設計，這正是第四項需求要解決的核心問題。

---

# AI Context Handoff: 擴充性（Scalability）— 多 AI 模型路由設計討論

## 1. 任務摘要 (What & Flow)

- **目標**：針對 `prd.md` 第四項功能需求「擴充性」與附加挑戰「多 AI 模型支持」，設計一個機制讓每個 Scene 可設定多個候選 AI 模型，由系統依規則自動選擇並容錯，管理人員可動態調整權重與路由邏輯；同時把 PRD「進階搜尋功能」附加挑戰的涵蓋狀況（已在 spec1/spec3 完成）記錄進本輪討論。
- **成功指標**：產出一份經使用者逐步確認的設計文件（spec4），並回頭修正 spec2 裡與新設計衝突的 `AIProvider` 介面/Celery 重試設計；使用者審閱 spec4 後可決定是否進入 `writing-plans`。
- **邏輯流**：透過 `/brainstorming` 流程，先確認範圍深度（要含具體路由機制，非僅文字帶過）→ 澄清「多模型路由」概念本身（使用者一開始不理解此詞）→ 逐一定案資料模型歸屬（新增 `ModelRoute` model，非塞進既有 JSONField）→ 選模演算法（加權隨機、分層優先度、跨層 fallback）→ 澄清「根據場景自動選模型」是否等於「AI 自動判斷場景」（使用者提出質疑，確認場景仍延續 spec1 假設為外部指定屬性）→ 派 subagent 研究 `litellm.Router` 官方能力 → 使用者要求改用 Router 取代手刻演算法、術語對齊套件用法 → 用 before/after 程式碼具體說明 `AIProvider` 介面改動 → 定案並寫入 spec4、回頭修正 spec1/spec2/spec3。
- **輸入**：`prd.md` 第四項需求文字與附加挑戰、spec1/spec2/spec3 全文、liteLLM 官方文件（透過 subagent 研究 `litellm.Router`）。
- **輸出**：
  - 新增 `docs/superpowers/specs/2026-07-10-scalability-model-routing-design.md`（spec4）
  - 修正 `docs/superpowers/specs/2026-07-08-conversation-management-design.md`（spec1：決策 3、未來擴充摘要表補修正紀錄）
  - 修正 `docs/superpowers/specs/2026-07-09-ai-auto-reply-design.md`（spec2：`AIProvider` 介面、`factory.get_provider`、Celery 重試設計皆補修正紀錄，說明改由 `litellm.Router` 取代）
  - 修正 `docs/superpowers/specs/2026-07-09-api-admin-design.md`（spec3：Django Admin 章節補 `SceneConfigAdmin`/`ModelRoute` inline 說明）

## 2. 決策背景 (Why)

- **決策依據**：
  - **範圍含具體路由機制，而非僅文字帶過**：PRD 主要需求段落只寫「設計時考慮可擴充性」，但附加挑戰明確要求「設計一個機制」，使用者選擇把附加挑戰的具體要求一併做完，而非留白。
  - **新增獨立 `ModelRoute` model，與 `SceneConfig` 一對多關聯**：比起把候選清單塞進既有 `SceneConfig.default_settings` JSONField，結構化欄位讓管理人員能在 Django Admin 直接編輯權重/啟用狀態，也方便查詢統計，不用手改 JSON 結構。
  - **改採 `litellm.Router` 取代手刻選模演算法**：派 subagent 研究後發現 `Router` 的 `order`（分層優先度）與 `weight`（層內加權隨機）參數幾乎完全對應原本手動設計的「分層優先度 + 層內加權隨機 + 跨層 fallback」語意，且內建 failover（`enable_weighted_failover`）。使用者判斷應直接依賴套件既有實作、術語也對齊套件用法（`order`/`weight`，不自創 `priority` 等詞），避免重複造輪子與額外測試維護成本。
  - **失敗處理改用 Router 預設行為（一失敗立即換同層下一候選）**：原本讨論中曾定案「同一模型重試到上限才換下一個」，但 Router 官方預設行為是一失敗就換候選，並非對同一 deployment 先重試多次。使用者選擇改採 Router 開箱即用行為，取代原先定案（記錄於已排除方案，避免文件內部矛盾）。
  - **拿掉 Celery 層 `autoretry`**：Router 內部的跨模型 failover 已是完整的失敗容錯機制；若再疊加整流程層級的 Celery 重試，等於把「所有候選都試過仍失敗」的流程原封不動重跑一次，對系統性故障（如 API 本身掛掉）沒有幫助，只會拉長延遲。此為對 spec2 的實質修正，非僅補充。
  - **`AIProvider.agenerate` 拿掉 `model` 參數**：因為選模資訊的「決定時機」從「呼叫當下由外部傳入字串」變成「建構 provider 時，依 DB 裡的 `ModelRoute` 資料組出 `Router` 設定」；一個 Scene 現在可能對應多個模型，一個字串參數已經裝不下這個資訊量。此為對 spec2 介面簽名的具體修正，已用 before/after 程式碼向使用者展示。
  - **`ModelRoute` 只透過 Django Admin inline 管理，不開額外 DRF API**：目前唯一情境是「管理人員後台手動操作」，Django Admin 內建的 inline 編輯機制已足夠，不需要多寫 serializer/view；spec3 既有的「更新場景設定」API 服務的是前端/其他系統的程式化呼叫情境，兩者受眾不同。
  - **`Message` 新增 `model_used` 欄位**：記錄實際成功呼叫的模型名稱（取自 liteLLM `ModelResponse.model`），供日後分析各模型使用比例/成功率，也是管理人員調整權重的參考依據。
  - **模型識別直接存 litellm 相容字串，不另建 `AIModel` 登錄表**：現階段候選模型數量有限，額外一張表的驗證好處不足以抵銷維護成本（YAGNI）。
  - **不含「回覆模板」路由**：PRD 附加挑戰同時提到模型與模板，但使用者選擇這次只做模型路由，模板路由涉及不同的 prompt 策略設計，範圍不同，留待未來需求。
  - **場景判定維持 spec1 既有假設**：使用者一度誤以為「自動選擇模型」暗示系統要用 AI 重新判斷這次對話屬於哪個場景；經釐清後確認場景仍是建立 Conversation 時外部指定的固定屬性，本次只自動化「已知場景 → 選模型」這一步。
- **已排除方案**：
  - 僅論述現有設計（`SceneConfig.default_settings` JSONField）為何已具擴充性，不設計新機制——排除，使用者要求含具體路由機制。
  - 直接擴充 `SceneConfig.default_settings` JSON 結構存路由清單——排除，Admin 編輯 JSON 體驗差，也難做欄位層級驗證。
  - 完全手刻加權隨機 + 分層 + fallback 演算法——排除，`litellm.Router` 已提供且測試過相同邏輯。
  - 同一模型重試到上限才 fallback 換下一個——排除，改採 Router 預設「一失敗就換候選」。
  - 保留 Celery autoretry 疊加在 Router fallback 之上——排除，對系統性故障沒有幫助，只拉長延遲。
  - Fallback 深度限制「最多跨 2 個 priority 層」——排除（此為討論中途的暫定決策，改用 Router 原生機制後不再由程式碼限制層數，改為完全交給管理人員透過 `ModelRoute` 筆數決定，避免文件前後矛盾）。
  - 新增 `AIModel` 登錄表，`ModelRoute` 用 FK 引用——排除，候選模型數量有限，多一張表不划算。
  - `ModelRoute` 調整也開放 DRF API——排除，目前只有後台手動操作情境，Admin inline 已足夠。
  - AI 自動推論場景——排除，延續 spec1 假設，場景是外部指定的固定屬性。
  - OpenRouter（託管閘道服務）作為多模型路由方案——排除（subagent 研究後提出），路由邏輯會落在第三方雲端服務，與「管理人員在自己 Django Admin 改權重」的需求衝突。

## 3. 邊界與假設 (Boundary & Assumption)

- **範疇外事項**：本次設計**不涵蓋**「回覆模板」路由、AI 自動分類/推論場景、`ModelRoute` 的程式化（DRF API）調整介面。PRD 附加挑戰「進階搜尋功能」已由 spec1/spec3 涵蓋，本文件僅記錄對照關係，不重複設計。
- **基礎假設**：
  - 假設每次 Celery task 執行時即時從 `ModelRoute` 資料表重建 `litellm.Router` 實例（而非常駐 process 內快取），換取管理人員改權重後「即時生效」，但犧牲一點點效能（多一次 DB 查詢 + 物件建構），本次設計不做快取最佳化。
  - 假設 `model_group` 命名 `f"scene-{scene.id}"` 與 Scene 一對一綁定；若未來需要多個 Scene 共用同一組路由設定，需要重新設計對應關係。
  - 假設 `litellm.Router` 的 `enable_weighted_failover` 行為與官方文件描述一致（同層一失敗即換候選，同層試完才跨層）——這是根據 subagent 研究官方文件與原始碼得出的結論，並未在本次對話中實際執行 Python 程式碼驗證，也未驗證同層只剩一個候選時的 edge case 行為。
  - 假設同一個 Scene 底下允許同一模型出現在不同 `order` 層而不加唯一性限制，目前無明確需求會用到這個彈性，但也不主動禁止（YAGNI）。

## 4. 風險與壓力測試 (Failure & Robustness)

- **失敗路徑**：`litellm.Router` 把某 Scene 底下所有已啟用的候選模型（依 order 分層、層內加權隨機）都試過仍失敗後才拋出例外，Celery task 捕捉到即直接判定 `Message.status=FAILED`、`Conversation.status=PENDING_HUMAN`，不再整流程重跑。此路徑已設計但**未實作驗證**，Router 內部 failover 的實際次數/延遲表現未經實測。
- **反例測試**：
  - 若某個 Scene 只設定一筆 `ModelRoute`（單一候選），Router 的分層/加權邏輯退化成單模型直接呼叫，理論上行為應與 spec2 原始設計等價，但本次未實測驗證這個邊界情況。
  - Router 官方文件描述的「靜態 `model_list`」與本設計「每次 task 動態重建」的搭配方式，未實際跑過 Python/litellm 驗證是否有預期外的初始化成本或行為差異，僅為文件層級推論。
- **抗壓能力**：`ModelRoute` 與既有 `SceneConfig`/`Conversation`/`Message` 解耦，新增/停用/調整候選模型都只需改 `ModelRoute` 資料，不影響既有資料結構；但目前完全沒有實測過同一 Scene 底下候選模型數量很多（例如 10+ 筆）時，Router 建構與選模的效能表現。

## 5. 延續執行 (Continuity)

- **目前狀態**：
  - 已完成：範圍確認（含具體路由機制）、「多模型路由」概念澄清、資料模型設計（`ModelRoute`）、選模演算法定案（改採 `litellm.Router`，術語對齊 `order`/`weight`）、失敗處理與 Celery 重試簡化、`AIProvider` 介面修正（含 before/after 程式碼展示）、Admin 管理方式、`Message.model_used` 欄位，皆已寫入 `docs/superpowers/specs/2026-07-10-scalability-model-routing-design.md`。
  - 已完成：spec4 自我審查時發現並修正一處內部矛盾——「fallback 最多跨 2 個 priority 層」的暫定決策與後續採用 Router 原生機制（不限層數，改由管理人員設定筆數決定）衝突，已在文件內加註取代說明。
  - 已完成：回頭修正 spec1（決策 3、未來擴充摘要表）、spec2（`AIProvider` 介面簽名、`factory.get_provider`、Celery 重試策略三處補修正紀錄）、spec3（Django Admin 章節補 `SceneConfigAdmin`/`ModelRoute` inline）。
  - 已確認：使用者看過 handoff 記錄的進度後，確定要 commit 這次的異動（新增 spec4 + 修正 spec1/spec2/spec3），準備進行 git commit。
  - 待處理：使用者尚未完成「審閱已寫入的 spec4 檔案」這一步（`/brainstorming` 流程要求使用者確認後才進入 `writing-plans`）——commit 只是把設計文件存進版本控制，不等於使用者已核准內容，仍需走完審閱步驟才能進 `writing-plans`。
- **待解決問題**：
  - `litellm.Router` 的 `enable_weighted_failover` edge case（同層剩一個候選、`model_list` 動態重建的初始化成本）尚未實測驗證。
  - PRD 四項功能需求皆已完成設計討論（對話管理、AI 自動回覆流程、API 與管理介面、擴充性），下一步理論上可進入 `writing-plans` 產出實作計畫，但需使用者先逐一審閱四份 spec。
- **下一步指令建議**：commit 完成後，接手的 AI 應請使用者逐一審閱四份 spec（尤其是 spec4，這是最新產出、尚未經確認），確認無誤後可呼叫 `writing-plans` 產出實作計畫——這將是 PRD 四項功能需求首次全部進入實作階段的時間點。若使用者要求修改設計內容，需重新走 spec 自我審查再請使用者確認。
