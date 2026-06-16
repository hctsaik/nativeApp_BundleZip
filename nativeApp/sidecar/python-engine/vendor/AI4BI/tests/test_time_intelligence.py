"""Round 047: trailing-window period-over-period comparison (WoW/MoM/YoY)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.analysis.time_intelligence import (
    PeriodComparison,
    compute_period_comparison,
    latest_date,
)
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec


def _daily_block() -> DataBlockContract:
    # 60 consecutive days; revenue = 10 per day for first 30 days,
    # then 20 per day for the last 30 days → MoM should be +100%.
    records = []
    d0 = date(2026, 1, 1)
    for i in range(60):
        d = d0.toordinal() + i
        rev = 10.0 if i < 30 else 20.0
        records.append({
            "order_date": date.fromordinal(d).isoformat(),
            "revenue": rev,
        })
    return DataBlockContract(
        block_id="daily",
        block_type=BlockType.fact,
        grain="one row per day",
        version="1.0.0",
        description="daily revenue",
        primary_keys=[],
        columns=[
            ColumnSchema(name="order_date", data_type="date"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum),
        ],
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _base_spec() -> VisualQuerySpec:
    return VisualQuerySpec(
        "kpi_rev", [BlockRef("daily")],
        metrics=[MetricRef("daily", "revenue", "Revenue")],
    )


def test_latest_date_resolves_max():
    ex = Executor(extra_contracts={"daily": _daily_block()})
    anchor = latest_date(ex, _base_spec(), "daily", "order_date")
    assert anchor == date(2026, 3, 1)  # Jan 1 + 59 days (2026 is not a leap year)


def test_mom_comparison_doubles():
    ex = Executor(extra_contracts={"daily": _daily_block()})
    comp = compute_period_comparison(
        ex, _base_spec(),
        date_block_id="daily", date_column="order_date",
        period="month", metric_col="Revenue",
    )
    assert isinstance(comp, PeriodComparison)
    # last 30 days: 20*30 = 600 ; prior 30 days: 10*30 = 300 → +100%
    assert comp.current == pytest.approx(600.0)
    assert comp.previous == pytest.approx(300.0)
    assert comp.delta_pct == pytest.approx(100.0)
    assert comp.has_delta


def test_unknown_period_returns_none():
    ex = Executor(extra_contracts={"daily": _daily_block()})
    comp = compute_period_comparison(
        ex, _base_spec(),
        date_block_id="daily", date_column="order_date",
        period="fortnight", metric_col="Revenue",
    )
    assert comp is None


def test_year_period_has_no_prior_data_degrades_gracefully():
    """Only 60 days of data → YoY prior window is empty → delta omitted."""
    ex = Executor(extra_contracts={"daily": _daily_block()})
    comp = compute_period_comparison(
        ex, _base_spec(),
        date_block_id="daily", date_column="order_date",
        period="year", metric_col="Revenue",
    )
    assert comp is not None
    assert comp.current is not None      # current window still captures the data
    assert comp.delta_pct is None        # no prior-year data → no delta


def test_retail_demo_revenue_kpi_comparison_runs():
    from ai4bi.report.retail_template import build_retail_sales_block

    block = build_retail_sales_block()
    ex = Executor(extra_contracts={block.block_id: block})
    spec = VisualQuerySpec(
        "kpi_revenue", [BlockRef(block.block_id)],
        metrics=[MetricRef(block.block_id, "revenue", "營收")],
    )
    comp = compute_period_comparison(
        ex, spec,
        date_block_id=block.block_id, date_column="order_date",
        period="month", metric_col="營收",
    )
    assert comp is not None
    assert comp.current is not None and comp.current > 0
