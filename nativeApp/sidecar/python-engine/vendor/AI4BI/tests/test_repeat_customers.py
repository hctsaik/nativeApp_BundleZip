"""Round 098: repeat vs one-time customer counts."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _detect_panel_analysis
from ai4bi.analysis.segments import repeat_vs_onetime
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _df():
    # A,B repeat (2 distinct days each); C,D,E one-time.
    rows = [
        {"customer_id": "A", "order_date": "2026-05-01"},
        {"customer_id": "A", "order_date": "2026-05-08"},
        {"customer_id": "B", "order_date": "2026-05-02"},
        {"customer_id": "B", "order_date": "2026-05-09"},
        {"customer_id": "C", "order_date": "2026-05-03"},
        {"customer_id": "D", "order_date": "2026-05-04"},
        {"customer_id": "E", "order_date": "2026-05-05"},
    ]
    return pd.DataFrame(rows)


def test_counts_and_percentages():
    out = repeat_vs_onetime(_df(), "customer_id", "order_date")
    counts = dict(zip(out["客戶類型"], out["人數"]))
    repeat = next(v for k, v in counts.items() if k.startswith("回頭"))
    onetime = next(v for k, v in counts.items() if "一次" in k)
    assert repeat == 2 and onetime == 3
    # 2 of 5 = 40%
    rep_pct = out[out["客戶類型"].str.startswith("回頭")]["佔比%"].iloc[0]
    assert rep_pct == 40.0


def test_same_day_multiple_rows_is_one_occasion():
    df = pd.DataFrame([
        {"customer_id": "X", "order_date": "2026-05-01"},
        {"customer_id": "X", "order_date": "2026-05-01"},  # same day → still one-time
    ])
    out = repeat_vs_onetime(df, "customer_id", "order_date")
    onetime = out[out["客戶類型"].str.contains("一次")]["人數"].iloc[0]
    assert onetime == 1


def test_missing_columns_empty():
    assert repeat_vs_onetime(_df(), "nope", "order_date").empty


def test_nl_detects_and_routes_repeat():
    assert _detect_panel_analysis("回頭客佔比多少", "回頭客佔比多少") == "repeat"
    svc = NL2ProposalService()
    contracts = {"orders": DataBlockContract(
        block_id="orders", block_type=BlockType.fact, grain="line", version="1.0.0",
        description="o", primary_keys=[],
        columns=[ColumnSchema(name="customer_id", data_type="string"),
                 ColumnSchema(name="order_date", data_type="date"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum)],
        data_source=InlineDataSource(records=[
            {"customer_id": "A", "order_date": "2026-05-01", "revenue": 1.0},
            {"customer_id": "A", "order_date": "2026-05-08", "revenue": 1.0},
            {"customer_id": "B", "order_date": "2026-05-02", "revenue": 1.0},
        ]),
        policy=PolicySpec(data_classification=DataClassification.internal))}
    result = svc.propose("回頭客還是一次性客比較多？", build_retail_demo_report(), None,
                         contracts=contracts, executor=None)
    assert result.result_table is not None
    assert "客戶類型" in result.result_table.columns
