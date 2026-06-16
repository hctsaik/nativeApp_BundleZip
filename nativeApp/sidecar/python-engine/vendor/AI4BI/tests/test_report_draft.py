from __future__ import annotations

from pathlib import Path

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.report.models import (
    DraftReportStore,
    ExecutableReportSpec,
    ReportChange,
    ReportProposal,
    ReportValidationError,
    apply_report_proposal,
    query_to_dict,
)
from ai4bi.report.proposals import controls_to_proposal, prompt_to_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report


DATA_DIR = Path(__file__).parent.parent / "data" / "semiconductor_demo"


def test_executable_report_round_trip_preserves_safe_join_and_style():
    report = build_semiconductor_queue_time_report()
    line = report.pages["main"].visuals["line_queue_by_day"]
    line.visualization.extra["line_color"] = "#D62728"

    restored = ExecutableReportSpec.from_dict(report.to_dict())
    bar = restored.pages["main"].visuals["bar_queue_by_tool_dimension"]
    result = Executor(registry_root=DATA_DIR / "blocks").run(
        bar.query, restored.active_filters()
    )

    assert bar.query.dimensions[0].block_id == "tool_dim"
    assert line.query.metrics[0].agg_override.value == "AVG"
    assert restored.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] == "#D62728"
    assert dict(zip(result["Tool ID"], result["Average Queue Time"])) == pytest.approx(
        {"ETCH-01": 2.0, "ETCH-02": 4.0}
    )


def test_style_prompt_is_previewable_and_does_not_modify_query_semantics():
    report = build_semiconductor_queue_time_report()
    before_query = query_to_dict(report.pages["main"].visuals["line_queue_by_day"].query)
    result = prompt_to_proposal("把趨勢線改成紅色", report, "line_queue_by_day")

    assert result.proposal is not None
    assert result.proposal.affects_data is False
    assert report.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] is None

    changed = apply_report_proposal(report, result.proposal)

    assert changed.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] == "#D62728"
    assert query_to_dict(changed.pages["main"].visuals["line_queue_by_day"].query) == before_query


def test_analysis_prompt_changes_result_only_after_proposal_is_applied():
    report = build_semiconductor_queue_time_report()
    result = prompt_to_proposal("只看 Logic-B", report, "line_queue_by_day")

    assert result.proposal is not None
    assert result.proposal.affects_data is True
    assert report.active_filters()["process_move_fact.product_family"] == ["Logic-A", "Logic-B"]

    changed = apply_report_proposal(report, result.proposal)

    assert changed.active_filters()["process_move_fact.product_family"] == ["Logic-B"]


def test_breakdown_control_updates_executable_dimension_atomically():
    report = build_semiconductor_queue_time_report()
    proposal = controls_to_proposal(
        report,
        steps=["ETCH"],
        products=["Logic-A", "Logic-B"],
        breakdown="Vendor",
    )

    assert proposal is not None
    changed = apply_report_proposal(report, proposal)
    bar = changed.pages["main"].visuals["bar_queue_by_tool_dimension"]

    assert changed.controls["breakdown"].value == "Vendor"
    assert bar.query.dimensions[0].column_name == "vendor"
    assert bar.visualization.title == "Queue Time by Vendor"


def test_stale_or_invalid_proposal_is_atomic():
    report = build_semiconductor_queue_time_report()
    proposal = ReportProposal(
        "stale proposal",
        [
            ReportChange(
                "controls/process_step/value",
                "Process step",
                ["PHOTO"],
                ["CVD"],
                True,
            ),
            ReportChange("unsupported/path", "Unsafe", None, "bad", False),
        ],
    )

    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)

    assert report.controls["process_step"].value == ["ETCH"]
    assert report.revision == 0


def test_local_draft_store_round_trip_is_explicitly_non_published(tmp_path):
    report = build_semiconductor_queue_time_report()
    changed = apply_report_proposal(
        report,
        prompt_to_proposal("make trend line red", report, "line_queue_by_day").proposal,
    )
    store = DraftReportStore(tmp_path)

    path = store.save(changed)
    restored = store.load(path)

    assert restored.status == "validated_demo_draft"
    assert restored.saved_at is not None
    assert restored.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] == "#D62728"
