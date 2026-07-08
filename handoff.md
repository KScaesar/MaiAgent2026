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
