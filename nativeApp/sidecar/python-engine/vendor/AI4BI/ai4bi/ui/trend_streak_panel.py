"""Trend-streak panel — Round 085.

"哪些商品連續 N 期下滑？" — flags entities (SKU / 門市 / 品類) whose metric has
declined (or grown) for several consecutive periods in a row. Reads rows from
the content store (R051); pure pandas, so it works where the single-GROUP-BY
executor cannot.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.trends import declining_streaks
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.blocks.datastore import materialize_dataframe
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

# Round 156: include fab entities/metrics so decline-detection works on
# semiconductor data too (e.g. which tool's queue time keeps rising).
_ENTITY_HINTS = ("product", "sku", "item", "store", "category", "商品", "品項", "門市", "品類", "客戶",
                 "tool", "機台", "設備", "area", "區", "step", "站", "vendor", "供應商", "chamber")
_DATE_HINTS = ("date", "_at", "time", "日期", "時間")
_VALUE_HINTS = ("revenue", "amount", "sales", "qty", "quantity", "count", "營收", "金額", "銷售", "數量",
                "queue", "cycle", "yield", "defect", "rate", "pct", "佇列", "週期", "良率", "缺陷")
_PERIODS = {"month": "每月", "week": "每週", "quarter": "每季"}


def _fact_blocks(blocks: dict | None = None) -> dict[str, DataBlockContract]:
    blocks = blocks if blocks is not None else st.session_state.get(_USER_BLOCKS_KEY, {})
    return {b: c for b, c in blocks.items() if c.block_type == BlockType.fact}


def _guess(cols: list[str], hints: tuple[str, ...], default: int = 0) -> int:
    for i, c in enumerate(cols):
        if any(h in c.lower() for h in hints):
            return i
    return default


def _streak_applicable(contract) -> bool:
    cols = [c.name.lower() for c in contract.columns]
    return (any(any(h in c for h in _ENTITY_HINTS) for c in cols)
            and any(any(h in c for h in _DATE_HINTS) for c in cols)
            and any(any(h in c for h in _VALUE_HINTS) for c in cols))


def render_trend_streak_panel(blocks: dict | None = None) -> None:
    # Round 156: applies to any data with entity + date + metric (retail OR fab);
    # CURRENT-report driven.
    facts = {b: c for b, c in _fact_blocks(blocks).items() if _streak_applicable(c)}
    if not facts:
        return
    with st.expander("📉 連續下滑偵測（誰在持續走弱）", expanded=False):
        st.caption("找出某個指標連續多期下滑的對象（依你選的維度，如產品 / 機台 / 類別），提早發現問題。")
        bid = st.selectbox(
            "資料集", list(facts.keys()),
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="streak_block",
        )
        contract = facts[bid]
        cols = [c.name for c in contract.columns]
        if len(cols) < 3:
            st.info("此資料集欄位不足以偵測趨勢。")
            return

        c1, c2 = st.columns(2)
        with c1:
            entity_col = st.selectbox("對象", cols, index=_guess(cols, _ENTITY_HINTS), key="streak_entity")
            date_col = st.selectbox("日期欄位", cols, index=_guess(cols, _DATE_HINTS), key="streak_date")
        with c2:
            value_col = st.selectbox("指標", cols, index=_guess(cols, _VALUE_HINTS), key="streak_value")
            period = st.selectbox("期間", list(_PERIODS), format_func=lambda p: _PERIODS[p], key="streak_period")
        min_streak = st.slider("連續期數門檻", 2, 6, 3, key="streak_min")
        direction = st.radio("方向", ["down", "up"],
                             format_func=lambda d: "連續下滑" if d == "down" else "連續成長",
                             horizontal=True, key="streak_dir")

        if st.button("🔍 偵測", key="streak_run", type="primary"):
            try:
                df = materialize_dataframe(contract)
                st.session_state["_streak_result"] = declining_streaks(
                    df, entity_col, date_col, value_col,
                    period=period, min_streak=min_streak, direction=direction,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"無法計算：{exc}")

        if st.session_state.get("_streak_result") is not None:
            st.caption("✅ 結果顯示在右側主畫面")


def render_trend_streak_results() -> bool:
    """Render trend-streak result in the main canvas. Returns True if rendered."""
    res = st.session_state.get("_streak_result")
    if res is None:
        return False
    if res.empty:
        st.info("沒有符合條件的連續趨勢。")
    else:
        st.markdown(f"**{len(res)} 個對象符合條件**")
        st.dataframe(res, width="stretch", hide_index=True)
        csv = res.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇ 下載名單 CSV", data=csv,
                           file_name="trend_streaks.csv", key="streak_csv")
    return True
