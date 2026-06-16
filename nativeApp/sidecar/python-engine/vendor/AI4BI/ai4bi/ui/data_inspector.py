"""
ai4bi.ui.data_inspector — resource-safe data-source inspection (Round 167).

The user loads many data sources (CSV / SQL / service → normalized to tabular
frames) and needs to answer, cheaply: *what sources are loaded, and what's in
each one (schema / types / shape)?* — without paying to render or scan a large
dataset.

Design (all the expensive paths are opt-in):
  * **Schema & shape are free** — read from the block contract
    (`columns` + `data_source.row_count`), never loading rows.
  * **Preview is sampled & lazy** — only the first N rows, only when the user
    asks (a checkbox), via ``datastore.sample_dataframe`` (never the full frame).
  * **Profiling runs on the sample only**, clearly labelled「取樣估計」, so a
    50K-row source never triggers a full-column scan on every rerun.

Pure helpers (no Streamlit) are unit-tested; ``render_source_inspector`` wires
them into the data-source manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

# Type label → friendly zh + icon (logical types from ColumnSchema.data_type)
_TYPE_LABEL = {
    "string": ("文字", "🔤"),
    "integer": ("整數", "🔢"),
    "float": ("數值", "🔢"),
    "boolean": ("布林", "✔️"),
    "date": ("日期", "📅"),
    "timestamp": ("時間", "🕒"),
    "datetime": ("時間", "🕒"),
}

# Row-count tiers for the cost hint (None = unknown without loading).
_SMALL, _MEDIUM = 1_000, 50_000


@dataclass(frozen=True)
class SourceShape:
    """Cheap, metadata-only summary of a source (no rows loaded)."""
    block_id: str
    n_cols: int
    row_count: Optional[int]
    cost_tier: str           # "small" | "medium" | "large" | "unknown"
    cost_label: str          # zh hint shown to the user

    @property
    def is_large(self) -> bool:
        return self.cost_tier == "large"


def classify_cost(row_count: Optional[int]) -> tuple[str, str]:
    """Map a row count to a (tier, zh-label) cost hint — metadata only."""
    if row_count is None:
        return "unknown", "未知大小 · 預覽僅取樣"
    if row_count <= _SMALL:
        return "small", f"{row_count:,} 列 · 小"
    if row_count <= _MEDIUM:
        return "medium", f"{row_count:,} 列 · 中"
    return "large", f"{row_count:,} 列 · 大,僅取樣預覽"


def source_shape(contract) -> SourceShape:
    """Metadata-only shape of a source — no data is materialized."""
    from ai4bi.blocks.datastore import source_row_count
    rc = source_row_count(contract)
    tier, label = classify_cost(rc)
    return SourceShape(
        block_id=getattr(contract, "block_id", "?"),
        n_cols=len(getattr(contract, "columns", []) or []),
        row_count=rc,
        cost_tier=tier,
        cost_label=label,
    )


def schema_rows(contract) -> list[dict[str, Any]]:
    """Schema table rows from the contract alone (no data load)."""
    rows: list[dict[str, Any]] = []
    for col in getattr(contract, "columns", []) or []:
        raw = getattr(col, "data_type", "") or ""
        label, icon = _TYPE_LABEL.get(raw.lower(), (raw or "—", "•"))
        rows.append({
            "欄位": getattr(col, "name", "?"),
            "型態": f"{icon} {label}",
            "可空": "是" if getattr(col, "nullable", True) else "否",
        })
    return rows


# ── Column display prefs (Round 176, scenario S4) ───────────────────────────
# Per-source friendly names + hidden columns. Scoped to display/preview so the
# user can tidy how data LOOKS in the workspace without touching the data.
_COL_PREFS_KEY = "_col_prefs"


def apply_column_prefs(df: pd.DataFrame, alias: dict, hidden: list) -> pd.DataFrame:
    """Pure: drop hidden columns and rename via the alias map (for the preview)."""
    hide = set(hidden or [])
    keep = [c for c in df.columns if c not in hide]
    out = df[keep]
    ren = {k: v for k, v in (alias or {}).items() if v and k in out.columns}
    return out.rename(columns=ren) if ren else out


def get_column_prefs(block_id: str) -> dict:
    """Session-stored {'alias': {col: name}, 'hidden': [col]} for a source."""
    import streamlit as st
    store = st.session_state.setdefault(_COL_PREFS_KEY, {})
    return store.setdefault(block_id, {"alias": {}, "hidden": []})


def profile_sample(sample: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-column profile computed on the SAMPLE only (cheap, approximate).

    Returns null-rate, distinct count and (numeric) min/max over the sample —
    never the full dataset. Callers must label these as 取樣估計.
    """
    if sample is None or sample.empty:
        return []
    n = len(sample)
    out: list[dict[str, Any]] = []
    for col in sample.columns:
        s = sample[col]
        nn = int(s.notna().sum())
        rate = (nn / n) if n else 0.0
        # ⚠️ flags low-completeness columns so data-quality issues stand out
        # at a glance (the sample's non-null rate; labelled 取樣估計 by callers).
        mark = " ⚠️" if rate < 0.9 else ""
        row: dict[str, Any] = {
            "欄位": str(col),
            "非空率": f"{rate * 100:.0f}%{mark}" if n else "—",
            "種類數": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s.dtype) and nn:
            row["最小"] = round(float(s.min()), 2)
            row["最大"] = round(float(s.max()), 2)
        else:
            # most-common value + its count in the sample (more useful than a
            # lone example for categorical columns); cheap on a small sample.
            vc = s.dropna().value_counts()
            if not vc.empty:
                top, cnt = vc.index[0], int(vc.iloc[0])
                row["最常見"] = f"{str(top)[:20]}（{cnt}）"
            else:
                row["最常見"] = "—"
        out.append(row)
    return out


