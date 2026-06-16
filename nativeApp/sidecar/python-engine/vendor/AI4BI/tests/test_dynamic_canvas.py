"""Tests for Round 014-A: Dynamic Canvas — visual_order and add_visual proposal."""

from __future__ import annotations

import pytest

from ai4bi.query_spec import (
    BlockRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)
from ai4bi.report.builder import build_add_visual_proposal
from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportChange,
    ReportProposal,
    ReportValidationError,
    ReportVisualSpec,
    apply_report_proposal,
)
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kpi_visual(visual_id: str, block_id: str = "process_move_fact") -> ReportVisualSpec:
    """Build a minimal kpi_card ReportVisualSpec for test use."""
    return ReportVisualSpec(
        component_id=visual_id,
        query=VisualQuerySpec(
            spec_id=visual_id,
            block_refs=[BlockRef(block_id=block_id)],
            metrics=[MetricRef(block_id=block_id, metric_name="move_count")],
        ),
        visualization=VisualizationSpec(
            visual_type=VisualType.kpi_card,
            title=f"Test {visual_id}",
        ),
    )


# ---------------------------------------------------------------------------
# Test 1 — visual_order defaults to same order as visuals.keys() in template
# ---------------------------------------------------------------------------

def test_visual_order_matches_visuals_keys_in_template():
    """visual_order must equal list(visuals.keys()) from build_semiconductor_queue_time_report."""
    report = build_semiconductor_queue_time_report()
    page = report.pages["main"]
    assert page.visual_order == list(page.visuals.keys())


# ---------------------------------------------------------------------------
# Test 2 — add_visual() appends to visual_order
# ---------------------------------------------------------------------------

def test_add_visual_appends_to_visual_order():
    report = build_semiconductor_queue_time_report()
    page = report.pages["main"]
    original_len = len(page.visual_order)
    new_visual = _make_kpi_visual("test_new_kpi")
    page.add_visual("test_new_kpi", new_visual)

    assert "test_new_kpi" in page.visual_order
    assert page.visual_order[-1] == "test_new_kpi"
    assert len(page.visual_order) == original_len + 1
    assert "test_new_kpi" in page.visuals


# ---------------------------------------------------------------------------
# Test 3 — to_dict() / from_dict() round-trip preserves visual_order
# ---------------------------------------------------------------------------

def test_to_dict_from_dict_round_trip_preserves_visual_order():
    report = build_semiconductor_queue_time_report()
    page = report.pages["main"]
    page.add_visual("extra_kpi", _make_kpi_visual("extra_kpi"))
    expected_order = list(page.visual_order)

    restored = ExecutableReportSpec.from_dict(report.to_dict())
    restored_page = restored.pages["main"]

    assert restored_page.visual_order == expected_order
    assert list(restored_page.visuals.keys()) == list(page.visuals.keys())


# ---------------------------------------------------------------------------
# Test 4 — build_add_visual_proposal() returns proposal with affects_data=True
# ---------------------------------------------------------------------------

def test_build_add_visual_proposal_has_affects_data_true():
    query_spec = VisualQuerySpec(
        spec_id="new_kpi",
        block_refs=[BlockRef("process_move_fact")],
        metrics=[MetricRef("process_move_fact", "move_count")],
    )
    viz_spec = VisualizationSpec(visual_type=VisualType.kpi_card, title="New KPI")

    proposal = build_add_visual_proposal(
        page_id="main",
        visual_id="new_kpi",
        query_spec=query_spec,
        viz_spec=viz_spec,
    )

    assert proposal.affects_data is True
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.path == "pages/main/add_visual"
    assert change.before is None
    assert change.affects_data is True
    assert change.after["visual_id"] == "new_kpi"
    assert "kpi_card" in change.label


# ---------------------------------------------------------------------------
# Test 5 — applying the add-visual proposal increments visual_order
# ---------------------------------------------------------------------------

def test_apply_add_visual_proposal_adds_to_visual_order():
    report = build_semiconductor_queue_time_report()
    original_order = list(report.pages["main"].visual_order)

    query_spec = VisualQuerySpec(
        spec_id="applied_kpi",
        block_refs=[BlockRef("process_move_fact")],
        metrics=[MetricRef("process_move_fact", "move_count")],
    )
    viz_spec = VisualizationSpec(visual_type=VisualType.kpi_card, title="Applied KPI")

    proposal = build_add_visual_proposal(
        page_id="main",
        visual_id="applied_kpi",
        query_spec=query_spec,
        viz_spec=viz_spec,
    )

    updated = apply_report_proposal(report, proposal)

    assert "applied_kpi" in updated.pages["main"].visual_order
    assert updated.pages["main"].visual_order == original_order + ["applied_kpi"]
    assert updated.pages["main"].visuals["applied_kpi"].visualization.title == "Applied KPI"
    assert updated.revision == report.revision + 1
    # Original report must be unchanged (atomicity).
    assert "applied_kpi" not in report.pages["main"].visual_order


# ---------------------------------------------------------------------------
# Test 6 — filter inheritance: new visual's filters contain matching entries
# ---------------------------------------------------------------------------

