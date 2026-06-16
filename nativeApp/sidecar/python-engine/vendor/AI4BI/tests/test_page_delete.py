"""Focused regression tests for page delete proposals."""

from __future__ import annotations

import pytest

from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportChange,
    ReportPageSpec,
    ReportProposal,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.proposals import build_page_delete_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report


def _make_empty_page(page_id: str, display_name: str = "") -> ReportPageSpec:
    return ReportPageSpec(
        page_id=page_id,
        title=f"Title for {page_id}",
        visuals={},
        visual_order=[],
        display_name=display_name,
    )


def _two_page_report() -> ExecutableReportSpec:
    report = build_semiconductor_queue_time_report()
    report.add_page("details", _make_empty_page("details", "Details"))
    return report


def test_delete_page_removes_existing_page():
    report = _two_page_report()

    report.delete_page("details")

    assert "details" not in report.pages
    assert "main" in report.pages


def test_delete_page_cannot_delete_last_page():
    report = build_semiconductor_queue_time_report()

    with pytest.raises(ReportValidationError, match="last page"):
        report.delete_page("main")

    proposal = build_page_delete_proposal(report, "main")
    with pytest.raises(ReportValidationError, match="last page"):
        apply_report_proposal(report, proposal)
    assert "main" in report.pages


def test_build_page_delete_proposal_uses_full_page_before_and_none_after():
    report = _two_page_report()
    page_before = report.pages["details"].to_dict()

    proposal = build_page_delete_proposal(report, "details")

    assert proposal.affects_data is True
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.path == "pages/details/delete"
    assert change.before == page_before
    assert change.after is None


def test_apply_page_delete_proposal_removes_page_without_mutating_original():
    report = _two_page_report()
    proposal = build_page_delete_proposal(report, "details")

    updated = apply_report_proposal(report, proposal)

    assert "details" not in updated.pages
    assert "details" in report.pages
    assert updated.revision == report.revision + 1


def test_page_delete_proposal_is_atomic_when_later_change_is_stale():
    report = _two_page_report()
    proposal = ReportProposal(
        description="Delete page then stale title",
        changes=[
            build_page_delete_proposal(report, "details").changes[0],
            ReportChange(
                path="title",
                label="Report title",
                before="Wrong stale title",
                after="New title",
                affects_data=False,
            ),
        ],
    )

    with pytest.raises(ReportValidationError, match="stale"):
        apply_report_proposal(report, proposal)

    assert "details" in report.pages
    assert report.title != "New title"
    assert report.revision == 0


def test_page_delete_round_trip_preserves_other_pages():
    report = _two_page_report()
    report.add_page("trends", _make_empty_page("trends", "Trends"))
    main_before = report.pages["main"].to_dict()
    trends_before = report.pages["trends"].to_dict()

    updated = apply_report_proposal(
        report,
        build_page_delete_proposal(report, "details"),
    )
    restored = ExecutableReportSpec.from_dict(updated.to_dict())

    assert set(restored.pages) == {"main", "trends"}
    assert restored.pages["main"].to_dict() == main_before
    assert restored.pages["trends"].to_dict() == trends_before