def _source_version(contract) -> str:
    """A cheap cache key that changes only when the source's data changes."""
    from ai4bi.blocks.contracts import CachedDataSource, InlineDataSource
    src = contract.data_source
    bid = getattr(contract, "block_id", "?")
    if isinstance(src, CachedDataSource):
        return f"cached:{src.content_hash}"
    if isinstance(src, InlineDataSource):
        return f"inline:{bid}:{len(src.records)}"
    return f"other:{bid}"


# Cache the sampled preview + profile so they're computed once per (source, n)
# rather than on every Streamlit rerun while the preview checkbox stays ticked.
# Guarded so the module still imports (and the pure helpers test) without a
# Streamlit script-run context.
try:  # pragma: no cover - exercised under Streamlit, not in unit tests
    import streamlit as _st
    # Bounded cache so a long session with many sources/previews can't grow
    # memory without limit (max_entries) and stale samples expire (ttl).
    _cache_data = _st.cache_data(show_spinner=False, max_entries=64, ttl=600)
except Exception:  # noqa: BLE001
    def _cache_data(fn):
        return fn


@_cache_data
def _cached_sample_profile(version: str, n: int, _contract):  # noqa: ARG001 - version is the cache key
    from ai4bi.blocks.datastore import sample_dataframe
    sample = sample_dataframe(_contract, n)
    return sample, profile_sample(sample)


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------

