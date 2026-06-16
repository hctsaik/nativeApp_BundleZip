"""Round 078: NL direct-answer engine — answer_metric intent.

The assistant must answer a metric *question* with a real, sourced number
(not a canvas edit). Imperative edit commands must be unaffected.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.report.proposals import prompt_to_proposal
from ai4bi.report.retail_template import build_retail_demo_report


def _sales_block() -> DataBlockContract:
    # 40 consecutive days ending today; revenue=100/day for first 20 days,
    # 200/day for last 20 → whole-period total = 20*100 + 20*200 = 6000.
    today = date.today()
    records = []
    for i in range(40):
        d = today - timedelta(days=39 - i)
        rev = 100.0 if i < 20 else 200.0
        records.append({"order_date": d.isoformat(), "revenue": rev, "order_count": 1})
    return DataBlockContract(
        block_id="mini_sales",
        block_type=BlockType.fact,
        grain="one row per day",
        version="1.0.0",
        description="mini sales",
        primary_keys=[],
        columns=[
            ColumnSchema(name="order_date", data_type="date"),
            ColumnSchema(name="revenue", data_type="float"),
            ColumnSchema(name="order_count", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum, unit="NT$"),
            MetricDefinition(name="order_count", formula="SUM(order_count)",
                             disaggregation_method=DisaggregationMethod.sum),
        ],
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


@pytest.fixture
def setup():
    block = _sales_block()
    contracts = {"mini_sales": block}
    executor = Executor(extra_contracts=contracts)
    report = build_retail_demo_report()
    return report, contracts, executor


def test_whole_period_total_answer(setup):
    report, contracts, executor = setup
    result = NL2ProposalService().propose(
        "總共營收多少？", report, None, contracts=contracts, executor=executor,
    )
    ans = result.direct_answer
    assert ans is not None
    assert ans.metric_name == "revenue"
    assert ans.period == "all"
    assert ans.value == pytest.approx(6000.0)
    assert "NT$6,000" in ans.sentence
    assert ans.trust_notes  # lineage present


def test_period_question_computes_delta(setup):
    report, contracts, executor = setup
    result = NL2ProposalService().propose(
        "最近30天營收多少？", report, None, contracts=contracts, executor=executor,
    )
    ans = result.direct_answer
    assert ans is not None
    assert ans.period == "month"
    # last 30 days vs prior 30 days — revenue ramps up, so delta is positive
    assert ans.value is not None
    if ans.delta_pct is not None:
        assert ans.delta_pct > 0


def test_english_question_resolves_metric(setup):
    report, contracts, executor = setup
    result = NL2ProposalService().propose(
        "how much revenue total?", report, None, contracts=contracts, executor=executor,
    )
    assert result.direct_answer is not None
    assert result.direct_answer.value == pytest.approx(6000.0)


def test_imperative_edit_is_not_answered(setup):
    report, contracts, executor = setup
    # An add-visual command has no question marker → must NOT become an answer.
    result = NL2ProposalService().propose(
        "加一張營收長條圖", report, None, contracts=contracts, executor=executor,
    )
    assert result.direct_answer is None


def test_no_executor_falls_through(setup):
    report, contracts, _ = setup
    # Without an executor we cannot compute — the answer engine must abstain.
    result = NL2ProposalService().propose(
        "總共營收多少？", report, None, contracts=contracts, executor=None,
    )
    assert result.direct_answer is None


def test_answer_offers_add_as_kpi_proposal(setup):
    report, contracts, executor = setup
    result = NL2ProposalService().propose(
        "營收總共多少？", report, None, contracts=contracts, executor=executor,
    )
    # The one-click "add as KPI" proposal accompanies the answer.
    assert result.proposal is not None
    assert any("add_visual" in c.path for c in result.proposal.changes)


def test_wrapper_returns_answer_intent(setup):
    report, contracts, executor = setup
    pr = prompt_to_proposal(
        "總共營收多少？", report, None, contracts=contracts, executor=executor,
    )
    assert pr.intent_kind == "answer"
    assert pr.direct_answer is not None
    assert pr.direct_answer.value == pytest.approx(6000.0)


def test_unresolvable_metric_question_falls_through(setup):
    report, contracts, executor = setup
    # Question marker present but no matching metric → fall through, no answer.
    result = NL2ProposalService().propose(
        "氣溫多少？", report, None, contracts=contracts, executor=executor,
    )
    assert result.direct_answer is None
