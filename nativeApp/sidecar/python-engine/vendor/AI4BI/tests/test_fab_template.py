"""Round 112: semiconductor fab demo dataset."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, SortDirection, SortSpec, VisualQuerySpec
from ai4bi.report.fab_template import (
    build_fab_demo_report, build_process_move_block, build_wafer_yield_block, fab_contracts,
)


def _ex():
    return Executor(extra_contracts=fab_contracts())


def test_blocks_have_volume():
    assert len(build_process_move_block().data_source.records) >= 300
    assert len(build_wafer_yield_block().data_source.records) >= 50


def test_overall_yield_reasonable():
    ex = _ex()
    q = VisualQuerySpec("t", [BlockRef("fab_wafer_yield")],
                        metrics=[MetricRef("fab_wafer_yield", "weighted_yield_pct", "y")])
    y = ex.run(q)["y"].iloc[0]
    # Round 178: ETCH-02 is now a clear yield detractor (~84% vs ETCH-01 ~93%),
    # so fab-wide yield sits in the high-80s — realistic for a fab with a problem
    # tool, and still a sane wafer yield (not summed/garbage).
    assert 80 < y < 95


def test_etch_is_the_bottleneck():
    ex = _ex()
    q = VisualQuerySpec("t", [BlockRef("fab_process_move")],
                        metrics=[MetricRef("fab_process_move", "avg_queue_time_hr", "q")],
                        dimensions=[DimensionRef("fab_process_move", "step_name", "step")],
                        sort=[SortSpec("q", SortDirection.desc)])
    df = ex.run(q)
    assert df.iloc[0]["step"] == "Etch"  # the embedded bottleneck


def test_etch02_is_yield_commonality():
    ex = _ex()
    q = VisualQuerySpec("t", [BlockRef("fab_wafer_yield")],
                        metrics=[MetricRef("fab_wafer_yield", "weighted_yield_pct", "y")],
                        dimensions=[DimensionRef("fab_wafer_yield", "etch_tool_id", "tool")],
                        sort=[SortSpec("y", SortDirection.asc)])
    df = ex.run(q)
    assert df.iloc[0]["tool"] == "ETCH-02"  # the embedded low-yield tool


def test_derived_and_distinct_metrics_execute():
    ex = _ex()
    for block, metric in [("fab_process_move", "rework_rate"),
                          ("fab_process_move", "unique_wafers"),
                          ("fab_wafer_yield", "defect_density_pct"),
                          ("fab_wafer_yield", "tested_wafers")]:
        q = VisualQuerySpec("t", [BlockRef(block)], metrics=[MetricRef(block, metric, "m")])
        assert ex.run(q)["m"].iloc[0] is not None


def test_demo_report_builds():
    r = build_fab_demo_report()
    assert r.audit.report_id == "fab_demo_v1"
    assert "main" in r.pages and r.pages["main"].visuals
