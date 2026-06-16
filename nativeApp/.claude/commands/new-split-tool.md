# /new-split-tool — 在 CIM 平台建立新的獨立分頁工具

## 架構概覽

CIM 平台的每個工具由**兩個獨立 Streamlit 程序**組成，透過一份 JSON 結果檔案溝通：

```
{stem}_input.py   ← 使用者輸入 + 觸發執行
      │  寫入 {TOOL_ID}_result.json
      │  postMessage: EXECUTE_COMPLETE
      ▼
Portal（React）收到訊號 → reload output iframe
      ▼
{stem}_output.py  ← 讀取結果、靜態渲染（無 polling）
```

**結果檔案格式（固定）：**
```json
{
  "user_input":     { ... 使用者填寫的欄位 ... },
  "process_result": { ... 運算產出的資料 ... }
}
```

---

## 共用工具程式庫（tools/ 目錄）

| 模組 | 用途 | 主要 API |
|------|------|----------|
| `tool_comms` | Portal ↔ Streamlit 溝通 | `notify_start()` / `notify_complete(success, error)` |
| `tool_result` | 讀寫結果檔案 | `write_result(path, user_input, process_result)` / `read_result(path)` |
| `ui_utils` | RWD 圖片 + lightbox | `show_image(source, caption)` |
| `db_utils` | SQLite 存取 | `SimpleDAO(db_path).query/execute/execute_many/last_insert_id` |
| `log_utils` | 雙輸出 logging | `get_logger(name)` |

---

## 輸入參數

執行此 skill 時，先詢問使用者以下資訊：

1. **Tool ID**：英文小寫 + 連字號，例如 `my-tool`（engine.py 用來識別）
2. **Tool 名稱**（中文）：顯示於 Portal 選單，例如「我的工具」
3. **Input 描述**：使用者在 Input 頁籤看到什麼、填什麼
4. **Process 描述**：按下執行按鈕後要做什麼運算
5. **Output 描述**：Output 頁籤要顯示什麼結果

---

## 生成的檔案結構

```
sidecar/python-engine/tools/
├── {stem}_input.py    ← 使用者輸入 + 呼叫 notify_start/complete
├── {stem}_output.py   ← 靜態讀取結果並渲染（無 polling）
└── {stem}.py          ← 空 stub（讓 engine 偵測 split-tool）
```

engine.py 的 `seed_tools` 列表也需要加入新 tool_id。

---

## 程式碼範本

### `{stem}.py`（stub，不需修改）
```python
# stub — engine uses this file to detect the split-tool pair
```

---

### `{stem}_input.py`
```python
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from tool_comms import notify_complete, notify_start
from tool_result import write_result

TOOL_ID = os.environ.get("CIM_TOOL_ID", "{tool-id}")
LOG_DIR = Path(os.environ.get("CIM_LOG_DIR", "/tmp"))
RESULT_FILE = LOG_DIR / f"{TOOL_ID}_result.json"


def main() -> None:
    st.set_page_config(page_title="{Tool 名稱} — Input", layout="wide")
    st.title("{Tool 名稱}")

    # ── 收集使用者輸入 ────────────────────────────────────────
    # （依 Input 描述實作）
    some_value = st.text_input("請輸入...")

    # ── 執行按鈕 ─────────────────────────────────────────────
    if st.button("▶ 執行", type="primary"):
        notify_start()
        try:
            # ── 運算邏輯（依 Process 描述實作）───────────────
            result_value = some_value.upper()  # 範例

            # ── 寫入結果（固定格式）──────────────────────────
            user_input = {
                "some_value": some_value,
            }
            process_result = {
                "result_value": result_value,
            }
            write_result(RESULT_FILE, user_input, process_result)
            notify_complete()
            st.success("執行完成，請切換至 Output 頁籤查看結果。")
        except Exception as exc:
            notify_complete(success=False, error=str(exc))
            st.error(f"執行失敗：{exc}")


if __name__ == "__main__":
    main()
```

---

### `{stem}_output.py`
```python
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from tool_result import read_result

TOOL_ID = os.environ.get("CIM_TOOL_ID", "{tool-id}")
LOG_DIR = Path(os.environ.get("CIM_LOG_DIR", "/tmp"))
RESULT_FILE = LOG_DIR / f"{TOOL_ID}_result.json"


def main() -> None:
    st.set_page_config(page_title="{Tool 名稱} — Output", layout="wide")

    data = read_result(RESULT_FILE)

    if data is None:
        st.title("執行結果")
        st.info("尚未執行，請在 Input 頁籤完成輸入後按下 ▶ 執行。")
        return

    ui = data["user_input"]
    pr = data["process_result"]

    # ── 顯示結果（依 Output 描述實作）────────────────────────
    st.title("執行結果")
    st.write("輸入值：", ui.get("some_value"))
    st.write("結果：",   pr.get("result_value"))


if __name__ == "__main__":
    main()
```

---

## 注意事項

- **Output page 絕對不可以有 `time.sleep` + `st.rerun()` 的 polling loop**。  
  Portal 收到 `EXECUTE_COMPLETE` 後會自動 reload output iframe，output page 只需靜態渲染即可。
- `user_input` 放「使用者決定的參數」，`process_result` 放「運算才知道的結果」。  
  Output page 可同時取用兩者，方便在結果旁顯示當初的輸入條件。
- 需要顯示圖片時，用 `from ui_utils import show_image`，不要用 `st.image`（缺乏 lightbox 和 RWD）。
- 需要存取 SQLite 時，用 `from db_utils import SimpleDAO`。
- 需要 logging 時，用 `from log_utils import get_logger`。

---

## 執行流程

1. 詢問上述 5 個參數
2. 確認使用者沒有要修改
3. 生成 3 個檔案（stub + input + output）
4. **自動 patch `engine.py`**：
   - 讀取 `sidecar/python-engine/engine.py`
   - 找到 `seed_tools` 列表（搜尋 `seed_tools = [` 或 `INSERT INTO tools`）
   - 在現有工具 entry 之後插入新的 tuple，格式：
     ```python
     (
         "{tool-id}",      # tool_id
         "{Tool 名稱}",    # name
         "{stem}.py",      # script_relative_path
         "0.1.0",          # version
         None,             # signature
         "seed",           # source_commit
         "system",         # author
         None,             # approved_at
         1,                # enabled
     ),
     ```
   - 確認 patch 後可以 `python -c "import ast; ast.parse(open('engine.py').read())"` 語法正確
5. 執行 `python -m pytest sidecar/python-engine/tests/test_sqlite_adapter.py -v` 確認新工具出現在 seed 清單
6. 提示使用者重啟程式（`npm run dev`）即可在 Portal 選單中看到新工具
