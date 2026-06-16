"""Round 107: new-product launch detection."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _detect_panel_analysis
from ai4bi.analysis.trends import new_products
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _df():
    rows = []
    # Old: sold since Jan. New: first appears in May (latest month).
    for m in (1, 2, 3, 4, 5):
        rows.append({"product_name": "Old", "order_date": f"2026-{m:02d}-10", "revenue": 100})
    rows.append({"product_name": "NewHit", "order_date": "2026-05-05", "revenue": 500})
    rows.append({"product_name": "NewHit", "order_date": "2026-05-20", "revenue": 500})
    rows.append({"product_name": "NewFlop", "order_date": "2026-05-08", "revenue": 20})
    return pd.DataFrame(rows)


def test_flags_only_new_launches():
    out = new_products(_df(), "product_name", "order_date", "revenue", period="month")
    assert set(out["product_name"]) == {"NewHit", "NewFlop"}
    assert "Old" not in set(out["product_name"])


def test_ranked_by_sales_since_launch():
    out = new_products(_df(), "product_name", "order_date", "revenue", period="month")
    assert list(out["product_name"]) == ["NewHit", "NewFlop"]  # 1000 > 20
    assert out.iloc[0]["上市以來"] == 1000.0


def test_insufficient_history_empty():
    df = pd.DataFrame([{"product_name": "X", "order_date": "2026-05-01", "revenue": 1}])
    assert new_products(df, "product_name", "order_date", "revenue").empty


def test_nl_routes_newproduct():
    assert _detect_panel_analysis("這季新品表現如何", "這季新品表現如何") == "newproduct"
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
            {"product_name": "Old", "order_date": "2026-01-10", "revenue": 100.0},
            {"product_name": "Old", "order_date": "2026-05-10", "revenue": 100.0},
            {"product_name": "New", "order_date": "2026-05-10", "revenue": 300.0},
        ]),
        policy=PolicySpec(data_classification=DataClassification.internal))}
    result = svc.propose("最近上架的新商品賣得如何？", build_retail_demo_report(), None,
                         contracts=contracts, executor=None)
    assert result.result_table is not None, result.message
    assert "New" in set(result.result_table["product_name"])
