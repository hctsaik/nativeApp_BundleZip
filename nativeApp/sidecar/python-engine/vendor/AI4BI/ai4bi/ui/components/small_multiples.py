"""
ai4bi.ui.components.small_multiples — trellis / faceted grid.

Round 094: Power BI "small multiples" — one mini-chart per category, on a shared
scale, for fast side-by-side comparison ("compare each category's trend").

Dispatch signature: render_small_multiples(query_spec, df, style)
- First dimension  → facet (one panel per value).
- Second dimension → x-axis (typically a date); if absent, falls back to a bar
  per facet value.
- First metric     → y-axis.
- style.extra["facet_wrap"] → panels per row (default 3).
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from ai4bi.query_spec import VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)


def _col(ref, df: pd.DataFrame) -> Optional[str]:
    alias = getattr(ref, "alias", None)
    raw = getattr(ref, "column_name", None) or getattr(ref, "metric_name", None)
    for c in filter(None, [alias, raw]):
        if c in df.columns:
            return c
    return None


def choose_facet_layout(query_spec: VisualQuerySpec, df: pd.DataFrame):
    """Resolve (facet_col, x_col, y_col) for a small-multiples render, or None.

    facet = first dimension, x = second dimension (or the facet itself if only
    one), y = first metric. Returns None when the columns can't be resolved.
    """
    if df is None or df.empty or not query_spec.metrics or not query_spec.dimensions:
        return None
    facet = _col(query_spec.dimensions[0], df)
    y = _col(query_spec.metrics[0], df)
    if facet is None or y is None:
        return None
    x = None
    if len(query_spec.dimensions) >= 2:
        x = _col(query_spec.dimensions[1], df)
    return facet, x, y


def render_small_multiples(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Render a faceted grid (one panel per first-dimension value)."""
    title = style.title or query_spec.spec_id
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        return

    layout = choose_facet_layout(query_spec, df)
    if layout is None:
        st.warning(f"[{query_spec.spec_id}] 小倍數圖需要一個分面維度與一個指標。")
        return
    facet, x, y = layout
    wrap = int((style.extra or {}).get("facet_wrap", 3))

    from ai4bi.ui.theme import apply_to_fig, colorway
    if x is not None:
        fig = px.line(df.sort_values([facet, x]), x=x, y=y,
                      facet_col=facet, facet_col_wrap=wrap, height=style.height_px,
                      title=style.title or "", color_discrete_sequence=colorway())
    else:
        # single dimension → a small bar per facet value
        fig = px.bar(df, x=facet, y=y, facet_col=facet, facet_col_wrap=wrap,
                     height=style.height_px, title=style.title or "",
                     color_discrete_sequence=colorway())
    # Trim the "facet=value" annotation prefix for a cleaner look.
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), showlegend=False)
    apply_to_fig(fig)  # Round 164: active theme
    fig.update_yaxes(matches=None)  # independent y per panel reads better for SMB

    st.plotly_chart(fig, width="stretch", key=f"sm_{query_spec.spec_id}")
    logger.debug("[small_multiples] spec=%s facet=%s x=%s y=%s",
                 query_spec.spec_id, facet, x, y)
