"""Tests for report title editing, created_at fix, and PublishedReportStore ANALYST_NAME — Round 016-B."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai4bi.report.models import (
    AuditMetadata,
    DraftReportStore,
    ExecutableReportSpec,
    PublishBlockedError,
    PublishedReportStore,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.proposals import build_title_proposal
from ai4bi.report.publication import GateCheckResult, PublicationGateResult
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_passing_gate() -> PublicationGateResult:
    return PublicationGateResult(
        can_publish=True,
        checks=[
            GateCheckResult(
                check_name="block_lifecycle",
                passed=True,
                message="All blocks certified.",
                blocking=True,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Test 1: build_title_proposal returns proposal with affects_data=False
# ---------------------------------------------------------------------------


def test_build_title_proposal_affects_data_false():
    """build_title_proposal() creates a proposal where affects_data is False."""
    proposal = build_title_proposal("Old Title", "New Title")
    assert proposal.affects_data is False


# ---------------------------------------------------------------------------
# Test 2: Applying title proposal updates report.title
# ---------------------------------------------------------------------------


def test_apply_title_proposal_updates_title():
    """Applying a title proposal via apply_report_proposal updates report.title."""
    report = build_semiconductor_queue_time_report()
    original_title = report.title
    new_title = "My Renamed Report"

    proposal = build_title_proposal(original_title, new_title)
    updated = apply_report_proposal(report, proposal)

    assert updated.title == new_title
    # Original report is unchanged (deep copy semantics)
    assert report.title == original_title


# ---------------------------------------------------------------------------
# Test 3: Applying title proposal with empty string raises ReportValidationError
# ---------------------------------------------------------------------------


def test_apply_title_proposal_empty_string_raises():
    """Applying a title proposal with an empty string raises ReportValidationError."""
    report = build_semiconductor_queue_time_report()
    proposal = build_title_proposal(report.title, "")
    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)


# ---------------------------------------------------------------------------
# Test 4: to_dict / from_dict preserves the new title
# ---------------------------------------------------------------------------


def test_title_roundtrip_via_serialization():
    """After renaming and serializing, from_dict() correctly restores the new title."""
    report = build_semiconductor_queue_time_report()
    new_title = "Serialization Roundtrip Title"
    proposal = build_title_proposal(report.title, new_title)
    updated = apply_report_proposal(report, proposal)

    as_dict = updated.to_dict()
    restored = ExecutableReportSpec.from_dict(as_dict)

    assert restored.title == new_title


# ---------------------------------------------------------------------------
# Test 5: DraftReportStore.save() sets created_at on first save
# ---------------------------------------------------------------------------


def test_draft_store_save_sets_created_at_on_first_save(tmp_path):
    """DraftReportStore.save() populates created_at when it is None."""
    store = DraftReportStore(tmp_path)
    report = build_semiconductor_queue_time_report()
    assert report.audit.created_at is None

    saved_path = store.save(report)
    loaded = store.load(saved_path)

    assert loaded.audit.created_at is not None


# ---------------------------------------------------------------------------
# Test 6: DraftReportStore.save() preserves created_at on second save
# ---------------------------------------------------------------------------


def test_draft_store_save_preserves_created_at_on_second_save(tmp_path):
    """DraftReportStore.save() does NOT overwrite created_at on subsequent saves."""
    store = DraftReportStore(tmp_path)
    report = build_semiconductor_queue_time_report()

    # First save
    path = store.save(report)
    loaded_once = store.load(path)
    first_created_at = loaded_once.audit.created_at
    assert first_created_at is not None

    # Second save using the loaded report (which already has created_at set)
    path2 = store.save(loaded_once)
    loaded_twice = store.load(path2)

    assert loaded_twice.audit.created_at == first_created_at


# ---------------------------------------------------------------------------
# Test 7: DraftReportStore.save() always updates last_modified_at
# ---------------------------------------------------------------------------


def test_draft_store_save_always_updates_last_modified_at(tmp_path):
    """DraftReportStore.save() always sets last_modified_at."""
    store = DraftReportStore(tmp_path)
    report = build_semiconductor_queue_time_report()

    path = store.save(report)
    loaded = store.load(path)

    assert loaded.audit.last_modified_at is not None


# ---------------------------------------------------------------------------
# Test 8: PublishedReportStore.publish() sets audit.last_modified_by from ANALYST_NAME
# ---------------------------------------------------------------------------


def test_published_store_sets_last_modified_by_from_env(tmp_path, monkeypatch):
    """PublishedReportStore.publish() reads ANALYST_NAME env var and stores it in audit."""
    monkeypatch.setenv("ANALYST_NAME", "alice")
    store = PublishedReportStore(tmp_path)
    report = build_semiconductor_queue_time_report()
    gate = _make_passing_gate()

    file_path, _ = store.publish(report, gate)

    import json
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["audit"]["last_modified_by"] == "alice"


# ---------------------------------------------------------------------------
# Bonus test: publish() with no ANALYST_NAME defaults to "unknown"
# ---------------------------------------------------------------------------


def test_published_store_sets_last_modified_by_unknown_when_no_env(tmp_path, monkeypatch):
    """PublishedReportStore.publish() defaults last_modified_by to 'unknown' when env not set."""
    monkeypatch.delenv("ANALYST_NAME", raising=False)
    store = PublishedReportStore(tmp_path)
    report = build_semiconductor_queue_time_report()
    gate = _make_passing_gate()

    file_path, _ = store.publish(report, gate)

    import json
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["audit"]["last_modified_by"] == "unknown"


# ---------------------------------------------------------------------------
# Bonus test: whitespace-only title raises ReportValidationError
# ---------------------------------------------------------------------------


def test_apply_title_proposal_whitespace_only_raises():
    """Applying a title proposal with a whitespace-only string raises ReportValidationError."""
    report = build_semiconductor_queue_time_report()
    proposal = build_title_proposal(report.title, "   ")
    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)
