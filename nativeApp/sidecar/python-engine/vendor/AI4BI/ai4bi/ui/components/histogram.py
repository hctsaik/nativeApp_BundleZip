"""Histogram / distribution component — Round 059.

Distribution analysis ("how are transaction sizes / prices spread?") that a
GROUP BY can't express. The visual's query returns the RAW values of one numeric
column (a single dimension, no metrics → no GROUP BY), and Plotly Express bins
them. Driven by style.extra["chart_mode"] == "histogram" (intercepted in
render_visual) so we don't disturb the VisualType enum or serialization.
"""

from __future__ import annotations

import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from ai4bi.query_spec import VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)


def _value_column(query_spec: VisualQuerySpec, df: pd.DataFrame) -> str | None:
    # prefer the first declared dimension's alias/column, else first numeric col
    for dim in query_spec.dimensions:
        name = dim.alias or dim.column_name
        if name in df.columns and pd.api.types.is_numeric_dtype(df[name]):
            return name
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    return numeric[0] if numeric else None


def render_histogram(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Render a distribution histogram of one numeric column."""
    col = _value_column(query_spec, df)
    if col is None or df.empty:
        with st.container(border=True):
            st.caption(style.title or "分布")
            st.info("沒有可用的數值資料。", icon="📊")
        return

    from ai4bi.ui.theme import apply_to_fig, colorway
    bins = int(style.extra.get("bins", 20))
    fig = px.histogram(
        df, x=col, nbins=bins,
        title=style.title or "",
        height=style.height_px,
        color_discrete_sequence=[style.extra.get("bar_color") or colorway()[0]],
    )
    fig.update_layout(
        bargap=0.05,
        xaxis_title=style.x_axis_label or col,
        yaxis_title=style.y_axis_label or "筆數",
        margin=dict(l=40, r=20, t=40, b=40),
    )
    apply_to_fig(fig)  # Round 164: active theme
    st.plotly_chart(fig, width="stretch", key=f"hist_{query_spec.spec_id}")

    # quick distribution stats below the chart
    s = df[col].dropna()
    if not s.empty:
        st.caption(
            f"平均 {s.mean():,.1f}　｜　中位數 {s.median():,.1f}　｜　"
            f"最小 {s.min():,.1f}　｜　最大 {s.max():,.1f}"
        )
