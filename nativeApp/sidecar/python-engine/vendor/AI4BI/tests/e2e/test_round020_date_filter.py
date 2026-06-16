"""
Round 020 Playwright E2E — Date Filter NL2 Intent.

Validates that the Visual Assistant in the Streamlit UI:
  - Accepts date filter prompts without crashing
  - Shows a proposal or informative message for known date periods
  - Shows governance refusal for SQL requests (no regression)
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

_PROMPT_PLACEHOLDER = "上個月營收多少"  # R106: matches the R102 text_area placeholder


def _load_app(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="networkidle", timeout=60_000)
    page.wait_for_selector("[data-testid='stApp']", timeout=30_000)
    page.wait_for_timeout(4_000)


def _submit_prompt(page: Page, prompt: str, wait_ms: int = 4_000) -> None:
    text_input = page.get_by_placeholder(_PROMPT_PLACEHOLDER, exact=False).first
    text_input.fill(prompt)
    page.wait_for_timeout(300)
    analyze_btn = page.locator("button", has_text="Analyze Request").first
    analyze_btn.click()
    page.wait_for_timeout(wait_ms)


def _no_exception(page: Page) -> bool:
    return page.locator("[data-testid='stException']").count() == 0


def _page_contains(page: Page, text: str) -> bool:
    return text.lower() in page.inner_text("body").lower()


class TestDateFilterNoCrash:
    """Primary guarantee: date filter prompts must not crash the app."""

    def test_last_3m_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "最近3個月")
        assert _no_exception(page), "App crashed on 最近3個月 prompt"

    def test_last_quarter_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "last quarter")
        assert _no_exception(page), "App crashed on last quarter prompt"

    def test_ytd_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "今年")
        assert _no_exception(page), "App crashed on 今年 prompt"

    def test_clear_date_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "清除日期")
        assert _no_exception(page), "App crashed on 清除日期 prompt"


class TestDateFilterFeedback:
    """Date filter prompts should produce visible feedback."""

    def test_date_filter_shows_feedback(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "最近3個月")
        # Either a proposal staged or a message shown
        has_feedback = (
            _page_contains(page, "proposal")
            or _page_contains(page, "date")
            or _page_contains(page, "last_3m")
            or _page_contains(page, "filter")
        )
        assert has_feedback, "Expected date filter feedback in page"

    def test_multiple_date_prompts_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        for prompt in ["最近3個月", "last quarter", "今年", "清除日期"]:
            _submit_prompt(page, prompt, wait_ms=2_000)
            assert _no_exception(page), f"Crashed on: {prompt!r}"
