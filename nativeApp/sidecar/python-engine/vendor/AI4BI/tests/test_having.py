"""Round 079: post-aggregate filtering (SQL HAVING).

Unblocks segmentation questions that single-GROUP-BY + pre-aggregation WHERE
could not express: "customers who bought more than N times", "products below
NT$X" (slow movers), VIP / churn lists.
"""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.planning.join_planner import QueryPlanningError
from ai4bi.query_spec import (
    BlockRef, DimensionRef, FilterOperator, HavingSpec, MetricRef, VisualQuerySpec,
)


def _orders_block() -> DataBlockContract:
    # Alice: 4 orders / 400 revenue; Bob: 2 orders / 600; Cara: 1 order / 50.
    rows = [
        {"customer": "Alice", "product": "Tea",    "revenue": 100.0, "orders": 1},
        {"customer": "Alice", "product": "Tea",    "revenue": 100.0, "orders": 1},
        {"customer": "Alice", "product": "Cake",   "revenue": 100.0, "orders": 1},
        {"customer": "Alice", "product": "Cake",   "revenue": 100.0, "orders": 1},
        {"customer": "Bob",   "product": "Tea",    "revenue": 300.0, "orders": 1},
        {"customer": "Bob",   "product": "Cake",   "revenue": 300.0, "orders": 1},
        {"customer": "Cara",  "product": "Tea",    "revenue": 50.0,  "orders": 1},
    ]
    return DataBlockContract(
        block_id="orders",
        block_type=BlockType.fact,
        grain="one row per order line",
        version="1.0.0",
        description="orders",
        primary_keys=[],
        columns=[
            ColumnSchema(name="customer", data_type="string"),
            ColumnSchema(name="product", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
            ColumnSchema(name="orders", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum, unit="NT$"),
            MetricDefinition(name="orders", formula="SUM(orders)",
                             disaggregation_method=DisaggregationMethod.sum),
        ],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _ex() -> Executor:
    return Executor(extra_contracts={"orders": _orders_block()})


def test_having_count_greater_than():
    # "customers who bought more than 3 times" → only Alice (4 orders)
    spec = VisualQuerySpec(
        "vip", [BlockRef("orders")],
        metrics=[MetricRef("orders", "orders", "Orders")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
        having=[HavingSpec("orders", "orders", FilterOperator.gt, 3)],
    )
    df = _ex().run(spec)
    assert list(df["Customer"]) == ["Alice"]
    assert int(df["Orders"].iloc[0]) == 4


def test_having_revenue_below_threshold():
    # "slow movers: customers below NT$500" → Cara (50) only; Alice=400 also <500
    spec = VisualQuerySpec(
        "slow", [BlockRef("orders")],
        metrics=[MetricRef("orders", "revenue", "Revenue")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
        having=[HavingSpec("orders", "revenue", FilterOperator.lt, 500)],
        sort=[],
    )
    df = _ex().run(spec)
    got = set(df["Customer"])
    assert got == {"Alice", "Cara"}  # Bob=600 excluded


def test_having_multiple_predicates_and():
    # bought >3 times AND revenue < 500 → Alice (4 orders, 400 revenue)
    spec = VisualQuerySpec(
        "combo", [BlockRef("orders")],
        metrics=[MetricRef("orders", "orders", "Orders"),
                 MetricRef("orders", "revenue", "Revenue")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
        having=[
            HavingSpec("orders", "orders", FilterOperator.gt, 3),
            HavingSpec("orders", "revenue", FilterOperator.lt, 500),
        ],
    )
    df = _ex().run(spec)
    assert list(df["Customer"]) == ["Alice"]


def test_having_between():
    spec = VisualQuerySpec(
        "mid", [BlockRef("orders")],
        metrics=[MetricRef("orders", "revenue", "Revenue")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
        having=[HavingSpec("orders", "revenue", FilterOperator.between, [100, 500])],
    )
    df = _ex().run(spec)
    assert set(df["Customer"]) == {"Alice"}  # 400 in [100,500]; Bob 600 out; Cara 50 out


def test_having_on_total_single_group():
    # No dimension: HAVING filters the single aggregate group.
    spec = VisualQuerySpec(
        "tot", [BlockRef("orders")],
        metrics=[MetricRef("orders", "revenue", "Revenue")],
        having=[HavingSpec("orders", "revenue", FilterOperator.gt, 9999)],
    )
    df = _ex().run(spec)
    assert df.empty  # total revenue 1050 is not > 9999


def test_having_unprojected_metric_raises():
    spec = VisualQuerySpec(
        "bad", [BlockRef("orders")],
        metrics=[MetricRef("orders", "revenue", "Revenue")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
        having=[HavingSpec("orders", "orders", FilterOperator.gt, 3)],  # 'orders' not projected
    )
    with pytest.raises(QueryPlanningError):
        _ex().run(spec)


def test_no_having_is_unchanged():
    spec = VisualQuerySpec(
        "plain", [BlockRef("orders")],
        metrics=[MetricRef("orders", "orders", "Orders")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
    )
    df = _ex().run(spec)
    assert set(df["Customer"]) == {"Alice", "Bob", "Cara"}


def test_having_changes_cache_key():
    base = VisualQuerySpec(
        "ck", [BlockRef("orders")],
        metrics=[MetricRef("orders", "orders", "Orders")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
    )
    with_having = VisualQuerySpec(
        "ck", [BlockRef("orders")],
        metrics=[MetricRef("orders", "orders", "Orders")],
        dimensions=[DimensionRef("orders", "customer", "Customer")],
        having=[HavingSpec("orders", "orders", FilterOperator.gt, 3)],
    )
    assert base.cache_key() != with_having.cache_key()
