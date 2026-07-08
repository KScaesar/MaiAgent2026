# Handoff：本機執行專案並確認 Admin 頁面

## 背景

專案是用 cookiecutter-django 產生的，但當初生成時**沒有帶出 Docker 相關檔案**——只有 `docker-compose.docs.yml`，缺少 `docker-compose.local.yml` 與 `compose/` 目錄。因此無法直接用 `docker compose up` 啟動整個專案（Django + Postgres + Redis + Mailpit）。

## 我做了什麼

### 1. 找回原始生成參數並重跑 cookiecutter

- 檢查了 `~/.cookiecutter_replay/cookiecutter-django.json`（cookiecutter CLI 的全域快取，記錄上次互動問答的答案），但發現裡面存的是**預設值**（`use_docker: "n"`、`use_celery: "n"` 等），跟目前專案實際的內容（`pyproject.toml` 有 celery、whitenoise，`.envs/.local/.django` 裡有 `USE_DOCKER=yes`，README 提到 Mailpit）對不上，不能直接拿來用。
- 改用**推測比對現有專案內容**的方式，手動組出一組參數（`use_docker=y`、`use_celery=y`、`use_mailpit=y`、`use_whitenoise=y`、`rest_api=DRF`、`postgresql_version=18`、專案名稱/slug 對齊現有專案等），用 `cookiecutter-django` 模板重新生成一份完整專案到暫存目錄（scratchpad），**不影響現有專案**。

### 2. 抽取 Docker 相關檔案回專案

從暫存目錄的生成結果中，只複製了 Docker/Compose 相關檔案回到專案，沒有動到任何既有程式碼：

- `docker-compose.local.yml`（新增）
- `compose/local/django/`（Dockerfile、start script、celery worker/beat/flower start script）
- `compose/production/django/entrypoint`（local Dockerfile 有引用到）
- `compose/production/postgres/`（Dockerfile 及備份/還原維護腳本，含你現在打開的 `yes_no.sh`）
- `.dockerignore`

複製前有用 `docker compose -f docker-compose.local.yml config` 驗證過設定檔語法正確，且確認裡面引用的 `./.envs/.local/.django`、`./.envs/.local/.postgres` 剛好對應到專案裡既有的環境變數檔案。

### 3. 啟動服務並跑起 Django

```bash
docker compose -f docker-compose.local.yml up -d --build postgres redis mailpit django
```

- 四個容器（postgres、redis、mailpit、django）皆成功啟動。
- Django 容器啟動時自動執行了 `python manage.py migrate`，所有 migration 皆成功套用。
- Django dev server 正常運作於 `http://localhost:8000`。

### 4. 建立超級使用者

透過 `docker compose exec` 進容器跑 Django shell 建立了一個 superuser：

- Email：`admin@example.com`
- 密碼：`AdminPass123!`

**注意**：`docker compose exec` 不會經過容器的 `/entrypoint` 腳本（該腳本負責把 `POSTGRES_*` 環境變數組成 `DATABASE_URL`），所以直接 exec 進去跑指令時預設會走 Unix socket 連線失敗。解法是額外用 `-e DATABASE_URL=...` 手動帶入完整連線字串。

### 5. 用瀏覽器驗證 Admin 頁面

用 `agent-browser` 實際打開瀏覽器操作：

1. 開啟 `http://localhost:8000/admin/`，確認登入頁正常渲染。
2. 用剛建立的帳密登入。
3. 確認成功導向 `http://localhost:8000/admin/`，畫面顯示 Site administration 首頁，包含 Accounts、Auth Token、Authentication and Authorization、MFA、Periodic Tasks 等區塊，代表登入與權限運作正常。

## 目前狀態

- Docker 服務仍在背景執行中（`postgres`、`redis`、`mailpit`、`django`）。
- Admin 頁面可正常存取：http://localhost:8000/admin/
- 測試帳號：`admin@example.com` / `AdminPass123!`

## 尚待你決定的事項

- 建立的 superuser 帳密目前只存在於本機測試用的資料庫，屬於暫時性測試帳號，正式環境請另外建立。
- 若不需要繼續跑，記得執行 `docker compose -f docker-compose.local.yml down` 停止並清掉容器（加 `-v` 會連同資料庫資料一起清掉）。
