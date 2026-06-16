"""Tests for Round 029: pie_chart and scatter_chart components + NL2 routing."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.query_spec import (
    AggFunction, BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualQuerySpec, VisualType,
)


# ---------------------------------------------------------------------------
# VisualType enum
# ---------------------------------------------------------------------------

def test_visual_type_has_pie_chart():
    assert VisualType.pie_chart == "pie_chart"


def test_visual_type_has_scatter():
    assert VisualType.scatter == "scatter"


# ---------------------------------------------------------------------------
# Component imports (smoke tests — no Streamlit session needed)
# ---------------------------------------------------------------------------

def test_pie_chart_module_importable():
    from ai4bi.ui.components.pie_chart import render_pie_chart
    assert callable(render_pie_chart)


def test_scatter_chart_module_importable():
    from ai4bi.ui.components.scatter_chart import render_scatter_chart
    assert callable(render_scatter_chart)


# ---------------------------------------------------------------------------
# render_visual dispatch registration
# ---------------------------------------------------------------------------

def test_render_visual_dispatch_includes_pie():
    from ai4bi.ui.render_visual import _COMPONENT_REGISTRY
    assert VisualType.pie_chart in _COMPONENT_REGISTRY


def test_render_visual_dispatch_includes_scatter():
    from ai4bi.ui.render_visual import _COMPONENT_REGISTRY
    assert VisualType.scatter in _COMPONENT_REGISTRY


# ---------------------------------------------------------------------------
# NL2: chart type keyword extraction
# ---------------------------------------------------------------------------

def test_extract_chart_type_pie():
    from ai4bi.ai.nl2proposal import _extract_chart_type
    result = _extract_chart_type("change to pie chart", "change to pie chart")
    assert result == VisualType.pie_chart


def test_extract_chart_type_donut():
    from ai4bi.ai.nl2proposal import _extract_chart_type
    result = _extract_chart_type("make it a donut", "make it a donut")
    assert result == VisualType.pie_chart


def test_extract_chart_type_scatter():
    from ai4bi.ai.nl2proposal import _extract_chart_type
    result = _extract_chart_type("convert to scatter", "convert to scatter")
    assert result == VisualType.scatter


def test_extract_chart_type_chinese_pie():
    from ai4bi.ai.nl2proposal import _extract_chart_type
    result = _extract_chart_type("改成圓餅圖", "改成圓餅圖")
    assert result == VisualType.pie_chart


def test_looks_like_chart_type_change_pie():
    from ai4bi.ai.nl2proposal import _looks_like_chart_type_change
    assert _looks_like_chart_type_change("change to pie chart", "change to pie chart")


def test_looks_like_chart_type_change_scatter():
    from ai4bi.ai.nl2proposal import _looks_like_chart_type_change
    assert _looks_like_chart_type_change("convert to scatter chart", "convert to scatter chart")


# ---------------------------------------------------------------------------
# NL2: chart_type_change handler
# ---------------------------------------------------------------------------

def _make_bar_report():
    from ai4bi.report.models import AuditMetadata, ExecutableReportSpec, ReportPageSpec, ReportVisualSpec
    from ai4bi.query_spec import BlockRef
    spec = VisualQuerySpec(
        "bar_q",
        [BlockRef("sales")],
        metrics=[MetricRef("sales", "revenue", "Revenue")],
        dimensions=[DimensionRef("sales", "region", "Region")],
    )
    viz = VisualizationSpec(VisualType.bar_chart, title="Revenue by Region")
    visual = ReportVisualSpec("bar_q", spec, viz)
    page = ReportPageSpec("main", "Overview", {"bar_q": visual}, ["bar_q"])
    return ExecutableReportSpec(
        audit=AuditMetadata(report_id="test", created_by="tester"),
        title="Test",
        semantic_model_ref="test@1",
        status="user_draft",
        pages={"main": page},
        controls={},
    )


def test_chart_type_change_bar_to_pie():
    from ai4bi.ai.nl2proposal import NL2ProposalService
    svc = NL2ProposalService.__new__(NL2ProposalService)
    svc._semantic_model = {}
    report = _make_bar_report()
    result = svc._chart_type_change("change to pie chart", "change to pie chart", report, "bar_q")
    assert result.proposal is not None
    assert result.proposal.changes


def test_chart_type_change_bar_to_scatter():
    from ai4bi.ai.nl2proposal import NL2ProposalService
    svc = NL2ProposalService.__new__(NL2ProposalService)
    svc._semantic_model = {}
    report = _make_bar_report()
    result = svc._chart_type_change("switch to scatter", "switch to scatter", report, "bar_q")
    assert result.proposal is not None
