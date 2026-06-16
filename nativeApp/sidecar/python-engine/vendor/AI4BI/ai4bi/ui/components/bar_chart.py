"""
ai4bi.ui.components.bar_chart — Bar chart visual component using Plotly Express.

Features
--------
- Vertical / horizontal orientation (controlled by VisualizationSpec.extra["orientation"],
  default: "vertical").
- Stacked bar when query_spec.dimensions has 2+ entries — the second dimension
  becomes the color grouping column.
- Grouped bar when style.extra["bar_mode"] == "group" (default: "stack").
- X-axis: first DimensionRef; Y-axis: first MetricRef (simplified single-metric).
- Cross-filter: clicking a bar updates st.session_state["cross_filters"] so other
  visuals can react on the next Streamlit rerun.

Edge cases handled
------------------
- Empty DataFrame → "No Data" placeholder card.
- No metrics defined → st.warning (no crash).
- No dimensions defined → bar chart over the raw metric column with no grouping.
- Multiple metrics → only the first metric is used; a caption warns the user.
- Color/group dimension column absent from DataFrame → falls back to ungrouped.
- All-null metric column → "No Data" placeholder.

Dispatch compatibility
----------------------
Signature: render_bar_chart(query_spec, df, style)
matches the convention used by render_visual._dispatch() for all components.
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_column_name(ref: DimensionRef | MetricRef, df: pd.DataFrame) -> Optional[str]:
    """
    Resolve the effective column name for a DimensionRef or MetricRef.

    Tries alias first, then the raw name.  Returns None if neither is present
    in the DataFrame.
    """
    alias = getattr(ref, "alias", None)
    raw = getattr(ref, "column_name", None) or getattr(ref, "metric_name", None)

    for candidate in filter(None, [alias, raw]):
        if candidate in df.columns:
            return candidate
    return None


def _handle_selection(event: Any, query_spec: VisualQuerySpec, x_col: str) -> None:
    """
    Translate a Plotly selection event into a cross-filter state update.

    ``event`` is the dict returned by st.plotly_chart(..., on_select="rerun").
    """
    if not event:
        return
    points = (event.get("selection") or {}).get("points", [])
    if not points:
        return

    x_value = points[0].get("x")
    if x_value is None:
        x_value = points[0].get("label")
    if x_value is None:
        # last resort — try the first non-y key with a value
        for k, v in points[0].items():
            if k != "y" and v is not None:
                x_value = v
                break

    if x_value is None:
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
        "column": emit.alias or emit.column_name or x_col,
        "value": x_value,
        "timestamp": time.time(),
    }
    cross_filters = dict(st.session_state.get(_CROSS_FILTER_KEY) or {})
    cross_filters[page_id] = payload
    st.session_state[_CROSS_FILTER_KEY] = cross_filters
    st.session_state[_LEGACY_CROSS_FILTER_KEY] = payload
    logger.debug(
        "[bar_chart] cross-filter set: column=%s value=%s source=%s",
        emit.column_name, x_value, query_spec.spec_id,
    )


def _build_figure(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: Optional[str],
    orientation: str,
    bar_mode: str,
    style: VisualizationSpec,
) -> px.bar:
    """
    Build a Plotly Express bar figure.

    Parameters
    ----------
    df          : DataFrame already validated to be non-empty.
    x_col       : Column name for the category axis.
    y_col       : Column name for the value axis.
    color_col   : Column name for color grouping (stacked/grouped), or None.
    orientation : "vertical" | "horizontal"
    bar_mode    : "stack" | "group" | "overlay" — passed to barmode.
    style       : VisualizationSpec for layout hints.
    """
    bar_color = style.extra.get("bar_color")
    color_sequence = colorway()  # Round 164: active theme palette
    if color_col is None and isinstance(bar_color, str) and bar_color:
        color_sequence = [bar_color]

    common_kwargs: dict[str, Any] = dict(
        data_frame=df,
        color=color_col,
        color_discrete_sequence=color_sequence,
        barmode=bar_mode,
        title=style.title or "",
        height=style.height_px,
    )

    if orientation == "horizontal":
        fig = px.bar(
            x=y_col,
            y=x_col,
            orientation="h",
            labels={y_col: style.y_axis_label or y_col, x_col: style.x_axis_label or x_col},
            **common_kwargs,
        )
    else:
        fig = px.bar(
            x=x_col,
            y=y_col,
            orientation="v",
            labels={x_col: style.x_axis_label or x_col, y_col: style.y_axis_label or y_col},
            **common_kwargs,
        )

    fig.update_layout(
        showlegend=style.show_legend and color_col is not None,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        dragmode="select",
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    # Round 164: thin white seam between segments so adjacent colors (esp. in
    # stacked/grouped bars) read as separate blocks even for CVD users.
    fig.update_traces(marker_line_color="rgba(255,255,255,0.9)", marker_line_width=0.6)

    # Round 058: optional data labels on bars (Power BI parity)
    if style.extra.get("data_labels"):
        fmt = style.extra.get("number_format", ",.0f")
        axis = "x" if orientation == "horizontal" else "y"
        fig.update_traces(
            texttemplate="%{" + axis + ":" + fmt + "}",
            textposition="outside",
            cliponaxis=False,
        )
    # Round 160: axis range/scale + legend placement (Format pane). Only meaningful
    # on a vertical bar chart's value (y) axis.
    if orientation != "horizontal":
        from ai4bi.ui.components.line_chart import (
            _apply_axis_and_legend_format, apply_baseline_line,
        )
        if y_col in df.columns:
            apply_baseline_line(fig, df[y_col], style.extra)  # Round 137: baseline
        _apply_axis_and_legend_format(fig, style)
    apply_to_fig(fig)  # Round 164: stamp active theme
    return fig


# ---------------------------------------------------------------------------
# Public component
# ---------------------------------------------------------------------------

def render_bar_chart(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """
    Render a Plotly Express bar chart (vertical or horizontal, stacked or grouped).

    Parameters
    ----------
    query_spec : VisualQuerySpec
        Declarative query spec.  First metric → y-axis; first dimension → x-axis;
        second dimension (if present) → color group.
    df : pd.DataFrame
        Result DataFrame from the executor.
    style : VisualizationSpec
        Presentation hints:
          - style.extra["orientation"]: "vertical" (default) | "horizontal"
          - style.extra["bar_mode"]:    "stack" (default) | "group" | "overlay"
          - style.height_px:            chart height in pixels
          - style.title, style.x_axis_label, style.y_axis_label: labels

    Cross-filter
    ------------
    Clicking a bar writes to st.session_state["cross_filters"].
    Clear it by removing the active page entry from that mapping.
    """
    title = style.title or query_spec.spec_id
    orientation: str = style.extra.get("orientation", "vertical")
    bar_mode: str = style.extra.get("bar_mode", "stack")

    # ------------------------------------------------------------------ #
    # Guard: empty DataFrame
    # ------------------------------------------------------------------ #
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        logger.debug("[bar_chart] spec=%s empty DataFrame", query_spec.spec_id)
        return

    # ------------------------------------------------------------------ #
    # Guard: no metrics
    # ------------------------------------------------------------------ #
    if not query_spec.metrics:
        st.warning(f"[{query_spec.spec_id}] No metrics defined — cannot render bar chart.")
        return

    # ------------------------------------------------------------------ #
    # Warn if multiple metrics (only first is used)
    # ------------------------------------------------------------------ #
    if len(query_spec.metrics) > 1:
        st.caption(
            f"Bar chart uses only the first metric "
            f"(**{query_spec.metrics[0].alias or query_spec.metrics[0].metric_name}**). "
            f"Additional metrics are ignored."
        )

    primary_metric = query_spec.metrics[0]

    # ------------------------------------------------------------------ #
    # Resolve y column (metric)
    # ------------------------------------------------------------------ #
    y_col = _resolve_column_name(primary_metric, df)
    if y_col is None:
        st.error(
            f"[{query_spec.spec_id}] Metric column "
            f"'{primary_metric.alias or primary_metric.metric_name}' not found in DataFrame. "
            f"Available columns: {list(df.columns)}"
        )
        return

    # Guard: all-null metric
    if df[y_col].isna().all():
        with st.container(border=True):
            st.caption(title)
            st.info("No Data (all metric values are null)", icon="📭")
        return

    # ------------------------------------------------------------------ #
    # Resolve x column (first dimension)
    # ------------------------------------------------------------------ #
    x_col: Optional[str] = None
    if query_spec.dimensions:
        x_col = _resolve_column_name(query_spec.dimensions[0], df)

    if x_col is None:
        # No dimension — use the DataFrame index as the category axis
        df = df.copy()
        df["_index"] = df.index.astype(str)
        x_col = "_index"
        logger.debug(
            "[bar_chart] spec=%s no dimension found, using DataFrame index as x-axis",
            query_spec.spec_id,
        )

    # ------------------------------------------------------------------ #
    # Resolve color/group column (second dimension, optional)
    # ------------------------------------------------------------------ #
    color_col: Optional[str] = None
    if len(query_spec.dimensions) >= 2:
        color_col = _resolve_column_name(query_spec.dimensions[1], df)
        if color_col is None:
            logger.warning(
                "[bar_chart] spec=%s second dimension column not found in DataFrame — "
                "falling back to ungrouped",
                query_spec.spec_id,
            )

    # ------------------------------------------------------------------ #
    # Build and render figure
    # ------------------------------------------------------------------ #
    fig = _build_figure(df, x_col, y_col, color_col, orientation, bar_mode, style)

    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        key=f"bar_chart_{query_spec.spec_id}",
    )

    # ------------------------------------------------------------------ #
    # Cross-filter handling
    # ------------------------------------------------------------------ #
    _handle_selection(event, query_spec, x_col)

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
        "[bar_chart] spec=%s rendered orientation=%s bar_mode=%s x=%s y=%s color=%s rows=%d",
        query_spec.spec_id, orientation, bar_mode, x_col, y_col, color_col, len(df),
    )
