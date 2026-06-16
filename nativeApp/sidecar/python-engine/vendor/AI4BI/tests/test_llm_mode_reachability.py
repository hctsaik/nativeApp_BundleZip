"""Round 095: the answer engine must stay reachable under LLM routing.

Regression guard for the round-6 finding: when LLM_MODE=anthropic, the model's
intent enum classified every metric question as 'unsupported', which returned a
refusal and never reached the keyword answer handlers — silently killing the
flagship feature. The fix: an LLM 'unsupported' (without a disambiguation) falls
through to the deterministic keyword router.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai4bi.ai import nl2proposal as N
from ai4bi.ai.llm_adapter import IntentClassification, SUPPORTED_INTENTS
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.retail_template import build_retail_demo_report


def _block():
    today = date.today()
    rows = [{"order_date": (today - timedelta(days=i)).isoformat(), "revenue": 100.0}
            for i in range(10)]
    return DataBlockContract(
        block_id="s", block_type=BlockType.fact, grain="day", version="1.0.0",
        description="s", primary_keys=[],
        columns=[ColumnSchema(name="order_date", data_type="date"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum, unit="NT$")],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _patch_llm(monkeypatch, **clf_kwargs):
    class _FakeAdapter:
        def classify(self, *a, **k):
            return IntentClassification(mode="llm", **clf_kwargs)
    monkeypatch.setattr(N, "LLMAdapter", _FakeAdapter)


def test_new_intents_registered():
    for i in ("answer_metric", "ranking", "grouped_topn", "segment_count",
              "explain_change", "pacing_question", "panel_analysis"):
        assert i in SUPPORTED_INTENTS


def test_answer_reachable_when_llm_returns_unsupported(monkeypatch):
    _patch_llm(monkeypatch, intent="unsupported")
    contracts = {"s": _block()}
    ex = Executor(extra_contracts=contracts)
    result = NL2ProposalService().propose(
        "總共營收多少？", build_retail_demo_report(), None, contracts=contracts, executor=ex)
    assert result.direct_answer is not None
    assert result.direct_answer.value is not None


def test_disambiguation_still_short_circuits(monkeypatch):
    _patch_llm(monkeypatch, intent="unsupported", disambiguation="你是指哪個指標？")
    contracts = {"s": _block()}
    ex = Executor(extra_contracts=contracts)
    result = NL2ProposalService().propose(
        "分析一下", build_retail_demo_report(), None, contracts=contracts, executor=ex)
    # a genuine clarifying question is preserved (not swallowed by fall-through)
    assert result.disambiguation == "你是指哪個指標？"


def test_panel_analysis_reachable_under_llm_unsupported(monkeypatch):
    _patch_llm(monkeypatch, intent="unsupported")
    # churn routes to RFM even when the LLM punts
    from ai4bi.report.retail_template import build_retail_sales_block
    contracts = {"retail_sales": build_retail_sales_block()}
    result = NL2ProposalService().propose(
        "哪些客戶快流失", build_retail_demo_report(), None, contracts=contracts, executor=None)
    assert result.result_table is not None
