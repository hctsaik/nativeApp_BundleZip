"""Matrix / pivot-table component — Round 072.

Power BI's most-used object: rows × columns × a metric, with row/column totals.
The executor already groups by two dimensions (positional GROUP BY), so the
result is long-format [dim1, dim2, metric]; we pivot it to wide here.

Driven by a visual with VisualType.pivot and two dimensions (first = rows,
second = columns) + one metric. style.extra["show_totals"] (default True) adds
margins.
"""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from ai4bi.query_spec import VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)


def render_pivot(query_spec: VisualQuerySpec, df: pd.DataFrame, style: VisualizationSpec) -> None:
    """Render a pivot/matrix table from a 2-dimension, 1-metric result."""
    title = style.title or "樞紐表"
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("沒有資料。", icon="📊")
        return

    dims = [d.alias or d.column_name for d in query_spec.dimensions]
    metric = (query_spec.metrics[0].alias or query_spec.metrics[0].metric_name) \
        if query_spec.metrics else None

    # Round 172: the visual frame already renders the title (bold) — rendering it
    # again here as a caption produced the duplicated, inconsistent second title.

    # Need 2 dims + a metric present to pivot; otherwise show the plain frame.
    if len(dims) >= 2 and metric and all(d in df.columns for d in dims[:2]) and metric in df.columns:
        try:
            show_totals = bool(style.extra.get("show_totals", True))
            pv = pd.pivot_table(
                df, index=dims[0], columns=dims[1], values=metric,
                aggfunc="sum", fill_value=0,
                margins=show_totals, margins_name="總計",
            )
            st.dataframe(pv, width="stretch", height=style.height_px)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pivot] pivot_table failed: %s", exc)

    st.dataframe(df, width="stretch", hide_index=True, height=style.height_px)
