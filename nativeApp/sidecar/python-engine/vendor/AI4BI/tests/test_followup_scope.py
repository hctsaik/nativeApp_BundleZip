"""Round 136: conversational follow-up scope inheritance ("只看 ETCH").

A short refinement after a breakdown should inherit the prior turn's metric +
dimension and narrow to one value, instead of being treated as an island.
"""

from __future__ import annotations

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_followup_scope, _extract_followup_value,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _ctx():
    contracts = fab_contracts()
    return (NL2ProposalService(), build_fab_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_detector_and_value_extraction():
    assert _looks_like_followup_scope("只看 ETCH 呢？", "只看 etch 呢？")
    assert _looks_like_followup_scope("那 PHOTO 呢", "那 photo 呢")
    assert not _looks_like_followup_scope(
        "各區的平均 queue time 是多少？", "各區的平均 queue time 是多少？")
    assert _extract_followup_value("只看 ETCH 呢？").upper() == "ETCH"


def test_followup_inherits_breakdown_scope():
    svc, report, contracts, ex = _ctx()
    convo: dict = {}
    # turn 1: breakdown of queue time by area
    r1 = svc.propose("各區的平均 queue time 是多少？", report, None,
                     contracts=contracts, executor=ex, conversation_state=convo)
    assert r1.result_table is not None and "area" in r1.result_table.columns
    assert convo.get("last", {}).get("dim_col") == "area"
    # turn 2: follow-up narrows to ETCH, inheriting metric + dimension
    r2 = svc.propose("只看 ETCH 呢？", report, None,
                     contracts=contracts, executor=ex, conversation_state=convo)
    df = r2.result_table
    assert df is not None and len(df) == 1
    assert str(df.iloc[0]["area"]) == "ETCH"
    assert "延續上一題" in r2.message


def test_followup_without_prior_context_is_not_hijacked():
    svc, report, contracts, ex = _ctx()
    # no prior turn → follow-up must NOT fabricate an answer from empty memory
    r = svc.propose("只看 ETCH 呢？", report, None,
                    contracts=contracts, executor=ex, conversation_state={})
    # falls through to normal routing (unsupported / value-filter guidance), never a
    # spurious "延續上一題" answer
    assert "延續上一題" not in (r.message or "")
