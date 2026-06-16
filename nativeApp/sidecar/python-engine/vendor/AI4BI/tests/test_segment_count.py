"""Round 091: cold-start grouped measure filter ('buyers with > N orders')."""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_segment_count
from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _block() -> DataBlockContract:
    # A=5 orders, B=2, C=4 (one row each, order_count=1).
    rows = []
    for cust, k in [("A", 5), ("B", 2), ("C", 4)]:
        for i in range(k):
            rows.append({"customer_id": cust, "order_date": f"2026-05-{i+1:02d}",
                         "order_count": 1, "revenue": 100.0})
    return DataBlockContract(
        block_id="orders", block_type=BlockType.fact, grain="order line",
        version="1.0.0", description="orders", primary_keys=[],
        columns=[
            ColumnSchema(name="customer_id", data_type="string"),
            ColumnSchema(name="order_date", data_type="date"),
            ColumnSchema(name="order_count", data_type="integer"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[
            MetricDefinition(name="order_count", formula="SUM(order_count)",
                             disaggregation_method=DisaggregationMethod.sum),
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum, unit="NT$"),
        ],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _ctx():
    contracts = {"orders": _block()}
    return (NL2ProposalService(), build_retail_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_detector():
    assert _looks_like_segment_count("買超過 3 次的客戶", "買超過 3 次的客戶")
    assert _looks_like_segment_count("customers who bought more than 3 times",
                                     "customers who bought more than 3 times")
    # no entity cue
    assert not _looks_like_segment_count("營收超過 100 的地區", "營收超過 100 的地區")
    # no comparison
    assert not _looks_like_segment_count("有幾個客戶", "有幾個客戶")


def test_buyers_more_than_three_times():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("買超過 3 次的客戶", report, None, contracts=contracts, executor=ex)
    df = result.result_table
    assert df is not None, result.message
    assert set(df["customer_id"]) == {"A", "C"}  # B (2) excluded


def test_english_phrasing():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("customers who bought more than 3 times", report, None,
                         contracts=contracts, executor=ex)
    assert result.result_table is not None
    assert set(result.result_table["customer_id"]) == {"A", "C"}


def test_below_threshold():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("下單少於 3 次的客戶", report, None, contracts=contracts, executor=ex)
    # B has 2 (< 3); A and C excluded
    assert result.result_table is not None
    assert set(result.result_table["customer_id"]) == {"B"}


def test_no_executor_falls_through():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("買超過 3 次的客戶", report, None, contracts=contracts, executor=None)
    assert result.result_table is None
