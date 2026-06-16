"""
ai4bi.ui.render_visual — Top-level visual dispatch with error handling.

This module is the single entry point that render_report() / app.py calls
for each visual on the dashboard.  It handles:

  1. Cache look-up (via QueryCache)
  2. Query execution with fallback (last_valid_result)
  3. Component dispatch based on VisualizationSpec.visual_type
  4. Structured error card (Retry / Undo / Reset) on query failure
  5. Empty result vs query failure distinction

Component dispatch table
------------------------
VisualType.kpi_card   → render_kpi_card
VisualType.line_chart → render_line_chart
VisualType.bar_chart  → render_bar_chart
VisualType.table      → render_data_table
(scatter, pivot, map — placeholder stubs, planned P4+)

Error card anatomy
-------------------
┌──────────────────────────────────────────────┐
│  ⚠ Query failed: <error summary>            │
│  Block: sales_fact | Spec: kpi_total_revenue │
│  [Retry]  [Undo]  [Reset]                    │
└──────────────────────────────────────────────┘

- Retry   → clears cache entry, re-executes immediately.
- Undo    → restores the last_valid_result without re-querying.
- Reset   → clears cache entry AND last_valid_result (shows empty state).
"""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any, Callable, Optional

import pandas as pd
import streamlit as st

from ai4bi.query_spec import VisualType, VisualQuerySpec, VisualizationSpec
from ai4bi.ui.cache import QueryCache
from ai4bi.ui.components.bar_chart import render_bar_chart
from ai4bi.ui.components.data_table import render_data_table
from ai4bi.ui.components.kpi_card import render_kpi_card
from ai4bi.ui.components.line_chart import render_line_chart
from ai4bi.ui.components.map_chart import render_map  # Round 083
from ai4bi.ui.components.pie_chart import render_pie_chart
from ai4bi.ui.components.small_multiples import render_small_multiples  # Round 094
from ai4bi.ui.components.pivot_table import render_pivot
from ai4bi.ui.components.scatter_chart import render_scatter_chart

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Session-state namespace for last-valid results
_LAST_VALID_KEY = "visual_last_valid"


# ---------------------------------------------------------------------------
# Executor protocol (structural typing — no ABC import needed)
# ---------------------------------------------------------------------------

_METADATA_KEY = "metadata_by_component"


