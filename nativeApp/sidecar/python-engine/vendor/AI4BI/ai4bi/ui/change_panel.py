"""Change-decomposition panel — Round 071.

"Why did revenue change vs last period?" — breaks the period-over-period delta
down by a chosen dimension (store / category / …), ranked by contribution to the
total change. Built on time_intelligence.compute_grouped_comparison.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.time_intelligence import compute_grouped_comparison
from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec

_PERIODS = {"week": "週(7天)", "month": "月(30天)", "quarter": "季(90天)", "year": "年"}
_DATE_HINTS = ("date", "_at", "_on", "time", "day")
_ID_HINTS = ("_id", "_code", "_sku", "id")


def _primary_metric_block(report):
    for page in report.pages.values():
        for v in page.visuals.values():
            if v.query.metrics:
                m = v.query.metrics[0]
                return m.block_id, m.metric_name, (m.alias or m.metric_name)
    return None, None, None


def render_change_panel(contracts: dict[str, DataBlockContract], executor) -> None:
    """Render the change-decomposition sidebar panel."""
    from ai4bi.ui import workspace
    report = workspace.current_report()
    block_id, metric_name, metric_alias = _primary_metric_block(report)
    if block_id is None or block_id not in contracts:
        return
    contract = contracts[block_id]
    cols = [c.name for c in contract.columns]
    date_cols = [c.name for c in contract.columns
                 if c.data_type in ("date", "timestamp")
                 or any(h in c.name.lower() for h in _DATE_HINTS)]
    cat_cols = [c.name for c in contract.columns
                if c.data_type in ("string", "str", "object")
                and not any(c.name.lower().endswith(h) or c.name.lower() == "id" for h in _ID_HINTS)]
    if not date_cols or not cat_cols:
        return

    with st.expander("📉 變化分解（為什麼變了）", expanded=False):
        st.caption(f"把「{metric_alias}」對比上一期的變化,依維度拆解,看誰貢獻最多增減。")
        c1, c2 = st.columns(2)
        with c1:
            dim = st.selectbox("拆解維度", cat_cols, key="chg_dim")
        with c2:
            period = st.selectbox("期間", list(_PERIODS), format_func=lambda p: _PERIODS[p], key="chg_period")
        date_col = st.selectbox("日期欄位", date_cols, key="chg_date") if len(date_cols) > 1 else date_cols[0]

        if st.button("📊 分析變化", key="chg_run", type="primary"):
            base = VisualQuerySpec("chg_base", [BlockRef(block_id)],
                                   metrics=[MetricRef(block_id, metric_name, metric_alias)])
            # Round 178: ratio/average metrics (yield %, rate) must not be summed
            # across groups — flag so compute_grouped_comparison uses the weighted
            # overall and skips bogus additive contributions.
            _m = next((m for m in contract.metrics if m.name == metric_name), None)
            _is_ratio = bool(_m and getattr(
                getattr(_m, "disaggregation_method", None), "value", None) in ("average", "none"))
            df = compute_grouped_comparison(
                executor, base, date_block_id=block_id, date_column=date_col,
                dimension_col=dim, period=period, metric_col=metric_alias,
                is_ratio=_is_ratio,
            )
            st.session_state["_chg_result"] = df

        if st.session_state.get("_chg_result") is not None:
            st.caption("✅ 結果顯示在右側主畫面")


def render_change_results() -> bool:
    """Render change-decomposition result in the main canvas. Returns True if rendered."""
    df = st.session_state.get("_chg_result")
    if df is None or df.empty:
        return False
    total = float(df["delta"].sum())
    arrow = "▲ 成長" if total >= 0 else "▼ 下降"
    st.markdown(f"**整體{arrow} {total:,.0f}**")
    worst = df.iloc[0]
    if worst["delta"] < 0:
        st.caption(f"最大跌幅：{worst[df.columns[0]]}（{worst['delta']:,.0f}，"
                   f"佔整體變化 {worst['contribution_pct']:.0f}%）")
    show = df.rename(columns={df.columns[0]: "維度", "current": "本期",
                              "previous": "上期", "delta": "變化",
                              "delta_pct": "變化%", "contribution_pct": "佔變化%"})
    st.dataframe(show, width="stretch", hide_index=True)
    return True
