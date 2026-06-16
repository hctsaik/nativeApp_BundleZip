"""
ai4bi.ui.components.filter_bar — Global filter bar component.

Renders a horizontal row of filter widgets derived from FilterSpec definitions.
Active filter values are written to ``st.session_state["global_filters"]``.

Supported operator → widget mappings
--------------------------------------
``in`` / ``not_in``    → st.multiselect  (options from spec.value list)
``eq`` / ``neq``       → st.selectbox
``between``            → st.slider (two-handle) if values are numeric/date
``like``               → st.text_input
``is_null``            → st.checkbox (toggle)
``is_not_null``        → st.checkbox (toggle)
``gt``/``gte``/``lt``/``lte`` → st.number_input

Usage
-----
::

    from ai4bi.ui.components.filter_bar import render_filter_bar
    from ai4bi.query_spec import FilterSpec, FilterOperator

    filter_specs = [
        FilterSpec(
            block_id="sales_fact",
            column_name="region",
            operator=FilterOperator.in_,
            value=["North", "South", "East"],
            inherit_global_filter=True,
        ),
    ]
    active_filters = render_filter_bar(filter_specs)
    # active_filters: {"sales_fact.region": ["North"]}  — user's selection
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from ai4bi.query_spec import FilterOperator, FilterSpec

logger = logging.getLogger(__name__)

_GLOBAL_FILTER_KEY = "global_filters"


def _filter_key(spec: FilterSpec) -> str:
    """Stable session_state key for a filter widget's current value."""
    return f"gf__{spec.block_id}__{spec.column_name}"


def _render_single_filter(spec: FilterSpec) -> Any:
    """
    Render one filter widget and return the currently selected value.

    The widget key is stable across reruns so Streamlit preserves user
    selections correctly.
    """
    label = f"{spec.column_name.replace('_', ' ').title()}"
    key = _filter_key(spec)
    op = spec.operator
    default = spec.value

    if op in (FilterOperator.in_, FilterOperator.not_in):
        options = default if isinstance(default, list) else []
        return st.multiselect(label, options=options, default=options, key=key)

    elif op in (FilterOperator.eq, FilterOperator.neq):
        options = default if isinstance(default, list) else ([default] if default else [])
        idx = 0
        return st.selectbox(label, options=options, index=idx, key=key)

    elif op == FilterOperator.between:
        # Expect default = [lo, hi]
        lo, hi = (default[0], default[1]) if isinstance(default, list) and len(default) == 2 else (0, 100)
        return st.slider(label, min_value=lo, max_value=hi, value=(lo, hi), key=key)

    elif op == FilterOperator.like:
        return st.text_input(label, value=default or "", key=key)

    elif op == FilterOperator.is_null:
        return st.checkbox(f"{label} is null", value=False, key=key)

    elif op == FilterOperator.is_not_null:
        return st.checkbox(f"{label} is not null", value=True, key=key)

    elif op in (FilterOperator.gt, FilterOperator.gte, FilterOperator.lt, FilterOperator.lte):
        return st.number_input(
            label,
            value=float(default) if default is not None else 0.0,
            key=key,
        )

    else:
        logger.warning("[filter_bar] Unsupported operator '%s' for column '%s'", op, spec.column_name)
        return None


def render_filter_bar(
    filter_specs: list[FilterSpec],
    *,
    label: str = "Filters",
    show_reset: bool = True,
) -> dict[str, Any]:
    """
    Render a horizontal global filter bar and return the active filter values.

    Parameters
    ----------
    filter_specs : list[FilterSpec]
        Filter definitions.  Only specs with ``inherit_global_filter=True``
        are rendered as interactive widgets; the rest are static.
    label : str
        Section header displayed above the filter row.
    show_reset : bool
        If True, a "Reset filters" button is appended that clears all widget
        values back to their defaults.

    Returns
    -------
    dict[str, Any]
        Mapping of ``"{block_id}.{column_name}"`` → current widget value.
        This dict is also written to ``st.session_state["global_filters"]``.
    """
    if not filter_specs:
        return {}

    global_specs = [s for s in filter_specs if s.inherit_global_filter]
    if not global_specs:
        return {}

    st.markdown(f"**{label}**")

    # Distribute widgets evenly across columns (max 4 per row)
    max_cols = min(len(global_specs) + (1 if show_reset else 0), 4)
    cols = st.columns(max_cols)

    active: dict[str, Any] = {}
    for i, spec in enumerate(global_specs):
        with cols[i % max_cols]:
            value = _render_single_filter(spec)
            composite_key = f"{spec.block_id}.{spec.column_name}"
            active[composite_key] = value

    # Reset button
    if show_reset:
        with cols[(len(global_specs)) % max_cols]:
            st.markdown("&nbsp;", unsafe_allow_html=True)  # vertical alignment spacer
            if st.button("Reset", key="gf__reset_all"):
                for spec in global_specs:
                    k = _filter_key(spec)
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()

    # Persist to session_state for cross-component access
    st.session_state[_GLOBAL_FILTER_KEY] = active
    logger.debug("[filter_bar] active_filters=%s", active)
    return active
