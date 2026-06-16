# AI4BI — AI 協作指引

## 對話語言（最高優先）

- **與使用者對話、說明、回報一律使用繁體中文**（程式碼、commit message、識別字維持英文）。
- 技術名詞可保留英文，但句子用中文書寫,不要整段英文。

## 專案速覽

AI4BI 是自助式 AI 商業分析平台（Streamlit + Plotly + DuckDB）。入口 `ai4bi/ui/app.py`。

## 開發環境

- **Python 3.11**（對齊 CIM Hybrid Edge Platform 的 host 直譯器，避免版本漂移）。本機開發用 `.venv`（3.11）。
- 安裝：`pip install -e ".[dev,llm]"`
- 測試：`python -m pytest tests/ -q --ignore=tests/e2e`（非 e2e 全綠;e2e 需 live server，本機環境跑不動屬環境限制）。

## 工作慣例

- 每完成一個開發段落要 **test + commit + push**,不要累積。
- 改 Streamlit 子模組後要**完全重啟 server** 才會生效;`.streamlit/config.toml`(主題 chrome、表頭、字重)也是啟動時才讀。
- 配色/UI 設計要顧及對比:**深色底用白字、淺色底用深字**(見 `ai4bi/ui/theme.py` 的 `on_color`,依亮度自動選最高對比);主題系統有 6 組色盲安全配色,見 `docs/theme-ux-validation.md`。
- LLM 模式由環境變數控制:`LLM_MODE`(`mock`|`anthropic`)、`ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`;未設或出錯自動 fallback 回 mock。

## 與 CIM 平台整合

AI4BI 以 git submodule 掛進 CIM 平台(`nativeApp/sidecar/python-engine/vendor/AI4BI`),用「app 類型工具」單一畫面內嵌。更新方式:在 submodule 內 `git pull`(editable 安裝即時生效)。
