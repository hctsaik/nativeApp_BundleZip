"""Round 088: target_good_if inference (honesty fix) + 'are we on track?' read-back."""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _infer_target_good_if, _looks_like_pacing_question,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.models import apply_report_proposal
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    contracts = {"retail_sales": build_retail_sales_block()}
    return (NL2ProposalService(), build_retail_demo_report(), contracts,
            Executor(extra_contracts=contracts))


# ---- honesty fix: good_if inference -----------------------------------------

def test_infer_good_if_from_rag():
    report = build_retail_demo_report()
    rr = report.pages["main"].visuals["kpi_return_rate"]   # has rag good_if=lte
    assert _infer_target_good_if(rr) == "lte"


def test_infer_good_if_revenue_is_gte():
    report = build_retail_demo_report()
    rev = report.pages["main"].visuals["kpi_revenue"]
    assert _infer_target_good_if(rev) == "gte"


def test_set_target_emits_good_if_for_lower_is_better():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("把平均退貨率目標設為 5", report, "kpi_return_rate", contracts=contracts)
    assert result.proposal is not None
    gi = next((c for c in result.proposal.changes
               if c.path.endswith("/extra/target_good_if")), None)
    assert gi is not None
    assert gi.after == "lte"


# ---- read-back question -----------------------------------------------------

def test_pacing_question_detector():
    assert _looks_like_pacing_question("達標了嗎", "達標了嗎")
    assert _looks_like_pacing_question("are we on track?", "are we on track?")
    assert not _looks_like_pacing_question("營收多少", "營收多少")


def test_pacing_readback_with_a_target_set():
    svc, report, contracts, ex = _ctx()
    # set a target on the orders KPI first
    setres = svc.propose("把訂單數目標設為 100", report, "kpi_orders", contracts=contracts)
    report2 = apply_report_proposal(report, setres.proposal)
    # now ask whether we're on track
    result = svc.propose("達標了嗎？", report2, None, contracts=contracts, executor=ex)
    assert result.direct_answer is not None
    assert "訂單" in result.message or "目標" in result.message or "達標" in result.message


def test_pacing_question_without_targets_guides_user():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("達標了嗎？", report, None, contracts=contracts, executor=ex)
    # no targets set anywhere → a guiding message, not a crash
    assert result.direct_answer is None
    assert "目標" in result.message


def test_pacing_question_without_executor_falls_through():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("達標了嗎？", report, None, contracts=contracts, executor=None)
    assert result.direct_answer is None
