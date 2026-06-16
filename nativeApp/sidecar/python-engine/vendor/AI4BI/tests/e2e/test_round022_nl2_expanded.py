"""
Round 022 Playwright E2E — Expanded NL2 intent coverage.

Validates:
  - 5 new intents produce no crash
  - rename, remove metric, categorical group, value filter all work in UI
  - Queue analysis not intercepted by new intents
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

_PROMPT_PLACEHOLDER = "上個月營收多少"  # R106: matches the R102 text_area placeholder


def _load_app(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="networkidle", timeout=60_000)
    page.wait_for_selector("[data-testid='stApp']", timeout=30_000)
    page.wait_for_timeout(4_000)


def _submit(page: Page, prompt: str, wait_ms: int = 4_000) -> None:
    inp = page.get_by_placeholder(_PROMPT_PLACEHOLDER, exact=False).first
    inp.fill(prompt)
    page.wait_for_timeout(300)
    page.locator("button", has_text="Analyze Request").first.click()
    page.wait_for_timeout(wait_ms)


def _ok(page: Page) -> bool:
    return page.locator("[data-testid='stException']").count() == 0


def _body(page: Page) -> str:
    return page.inner_text("body").lower()


class TestNoCrashExpanded:
    """All new intents must not crash the app."""

    @pytest.mark.parametrize("prompt", [
        "add metric move_count",
        "add move_count",
        "rename this chart to Queue Trend",
        "group by product family",
        "only show PHOTO",
        "filter to ETCH",
        "remove queue_time_hr",
        "analyze queue time drivers by tool",  # must NOT be intercepted
    ])
    def test_no_crash(self, page: Page, app_url: str, prompt: str):
        _load_app(page, app_url)
        _submit(page, prompt)
        assert _ok(page), f"Crash on: {prompt!r}"


class TestFeedbackVisible:

    def test_add_metric_feedback(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit(page, "add metric move_count")
        assert _ok(page)
        assert "proposal" in _body(page) or "metric" in _body(page)

    def test_rename_feedback(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit(page, "rename this chart to MyCustomChart")
        assert _ok(page)
        assert "mycustomchart" in _body(page) or "proposal" in _body(page)

    def test_group_by_feedback(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit(page, "group by product family")
        assert _ok(page)
        assert "proposal" in _body(page) or "dimension" in _body(page)

    def test_value_filter_feedback(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit(page, "only show PHOTO")
        assert _ok(page)
        assert "proposal" in _body(page) or "filter" in _body(page) or "photo" in _body(page)

    def test_queue_analysis_still_works(self, page: Page, app_url: str):
        """Queue analysis must not be intercepted by categorical/value-filter."""
        _load_app(page, app_url)
        _submit(page, "analyze queue time drivers")
        assert _ok(page)
        # Should produce analysis plan, not crash
        assert "analysis" in _body(page) or "plan" in _body(page) or "queue" in _body(page)
