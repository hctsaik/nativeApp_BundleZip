"""Self-serve CSV / Excel data import — Round 028 / Round 032.

Round 032 adds:
- Ratio column detection: columns whose names suggest a rate/percentage/margin
  are classified as average-aggregated metrics, NOT sum-aggregated, to prevent
  displaying nonsense like "profit margin total = 347%".
- Data Health Check UI: before importing, users see a colour-coded confirmation
  of how each column will be treated.
- Human-readable metadata sentence shown below each visual.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

import pandas as pd
import streamlit as st

from ai4bi.blocks.contracts import (
    BlockType,
    ColumnSchema,
    DataBlockContract,
    DataClassification,
    DisaggregationMethod,
    InlineDataSource,
    LifecycleStatus,
    MetricDefinition,
    PolicySpec,
)

_USER_BLOCKS_KEY = "user_blocks"
_USER_BLOCK_META_KEY = "user_block_meta"
_PENDING_NEW_BLOCK_KEY = "pending_new_block"   # Round 033: triggers auto-build in app.py

_ID_RE = re.compile(r"(_id|_key|_code|_num|_no)\s*$|^id$", re.I)

# Token-based keyword sets — split column name by _ and spaces, then check tokens
# This correctly handles compound names like "profit_margin", "sale_date".
_DATE_TOKENS = frozenset({
    "date", "time", "day", "month", "year", "week", "period",
    "timestamp", "ts", "dt", "created", "updated", "at",
})
# Round 032: ratio/percentage column names — these should NEVER be summed
_RATIO_TOKENS = frozenset({
    "rate", "ratio", "pct", "percent", "margin", "yield", "utilization",
    "efficiency", "coverage", "conversion", "churn", "retention",
    "accuracy", "score", "index", "proportion", "share", "fraction",
})

# Still keep _DATE_RE for backward-compat usages elsewhere
_DATE_RE = re.compile(r"\b(date|time|day|month|year|week|period|ts|timestamp|dt)\b", re.I)


def _col_tokens(col_name: str) -> list[str]:
    """Split column name into lowercase tokens by underscores and spaces."""
    return [t for t in re.split(r"[_\s]+", col_name.lower()) if t]


def _is_date_col_name(col_name: str) -> bool:
    return bool(set(_col_tokens(col_name)) & _DATE_TOKENS)


def _is_ratio_col_name(col_name: str) -> bool:
    return bool(set(_col_tokens(col_name)) & _RATIO_TOKENS)
_MAX_INLINE_ROWS = 50_000

ColCategory = Literal["sum_metric", "ratio_metric", "date", "dimension", "primary_key"]


@dataclass
class ColumnClassification:
    name: str
    category: ColCategory
    sample: str   # first non-null value as string


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "col"


def _detect_date_cols(df: pd.DataFrame) -> set[str]:
    """Detect string columns that represent dates by name tokens + parse attempt."""
    guessed: set[str] = set()
    for col in df.select_dtypes(include=["object", "string"]).columns:
        if _is_date_col_name(col):
            try:
                pd.to_datetime(df[col].dropna().head(20))
                guessed.add(col)
            except Exception:  # noqa: BLE001
                pass
    return guessed


def classify_df(df: pd.DataFrame) -> list[ColumnClassification]:
    """Return a ColumnClassification for each column — used for the Health Check UI."""
    guessed_dates = _detect_date_cols(df)
    result: list[ColumnClassification] = []
    for col in df.columns:
        dtype = df[col].dtype
        sample_val = df[col].dropna().iloc[0] if not df[col].dropna().empty else ""
        sample = str(sample_val)[:20]
        is_numeric = pd.api.types.is_numeric_dtype(dtype)
        is_datetime = pd.api.types.is_datetime64_any_dtype(dtype) or col in guessed_dates
        is_id_like = bool(_ID_RE.search(col))
        # Round 032: use token-based ratio detection
        is_ratio = is_numeric and _is_ratio_col_name(col)

        if is_datetime:
            category: ColCategory = "date"
        elif is_id_like:
            category = "primary_key"
        elif is_ratio:
            category = "ratio_metric"
        elif is_numeric:
            category = "sum_metric"
        else:
            category = "dimension"
        result.append(ColumnClassification(name=col, category=category, sample=sample))
    return result


def infer_block(
    df: pd.DataFrame,
    block_id: str,
    display_name: str,
) -> tuple[DataBlockContract, list[str], list[str]]:
    """Infer a DataBlockContract from a DataFrame.

    Returns
    -------
    contract      : validated DataBlockContract
    metric_names  : original column names classified as metrics (sum + ratio)
    dim_names     : original column names classified as dimensions
    """
    guessed_dates = _detect_date_cols(df)

    columns: list[ColumnSchema] = []
    metrics: list[MetricDefinition] = []
    metric_names: list[str] = []
    dim_names: list[str] = []
    primary_keys: list[str] = []

    for col in df.columns:
        dtype = df[col].dtype
        is_numeric = pd.api.types.is_numeric_dtype(dtype)
        is_datetime = pd.api.types.is_datetime64_any_dtype(dtype) or col in guessed_dates
        is_id_like = bool(_ID_RE.search(col))
        # Round 032: ratio columns use average, not sum — token-based detection
        is_ratio = is_numeric and _is_ratio_col_name(col)

        if is_datetime:
            col_type = "date"
            dim_names.append(col)
        elif is_numeric and not is_id_like:
            col_type = "float" if pd.api.types.is_float_dtype(dtype) else "integer"
            if is_ratio:
                agg = DisaggregationMethod.average
                formula = f"AVG({col})"
                desc = f"Average of {col} (ratio — not summed)"
            else:
                agg = DisaggregationMethod.sum
                formula = f"SUM({col})"
                desc = f"Sum of {col}"
            metrics.append(MetricDefinition(
                name=col,
                formula=formula,
                disaggregation_method=agg,
                description=desc,
            ))
            metric_names.append(col)
        else:
            col_type = "string"
            if is_id_like:
                primary_keys.append(col)
            else:
                dim_names.append(col)

        columns.append(ColumnSchema(name=col, data_type=col_type, nullable=True))

    # Ensure at least one metric exists (fallback: first numeric col regardless of name)
    if not metric_names:
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col].dtype) and col not in primary_keys:
                metrics.append(MetricDefinition(
                    name=col,
                    formula=f"SUM({col})",
                    disaggregation_method=DisaggregationMethod.sum,
                ))
                metric_names.append(col)
                break

    # Convert datetime columns in the df records to ISO strings so they serialise
    df_serial = df.copy()
    for col in guessed_dates:
        df_serial[col] = pd.to_datetime(df_serial[col], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in df_serial.select_dtypes(include="datetime64").columns:
        df_serial[col] = df_serial[col].dt.strftime("%Y-%m-%d")

    df_clean = df_serial.where(pd.notna(df_serial), None)

    # Round 051: store rows in the content-addressed DataFrame store and keep
    # only a hash in the contract, so large uploads don't bloat st.session_state.
    from ai4bi.blocks.contracts import CachedDataSource
    from ai4bi.blocks.datastore import put_dataframe
    content_hash = put_dataframe(df_clean)

    contract = DataBlockContract(
        block_id=block_id,
        block_type=BlockType.fact,
        grain="one row per record",
        version="1.0.0",
        description=f"Uploaded from {display_name}",
        block_lifecycle=LifecycleStatus.draft,
        primary_keys=primary_keys[:1],
        columns=columns,
        metrics=metrics,
        data_source=CachedDataSource(content_hash=content_hash, row_count=len(df_clean)),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    return contract, metric_names, dim_names


# Real-world CSVs (esp. Taiwanese gov / Excel exports) are often NOT utf-8 —
# Big5 / CP950 are common. Try the likely encodings in order before giving up.
_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "big5", "cp950", "gb18030", "utf-16")


def _read_csv_any_encoding(raw: bytes) -> pd.DataFrame:
    last_exc: Exception | None = None
    for enc in _CSV_ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_exc = exc
            continue
    # latin-1 maps every byte, so this never raises a decode error — last resort
    # (keeps a stubborn file readable rather than failing the upload outright).
    try:
        return pd.read_csv(io.BytesIO(raw), encoding="latin-1")
    except Exception:  # noqa: BLE001
        raise last_exc or RuntimeError("無法解析 CSV 編碼")


# ── JSON ingestion (Round 176) ──────────────────────────────────────────────
# Most user data "ends up as JSON" (from APIs / SQL exports), but JSON is often
# nested or wrapped in an envelope. These pure helpers turn an arbitrary parsed
# JSON value into a flat, queryable table; the UI picks the records path.

def _parse_json_any_encoding(raw: bytes) -> Any:
    """Decode + parse JSON, tolerating common encodings (mirrors the CSV path)."""
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950", "gb18030", "utf-16"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, UnicodeError):
            continue
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式錯誤：{exc}") from exc
    raise ValueError("無法解析 JSON 編碼")


def _is_list_of_dicts(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, dict) for x in v)


def json_record_paths(obj: Any) -> list[str]:
    """Candidate dot-paths to the list-of-records inside a parsed JSON object.

    "" means "the top level is already the records" (an array of objects) or
    "treat the whole object as a single row". Paths are ranked by record count
    (largest table first) so the most likely choice leads the picker.
    """
    if _is_list_of_dicts(obj):
        return [""]
    paths: list[tuple[str, int]] = []
    if isinstance(obj, dict):
        def _scan(d: dict, prefix: str) -> None:
            for k, v in d.items():
                p = f"{prefix}{k}"
                if _is_list_of_dicts(v):
                    paths.append((p, len(v)))
                elif isinstance(v, dict):
                    _scan(v, p + ".")
        _scan(obj, "")
    paths.sort(key=lambda x: -x[1])
    return [p for p, _ in paths] or [""]


def _get_json_path(obj: Any, path: str) -> Any:
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        cur = cur[part]
    return cur


def json_to_dataframe(obj: Any, record_path: str = "") -> pd.DataFrame:
    """Normalize parsed JSON into a flat DataFrame.

    Nested objects flatten to dotted columns (``addr.city``); residual list/dict
    cells are JSON-encoded to strings so every column is representable (and can
    be flagged as 巢狀 downstream). The caller still caps row count.
    """
    target = _get_json_path(obj, record_path)
    if isinstance(target, list):
        records = [r if isinstance(r, dict) else {"value": r} for r in target]
    elif isinstance(target, dict):
        records = [target]
    else:
        records = [{"value": target}]
    df = pd.json_normalize(records, sep=".")
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
            df[col] = df[col].apply(
                lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x
            )
    return df


def nested_json_columns(df: pd.DataFrame) -> list[str]:
    """Columns that hold JSON-encoded nested values (arrays/objects kept as text
    by json_to_dataframe). Used to flag 🧩 巢狀欄位 in the JSON/REST previews."""
    # No dtype gate: pandas 3.0 gives string columns a real `str` dtype (not
    # object), so check values directly — dtype-agnostic and robust.
    def _looks_json(v) -> bool:
        return isinstance(v, str) and v[:1] in ("{", "[")
    return [c for c in df.columns if df[c].map(_looks_json).any()]


def _load_file(uploaded_file) -> Optional[pd.DataFrame]:
    """Parse an uploaded file into a DataFrame (encoding/format tolerant).

    JSON uses the best auto-detected records path; the upload panel offers a
    picker to override it for nested/enveloped data.
    """
    name: str = uploaded_file.name.lower()
    raw = uploaded_file.read()
    try:
        if name.endswith(".csv"):
            return _read_csv_any_encoding(raw)
        if name.endswith(".xlsx"):
            return pd.read_excel(io.BytesIO(raw), engine="openpyxl")
        if name.endswith(".xls"):
            try:
                return pd.read_excel(io.BytesIO(raw), engine="xlrd")
            except ImportError:
                st.error("讀取舊版 .xls 需要 `xlrd` 套件；請改存成 .xlsx,或安裝 `xlrd>=2.0.1` 後重試。")
                return None
        if name.endswith(".parquet"):
            return pd.read_parquet(io.BytesIO(raw))
        if name.endswith(".json"):
            obj = _parse_json_any_encoding(raw)
            return json_to_dataframe(obj, json_record_paths(obj)[0])
        st.error(f"不支援的檔案格式：{uploaded_file.name}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"讀取檔案失敗：{exc}")
    return None


def _render_json_records_picker(uploaded) -> Optional[pd.DataFrame]:
    """Parse a JSON upload, let the user choose where the data rows live, and
    return the normalized table. Handles arrays, envelopes ({"data": [...]}) and
    nested objects; flags the residual nested (JSON-text) columns."""
    try:
        obj = _parse_json_any_encoding(uploaded.getvalue())
    except Exception as exc:  # noqa: BLE001
        st.error(f"讀取 JSON 失敗：{exc}")
        return None

    paths = json_record_paths(obj)
    if len(paths) > 1:
        def _label(p: str) -> str:
            if p == "":
                return "最外層（整份就是資料列）"
            try:
                n = len(_get_json_path(obj, p))
            except Exception:  # noqa: BLE001
                n = "?"
            return f"{p}（{n} 筆）"
        path = st.selectbox(
            "這份 JSON 的「資料列」在哪裡？", paths, format_func=_label,
            key="json_record_path",
            help="JSON 常把資料包在某個欄位裡（例如 data、items、results）。選錯可改這裡。",
        )
    else:
        path = paths[0]
        # Make the auto-choice transparent so the user can tell what we picked.
        if path:
            st.caption(f"📍 已自動從 `{path}` 取出資料列（這份 JSON 只有這一處像資料表）。")

    try:
        df = json_to_dataframe(obj, path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"無法把這份 JSON 轉成表格：{exc}")
        return None
    if df.empty:
        st.warning("這份 JSON 沒有可轉成表格的資料列。")
        return None

    nested = nested_json_columns(df)
    if nested:
        st.caption("🧩 巢狀欄位（內含多個值，目前以 JSON 文字保存，例如 "
                   f"`{nested[0]}`）：" + "、".join(f"`{c}`" for c in nested))
    return df


_COL_CATEGORY_LABEL: dict[ColCategory, str] = {
    "sum_metric":   "📊 加總指標",
    "ratio_metric": "⚠️ 比率欄位",
    "date":         "📅 日期",
    "dimension":    "🏷️ 分類",
    "primary_key":  "🔑 識別碼",
}
_COL_CATEGORY_NOTE: dict[ColCategory, str] = {
    "sum_metric":   "加總計算（SUM）",
    "ratio_metric": "⚠️ 平均計算（AVG），不加總——避免顯示錯誤數字",
    "date":         "時間維度",
    "dimension":    "分類維度",
    "primary_key":  "主鍵，不計算",
}


def _render_health_check(classifications: list[ColumnClassification]) -> None:
    """Render the Data Health Check card — Round 032."""
    groups: dict[ColCategory, list[str]] = {
        "sum_metric": [], "ratio_metric": [], "date": [],
        "dimension": [], "primary_key": [],
    }
    for c in classifications:
        groups[c.category].append(c.name)

    has_ratio = bool(groups["ratio_metric"])
    if has_ratio:
        st.warning(
            f"⚠️ 偵測到 **{len(groups['ratio_metric'])}** 個比率欄位：{', '.join(groups['ratio_metric'])}。"
            "這些欄位將以**平均值**計算，不會直接加總（避免「毛利率合計 = 347%」這類錯誤）。"
            "如果判斷不正確，請在下方修正。"
        )

    for cat in ("sum_metric", "ratio_metric", "date", "dimension"):
        names = groups[cat]
        if not names:
            continue
        label = _COL_CATEGORY_LABEL[cat]
        note = _COL_CATEGORY_NOTE[cat]
        st.caption(f"**{label}**（{len(names)}）— {note}")
        st.caption("  ".join(f"`{n}`" for n in names))


def render_upload_panel() -> None:
    """Render the 'Upload Your Data' sidebar expander — Round 028/032."""
    with st.expander("上傳資料", expanded=False):
        st.caption("支援 CSV（自動辨識 Big5／UTF-8 等編碼）、Excel（.xlsx／.xls）、Parquet、JSON — 最多 50,000 行")

        uploaded = st.file_uploader(
            "選擇檔案",
            type=["csv", "xlsx", "xls", "parquet", "json"],
            key="data_upload_widget",
            label_visibility="collapsed",
        )
        if uploaded is None:
            st.session_state.pop("_upload_preview", None)  # clear the canvas preview
            _render_existing_blocks()
            return

        # JSON gets a records-path picker (nested / enveloped data); other
        # formats load directly.
        if uploaded.name.lower().endswith(".json"):
            df = _render_json_records_picker(uploaded)
        else:
            df = _load_file(uploaded)
        if df is None:
            return

        if len(df) > _MAX_INLINE_ROWS:
            st.warning(f"檔案有 {len(df):,} 行，已截取前 {_MAX_INLINE_ROWS:,} 行。")
            df = df.head(_MAX_INLINE_ROWS)

        # Auto-generate block_id from filename
        raw_name = re.sub(r"\.[^.]+$", "", uploaded.name)
        default_id = _slugify(raw_name) or "my_data"
        # Round 032: user-friendly label (no "Block ID" jargon)
        data_name = st.text_input(
            "這份資料的名稱",
            value=raw_name or default_id,
            key="upload_block_id",
            help="之後可以用這個名稱讓 AI 查詢它",
        )
        block_id = _slugify(data_name) or default_id

        # Preview — Round 173: render it in the WIDE main canvas (a 13-column
        # table is unreadable here). Stash it; render_staged_upload_preview()
        # renders the wide table just below (Round 176: in the same 新增資料 tab,
        # so the preview appears where the user uploaded — no more cross-tab hunt).
        st.session_state["_upload_preview"] = {
            "name": data_name, "rows": int(len(df)), "cols": int(len(df.columns)),
            "head": df.head(5),
        }
        st.caption(f"資料預覽（前 5 行，共 {len(df):,} 行 × {len(df.columns)} 欄）👇 顯示在下方")

        # Round 032: Data Health Check
        classifications = classify_df(df)
        st.markdown("---")
        st.caption("**📋 AI 讀懂了這些欄位**")
        _render_health_check(classifications)

        # Infer contract
        contract, metric_names, dim_names = infer_block(df, block_id, uploaded.name)

        if not metric_names:
            st.warning("未偵測到數值欄位，請確認資料格式。")

        st.markdown("---")
        if st.button(
            "✅ 確認並匯入",
            key="upload_import_btn",
            type="primary",
            disabled=not metric_names,
        ):
            if _USER_BLOCKS_KEY not in st.session_state:
                st.session_state[_USER_BLOCKS_KEY] = {}
            if _USER_BLOCK_META_KEY not in st.session_state:
                st.session_state[_USER_BLOCK_META_KEY] = {}
            st.session_state[_USER_BLOCKS_KEY][block_id] = contract
            import datetime as _dt
            st.session_state[_USER_BLOCK_META_KEY][block_id] = {
                "metric_names": metric_names,
                "dim_names": dim_names,
                "display_name": data_name,
                "row_count": len(df),
                "uploaded_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            # Round 033: signal app.py to auto-build report immediately
            st.session_state[_PENDING_NEW_BLOCK_KEY] = block_id
            st.session_state.pop("_upload_preview", None)
            st.rerun()

        _render_existing_blocks()


def render_staged_upload_preview() -> bool:
    """Round 173: render the staged-upload preview WIDE in the main canvas.

    Returns True if something was rendered. The upload controls (picker / name /
    health check / import) stay in the sidebar; only the wide table preview lives
    here so a many-column file is readable.
    """
    prev = st.session_state.get("_upload_preview")
    if not prev:
        return False
    st.markdown(f"**📤 待匯入預覽：{prev['name']}**")
    st.caption(f"前 5 行，共 {prev['rows']:,} 行 × {prev['cols']} 欄"
               "（在左側「上傳資料」按「✅ 確認並匯入」完成匯入）")
    st.dataframe(prev["head"], width="stretch", hide_index=True)
    return True


def _render_existing_blocks() -> None:
    """Show already-imported user blocks with a delete button."""
    meta: dict = st.session_state.get(_USER_BLOCK_META_KEY, {})
    # Round 156: only list genuinely uploaded/connected blocks (meta-tracked); the
    # demo seed in user_blocks has no meta and must not appear as "已匯入".
    all_blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    user_blocks = {bid: c for bid, c in all_blocks.items() if bid in meta}
    if not user_blocks:
        return
    st.divider()
    st.caption("**已匯入的資料**")
    for bid, contract in list(user_blocks.items()):
        m = meta.get(bid, {})
        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown(
                f"**{bid}** — {m.get('row_count', '?')} 行 · "
                f"{len(m.get('metric_names', []))} 指標 · "
                f"{len(m.get('dim_names', []))} 維度"
            )
        with cols[1]:
            if st.button("刪除", key=f"del_upload_{bid}"):
                del st.session_state[_USER_BLOCKS_KEY][bid]
                st.session_state.get(_USER_BLOCK_META_KEY, {}).pop(bid, None)
                st.rerun()