def test_filter_inheritance_carries_active_filters():
    """Filters whose key starts with the selected block_id must be copied into the
    new visual's VisualQuerySpec.filters."""
    report = build_semiconductor_queue_time_report()

    # Active filters from the template include process_move_fact.step_id and
    # process_move_fact.product_family.
    active = report.active_filters()
    selected_block_id = "process_move_fact"

    inherited_filters: list[FilterSpec] = []
    for filter_key, filter_value in active.items():
        key_block_id = filter_key.split(".")[0] if "." in filter_key else ""
        if key_block_id == selected_block_id:
            col_name = filter_key.split(".", 1)[1] if "." in filter_key else filter_key
            inherited_filters.append(
                FilterSpec(
                    block_id=key_block_id,
                    column_name=col_name,
                    operator=FilterOperator.in_,
                    value=filter_value if isinstance(filter_value, list) else [filter_value],
                    inherit_global_filter=True,
                )
            )

    assert len(inherited_filters) >= 1, "Expected at least one active filter for process_move_fact"

    from dataclasses import replace
    query_spec = VisualQuerySpec(
        spec_id="filtered_kpi",
        block_refs=[BlockRef(selected_block_id)],
        metrics=[MetricRef(selected_block_id, "move_count")],
        filters=inherited_filters,
    )
    viz_spec = VisualizationSpec(visual_type=VisualType.kpi_card, title="Filtered KPI")
    query_spec = replace(query_spec, filters=inherited_filters)

    proposal = build_add_visual_proposal(
        page_id="main",
        visual_id="filtered_kpi",
        query_spec=query_spec,
        viz_spec=viz_spec,
    )

    updated = apply_report_proposal(report, proposal)
    new_visual = updated.pages["main"].visuals["filtered_kpi"]
    new_filter_cols = {f.column_name for f in new_visual.query.filters}

    # Verify the filters that were inherited are present on the new visual.
    for fs in inherited_filters:
        assert fs.column_name in new_filter_cols


# ---------------------------------------------------------------------------
# Test 7 — stale proposal atomicity: add_visual + invalid path rejects completely
# ---------------------------------------------------------------------------

def test_stale_proposal_with_add_visual_is_atomic():
    """If any change in a multi-change proposal fails, the whole thing rolls back."""
    report = build_semiconductor_queue_time_report()
    original_order = list(report.pages["main"].visual_order)
    original_revision = report.revision

    query_spec = VisualQuerySpec(
        spec_id="atomic_kpi",
        block_refs=[BlockRef("process_move_fact")],
        metrics=[MetricRef("process_move_fact", "move_count")],
    )
    viz_spec = VisualizationSpec(visual_type=VisualType.kpi_card, title="Atomic KPI")

    proposal = ReportProposal(
        description="Mixed valid+invalid proposal",
        changes=[
            ReportChange(
                path="pages/main/add_visual",
                label="Add kpi_card visual",
                before=None,
                after={
                    "visual_id": "atomic_kpi",
                    "visual": ReportVisualSpec(
                        component_id="atomic_kpi",
                        query=query_spec,
                        visualization=viz_spec,
                    ).to_dict(),
                },
                affects_data=True,
            ),
            # This second change uses an unsupported path that must cause a failure.
            ReportChange(
                path="invalid/nonexistent/path",
                label="Bad path",
                before=None,
                after="bad_value",
                affects_data=False,
            ),
        ],
    )

    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)

    # Original report must be completely unchanged.
    assert report.pages["main"].visual_order == original_order
    assert "atomic_kpi" not in report.pages["main"].visuals
    assert report.revision == original_revision


# ---------------------------------------------------------------------------
# Test 8 — adding a visual that already exists raises ReportValidationError
# ---------------------------------------------------------------------------

def test_add_visual_duplicate_id_raises_validation_error():
    report = build_semiconductor_queue_time_report()
    page = report.pages["main"]

    # "kpi_move_count" already exists in the template.
    duplicate_visual = _make_kpi_visual("kpi_move_count")

    with pytest.raises(ReportValidationError, match="kpi_move_count"):
        page.add_visual("kpi_move_count", duplicate_visual)


# ---------------------------------------------------------------------------
# Bonus: applying add_visual for duplicate via proposal also raises
# ---------------------------------------------------------------------------

def test_apply_add_visual_proposal_duplicate_raises_validation_error():
    report = build_semiconductor_queue_time_report()

    query_spec = VisualQuerySpec(
        spec_id="kpi_move_count",  # duplicate id
        block_refs=[BlockRef("process_move_fact")],
        metrics=[MetricRef("process_move_fact", "move_count")],
    )
    viz_spec = VisualizationSpec(visual_type=VisualType.kpi_card, title="Dup KPI")

    proposal = build_add_visual_proposal(
        page_id="main",
        visual_id="kpi_move_count",  # already exists
        query_spec=query_spec,
        viz_spec=viz_spec,
    )

    with pytest.raises(ReportValidationError):
        apply_report_proposal(report, proposal)

    # Report must be unchanged.
    assert report.revision == 0
