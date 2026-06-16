"""Round 099: COUNT(DISTINCT) — first-class disaggregation + derived formula."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, VisualQuerySpec
from ai4bi.report.retail_template import build_retail_sales_block


def _block() -> DataBlockContract:
    rows = [
        {"customer_id": "A", "city": "台北", "revenue": 10.0},
        {"customer_id": "A", "city": "台北", "revenue": 10.0},   # dup customer
        {"customer_id": "B", "city": "台北", "revenue": 10.0},
        {"customer_id": "C", "city": "台中", "revenue": 10.0},
    ]
    return DataBlockContract(
        block_id="orders", block_type=BlockType.fact, grain="line", version="1.0.0",
        description="o", primary_keys=[],
        columns=[ColumnSchema(name="customer_id", data_type="string"),
                 ColumnSchema(name="city", data_type="string"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[
            # first-class count_distinct: metric name IS the column to dedupe
            MetricDefinition(name="customer_id", formula="COUNT(DISTINCT customer_id)",
                             disaggregation_method=DisaggregationMethod.count_distinct,
                             description="distinct customers"),
            # derived form: name != column
            MetricDefinition(name="unique_customers", formula="COUNT(DISTINCT customer_id)",
                             disaggregation_method=DisaggregationMethod.none),
        ],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def test_first_class_count_distinct_total():
    ex = Executor(extra_contracts={"orders": _block()})
    spec = VisualQuerySpec("d", [BlockRef("orders")],
                           metrics=[MetricRef("orders", "customer_id", "獨立客戶")])
    df = ex.run(spec)
    assert int(df["獨立客戶"].iloc[0]) == 3  # A, B, C


def test_count_distinct_by_dimension():
    ex = Executor(extra_contracts={"orders": _block()})
    spec = VisualQuerySpec(
        "d", [BlockRef("orders")],
        metrics=[MetricRef("orders", "customer_id", "獨立客戶")],
        dimensions=[DimensionRef("orders", "city", "city")])
    df = ex.run(spec).set_index("city")["獨立客戶"]
    assert int(df["台北"]) == 2   # A, B
    assert int(df["台中"]) == 1   # C


def test_derived_count_distinct():
    ex = Executor(extra_contracts={"orders": _block()})
    spec = VisualQuerySpec("d", [BlockRef("orders")],
                           metrics=[MetricRef("orders", "unique_customers", "U")])
    df = ex.run(spec)
    assert int(df["U"].iloc[0]) == 3


def test_retail_demo_unique_customers_metric():
    # the demo's unique_customers metric executes
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()})
    spec = VisualQuerySpec("d", [BlockRef("retail_sales")],
                           metrics=[MetricRef("retail_sales", "unique_customers", "不重複客戶")])
    df = ex.run(spec)
    assert int(df["不重複客戶"].iloc[0]) > 0
