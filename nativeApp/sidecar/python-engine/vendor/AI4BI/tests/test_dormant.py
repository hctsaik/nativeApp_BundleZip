"""Round 101: dead-stock / dormant product detection (stopped selling)."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _detect_panel_analysis
from ai4bi.analysis.trends import dormant_products
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _df():
    rows = []
    # Dead: sold Jan-Mar, nothing Apr-May.
    for m in (1, 2, 3):
        rows.append({"sku": "Dead", "order_date": f"2026-{m:02d}-15", "qty": 50})
    # Alive: sells every month incl. the latest.
    for m in (1, 2, 3, 4, 5):
        rows.append({"sku": "Alive", "order_date": f"2026-{m:02d}-15", "qty": 10})
    return pd.DataFrame(rows)


def test_flags_stopped_selling_only():
    out = dormant_products(_df(), "sku", "order_date", "qty", period="month")
    assert set(out["sku"]) == {"Dead"}
    row = out.iloc[0]
    assert row["最後售出"].startswith("2026-03")
    assert row["沉睡期數"] == 2  # Apr, May


def test_alive_excluded():
    out = dormant_products(_df(), "sku", "order_date", "qty", period="month")
    assert "Alive" not in set(out["sku"])


def test_insufficient_history_empty():
    df = pd.DataFrame([{"sku": "X", "order_date": "2026-05-01", "qty": 1}])
    assert dormant_products(df, "sku", "order_date", "qty").empty


def test_missing_columns_empty():
    assert dormant_products(_df(), "nope", "order_date", "qty").empty


def test_nl_detects_and_routes_dormant():
    assert _detect_panel_analysis("有哪些滯銷品", "有哪些滯銷品") == "dormant"
    svc = NL2ProposalService()
    contracts = {"orders": DataBlockContract(
        block_id="orders", block_type=BlockType.fact, grain="line", version="1.0.0",
        description="o", primary_keys=[],
        columns=[ColumnSchema(name="product_name", data_type="string"),
                 ColumnSchema(name="order_date", data_type="date"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum)],
        data_source=InlineDataSource(records=[
            {"product_name": "Dead", "order_date": "2026-01-10", "revenue": 100.0},
            {"product_name": "Dead", "order_date": "2026-02-10", "revenue": 100.0},
            {"product_name": "Alive", "order_date": "2026-01-10", "revenue": 50.0},
            {"product_name": "Alive", "order_date": "2026-05-10", "revenue": 50.0},
        ]),
        policy=PolicySpec(data_classification=DataClassification.internal))}
    result = svc.propose("哪些商品賣不動了？", build_retail_demo_report(), None,
                         contracts=contracts, executor=None)
    assert result.result_table is not None, result.message
    assert "Dead" in set(result.result_table["product_name"])
