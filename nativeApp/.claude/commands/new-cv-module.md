# /new-cv-module — 建立新 CV 模組骨架

## 框架契約

CIM CV 框架的每個模組遵循三層契約：

| 層 | 檔案 | 必須實作 | 禁止 |
|----|------|----------|------|
| Input | `{ID}_input.py` | `render_input() -> dict` | — |
| Process | `{ID}_process.py` | `execute_logic(params: dict) -> dict` | `import streamlit` |
| Output | `{ID}_output.py` | `render_output(result: dict) -> None` | — |

框架執行順序：`render_input()` → 使用者按「▶ 執行」→ `execute_logic(params)` → `render_output(result)`

---

## 輸入參數

執行此 skill 時，先詢問使用者以下資訊：

1. **模組 ID**（`module_NNN` 格式）：確認不與現有資料夾重複，執行 `ls sidecar/python-engine/scripts/` 檢查
2. **模組名稱**（中文）：顯示於選單，例如「輪廓偵測」
3. **Domain**：`cv` / `edge` / `annotation` / `pipeline` / 其他
4. **Input 描述**：使用者在 Input 頁籤看到什麼、輸入什麼
5. **Process 描述**：純運算邏輯做什麼（禁止 Streamlit）
6. **Output 描述**：`render_output` 要顯示什麼
7. **是否需要 SQLite 持久儲存**：是 → 生成 DB 樣板
8. **是否需要查詢其他模組的 DB**：是 → 生成查詢樣板

---

## 生成的檔案結構

```
sidecar/python-engine/scripts/module_{NNN}/
├── __init__.py              ← MODULE_NAME = "{模組名稱}"
├── plugin.yaml              ← ★ 模組的唯一真相來源（取代 engine.py 手動 seed）
├── {NNN}_input.py           ← render_input() -> dict
├── {NNN}_process.py         ← execute_logic(params) -> dict  （無 streamlit）
├── {NNN}_output.py          ← render_output(result) -> None
└── {NNN}_process_test.py    ← pytest，至少 8 個測試
```

---

## ★ plugin.yaml — 必填，取代 engine.py 手動 seed

**重要改變**：自 2026-05 起，engine.py 在啟動時自動掃描所有 `scripts/*/plugin.yaml`。
新模組只需建立 `plugin.yaml`，**不需要修改 engine.py**。

```yaml
id: module_{NNN}
vendor: cimcore                  # 核心模組用 cimcore；外部貢獻者用 partner_{github_id}
domain: cv                       # cv | edge | annotation | pipeline
name: {模組名稱}                  # 顯示在 Portal 選單的中文名稱
version: "1.0.0"
category: module
description: {一句話說明功能}
author: {作者名稱}
enabled: true                    # false = 停用（不出現在選單）
tags: [tag1, tag2]
runner: cv_framework             # 固定填 cv_framework
input_file: {NNN}_input.py
output_file: {NNN}_output.py
process_file: {NNN}_process.py
aliases: []                      # 未來 ID 重命名時填舊 ID，保持向下相容
```

engine.py 啟動時自動從 yaml 讀取 `id`、`name`、`enabled`、`vendor`、`domain`，
直接寫入 DB。**不需要手動加 INSERT seed 或修改 enabled 清單**。

---

## 必讀：核心規則

### 1. JSON 序列化限制（最重要）

`execute_logic()` 的回傳值會透過 JSON 傳給 `render_output()`。

**允許**：`str`, `int`, `float`, `bool`, `list`, `dict`, `None`

**禁止**：
- `bytes` → 改用 `base64.b64encode(data).decode("ascii")`
- `numpy.ndarray` → 改用 `data.tolist()` 或序列化為 base64
- `datetime` → 改用 `dt.isoformat()` 字串

```python
# ✅ 正確：bytes 轉 base64 字串
import base64
return {
    "image_b64": base64.b64encode(image_bytes).decode("ascii"),
}

# ❌ 錯誤：直接回傳 bytes
return {"image_bytes": image_bytes}
```

### 2. SQLite 持久儲存

DB 路徑必須在**呼叫時**解析，不能在 import 時解析（否則 pytest monkeypatch 無效）：

```python
import os
from pathlib import Path

def _db_path() -> Path:
    return Path(os.environ.get("CIM_LOG_DIR", "/tmp")) / "my_records.sqlite"
```

DB 遷移使用 PRAGMA 而非直接 ALTER（不會因欄位已存在而報錯）：

```python
def _ensure_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS my_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ...
    )""")
    existing = {r[1] for r in conn.execute("PRAGMA table_info(my_records)").fetchall()}
    if "new_column" not in existing:
        conn.execute("ALTER TABLE my_records ADD COLUMN new_column TEXT")
```

