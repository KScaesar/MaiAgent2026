# AGENTS.md

## Python 使用規則

- 所有 Python 程式碼的撰寫、執行與依賴管理，一律使用 `uv`。
- 不得直接使用 `pip`、`poetry`、`conda` 或系統 Python 進行安裝或執行。
- Python 指令一律透過 `uv run` 執行。

### Shell Command Line Execution Rule

本專案環境由 `mise` 管理。執行任何指令前，請務必遵循 `mise` skill 中定義的「AI Agent Execution Pattern」，以確保環境正確載入：
```bash
[ "$MISE_FOR_AI" = "1" ] || { eval "$(mise env)" && export MISE_FOR_AI=1; }
<YOUR_COMMAND>
```

---

## 專案工具與環境

- **全域 CLI 工具管理**：
  - `cookiecutter` (版本 `1.7.0`)：已透過 `uv tool install "cookiecutter==1.7.0"` 安裝為全域執行工具，用於從專案範本生成程式碼。
