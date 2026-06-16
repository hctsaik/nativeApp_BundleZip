"""
ai4bi.ui.components.line_chart — Line chart visual component using Plotly.

Features
--------
- Multi-series: each MetricRef in query_spec.metrics becomes a separate line.
- Cross-filter: ``on_select="rerun"`` captures point selections and writes
  them into ``st.session_state["cross_filter"]``.  Other visuals that declare
  the same dimension column as a filter will re-render with the selected value.
- Empty / null handling: missing metric columns are skipped with a warning;
  if the DataFrame is fully empty a No-Data placeholder is shown.

Cross-filter protocol
---------------------
When the user clicks a data point:
  st.session_state["cross_filters"] is updated as:
  {
      "<page_id>": {
      "source_spec_id": str,          # which chart fired the event
      "block_id": str,
      "column_name": str,
      "column": str,                  # display label for badges
      "value": Any,                   # selected x-axis value
      "timestamp": float,             # time.time() for de-duplication
      }
  }

Visuals that inherit global filters should observe this dict in their
render_visual wrapper and translate it into an active filter before
calling the executor.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai4bi.query_spec import DimensionRef, MetricRef, VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)

from ai4bi.ui.theme import apply_to_fig, colorway

_CROSS_FILTER_KEY = "cross_filters"
_LEGACY_CROSS_FILTER_KEY = "cross_filter"
_CURRENT_PAGE_KEY = "_current_render_page_id"


def _future_x(xs: list, n: int) -> list:
    """Round 074: generate ``n`` future x-axis labels for a forecast.

    If the last two x values parse as dates, extend by their step (so weekly/
    monthly data continues correctly); otherwise fall back to '預測+k' labels.
    """
    try:
        if len(xs) >= 2:
            prev, last = pd.to_datetime(xs[-2]), pd.to_datetime(xs[-1])
            if pd.notna(prev) and pd.notna(last):
                step = last - prev
                return [(last + step * (k + 1)).date().isoformat() for k in range(n)]
    except Exception:  # noqa: BLE001
        pass
    return [f"預測+{k + 1}" for k in range(n)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_x_column(query_spec: VisualQuerySpec, df: pd.DataFrame) -> Optional[str]:
    """
    Determine the x-axis column name.

    Priority:
    1. First DimensionRef that has ``truncate_date_to`` set (time-series intent).
    2. First DimensionRef's column_name.
    3. DataFrame index if it has a name.
    4. None (caller shows error).
    """
    for dim in query_spec.dimensions:
        col = dim.alias or dim.column_name
        if col in df.columns:
            return col
    if df.index.name and df.index.name in df.columns:
        return df.index.name
    return None


def _build_figure(
    df: pd.DataFrame,
    x_col: str,
    metrics: list[MetricRef],
    style: VisualizationSpec,
) -> go.Figure:
    """Construct a Plotly Figure with one trace per metric."""
    fig = go.Figure()
    palette = colorway()

    for idx, metric in enumerate(metrics):
        y_col = metric.alias or metric.metric_name
        if y_col not in df.columns:
            y_col = metric.metric_name
        if y_col not in df.columns:
            logger.warning("[line_chart] metric column '%s' not in DataFrame — skipping", y_col)
            continue

        prompted_color = style.extra.get("line_color") if idx == 0 else None
        color = prompted_color or palette[idx % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines+markers",
                name=metric.alias or metric.metric_name,
                line=dict(color=color, width=2.5),  # R164: thicker = legible at small size / on projectors
                marker=dict(size=6),
                hovertemplate=f"<b>{y_col}</b>: %{{y:,.0f}}<extra></extra>",
            )
        )

    fig.update_layout(
        title=style.title or "",
        xaxis_title=style.x_axis_label or x_col,
        yaxis_title=style.y_axis_label or "",
        height=style.height_px,
        showlegend=style.show_legend and len(metrics) > 1,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        dragmode="select",  # enables box/lasso selection for cross-filter
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    # Round 135: data labels on each point (Power BI parity). Only affects the
    # metric traces added above — the trend/forecast traces are appended later.
    if style.extra.get("data_labels"):
        fmt = style.extra.get("number_format", ",.0f")
        fig.update_traces(
            mode="lines+markers+text",
            texttemplate="%{y:" + fmt + "}",
            textposition="top center",
            cliponaxis=False,
        )
    # Round 137: horizontal baseline (mean / custom) reference line.
    _ycols = [(m.alias or m.metric_name) for m in metrics]
    _yc = next((c for c in _ycols if c in df.columns), None)
    if _yc is not None:
        apply_baseline_line(fig, df[_yc], style.extra)
    apply_to_fig(fig)  # Round 164: stamp active theme (fonts/bg/grid/colorway)
    _apply_axis_and_legend_format(fig, style)
    return fig


def _apply_axis_and_legend_format(fig, style) -> None:
    """Round 160: apply Format-pane settings from style.extra:
    y_min/y_max (axis range), y_scale ('linear'|'log'), legend_position."""
    extra = getattr(style, "extra", None) or {}
    y_scale = extra.get("y_scale")
    if y_scale == "log":
        fig.update_yaxes(type="log")
    y_min, y_max = extra.get("y_min"), extra.get("y_max")
    if y_min is not None and y_max is not None:
        # both bounds → explicit range; on a log axis the range is log10.
        import math
        rng = [y_min, y_max]
        if y_scale == "log":
            rng = [math.log10(v) if v and v > 0 else 0 for v in rng]
        fig.update_yaxes(range=rng, autorange=False)
    elif y_min is not None or y_max is not None:
        # Round 162: one-sided bound — clamp via autorangeoptions so a min-only or
        # max-only setting isn't silently ignored (the other side auto-fits).
        opts = {}
        if y_min is not None:
            opts["minallowed"] = y_min
        if y_max is not None:
            opts["maxallowed"] = y_max
        fig.update_yaxes(autorangeoptions=opts)
    apply_legend_position(fig, extra)


_LEGEND_ANCHORS = {
    "top": dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    "bottom": dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
    "right": dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    "left": dict(orientation="v", yanchor="top", y=1, xanchor="right", x=-0.1),
}


def apply_baseline_line(fig, series, extra) -> None:
    """Round 137: draw a horizontal baseline/reference line (Power BI parity).

    extra['baseline'] == 'mean'   → line at the average of `series`.
    extra['baseline'] == 'custom' → line at extra['baseline_value'].
    Used as a data baseline to see which points sit above/below it.
    """
    base = (extra or {}).get("baseline")
    if not base:
        return
    yv = None
    if base == "mean":
        try:
            yv = float(pd.Series(series).dropna().mean())
        except Exception:  # noqa: BLE001
            yv = None
    elif base == "custom":
        try:
            v = extra.get("baseline_value")
            yv = float(v) if v is not None and str(v) != "" else None
        except Exception:  # noqa: BLE001
            yv = None
    if yv is None:
        return
    label = f"平均 {yv:,.2f}" if base == "mean" else f"基準 {yv:,.2f}"
    fig.add_hline(y=yv, line_dash="dot", line_color="#E45756", line_width=2,
                  annotation_text=label, annotation_position="top left")


def apply_legend_position(fig, extra) -> None:
    """Round 135: shared legend placement (line/bar/pie) so every chart that
    offers the 圖例位置 control honors it. 'hide' turns the legend off."""
    pos = (extra or {}).get("legend_position")
    if not pos:
        return
    if pos == "hide":
        fig.update_layout(showlegend=False)
        return
    fig.update_layout(showlegend=True, legend=_LEGEND_ANCHORS.get(pos, _LEGEND_ANCHORS["top"]))


def _handle_selection(
    event: Any,
    query_spec: VisualQuerySpec,
    x_col: str,
) -> None:
    """
    Translate a Plotly selection event into a cross-filter update.

    ``event`` is the dict returned by ``st.plotly_chart(..., on_select="rerun")``.
    Streamlit populates ``event["selection"]["points"]`` on a click/box-select.
    """
    if not event:
        return
    points = (event.get("selection") or {}).get("points", [])
    if not points:
        return

    # Use the first selected point's x-value
    x_value = points[0].get("x")
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
        "[line_chart] cross-filter set: column=%s value=%s source=%s",
        emit.column_name, x_value, query_spec.spec_id,
    )


# ---------------------------------------------------------------------------
# Public component
# ---------------------------------------------------------------------------

def render_line_chart(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """
    Render a multi-series Plotly line chart with cross-filter support.

    Parameters
    ----------
    query_spec : VisualQuerySpec
        Query specification; metrics become series, first dimension is x-axis.
    df : pd.DataFrame
        Result DataFrame from the executor.  Must contain one column per metric
        (named by ``metric.alias or metric.metric_name``) and one column for
        the x-axis dimension.
    style : VisualizationSpec
        Presentation hints: title, axis labels, height, color scheme.

    Cross-filter
    ------------
    Clicking a data point writes to ``st.session_state["cross_filter"]``.
    A subsequent Streamlit rerun causes other visuals to pick up the new filter.
    To clear the cross-filter, set ``st.session_state["cross_filter"] = None``.
    """
    title = style.title or query_spec.spec_id

    # ------------------------------------------------------------------ #
    # Empty state
    # ------------------------------------------------------------------ #
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        logger.debug("[line_chart] spec=%s empty DataFrame", query_spec.spec_id)
        return

    if not query_spec.metrics:
        st.warning(f"[{query_spec.spec_id}] No metrics defined — cannot render line chart.")
        return

    # ------------------------------------------------------------------ #
    # Resolve x-axis column
    # ------------------------------------------------------------------ #
    x_col = _resolve_x_column(query_spec, df)
    if x_col is None:
        st.error(
            f"[{query_spec.spec_id}] Cannot determine x-axis column. "
            "Add a DimensionRef to VisualQuerySpec."
        )
        return

    # ------------------------------------------------------------------ #
    # Build and render figure
    # ------------------------------------------------------------------ #
    fig = _build_figure(df, x_col, query_spec.metrics, style)

    # ------------------------------------------------------------------ #
    # Trend line overlay (Round 027)
    # ------------------------------------------------------------------ #
    trend_cfg = style.extra.get("trend_line")
    if trend_cfg and not df.empty and query_spec.metrics:
        try:
            import numpy as np
            import plotly.graph_objects as go
            y_col = next(
                (c for c in [query_spec.metrics[0].alias, query_spec.metrics[0].metric_name]
                 if c in df.columns),
                None,
            )
            if y_col is not None:
                method = trend_cfg.get("method", "linear")
                color = trend_cfg.get("color", "#888888")
                dash = trend_cfg.get("dash", "dot")
                y_vals = df[y_col].fillna(0).values
                x_idx = np.arange(len(y_vals))
                if method == "moving_avg":
                    window = int(trend_cfg.get("window", 3))
                    trend = pd.Series(y_vals).rolling(window, min_periods=1).mean().values
                else:  # linear
                    coeffs = np.polyfit(x_idx, y_vals, 1)
                    trend = np.polyval(coeffs, x_idx)
                fig.add_trace(go.Scatter(
                    x=df[x_col],
                    y=trend,
                    mode="lines",
                    name="趨勢線",
                    line=dict(color=color, dash=dash, width=2),
                    showlegend=True,
                ))
                # Round 074: project the linear trend into the future
                forecast_n = int(trend_cfg.get("forecast_periods", 0))
                if method == "linear" and forecast_n > 0:
                    fut_idx = np.arange(len(y_vals), len(y_vals) + forecast_n)
                    fut_y = np.polyval(coeffs, fut_idx)
                    fut_x = _future_x(list(df[x_col]), forecast_n)
                    fig.add_trace(go.Scatter(
                        x=[df[x_col].iloc[-1]] + fut_x,
                        y=[float(trend[-1])] + [float(v) for v in fut_y],
                        mode="lines+markers",
                        name=f"預測 (+{forecast_n})",
                        line=dict(color="#E45756", dash="dash", width=2),
                        showlegend=True,
                    ))
        except Exception:  # noqa: BLE001
            pass

    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        key=f"line_chart_{query_spec.spec_id}",
    )

    # ------------------------------------------------------------------ #
    # Cross-filter handling
    # ------------------------------------------------------------------ #
    _handle_selection(event, query_spec, x_col)

    # Surface active cross-filter badge
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
        "[line_chart] spec=%s rendered %d series x=%s rows=%d",
        query_spec.spec_id, len(query_spec.metrics), x_col, len(df),
    )
