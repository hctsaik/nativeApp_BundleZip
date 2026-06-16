"""Round 045: Derived (composite) metric formula execution + sandbox.

A metric with disaggregation_method == none carries a composite aggregate
formula (e.g. AOV = SUM(revenue) / NULLIF(SUM(order_count), 0)). The executor
expands the validated formula instead of aggregating a single column.

These tests verify:
  - the formula computes the correct number (KPI and grouped),
  - column references are resolved regardless of qualification, and
  - the allow-list rejects unknown identifiers and injection sequences.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.analysis.executor import Executor, _build_derived_formula_expr
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.planning.join_planner import QueryPlanningError
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, SortSpec, SortDirection, VisualQuerySpec


def _sales_block() -> DataBlockContract:
    records = [
        {"store": "A", "revenue": 100.0, "order_count": 4},
        {"store": "A", "revenue": 200.0, "order_count": 6},
        {"store": "B", "revenue": 150.0, "order_count": 5},
    ]
    return DataBlockContract(
        block_id="sales",
        block_type=BlockType.fact,
        grain="one row per store per day",
        version="1.0.0",
        description="test sales",
        primary_keys=[],
        columns=[
            ColumnSchema(name="store", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
            ColumnSchema(name="order_count", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum),
            MetricDefinition(name="order_count", formula="SUM(order_count)",
                             disaggregation_method=DisaggregationMethod.sum),
            MetricDefinition(
                name="aov",
                formula="SUM(revenue) / NULLIF(SUM(order_count), 0)",
                disaggregation_method=DisaggregationMethod.none,
            ),
        ],
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


# ── End-to-end execution ───────────────────────────────────────────────────

def test_derived_metric_kpi_computes_correctly():
    executor = Executor(extra_contracts={"sales": _sales_block()})
    spec = VisualQuerySpec(
        "kpi_aov", [BlockRef("sales")],
        metrics=[MetricRef("sales", "aov", "AOV")],
    )
    df = executor.run(spec)
    # total revenue 450 / total orders 15 = 30.0
    assert df["AOV"].iloc[0] == pytest.approx(30.0)


def test_derived_metric_grouped_by_dimension():
    executor = Executor(extra_contracts={"sales": _sales_block()})
    spec = VisualQuerySpec(
        "bar_aov", [BlockRef("sales")],
        metrics=[MetricRef("sales", "aov", "AOV")],
        dimensions=[DimensionRef("sales", "store", "Store")],
        sort=[SortSpec("Store", SortDirection.asc)],
    )
    df = executor.run(spec).set_index("Store")
    # A: 300/10 = 30 ; B: 150/5 = 30
    assert df.loc["A", "AOV"] == pytest.approx(30.0)
    assert df.loc["B", "AOV"] == pytest.approx(30.0)


def test_retail_demo_aov_metric_executes():
    """The shipped retail demo AOV metric runs without error."""
    from ai4bi.report.retail_template import build_retail_sales_block

    block = build_retail_sales_block()
    executor = Executor(extra_contracts={block.block_id: block})
    spec = VisualQuerySpec(
        "kpi_avg_order_value", [BlockRef(block.block_id)],
        metrics=[MetricRef(block.block_id, "avg_order_value", "平均客單價")],
    )
    df = executor.run(spec)
    assert len(df) == 1
    assert df["平均客單價"].iloc[0] > 0


# ── Formula sandbox / security ──────────────────────────────────────────────

def test_formula_qualifies_columns():
    expr = _build_derived_formula_expr(
        "SUM(revenue) / NULLIF(SUM(order_count), 0)",
        "sales", {"revenue", "order_count"},
    )
    assert '"sales"."revenue"' in expr
    assert '"sales"."order_count"' in expr
    assert "NULLIF" in expr


def test_formula_rejects_unknown_identifier():
    with pytest.raises(QueryPlanningError):
        _build_derived_formula_expr("SUM(secret_column)", "sales", {"revenue"})


def test_formula_rejects_unapproved_function():
    with pytest.raises(QueryPlanningError):
        _build_derived_formula_expr("read_csv('x')", "sales", {"revenue"})


@pytest.mark.parametrize("evil", [
    "SUM(revenue); DROP TABLE sales",
    "SUM(revenue) -- comment",
    "SUM(revenue) /* x */ + 1",
])
def test_formula_rejects_injection_sequences(evil):
    with pytest.raises(QueryPlanningError):
        _build_derived_formula_expr(evil, "sales", {"revenue"})


def test_case_when_formula_allowed():
    expr = _build_derived_formula_expr(
        "SUM(CASE WHEN revenue > 100 THEN revenue ELSE 0 END)",
        "sales", {"revenue"},
    )
    assert "CASE" in expr and '"sales"."revenue"' in expr
