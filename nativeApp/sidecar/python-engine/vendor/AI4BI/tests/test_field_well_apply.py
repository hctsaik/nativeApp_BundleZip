"""Round 154: the drag-drop field-well's server-side apply round-trip.

The React component is verified to render in a browser; here we lock in that a
returned wells assignment is turned into a governed metrics+dimensions+chart-type
patch and actually changes the selected visual.
"""

from __future__ import annotations

import pytest

from ai4bi.ui import workspace
from ai4bi.report.retail_template import build_retail_demo_report


def _first_chart(report):
    for pid, page in report.pages.items():
        for vid, v in page.visuals.items():
            if v.visualization.visual_type.value in ("bar_chart", "line_chart"):
                return pid, vid, v
    raise AssertionError("no chart visual in retail demo")


def test_apply_field_well_result_changes_visual():
    from ai4bi.ui.app import _apply_field_well_result

    report = build_retail_demo_report()
    workspace.replace_with_loaded(report)
    report = workspace.current_report()
    page_id, vid, visual = _first_chart(report)
    fact_block = visual.query.metrics[0].block_id

    result = {
        "values": ["order_count"],
        "axis": ["region"],
        "legend": [],
        "chart_type": "bar_chart",
        "nonce": 12345,
    }
    changed = _apply_field_well_result(report, page_id, vid, visual, fact_block, result)
    assert changed is True

    updated = workspace.current_report().pages[page_id].visuals[vid]
    assert [m.metric_name for m in updated.query.metrics] == ["order_count"]
    assert [d.column_name for d in updated.query.dimensions] == ["region"]
    assert updated.visualization.visual_type.value == "bar_chart"


def test_apply_field_well_result_requires_a_measure():
    from ai4bi.ui.app import _apply_field_well_result

    report = build_retail_demo_report()
    workspace.replace_with_loaded(report)
    report = workspace.current_report()
    page_id, vid, visual = _first_chart(report)
    fact_block = visual.query.metrics[0].block_id

    # empty values must be a no-op (a visual needs at least one measure)
    result = {"values": [], "axis": ["region"], "legend": [], "chart_type": "bar_chart", "nonce": 9}
    assert _apply_field_well_result(report, page_id, vid, visual, fact_block, result) is False
