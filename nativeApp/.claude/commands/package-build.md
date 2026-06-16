# /package-build — 打包 CIM Hybrid Edge Platform

## 說明

此 skill 執行完整的打包流程，輸出一個 **x64 portable exe**，使用者不需安裝 Python 或 Node.js。

流程：
1. PyInstaller 編譯 engine.exe（內含 Python runtime + Streamlit + 所有模組）
2. 清理暫存檔案
3. 執行測試確認無誤
4. **取得自帶 Python**（standalone 3.11，供 per-tool venv 用）
5. 建置 Electron portable 安裝檔（x64）

> **自帶 Python（per-tool 相依用）**：frozen `engine.exe` 內建的 Python 唯讀、無法 `-m venv`，
> 所以宣告 `requires:` 的工具需要一支外部 real Python 來建隔離 venv。release 透過
> `scripts/win/fetch-standalone-python.ps1` 取得可重定位的 **python-build-standalone 3.11**
> 並由 electron-builder 打進 `resources/python/`；`main.js` 啟動 engine 時注入 `CIM_PYTHON`。
> 這讓**乾淨工廠機（沒裝 Python）也能用自帶相依的工具**。`build-release.bat` 已含此步驟。
> 版本鎖 3.11（須與 engine.exe 對齊）。詳見 [`docs/platform/per-tool-dependencies.md`](../../docs/platform/per-tool-dependencies.md)。

執行前請確認（Build machine）：
- Python 3.11+（含所有 `requirements.txt` 依賴）
- Node.js 18+
- `pip install pyinstaller`

> **快速打包**：直接執行 `build-release.bat`（已內建完整流程，預設 x64）

---

## 步驟 0：Pre-flight 檢查

```bash
test -d apps/host-electron/node_modules && echo "✅ host-electron node_modules 存在" || echo "❌ 請先 npm install"
test -d apps/portal-react/node_modules  && echo "✅ portal-react node_modules 存在"  || echo "❌ 請先 npm install"
test -f sidecar/python-engine/dist/engine.exe && echo "✅ 上次 engine.exe 存在（可跳過步驟 0.5）"
```

---

## 步驟 0.5：編譯 Python Engine（必須每次重跑）

```bash
cd sidecar/python-engine
python -m PyInstaller engine.spec --clean --noconfirm
```

`engine.spec` 的 `datas` 會把以下目錄一起打入 engine.exe：

| 目錄 | 說明 |
|------|------|
| `tools/` | Streamlit runner 腳本 |
| `scripts/` | 所有模組（module_001–025+） |
| `annotation/` | Annotation 領域服務 |
| `cim_platform/` | 通用平台介面（connector、tenant） |
| `sheets/` | Sheet workflow YAML 定義 |

確認輸出：
```bash
test -f sidecar/python-engine/dist/engine.exe && echo "✅ engine.exe 已生成" || echo "❌ PyInstaller 失敗"
```

---

## 步驟 1：清理暫存與快取

```bash
find sidecar/python-engine -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find sidecar/python-engine -name "*.pyc" -delete 2>/dev/null || true
rm -rf sidecar/python-engine/.pytest_cache
rm -rf tmp release
```

---

## 步驟 2：執行 Python 單元測試

```bash
cd sidecar/python-engine
python -m pytest tests/ -q --tb=short
```

**期望結果**：全部 pass，0 failed。

---

## 步驟 3：建置 React Portal

```bash
cd apps/portal-react
npm run build
```

---

## 步驟 3.5：取得自帶 Python（standalone 3.11）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\fetch-standalone-python.ps1
```

把可重定位的 Python 3.11 放到 `apps/host-electron/python-runtime/python/`，下一步 electron-builder
會經 `extraResources` 複製進 `resources/python/`。冪等（已存在則略過，`-Force` 可重抓）。

---

## 步驟 4：打包 Electron（x64 Portable）

```bash
cd apps/host-electron
npm run package:portable:x64
```

**輸出**：`release/CIM Hybrid Edge Platform *.exe`（x64，可直接給使用者）

---

## 步驟 5：驗收

確認 `release/CIM Hybrid Edge Platform *.exe` 存在，大小約 400–600 MB。

用 7-Zip 開啟 exe，確認以下路徑存在：
- `resources/engine/engine.exe`
- `resources/sidecar-source/scripts/`
- `resources/sidecar-source/plugins/`（labeling 等 plugin）
- `resources/sidecar-source/core/`
- `resources/sidecar-source/sheets/`
- `resources/python/python.exe`（自帶 standalone Python，per-tool venv 用）

驗自帶相依（per-tool venv）端到端：啟動安裝後的 app，跑一個宣告 `requires:` 的工具，
確認 `<安裝目錄>/.tool-venvs/<tool_id>/` 被建出且相依可 import（engine.log 有建 venv 記錄）。

---

## engine.exe 架構說明

使用者執行時：
```
CIM Hybrid Edge Platform.exe
  → Electron（UI）
  → engine.exe（FastAPI server，包含 Python runtime）
       → engine.exe --run-streamlit-script ...（子程序，同一個 exe）
```

**Streamlit 子程序使用 engine.exe 自我呼叫**，使用者不需要安裝 Python。

---

## 常見問題

### 打包出來是 arm64 而不是 x64
確認使用 `package:portable:x64` 而非 `package:portable`。

### `engine.exe` 執行後找不到模組
確認 `engine.spec` 的 `datas` 包含 `annotation/`、`cim_platform/`、`sheets/`，重跑 PyInstaller。

### LabelMe Dino 警告（`file source doesn't exist`）
非必要工具，不影響主功能。若需要，先在 `LabelMe_Dino/` 執行其 PyInstaller 打包。

### 測試失敗
確認 Python 版本 >= 3.11，並 `pip install -r sidecar/python-engine/requirements.txt`。