### 3. 影像處理

上傳影像在 process 層用 `PIL` 或 `cv2` 處理：

```python
from PIL import Image
import io

def execute_logic(params: dict) -> dict:
    file_bytes = params.get("file_bytes")
    if not file_bytes:
        return {"error": "no_image"}

    img = Image.open(io.BytesIO(file_bytes))
    w, h = img.size
    image_name = params.get("image_name", "image.png")

    buf = io.BytesIO()
    result_img.save(buf, format="PNG")
    return {
        "image_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "image_name": image_name,
        "image_width": w,
        "image_height": h,
    }
```

**input 層**：從 `st.file_uploader` 取 bytes 和檔名：

```python
uploaded = st.file_uploader("上傳影像", type=["jpg","jpeg","png"])
file_bytes = uploaded.read() if uploaded else None
image_name = uploaded.name  if uploaded else ""
return {"file_bytes": file_bytes, "image_name": image_name, ...}
```

### 4. 成功 / 失敗通知

使用 `st.toast`，不使用 `st.success`（後者佔版面）：

```python
st.toast("儲存成功！", icon="✅")
st.toast("儲存失敗", icon="❌")
```

### 5. 日期區間選擇

使用兩個分開的 `st.date_input`，或直接用 `shared/ui_components.py` 的 `date_input_range()`：

```python
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ui_components",
    Path(__file__).resolve().parent.parent / "shared" / "ui_components.py"
)
_ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ui)

def render_input() -> dict:
    date_from, date_to = _ui.date_input_range()
    return {"date_from": str(date_from), "date_to": str(date_to)}
```

### 6. 影像在表格中的呈現

不要把 `st.image` 放在 `st.columns` 的 table cell 裡。表格只顯示文字，點擊欄位開啟 `@st.dialog`：

```python
@st.dialog("影像預覽", width="large")
def _show_preview(rec: dict) -> None:
    image_bytes = base64.b64decode(rec["image_b64"]) if rec.get("image_b64") else None
    if image_bytes:
        st.image(image_bytes)

def _data_row(rec: dict) -> None:
    cols = st.columns([...])
    if cols[1].button(rec.get("image_name", "檢視"), key=f"view_{rec['id']}"):
        _show_preview(rec)
```

### 7. postMessage 給 Portal（如需導航）

若模組執行完需要跳到另一個模組：

```python
import json
import streamlit.components.v1 as components

def _post_message(msg_type: str, payload: dict) -> None:
    blob = json.dumps({"type": msg_type, "source": "cim-platform", "payload": payload, "_cim": True})
    components.html(f"<script>window.top.postMessage({blob}, '*');</script>", height=0)

# 跳到指定模組的 input
_post_message("SWITCH_TAB", {"plugin_id": "module_012", "tab": "input"})
```

**注意**：`source: "cim-platform"` 為必填，且訊息 type 必須在 `shared-protocol/src/index.js` 的 `MessageTypes` 中。

### 8. 載入 shared 模組

避免依賴 `sys.path`，改用 `importlib.util`：

```python
import importlib.util
from pathlib import Path

def _load_shared(name: str):
    path = Path(__file__).resolve().parent.parent / "shared" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

### 9. Navigation race condition（polling 覆蓋問題）

Portal 每 2 秒 polling 一次 result file mtime。若模組執行後需要跳頁，必須在 sheet_runner 發送
`SWITCH_TAB`。Portal 的 `EXECUTE_START` handler 已設 10 秒 suppression，`SWITCH_TAB` handler
再延長 6 秒，合計保護約 16 秒不被 polling 覆蓋。

詳見 memory：`feedback_navigation_priority.md`

---

## 執行流程

1. 詢問上述參數（含 domain、是否需要 SQLite、是否查詢其他 DB）
2. 確認使用者沒有要修改
3. 生成 6 個檔案：`__init__.py`、`plugin.yaml`、3 個 `.py`、1 個測試
4. **不需要修改 engine.py**（自動掃描）
5. 執行 `pytest scripts/module_{NNN}/` 確認全部通過
6. 提示使用者重啟 sidecar，新模組自動出現在選單

---

## 現有模組 ID 快速參考

| ID | 名稱 | Domain |
|----|------|--------|
| module_001 | OpenCV 影像處理 | cv |
| module_003 | 不規則邊框產生器 | edge |
| module_004 | 邊緣完整度偵測 | edge |
| module_005 | 邊緣記錄查詢 | edge |
| module_006 | 動物影像標記 | annotation |
| module_008 | 影片追蹤標注 | annotation |
| module_009 | 統一標注平台 | annotation |
| module_010 | Data Feeder | pipeline |
| module_012 | Annotation Session | annotation |
| module_013 | Update | pipeline |