class ExecutorProtocol:  # pragma: no cover
    """
    Structural interface expected of ``executor`` objects.
    Any object with a ``run(spec, active_filters) -> pd.DataFrame`` method qualifies.
    Also supports optional ``run_with_metadata(spec, ..., component_id) -> (df, meta)``.
    """
    def run(
        self,
        spec: VisualQuerySpec,
        active_filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame: ...


# ---------------------------------------------------------------------------
# Fallback execution
# ---------------------------------------------------------------------------

def _last_valid_store() -> dict[str, pd.DataFrame]:
    """Lazy-init the last-valid result store in session_state."""
    if _LAST_VALID_KEY not in st.session_state:
        st.session_state[_LAST_VALID_KEY] = {}
    return st.session_state[_LAST_VALID_KEY]


def _metadata_store() -> dict[str, Any]:
    """Lazy-init the per-component metadata store (spec 7.5 metadata_by_component)."""
    if _METADATA_KEY not in st.session_state:
        st.session_state[_METADATA_KEY] = {}
    return st.session_state[_METADATA_KEY]


def execute_with_fallback(
    query_spec: VisualQuerySpec,
    executor: ExecutorProtocol,
    cache: QueryCache,
    active_filters: Optional[dict[str, Any]] = None,
) -> tuple[pd.DataFrame, Optional[Exception]]:
    """
    Execute a query and return (DataFrame, error).

    On success:
    - Stores the result in cache.
    - Saves a copy as ``last_valid_result`` keyed by spec_id.
    - Returns (df, None).

    On failure:
    - Does NOT update the cache.
    - Returns (last_valid_result_or_empty_df, exception).

    Parameters
    ----------
    query_spec : VisualQuerySpec
    executor   : object with ``run(spec) -> pd.DataFrame``
    cache      : QueryCache instance
    active_filters : dict | None
        Current global filter state; passed through to the executor.

    Returns
    -------
    (pd.DataFrame, Optional[Exception])
        The DataFrame to render and any exception that occurred.
    """
    store = _last_valid_store()
    meta_store = _metadata_store()
    component_id = query_spec.spec_id

    # Effective global filter values are not encoded in the static spec key.
    # Prefer correctness over reuse for dynamic visuals in this MVP.
    if active_filters is not None and query_spec.inherit_global_filter:
        cache.invalidate(query_spec)

    # Try cache first
    cached = cache.get(query_spec)
    if cached is not None:
        store[component_id] = cached  # keep last-valid in sync
        # Populate basic metadata from cache if not yet stored this session
        if component_id not in meta_store:
            try:
                from ai4bi.analysis.executor import ResultMetadata
                from datetime import datetime, timezone
                meta_store[component_id] = ResultMetadata(
                    component_id=component_id,
                    row_count=len(cached),
                    executed_at=datetime.now(timezone.utc).isoformat() + " (cached)",
                    blocks_used=[ref.block_id for ref in query_spec.block_refs],
                    dimensions_used=[
                        (d.alias or d.column_name)
                        + (f" (DATE_TRUNC {d.truncate_date_to})" if d.truncate_date_to else "")
                        for d in query_spec.dimensions
                    ],
                    filters_applied=[
                        f"{f.block_id}.{f.column_name} {f.operator.value} {f.value!r}"
                        for f in query_spec.filters if f.value is not None
                    ],
                    metrics_used=[
                        {"name": m.alias or m.metric_name, "metric_id": m.metric_name,
                         "formula": m.metric_name, "agg": "—", "block_id": m.block_id}
                        for m in query_spec.metrics
                    ],
                )
            except Exception:  # noqa: BLE001
                pass
        return cached, None

    # Execute — use run_with_metadata when available (stores lineage for Explanation Panel)
    try:
        run_meta = getattr(executor, "run_with_metadata", None)
        if run_meta is not None:
            df, metadata = run_meta(query_spec, active_filters, component_id=component_id)
            meta_store[component_id] = metadata
        else:
            df = executor.run(query_spec, active_filters)
        cache.put(query_spec, df)
        cache.register_key_for_spec(query_spec)
        store[component_id] = df.copy()
        logger.debug(
            "[render_visual] execute_with_fallback spec=%s rows=%d",
            component_id, len(df),
        )
        return df, None

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[render_visual] query failed spec=%s: %s",
            component_id, exc,
            exc_info=True,
        )
        fallback = store.get(component_id, pd.DataFrame())
        return fallback, exc


# ---------------------------------------------------------------------------
# Error card
# ---------------------------------------------------------------------------

def _render_error_card(
    query_spec: VisualQuerySpec,
    exc: Exception,
    cache: QueryCache,
    on_retry: Callable[[], None],
    on_undo: Callable[[], None],
    on_reset: Callable[[], None],
) -> None:
    """
    Render a structured inline error card with Retry / Undo / Reset actions.

    Parameters
    ----------
    query_spec : VisualQuerySpec
    exc        : The exception that caused the failure.
    cache      : QueryCache — used by the Retry handler to clear the entry.
    on_retry   : Called when the user clicks "Retry".
    on_undo    : Called when the user clicks "Undo".
    on_reset   : Called when the user clicks "Reset".
    """
    error_summary = str(exc)[:200]  # truncate very long messages

    with st.container(border=True):
        st.error(
            f"**Query failed** — {error_summary}\n\n"
            f"Block: `{query_spec.primary_block_id}` | "
            f"Spec: `{query_spec.spec_id}`",
            icon="⚠️",
        )

        with st.expander("Stack trace", expanded=False):
            st.code(traceback.format_exc(), language="python")

        btn_cols = st.columns(3)
        with btn_cols[0]:
            if st.button("Retry", key=f"err_retry_{query_spec.spec_id}", type="primary"):
                on_retry()
        with btn_cols[1]:
            has_fallback = bool(_last_valid_store().get(query_spec.spec_id) is not None
                                and not _last_valid_store()[query_spec.spec_id].empty)
            if st.button(
                "Show previous result",
                key=f"err_undo_{query_spec.spec_id}",
                disabled=not has_fallback,
            ):
                on_undo()
        with btn_cols[2]:
            if st.button("Reset", key=f"err_reset_{query_spec.spec_id}"):
                on_reset()


