"""Round 096: weekday / hour seasonality ('which days are busiest?')."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_seasonality, _is_hour_seasonality,
)
from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, VisualQuerySpec
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def test_detector():
    assert _looks_like_seasonality("哪幾天最忙", "哪幾天最忙")
    assert _looks_like_seasonality("busiest day of week", "busiest day of week")
    assert _looks_like_seasonality("哪個時段營收最高", "哪個時段營收最高")
    assert not _looks_like_seasonality("營收多少", "營收多少")
    assert _is_hour_seasonality("哪個時段最忙")
    assert not _is_hour_seasonality("哪幾天最忙")


def test_executor_groups_by_weekday():
    # the executor now emits DAYNAME() for truncate_date_to='dow'
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()})
    spec = VisualQuerySpec(
        "dow", [BlockRef("retail_sales")],
        metrics=[MetricRef("retail_sales", "revenue", "營收")],
        dimensions=[DimensionRef("retail_sales", "order_date", "星期", truncate_date_to="dow")],
    )
    df = ex.run(spec)
    assert "星期" in df.columns
    # weekday names, not dates
    assert set(df["星期"]) <= {"Monday", "Tuesday", "Wednesday", "Thursday",
                              "Friday", "Saturday", "Sunday"}


def test_weekend_lift_is_surfaced():
    # The demo encodes a weekend boost — grouping by weekday must reveal that
    # Sat/Sun out-earn an average weekday.
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()})
    spec = VisualQuerySpec(
        "dow", [BlockRef("retail_sales")],
        metrics=[MetricRef("retail_sales", "revenue", "營收")],
        dimensions=[DimensionRef("retail_sales", "order_date", "星期", truncate_date_to="dow")],
    )
    df = ex.run(spec).set_index("星期")["營收"]
    weekend = df[[d for d in ("Saturday", "Sunday") if d in df.index]].mean()
    weekday = df[[d for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
                  if d in df.index]].mean()
    assert weekend > weekday


def test_nl_busiest_day_returns_ranked_table():
    svc = NL2ProposalService()
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}
    ex = Executor(extra_contracts=contracts)
    result = svc.propose("哪幾天營收最高？", report, None, contracts=contracts, executor=ex)
    assert result.result_table is not None, result.message
    df = result.result_table
    assert "星期" in df.columns
    # busiest-first: the metric column (SchemaIndex aliases it Title-cased) descending
    metric_col = [c for c in df.columns if c != "星期"][-1]
    vals = list(df[metric_col])
    assert vals == sorted(vals, reverse=True)


def test_no_executor_falls_through():
    svc = NL2ProposalService()
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}
    result = svc.propose("哪幾天最忙", report, None, contracts=contracts, executor=None)
    assert result.result_table is None
