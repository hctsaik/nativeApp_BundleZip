"""Round 084: KPI goal / pacing (progress toward a target)."""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_set_target, _extract_target_value,
)
from ai4bi.ui.components.kpi_card import _pacing_status
from ai4bi.report.models import apply_report_proposal
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


# ---- pacing helper ----------------------------------------------------------

def test_pacing_gte_behind():
    frac, cap, on_track = _pacing_status(60.0, 100.0, "gte")
    assert frac == pytest.approx(0.6)
    assert not on_track
    assert "還差" in cap


def test_pacing_gte_met_clamps_bar():
    frac, cap, on_track = _pacing_status(150.0, 100.0, "gte")
    assert frac == 1.0  # clamped for the bar
    assert on_track
    assert "達標" in cap


def test_pacing_lte_lower_is_better():
    # cost/return-rate: actual below target = on track
    frac, cap, on_track = _pacing_status(0.05, 0.06, "lte")
    assert on_track
    frac2, cap2, on2 = _pacing_status(0.08, 0.06, "lte")
    assert not on2


def test_pacing_zero_target_is_none():
    assert _pacing_status(10.0, 0.0, "gte") is None


# ---- NL parsing -------------------------------------------------------------

def test_detector_requires_set_verb_and_number():
    assert _looks_like_set_target("把營收目標設為 100 萬", "把營收目標設為 100 萬")
    assert _looks_like_set_target("set revenue target = 500000", "set revenue target = 500000")
    # a question about hitting target is NOT a set command
    assert not _looks_like_set_target("達標了嗎", "達標了嗎")
    # target word but no number
    assert not _looks_like_set_target("設定目標", "設定目標")


def test_extract_value_multipliers():
    assert _extract_target_value("目標設為 100 萬", "目標設為 100 萬") == 1_000_000
    assert _extract_target_value("target 500000", "target 500000") == 500000
    assert _extract_target_value("目標 1.5 億", "目標 1.5 億") == 150_000_000


# ---- end-to-end -------------------------------------------------------------

def _ctx():
    return (NL2ProposalService(), build_retail_demo_report(),
            {"retail_sales": build_retail_sales_block()})


def test_set_target_creates_proposal_on_orders_kpi():
    svc, report, contracts = _ctx()
    result = svc.propose("把訂單數目標設為 5000", report, "kpi_orders", contracts=contracts)
    assert result.proposal is not None, result.message
    ch = next(c for c in result.proposal.changes if c.path.endswith("/visualization/extra/target"))
    assert ch.after == 5000
    assert ch.affects_data is False  # display-only


def test_set_target_applies_and_persists():
    svc, report, contracts = _ctx()
    result = svc.propose("把訂單數目標設為 5000", report, "kpi_orders", contracts=contracts)
    applied = apply_report_proposal(report, result.proposal)
    kpi = applied.pages["main"].visuals["kpi_orders"]
    assert kpi.visualization.extra.get("target") == 5000
    # round-trips through serialization (extra is already serialized)
    from ai4bi.report.models import ExecutableReportSpec
    restored = ExecutableReportSpec.from_dict(applied.to_dict())
    assert restored.pages["main"].visuals["kpi_orders"].visualization.extra.get("target") == 5000
