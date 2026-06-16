"""
ai4bi.ui.components.kpi_card — KPI Card visual component.

Renders a single headline metric with optional delta and sparkline.
Designed to be called from render_visual.py via the component dispatch table.

Layout (with all features enabled)
------------------------------------
┌─────────────────────────────┐
│  Title (style.title)        │
│  ─────────────────────────  │
│  123,456  ▲ +12.3%  (delta) │
│  ▁▂▃▄▅▆▇█  (sparkline)      │
│  Subtitle                   │
└─────────────────────────────┘

Empty state
-----------
When ``df`` is empty or the primary metric column is missing/all-null:
  - Renders a greyed-out "No Data" card.
  - Does NOT raise; error conditions are handled by render_visual.

Error state
-----------
Callers should wrap in try/except and use the ``inline_error`` helper to
render an inline error card instead of propagating the exception.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import streamlit as st

from ai4bi.query_spec import MetricRef, VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_number(value: float, unit: Optional[str] = None, decimals: int = 1) -> str:
    """Human-readable number with optional unit and configurable decimals.

    Round 058: ``decimals`` controls precision (Power BI parity). Large numbers
    are abbreviated (K/M/B) at the same precision.
    """
    if pd.isna(value):
        return "—"
    d = max(0, int(decimals))
    abs_val = abs(value)
    if abs_val >= 1_000_000_000:
        s = f"{value / 1_000_000_000:.{d}f}B"
    elif abs_val >= 1_000_000:
        s = f"{value / 1_000_000:.{d}f}M"
    elif abs_val >= 1_000:
        s = f"{value / 1_000:.{d}f}K"
    else:
        s = f"{value:,.{d}f}"
    return f"{s} {unit}" if unit else s


def _fmt_delta(current: float, reference: float) -> tuple[float, str]:
    """Return (absolute_delta, formatted_pct_string)."""
    delta = current - reference
    if reference != 0:
        pct = delta / abs(reference) * 100
        sign = "+" if pct >= 0 else ""
        return delta, f"{sign}{pct:.1f}%"
    return delta, ("+" if delta > 0 else "") + f"{delta:,.0f}"


def _rag_status(value: float, rag: dict) -> Optional[tuple[str, str]]:
    """Round 053: compute a RAG status (emoji, label) for a KPI value.

    rag = {"good_if": "gte"|"lte", "target": float, "warn": float (optional)}
    - good_if="gte": higher is better (revenue) → green ≥ target, amber ≥ warn, else red
    - good_if="lte": lower is better (return rate) → green ≤ target, amber ≤ warn, else red
    """
    target = rag.get("target")
    if target is None or pd.isna(value):
        return None

    def _thr(x: float) -> str:
        # ratio/percentage thresholds (<1) need decimals; large values don't
        if x != 0 and abs(x) < 1:
            return f"{x:.2g}"
        return f"{x:,.0f}"

    good_if = rag.get("good_if", "gte")
    warn = rag.get("warn")
    if good_if == "lte":
        if value <= target:
            return "🟢", f"達標（≤ {_thr(target)}）"
        if warn is not None and value <= warn:
            return "🟡", f"注意（≤ {_thr(warn)}）"
        return "🔴", f"超標（目標 ≤ {_thr(target)}）"
    # default: higher is better
    if value >= target:
        return "🟢", f"達標（≥ {_thr(target)}）"
    if warn is not None and value >= warn:
        return "🟡", f"注意（≥ {_thr(warn)}）"
    return "🔴", f"低於目標 {_thr(target)}"


def _pacing_status(value: float, target: float, good_if: str = "gte") -> Optional[tuple[float, str, bool]]:
    """Round 084: progress toward a goal.

    Returns (progress_fraction_0_to_1, caption, on_track) or None when the
    target is unusable. For good_if="gte" (higher is better) progress is
    value/target; for "lte" (lower is better, e.g. cost/return rate) progress is
    target/value so a smaller actual reads as ahead of goal.
    """
    if target is None or target == 0 or pd.isna(value):
        return None
    if good_if == "lte":
        frac = target / value if value else 2.0
        on_track = value <= target
        pct = (value / target) * 100.0
        cap = (f"✅ 達標：{pct:.0f}% of 目標（越低越好，目標 ≤ {target:,.0f}）"
               if on_track else
               f"⚠️ 超出目標 {pct - 100:.0f}%（目標 ≤ {target:,.0f}）")
    else:
        frac = value / target
        on_track = value >= target
        pct = frac * 100.0
        if on_track:
            cap = f"✅ 已達標：{pct:.0f}% of 目標 {target:,.0f}"
        else:
            cap = f"進度 {pct:.0f}%（目標 {target:,.0f}，還差 {target - value:,.0f}）"
    return max(0.0, min(frac, 1.0)), cap, on_track


def _extract_primary_value(
    df: pd.DataFrame,
    metric: MetricRef,
) -> Optional[float]:
    """
    Pull the primary aggregated value from ``df``.

    Expected shape: a single-row DataFrame where the metric column is named
    by ``metric.alias or metric.metric_name``.
    Returns None if the column is absent or the value is null.
    """
    col = metric.alias or metric.metric_name
    if col not in df.columns:
        # Fall back to raw metric name
        col = metric.metric_name
    if col not in df.columns or df.empty:
        return None
    val = df[col].iloc[0]
    return None if pd.isna(val) else float(val)


def _render_sparkline(df: pd.DataFrame, metric_col: str) -> None:
    """
    Render a minimal sparkline using st.line_chart.

    Expects ``df`` to have a time/ordinal index and the metric column.
    Uses a compact height so it fits below the headline number.
    """
    if metric_col not in df.columns or df.empty:
        return
    spark_df = df[[metric_col]].rename(columns={metric_col: "value"})
    st.line_chart(spark_df, height=60, width="stretch")


# ---------------------------------------------------------------------------
# Public component
# ---------------------------------------------------------------------------

def render_kpi_card(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
    *,
    delta_df: Optional[pd.DataFrame] = None,
) -> None:
    """
    Render a KPI card visual inside the current Streamlit column/container.

    Parameters
    ----------
    query_spec : VisualQuerySpec
        The query specification that produced ``df``.  Used to resolve metric
        names, units, and sparkline column.
    df : pd.DataFrame
        Result DataFrame from the executor.  For a simple KPI (no time
        dimension), this is typically a single-row summary.  For a sparkline,
        it must have multiple rows with a time column as the index.
    style : VisualizationSpec
        Presentation hints: title, subtitle, show_sparkline, delta_metric.
    delta_df : pd.DataFrame | None
        Optional comparison period result.  If provided and ``style.delta_metric``
        is set, a delta badge is rendered beneath the headline number.

    Notes
    -----
    - All rendering is done with plain Streamlit / st.metric() — no custom CSS
      injection so the component remains theme-compatible.
    - Errors inside this function should be caught by render_visual() and
      displayed as inline error cards.
    """
    title = style.title or (query_spec.metrics[0].alias if query_spec.metrics else "KPI")

    # ------------------------------------------------------------------ #
    # Empty state
    # ------------------------------------------------------------------ #
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.markdown(
                "<div style='color: #9e9e9e; font-size: 1.8rem; padding: 8px 0;'>—</div>",
                unsafe_allow_html=True,
            )
            st.caption("No Data")
        logger.debug("[kpi_card] spec=%s empty DataFrame — showing No Data state", query_spec.spec_id)
        return

    if not query_spec.metrics:
        st.warning(f"[{query_spec.spec_id}] No metrics defined in VisualQuerySpec.")
        return

    primary_metric = query_spec.metrics[0]

    # ------------------------------------------------------------------ #
    # Extract value
    # ------------------------------------------------------------------ #
    primary_value = _extract_primary_value(df, primary_metric)

    if primary_value is None:
        with st.container(border=True):
            st.caption(title)
            st.markdown(
                "<div style='color: #9e9e9e; font-size: 1.8rem; padding: 8px 0;'>—</div>",
                unsafe_allow_html=True,
            )
            st.caption("No Data (all values null)")
        return

    # ------------------------------------------------------------------ #
    # Delta calculation
    # ------------------------------------------------------------------ #
    delta_str: Optional[str] = None
    delta_color: str = "normal"   # "normal" | "inverse" | "off"

    if style.delta_metric and delta_df is not None and not delta_df.empty:
        try:
            ref_metric = next(
                (m for m in query_spec.metrics if m.metric_name == style.delta_metric),
                primary_metric,
            )
            ref_value = _extract_primary_value(delta_df, ref_metric)
            if ref_value is not None:
                _, delta_str = _fmt_delta(primary_value, ref_value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[kpi_card] delta calculation failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Render headline metric
    # ------------------------------------------------------------------ #
    unit = None
    # Attempt to find unit from block metric definition — not available here,
    # so we accept it as an extra hint in style.extra["unit"]
    unit = style.extra.get("unit")
    formatted_value = _fmt_number(primary_value, unit, decimals=style.extra.get("decimals", 1))

    with st.container(border=True):
        if style.subtitle:
            st.caption(style.subtitle)

        st.metric(
            label=title,
            value=formatted_value,
            delta=delta_str,
            delta_color=delta_color,
        )

        # Round 053: RAG status line (red/amber/green vs a target)
        rag = style.extra.get("rag")
        if rag:
            status = _rag_status(primary_value, rag)
            if status:
                emoji, label = status
                st.caption(f"{emoji} {label}")

        # Round 084: goal / pacing — progress bar toward a target
        target = style.extra.get("target")
        if target is not None:
            pacing = _pacing_status(
                primary_value, float(target),
                good_if=style.extra.get("target_good_if", "gte"),
            )
            if pacing:
                frac, cap, _on_track = pacing
                st.progress(frac)
                st.caption(cap)

        # ------------------------------------------------------------------ #
        # Sparkline (optional — only when df has multiple rows and a time index)
        # ------------------------------------------------------------------ #
        if style.show_sparkline and len(df) > 1:
            metric_col = primary_metric.alias or primary_metric.metric_name
            _render_sparkline(df, metric_col)

    logger.debug(
        "[kpi_card] spec=%s rendered value=%s delta=%s sparkline=%s",
        query_spec.spec_id,
        formatted_value,
        delta_str,
        style.show_sparkline,
    )
