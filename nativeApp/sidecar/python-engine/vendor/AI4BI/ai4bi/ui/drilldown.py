"""Drill-down hierarchy — Round 049.

Power BI's click-to-drill: a chart starts at the top of a hierarchy
(e.g. 地區) and clicking a bar drills into the next level (門市, then 商品),
filtered to the clicked value. A breadcrumb lets the user climb back up.

How it integrates
------------------
- A visual opts in via ``VisualizationSpec.extra["drill_hierarchy"]``, an
  ordered list of column names, e.g. ["city", "store_name", "product_name"].
- Per-visual drill state lives in st.session_state["drill_state"][component_id]
  as {"path": [{"column": .., "value": ..}, ...]}. The current level is
  len(path) (capped at the last hierarchy entry).
- apply_drill() rewrites the visual's grouping dimension to the current level's
  column, adds an equality filter for each climbed step, and ranks bars by the
  primary metric.
- Bar clicks arrive through the existing cross-filter mechanism. To keep
  drill-charts from also cross-filtering their neighbours, process_pending_drill()
  consumes the click at the page level (before any visual renders): it appends
  to the path and clears the page cross-filter.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import streamlit as st

from ai4bi.query_spec import (
    DimensionRef,
    FilterOperator,
    FilterSpec,
    SortDirection,
    SortSpec,
    VisualQuerySpec,
    VisualizationSpec,
)

_DRILL_KEY = "drill_state"
_CROSS_FILTER_KEY = "cross_filters"
_LEGACY_CROSS_FILTER_KEY = "cross_filter"


def hierarchy_of(viz: VisualizationSpec) -> list[str]:
    """Return the drill hierarchy column list, or [] if the visual isn't drillable."""
    raw = (viz.extra or {}).get("drill_hierarchy")
    return [str(c) for c in raw] if raw else []


def _store() -> dict:
    return st.session_state.setdefault(_DRILL_KEY, {})


def get_path(component_id: str) -> list[dict]:
    return list(_store().get(component_id, {}).get("path", []))


def _set_path(component_id: str, path: list[dict]) -> None:
    _store()[component_id] = {"path": path}


def current_level(component_id: str, hierarchy: list[str]) -> int:
    return min(len(get_path(component_id)), max(len(hierarchy) - 1, 0))


def drill_up(component_id: str) -> None:
    path = get_path(component_id)
    if path:
        _set_path(component_id, path[:-1])


def drill_reset(component_id: str) -> None:
    _store().pop(component_id, None)


def apply_drill(
    query: VisualQuerySpec,
    component_id: str,
    viz: VisualizationSpec,
) -> VisualQuerySpec:
    """Rewrite a drillable visual's query to its current hierarchy level."""
    hierarchy = hierarchy_of(viz)
    if not hierarchy or not query.metrics:
        return query
    block_id = query.primary_block_id
    path = get_path(component_id)
    level = current_level(component_id, hierarchy)
    level_col = hierarchy[level]

    path_filters = [
        FilterSpec(block_id, step["column"], FilterOperator.eq, step["value"],
                   inherit_global_filter=False)
        for step in path
    ]
    metric_alias = query.metrics[0].alias or query.metrics[0].metric_name
    return replace(
        query,
        dimensions=[DimensionRef(block_id, level_col, level_col)],
        filters=list(query.filters) + path_filters,
        sort=[SortSpec(metric_alias, SortDirection.desc)],
        cross_filter_emit=DimensionRef(block_id, level_col, level_col),
        data_version=f"{query.data_version}:drill:{level}:"
                     + ",".join(str(s['value']) for s in path),
    )


def process_pending_drill(report, page_id: str) -> bool:
    """Convert a pending bar click on a drill-enabled visual into a drill step.

    Called once at the top of a page render, before any visual renders, so the
    click never leaks to neighbouring visuals as a cross-filter. Returns True if
    state changed (caller should st.rerun()).
    """
    cross_filters = st.session_state.get(_CROSS_FILTER_KEY) or {}
    payload = cross_filters.get(page_id) if isinstance(cross_filters, dict) else None
    if not payload:
        return False
    source_id = payload.get("source_spec_id")
    page = report.pages.get(page_id)
    if page is None or source_id not in page.visuals:
        return False
    viz = page.visuals[source_id].visualization
    hierarchy = hierarchy_of(viz)
    if not hierarchy:
        return False  # not a drill chart — leave the cross-filter alone

    # This is a drill chart: consume the click so it does not cross-filter others.
    cross_filters = dict(cross_filters)
    cross_filters.pop(page_id, None)
    st.session_state[_CROSS_FILTER_KEY] = cross_filters
    st.session_state[_LEGACY_CROSS_FILTER_KEY] = None

    level = current_level(source_id, hierarchy)
    value = payload.get("value")
    # Only advance if there is a deeper level to go to.
    if value is not None and level < len(hierarchy) - 1:
        path = get_path(source_id)
        path.append({"column": hierarchy[level], "value": value})
        _set_path(source_id, path)
    return True


def render_drill_controls(component_id: str, viz: VisualizationSpec) -> None:
    """Render a breadcrumb + up/reset controls above a drillable visual."""
    hierarchy = hierarchy_of(viz)
    if not hierarchy:
        return
    path = get_path(component_id)
    level = current_level(component_id, hierarchy)

    crumbs = ["全部"] + [str(step["value"]) for step in path]
    breadcrumb = "　›　".join(crumbs)
    next_hint = ""
    if level < len(hierarchy) - 1:
        next_hint = f"（點圖表鑽取到「{hierarchy[level + 1]}」）"

    cols = st.columns([6, 1, 1])
    with cols[0]:
        st.caption(f"📍 {breadcrumb} {next_hint}")
    with cols[1]:
        if st.button("⬅ 上層", key=f"drill_up_{component_id}", disabled=not path):
            drill_up(component_id)
            st.rerun()
    with cols[2]:
        if st.button("🔄 重設", key=f"drill_reset_{component_id}", disabled=not path):
            drill_reset(component_id)
            st.rerun()
