# /common-component — CIM 共用 UI 元件指南

本 skill 提供 CIM CV 模組中所有標準 UI 元件的正確使用方式，確保所有模組有一致的外觀與行為。

---

## 共用元件位置

```
sidecar/python-engine/scripts/shared/
├── ui_components.py    ← 日期、Parts 輸入、toast、下載按鈕
└── image_widget.py     ← 縮圖 + hover + lightbox + 下載
```

## 載入方式（在任何模組中）

```python
import importlib.util
from pathlib import Path

def _load_shared(name: str):
    path = Path(__file__).resolve().parent.parent / "shared" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_ui  = _load_shared("ui_components")
_img = _load_shared("image_widget")
```

---

## 日期選擇元件

### 單一日期（`date_input_single`）

```python
selected_date = _ui.date_input_single(
    label="選擇日期",    # 預設 "選擇日期"
    default=None,       # 預設 today
    key="date_single",  # 必須唯一
)
# 回傳：datetime.date
```

### 日期區間（`date_input_range`）— 推薦

兩個並排的 From / To 選擇器，From > To 時自動顯示警告：

```python
date_from, date_to = _ui.date_input_range(
    key_from="date_from",     # 必須唯一
    key_to="date_to",         # 必須唯一
    default_from=None,        # 預設：三個月前
    default_to=None,          # 預設：今天
)
# 回傳：tuple[datetime.date, datetime.date]
```

**注意**：不要用單一 `st.date_input` 傳入 list 來做範圍選擇，行為不穩定。

### 純日期計算（`three_months_ago`）

```python
from_date = _ui.three_months_ago()             # 今天往前三個月
from_date = _ui.three_months_ago(ref_date)     # 指定參考日期
# 自動處理月底溢位（5月31日 → 2月28日）
```

---

## Parts 輸入元件（`parts_input`）

顯示為「**Parts** [輸入欄]」一列：

```python
parts = _ui.parts_input(
    key="parts_input",
    placeholder="輸入 Parts 編號或說明",
)
# 回傳：str
```

---

## 通知元件（toast）

儲存操作後的非侵入式通知。不要使用 `st.success()`（佔版面）。

```python
_ui.save_success_toast()                    # 儲存成功！ ✅
_ui.save_success_toast("上傳完成！")        # 自訂訊息
_ui.save_error_toast()                      # 儲存失敗 ❌
_ui.save_error_toast(f"失敗：{e}")          # 含錯誤細節
```

**注意**：`icon` 欄位已包含符號，`message` 不要再加 emoji（避免顯示兩個符號）。

---

## 下載按鈕元件（`download_image_button`）

```python
_ui.download_image_button(
    image_bytes=bytes_data,
    filename="result.png",
    label="🖼️ 下載",   # 預設
    key="dl_btn",       # 必須唯一
)
```

---

## 影像預覽元件（`render_image_preview`）

縮圖 + hover 預覽 + 點擊全螢幕放大 + 下載：

```python
_img.render_image_preview(
    image_bytes=bytes_data,   # None → 顯示「無影像」
    filename="image.png",
    thumb_width=72,           # 縮圖寬度（px），預設 72
    key="preview_1",          # 可省略
)
```

**注意**：不要把 `render_image_preview` 放入 `st.columns` 的 table cell（iframe 高度不一致，破壞格線）。

---

## 表格 + 影像放大（標準模式）

影像**不放進**表格格，改用點擊對話方塊：

```python
import streamlit as st
import base64

@st.dialog("影像預覽", width="large")
def _show_preview(rec: dict) -> None:
    image_bytes = base64.b64decode(rec["image_b64"]) if rec.get("image_b64") else None
    fname = rec.get("image_name") or "image.png"
    orig_w = rec.get("image_width", 0)

    st.caption(f"{fname}　·　{orig_w} × {rec.get('image_height',0)} px")
    if image_bytes:
        st.image(image_bytes, width=orig_w if orig_w > 0 else None)
        st.download_button("🖼️ 下載原圖", data=image_bytes,
                           file_name=fname, mime="image/png",
                           key=f"dlg_dl_{rec['id']}")
    else:
        st.info("無影像資料")


def _data_row(rec: dict, cols_spec: list[float]) -> None:
    cols = st.columns(cols_spec)

    # 檔名欄：點擊 → 對話方塊
    fname = rec.get("image_name") or "（無檔名）"
    if cols[1].button(fname, key=f"view_{rec['id']}"):
        _show_preview(rec)

    # 下載欄：獨立 download_button
    image_bytes = base64.b64decode(rec["image_b64"]) if rec.get("image_b64") else None
    if image_bytes:
        cols[-1].download_button("🖼️", data=image_bytes,
                                 file_name=fname if fname != "（無檔名）" else "image.png",
                                 mime="image/png", key=f"dl_{rec['id']}")
    else:
        cols[-1].write("—")

    st.divider()
```

---

## 執行按鈕（Execute）

主要執行動作使用 `type="primary"`：

```python
if st.button("▶ 執行", type="primary"):
    with st.spinner("運算中…"):
        result = execute_logic(params)
    st.session_state["last_result"] = result
```

---

## 查詢按鈕（Query）

查詢操作使用 `type="secondary"`（或預設），與執行明顯區分：

```python
if st.button("🔍 查詢", type="secondary"):
    with st.spinner("查詢中…"):
        result = execute_logic(params)
    st.session_state["last_result"] = result
```

---

## 儲存按鈕（Save to SQLite）

```python
if st.button("💾 儲存 SQLite", type="primary"):
    try:
        # ... DB 寫入 ...
        _ui.save_success_toast()
    except Exception as e:
        _ui.save_error_toast(f"儲存失敗：{e}")
```

---

## 元件一致性原則

| 情境 | 正確做法 | 錯誤做法 |
|------|----------|----------|
| 日期區間 | `date_input_range()` 兩個分開元件 | 單一 `st.date_input` + list |
| 儲存通知 | `st.toast(icon="✅")` | `st.success()` 或 `st.toast("✅ ...", icon="✅")` |
| 影像放大 | `@st.dialog` 點擊開啟 | `iframe` / `st.image` 在 columns |
| 影像下載 | `<a download>` 或 `st.download_button` 獨立欄 | `window.open("data:...")` |
| 執行入口 | `st.button("▶ 執行", type="primary")` | 自動觸發（無按鈕） |

---

## 如何使用此 skill

執行 `/common-component` 後，說明你要在哪個模組加入什麼元件，Claude 會：

1. 確認模組路徑（`scripts/module_{ID}/`）
2. 加入 `_load_shared()` 載入程式碼
3. 在正確層（input / output）插入標準元件呼叫
4. 確認沒有違反「元件一致性原則」
