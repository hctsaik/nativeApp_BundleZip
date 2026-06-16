"""Round 076: state-driven page navigation (drill-through enabler)."""

from __future__ import annotations

from ai4bi.ui.app import _resolve_active_page


def test_resolve_returns_requested_when_valid():
    assert _resolve_active_page(["main", "detail"], "detail") == "detail"


def test_resolve_falls_back_to_first():
    assert _resolve_active_page(["main", "detail"], None) == "main"
    assert _resolve_active_page(["main", "detail"], "nonexistent") == "main"


def test_default_report_single_page_unaffected():
    """The default retail demo is single-page → no nav, renders directly."""
    from ai4bi.report.retail_template import build_retail_demo_report
    report = build_retail_demo_report()
    assert len(report.pages) == 1   # canvas takes the single-page fast path
