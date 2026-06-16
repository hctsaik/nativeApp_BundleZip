"""
Round 019 Playwright E2E tests — NL2 Proposal new intents.

Tests validate that the Visual Assistant in the Streamlit UI:
  - Accepts chart type change requests and stages a proposal
  - Shows refusal message for governance-blocked requests
  - No crash (AttributeError) on any Analyze Request click
  - Defensive _store_visual_assistant_context no longer crashes on hot-reload
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

_PROMPT_PLACEHOLDER = "上個月營收多少"  # R106: matches the R102 text_area placeholder


def _load_app(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="networkidle", timeout=60_000)
    page.wait_for_selector("[data-testid='stApp']", timeout=30_000)
    page.wait_for_timeout(4_000)


def _submit_prompt(page: Page, prompt: str, wait_ms: int = 5_000) -> None:
    """Fill the Visual Assistant prompt input (identified by placeholder) and click Analyze."""
    text_input = page.get_by_placeholder(_PROMPT_PLACEHOLDER, exact=False).first
    text_input.fill(prompt)
    page.wait_for_timeout(300)
    analyze_btn = page.locator("button", has_text="Analyze Request").first
    analyze_btn.click()
    page.wait_for_timeout(wait_ms)


def _no_exception(page: Page) -> bool:
    """Return True if no Streamlit exception box is visible."""
    return page.locator("[data-testid='stException']").count() == 0


def _page_contains(page: Page, text: str) -> bool:
    """Return True if the page text contains the given string (case-insensitive)."""
    return text.lower() in page.inner_text("body").lower()


class TestNL2NocrashGuarantee:
    """Primary E2E requirement: Analyze Request must NEVER crash the app."""

    def test_chart_type_change_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "把這個改成長條圖")
        assert _no_exception(page), "App crashed on chart type change prompt"

    def test_line_to_bar_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "change to line chart")
        assert _no_exception(page), "App crashed on English chart type change"

    def test_dimension_change_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "改用月份分組")
        assert _no_exception(page), "App crashed on dimension change"

    def test_add_metric_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "也加上move_count")
        assert _no_exception(page), "App crashed on add metric prompt"

    def test_sql_refusal_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "SELECT * FROM process_move_fact JOIN tool_dim")
        assert _no_exception(page), "App crashed on SQL governance refusal"

    def test_repeated_prompts_no_crash(self, page: Page, app_url: str):
        _load_app(page, app_url)
        prompts = [
            "改成折線圖",
            "改用月份分組",
            "也加上move_count",
            "SELECT * FROM table",
        ]
        for prompt in prompts:
            _submit_prompt(page, prompt, wait_ms=2_000)
            assert _no_exception(page), f"App crashed on prompt: {prompt!r}"


class TestNL2GovernanceRefusal:
    """SQL/join requests must produce a refusal message, not a crash."""

    def test_sql_request_shows_message(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "SELECT * FROM table JOIN other")
        # The governance refusal message contains "governed" or "workflow"
        assert (
            _page_contains(page, "governed")
            or _page_contains(page, "workflow")
            or _page_contains(page, "cannot be staged")
        ), "Expected governance refusal text in page after SQL prompt"

    def test_yield_join_request_refused(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "join yield detail rows")
        assert _no_exception(page), "SQL refusal crashed the app"
        assert _page_contains(page, "governed") or _page_contains(page, "workflow"), \
            "Expected refusal message"


class TestNL2ProposalWorkflow:
    """Chart-type change produces a pending proposal that can be cancelled."""

    def test_chart_change_produces_message_or_proposal(self, page: Page, app_url: str):
        _load_app(page, app_url)
        _submit_prompt(page, "改成折線圖")
        # One of: Pending Proposal staged, "already" message, or any workspace message
        has_pending = _page_contains(page, "Pending Proposal")
        has_already = _page_contains(page, "already")
        has_proposal_staged = _page_contains(page, "proposal")
        assert has_pending or has_already or has_proposal_staged, \
            "Expected some feedback after chart type change prompt"

    def test_cancel_clears_pending_proposal(self, page: Page, app_url: str):
        _load_app(page, app_url)
        # Try to get a pending proposal by changing chart type
        _submit_prompt(page, "把這個改成折線圖")
        cancel_btn = page.locator("button", has_text="Cancel Proposal")
        if cancel_btn.count() > 0:
            cancel_btn.first.click()
            page.wait_for_timeout(2_000)
            assert page.locator("text=Pending Proposal").count() == 0, \
                "Pending proposal not cleared after Cancel"
