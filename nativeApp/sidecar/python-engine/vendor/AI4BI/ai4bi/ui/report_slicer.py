"""Report-level Slicer — Round 041/042.

Power BI's most-used feature: a slicer on one side of the dashboard that
filters ALL visuals simultaneously. Users don't need to configure filters
on each chart individually.

Implementation
--------------
- Scans all loaded blocks to discover available slicer columns (dimensions).
- Renders a sidebar slicer panel with multiselect/date-range pickers.
- Slicer values are stored in st.session_state["report_slicers"].
- The executor applies these as additional WHERE conditions to each visual
  by injecting them into the VisualQuerySpec filters at render time.

Slicer types
------------
- categorical: st.multiselect, values from distinct column values
- date_range:  st.date_input (range), applied as BETWEEN filter
- numeric:     st.slider (min/max), applied as BETWEEN filter
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

import pandas as pd
import streamlit as st

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.query_spec import FilterOperator, FilterSpec

_SLICER_STATE_KEY = "report_slicers"   # dict: slicer_id → value
_SLICER_CACHE_KEY = "report_slicers_cache"  # cached list[SlicerDefinition]

SlicerType = Literal["categorical", "date_range", "numeric", "relative_date"]

# Round 069: relative-date presets, anchored on the data's latest date so they
# never go stale as new data arrives.
_REL_PRESETS = {
    "all": "全部期間",
    "last_7": "最近 7 天",
    "last_30": "最近 30 天",
    "last_90": "最近 90 天",
    "mtd": "本月至今",
    "ytd": "今年至今",
}


def _relative_bounds(preset: str, anchor):
    """Return (lo, hi) dates for a relative preset, or (None, None) for 'all'."""
    import datetime as _dt
    if anchor is None:
        return None, None
    if preset == "last_7":
        return anchor - _dt.timedelta(days=6), anchor
    if preset == "last_30":
        return anchor - _dt.timedelta(days=29), anchor
    if preset == "last_90":
        return anchor - _dt.timedelta(days=89), anchor
    if preset == "mtd":
        return anchor.replace(day=1), anchor
    if preset == "ytd":
        return anchor.replace(month=1, day=1), anchor
    return None, None  # 'all'


@dataclass
class SlicerDefinition:
    slicer_id: str
    label: str
    block_id: str
    column: str
    slicer_type: SlicerType
    options: list[Any]      # for categorical: distinct values
    min_val: Any = None     # for numeric/date
    max_val: Any = None


def _discover_slicers(
    contracts: dict[str, DataBlockContract],
) -> list[SlicerDefinition]:
    """Auto-discover slicer-worthy columns from loaded contracts."""
    slicers: list[SlicerDefinition] = []
    seen: set[str] = set()

    for block_id, contract in contracts.items():
        if not hasattr(contract, "data_source"):
            continue
        from ai4bi.blocks.contracts import CachedDataSource, InlineDataSource
        if not isinstance(contract.data_source, (InlineDataSource, CachedDataSource)):
            continue
        from ai4bi.blocks.datastore import materialize_dataframe
        try:
            df = materialize_dataframe(contract)
        except (KeyError, TypeError):
            continue
        if df is None or df.empty:
            continue

        pk_set = set(contract.primary_keys)

        for col in contract.columns:
            col_name = col.name
            if col_name in pk_set:
                continue
            slicer_id = f"{block_id}_{col_name}"
            if slicer_id in seen:
                continue

            if col.data_type in ("date", "timestamp") and col_name in df.columns:
                try:
                    dates = pd.to_datetime(df[col_name].dropna()).dt.date.unique()
                    dates = sorted(dates)
                    if len(dates) >= 2:
                        # Round 069: prefer a relative-date preset slicer (never
                        # goes stale) over an absolute min/max range.
                        slicers.append(SlicerDefinition(
                            slicer_id=slicer_id,
                            label=col_name.replace("_", " ").title(),
                            block_id=block_id,
                            column=col_name,
                            slicer_type="relative_date",
                            options=list(_REL_PRESETS.keys()),
                            min_val=dates[0],
                            max_val=dates[-1],
                        ))
                        seen.add(slicer_id)
                except Exception:  # noqa: BLE001
                    pass

            elif col.data_type in ("string", "str", "object") and col_name in df.columns:
                unique_vals = sorted(df[col_name].dropna().unique().tolist())
                if 2 <= len(unique_vals) <= 30:  # reasonable slicer cardinality
                    slicers.append(SlicerDefinition(
                        slicer_id=slicer_id,
                        label=col_name.replace("_", " ").title(),
                        block_id=block_id,
                        column=col_name,
                        slicer_type="categorical",
                        options=unique_vals,
                    ))
                    seen.add(slicer_id)

    return slicers[:8]  # cap at 8 slicers to avoid sidebar overload


def get_slicer_filters(
    slicers: list[SlicerDefinition],
) -> list[FilterSpec]:
    """Convert active slicer state to FilterSpec list for injection into queries."""
    state: dict = st.session_state.get(_SLICER_STATE_KEY, {})
    filters: list[FilterSpec] = []
    for slicer in slicers:
        val = state.get(slicer.slicer_id)
        if val is None:
            continue
        if slicer.slicer_type == "categorical" and val:
            filters.append(FilterSpec(
                block_id=slicer.block_id,
                column_name=slicer.column,
                operator=FilterOperator.in_,
                value=val,
                inherit_global_filter=False,
            ))
        elif slicer.slicer_type == "date_range" and isinstance(val, (list, tuple)) and len(val) == 2:
            filters.append(FilterSpec(
                block_id=slicer.block_id,
                column_name=slicer.column,
                operator=FilterOperator.gte,
                value=str(val[0]),
                inherit_global_filter=False,
            ))
            filters.append(FilterSpec(
                block_id=slicer.block_id,
                column_name=slicer.column,
                operator=FilterOperator.lte,
                value=str(val[1]),
                inherit_global_filter=False,
            ))
        elif slicer.slicer_type == "relative_date" and val and val != "all":
            lo, hi = _relative_bounds(val, slicer.max_val)
            if lo is not None and hi is not None:
                filters.append(FilterSpec(
                    block_id=slicer.block_id, column_name=slicer.column,
                    operator=FilterOperator.gte, value=str(lo), inherit_global_filter=False,
                ))
                filters.append(FilterSpec(
                    block_id=slicer.block_id, column_name=slicer.column,
                    operator=FilterOperator.lte, value=str(hi), inherit_global_filter=False,
                ))
    return filters


def render_report_slicer(
    contracts: dict[str, DataBlockContract],
    cache,
) -> list[SlicerDefinition]:
    """Render the Report-level Slicer panel.

    Returns list of discovered SlicerDefinitions (for use in filter injection).
    """
    # Cache slicer discovery keyed by block_id set to avoid repeated DataFrame ops
    cache_key = frozenset(contracts.keys())
    cached = st.session_state.get(_SLICER_CACHE_KEY)
    if cached and cached[0] == cache_key:
        slicers = cached[1]
    else:
        slicers = _discover_slicers(contracts)
        st.session_state[_SLICER_CACHE_KEY] = (cache_key, slicers)
    if not slicers:
        return []

    if _SLICER_STATE_KEY not in st.session_state:
        st.session_state[_SLICER_STATE_KEY] = {}

    state: dict = st.session_state[_SLICER_STATE_KEY]
    changed = False

    with st.expander("🎚️ 全域篩選器", expanded=True):
        st.caption("以下篩選條件同時影響所有圖表。")
        for slicer in slicers:
            if slicer.slicer_type == "categorical":
                current = state.get(slicer.slicer_id, [])
                new_val = st.multiselect(
                    slicer.label,
                    slicer.options,
                    default=current,
                    key=f"slicer_{slicer.slicer_id}",
                )
                if new_val != current:
                    state[slicer.slicer_id] = new_val
                    changed = True
            elif slicer.slicer_type == "date_range":
                import datetime
                current = state.get(slicer.slicer_id)
                default_val = (slicer.min_val, slicer.max_val)
                new_val = st.date_input(
                    slicer.label,
                    value=current if current else default_val,
                    min_value=slicer.min_val,
                    max_value=slicer.max_val,
                    key=f"slicer_{slicer.slicer_id}",
                )
                if isinstance(new_val, (list, tuple)) and len(new_val) == 2:
                    # st.date_input returns a tuple; state stores a list.
                    # Compare as lists so an unchanged range does not look
                    # "changed" every rerun (which would cause an infinite
                    # rerun loop and hang the app on startup).
                    new_list = list(new_val)
                    if new_list != current:
                        state[slicer.slicer_id] = new_list
                        changed = True
            elif slicer.slicer_type == "relative_date":
                current = state.get(slicer.slicer_id, "all")
                opts = list(_REL_PRESETS.keys())
                new_val = st.selectbox(
                    slicer.label, opts,
                    index=opts.index(current) if current in opts else 0,
                    format_func=lambda k: _REL_PRESETS.get(k, k),
                    key=f"slicer_{slicer.slicer_id}",
                )
                if new_val != current:
                    state[slicer.slicer_id] = new_val
                    changed = True

        if state:
            if st.button("清除所有篩選器", key="slicer_clear_all"):
                st.session_state[_SLICER_STATE_KEY] = {}
                cache.invalidate_all()
                st.rerun()

    if changed:
        cache.invalidate_all()
        st.rerun()

    return slicers
