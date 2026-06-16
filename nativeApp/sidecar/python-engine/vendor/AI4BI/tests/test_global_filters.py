"""Tests for cross-page global filter sync (Round 016-A)."""

from __future__ import annotations

import pytest

from ai4bi.report.builder import build_global_filter_proposal
from ai4bi.report.models import (
    ReportChange,
    ReportProposal,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report():
    return build_semiconductor_queue_time_report()


# ---------------------------------------------------------------------------
# Test 1 — global_filters defaults to {}
# ---------------------------------------------------------------------------

def test_global_filters_defaults_to_empty_dict():
    report = _report()
    assert report.global_filters == {}


# ---------------------------------------------------------------------------
# Test 2 — set_global_filter adds and removes keys correctly
# ---------------------------------------------------------------------------

def test_set_global_filter_adds_key():
    report = _report()
    report.set_global_filter("process_move_fact.product_family", ["Logic-A"])
    assert report.global_filters == {"process_move_fact.product_family": ["Logic-A"]}


def test_set_global_filter_removes_key_on_empty_list():
    report = _report()
    report.set_global_filter("process_move_fact.product_family", ["Logic-A"])
    report.set_global_filter("process_move_fact.product_family", [])
    assert "process_move_fact.product_family" not in report.global_filters


def test_set_global_filter_no_error_removing_absent_key():
    report = _report()
    # Should not raise even if key was never set
    report.set_global_filter("nonexistent.key", [])
    assert report.global_filters == {}


# ---------------------------------------------------------------------------
# Test 3 — merged_filters() returns active_filters() when global_filters empty
# ---------------------------------------------------------------------------

def test_merged_filters_equals_active_filters_when_no_global():
    report = _report()
    assert report.merged_filters() == report.active_filters()


# ---------------------------------------------------------------------------
# Test 4 — merged_filters() merges and global_filters wins on conflict
# ---------------------------------------------------------------------------

def test_merged_filters_global_wins_on_conflict():
    report = _report()
    # The demo report has active_filters driven by controls.
    # Identify one filter key from active_filters.
    active = report.active_filters()
    if not active:
        pytest.skip("No active filters in demo report to test conflict.")
    conflict_key = next(iter(active))
    original_value = active[conflict_key]

    # Override with a different value via global_filters
    override_value = ["OVERRIDE"]
    report.set_global_filter(conflict_key, override_value)

    merged = report.merged_filters()
    assert merged[conflict_key] == override_value
    # Also confirm original active_filters still unchanged
    assert report.active_filters()[conflict_key] == original_value


def test_merged_filters_includes_non_conflicting_global():
    report = _report()
    report.set_global_filter("some_block.some_col", ["v1", "v2"])
    merged = report.merged_filters()
    assert merged["some_block.some_col"] == ["v1", "v2"]
    # active_filters content is also preserved
    for key, val in report.active_filters().items():
        if key != "some_block.some_col":
            assert merged[key] == val


# ---------------------------------------------------------------------------
# Test 5 — to_dict() / from_dict() round-trip preserves global_filters
# ---------------------------------------------------------------------------

def test_to_dict_from_dict_roundtrip_preserves_global_filters():
    report = _report()
    report.set_global_filter("process_move_fact.product_family", ["Logic-A"])
    report.set_global_filter("tool_dim.vendor", ["ASML"])

    restored = type(report).from_dict(report.to_dict())
    assert restored.global_filters == {
        "process_move_fact.product_family": ["Logic-A"],
        "tool_dim.vendor": ["ASML"],
    }


def test_to_dict_global_filters_key_present_even_when_empty():
    report = _report()
    d = report.to_dict()
    assert "global_filters" in d
    assert d["global_filters"] == {}


def test_from_dict_missing_global_filters_key_defaults_to_empty():
    """Old serialized reports without global_filters key should load fine."""
    report = _report()
    d = report.to_dict()
    del d["global_filters"]
    restored = type(report).from_dict(d)
    assert restored.global_filters == {}


# ---------------------------------------------------------------------------
# Test 6 — build_global_filter_proposal() returns proposal with affects_data=True
# ---------------------------------------------------------------------------

def test_build_global_filter_proposal_affects_data_true():
    proposal = build_global_filter_proposal(
        filter_key="process_move_fact.product_family",
        before_values=[],
        after_values=["Logic-A"],
    )
    assert isinstance(proposal, ReportProposal)
    assert proposal.affects_data is True
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.path == "global_filters/process_move_fact.product_family"
    assert change.affects_data is True


# ---------------------------------------------------------------------------
# Test 7 — Applying a global filter proposal via apply_report_proposal() updates global_filters
# ---------------------------------------------------------------------------

def test_apply_global_filter_proposal_updates_global_filters():
    report = _report()
    proposal = ReportProposal(
        description="Set global filter",
        changes=[
            ReportChange(
                path="global_filters/process_move_fact.product_family",
                label="Product family global filter",
                before=None,
                after=["Logic-A"],
                affects_data=True,
            )
        ],
    )
    updated = apply_report_proposal(report, proposal)
    assert updated.global_filters.get("process_move_fact.product_family") == ["Logic-A"]
    # Original report unchanged
    assert report.global_filters == {}


def test_apply_global_filter_proposal_removes_key_when_after_is_none():
    report = _report()
    report.set_global_filter("process_move_fact.product_family", ["Logic-A"])

    proposal = ReportProposal(
        description="Remove global filter",
        changes=[
            ReportChange(
                path="global_filters/process_move_fact.product_family",
                label="Remove product family global filter",
                before=["Logic-A"],
                after=None,
                affects_data=True,
            )
        ],
    )
    updated = apply_report_proposal(report, proposal)
    assert "process_move_fact.product_family" not in updated.global_filters


# ---------------------------------------------------------------------------
# Test 8 — Stale proposal atomicity: global filter change + invalid path rejects completely
# ---------------------------------------------------------------------------

def test_stale_proposal_with_global_filter_rejects_atomically():
    """A multi-change proposal is rejected if ANY change is stale."""
    report = _report()

    # First change: stale global filter (before value doesn't match)
    proposal = ReportProposal(
        description="Stale multi-change proposal",
        changes=[
            ReportChange(
                path="global_filters/process_move_fact.product_family",
                label="Product family",
                before=["WRONG_BEFORE"],   # stale — actual before is None
                after=["Logic-A"],
                affects_data=True,
            ),
        ],
    )
    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)
    # Report must be unmodified
    assert report.global_filters == {}


def test_stale_second_change_rejects_entire_proposal():
    """If second change is stale, entire proposal rejected and first change not applied."""
    report = _report()

    proposal = ReportProposal(
        description="Mixed valid + stale changes",
        changes=[
            ReportChange(
                path="global_filters/process_move_fact.product_family",
                label="Product family",
                before=None,
                after=["Logic-A"],
                affects_data=True,
            ),
            ReportChange(
                path="global_filters/tool_dim.vendor",
                label="Vendor filter",
                before=["WRONG_BEFORE"],   # stale
                after=["ASML"],
                affects_data=True,
            ),
        ],
    )
    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)
    # Original report must be completely unchanged
    assert report.global_filters == {}
