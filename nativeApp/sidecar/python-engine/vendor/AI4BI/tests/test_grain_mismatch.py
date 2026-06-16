"""Round 046: page-level date-grain mismatch detection.

Mixing date grains (e.g. a weekly trend next to a monthly trend) is a silent
data error — numbers look comparable but aren't. _detect_grain_mismatch finds
the distinct grains used by time-bucketed visuals on a page so the UI can warn.
"""

from __future__ import annotations

from ai4bi.ui.app import _detect_grain_mismatch
from ai4bi.report.retail_template import build_retail_demo_report
from ai4bi.report.models import ReportPageSpec, ReportVisualSpec
from ai4bi.query_spec import (
    BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType, VisualQuerySpec,
)


def _visual(vid: str, grain: str | None) -> ReportVisualSpec:
    dims = []
    if grain is not None:
        dims = [DimensionRef("b", "order_date", "日期", truncate_date_to=grain)]
    return ReportVisualSpec(
        vid,
        VisualQuerySpec(vid, [BlockRef("b")],
                        metrics=[MetricRef("b", "revenue", "營收")],
                        dimensions=dims),
        VisualizationSpec(VisualType.line_chart, title=vid),
    )


def _page(*visuals: ReportVisualSpec) -> ReportPageSpec:
    vmap = {v.component_id: v for v in visuals}
    return ReportPageSpec("p", "p", vmap, list(vmap.keys()))


def test_no_mismatch_when_single_grain():
    page = _page(_visual("a", "week"), _visual("b", "week"), _visual("c", None))
    grains = _detect_grain_mismatch(page)
    assert set(grains.keys()) == {"week"}


def test_no_grain_dims_returns_empty():
    page = _page(_visual("a", None), _visual("b", None))
    assert _detect_grain_mismatch(page) == {}


def test_mismatch_detected_across_grains():
    page = _page(_visual("weekly", "week"), _visual("monthly", "month"))
    grains = _detect_grain_mismatch(page)
    assert set(grains.keys()) == {"week", "month"}
    assert "weekly" in grains["week"]
    assert "monthly" in grains["month"]


def test_shipped_retail_demo_has_no_grain_mismatch():
    """The default retail dashboard must not trip its own warning."""
    report = build_retail_demo_report()
    page = report.pages["main"]
    assert len(_detect_grain_mismatch(page)) <= 1
