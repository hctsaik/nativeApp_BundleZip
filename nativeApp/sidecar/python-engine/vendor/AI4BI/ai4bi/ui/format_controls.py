"""Round 135: single source of truth for which Format-pane controls apply to
which visual type.

Both the UI gating (``_render_format_controls`` in app.py) and the renderer
coverage test (``tests/test_format_controls_coverage.py``) import this mapping,
so a control can never be *offered* for a chart type whose renderer silently
ignores it (the class of bug behind "顯示資料標籤 does nothing on a line chart").

When you add a Format control or extend one to a new chart type:
  1. add/extend the entry here,
  2. implement it in that chart's renderer,
  3. the coverage test will fail until the renderer actually honors it.
"""

from __future__ import annotations

# control_id -> visual types (VisualType.value strings) that OFFER it in the pane
FORMAT_CONTROL_VTYPES: dict[str, tuple[str, ...]] = {
    "sort": ("bar_chart", "pie_chart", "table"),
    "y_axis": ("line_chart", "bar_chart"),          # y_min / y_max / y_scale
    "data_labels": ("bar_chart", "line_chart", "pie_chart"),
    "legend_position": ("line_chart", "bar_chart", "pie_chart"),
    "baseline": ("line_chart", "bar_chart"),       # horizontal mean/custom reference line
}


def offers(control_id: str, vtype: str) -> bool:
    return vtype in FORMAT_CONTROL_VTYPES.get(control_id, ())
