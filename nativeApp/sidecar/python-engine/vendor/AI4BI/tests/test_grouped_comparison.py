"""Round 071: per-dimension period-over-period delta (change decomposition)."""

from __future__ import annotations

from datetime import date

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.analysis.time_intelligence import compute_grouped_comparison
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec


def _block() -> DataBlockContract:
    # 60 days. Store A: 10/day both halves (flat). Store B: 20/day first 30,
    # then 5/day last 30 (big drop). Current window = last 30 days.
    records = []
    d0 = date(2026, 1, 1)
    for i in range(60):
        d = date.fromordinal(d0.toordinal() + i).isoformat()
        records.append({"store": "A", "order_date": d, "revenue": 10.0})
        records.append({"store": "B", "order_date": d, "revenue": 20.0 if i < 30 else 5.0})
    return DataBlockContract(
        block_id="s", block_type=BlockType.fact, grain="row", version="1.0.0",
        description="s", primary_keys=[],
        columns=[ColumnSchema(name="store", data_type="string"),
                 ColumnSchema(name="order_date", data_type="date"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum)],
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _base():
    return VisualQuerySpec("b", [BlockRef("s")], metrics=[MetricRef("s", "revenue", "營收")])


def test_decomposition_identifies_decliner():
    ex = Executor(extra_contracts={"s": _block()})
    df = compute_grouped_comparison(
        ex, _base(), date_block_id="s", date_column="order_date",
        dimension_col="store", period="month", metric_col="營收",
    ).set_index("store")
    # Store A flat: current 300 vs previous 300 → delta 0
    assert df.loc["A", "delta"] == pytest.approx(0.0)
    # Store B dropped: current 150 (5*30) vs previous 600 (20*30) → delta -450
    assert df.loc["B", "current"] == pytest.approx(150.0)
    assert df.loc["B", "previous"] == pytest.approx(600.0)
    assert df.loc["B", "delta"] == pytest.approx(-450.0)
    # B is 100% of the total change
    assert df.loc["B", "contribution_pct"] == pytest.approx(100.0)


def test_sorted_decliners_first():
    ex = Executor(extra_contracts={"s": _block()})
    df = compute_grouped_comparison(
        ex, _base(), date_block_id="s", date_column="order_date",
        dimension_col="store", period="month", metric_col="營收",
    )
    assert df.iloc[0]["store"] == "B"   # biggest drop first


def test_unknown_period_empty():
    ex = Executor(extra_contracts={"s": _block()})
    df = compute_grouped_comparison(
        ex, _base(), date_block_id="s", date_column="order_date",
        dimension_col="store", period="decade", metric_col="營收",
    )
    assert df.empty
