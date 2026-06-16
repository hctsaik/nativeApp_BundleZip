"""
Round 020 — Date Filter NL2 Intent tests.

Validates date_filter_change intent:
  - Relative period detection (last_3m, last_quarter, ytd, last_6m, last_month)
  - global_filters/date_range path
  - affects_data = True
  - risk_level = low
  - Clear date filter works
  - No-op when already set to same value
  - Proposal round-trip via apply_report_proposal
"""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.models import apply_report_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report


@pytest.fixture
def service() -> NL2ProposalService:
    return NL2ProposalService()


@pytest.fixture
def report():
    return build_semiconductor_queue_time_report()


# ---------------------------------------------------------------------------
# Period detection tests
# ---------------------------------------------------------------------------

class TestDateFilterDetection:

    @pytest.mark.parametrize("prompt,expected_period", [
        ("最近3個月", "last_3m"),
        ("最近三個月", "last_3m"),
        ("last 3 months", "last_3m"),
        ("past 3 months", "last_3m"),
        ("last quarter", "last_quarter"),
        ("上季", "last_quarter"),
        ("上一季", "last_quarter"),
        ("今年", "ytd"),
        ("ytd", "ytd"),
        ("year to date", "ytd"),
        ("this year", "ytd"),
        ("本年度", "ytd"),
        ("最近6個月", "last_6m"),
        ("最近半年", "last_6m"),
        ("last 6 months", "last_6m"),
        ("上個月", "last_month"),
        ("last month", "last_month"),
    ])
    def test_period_detected(self, service, report, prompt, expected_period):
        result = service.propose(prompt, report, None)
        assert result.proposal is not None, f"No proposal for prompt: {prompt!r}"
        change = result.proposal.changes[0]
        assert change.after is not None
        assert change.after["period"] == expected_period, (
            f"Expected period {expected_period!r} for {prompt!r}, "
            f"got {change.after!r}"
        )

    def test_clear_date_filter_when_set(self, service, report):
        """Clear after setting — should produce a proposal."""
        from ai4bi.report.models import apply_report_proposal
        r1 = service.propose("今年", report, None)
        updated = apply_report_proposal(report, r1.proposal)
        # Now clear
        r2 = service.propose("清除日期", updated, None)
        assert r2.proposal is not None
        assert r2.proposal.changes[0].after is None

    def test_clear_date_filter_noop_on_fresh(self, service, report):
        """Clear on a report with no date filter is a no-op (no proposal)."""
        result = service.propose("清除日期", report, None)
        # Fresh report has no date filter → clear is no-op
        assert result.proposal is None
        assert "已經是" in result.message  # Round 184: message is now 繁中

    def test_clear_date_filter_english(self, service, report):
        """clear date filter on a fresh report → no-op."""
        result = service.propose("clear date filter", report, None)
        assert result.proposal is None  # no filter to clear


# ---------------------------------------------------------------------------
# Proposal structure tests
# ---------------------------------------------------------------------------

class TestDateFilterProposal:

    def test_path_is_global_filter_date_range(self, service, report):
        result = service.propose("最近3個月", report, None)
        assert result.proposal is not None
        assert result.proposal.changes[0].path == "global_filters/date_range"

    def test_affects_data_true(self, service, report):
        result = service.propose("今年", report, None)
        assert result.proposal is not None
        assert result.proposal.changes[0].affects_data is True

    def test_risk_level_low(self, service, report):
        result = service.propose("last quarter", report, None)
        assert result.risk_level == "low"

    def test_anchor_is_relative(self, service, report):
        result = service.propose("最近3個月", report, None)
        assert result.proposal is not None
        after = result.proposal.changes[0].after
        assert after["anchor"] == "relative"

    def test_before_is_none_on_fresh_report(self, service, report):
        result = service.propose("today year ytd", report, None)
        assert result.proposal is not None
        assert result.proposal.changes[0].before is None

    def test_before_reflects_existing_filter(self, service, report):
        # First apply a date filter
        r1 = service.propose("今年", report, None)
        updated = apply_report_proposal(report, r1.proposal)
        # Then propose a different one
        r2 = service.propose("last quarter", updated, None)
        assert r2.proposal is not None
        before = r2.proposal.changes[0].before
        assert before is not None
        assert before["period"] == "ytd"

    def test_no_proposal_when_already_set(self, service, report):
        """If date filter is already set to the requested period, no proposal."""
        r1 = service.propose("今年", report, None)
        updated = apply_report_proposal(report, r1.proposal)
        r2 = service.propose("ytd", updated, None)
        # Already ytd → no proposal, just a message
        assert r2.proposal is None
        assert "已經是" in r2.message  # Round 184: message is now 繁中

    def test_intent_kind_analysis_request(self, service, report):
        result = service.propose("最近3個月", report, None)
        assert result.intent.intent_kind == "analysis_request"


# ---------------------------------------------------------------------------
# Round-trip tests via apply_report_proposal
# ---------------------------------------------------------------------------

class TestDateFilterRoundTrip:

    def test_apply_sets_global_filter(self, service, report):
        result = service.propose("最近3個月", report, None)
        assert result.proposal is not None
        updated = apply_report_proposal(report, result.proposal)
        dr = updated.global_filters.get("date_range")
        assert dr is not None
        assert dr["period"] == "last_3m"

    def test_apply_then_clear(self, service, report):
        # Set
        r1 = service.propose("今年", report, None)
        after_set = apply_report_proposal(report, r1.proposal)
        assert after_set.global_filters.get("date_range") is not None
        # Clear
        r2 = service.propose("清除日期", after_set, None)
        assert r2.proposal is not None
        after_clear = apply_report_proposal(after_set, r2.proposal)
        assert after_clear.global_filters.get("date_range") is None

    def test_apply_updates_revision(self, service, report):
        r1 = service.propose("last quarter", report, None)
        updated = apply_report_proposal(report, r1.proposal)
        assert updated.revision == report.revision + 1


# ---------------------------------------------------------------------------
# Does not interfere with other intents
# ---------------------------------------------------------------------------

class TestDateFilterIsolation:

    def test_color_prompt_not_confused_with_date(self, service, report):
        """'Make this line red' must not trigger date filter."""
        result = service.propose("make this line red", report, "line_queue_by_day")
        # Should be style change, not date filter
        if result.proposal:
            change = result.proposal.changes[0]
            assert "date_range" not in change.path

    def test_sql_refusal_not_confused_with_date(self, service, report):
        result = service.propose("SELECT * FROM fact JOIN dim", report, None)
        assert result.refusal is not None
        assert result.proposal is None
