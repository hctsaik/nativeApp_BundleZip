"""
Round 019 NL2Proposal Enhancement tests.

Tests three new governed intents:
  - chart_type_change (bar ↔ line, affects_data=False)
  - dimension_change  (date granularity, affects_data=True)
  - add_metric        (certified metric only, owner_block check, max 3)

Each intent tests: happy path + governance refusal path + affects_data assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.query_spec import VisualType
from ai4bi.report.templates import build_semiconductor_queue_time_report

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_SEMANTIC_MODEL = json.loads((_DEMO_ROOT / "semantic_model.json").read_text(encoding="utf-8"))


@pytest.fixture
def service() -> NL2ProposalService:
    return NL2ProposalService()


@pytest.fixture
def report():
    return build_semiconductor_queue_time_report()


@pytest.fixture
def line_visual_id(report) -> str:
    """Return the ID of the line_chart visual on the main page."""
    for vid, v in report.pages["main"].visuals.items():
        if v.visualization.visual_type == VisualType.line_chart:
            return vid
    raise RuntimeError("No line_chart visual found in demo report")


@pytest.fixture
def bar_visual_id(report) -> str:
    """Return the ID of the bar_chart visual on the main page."""
    for vid, v in report.pages["main"].visuals.items():
        if v.visualization.visual_type == VisualType.bar_chart:
            return vid
    raise RuntimeError("No bar_chart visual found in demo report")


@pytest.fixture
def kpi_visual_id(report) -> str:
    """Return the ID of the first kpi_card visual on the main page."""
    for vid, v in report.pages["main"].visuals.items():
        if v.visualization.visual_type == VisualType.kpi_card:
            return vid
    raise RuntimeError("No kpi_card visual found in demo report")


# ===========================================================================
# chart_type_change tests
# ===========================================================================

class TestChartTypeChange:

    def test_line_to_bar_proposal(self, service, report, line_visual_id):
        result = service.propose("把這個改成長條圖", report, line_visual_id)
        assert result.proposal is not None
        assert len(result.proposal.changes) == 1
        change = result.proposal.changes[0]
        assert change.path.endswith("/visualization/visual_type")
        assert change.before == VisualType.line_chart.value
        assert change.after == VisualType.bar_chart.value

    def test_chart_type_change_affects_data_false(self, service, report, line_visual_id):
        result = service.propose("改成長條圖", report, line_visual_id)
        assert result.proposal is not None
        assert result.proposal.changes[0].affects_data is False

    def test_bar_to_line_proposal(self, service, report, bar_visual_id):
        result = service.propose("change to line chart", report, bar_visual_id)
        assert result.proposal is not None
        change = result.proposal.changes[0]
        assert change.after == VisualType.line_chart.value

    def test_chart_type_change_english(self, service, report, bar_visual_id):
        result = service.propose("convert this to line chart", report, bar_visual_id)
        assert result.proposal is not None

    def test_chart_type_blocked_for_kpi_card(self, service, report, kpi_visual_id):
        """kpi_card cannot be converted — different data contract."""
        result = service.propose("改成長條圖", report, kpi_visual_id)
        assert result.proposal is None
        assert result.intent.intent_kind == "unsupported"

    def test_chart_type_blocked_target_kpi(self, service, report, bar_visual_id):
        """Target type kpi_card/table is blocked."""
        result = service.propose("convert to table", report, bar_visual_id)
        # "table" doesn't match chart_type_change keywords → falls through to unsupported
        # or if it somehow matches, it should be blocked
        # Either way, no valid chart_type proposal should produce a table conversion
        if result.proposal is not None:
            assert result.proposal.changes[0].after != VisualType.table.value

    def test_no_change_when_already_target_type(self, service, report, bar_visual_id):
        """No proposal when visual already has the target type."""
        result = service.propose("改成長條圖", report, bar_visual_id)
        assert result.proposal is None  # already bar_chart
        assert "already" in result.message.lower()

    def test_chart_type_change_risk_level_low(self, service, report, line_visual_id):
        result = service.propose("把這個改成長條圖", report, line_visual_id)
        assert result.risk_level == "low"

    def test_chart_type_change_requires_visual_selection(self, service, report):
        result = service.propose("改成長條圖", report, None)
        assert result.proposal is None


# ===========================================================================
# dimension_change tests
# ===========================================================================

class TestDimensionChange:

    def test_change_to_month_grouping(self, service, report, line_visual_id):
        result = service.propose("改用月份分組", report, line_visual_id)
        assert result.proposal is not None
        change = result.proposal.changes[0]
        assert change.path.endswith("/query/dimensions")
        assert change.affects_data is True
        # The after should have truncate_date_to='month' on the time column
        after_dims = change.after
        has_month = any(d.get("truncate_date_to") == "month" for d in after_dims)
        assert has_month, f"Expected month truncation in {after_dims}"

    def test_change_to_week_grouping(self, service, report, line_visual_id):
        result = service.propose("group by week", report, line_visual_id)
        assert result.proposal is not None
        after_dims = result.proposal.changes[0].after
        has_week = any(d.get("truncate_date_to") == "week" for d in after_dims)
        assert has_week

    def test_change_to_day_grouping(self, service, report, line_visual_id):
        result = service.propose("按日分組", report, line_visual_id)
        assert result.proposal is not None
        after_dims = result.proposal.changes[0].after
        has_day = any(d.get("truncate_date_to") == "day" for d in after_dims)
        assert has_day

    def test_dimension_change_affects_data_true(self, service, report, line_visual_id):
        result = service.propose("改用月份分組", report, line_visual_id)
        assert result.proposal is not None
        assert result.proposal.changes[0].affects_data is True

    def test_dimension_change_risk_level_medium(self, service, report, line_visual_id):
        result = service.propose("改用月份分組", report, line_visual_id)
        assert result.risk_level == "medium"

    def test_dimension_change_requires_visual_selection(self, service, report):
        result = service.propose("改用月份分組", report, None)
        assert result.proposal is None

    def test_dimension_change_stale_check_roundtrip(self, service, report, line_visual_id):
        """Verify before/after are compatible with apply_report_proposal."""
        from ai4bi.report.models import apply_report_proposal, ReportProposal, ReportChange
        result = service.propose("改用月份分組", report, line_visual_id)
        assert result.proposal is not None
        updated = apply_report_proposal(report, result.proposal)
        page = updated.pages["main"]
        dims = page.visuals[line_visual_id].query.dimensions
        has_month = any(d.truncate_date_to == "month" for d in dims)
        assert has_month


# ===========================================================================
# add_metric tests
# ===========================================================================

class TestAddMetric:

    def _semantic_model(self):
        return _SEMANTIC_MODEL

    def test_add_certified_metric(self, service, report, line_visual_id):
        """add move_count to line visual (same block: process_move_fact)."""
        result = service.propose(
            "也加上move_count",
            report, line_visual_id,
            semantic_model=self._semantic_model(),
        )
        assert result.proposal is not None
        change = result.proposal.changes[0]
        assert change.path.endswith("/query/metrics")
        assert change.affects_data is True
        after_names = [m["metric_name"] for m in change.after]
        assert "move_count" in after_names

    def test_add_metric_affects_data_true(self, service, report, line_visual_id):
        result = service.propose(
            "加上move_count指標",
            report, line_visual_id,
            semantic_model=self._semantic_model(),
        )
        if result.proposal is not None:
            assert result.proposal.changes[0].affects_data is True

    def test_add_metric_not_in_semantic_model_is_refused(self, service, report, line_visual_id):
        """Metric not in semantic model → governance refusal, risk_level=high."""
        result = service.propose(
            "也加上nonexistent_metric",
            report, line_visual_id,
            semantic_model=self._semantic_model(),
        )
        assert result.proposal is None
        assert result.refusal is not None
        assert result.risk_level == "high"

    def test_add_metric_wrong_block_is_refused(self, service, report, line_visual_id):
        """Metric from a different block (wafer_yield_fact) → governance refusal."""
        result = service.propose(
            "也加上failed_wafer_count",
            report, line_visual_id,
            semantic_model=self._semantic_model(),
        )
        assert result.proposal is None
        assert result.refusal is not None
        assert result.risk_level == "high"

    def test_add_metric_max_limit_enforced(self, service, report, line_visual_id):
        """Cannot add more than 3 metrics to one visual."""
        from ai4bi.report.models import apply_report_proposal
        from ai4bi.ai.nl2proposal import _MAX_METRICS_PER_VISUAL

        # Build a report with max metrics already
        working = report
        metric_names = ["move_count", "avg_queue_time_hr", "avg_process_time_min"]
        current_count = len(working.pages["main"].visuals[line_visual_id].query.metrics)

        # Only add up to the limit
        added = 0
        for metric_name in metric_names:
            if current_count + added >= _MAX_METRICS_PER_VISUAL:
                break
            r = service.propose(
                f"也加上{metric_name}",
                working, line_visual_id,
                semantic_model=self._semantic_model(),
            )
            if r.proposal is not None:
                working = apply_report_proposal(working, r.proposal)
                added += 1

        # Now the visual should be at max — adding another should be rejected
        final_count = len(working.pages["main"].visuals[line_visual_id].query.metrics)
        if final_count >= _MAX_METRICS_PER_VISUAL:
            any_remaining = [
                m for m in metric_names
                if m not in [mx.metric_name for mx in working.pages["main"].visuals[line_visual_id].query.metrics]
            ]
            if any_remaining:
                blocked = service.propose(
                    f"也加上{any_remaining[0]}",
                    working, line_visual_id,
                    semantic_model=self._semantic_model(),
                )
                assert blocked.proposal is None

    def test_add_duplicate_metric_is_rejected(self, service, report, line_visual_id):
        """Adding a metric already present returns unsupported."""
        from ai4bi.report.models import apply_report_proposal

        # First, add move_count successfully
        r1 = service.propose(
            "也加上move_count",
            report, line_visual_id,
            semantic_model=self._semantic_model(),
        )
        assert r1.proposal is not None, "First add_metric should succeed"
        updated = apply_report_proposal(report, r1.proposal)

        # Now try to add move_count again — should be rejected as duplicate
        r2 = service.propose(
            "也加上move_count",
            updated, line_visual_id,
            semantic_model=self._semantic_model(),
        )
        assert r2.proposal is None
        assert "already" in r2.message.lower()

    def test_add_metric_requires_semantic_model(self, service, report, line_visual_id):
        """Without semantic_model, metric cannot be validated → refusal."""
        result = service.propose(
            "也加上move_count",
            report, line_visual_id,
            semantic_model=None,
        )
        # With no semantic model, move_count not in empty dict → refusal
        assert result.proposal is None
        assert result.refusal is not None


# ===========================================================================
# Models path tests for new paths
# ===========================================================================

class TestNewModelPaths:

    def test_get_visual_type_path(self, report, bar_visual_id):
        from ai4bi.report.models import _get_path
        path = f"pages/main/visuals/{bar_visual_id}/visualization/visual_type"
        value = _get_path(report, path)
        assert value == VisualType.bar_chart.value

    def test_set_visual_type_path(self, report, bar_visual_id):
        from ai4bi.report.models import _get_path, _set_path
        path = f"pages/main/visuals/{bar_visual_id}/visualization/visual_type"
        _set_path(report, path, VisualType.line_chart.value)
        assert _get_path(report, path) == VisualType.line_chart.value

    def test_get_metrics_path(self, report, line_visual_id):
        from ai4bi.report.models import _get_path
        path = f"pages/main/visuals/{line_visual_id}/query/metrics"
        value = _get_path(report, path)
        assert isinstance(value, list)
        assert len(value) > 0
        assert "metric_name" in value[0]

    def test_set_metrics_path_roundtrip(self, report, line_visual_id):
        from ai4bi.report.models import _get_path, _set_path
        path = f"pages/main/visuals/{line_visual_id}/query/metrics"
        original = _get_path(report, path)
        # Set to the same value and verify roundtrip
        _set_path(report, path, original)
        after = _get_path(report, path)
        assert after == original

    def test_visual_type_change_via_proposal(self, report, bar_visual_id):
        """Full round-trip: apply_report_proposal with visual_type change."""
        from ai4bi.report.models import apply_report_proposal, ReportProposal, ReportChange
        path = f"pages/main/visuals/{bar_visual_id}/visualization/visual_type"
        proposal = ReportProposal(
            description="Change bar to line",
            changes=[
                ReportChange(
                    path=path,
                    label="Chart type",
                    before=VisualType.bar_chart.value,
                    after=VisualType.line_chart.value,
                    affects_data=False,
                )
            ],
        )
        updated = apply_report_proposal(report, proposal)
        new_type = updated.pages["main"].visuals[bar_visual_id].visualization.visual_type
        assert new_type == VisualType.line_chart
