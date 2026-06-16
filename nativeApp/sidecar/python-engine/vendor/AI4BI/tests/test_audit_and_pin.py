"""Tests for AuditMetadata dataclass and BlockRef pin workflow (Round 014-C)."""

from __future__ import annotations

import pytest

from ai4bi.report.models import (
    AuditMetadata,
    DraftReportStore,
    ExecutableReportSpec,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.proposals import pin_block_version_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Test 1: AuditMetadata defaults
# ---------------------------------------------------------------------------


def test_audit_metadata_defaults():
    """AuditMetadata defaults revision=0 and created_by='unknown'."""
    audit = AuditMetadata(report_id="test_report")
    assert audit.revision == 0
    assert audit.created_by == "unknown"
    assert audit.last_modified_by == "unknown"
    assert audit.created_at is None
    assert audit.last_modified_at is None


# ---------------------------------------------------------------------------
# Test 2: report_id property delegates to audit
# ---------------------------------------------------------------------------


def test_executable_report_spec_report_id_property():
    """ExecutableReportSpec.report_id property returns audit.report_id."""
    report = build_semiconductor_queue_time_report()
    assert report.report_id == report.audit.report_id
    assert report.report_id == "semiconductor_queue_time_v1"


# ---------------------------------------------------------------------------
# Test 3: revision property delegates to audit
# ---------------------------------------------------------------------------


def test_executable_report_spec_revision_property():
    """ExecutableReportSpec.revision property returns audit.revision."""
    report = build_semiconductor_queue_time_report()
    assert report.revision == report.audit.revision
    assert report.revision == 0


# ---------------------------------------------------------------------------
# Test 4: to_dict / from_dict round-trip preserves AuditMetadata fields
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_round_trip_preserves_audit():
    """to_dict() / from_dict() round-trip preserves all AuditMetadata fields."""
    report = build_semiconductor_queue_time_report()
    # Set some non-default audit fields
    report.audit.created_by = "alice"
    report.audit.created_at = "2026-01-01T00:00:00+00:00"
    report.audit.last_modified_by = "bob"
    report.audit.last_modified_at = "2026-05-28T12:00:00+00:00"
    report.audit.revision = 3

    data = report.to_dict()
    assert "audit" in data
    assert "report_id" not in data  # top-level report_id removed

    restored = ExecutableReportSpec.from_dict(data)
    assert restored.audit.report_id == report.audit.report_id
    assert restored.audit.created_by == "alice"
    assert restored.audit.created_at == "2026-01-01T00:00:00+00:00"
    assert restored.audit.last_modified_by == "bob"
    assert restored.audit.last_modified_at == "2026-05-28T12:00:00+00:00"
    assert restored.audit.revision == 3


# ---------------------------------------------------------------------------
# Test 5: from_dict backward compat — old dict with top-level report_id/revision
# ---------------------------------------------------------------------------


def test_from_dict_backward_compat_old_format():
    """from_dict() backward-compat: old dict with top-level report_id and revision (no audit key)."""
    report = build_semiconductor_queue_time_report()
    data = report.to_dict()

    # Simulate old format: remove audit, inject top-level fields
    audit_data = data.pop("audit")
    data["report_id"] = audit_data["report_id"]
    data["revision"] = 5

    restored = ExecutableReportSpec.from_dict(data)
    assert restored.audit.report_id == audit_data["report_id"]
    assert restored.audit.revision == 5
    assert restored.report_id == audit_data["report_id"]
    assert restored.revision == 5


# ---------------------------------------------------------------------------
# Test 6: DraftReportStore.save() sets audit.last_modified_at
# ---------------------------------------------------------------------------


def test_draft_report_store_save_sets_last_modified_at(tmp_path):
    """DraftReportStore.save() sets audit.last_modified_at on save."""
    report = build_semiconductor_queue_time_report()
    assert report.audit.last_modified_at is None

    store = DraftReportStore(tmp_path)
    path = store.save(report)

    restored = store.load(path)
    assert restored.audit.last_modified_at is not None
    # Should be a valid ISO-8601 string
    assert "T" in restored.audit.last_modified_at


# ---------------------------------------------------------------------------
# Test 7: pin_block_version_proposal returns a proposal with affects_data=False
# ---------------------------------------------------------------------------


def test_pin_block_version_proposal_affects_data_false():
    """pin_block_version_proposal() returns a proposal with affects_data=False."""
    report = build_semiconductor_queue_time_report()
    proposal = pin_block_version_proposal(
        report,
        page_id="main",
        visual_id="kpi_move_count",
        block_id="process_move_fact",
        certified_version="1.2.0",
    )
    assert proposal.affects_data is False
    assert len(proposal.changes) == 1
    assert proposal.changes[0].after == "1.2.0"


# ---------------------------------------------------------------------------
# Test 8: Applying the pin proposal updates the matching BlockRef.pinned_version
# ---------------------------------------------------------------------------


def test_apply_pin_proposal_updates_block_ref_pinned_version():
    """Applying the pin proposal updates the matching BlockRef.pinned_version."""
    report = build_semiconductor_queue_time_report()
    # Verify initially unpinned
    move_ref = report.pages["main"].visuals["kpi_move_count"].query.block_refs[0]
    assert move_ref.pinned_version is None

    proposal = pin_block_version_proposal(
        report,
        page_id="main",
        visual_id="kpi_move_count",
        block_id="process_move_fact",
        certified_version="2.0.1",
    )
    updated = apply_report_proposal(report, proposal)

    updated_ref = updated.pages["main"].visuals["kpi_move_count"].query.block_refs[0]
    assert updated_ref.pinned_version == "2.0.1"


# ---------------------------------------------------------------------------
# Test 9: Pin proposal for non-existent block_id raises ReportValidationError
# ---------------------------------------------------------------------------


def test_pin_proposal_nonexistent_block_id_raises():
    """Pin proposal for a non-existent block_id raises ReportValidationError."""
    report = build_semiconductor_queue_time_report()
    with pytest.raises(ReportValidationError):
        pin_block_version_proposal(
            report,
            page_id="main",
            visual_id="kpi_move_count",
            block_id="nonexistent_block",
            certified_version="1.0.0",
        )
