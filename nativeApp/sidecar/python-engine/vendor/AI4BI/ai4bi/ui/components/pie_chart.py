"""
ai4bi.ui.components.pie_chart — Pie / Donut chart component.

Round 029: first non-bar/line chart type.

Dispatch signature: render_pie_chart(query_spec, df, style)

Behaviour
---------
- First metric  → values (slice size).
- First dimension → names (slice labels).
- style.extra["hole"]  → 0.0–0.9, set > 0 for a donut (default 0.4 = donut).
- style.extra["show_percent"] → True (default) shows percentage labels.
- Cross-filter: clicking a slice writes to st.session_state["cross_filters"].
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from ai4bi.query_spec import DimensionRef, MetricRef, VisualQuerySpec, VisualizationSpec

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


def _handle_selection(event: Any, query_spec: VisualQuerySpec, label_col: str) -> None:
    if not event:
        return
    points = (event.get("selection") or {}).get("points", [])
    if not points:
        return
    label_value = points[0].get("label")
    if label_value is None:
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
        "column": emit.alias or emit.column_name or label_col,
        "value": label_value,
        "timestamp": time.time(),
    }
    cross_filters = dict(st.session_state.get(_CROSS_FILTER_KEY) or {})
    cross_filters[page_id] = payload
    st.session_state[_CROSS_FILTER_KEY] = cross_filters
    st.session_state[_LEGACY_CROSS_FILTER_KEY] = payload


def _build_figure(df: pd.DataFrame, val_col: str, name_col, style: VisualizationSpec):
    """Construct the pie/donut Figure. Honors Format-pane controls offered for a
    pie (data_labels, legend_position) so the UI toggles aren't silently dropped."""
    hole: float = float(style.extra.get("hole", 0.4))
    show_percent: bool = bool(style.extra.get("show_percent", True))
    text_info = "percent+label" if show_percent else "label"
    # Round 135: 顯示資料標籤 toggle adds the raw value onto each slice.
    if style.extra.get("data_labels"):
        text_info = text_info + "+value"

    from ai4bi.ui.theme import apply_to_fig, colorway
    fig = px.pie(
        df,
        values=val_col,
        names=name_col,
        hole=hole,
        title=style.title or "",
        height=style.height_px,
        color_discrete_sequence=colorway(),
    )
    fig.update_traces(textinfo=text_info, pull=0.02)
    fig.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        showlegend=style.show_legend,
    )
    apply_to_fig(fig)  # Round 164: active theme (fonts/bg/colorway)
    # Round 135: shared legend placement (圖例位置) — previously ignored on pies.
    from ai4bi.ui.components.line_chart import apply_legend_position
    apply_legend_position(fig, style.extra)
    return fig


def render_pie_chart(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Render a Plotly pie / donut chart."""
    title = style.title or query_spec.spec_id

    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        return

    if not query_spec.metrics:
        st.warning(f"[{query_spec.spec_id}] No metrics — cannot render pie chart.")
        return

    val_col = _resolve_col(query_spec.metrics[0], df)
    if val_col is None:
        st.error(f"[{query_spec.spec_id}] Metric column not found in DataFrame.")
        return

    name_col: Optional[str] = None
    if query_spec.dimensions:
        name_col = _resolve_col(query_spec.dimensions[0], df)

    fig = _build_figure(df, val_col, name_col, style)

    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        key=f"pie_chart_{query_spec.spec_id}",
    )

    if name_col:
        _handle_selection(event, query_spec, name_col)

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
        "[pie_chart] spec=%s hole=%.2f rows=%d",
        query_spec.spec_id, float(style.extra.get("hole", 0.4)), len(df),
    )
