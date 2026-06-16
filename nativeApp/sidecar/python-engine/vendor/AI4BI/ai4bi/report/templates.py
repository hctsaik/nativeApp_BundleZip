"""Starter report artifacts for locally governed demos."""

from __future__ import annotations

import os

from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    SortDirection,
    SortSpec,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)
from ai4bi.report.models import (
    AuditMetadata,
    ControlSpec,
    ExecutableReportSpec,
    ReportPageSpec,
    ReportVisualSpec,
)

_PRODUCT_FAMILIES = ["Logic-A", "Logic-B"]
_PROCESS_STEPS = ["PHOTO", "ETCH", "CVD"]


def _global_filters() -> list[FilterSpec]:
    return [
        FilterSpec(
            block_id="process_move_fact",
            column_name="step_id",
            operator=FilterOperator.in_,
            value=["ETCH"],
            inherit_global_filter=True,
        ),
        FilterSpec(
            block_id="process_move_fact",
            column_name="product_family",
            operator=FilterOperator.in_,
            value=list(_PRODUCT_FAMILIES),
            inherit_global_filter=True,
        ),
    ]


def build_semiconductor_queue_time_report() -> ExecutableReportSpec:
    """Return the editable draft used by the semiconductor report canvas."""
    move = BlockRef("process_move_fact")
    tool = BlockRef("tool_dim")
    visuals = {
        "kpi_move_count": ReportVisualSpec(
            "kpi_move_count",
            VisualQuerySpec(
                "kpi_move_count",
                [move],
                metrics=[MetricRef("process_move_fact", "move_count", "Moves")],
                filters=_global_filters(),
                inherit_global_filter=True,
            ),
            VisualizationSpec(VisualType.kpi_card, title="Processed Moves", extra={"unit": "moves"}),
        ),
        "kpi_avg_queue": ReportVisualSpec(
            "kpi_avg_queue",
            VisualQuerySpec(
                "kpi_avg_queue",
                [move],
                metrics=[
                    MetricRef("process_move_fact", "queue_time_hr", "Average Queue Time", AggFunction.avg)
                ],
                filters=_global_filters(),
                inherit_global_filter=True,
            ),
            VisualizationSpec(VisualType.kpi_card, title="Average Queue Time", extra={"unit": "hr"}),
        ),
        "line_queue_by_day": ReportVisualSpec(
            "line_queue_by_day",
            VisualQuerySpec(
                "line_queue_by_day",
                [move],
                metrics=[
                    MetricRef("process_move_fact", "queue_time_hr", "Average Queue Time", AggFunction.avg)
                ],
                dimensions=[DimensionRef("process_move_fact", "event_date", "Date")],
                filters=_global_filters(),
                sort=[SortSpec("Date", SortDirection.asc)],
                inherit_global_filter=True,
                cross_filter_emit=DimensionRef("process_move_fact", "event_date", "Date"),
            ),
            VisualizationSpec(
                VisualType.line_chart,
                title="Queue-Time Trend",
                x_axis_label="Date",
                y_axis_label="Average Queue Time (hr)",
                height_px=340,
                extra={"line_color": None},
            ),
        ),
        "bar_queue_by_tool_dimension": ReportVisualSpec(
            "bar_queue_by_tool_dimension",
            VisualQuerySpec(
                "bar_queue_by_tool_dimension",
                [move, tool],
                metrics=[
                    MetricRef("process_move_fact", "queue_time_hr", "Average Queue Time", AggFunction.avg)
                ],
                dimensions=[DimensionRef("tool_dim", "tool_id", "Tool ID")],
                filters=_global_filters(),
                sort=[SortSpec("Average Queue Time", SortDirection.desc)],
                inherit_global_filter=True,
                cross_filter_emit=DimensionRef("tool_dim", "tool_id", "Tool ID"),
            ),
            VisualizationSpec(
                VisualType.bar_chart,
                title="Queue Time by Tool ID",
                x_axis_label="Tool ID",
                y_axis_label="Average Queue Time (hr)",
                height_px=340,
            ),
        ),
        "table_queue_by_tool_dimension": ReportVisualSpec(
            "table_queue_by_tool_dimension",
            VisualQuerySpec(
                "table_queue_by_tool_dimension",
                [move, tool],
                metrics=[
                    MetricRef("process_move_fact", "move_count", "Moves"),
                    MetricRef("process_move_fact", "queue_time_hr", "Average Queue Time", AggFunction.avg),
                ],
                dimensions=[
                    DimensionRef("tool_dim", "tool_id", "Tool ID"),
                    DimensionRef("tool_dim", "vendor", "Vendor"),
                ],
                filters=_global_filters(),
                sort=[SortSpec("Average Queue Time", SortDirection.desc)],
                inherit_global_filter=True,
            ),
            VisualizationSpec(VisualType.table, title="Certified Path Tool Breakdown", height_px=250),
        ),
    }
    report = ExecutableReportSpec(
        audit=AuditMetadata(
            report_id="semiconductor_queue_time_v1",
            created_by=os.environ.get("ANALYST_NAME", "unknown"),
        ),
        title="ETCH Queue-Time Explorer",
        semantic_model_ref="semiconductor_process_demo@1.0.0",
        status="validated_demo_draft",
        pages={
            "main": ReportPageSpec(
                "main",
                "Queue Time Overview",
                visuals,
                [
                    "kpi_move_count",
                    "kpi_avg_queue",
                    "line_queue_by_day",
                    "bar_queue_by_tool_dimension",
                    "table_queue_by_tool_dimension",
                ],
                display_name="ETCH Queue-Time",
            )
        },
        controls={
            "process_step": ControlSpec(
                "process_step",
                "Process step",
                ["ETCH"],
                _PROCESS_STEPS,
                "process_move_fact.step_id",
            ),
            "product_family": ControlSpec(
                "product_family",
                "Product family",
                list(_PRODUCT_FAMILIES),
                _PRODUCT_FAMILIES,
                "process_move_fact.product_family",
            ),
            "breakdown": ControlSpec("breakdown", "Comparison breakdown", "Tool ID", ["Tool ID", "Vendor"]),
        },
    )
    report.validate()
    return report
