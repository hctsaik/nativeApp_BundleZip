"""Round 086: NL routing to the pandas analytics engines (churn / decline / basket).

The compute (RFM, declining_streaks, basket_affinity) shipped in R077/R082/R085
but was sidebar-only. These tests prove a typed question reaches the engine and
returns a result table.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService, _detect_panel_analysis
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _sales_block() -> DataBlockContract:
    today = date(2026, 5, 30)
    rows = []
    # VIP buys weekly; Lapsed stopped 6 months ago. Each VIP visit buys Tea AND
    # Cake on the same day → a multi-item basket for affinity.
    for i in range(20):
        d = (today - timedelta(days=i * 2)).isoformat()
        rows.append({"customer_id": "VIP", "order_date": d, "product_name": "Tea", "revenue": 500.0})
        rows.append({"customer_id": "VIP", "order_date": d, "product_name": "Cake", "revenue": 300.0})
    for i in range(5):
        rows.append({"customer_id": "Lapsed", "order_date": (today - timedelta(days=180 + i)).isoformat(),
                     "product_name": "Tea", "revenue": 300.0})
    # A SKU that declines monthly for 4 months.
    for k, rev in enumerate([800, 600, 400, 200]):
        m = today.replace(day=1) - timedelta(days=30 * (3 - k))
        rows.append({"customer_id": f"C{k}", "order_date": m.isoformat(),
                     "product_name": "FadingSKU", "revenue": float(rev)})
    return DataBlockContract(
        block_id="sales", block_type=BlockType.fact, grain="line", version="1.0.0",
        description="sales", primary_keys=[],
        columns=[
            ColumnSchema(name="customer_id", data_type="string"),
            ColumnSchema(name="order_date", data_type="date"),
            ColumnSchema(name="product_name", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum, unit="NT$")],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _ctx():
    return NL2ProposalService(), build_retail_demo_report(), {"sales": _sales_block()}


def test_detect_routes_keywords():
    assert _detect_panel_analysis("哪些客戶快流失", "哪些客戶快流失") == "churn"
    assert _detect_panel_analysis("哪些商品連續下滑", "哪些商品連續下滑") == "decline"
    assert _detect_panel_analysis("常一起買的商品", "常一起買的商品") == "basket"
    assert _detect_panel_analysis("營收多少", "營收多少") is None


def test_churn_question_returns_rfm_table():
    svc, report, contracts = _ctx()
    result = svc.propose("哪些客戶快流失了？", report, None, contracts=contracts, executor=None)
    assert result.result_table is not None
    assert isinstance(result.result_table, pd.DataFrame)
    assert "流失風險" in result.result_table.columns
    assert "流失風險" in result.message or "客戶" in result.message


def test_decline_question_returns_streak_table():
    svc, report, contracts = _ctx()
    result = svc.propose("哪些商品連續下滑？", report, None, contracts=contracts, executor=None)
    assert result.result_table is not None
    assert "FadingSKU" in set(result.result_table["product_name"])


def test_basket_question_returns_pairs():
    svc, report, contracts = _ctx()
    result = svc.propose("哪些商品常一起買？", report, None, contracts=contracts, executor=None)
    assert result.result_table is not None
    assert "商品A" in result.result_table.columns


def test_panel_analysis_works_without_executor():
    # These run on materialized rows, not the executor — must not require one.
    svc, report, contracts = _ctx()
    result = svc.propose("哪些客戶快流失", report, None, contracts=contracts, executor=None)
    assert result.result_table is not None


def test_no_contracts_falls_through():
    svc, report, _ = _ctx()
    result = svc.propose("哪些客戶快流失", report, None, contracts=None, executor=None)
    assert result.result_table is None
