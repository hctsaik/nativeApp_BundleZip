"""Create-new-data panel — Round 176 (Phase: 新產生資料).

Lets a non-technical user derive a NEW dataset from the ones they've loaded, in
the workspace's ➕ 新增資料 tab:

  * 合併 (union)   — stack two+ sources into one longer table (scenario S8);
  * 樞紐彙總 (pivot) — group a source by category columns and aggregate a measure
    into a smaller summary table (scenario S9).

The result is materialized through the same infer_block → CachedDataSource
pipeline as an upload, so the new dataset is content-addressed (no session-state
bloat), previewable, joinable and re-derivable like any other source. Pure
transforms (union_frames / aggregate_frame) are unit-tested without Streamlit.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

# Aggregation functions offered for pivot, with plain-language labels.
_AGG_LABELS = {
    "sum": "加總 (SUM)", "mean": "平均 (AVG)", "count": "筆數 (COUNT)",
    "min": "最小 (MIN)", "max": "最大 (MAX)",
}


def union_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Stack frames vertically, aligning on the UNION of columns (missing → NaN).

    Concatenating mismatched schemas is the common "this month + last month"
    case; columns only present in some frames are kept and null-filled elsewhere.
    """
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def aggregate_frame(df: pd.DataFrame, group_cols: list[str],
                    measure: "str | None", agg: str = "sum") -> pd.DataFrame:
    """Group ``df`` by ``group_cols`` and aggregate ``measure`` with ``agg``.

    agg="count" (or no measure) counts rows per group. Returns a tidy summary
    frame with one row per group.
    """
    if not group_cols:
        raise ValueError("需要至少一個分組欄位。")
    missing = [c for c in group_cols if c not in df.columns]
    if missing:
        raise ValueError(f"分組欄位不存在：{', '.join(missing)}")
    grouped = df.groupby(group_cols, dropna=False)
    if agg == "count" or not measure:
        return grouped.size().reset_index(name="筆數")
    if measure not in df.columns:
        raise ValueError(f"彙總欄位不存在：{measure}")
    out = grouped[measure].agg(agg).reset_index()
    return out.rename(columns={measure: f"{measure}_{agg}"})


def _capped_frame(contract) -> pd.DataFrame:
    """Materialize a source's rows, capped (an explicit create action, not a
    per-rerun preview — still bounded so a huge source can't blow up memory)."""
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi.ui.upload import _MAX_INLINE_ROWS
    df = materialize_dataframe(contract)
    if len(df) > _MAX_INLINE_ROWS:
        df = df.head(_MAX_INLINE_ROWS)
    return df


def _numeric_cols(contract) -> list[str]:
    return [c.name for c in getattr(contract, "columns", [])
            if getattr(c, "data_type", "") in ("integer", "float")]


def _existing_block_ids() -> set:
    from ai4bi.ui.upload import _USER_BLOCK_META_KEY
    return set(st.session_state.get(_USER_BLOCK_META_KEY, {}).keys())


def _confirm_overwrite(block_id: str, display_name: str, key: str) -> bool:
    """If a block with this id already exists, warn and require explicit
    confirmation so the user never silently overwrites a dataset."""
    if block_id not in _existing_block_ids():
        return True
    st.warning(f"已有名為「{display_name}」的資料；建立會**覆蓋**它。")
    return st.checkbox("我確認要覆蓋同名資料", key=key)


def render_create_data_panel(report_sources: "dict | None" = None) -> None:
    """Render the 合併 / 樞紐彙總 creators in the ➕ 新增資料 tab."""
    from ai4bi.ui.upload import _slugify
    from ai4bi.ui.connector_panel import _register_block

    sources = dict(report_sources or {})
    if not sources:
        st.caption("先載入資料，才能合併或彙總出新的資料。")
        return
    names = {bid: (getattr(c, "description", None) or bid) for bid, c in sources.items()}

    # ── 合併 (union) ──────────────────────────────────────────────────
    with st.expander("🔗 合併多份資料（上下疊加成一份）", expanded=False):
        st.caption("把多份結構相近的資料疊成一份（例如各月銷售）。欄位不一致時會自動對齊、缺值留白。")
        picked = st.multiselect(
            "選擇要合併的資料（至少 2 份）", list(sources.keys()),
            format_func=lambda b: names[b], key="union_pick",
        )
        if len(picked) >= 2:
            try:
                df = union_frames([_capped_frame(sources[b]) for b in picked])
            except Exception as exc:  # noqa: BLE001
                st.error(f"合併失敗：{exc}")
            else:
                st.caption(f"預覽（前 5 列，共 {len(df):,} 列 × {len(df.columns)} 欄）")
                st.dataframe(df.head(5), width="stretch", hide_index=True)
                nm = st.text_input("新資料的名稱", value="合併資料", key="union_name")
                bid = _slugify(nm) or "merged_data"
                ok = _confirm_overwrite(bid, nm, key="union_overwrite")
                if st.button("✅ 建立合併資料", key="union_create", type="primary",
                             disabled=df.empty or not ok):
                    _register_block(df, bid, nm, source="derived")
                    st.success(f"✅ 已建立「{nm}」（最多 {len(df):,} 列）")
                    st.rerun()
        elif picked:
            st.info("請再選一份資料才能合併。")

    # ── 樞紐彙總 (pivot / aggregate) ──────────────────────────────────
    with st.expander("📐 樞紐彙總（依分類加總／平均成摘要表）", expanded=False):
        st.caption("把明細資料依分類欄位彙總成摘要（例如「各門市每月營收」）。")
        bid_src = st.selectbox(
            "選擇來源資料", list(sources.keys()),
            format_func=lambda b: names[b], key="pivot_src",
        )
        contract = sources[bid_src]
        all_cols = [c.name for c in contract.columns]
        num_cols = _numeric_cols(contract)
        group_cols = st.multiselect("分組欄位（分類／日期）", all_cols, key="pivot_groups")
        agg = st.selectbox("彙總方式", list(_AGG_LABELS.keys()),
                           format_func=lambda a: _AGG_LABELS[a], key="pivot_agg")
        measure = None
        if agg != "count":
            measure = st.selectbox("彙總欄位（數值）", num_cols or ["—"], key="pivot_measure")
        # A non-count aggregate needs a real numeric column; guide the user to
        # COUNT instead of letting them hit an error (S9 edge case).
        valid_measure = (agg == "count") or (measure in num_cols)
        if group_cols and not valid_measure:
            st.info("這個彙總方式需要一個數值欄位；請選數值欄位，或改用「筆數 (COUNT)」。")
        if group_cols and valid_measure:
            try:
                src_df = _capped_frame(contract)
                out = aggregate_frame(src_df, group_cols,
                                      None if agg == "count" else measure, agg)
            except Exception as exc:  # noqa: BLE001
                st.error(f"彙總失敗：{exc}")
            else:
                st.caption(f"預覽（前 5 列，共 {len(out):,} 列 × {len(out.columns)} 欄）")
                st.dataframe(out.head(5), width="stretch", hide_index=True)
                nm = st.text_input("新資料的名稱", value=f"{names[bid_src]}_摘要", key="pivot_name")
                bid_new = _slugify(nm) or "summary_data"
                ok = _confirm_overwrite(bid_new, nm, key="pivot_overwrite")
                if st.button("✅ 建立彙總資料", key="pivot_create", type="primary",
                             disabled=out.empty or not ok):
                    _register_block(out, bid_new, nm, source="derived")
                    st.success(f"✅ 已建立「{nm}」（{len(out):,} 列）")
                    st.rerun()
