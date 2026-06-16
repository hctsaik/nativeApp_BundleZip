"""
Round 015-B: Tests for unpin_block_version_proposal and full pin/unpin workflow.
Model-layer only — no Streamlit AppTest required.
"""

from __future__ import annotations

import pytest

from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.proposals import pin_block_version_proposal, unpin_block_version_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_block_ref(report: ExecutableReportSpec, visual_id: str, block_id: str):
    """Return the BlockRef for block_id in the given visual."""
    return next(
        ref
        for ref in report.pages["main"].visuals[visual_id].query.block_refs
        if ref.block_id == block_id
    )


# ---------------------------------------------------------------------------
# Test 1: unpin_block_version_proposal returns affects_data=False
# ---------------------------------------------------------------------------

def test_unpin_proposal_affects_data_false():
    """unpin_block_version_proposal() returns a proposal with affects_data=False."""
    report = build_semiconductor_queue_time_report()
    # First pin so we have something to unpin
    pin_proposal = pin_block_version_proposal(
        report, "main", "kpi_move_count", "process_move_fact", "1.0.0"
    )
    pinned_report = apply_report_proposal(report, pin_proposal)

    unpin_proposal = unpin_block_version_proposal(
        pinned_report, "main", "kpi_move_count", "process_move_fact"
    )
    assert unpin_proposal.affects_data is False
    assert len(unpin_proposal.changes) == 1


# ---------------------------------------------------------------------------
# Test 2: Applying unpin proposal sets pinned_version=None
# ---------------------------------------------------------------------------

def test_apply_unpin_proposal_clears_pinned_version():
    """Applying unpin proposal sets pinned_version=None on the matching BlockRef."""
    report = build_semiconductor_queue_time_report()
    pin_proposal = pin_block_version_proposal(
        report, "main", "kpi_move_count", "process_move_fact", "2.0.0"
    )
    pinned_report = apply_report_proposal(report, pin_proposal)
    ref = _get_block_ref(pinned_report, "kpi_move_count", "process_move_fact")
    assert ref.pinned_version == "2.0.0"

    unpin_proposal = unpin_block_version_proposal(
        pinned_report, "main", "kpi_move_count", "process_move_fact"
    )
    unpinned_report = apply_report_proposal(pinned_report, unpin_proposal)
    ref_after = _get_block_ref(unpinned_report, "kpi_move_count", "process_move_fact")
    assert ref_after.pinned_version is None
    assert ref_after.pin_reason is None


# ---------------------------------------------------------------------------
# Test 3: Applying unpin on an already-unpinned BlockRef is idempotent
# ---------------------------------------------------------------------------

def test_apply_unpin_on_already_unpinned_is_idempotent():
    """Applying unpin on an already-unpinned BlockRef raises no error and leaves state unchanged."""
    report = build_semiconductor_queue_time_report()
    ref = _get_block_ref(report, "kpi_move_count", "process_move_fact")
    assert ref.pinned_version is None

    unpin_proposal = unpin_block_version_proposal(
        report, "main", "kpi_move_count", "process_move_fact"
    )
    # Proposal change: before=None, after=None — applying should succeed without error
    result_report = apply_report_proposal(report, unpin_proposal)
    ref_after = _get_block_ref(result_report, "kpi_move_count", "process_move_fact")
    assert ref_after.pinned_version is None
    assert ref_after.pin_reason is None


# ---------------------------------------------------------------------------
# Test 4: pin_block_version_proposal for unknown block_id raises ReportValidationError
# ---------------------------------------------------------------------------

def test_pin_proposal_unknown_block_id_raises():
    """pin_block_version_proposal() for an unknown block_id raises ReportValidationError."""
    report = build_semiconductor_queue_time_report()
    with pytest.raises(ReportValidationError):
        pin_block_version_proposal(
            report, "main", "kpi_move_count", "unknown_block_xyz", "1.0.0"
        )


