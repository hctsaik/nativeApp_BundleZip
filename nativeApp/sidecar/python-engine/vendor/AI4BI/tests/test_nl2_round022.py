"""
Round 022 — NL2 expanded intent coverage tests.

Tests five new or improved capabilities:
  1. add_metric — broader keyword detection
  2. remove_metric — governance: cannot empty a visual
  3. rename_visual — title change, XSS safe
  4. categorical_dimension_change — certified relationship whitelist
  5. value_filter_change — query/filters path, PHOTO/ETCH/CVD
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.models import apply_report_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_SEMANTIC_MODEL = json.loads((_DEMO_ROOT / "semantic_model.json").read_text(encoding="utf-8"))


@pytest.fixture
def svc():
    return NL2ProposalService()


@pytest.fixture
def report():
    return build_semiconductor_queue_time_report()


@pytest.fixture
def sm():
    return _SEMANTIC_MODEL


# ===========================================================================
# 1. add_metric — broader keywords
# ===========================================================================

class TestAddMetricBroaderKeywords:

    @pytest.mark.parametrize("prompt", [
        "add move_count",
        "add metric move_count",
        "add the move_count metric",
        "add move_count to this chart",
        "also show move_count",
        "include move_count metric",
        "也加上move_count",
        "加上move_count指標",
    ])
    def test_add_metric_detected(self, svc, report, sm, prompt):
        result = svc.propose(prompt, report, "line_queue_by_day", semantic_model=sm)
        assert result.proposal is not None, f"No proposal for: {prompt!r}"
        metrics_after = result.proposal.changes[0].after
        names_after = [m["metric_name"] for m in metrics_after]
        assert "move_count" in names_after


# ===========================================================================
# 2. remove_metric
# ===========================================================================

class TestRemoveMetric:

    def _add_metric(self, svc, report, sm):
        r = svc.propose("add metric move_count", report, "line_queue_by_day", semantic_model=sm)
        return apply_report_proposal(report, r.proposal)

    def test_remove_metric_proposal(self, svc, report, sm):
        report_with_2 = self._add_metric(svc, report, sm)
        result = svc.propose("remove queue_time_hr", report_with_2, "line_queue_by_day")
        assert result.proposal is not None
        after = result.proposal.changes[0].after
        names = [m["metric_name"] for m in after]
        assert "queue_time_hr" not in names
        assert "move_count" in names

    def test_remove_metric_affects_data_true(self, svc, report, sm):
        report_with_2 = self._add_metric(svc, report, sm)
        result = svc.propose("remove queue_time_hr", report_with_2, "line_queue_by_day")
        assert result.proposal.changes[0].affects_data is True

    def test_cannot_remove_last_metric(self, svc, report):
        """Removing the only metric → governance refusal."""
        result = svc.propose("remove queue_time_hr", report, "line_queue_by_day")
        assert result.proposal is None
        assert result.refusal is not None
        assert "at least one metric" in result.message.lower()

    def test_remove_nonexistent_metric_unsupported(self, svc, report):
        result = svc.propose("remove nonexistent_metric", report, "line_queue_by_day")
        assert result.proposal is None

    def test_remove_roundtrip(self, svc, report, sm):
        report_with_2 = self._add_metric(svc, report, sm)
        result = svc.propose("remove queue_time_hr", report_with_2, "line_queue_by_day")
        updated = apply_report_proposal(report_with_2, result.proposal)
        metrics = [m.metric_name for m in updated.pages["main"].visuals["line_queue_by_day"].query.metrics]
        assert "queue_time_hr" not in metrics
        assert len(metrics) == 1


# ===========================================================================
# 3. rename_visual
# ===========================================================================

class TestRenameVisual:

    @pytest.mark.parametrize("prompt,expected_title", [
        ("rename this chart to Queue Trend", "Queue Trend"),
        ("change title to Average Wait", "Average Wait"),
        ("set title to My Custom Chart", "My Custom Chart"),
    ])
    def test_rename_proposal(self, svc, report, prompt, expected_title):
        result = svc.propose(prompt, report, "line_queue_by_day")
        assert result.proposal is not None, f"No proposal for: {prompt!r}"
        change = result.proposal.changes[0]
        assert change.after == expected_title
        assert change.affects_data is False

    def test_rename_path_is_visualization_title(self, svc, report):
        result = svc.propose("rename this chart to Test", report, "line_queue_by_day")
        assert result.proposal.changes[0].path.endswith("/visualization/title")

    def test_rename_risk_level_low(self, svc, report):
        result = svc.propose("rename this chart to Test", report, "line_queue_by_day")
        assert result.risk_level == "low"

    def test_rename_requires_visual_selection(self, svc, report):
        result = svc.propose("rename this chart to Test", report, None)
        assert result.proposal is None

    def test_rename_xss_stripped(self, svc, report):
        result = svc.propose('rename this chart to <script>alert(1)</script>Queue', report, "line_queue_by_day")
        if result.proposal:
            assert "<script>" not in result.proposal.changes[0].after

    def test_rename_already_same_no_proposal(self, svc, report):
        current_title = report.pages["main"].visuals["line_queue_by_day"].visualization.title
        if current_title:
            result = svc.propose(f"rename this chart to {current_title}", report, "line_queue_by_day")
            assert result.proposal is None

    def test_rename_roundtrip(self, svc, report):
        result = svc.propose("rename this chart to Queue Trend", report, "line_queue_by_day")
        updated = apply_report_proposal(report, result.proposal)
        assert updated.pages["main"].visuals["line_queue_by_day"].visualization.title == "Queue Trend"


# ===========================================================================
# 4. categorical_dimension_change
# ===========================================================================

class TestCategoricalDimensionChange:

    @pytest.mark.parametrize("prompt,expected_col", [
        ("group by product family", "product_family"),
        ("group by vendor", "vendor"),
        ("group by tool", "tool_id"),
        ("breakdown by product family", "product_family"),
    ])
    def test_categorical_dim_proposal(self, svc, report, sm, prompt, expected_col):
        result = svc.propose(prompt, report, "bar_queue_by_tool_dimension", semantic_model=sm)
        assert result.proposal is not None, f"No proposal for: {prompt!r}"
        after_dims = result.proposal.changes[0].after
        cols = [d["column_name"] for d in after_dims]
        assert expected_col in cols

    def test_categorical_dim_affects_data_true(self, svc, report, sm):
        result = svc.propose("group by product family", report, "bar_queue_by_tool_dimension", semantic_model=sm)
        assert result.proposal.changes[0].affects_data is True

    def test_categorical_dim_blocks_uncertified(self, svc, report):
        """Without semantic_model, cannot verify certification → refusal."""
        result = svc.propose("group by product family", report, "bar_queue_by_tool_dimension", semantic_model={})
        # No certified relationships in empty SM → governance refusal
        assert result.proposal is None
        assert result.refusal is not None
        assert result.risk_level == "high"

    def test_categorical_dim_requires_visual(self, svc, report, sm):
        result = svc.propose("group by product family", report, None, semantic_model=sm)
        assert result.proposal is None

    def test_queue_analysis_not_intercepted(self, svc, report, sm):
        """'analyze queue time drivers by tool' must NOT trigger categorical_dimension_change."""
        result = svc.propose("analyze queue time drivers by tool", report, "line_queue_by_day", semantic_model=sm)
        # Should be queue_analysis plan, not categorical
        assert result.analysis_plan is not None
        assert result.proposal is None


# ===========================================================================
# 5. value_filter_change
# ===========================================================================

class TestValueFilterChange:

    @pytest.mark.parametrize("prompt,expected_values", [
        ("only show PHOTO", ["PHOTO"]),
        ("filter to ETCH", ["ETCH"]),
        ("only show PHOTO process", ["PHOTO"]),
        ("只看 ETCH", ["ETCH"]),
    ])
    def test_value_filter_proposal(self, svc, report, sm, prompt, expected_values):
        result = svc.propose(prompt, report, "line_queue_by_day", semantic_model=sm)
        assert result.proposal is not None, f"No proposal for: {prompt!r}"
        change = result.proposal.changes[0]
        assert change.affects_data is True
        after = change.after
        matched = any(
            set(f.get("value", [])) == set(expected_values)
            for f in after
            if isinstance(f.get("value"), list)
        )
        assert matched, f"Expected filter values {expected_values} in {after}"

    def test_value_filter_path_is_query_filters(self, svc, report, sm):
        result = svc.propose("only show PHOTO", report, "line_queue_by_day", semantic_model=sm)
        assert result.proposal.changes[0].path.endswith("/query/filters")

    def test_value_filter_roundtrip(self, svc, report, sm):
        result = svc.propose("only show PHOTO", report, "line_queue_by_day", semantic_model=sm)
        updated = apply_report_proposal(report, result.proposal)
        filters = updated.pages["main"].visuals["line_queue_by_day"].query.filters
        step_filters = [f for f in filters if f.column_name == "step_id"]
        assert any(set(f.value) == {"PHOTO"} for f in step_filters)

    def test_value_filter_risk_medium(self, svc, report, sm):
        result = svc.propose("only show PHOTO", report, "line_queue_by_day")
        if result.proposal:
            assert result.risk_level == "medium"


# ===========================================================================
# model path tests for query/filters
# ===========================================================================

class TestQueryFiltersPath:

    def test_get_query_filters_path(self, report):
        from ai4bi.report.models import _get_path
        vid = "line_queue_by_day"
        path = f"pages/main/visuals/{vid}/query/filters"
        filters = _get_path(report, path)
        assert isinstance(filters, list)

    def test_set_query_filters_path(self, report):
        from ai4bi.report.models import _get_path, _set_path
        vid = "line_queue_by_day"
        path = f"pages/main/visuals/{vid}/query/filters"
        new_filters = [
            {"block_id": "process_move_fact", "column_name": "step_id",
             "operator": "in", "value": ["PHOTO"], "inherit_global_filter": False}
        ]
        _set_path(report, path, new_filters)
        result = _get_path(report, path)
        assert len(result) >= 1
        added = next(f for f in result if f["column_name"] == "step_id" and f["value"] == ["PHOTO"])
        assert added is not None