# ---------------------------------------------------------------------------
# Component dispatch
# ---------------------------------------------------------------------------

_COMPONENT_REGISTRY: dict[VisualType, Callable] = {
    VisualType.kpi_card:   render_kpi_card,
    VisualType.line_chart: render_line_chart,
    VisualType.bar_chart:  render_bar_chart,
    VisualType.pie_chart:  render_pie_chart,   # Round 029
    VisualType.scatter:    render_scatter_chart,  # Round 029
    VisualType.table:      render_data_table,
    VisualType.pivot:      render_pivot,          # Round 072
    VisualType.map:        render_map,            # Round 083
    VisualType.small_multiples: render_small_multiples,  # Round 094
}


def _dispatch(
    visual_type: VisualType,
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Route to the appropriate component renderer."""
    renderer = _COMPONENT_REGISTRY.get(visual_type)
    if renderer is None:
        st.warning(
            f"[render_visual] Visual type '{visual_type}' is not yet implemented. "
            f"Spec: {query_spec.spec_id}"
        )
        return
    renderer(query_spec, df, style)


def _render_kpi_with_comparison(
    query_spec: VisualQuerySpec,
    style: VisualizationSpec,
    executor: ExecutorProtocol,
) -> bool:
    """Round 047: render a KPI card as a period-over-period comparison.

    Driven by ``style.extra["compare_period"]`` ("week"|"month"|"quarter"|"year")
    and ``style.extra["compare_date_column"]``. The headline shows the current
    trailing-window value and a delta vs the previous window.

    Returns True if it rendered a comparison card, False if it could not
    (caller should then fall back to the normal all-period KPI).
    """
    from dataclasses import replace as _replace

    from ai4bi.analysis.time_intelligence import compute_period_comparison

    period = style.extra.get("compare_period")
    date_column = style.extra.get("compare_date_column")
    if not period or not date_column or not query_spec.metrics:
        return False

    primary = query_spec.metrics[0]
    metric_col = primary.alias or primary.metric_name
    comp = compute_period_comparison(
        executor,
        query_spec,
        date_block_id=query_spec.primary_block_id,
        date_column=date_column,
        period=period,
        metric_col=metric_col,
    )
    if comp is None or comp.current is None:
        return False

    cur_df = pd.DataFrame({metric_col: [comp.current]})
    delta_df = (
        pd.DataFrame({metric_col: [comp.previous]})
        if comp.previous is not None else None
    )
    base_title = style.title or metric_col
    style2 = _replace(
        style,
        title=f"{base_title}（{comp.current_label}）",
        subtitle=(style.subtitle or f"對比 {comp.previous_label}"),
        delta_metric=primary.metric_name,
    )
    render_kpi_card(query_spec, cur_df, style2, delta_df=delta_df)
    return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_metadata(component_id: str) -> Optional[Any]:
    """Return the most recent ResultMetadata for a component, or None."""
    return st.session_state.get(_METADATA_KEY, {}).get(component_id)


def humanize_metadata(meta) -> str:
    """Convert ResultMetadata to a human-readable Chinese sentence. Round 032.

    Example output:
      「843 筆資料 ｜ 已套用 2 個篩選 ｜ 計算於 14:23」
    """
    if meta is None:
        return ""
    parts: list[str] = []
    if getattr(meta, "row_count", None):
        parts.append(f"{meta.row_count:,} 筆資料")
    if getattr(meta, "filters_applied", None):
        parts.append(f"已套用 {len(meta.filters_applied)} 個篩選")
    if getattr(meta, "blocks_used", None):
        parts.append(f"來源：{'、'.join(meta.blocks_used)}")
    executed_at = getattr(meta, "executed_at", "") or ""
    if executed_at and len(executed_at) >= 19:
        time_part = executed_at[11:19]  # HH:MM:SS from ISO string
        if "(cached)" in executed_at:
            parts.append(f"⚡ 快取")
        else:
            parts.append(f"計算於 {time_part}")
    return "　｜　".join(parts)


def render_visual(
    query_spec: VisualQuerySpec,
    style: VisualizationSpec,
    cache: QueryCache,
    executor: ExecutorProtocol,
    active_filters: Optional[dict[str, Any]] = None,
) -> None:
    """
    Render one visual: cache → execute → dispatch → error handling.

    This is the function called by ``app.py`` / ``analysis/executor.py``
    for each visual in a report layout.

    Parameters
    ----------
    query_spec     : VisualQuerySpec
        Declarative query specification for this visual.
    style          : VisualizationSpec
        Presentation hints (visual_type, title, etc.).
    cache          : QueryCache
        Two-tier cache instance shared across the page render.
    executor       : object with run(spec) -> pd.DataFrame
        Executes the query when there is a cache miss.
    active_filters : dict | None
        Current global filter values from the filter bar.

    Behaviour
    ---------
    - On success with data:  dispatch to component renderer.
    - On success with empty: show "No Results" — distinct from an error.
    - On failure with fallback: show stale data banner + error card.
    - On failure without fallback: show error card only.
    """
    # ------------------------------------------------------------------
    # Execute with fallback
    # ------------------------------------------------------------------
    df, exc = execute_with_fallback(query_spec, executor, cache, active_filters)

    # ------------------------------------------------------------------
    # Error card action callbacks
    # ------------------------------------------------------------------
    def _retry() -> None:
        cache.invalidate(query_spec)
        st.rerun()

    def _undo() -> None:
        # Re-render using the last_valid_result already in df (fallback)
        st.rerun()

    def _reset() -> None:
        cache.invalidate(query_spec)
        store = _last_valid_store()
        store.pop(query_spec.spec_id, None)
        st.rerun()

    # ------------------------------------------------------------------
    # Error state — query failed
    # ------------------------------------------------------------------
    if exc is not None:
        is_stale = not df.empty  # we have a fallback
        if is_stale:
            st.warning(
                f"Showing stale data for **{style.title or query_spec.spec_id}** "
                f"(last successful query). Live query failed.",
                icon="🕐",
            )
            # Render the stale data below the warning
            _dispatch(style.visual_type, query_spec, df, style)

        # Always show the error card (even alongside stale data)
        _render_error_card(query_spec, exc, cache, _retry, _undo, _reset)
        return

    # ------------------------------------------------------------------
    # Empty result — query succeeded but returned no rows
    # ------------------------------------------------------------------
    if df.empty:
        with st.container(border=True):
            title = style.title or query_spec.spec_id
            st.caption(title)
            st.info(
                "No results match the current filters.",
                icon="🔍",
            )
        logger.debug("[render_visual] spec=%s empty result (query succeeded)", query_spec.spec_id)
        return

    # ------------------------------------------------------------------
    # Happy path — dispatch to component
    # ------------------------------------------------------------------
    # Round 059: distribution histogram (raw values → binned), intercepted here
    if (style.extra or {}).get("chart_mode") == "histogram":
        from ai4bi.ui.components.histogram import render_histogram
        render_histogram(query_spec, df, style)
        return
    # Round 054: result post-processing (running total / moving avg / Pareto)
    if (style.extra or {}).get("postprocess"):
        from ai4bi.analysis.postprocess import apply_postprocess
        df = apply_postprocess(df, query_spec, style)
    # Round 047: period-over-period KPI (trailing-window delta). Falls back
    # to the plain all-period KPI if comparison data is unavailable.
    if style.visual_type == VisualType.kpi_card and style.extra.get("compare_period"):
        if _render_kpi_with_comparison(query_spec, style, executor):
            return
    _dispatch(style.visual_type, query_spec, df, style)
