"""Cross-page drill-through — Round 093.

"Show me everything about store X." Builds a focused *detail page* filtered to a
single entity (the dimension value the user clicked / cross-filtered on), with a
standard 360 layout — a KPI per metric, a trend line, and a breakdown bar — all
scoped by one ``column = value`` filter. Pure spec construction (no Streamlit),
so it is unit-testable; the app layer just adds the page and navigates to it.
"""

from __future__ import annotations

from typing import Optional

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.query_spec import (
    BlockRef, DimensionRef, FilterOperator, FilterSpec, MetricRef,
    SortDirection, SortSpec, VisualizationSpec, VisualQuerySpec, VisualType,
)
from ai4bi.report.models import ReportPageSpec, ReportVisualSpec

_DATE_HINTS = ("date", "time", "_at", "_dt", "day")


def _slug(value: str) -> str:
    keep = [c if (c.isalnum() or c in "_- ") else "_" for c in str(value)]
    return "".join(keep).strip().replace(" ", "_")[:40] or "x"


def _sum_metrics(contract: DataBlockContract) -> list:
    out = []
    for m in contract.metrics:
        meth = getattr(getattr(m, "disaggregation_method", None), "value", "")
        if meth in ("sum", "average", "count"):
            out.append(m)
    return out


def _date_col(contract: DataBlockContract) -> Optional[str]:
    for c in contract.columns:
        if c.data_type in ("date", "timestamp") or any(h in c.name.lower() for h in _DATE_HINTS):
            return c.name
    return None


def _other_cat_col(contract: DataBlockContract, exclude: str) -> Optional[str]:
    pk = set(getattr(contract, "primary_keys", []) or [])
    for c in contract.columns:
        low = c.name.lower()
        if (c.data_type in ("string", "str", "object") and c.name != exclude
                and c.name not in pk
                and not (low == "id" or low.endswith(("_id", "_code", "_sku")))):
            return c.name
    return None


def build_detail_page(
    contract: DataBlockContract,
    block_id: str,
    column: str,
    value: object,
    max_metrics: int = 3,
) -> ReportPageSpec:
    """Build a detail (drill-through) page filtered to ``column = value``.

    Layout: one KPI per (up to ``max_metrics``) metric, a trend line over the
    date column, and a breakdown bar by another categorical column — every
    visual carries the same single ``column = value`` filter.
    """
    flt = FilterSpec(block_id, column, FilterOperator.eq, value, inherit_global_filter=False)
    metrics = _sum_metrics(contract)
    date_col = _date_col(contract)
    other_cat = _other_cat_col(contract, column)
    title_val = str(value)
    page_id = f"detail_{column}_{_slug(title_val)}"

    visuals: dict[str, ReportVisualSpec] = {}
    order: list[str] = []

    def _add(vid: str, query: VisualQuerySpec, viz: VisualizationSpec, span: int) -> None:
        visuals[vid] = ReportVisualSpec(vid, query, viz, col_span=span)
        order.append(vid)

    # KPI row
    for m in metrics[:max_metrics]:
        alias = m.name.replace("_", " ").title()
        vid = f"{page_id}_kpi_{m.name}"
        q = VisualQuerySpec(vid, [BlockRef(block_id)],
                            metrics=[MetricRef(block_id, m.name, alias)],
                            filters=[flt], inherit_global_filter=False)
        unit = getattr(m, "unit", None)
        _add(vid, q, VisualizationSpec(VisualType.kpi_card, title=alias,
                                       extra={"unit": unit} if unit else {}), 4)

    primary = metrics[0] if metrics else None

    # Trend line over time
    if primary and date_col:
        alias = primary.name.replace("_", " ").title()
        vid = f"{page_id}_trend"
        q = VisualQuerySpec(
            vid, [BlockRef(block_id)],
            metrics=[MetricRef(block_id, primary.name, alias)],
            dimensions=[DimensionRef(block_id, date_col, date_col, truncate_date_to="week")],
            filters=[flt], sort=[SortSpec(date_col, SortDirection.asc)],
            inherit_global_filter=False)
        _add(vid, q, VisualizationSpec(VisualType.line_chart, title=f"{alias} 趨勢"), 12)

    # Breakdown bar by another dimension
    if primary and other_cat:
        alias = primary.name.replace("_", " ").title()
        vid = f"{page_id}_breakdown"
        q = VisualQuerySpec(
            vid, [BlockRef(block_id)],
            metrics=[MetricRef(block_id, primary.name, alias)],
            dimensions=[DimensionRef(block_id, other_cat, other_cat)],
            filters=[flt], sort=[SortSpec(alias, SortDirection.desc)],
            limit=10, inherit_global_filter=False)
        _add(vid, q, VisualizationSpec(VisualType.bar_chart, title=f"{alias}（依{other_cat}）"), 12)

    return ReportPageSpec(
        page_id=page_id,
        title=f"{title_val} 詳情",
        visuals=visuals,
        visual_order=order,
        display_name=f"🔎 {title_val}",
    )
