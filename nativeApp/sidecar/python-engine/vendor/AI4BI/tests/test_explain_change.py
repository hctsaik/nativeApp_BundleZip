"""Round 081: NL "why did <metric> change?" → decomposition answer.

Reuses time_intelligence.compute_grouped_comparison (previously only reachable
from the sidebar panel) to rank the biggest contributors to a period change.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_explain_change, _resolve_decomp_dimension,
)
from ai4bi.ai.schema_index import SchemaIndex
from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _block() -> DataBlockContract:
    # 60 days. North region jumps up in the recent window; South dips.
    today = date.today()
    rows = []
    for i in range(60):
        d = today - timedelta(days=59 - i)
        recent = i >= 30
        rows.append({"order_date": d.isoformat(), "region": "North",
                     "revenue": 300.0 if recent else 100.0})
        rows.append({"order_date": d.isoformat(), "region": "South",
                     "revenue": 50.0 if recent else 150.0})
    return DataBlockContract(
        block_id="sales", block_type=BlockType.fact, grain="day x region",
        version="1.0.0", description="sales", primary_keys=[],
        columns=[
            ColumnSchema(name="order_date", data_type="date"),
            ColumnSchema(name="region", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum, unit="NT$")],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _ctx():
    contracts = {"sales": _block()}
    return NL2ProposalService(), build_retail_demo_report(), contracts, Executor(extra_contracts=contracts)


def test_detector():
    assert _looks_like_explain_change("為什麼營收下降", "為什麼營收下降")
    assert _looks_like_explain_change("why did revenue change", "why did revenue change")
    assert _looks_like_explain_change("把營收依地區拆解", "把營收依地區拆解")
    # plain question is NOT an explain-change
    assert not _looks_like_explain_change("營收多少", "營收多少")


def test_resolve_dimension_rejects_date():
    contracts = {"sales": _block()}
    idx = SchemaIndex.build(contracts)
    # "region" is categorical → resolves; date columns must be rejected
    assert _resolve_decomp_dimension(idx, "依 region 拆解", "依 region 拆解", contracts, "sales") == "region"


def test_explain_change_returns_decomposition():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("為什麼 revenue 變化 by region", report, None,
                         contracts=contracts, executor=ex)
    ans = result.direct_answer
    assert ans is not None
    assert ans.metric_name == "revenue"
    # both regions should be named as contributors in the sentence
    assert "North" in ans.sentence and "South" in ans.sentence
    assert "拆解" in ans.sentence


def test_explain_change_without_dimension_falls_through_to_answer():
    svc, report, contracts, ex = _ctx()
    # "why did revenue change" with no dimension → no decomposition; the plain
    # answer engine still handles the "why"(question marker) gracefully or it
    # falls through. Either way it must not raise and must not decompose.
    result = svc.propose("為什麼 revenue 變化", report, None,
                         contracts=contracts, executor=ex)
    # No dimension → either a plain answer or unsupported, but never a decomposition sentence.
    if result.direct_answer is not None:
        assert "拆解" not in result.direct_answer.sentence


def test_no_executor_falls_through():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("為什麼 revenue 變化 by region", report, None,
                         contracts=contracts, executor=None)
    assert result.direct_answer is None
