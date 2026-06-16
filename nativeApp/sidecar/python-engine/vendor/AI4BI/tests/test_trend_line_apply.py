"""Round 066: trend-line (and other presentation extras) apply cleanly.

Reproduces the user bug: "增加一個營收趨勢線" produced a proposal at path
.../visualization/extra/trend_line that the applier rejected as unsupported.
"""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.models import (
    _ALLOWLISTED_VISUAL_EXTRA_KEYS, apply_report_proposal,
)
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def test_trend_line_key_is_allowlisted():
    assert "trend_line" in _ALLOWLISTED_VISUAL_EXTRA_KEYS


def test_trend_line_proposal_generates_and_applies():
    svc = NL2ProposalService()
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}

    result = svc.propose("增加一個營收趨勢線", report, "line_revenue_trend",
                         semantic_model={}, contracts=contracts)
    assert result.proposal is not None, f"unsupported: {result.message}"
    # the proposal targets the trend_line extra path
    assert any(c.path.endswith("/visualization/extra/trend_line") for c in result.proposal.changes)

    # applying must NOT raise "Unsupported proposal path"
    updated = apply_report_proposal(report, result.proposal)
    viz = updated.pages["main"].visuals["line_revenue_trend"].visualization
    assert viz.extra.get("trend_line") is not None


def test_apply_rejects_non_allowlisted_extra_key():
    """Safety: a non-allowlisted extra key is still rejected."""
    from ai4bi.report.models import ReportProposal, ReportChange
    report = build_retail_demo_report()
    viz = report.pages["main"].visuals["line_revenue_trend"].visualization
    bad = ReportProposal(
        description="evil",
        changes=[ReportChange(
            path="pages/main/visuals/line_revenue_trend/visualization/extra/__danger__",
            label="x", before=viz.extra.get("__danger__"), after={"x": 1}, affects_data=False,
        )],
    )
    with pytest.raises(Exception):
        apply_report_proposal(report, bad)
