"""Round 158: delete a single visual (model + proposal + apply round-trip)."""

from __future__ import annotations

import pytest

from ai4bi.report.models import apply_report_proposal, ReportValidationError
from ai4bi.report.proposals import build_delete_visual_proposal
from ai4bi.report.retail_template import build_retail_demo_report


def _first(report):
    pid = next(iter(report.pages))
    vid = list(report.pages[pid].visuals)[0]
    return pid, vid


def test_delete_visual_removes_it_and_keeps_order_invariant():
    report = build_retail_demo_report()
    pid, vid = _first(report)
    n0 = len(report.pages[pid].visuals)
    updated = apply_report_proposal(report, build_delete_visual_proposal(report, pid, vid))
    page = updated.pages[pid]
    assert vid not in page.visuals
    assert vid not in page.visual_order
    assert set(page.visual_order) == set(page.visuals)  # invariant holds
    assert len(page.visuals) == n0 - 1


def test_delete_visual_unknown_id_raises():
    report = build_retail_demo_report()
    pid = next(iter(report.pages))
    with pytest.raises(ReportValidationError):
        build_delete_visual_proposal(report, pid, "no_such_visual")


def test_delete_proposal_is_not_stale():
    # the before-value must match _get_path so apply doesn't reject it as stale
    report = build_retail_demo_report()
    pid, vid = _first(report)
    proposal = build_delete_visual_proposal(report, pid, vid)
    # applying twice: first succeeds, second must raise (already gone)
    updated = apply_report_proposal(report, proposal)
    assert vid not in updated.pages[pid].visuals
