"""Power BI-style drag-and-drop field-well — a custom Streamlit component.

A real bidirectional React/TS component (Streamlit Components API): the user
drags fields between 可用欄位 / 值 / 軸 / 圖例 wells with live preview, and the new
assignment is returned to Python, which rebuilds the visual through the governed
builders. Built frontend lives in ``frontend/dist`` (``npm run build``).
"""

from __future__ import annotations

import os

import streamlit.components.v1 as components

_DIR = os.path.dirname(os.path.abspath(__file__))
_BUILD_DIR = os.path.join(_DIR, "frontend", "dist")

# Only declare the component when the build exists, so the app degrades
# gracefully (falls back to dropdowns) if the frontend hasn't been built.
_AVAILABLE = os.path.isdir(_BUILD_DIR) and os.path.isfile(
    os.path.join(_BUILD_DIR, "index.html")
)
_component = (
    components.declare_component("ai4bi_field_well", path=_BUILD_DIR)
    if _AVAILABLE
    else None
)


def is_available() -> bool:
    """True when the built frontend is present and the component can render."""
    return _AVAILABLE


def field_well(
    available: list[dict],
    wells: dict,
    chart_type: str = "bar_chart",
    key: str | None = None,
):
    """Render the drag-drop field-well.

    Parameters
    ----------
    available : list of {"name", "label", "kind"} where kind is "measure"|"dimension"
    wells     : {"values": [name...], "axis": [name...], "legend": [name...]}
    chart_type: current visual type id (bar_chart/line_chart/...)

    Returns the new assignment dict {values, axis, legend, chart_type, nonce} on a
    user change, else None.
    """
    if _component is None:
        return None
    return _component(
        available=available, wells=wells, chart_type=chart_type, key=key, default=None
    )
