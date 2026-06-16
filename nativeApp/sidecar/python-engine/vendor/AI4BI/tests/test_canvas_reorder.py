"""Tests for canvas visual reorder (Round 015-C)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai4bi.report.builder import build_reorder_visual_proposal
from ai4bi.report.models import (
    DraftReportStore,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page():
    """Return the 'main' page from a fresh template report."""
    report = build_semiconductor_queue_time_report()
    return report.pages["main"]


def _order():
    """Return the default visual_order from the template."""
    return list(_make_page().visual_order)


# ---------------------------------------------------------------------------
# Test 1 — move_visual_up swaps visual with the one before it
# ---------------------------------------------------------------------------

def test_move_visual_up_swaps_with_previous():
    page = _make_page()
    original = list(page.visual_order)
    # move the second element up
    target = original[1]
    page.move_visual_up(target)
    assert page.visual_order[0] == target
    assert page.visual_order[1] == original[0]
    # rest unchanged
    assert page.visual_order[2:] == original[2:]


# ---------------------------------------------------------------------------
# Test 2 — move_visual_up is a no-op when visual is already first
# ---------------------------------------------------------------------------

def test_move_visual_up_noop_when_first():
    page = _make_page()
    original = list(page.visual_order)
    first = original[0]
    page.move_visual_up(first)
    assert page.visual_order == original


# ---------------------------------------------------------------------------
# Test 3 — move_visual_down swaps visual with the one after it
# ---------------------------------------------------------------------------

def test_move_visual_down_swaps_with_next():
    page = _make_page()
    original = list(page.visual_order)
    # move the first element down
    target = original[0]
    page.move_visual_down(target)
    assert page.visual_order[0] == original[1]
    assert page.visual_order[1] == target
    assert page.visual_order[2:] == original[2:]


# ---------------------------------------------------------------------------
# Test 4 — move_visual_down is a no-op when visual is already last
# ---------------------------------------------------------------------------

def test_move_visual_down_noop_when_last():
    page = _make_page()
    original = list(page.visual_order)
    last = original[-1]
    page.move_visual_down(last)
    assert page.visual_order == original


# ---------------------------------------------------------------------------
# Test 5 — move_visual_up raises ReportValidationError for unknown visual_id
# ---------------------------------------------------------------------------

def test_move_visual_up_unknown_id_raises():
    page = _make_page()
    with pytest.raises(ReportValidationError, match="not in visual_order"):
        page.move_visual_up("nonexistent_visual")


# ---------------------------------------------------------------------------
# Test 6 — build_reorder_visual_proposal returns a proposal with affects_data=False
# ---------------------------------------------------------------------------

def test_build_reorder_visual_proposal_affects_data_false():
    order = _order()
    visual_id = order[1]
    proposal = build_reorder_visual_proposal(
        page_id="main",
        visual_id=visual_id,
        direction="up",
        current_order=order,
    )
    assert proposal.affects_data is False
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.path == "pages/main/reorder_visual"
    assert change.before == order
    assert change.after == {"visual_id": visual_id, "direction": "up"}


# ---------------------------------------------------------------------------
# Test 7 — applying a reorder proposal updates visual_order
# ---------------------------------------------------------------------------

def test_apply_reorder_proposal_updates_visual_order():
    report = build_semiconductor_queue_time_report()
    original_order = list(report.pages["main"].visual_order)
    target = original_order[2]  # third visual, move it up

    proposal = build_reorder_visual_proposal(
        page_id="main",
        visual_id=target,
        direction="up",
        current_order=original_order,
    )
    updated = apply_report_proposal(report, proposal)

    new_order = list(updated.pages["main"].visual_order)
    assert new_order[1] == target  # moved one position earlier
    assert new_order[2] == original_order[1]


# ---------------------------------------------------------------------------
# Test 8 — round-trip: apply up then down returns to original order
# ---------------------------------------------------------------------------

def test_reorder_round_trip_up_then_down():
    report = build_semiconductor_queue_time_report()
    original_order = list(report.pages["main"].visual_order)
    target = original_order[1]  # second element

    # Move up
    proposal_up = build_reorder_visual_proposal(
        page_id="main",
        visual_id=target,
        direction="up",
        current_order=list(report.pages["main"].visual_order),
    )
    report_after_up = apply_report_proposal(report, proposal_up)

    # Move back down
    proposal_down = build_reorder_visual_proposal(
        page_id="main",
        visual_id=target,
        direction="down",
        current_order=list(report_after_up.pages["main"].visual_order),
    )
    report_after_down = apply_report_proposal(report_after_up, proposal_down)

    assert list(report_after_down.pages["main"].visual_order) == original_order


# ---------------------------------------------------------------------------
# Test 9 — ANALYST_NAME env var is reflected in audit.last_modified_by after save
# ---------------------------------------------------------------------------

def test_analyst_name_reflected_in_last_modified_by(tmp_path):
    report = build_semiconductor_queue_time_report()
    store = DraftReportStore(tmp_path)

    analyst_name = "alice_analyst"
    old_value = os.environ.get("ANALYST_NAME")
    try:
        os.environ["ANALYST_NAME"] = analyst_name
        saved_path = store.save(report)
        loaded = store.load(saved_path)
    finally:
        if old_value is None:
            os.environ.pop("ANALYST_NAME", None)
        else:
            os.environ["ANALYST_NAME"] = old_value

    assert loaded.audit.last_modified_by == analyst_name


# ---------------------------------------------------------------------------
# Bonus test — move_visual_down raises ReportValidationError for unknown visual_id
# ---------------------------------------------------------------------------

def test_move_visual_down_unknown_id_raises():
    page = _make_page()
    with pytest.raises(ReportValidationError, match="not in visual_order"):
        page.move_visual_down("nonexistent_visual")
