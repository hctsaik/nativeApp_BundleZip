"""
ai4bi.ui.components.scatter_chart — Scatter plot component.

Round 029.

Dispatch signature: render_scatter_chart(query_spec, df, style)

Behaviour
---------
- First metric   → X axis.
- Second metric  → Y axis.  If only one metric, uses DataFrame index for Y.
- First dimension → color grouping (optional).
- style.extra["size_col"]  → column name to map to marker size (optional).
- style.extra["trendline"] → "ols" | "lowess" | None (default None).
- Cross-filter: clicking a point writes to st.session_state["cross_filters"].
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from ai4bi.query_spec import DimensionRef, MetricRef, VisualQuerySpec, VisualizationSpec
from ai4bi.ui.theme import apply_to_fig, colorway

logger = logging.getLogger(__name__)

_CROSS_FILTER_KEY = "cross_filters"
_LEGACY_CROSS_FILTER_KEY = "cross_filter"
_CURRENT_PAGE_KEY = "_current_render_page_id"


def _resolve_col(ref, df: pd.DataFrame) -> Optional[str]:
    alias = getattr(ref, "alias", None)
    raw = getattr(ref, "column_name", None) or getattr(ref, "metric_name", None)
    for c in filter(None, [alias, raw]):
        if c in df.columns:
            return c
    return None


def _handle_selection(event: Any, query_spec: VisualQuerySpec, color_col: Optional[str]) -> None:
    if not event or color_col is None:
        return
    points = (event.get("selection") or {}).get("points", [])
    if not points:
        return
    legend_group = points[0].get("legendgroup")
    if legend_group is None:
        return
    emit = query_spec.cross_filter_emit
    if emit is None:
        return
    page_id = st.session_state.get(_CURRENT_PAGE_KEY, "main")
    payload = {
        "page_id": page_id,
        "source_spec_id": query_spec.spec_id,
        "block_id": emit.block_id,
        "column_name": emit.column_name,
        "column": emit.alias or emit.column_name or color_col,
        "value": legend_group,
        "timestamp": time.time(),
    }
    cross_filters = dict(st.session_state.get(_CROSS_FILTER_KEY) or {})
    cross_filters[page_id] = payload
    st.session_state[_CROSS_FILTER_KEY] = cross_filters
    st.session_state[_LEGACY_CROSS_FILTER_KEY] = payload


def render_scatter_chart(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Render a Plotly Express scatter plot."""
    title = style.title or query_spec.spec_id

    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        return

    if not query_spec.metrics:
        st.warning(f"[{query_spec.spec_id}] No metrics — cannot render scatter chart.")
        return

    # X axis: first metric
    x_col = _resolve_col(query_spec.metrics[0], df)
    if x_col is None:
        st.error(f"[{query_spec.spec_id}] X-axis metric column not found.")
        return

    # Y axis: second metric or index
    y_col: Optional[str] = None
    if len(query_spec.metrics) >= 2:
        y_col = _resolve_col(query_spec.metrics[1], df)
    if y_col is None:
        df = df.copy()
        df["_index"] = df.index.astype(float)
        y_col = "_index"

    # Color: first dimension
    color_col: Optional[str] = None
    if query_spec.dimensions:
        color_col = _resolve_col(query_spec.dimensions[0], df)

    size_col_name: Optional[str] = style.extra.get("size_col")
    size_col = size_col_name if size_col_name and size_col_name in df.columns else None
    trendline: Optional[str] = style.extra.get("trendline")

    try:
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            color=color_col,
            symbol=color_col,  # Round 164: shape-code groups → CVD-safe even if colors confuse
            size=size_col,
            trendline=trendline,
            title=style.title or "",
            height=style.height_px,
            labels={
                x_col: style.x_axis_label or x_col,
                y_col: style.y_axis_label or y_col,
            },
            color_discrete_sequence=colorway(),
        )
    except Exception as exc:  # noqa: BLE001
        # trendline requires statsmodels; fall back gracefully
        logger.warning("[scatter_chart] trendline failed (%s), retrying without.", exc)
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            color=color_col,
            symbol=color_col,  # Round 164: shape-code groups (CVD-safe)
            size=size_col,
            title=style.title or "",
            height=style.height_px,
            labels={
                x_col: style.x_axis_label or x_col,
                y_col: style.y_axis_label or y_col,
            },
            color_discrete_sequence=colorway(),
        )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=40, b=40),
        showlegend=style.show_legend and color_col is not None,
        dragmode="select",
    )
    fig.update_xaxes(showgrid=True)
    fig.update_yaxes(showgrid=True)
    apply_to_fig(fig)  # Round 164: active theme

    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        key=f"scatter_{query_spec.spec_id}",
    )

    _handle_selection(event, query_spec, color_col)

    if color_col:
        page_id = st.session_state.get(_CURRENT_PAGE_KEY, "main")
        active_cf = (st.session_state.get(_CROSS_FILTER_KEY) or {}).get(page_id)
        if active_cf and active_cf.get("source_spec_id") == query_spec.spec_id:
            col1, col2 = st.columns([6, 1])
            with col1:
                st.caption(
                    f"Cross-filter active: **{active_cf['column']}** = `{active_cf['value']}`"
                )
            with col2:
                if st.button("Clear", key=f"cf_clear_{query_spec.spec_id}"):
                    cross_filters = dict(st.session_state.get(_CROSS_FILTER_KEY) or {})
                    cross_filters.pop(page_id, None)
                    st.session_state[_CROSS_FILTER_KEY] = cross_filters
                    st.session_state[_LEGACY_CROSS_FILTER_KEY] = None
                    st.rerun()

    logger.debug(
        "[scatter_chart] spec=%s x=%s y=%s color=%s rows=%d",
        query_spec.spec_id, x_col, y_col, color_col, len(df),
    )
