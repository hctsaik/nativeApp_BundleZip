"""Auto-generate a starter ExecutableReportSpec from a user-uploaded block.

Round 028: Self-Serve Data Import.

Given a DataBlockContract plus lists of inferred metric/dimension column names,
builds a minimal report with:
  - One KPI card per metric (up to 3)
  - One bar chart (first metric × first dimension, if both exist)
  - One table showing all inferred metrics and dimensions (up to 3 each)

The report uses no global filters and no joins (single-block queries only).
"""

from __future__ import annotations

import os
import uuid

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    MetricRef,
    SortDirection,
    SortSpec,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)
from ai4bi.report.models import (
    AuditMetadata,
    ExecutableReportSpec,
    ReportPageSpec,
    ReportVisualSpec,
)


def build_report_from_block(
    contract: DataBlockContract,
    metric_names: list[str],
    dim_names: list[str],
) -> ExecutableReportSpec:
    """Return an auto-generated starter report for an uploaded data block."""
    bid = contract.block_id
    block_ref = BlockRef(bid)

    visuals: dict[str, ReportVisualSpec] = {}
    visual_order: list[str] = []

    # KPI cards — first 3 metrics
    for i, metric in enumerate(metric_names[:3]):
        vid = f"kpi_{_slugify(metric)}_{i}"
        visuals[vid] = ReportVisualSpec(
            vid,
            VisualQuerySpec(
                vid,
                [block_ref],
                metrics=[MetricRef(bid, metric, metric, AggFunction.sum)],
            ),
            VisualizationSpec(VisualType.kpi_card, title=f"Total {metric}"),
        )
        visual_order.append(vid)

    first_metric = metric_names[0] if metric_names else None
    first_dim = dim_names[0] if dim_names else None

    # Bar chart — first metric × first dimension
    if first_metric and first_dim:
        bar_vid = "bar_overview"
        visuals[bar_vid] = ReportVisualSpec(
            bar_vid,
            VisualQuerySpec(
                bar_vid,
                [block_ref],
                metrics=[MetricRef(bid, first_metric, first_metric, AggFunction.sum)],
                dimensions=[DimensionRef(bid, first_dim, first_dim)],
                sort=[SortSpec(first_metric, SortDirection.desc)],
                limit=20,
            ),
            VisualizationSpec(
                VisualType.bar_chart,
                title=f"{first_metric} by {first_dim}",
                x_axis_label=first_dim,
                y_axis_label=first_metric,
                height_px=340,
            ),
        )
        visual_order.append(bar_vid)

    # Summary table — up to 3 metrics + 3 dimensions
    if first_metric and first_dim:
        tbl_vid = "table_summary"
        tbl_metrics = [MetricRef(bid, m, m, AggFunction.sum) for m in metric_names[:3]]
        tbl_dims = [DimensionRef(bid, d, d) for d in dim_names[:3]]
        visuals[tbl_vid] = ReportVisualSpec(
            tbl_vid,
            VisualQuerySpec(
                tbl_vid,
                [block_ref],
                metrics=tbl_metrics,
                dimensions=tbl_dims,
                sort=[SortSpec(first_metric, SortDirection.desc)],
                limit=100,
            ),
            VisualizationSpec(VisualType.table, title="資料摘要", height_px=320),
        )
        visual_order.append(tbl_vid)

    report_id = f"upload_{bid}_{uuid.uuid4().hex[:6]}"
    page = ReportPageSpec(
        "main",
        "Overview",
        visuals,
        visual_order,
        display_name="概覽",
    )
    return ExecutableReportSpec(
        audit=AuditMetadata(
            report_id=report_id,
            created_by=os.environ.get("ANALYST_NAME", "user"),
        ),
        title=f"{bid} 報表",
        semantic_model_ref=f"{bid}@user_upload",
        status="user_draft",
        pages={"main": page},
        controls={},
    )


def _slugify(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "col"
