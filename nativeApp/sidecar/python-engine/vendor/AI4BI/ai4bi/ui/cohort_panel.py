"""Cohort / retention panel — Round 062.

Pick a dataset with a customer id + a date column and see a retention matrix:
of the customers who first bought in month M, what % came back in month M+1,
M+2, ... Reads rows from the content-addressed store (R051), no executor needed.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.cohort import cohort_retention
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.blocks.datastore import materialize_dataframe
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_ID_HINTS = ("customer", "member", "user", "client", "_id")
_DATE_HINTS = ("date", "_at", "_on", "time")


def _fact_blocks(blocks: dict | None = None) -> dict[str, DataBlockContract]:
    blocks = blocks if blocks is not None else st.session_state.get(_USER_BLOCKS_KEY, {})
    return {b: c for b, c in blocks.items() if c.block_type == BlockType.fact}


def _guess(cols: list[str], hints: tuple[str, ...]) -> int:
    for i, c in enumerate(cols):
        lc = c.lower()
        if any(h in lc for h in hints):
            return i
    return 0


# Strong customer hints (exclude bare "_id" so lot_id/tool_id don't masquerade
# as customers on non-retail data).
_STRONG_CUSTOMER = ("customer", "member", "user", "client", "顧客", "會員", "客戶")


def _cohort_applicable(contract) -> bool:
    cols = [c.name.lower() for c in contract.columns]
    has_cust = any(any(h in c for h in _STRONG_CUSTOMER) for c in cols)
    has_date = any(any(h in c for h in _DATE_HINTS) for c in cols)
    return has_cust and has_date


def render_cohort_panel(blocks: dict | None = None) -> None:
    """Render the cohort/retention panel — only on data with customer + date
    columns (Round 156: driven by the CURRENT report's data)."""
    facts = {b: c for b, c in _fact_blocks(blocks).items() if _cohort_applicable(c)}
    if not facts:
        return

    with st.expander("👥 客戶留存分析（Cohort）", expanded=False):
        st.caption("看不同月份首購的客戶，後續幾個月還會回來消費的比例。")

        bid = st.selectbox(
            "資料集", list(facts.keys()),
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="cohort_block",
        )
        contract = facts[bid]
        cols = [c.name for c in contract.columns]
        if len(cols) < 2:
            st.info("欄位不足，無法分析。")
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            cust = st.selectbox("客戶欄位", cols, index=_guess(cols, _ID_HINTS), key="cohort_cust")
        with c2:
            date_col = st.selectbox("日期欄位", cols, index=_guess(cols, _DATE_HINTS), key="cohort_date")
        with c3:
            period = st.selectbox("週期", ["month", "week"],
                                  format_func=lambda p: {"month": "月", "week": "週"}[p],
                                  key="cohort_period")

        if st.button("📊 計算留存", key="cohort_run", type="primary"):
            try:
                df = materialize_dataframe(contract)
                result = cohort_retention(df, cust, date_col, period)
                st.session_state["_cohort_result"] = result.retention
                st.session_state["_cohort_sizes"] = result.cohort_sizes
                # Round 063: also compute a repeat-purchase funnel on the same customer
                from ai4bi.analysis.funnel import purchase_frequency_funnel
                st.session_state["_funnel_result"] = purchase_frequency_funnel(df, cust)
                # Round 073: new-vs-returning revenue + value tiers (needs a revenue col)
                from ai4bi.analysis.segments import new_vs_returning_revenue, value_tier_summary
                _rev = next((c.name for c in contract.columns
                             if c.data_type in ("float", "double", "number", "numeric")
                             and any(t in c.name.lower() for t in ("revenue", "sales", "amount", "營收", "金額"))),
                            None)
                if _rev:
                    st.session_state["_nvr_result"] = new_vs_returning_revenue(df, cust, date_col, _rev, period)
                    st.session_state["_tier_result"] = value_tier_summary(df, cust, _rev)
                else:
                    st.session_state["_nvr_result"] = None
                    st.session_state["_tier_result"] = None
            except Exception as exc:  # noqa: BLE001
                st.error(f"無法計算：{exc}")

        if st.session_state.get("_cohort_result") is not None:
            st.caption("✅ 結果顯示在右側主畫面")


def render_cohort_results() -> bool:
    """Render cohort/funnel/new-vs-returning/tier results in the main canvas.

    Reads session_state keys written by render_cohort_panel. Returns True if any
    result was rendered, else False."""
    rendered = False

    retention = st.session_state.get("_cohort_result")
    if retention is not None and not retention.empty:
        rendered = True
        sizes = st.session_state.get("_cohort_sizes")
        st.caption("留存率 %（列＝首購週期，欄＝之後第幾期）")
        st.dataframe(retention, width="stretch")
        if sizes is not None and not sizes.empty:
            st.caption(
                "各 cohort 人數：" + "、".join(f"{k}={int(v)}" for k, v in sizes.items())
            )

    # Round 063: repeat-purchase funnel
    funnel = st.session_state.get("_funnel_result")
    if funnel is not None and not funnel.empty:
        rendered = True
        st.markdown("---")
        st.caption("回購漏斗：購買達 N 次的客戶數")
        try:
            import plotly.express as px
            from ai4bi.ui.theme import apply_to_fig, colorway
            fig = px.funnel(funnel, x="customers", y="stage",
                            color_discrete_sequence=colorway())
            fig.update_layout(height=260, margin=dict(l=40, r=20, t=20, b=20))
            apply_to_fig(fig)  # Round 164: active theme
            st.plotly_chart(fig, width="stretch", key="cohort_funnel_chart")
        except Exception:  # noqa: BLE001
            st.dataframe(funnel, width="stretch", hide_index=True)

    # Round 073: new vs returning revenue + value tiers
    nvr = st.session_state.get("_nvr_result")
    if nvr is not None and not nvr.empty:
        rendered = True
        st.markdown("---")
        st.caption("新客 vs 回頭客 營收（每期）")
        st.bar_chart(nvr)
    tiers = st.session_state.get("_tier_result")
    if tiers is not None and not tiers.empty:
        rendered = True
        st.caption("客戶價值分層")
        st.dataframe(tiers.rename(columns={
            "tier": "分層", "customers": "人數", "revenue": "營收", "revenue_pct": "營收占比%"}),
            width="stretch", hide_index=True)

    return rendered
