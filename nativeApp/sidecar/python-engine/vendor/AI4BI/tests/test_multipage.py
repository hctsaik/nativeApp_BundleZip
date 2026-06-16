"""Tests for Round 016-C: Multi-page tab switcher."""

from __future__ import annotations

import pytest

from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportPageSpec,
    ReportValidationError,
    apply_report_proposal,
)
from ai4bi.report.proposals import build_page_rename_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_empty_page(page_id: str, display_name: str = "") -> ReportPageSpec:
    """Return a minimal valid ReportPageSpec with no visuals."""
    return ReportPageSpec(
        page_id=page_id,
        title=f"Title for {page_id}",
        visuals={},
        visual_order=[],
        display_name=display_name,
    )


# ---------------------------------------------------------------------------
# Test 1: display_name defaults to ""
# ---------------------------------------------------------------------------

def test_report_page_spec_display_name_defaults_to_empty():
    page = _make_empty_page("main")
    assert page.display_name == ""


# ---------------------------------------------------------------------------
# Test 2: to_dict / from_dict round-trip preserves display_name
# ---------------------------------------------------------------------------

def test_report_page_spec_round_trip_with_display_name():
    page = _make_empty_page("analytics", display_name="Analytics Overview")
    d = page.to_dict()
    assert d["display_name"] == "Analytics Overview"
    restored = ReportPageSpec.from_dict(d)
    assert restored.display_name == "Analytics Overview"
    assert restored.page_id == "analytics"


def test_report_page_spec_round_trip_empty_display_name():
    """from_dict on a dict without display_name key should default to ''."""
    page = _make_empty_page("main")
    d = page.to_dict()
    # Simulate old serialised format that has no display_name key
    del d["display_name"]
    restored = ReportPageSpec.from_dict(d)
    assert restored.display_name == ""


# ---------------------------------------------------------------------------
# Test 3: build_page_rename_proposal returns affects_data=False
# ---------------------------------------------------------------------------

def test_build_page_rename_proposal_affects_data_false():
    proposal = build_page_rename_proposal(
        page_id="main",
        current_name="",
        new_name="ETCH Queue-Time",
    )
    assert not proposal.affects_data
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.path == "pages/main/display_name"
    assert change.before == ""
    assert change.after == "ETCH Queue-Time"


# ---------------------------------------------------------------------------
# Test 4: Applying rename proposal updates page.display_name
# ---------------------------------------------------------------------------

def test_applying_rename_proposal_updates_display_name():
    report = build_semiconductor_queue_time_report()
    proposal = build_page_rename_proposal(
        page_id="main",
        current_name=report.pages["main"].display_name,
        new_name="My Custom Name",
    )
    updated = apply_report_proposal(report, proposal)
    assert updated.pages["main"].display_name == "My Custom Name"
    # Original is not mutated
    assert report.pages["main"].display_name != "My Custom Name"


# ---------------------------------------------------------------------------
# Test 5: ExecutableReportSpec.add_page() adds a new page
# ---------------------------------------------------------------------------

def test_add_page_adds_new_page():
    report = build_semiconductor_queue_time_report()
    assert "secondary" not in report.pages
    new_page = _make_empty_page("secondary", display_name="Secondary Page")
    report.add_page("secondary", new_page)
    assert "secondary" in report.pages
    assert report.pages["secondary"].display_name == "Secondary Page"


# ---------------------------------------------------------------------------
# Test 6: add_page() raises ReportValidationError when page_id already exists
# ---------------------------------------------------------------------------

def test_add_page_raises_when_page_id_exists():
    report = build_semiconductor_queue_time_report()
    dup_page = _make_empty_page("main")
    with pytest.raises(ReportValidationError, match="already exists"):
        report.add_page("main", dup_page)


# ---------------------------------------------------------------------------
# Test 7: Template sets display_name="ETCH Queue-Time" on main page
# ---------------------------------------------------------------------------

def test_template_sets_display_name_on_main_page():
    report = build_semiconductor_queue_time_report()
    assert report.pages["main"].display_name == "ETCH Queue-Time"


# ---------------------------------------------------------------------------
# Test 8: to_dict / from_dict round-trip on a 2-page report preserves both
#         pages and their display names
# ---------------------------------------------------------------------------

def test_two_page_report_round_trip():
    report = build_semiconductor_queue_time_report()
    extra_page = _make_empty_page("trends", display_name="Trends Dashboard")
    report.add_page("trends", extra_page)

    d = report.to_dict()

    # Both pages present in serialised form
    assert "main" in d["pages"]
    assert "trends" in d["pages"]
    assert d["pages"]["main"]["display_name"] == "ETCH Queue-Time"
    assert d["pages"]["trends"]["display_name"] == "Trends Dashboard"

    restored = ExecutableReportSpec.from_dict(d)
    assert restored.pages["main"].display_name == "ETCH Queue-Time"
    assert restored.pages["trends"].display_name == "Trends Dashboard"
    assert len(restored.pages) == 2
