"""Round 100: calendar YoY ('this month vs same month last year')."""

from __future__ import annotations

from datetime import date

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_calendar_yoy
from ai4bi.analysis.executor import Executor
from ai4bi.analysis.time_intelligence import compute_calendar_comparison, _calendar_window
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec
from ai4bi.report.retail_template import build_retail_demo_report


def _two_year_block() -> DataBlockContract:
    # May 2025: 100/day for 10 days = 1000. May 2026: 150/day for 10 days = 1500.
    rows = []
    for y, rev in ((2025, 100.0), (2026, 150.0)):
        for d in range(1, 11):
            rows.append({"order_date": date(y, 5, d).isoformat(), "revenue": rev})
    return DataBlockContract(
        block_id="s", block_type=BlockType.fact, grain="day", version="1.0.0",
        description="s", primary_keys=[],
        columns=[ColumnSchema(name="order_date", data_type="date"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum, unit="NT$")],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def test_calendar_window_month():
    cur_s, cur_e, prev_s, prev_e = _calendar_window(date(2026, 5, 10), "month")
    assert cur_s == date(2026, 5, 1) and cur_e == date(2026, 5, 10)
    assert prev_s == date(2025, 5, 1) and prev_e == date(2025, 5, 10)


def test_calendar_window_leap_day_safe():
    # anchor Feb 29 2024 → prior year Feb 28 2023, no crash
    cur_s, cur_e, prev_s, prev_e = _calendar_window(date(2024, 2, 29), "month")
    assert prev_e == date(2023, 2, 28)


def test_detector():
    assert _looks_like_calendar_yoy("本月營收 vs 去年同期", "本月營收 vs 去年同期")
    assert _looks_like_calendar_yoy("revenue same month last year", "revenue same month last year")
    assert not _looks_like_calendar_yoy("最近 30 天營收", "最近 30 天營收")


def test_compute_calendar_comparison_mtd_vs_last_year():
    ex = Executor(extra_contracts={"s": _two_year_block()})
    base = VisualQuerySpec("b", [BlockRef("s")],
                           metrics=[MetricRef("s", "revenue", "營收")])
    comp = compute_calendar_comparison(ex, base, date_block_id="s", date_column="order_date",
                                       grain="month", metric_col="營收", anchor=date(2026, 5, 10))
    assert comp.current == pytest.approx(1500.0)
    assert comp.previous == pytest.approx(1000.0)
    assert comp.delta_pct == pytest.approx(50.0)


def test_nl_calendar_yoy_answer():
    svc = NL2ProposalService()
    contracts = {"s": _two_year_block()}
    ex = Executor(extra_contracts=contracts)
    result = svc.propose("營收 vs 去年同期？", build_retail_demo_report(), None,
                         contracts=contracts, executor=ex)
    assert result.direct_answer is not None, result.message
    # delta vs same period last year should be present and positive
    assert result.direct_answer.delta_pct is not None
    assert result.direct_answer.delta_pct > 0


def test_no_executor_falls_through():
    svc = NL2ProposalService()
    contracts = {"s": _two_year_block()}
    result = svc.propose("營收 vs 去年同期", build_retail_demo_report(), None,
                         contracts=contracts, executor=None)
    assert result.direct_answer is None
