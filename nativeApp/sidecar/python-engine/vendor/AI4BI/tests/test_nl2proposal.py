from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai4bi.ai import NL2ProposalService
from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.blocks.loader import BlockLoader
from ai4bi.report.models import apply_report_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"
_SEMANTIC_MODEL_PATH = _DEMO_ROOT / "semantic_model.json"


@pytest.fixture
def service() -> NL2ProposalService:
    return NL2ProposalService()


@pytest.fixture
def semantic_model() -> dict:
    return json.loads(_SEMANTIC_MODEL_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def contracts() -> dict[str, DataBlockContract]:
    loader = BlockLoader()
    result: dict[str, DataBlockContract] = {}
    for path in _BLOCKS_DIR.glob("*.json"):
        contract = loader.load_json(str(path))
        result[contract.block_id] = contract
    return result


def test_generic_line_style_change_targets_any_selected_line_chart(service: NL2ProposalService):
    report = build_semiconductor_queue_time_report()
    copied = copy.deepcopy(report.pages["main"].visuals["line_queue_by_day"])
    copied.component_id = "line_queue_by_day_copy"
    copied.query.spec_id = "line_queue_by_day_copy"
    report.pages["main"].add_visual("line_queue_by_day_copy", copied)

    result = service.propose("make this line chart red", report, "line_queue_by_day_copy")

    assert result.intent.intent_kind == "style_change"
    assert result.proposal is not None
    assert result.proposal.affects_data is False
    assert result.proposal.target_component_id == "line_queue_by_day_copy"
    assert result.proposal.changes[0].path == (
        "pages/main/visuals/line_queue_by_day_copy/visualization/extra/line_color"
    )

    changed = apply_report_proposal(report, result.proposal)

    assert changed.pages["main"].visuals["line_queue_by_day_copy"].visualization.extra["line_color"] == "#D62728"
    assert changed.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] is None


def test_bar_chart_style_supported_and_kpi_style_explains_unsupported(service: NL2ProposalService):
    report = build_semiconductor_queue_time_report()

    bar_result = service.propose("make this bar chart green", report, "bar_queue_by_tool_dimension")

    assert bar_result.intent.intent_kind == "style_change"
    assert bar_result.proposal is not None
    assert bar_result.proposal.changes[0].path == (
        "pages/main/visuals/bar_queue_by_tool_dimension/visualization/extra/bar_color"
    )
    assert bar_result.proposal.changes[0].after == "#2CA02C"
    assert bar_result.trust_notes == bar_result.intent.trust_notes

    changed = apply_report_proposal(report, bar_result.proposal)

    assert changed.pages["main"].visuals["bar_queue_by_tool_dimension"].visualization.extra["bar_color"] == "#2CA02C"

    kpi_result = service.propose("make this chart green", report, "kpi_avg_queue")

    assert kpi_result.intent.intent_kind == "unsupported"
    assert kpi_result.proposal is None
    assert "line and bar charts" in kpi_result.message
    assert kpi_result.intent.selection.metric_name == "queue_time_hr"


def test_unsupported_sql_and_detail_join_requests_return_governance_refusal(
    service: NL2ProposalService,
    semantic_model: dict,
):
    report = build_semiconductor_queue_time_report()

    result = service.propose(
        "write SQL to join raw queue moves to wafer yield detail rows",
        report,
        "line_queue_by_day",
        semantic_model=semantic_model,
    )

    assert result.intent.intent_kind == "unsupported"
    assert result.proposal is None
    assert result.refusal is not None
    assert result.is_refusal is True
    assert result.risk_level == "high"
    assert {"sql", "join", "yield", "detail", "raw"}.issubset(set(result.refusal.blocked_terms))
    assert "cannot be staged" in result.message


def test_queue_time_analysis_request_returns_plan_without_sql(
    service: NL2ProposalService,
    semantic_model: dict,
    contracts: dict[str, DataBlockContract],
):
    report = build_semiconductor_queue_time_report()

    result = service.propose(
        "analyze queue time drivers by tool",
        report,
        "line_queue_by_day",
        semantic_model=semantic_model,
        contracts=contracts,
    )

    assert result.intent.intent_kind == "analysis_request"
    assert result.proposal is None
    assert result.refusal is None
    assert result.analysis_plan is not None
    assert result.analysis_plan.generated_sql is None
    assert result.analysis_plan.selection.metric_name == "queue_time_hr"
    assert "line_queue_by_day" in result.analysis_plan.suggested_visuals
    assert any("no SQL" in note for note in result.analysis_plan.trust_notes)
