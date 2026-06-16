"""Round 049: drill-down hierarchy logic.

The drill helpers only read/write st.session_state (no reruns), so we swap in a
plain dict and exercise the pure logic directly.
"""

from __future__ import annotations

import pytest

import ai4bi.ui.drilldown as dd
from ai4bi.report.models import ReportPageSpec, ReportVisualSpec
from ai4bi.query_spec import (
    BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType, VisualQuerySpec,
)

HIER = ["city", "store_name", "product_name"]


@pytest.fixture(autouse=True)
def fake_state(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(dd.st, "session_state", state)
    return state


def _viz() -> VisualizationSpec:
    return VisualizationSpec(VisualType.bar_chart, title="drill",
                             extra={"drill_hierarchy": HIER})


def _spec() -> VisualQuerySpec:
    return VisualQuerySpec(
        "bar", [BlockRef("b")],
        metrics=[MetricRef("b", "revenue", "營收")],
        dimensions=[DimensionRef("b", "city", "地區")],
    )


def test_hierarchy_of_reads_extra():
    assert dd.hierarchy_of(_viz()) == HIER
    assert dd.hierarchy_of(VisualizationSpec(VisualType.bar_chart)) == []


def test_apply_drill_level0_groups_by_first_column():
    q = dd.apply_drill(_spec(), "bar", _viz())
    assert [d.column_name for d in q.dimensions] == ["city"]
    # no path yet → no equality filters
    assert all(f.operator.value != "eq" for f in q.filters)


def test_apply_drill_level1_filters_path_and_groups_next():
    dd._set_path("bar", [{"column": "city", "value": "台北"}])
    q = dd.apply_drill(_spec(), "bar", _viz())
    assert [d.column_name for d in q.dimensions] == ["store_name"]
    eq = [f for f in q.filters if f.column_name == "city"]
    assert len(eq) == 1 and eq[0].value == "台北"


def test_process_pending_drill_advances_path_and_clears_crossfilter(fake_state):
    page = ReportPageSpec("main", "p", {"bar": ReportVisualSpec("bar", _spec(), _viz())}, ["bar"])

    class _Report:
        pages = {"main": page}

    fake_state["cross_filters"] = {"main": {"source_spec_id": "bar", "value": "台北"}}
    changed = dd.process_pending_drill(_Report(), "main")
    assert changed
    assert dd.get_path("bar") == [{"column": "city", "value": "台北"}]
    # cross-filter consumed so it does not leak to neighbours
    assert fake_state["cross_filters"].get("main") is None


def test_drill_stops_at_last_level(fake_state):
    page = ReportPageSpec("main", "p", {"bar": ReportVisualSpec("bar", _spec(), _viz())}, ["bar"])

    class _Report:
        pages = {"main": page}

    # already at deepest level (2 steps climbed → showing product_name)
    dd._set_path("bar", [{"column": "city", "value": "台北"},
                         {"column": "store_name", "value": "信義店"}])
    fake_state["cross_filters"] = {"main": {"source_spec_id": "bar", "value": "經典T恤"}}
    dd.process_pending_drill(_Report(), "main")
    # path unchanged (no level 3) but click still consumed
    assert len(dd.get_path("bar")) == 2


def test_drill_up_and_reset():
    dd._set_path("bar", [{"column": "city", "value": "台北"},
                         {"column": "store_name", "value": "信義店"}])
    dd.drill_up("bar")
    assert dd.get_path("bar") == [{"column": "city", "value": "台北"}]
    dd.drill_reset("bar")
    assert dd.get_path("bar") == []


def test_retail_demo_bar_has_drill_hierarchy():
    from ai4bi.report.retail_template import build_retail_demo_report
    report = build_retail_demo_report()
    bar = report.pages["main"].visuals["bar_revenue_by_store"]
    assert dd.hierarchy_of(bar.visualization) == HIER