def render_source_inspector(contract, *, display_name: str, origin: str,
                            key_prefix: str, default_sample: int = 20,
                            subtitle: Optional[str] = None,
                            embedded: bool = False) -> None:
    """Render one source CONTENT-FIRST: a small sampled preview of the actual
    rows up top, with the schema/types tucked into a click-to-open expander.

    Round 177: a fab engineer judges a dataset by its values (yield 0–1 vs 0–100,
    date span, right lot), not by a column-type table — so the sample leads and
    the schema is secondary. Resource-safe: the preview is the first N rows only
    (sample_dataframe → head(N), cached); the full table is never scanned. The
    distinct-count/range stats stay opt-in. ``embedded`` (Round 176) drops the
    outer expander for the workspace master-detail detail pane.
    """
    import contextlib
    import streamlit as st

    shape = source_shape(contract)
    rc = "未知" if shape.row_count is None else f"{shape.row_count:,}"
    badge = {"small": "🟢", "medium": "🟡", "large": "🔴", "unknown": "⚪"}[shape.cost_tier]
    header = f"🔎 {display_name} · {shape.n_cols} 欄 · {rc} 列"

    if embedded:
        st.markdown(f"#### {header}")
        ctx = contextlib.nullcontext()
    else:
        ctx = st.expander(header, expanded=False)

    with ctx:
        line = f"{origin}　|　`{shape.block_id}`　|　{badge} {shape.cost_label}"
        if subtitle:
            line += f"　|　{subtitle}"
        st.caption(line)

        # Round 177: CONTENT-FIRST. A fab engineer wants to see what the data
        # actually looks like (is yield 0–1 or 0–100? which dates? right lot?) —
        # that's the judgement; the schema (types) is secondary, click-to-open.
        # Resource-safe: the sample is the first N rows only (sample_dataframe →
        # head(N), cached); the full table is never scanned/sent to the browser.
        prefs = get_column_prefs(shape.block_id) if embedded else None
        try:
            sample, prof = _cached_sample_profile(
                _source_version(contract), default_sample, contract)
        except Exception as exc:  # noqa: BLE001 — preview must never break the page
            sample, prof = None, []
            st.warning(f"無法取樣預覽：{exc}")

        if shape.is_large:
            st.caption(f"⚠️ 大型資料：以下只是**前 {default_sample} 列取樣**，不是全表"
                       "（不會把整張表送進瀏覽器或做全表掃描）。")
        if sample is not None and not sample.empty:
            st.markdown(f"**資料內容（前 {len(sample)} 列取樣）**")
            _disp = sample
            if prefs and (prefs["alias"] or prefs["hidden"]):
                _disp = apply_column_prefs(sample, prefs["alias"], prefs["hidden"])
            st.dataframe(_disp, width="stretch", hide_index=True)
        else:
            st.caption("沒有可預覽的資料。")

        # --- schema is now SECONDARY: collapsed, open only when you need types ---
        rows = schema_rows(contract)
        with st.expander("🔧 欄位結構（型態／可空，需要時點開）", expanded=False):
            if rows:
                _view = rows
                if len(rows) > 12:
                    q = st.text_input("搜尋欄位", key=f"{key_prefix}_q",
                                      placeholder="輸入欄位名片段…").strip().lower()
                    if q:
                        _view = [r for r in rows if q in str(r["欄位"]).lower()]
                        st.caption(f"符合「{q}」：{len(_view)} 欄")
                schema_df = pd.DataFrame(_view)
                st.dataframe(schema_df, width="stretch", hide_index=True)
                st.download_button(
                    "⬇️ 匯出欄位清單 (CSV)",
                    schema_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{shape.block_id}_schema.csv", mime="text/csv",
                    key=f"{key_prefix}_dl",
                )
            else:
                st.caption("此來源未宣告欄位結構。")

        # --- column display prefs (S4): rename / hide for this preview ---
        if embedded and rows:
            with st.expander("⚙️ 預覽顯示設定（改名稱／隱藏欄位）", expanded=False):
                st.caption("整理**這份預覽**要怎麼顯示：把欄位改成看得懂的名稱、或暫時隱藏不需要的欄位。"
                           "（僅影響此處的預覽顯示，不會更動原始資料，也不會改到圖表。）")
                for col in [c.name for c in getattr(contract, "columns", [])]:
                    cc1, cc2 = st.columns([3, 1])
                    with cc1:
                        new = st.text_input(
                            f"`{col}`", value=prefs["alias"].get(col, ""),
                            key=f"{key_prefix}_alias_{col}", placeholder="（顯示名稱，留空＝原名）",
                        ).strip()
                        if new:
                            prefs["alias"][col] = new
                        else:
                            prefs["alias"].pop(col, None)
                    with cc2:
                        hidden_now = st.checkbox(
                            "隱藏", value=col in prefs["hidden"], key=f"{key_prefix}_hide_{col}")
                        if hidden_now and col not in prefs["hidden"]:
                            prefs["hidden"].append(col)
                        elif not hidden_now and col in prefs["hidden"]:
                            prefs["hidden"].remove(col)

        # --- sampled stats stay opt-in (distinct counts etc. — more than head) ---
        if sample is not None and not sample.empty:
            if st.checkbox("📊 顯示取樣統計（非空率／種類數／範圍）", key=f"{key_prefix}_prof"):
                st.caption(f"以下為**取樣估計**（基於前 {len(sample)} 列,非全表,僅供概覽）：")
                st.dataframe(pd.DataFrame(prof), width="stretch", hide_index=True)
                st.caption("⚠️＝此欄空白偏多（非空率 < 90%）　·　「種類數」＝此欄有幾種不同的值")