# ---------------------------------------------------------------------------
# Test 5: unpin_block_version_proposal for unknown block_id raises ReportValidationError
# ---------------------------------------------------------------------------

def test_unpin_proposal_unknown_block_id_raises():
    """unpin_block_version_proposal() for an unknown block_id raises ReportValidationError."""
    report = build_semiconductor_queue_time_report()
    with pytest.raises(ReportValidationError):
        unpin_block_version_proposal(
            report, "main", "kpi_move_count", "unknown_block_xyz"
        )


# ---------------------------------------------------------------------------
# Test 6: Pin then unpin round-trip returns BlockRef to original unpinned state
# ---------------------------------------------------------------------------

def test_pin_then_unpin_round_trip():
    """Pin then unpin round-trip returns BlockRef to original unpinned state."""
    report = build_semiconductor_queue_time_report()
    original_ref = _get_block_ref(report, "kpi_move_count", "process_move_fact")
    assert original_ref.pinned_version is None
    assert original_ref.pin_reason is None

    # Pin
    pin_proposal = pin_block_version_proposal(
        report, "main", "kpi_move_count", "process_move_fact", "3.0.0"
    )
    pinned_report = apply_report_proposal(report, pin_proposal)
    pinned_ref = _get_block_ref(pinned_report, "kpi_move_count", "process_move_fact")
    assert pinned_ref.pinned_version == "3.0.0"

    # Unpin
    unpin_proposal = unpin_block_version_proposal(
        pinned_report, "main", "kpi_move_count", "process_move_fact"
    )
    final_report = apply_report_proposal(pinned_report, unpin_proposal)
    final_ref = _get_block_ref(final_report, "kpi_move_count", "process_move_fact")

    assert final_ref.pinned_version is None
    assert final_ref.pin_reason is None


# ---------------------------------------------------------------------------
# Test 7: Pin + apply + to_dict/from_dict preserves pinned_version across serialization
# ---------------------------------------------------------------------------

def test_pin_survives_serialization_round_trip():
    """Pin + apply + to_dict/from_dict preserves pinned_version across serialization."""
    report = build_semiconductor_queue_time_report()
    pin_proposal = pin_block_version_proposal(
        report, "main", "kpi_move_count", "process_move_fact", "1.2.3"
    )
    pinned_report = apply_report_proposal(report, pin_proposal)

    # Serialize and deserialize
    data = pinned_report.to_dict()
    restored_report = ExecutableReportSpec.from_dict(data)

    ref = _get_block_ref(restored_report, "kpi_move_count", "process_move_fact")
    assert ref.pinned_version == "1.2.3"
    assert ref.pin_reason is not None  # was set during apply


# ---------------------------------------------------------------------------
# Test 8: unpin proposal description mentions "Unpin" and correct block
# ---------------------------------------------------------------------------

def test_unpin_proposal_description_content():
    """unpin_block_version_proposal() description mentions the block being unpinned."""
    report = build_semiconductor_queue_time_report()
    pin_proposal = pin_block_version_proposal(
        report, "main", "kpi_move_count", "process_move_fact", "1.0.0"
    )
    pinned_report = apply_report_proposal(report, pin_proposal)

    unpin_proposal = unpin_block_version_proposal(
        pinned_report, "main", "kpi_move_count", "process_move_fact"
    )
    assert "process_move_fact" in unpin_proposal.description
    assert "npin" in unpin_proposal.description  # "Unpin" or "unpin"


# ---------------------------------------------------------------------------
# Test 9: unpin for unknown visual raises ReportValidationError
# ---------------------------------------------------------------------------

def test_unpin_proposal_unknown_visual_raises():
    """unpin_block_version_proposal() for an unknown visual_id raises ReportValidationError."""
    report = build_semiconductor_queue_time_report()
    with pytest.raises(ReportValidationError):
        unpin_block_version_proposal(
            report, "main", "nonexistent_visual_id", "process_move_fact"
        )
