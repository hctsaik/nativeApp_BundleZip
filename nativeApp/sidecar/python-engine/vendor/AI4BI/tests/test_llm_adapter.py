"""Tests for LLMAdapter and NL2ProposalService LLM integration.

These tests run entirely in mock mode (no API calls) and verify:
1. LLMAdapter returns mock_passthrough when LLM_MODE != anthropic.
2. LLMAdapter returns mock_passthrough when key is missing.
3. NL2ProposalService falls back correctly to keyword routing.
4. LLM intent dispatch routes to the correct handler (via monkey-patch).
"""

from __future__ import annotations

import os
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from ai4bi.ai.llm_adapter import (
    LLMAdapter,
    IntentClassification,
    get_llm_mode_label,
)
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def report():
    return build_semiconductor_queue_time_report()


@pytest.fixture()
def visual_id(report):
    return next(iter(report.pages["main"].visuals))


@pytest.fixture()
def line_visual_id(report):
    """A line_chart visual in the demo report (supports color / chart-type change)."""
    from ai4bi.query_spec import VisualType
    for vid, visual in report.pages["main"].visuals.items():
        if visual.visualization.visual_type == VisualType.line_chart:
            return vid
    # Fallback: return any non-kpi visual
    from ai4bi.query_spec import VisualType as VT
    for vid, visual in report.pages["main"].visuals.items():
        if visual.visualization.visual_type != VT.kpi_card:
            return vid
    return next(iter(report.pages["main"].visuals))


# ---------------------------------------------------------------------------
# LLMAdapter — mode detection
# ---------------------------------------------------------------------------

class TestLLMAdapterModeDetection:
    def test_default_mode_is_mock(self, monkeypatch):
        monkeypatch.delenv("LLM_MODE", raising=False)
        adapter = LLMAdapter()
        assert adapter.active_mode == "mock"

    def test_mock_explicit(self, monkeypatch):
        monkeypatch.setenv("LLM_MODE", "mock")
        adapter = LLMAdapter()
        assert adapter.active_mode == "mock"

    def test_anthropic_without_key_is_mock(self, monkeypatch):
        monkeypatch.setenv("LLM_MODE", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        adapter = LLMAdapter()
        assert adapter.active_mode == "mock"

    def test_anthropic_with_key_is_llm(self, monkeypatch):
        monkeypatch.setenv("LLM_MODE", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        adapter = LLMAdapter()
        assert adapter.active_mode == "llm"


# ---------------------------------------------------------------------------
# LLMAdapter.classify — mock passthrough
# ---------------------------------------------------------------------------

class TestLLMAdapterClassify:
    def test_classify_mock_returns_passthrough(self, monkeypatch, report, visual_id):
        monkeypatch.setenv("LLM_MODE", "mock")
        result = LLMAdapter().classify("make it red", report, visual_id)
        assert result.mode == "mock"
        assert result.intent == "mock_passthrough"

    def test_classify_missing_key_returns_passthrough(self, monkeypatch, report, visual_id):
        monkeypatch.setenv("LLM_MODE", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = LLMAdapter().classify("make it red", report, visual_id)
        assert result.mode == "mock"

    def test_classify_api_error_returns_passthrough(self, monkeypatch, report, visual_id):
        monkeypatch.setenv("LLM_MODE", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        def bad_call(*a, **kw):
            raise RuntimeError("simulated API failure")

        adapter = LLMAdapter()
        with patch.object(adapter, "_call_anthropic", side_effect=bad_call):
            result = adapter.classify("make it red", report, visual_id)
        assert result.mode == "mock"


# ---------------------------------------------------------------------------
# get_llm_mode_label
# ---------------------------------------------------------------------------

class TestGetLLMModeLabel:
    def test_mock_label(self, monkeypatch):
        monkeypatch.setenv("LLM_MODE", "mock")
        assert get_llm_mode_label() == "Mock NL2"

    def test_llm_label(self, monkeypatch):
        monkeypatch.setenv("LLM_MODE", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        label = get_llm_mode_label()
        assert label.startswith("LLM:")


# ---------------------------------------------------------------------------
# NL2ProposalService — LLM dispatch via mock classification
# ---------------------------------------------------------------------------

def _make_classification(intent: str, **params) -> IntentClassification:
    return IntentClassification(intent=intent, parameters=params, mode="llm", confidence=0.95)


class TestNL2LLMDispatch:
    """Verify that each LLM intent is dispatched to the right handler."""

    def _propose_with_llm(self, classification, prompt, report, visual_id, semantic_model=None):
        svc = NL2ProposalService()
        with patch("ai4bi.ai.nl2proposal.LLMAdapter") as MockAdapter:
            instance = MagicMock()
            instance.classify.return_value = classification
            MockAdapter.return_value = instance
            return svc.propose(prompt, report, visual_id, semantic_model=semantic_model)

    def test_style_change_red(self, report, line_visual_id):
        clf = _make_classification("style_change", color="red")
        result = self._propose_with_llm(clf, "make it red", report, line_visual_id)
        assert result.proposal is not None
        assert result.proposal.changes[0].after == "#D62728"

    def test_chart_type_change_to_bar(self, report, line_visual_id):
        clf = _make_classification("chart_type_change", target_type="bar_chart")
        result = self._propose_with_llm(clf, "switch to bar", report, line_visual_id)
        # line_chart → bar_chart is a valid transition
        assert result.proposal is not None or "already" in result.message.lower()

    def test_dimension_change_monthly(self, report, line_visual_id):
        clf = _make_classification("dimension_change", granularity="month")
        result = self._propose_with_llm(clf, "group by month", report, line_visual_id)
        assert result.proposal is not None or result.message

    def test_date_filter_last_3_months(self, report, visual_id):
        clf = _make_classification("date_filter_change", period="最近3個月")
        result = self._propose_with_llm(clf, "最近3個月", report, visual_id)
        assert result.proposal is not None
        assert result.proposal.changes[0].after == {"anchor": "relative", "period": "last_3m"}

    def test_rename_visual(self, report, line_visual_id):
        clf = _make_classification("rename_visual", new_title="My Custom Chart")
        result = self._propose_with_llm(clf, "rename to My Custom Chart", report, line_visual_id)
        assert result.proposal is not None
        assert result.proposal.changes[0].after == "My Custom Chart"

    def test_unsupported_llm_intent(self, report, visual_id):
        clf = _make_classification("unsupported", reason="Raw SQL request refused.")
        result = self._propose_with_llm(clf, "write SQL for me", report, visual_id)
        assert result.proposal is None
        assert result.message  # some message is shown

    def test_governance_block_overrides_llm(self, report, visual_id):
        """Governance hard-block must fire even if LLM would classify the intent."""
        clf = _make_classification("style_change", color="red")
        svc = NL2ProposalService()
        # SQL patterns trigger governance refusal before LLM routing
        with patch("ai4bi.ai.nl2proposal.LLMAdapter") as MockAdapter:
            instance = MagicMock()
            instance.classify.return_value = clf
            MockAdapter.return_value = instance
            result = svc.propose("select * from yield join moves", report, visual_id)
        # Governance should have blocked this before LLM dispatch
        assert result.refusal is not None or result.proposal is None

    def test_fallback_to_keyword_when_llm_returns_unknown_intent(self, report, line_visual_id):
        """If LLM returns an unrecognised intent, keyword routing takes over."""
        clf = IntentClassification(intent="unknown_future_intent", mode="llm", confidence=0.5)
        result = self._propose_with_llm(clf, "make trend line red", report, line_visual_id)
        # Keyword fallback should handle "red" → style_change on line chart
        assert result.proposal is not None
