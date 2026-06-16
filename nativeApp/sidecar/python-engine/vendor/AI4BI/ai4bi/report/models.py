"""Executable report state for the governed Streamlit report canvas."""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    HavingSpec,
    MetricRef,
    SortDirection,
    SortSpec,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)


class ReportValidationError(ValueError):
    """Raised when a report or proposal does not conform to the draft contract."""


class PublishBlockedError(Exception):
    """Raised when attempting to publish a report that has not passed the publication gate."""


@dataclass
class AuditMetadata:
    """Governance audit trail for a report draft."""

    report_id: str
    created_by: str = "unknown"
    created_at: str | None = None      # ISO-8601 string, set on first save
    last_modified_by: str = "unknown"
    last_modified_at: str | None = None
    revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "last_modified_by": self.last_modified_by,
            "last_modified_at": self.last_modified_at,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuditMetadata":
        return cls(
            report_id=payload["report_id"],
            created_by=payload.get("created_by", "unknown"),
            created_at=payload.get("created_at"),
            last_modified_by=payload.get("last_modified_by", "unknown"),
            last_modified_at=payload.get("last_modified_at"),
            revision=int(payload.get("revision", 0)),
        )


@dataclass
class ControlSpec:
    """One user-editable report control, optionally bound to a global filter."""

    control_id: str
    label: str
    value: Any
    options: list[Any]
    filter_key: str | None = None

    def validate(self) -> None:
        values = self.value if isinstance(self.value, list) else [self.value]
        invalid = [value for value in values if value not in self.options]
        if invalid:
            raise ReportValidationError(
                f"Control '{self.control_id}' contains unsupported values: {invalid}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "label": self.label,
            "value": copy.deepcopy(self.value),
            "options": copy.deepcopy(self.options),
            "filter_key": self.filter_key,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlSpec":
        control = cls(
            control_id=payload["control_id"],
            label=payload["label"],
            value=copy.deepcopy(payload["value"]),
            options=copy.deepcopy(payload["options"]),
            filter_key=payload.get("filter_key"),
        )
        control.validate()
        return control


def _block_ref_to_dict(ref: BlockRef) -> dict[str, Any]:
    return {
        "block_id": ref.block_id,
        "pinned_version": ref.pinned_version,
        "pin_reason": ref.pin_reason,
        "pinned_at": ref.pinned_at.isoformat() if ref.pinned_at else None,
    }


def _block_ref_from_dict(payload: dict[str, Any]) -> BlockRef:
    pinned_at = payload.get("pinned_at")
    return BlockRef(
        block_id=payload["block_id"],
        pinned_version=payload.get("pinned_version"),
        pin_reason=payload.get("pin_reason"),
        pinned_at=datetime.fromisoformat(pinned_at) if pinned_at else None,
    )


def query_to_dict(query: VisualQuerySpec) -> dict[str, Any]:
    return {
        "spec_id": query.spec_id,
        "block_refs": [_block_ref_to_dict(ref) for ref in query.block_refs],
        "metrics": [
            {
                "block_id": metric.block_id,
                "metric_name": metric.metric_name,
                "alias": metric.alias,
                "agg_override": metric.agg_override.value if metric.agg_override else None,
            }
            for metric in query.metrics
        ],
        "dimensions": [
            {
                "block_id": dimension.block_id,
                "column_name": dimension.column_name,
                "alias": dimension.alias,
                "truncate_date_to": dimension.truncate_date_to,
            }
            for dimension in query.dimensions
        ],
        "filters": [
            {
                "block_id": filter_spec.block_id,
                "column_name": filter_spec.column_name,
                "operator": filter_spec.operator.value,
                "value": copy.deepcopy(filter_spec.value),
                "inherit_global_filter": filter_spec.inherit_global_filter,
            }
            for filter_spec in query.filters
        ],
        "having": [
            {
                "block_id": h.block_id,
                "metric_name": h.metric_name,
                "operator": h.operator.value,
                "value": copy.deepcopy(h.value),
            }
            for h in query.having
        ],
        "sort": [
            {"column_name": sort.column_name, "direction": sort.direction.value}
            for sort in query.sort
        ],
        "limit": query.limit,
        "data_version": query.data_version,
        "inherit_global_filter": query.inherit_global_filter,
        "cross_filter_emit": (
            {
                "block_id": query.cross_filter_emit.block_id,
                "column_name": query.cross_filter_emit.column_name,
                "alias": query.cross_filter_emit.alias,
                "truncate_date_to": query.cross_filter_emit.truncate_date_to,
            }
            if query.cross_filter_emit
            else None
        ),
    }


def query_from_dict(payload: dict[str, Any]) -> VisualQuerySpec:
    return VisualQuerySpec(
        spec_id=payload["spec_id"],
        block_refs=[_block_ref_from_dict(ref) for ref in payload["block_refs"]],
        metrics=[
            MetricRef(
                block_id=metric["block_id"],
                metric_name=metric["metric_name"],
                alias=metric.get("alias"),
                agg_override=(
                    AggFunction(metric["agg_override"]) if metric.get("agg_override") else None
                ),
            )
            for metric in payload.get("metrics", [])
        ],
        dimensions=[
            DimensionRef(
                block_id=dimension["block_id"],
                column_name=dimension["column_name"],
                alias=dimension.get("alias"),
                truncate_date_to=dimension.get("truncate_date_to"),
            )
            for dimension in payload.get("dimensions", [])
        ],
        filters=[
            FilterSpec(
                block_id=filter_spec["block_id"],
                column_name=filter_spec["column_name"],
                operator=FilterOperator(filter_spec["operator"]),
                value=copy.deepcopy(filter_spec.get("value")),
                inherit_global_filter=filter_spec.get("inherit_global_filter", False),
            )
            for filter_spec in payload.get("filters", [])
        ],
        having=[
            HavingSpec(
                block_id=h["block_id"],
                metric_name=h["metric_name"],
                operator=FilterOperator(h["operator"]),
                value=copy.deepcopy(h.get("value")),
            )
            for h in payload.get("having", [])
        ],
        sort=[
            SortSpec(sort["column_name"], SortDirection(sort.get("direction", "desc")))
            for sort in payload.get("sort", [])
        ],
        limit=payload.get("limit"),
        data_version=payload.get("data_version", "v1"),
        inherit_global_filter=payload.get("inherit_global_filter", False),
        cross_filter_emit=(
            DimensionRef(
                block_id=payload["cross_filter_emit"]["block_id"],
                column_name=payload["cross_filter_emit"]["column_name"],
                alias=payload["cross_filter_emit"].get("alias"),
                truncate_date_to=payload["cross_filter_emit"].get("truncate_date_to"),
            )
            if payload.get("cross_filter_emit")
            else None
        ),
    )


def visualization_to_dict(style: VisualizationSpec) -> dict[str, Any]:
    return {
        "visual_type": style.visual_type.value,
        "title": style.title,
        "subtitle": style.subtitle,
        "x_axis_label": style.x_axis_label,
        "y_axis_label": style.y_axis_label,
        "color_scheme": style.color_scheme,
        "show_legend": style.show_legend,
        "show_sparkline": style.show_sparkline,
        "delta_metric": style.delta_metric,
        "height_px": style.height_px,
        "extra": copy.deepcopy(style.extra),
    }


def visualization_from_dict(payload: dict[str, Any]) -> VisualizationSpec:
    return VisualizationSpec(
        visual_type=VisualType(payload.get("visual_type", "kpi_card")),
        title=payload.get("title"),
        subtitle=payload.get("subtitle"),
        x_axis_label=payload.get("x_axis_label"),
        y_axis_label=payload.get("y_axis_label"),
        color_scheme=payload.get("color_scheme", "plotly"),
        show_legend=payload.get("show_legend", True),
        show_sparkline=payload.get("show_sparkline", False),
        delta_metric=payload.get("delta_metric"),
        height_px=payload.get("height_px", 300),
        extra=copy.deepcopy(payload.get("extra", {})),
    )


@dataclass
class ReportVisualSpec:
    component_id: str
    query: VisualQuerySpec
    visualization: VisualizationSpec
    col_span: int = 12  # Round 030: 12-column grid (3=25%, 4=33%, 6=50%, 12=100%)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "query": query_to_dict(self.query),
            "visualization": visualization_to_dict(self.visualization),
            "col_span": self.col_span,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportVisualSpec":
        return cls(
            component_id=payload["component_id"],
            query=query_from_dict(payload["query"]),
            visualization=visualization_from_dict(payload["visualization"]),
            col_span=int(payload.get("col_span", 12)),
        )


@dataclass
class ReportPageSpec:
    page_id: str
    title: str
    visuals: dict[str, ReportVisualSpec]
    visual_order: list[str]
    display_name: str = ""

    def validate(self) -> None:
        if set(self.visual_order) != set(self.visuals):
            raise ReportValidationError("Page visual_order must exactly identify its visuals.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "visuals": {key: visual.to_dict() for key, visual in self.visuals.items()},
            "visual_order": list(self.visual_order),
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportPageSpec":
        page = cls(
            page_id=payload["page_id"],
            title=payload["title"],
            visuals={
                key: ReportVisualSpec.from_dict(value)
                for key, value in payload["visuals"].items()
            },
            visual_order=list(payload["visual_order"]),
            display_name=payload.get("display_name", ""),
        )
        page.validate()
        return page

    def add_visual(self, visual_id: str, visual_spec: "ReportVisualSpec") -> None:
        """Add a visual to this page, appending its id to visual_order."""
        if visual_id in self.visuals:
            raise ReportValidationError(
                f"Visual '{visual_id}' already exists on page '{self.page_id}'."
            )
        self.visuals[visual_id] = visual_spec
        self.visual_order.append(visual_id)

    def remove_visual(self, visual_id: str) -> None:
        """Remove a visual from this page (and from visual_order)."""
        if visual_id not in self.visuals:
            raise ReportValidationError(
                f"Visual '{visual_id}' is not on page '{self.page_id}'."
            )
        del self.visuals[visual_id]
        if visual_id in self.visual_order:
            self.visual_order.remove(visual_id)

    def move_visual_up(self, visual_id: str) -> None:
        """Moves visual_id one position earlier in visual_order. No-op if already first."""
        if visual_id not in self.visual_order:
            raise ReportValidationError(
                f"Visual '{visual_id}' is not in visual_order for page '{self.page_id}'."
            )
        idx = self.visual_order.index(visual_id)
        if idx == 0:
            return  # already first, no-op
        self.visual_order[idx - 1], self.visual_order[idx] = (
            self.visual_order[idx],
            self.visual_order[idx - 1],
        )

    def move_visual_down(self, visual_id: str) -> None:
        """Moves visual_id one position later in visual_order. No-op if already last."""
        if visual_id not in self.visual_order:
            raise ReportValidationError(
                f"Visual '{visual_id}' is not in visual_order for page '{self.page_id}'."
            )
        idx = self.visual_order.index(visual_id)
        if idx == len(self.visual_order) - 1:
            return  # already last, no-op
        self.visual_order[idx], self.visual_order[idx + 1] = (
            self.visual_order[idx + 1],
            self.visual_order[idx],
        )


@dataclass
class ExecutableReportSpec:
    audit: AuditMetadata
    title: str
    semantic_model_ref: str
    status: str
    pages: dict[str, ReportPageSpec]
    controls: dict[str, ControlSpec]
    read_only: bool = False
    saved_at: str | None = None
    global_filters: dict[str, Any] = field(default_factory=dict)
    # Round 064: optional password gate for read-only shares (sha256 hash; None = open)
    share_password_hash: str | None = None

    # ------------------------------------------------------------------
    # Backward-compat properties so existing code using report.report_id
    # and report.revision continues to work without modification.
    # ------------------------------------------------------------------

    @property
    def report_id(self) -> str:
        return self.audit.report_id

    @property
    def revision(self) -> int:
        return self.audit.revision

    @revision.setter
    def revision(self, value: int) -> None:
        self.audit.revision = value

    _VALID_STATUSES = {"validated_demo_draft", "user_draft"}

    def validate(self) -> None:
        if self.status not in self._VALID_STATUSES:
            raise ReportValidationError("Only validated demo drafts are supported in this MVP.")
        if not self.pages:
            raise ReportValidationError("A report must contain at least one page.")
        for page in self.pages.values():
            page.validate()
        for control in self.controls.values():
            control.validate()

    def deep_copy(self) -> "ExecutableReportSpec":
        return ExecutableReportSpec.from_dict(self.to_dict())

    def active_filters(self) -> dict[str, Any]:
        return {
            control.filter_key: copy.deepcopy(control.value)
            for control in self.controls.values()
            if control.filter_key
        }

    def set_global_filter(self, key: str, values: list) -> None:
        """Sets a global filter. Empty list removes the key."""
        if values:
            self.global_filters[key] = values
        else:
            self.global_filters.pop(key, None)

    def merged_filters(self) -> dict[str, list]:
        """Returns active_filters() merged with global_filters. global_filters wins on conflict."""
        merged = dict(self.active_filters())
        merged.update(self.global_filters)
        return merged

    def add_page(self, page_id: str, page_spec: "ReportPageSpec") -> None:
        """Adds a new page. Raises ReportValidationError if page_id already exists."""
        if page_id in self.pages:
            raise ReportValidationError(f"Page '{page_id}' already exists")
        self.pages[page_id] = page_spec

    def delete_page(self, page_id: str) -> None:
        """Deletes a page while preserving the invariant that reports have pages."""
        if page_id not in self.pages:
            raise ReportValidationError(f"Page '{page_id}' not found in report.")
        if len(self.pages) <= 1:
            raise ReportValidationError("Cannot delete the last page in a report.")
        del self.pages[page_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": "2.0-draft",
            "audit": self.audit.to_dict(),
            "title": self.title,
            "semantic_model_ref": self.semantic_model_ref,
            "status": self.status,
            "pages": {key: page.to_dict() for key, page in self.pages.items()},
            "controls": {key: control.to_dict() for key, control in self.controls.items()},
            "read_only": self.read_only,
            "saved_at": self.saved_at,
            "global_filters": copy.deepcopy(self.global_filters),
            "share_password_hash": self.share_password_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutableReportSpec":
        if payload.get("spec_version") != "2.0-draft":
            raise ReportValidationError("Unsupported report draft spec version.")
        # Backward compat: old drafts have top-level report_id/revision, no audit key
        if "audit" in payload:
            audit = AuditMetadata.from_dict(payload["audit"])
        else:
            audit = AuditMetadata(
                report_id=payload.get("report_id", ""),
                revision=int(payload.get("revision", 0)),
            )
        report = cls(
            audit=audit,
            title=payload["title"],
            semantic_model_ref=payload["semantic_model_ref"],
            status=payload["status"],
            pages={
                key: ReportPageSpec.from_dict(value)
                for key, value in payload["pages"].items()
            },
            controls={
                key: ControlSpec.from_dict(value)
                for key, value in payload["controls"].items()
            },
            read_only=bool(payload.get("read_only", False)),
            saved_at=payload.get("saved_at"),
            global_filters=copy.deepcopy(payload.get("global_filters", {})),
            share_password_hash=payload.get("share_password_hash"),
        )
        report.validate()
        return report


@dataclass(frozen=True)
class ReportChange:
    path: str
    label: str
    before: Any
    after: Any
    affects_data: bool


@dataclass
class ReportProposal:
    description: str
    changes: list[ReportChange] = field(default_factory=list)
    target_component_id: str | None = None

    @property
    def affects_data(self) -> bool:
        return any(change.affects_data for change in self.changes)


# Presentation-only visualization.extra keys an AI proposal may set/get.
# These never change query semantics or numbers — they are overlays/formatting.
_ALLOWLISTED_VISUAL_EXTRA_KEYS = {
    "line_color", "bar_color",
    "trend_line",          # linear/avg overlay on a line chart
    "moving_avg",          # moving-average overlay
    "conditional_formats", # table cell highlighting rules
    "data_labels",         # show value labels on bars (Round 058)
    "number_format",       # display number format (Round 058)
    "hole", "show_percent",  # pie/donut presentation
    "target", "target_good_if",  # KPI goal / pacing (Round 084)
    # Round 160: chart Format pane — axis range/scale, legend placement
    "y_min", "y_max", "y_scale", "legend_position",
    # Round 137: horizontal baseline / reference line (mean or custom value)
    "baseline", "baseline_value",
}


def _get_path(report: ExecutableReportSpec, path: str) -> Any:
    parts = path.split("/")
    if len(parts) == 2 and parts[0] == "global_filters":
        return report.global_filters.get(parts[1])
    if len(parts) == 3 and parts[0] == "controls" and parts[2] == "value":
        return report.controls[parts[1]].value
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "add_visual":
        # For add_visual the "current" state is None (visual does not exist yet).
        return None
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "delete":
        page = report.pages.get(parts[1])
        return page.to_dict() if page is not None else None
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "reorder_visual":
        return list(report.pages[parts[1]].visual_order)
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "display_name":
        return report.pages[parts[1]].display_name
    if len(parts) == 7 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:6] == ["visualization", "extra"] and parts[6] in _ALLOWLISTED_VISUAL_EXTRA_KEYS:
            return visual.visualization.extra.get(parts[6])
    if len(parts) == 5 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "delete":
        page = report.pages.get(parts[1])
        if page is not None and parts[3] in page.visuals:
            return page.visuals[parts[3]].to_dict()
        return None
    if len(parts) == 5 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "col_span":
        return report.pages[parts[1]].visuals[parts[3]].col_span
    if len(parts) == 6 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:] == ["visualization", "title"]:
            return visual.visualization.title
        if parts[4:] == ["visualization", "visual_type"]:
            return visual.visualization.visual_type.value
        if parts[4:] == ["query", "dimensions"]:
            return [
                {
                    "block_id": dimension.block_id,
                    "column_name": dimension.column_name,
                    "alias": dimension.alias,
                    "truncate_date_to": dimension.truncate_date_to,
                }
                for dimension in visual.query.dimensions
            ]
        if parts[4:] == ["query", "metrics"]:
            return [
                {
                    "block_id": metric.block_id,
                    "metric_name": metric.metric_name,
                    "alias": metric.alias,
                    "agg_override": metric.agg_override.value if metric.agg_override else None,
                }
                for metric in visual.query.metrics
            ]
        if parts[4:] == ["query", "sort"]:
            return [
                {"column_name": s.column_name, "direction": s.direction.value}
                for s in visual.query.sort
            ]
        if parts[4:] == ["query", "filters"]:
            return [
                {
                    "block_id": f.block_id,
                    "column_name": f.column_name,
                    "operator": f.operator.value,
                    "value": copy.deepcopy(f.value),
                    "inherit_global_filter": f.inherit_global_filter,
                }
                for f in visual.query.filters
            ]
        if parts[4:] == ["query", "having"]:
            return [
                {
                    "block_id": h.block_id,
                    "metric_name": h.metric_name,
                    "operator": h.operator.value,
                    "value": copy.deepcopy(h.value),
                }
                for h in visual.query.having
            ]
    if len(parts) == 8 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "query" and parts[5] == "block_refs" and parts[7] == "pinned_version":
        visual = report.pages[parts[1]].visuals[parts[3]]
        block_id = parts[6]
        for ref in visual.query.block_refs:
            if ref.block_id == block_id:
                return ref.pinned_version
        raise ReportValidationError(f"BlockRef '{block_id}' not found in visual '{parts[3]}'.")
    if path == "title":
        return report.title
    raise ReportValidationError(f"Unsupported proposal path '{path}'.")


def _set_path(report: ExecutableReportSpec, path: str, value: Any) -> None:
    parts = path.split("/")
    if len(parts) == 2 and parts[0] == "global_filters":
        report.set_global_filter(parts[1], value if value is not None else [])
        return
    if len(parts) == 3 and parts[0] == "controls" and parts[2] == "value":
        report.controls[parts[1]].value = copy.deepcopy(value)
        return
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "add_visual":
        # value is {"visual_id": str, "visual": dict}
        page = report.pages[parts[1]]
        visual_id = value["visual_id"]
        visual_spec = ReportVisualSpec.from_dict(value["visual"])
        page.add_visual(visual_id, visual_spec)
        return
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "delete":
        page_id = parts[1]
        if value is None:
            report.delete_page(page_id)
        else:
            report.add_page(page_id, ReportPageSpec.from_dict(value))
        return
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "display_name":
        report.pages[parts[1]].display_name = str(value) if value is not None else ""
        return
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "reorder_visual":
        # value is {"visual_id": str, "direction": "up" | "down"}
        page = report.pages[parts[1]]
        visual_id = value["visual_id"]
        direction = value["direction"]
        if direction == "up":
            page.move_visual_up(visual_id)
        elif direction == "down":
            page.move_visual_down(visual_id)
        else:
            raise ReportValidationError(f"Invalid reorder direction '{direction}'; must be 'up' or 'down'.")
        return
    if len(parts) == 5 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "delete":
        report.pages[parts[1]].remove_visual(parts[3])
        return
    if len(parts) == 7 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:6] == ["visualization", "extra"] and parts[6] in _ALLOWLISTED_VISUAL_EXTRA_KEYS:
            visual.visualization.extra[parts[6]] = value
            return
    if len(parts) == 5 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "col_span":
        report.pages[parts[1]].visuals[parts[3]].col_span = int(value)
        return
    if len(parts) == 6 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:] == ["visualization", "title"]:
            visual.visualization.title = str(value)
            return
        if parts[4:] == ["visualization", "visual_type"]:
            visual.visualization.visual_type = VisualType(value)
            return
        if parts[4:] == ["query", "dimensions"]:
            visual.query.dimensions = [
                DimensionRef(
                    block_id=dimension["block_id"],
                    column_name=dimension["column_name"],
                    alias=dimension.get("alias"),
                    truncate_date_to=dimension.get("truncate_date_to"),
                )
                for dimension in value
            ]
            return
        if parts[4:] == ["query", "metrics"]:
            visual.query.metrics = [
                MetricRef(
                    block_id=m["block_id"],
                    metric_name=m["metric_name"],
                    alias=m.get("alias"),
                    agg_override=(
                        AggFunction(m["agg_override"]) if m.get("agg_override") else None
                    ),
                )
                for m in value
            ]
            return
        if parts[4:] == ["query", "filters"]:
            visual.query.filters = [
                FilterSpec(
                    block_id=f["block_id"],
                    column_name=f["column_name"],
                    operator=FilterOperator(f["operator"]),
                    value=copy.deepcopy(f.get("value")),
                    inherit_global_filter=f.get("inherit_global_filter", False),
                )
                for f in value
            ]
            return
        if parts[4:] == ["query", "having"]:
            visual.query.having = [
                HavingSpec(
                    block_id=h["block_id"],
                    metric_name=h["metric_name"],
                    operator=FilterOperator(h["operator"]),
                    value=copy.deepcopy(h.get("value")),
                )
                for h in value
            ]
            return
        if parts[4:] == ["query", "sort"]:
            visual.query.sort = [
                SortSpec(s["column_name"], SortDirection(s.get("direction", "desc")))
                for s in value
            ]
            return
    if len(parts) == 8 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "query" and parts[5] == "block_refs" and parts[7] == "pinned_version":
        visual = report.pages[parts[1]].visuals[parts[3]]
        block_id = parts[6]
        for ref in visual.query.block_refs:
            if ref.block_id == block_id:
                ref.pinned_version = value
                if value is None:
                    # Unpinning — clear both fields
                    ref.pin_reason = None
                elif ref.pin_reason is None:
                    ref.pin_reason = "manually pinned by user"
                return
        raise ReportValidationError(f"BlockRef '{block_id}' not found in visual '{parts[3]}'.")
    if path == "title":
        if not isinstance(value, str) or not value.strip():
            raise ReportValidationError("Report title must be a non-empty string.")
        report.title = value
        return
    raise ReportValidationError(f"Unsupported proposal path '{path}'.")


def apply_report_proposal(
    report: ExecutableReportSpec,
    proposal: ReportProposal,
) -> ExecutableReportSpec:
    """Atomically apply an allowlisted proposal to a report draft."""
    candidate = report.deep_copy()
    for change in proposal.changes:
        current = _get_path(candidate, change.path)
        if current != change.before:
            raise ReportValidationError(
                f"Proposal is stale for '{change.label}': expected {change.before!r}, got {current!r}."
            )
        _set_path(candidate, change.path, change.after)
    candidate.audit.revision += 1
    candidate.saved_at = None
    candidate.validate()
    return candidate


class DraftReportStore:
    """Filesystem store for explicitly non-published local report drafts."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def _safe_name(report_id: str) -> str:
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", report_id).strip("_")
        if not name:
            raise ReportValidationError("Report id cannot be converted to a draft filename.")
        return name

    def save(self, report: ExecutableReportSpec) -> Path:
        report.validate()
        saved = report.deep_copy()
        saved.saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        now_utc = datetime.now(timezone.utc).isoformat()
        if saved.audit.created_at is None:
            saved.audit.created_at = now_utc
        saved.audit.last_modified_at = now_utc
        saved.audit.last_modified_by = os.environ.get("ANALYST_NAME", "unknown")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self._safe_name(saved.report_id)}.json"
        path.write_text(json.dumps(saved.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def list_paths(self) -> list[Path]:
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*.json"))

    def load(self, path: str | Path) -> ExecutableReportSpec:
        candidate = Path(path)
        if candidate.parent.resolve() != self.directory.resolve():
            raise ReportValidationError("Draft path is outside the configured store.")
        return ExecutableReportSpec.from_dict(
            json.loads(candidate.read_text(encoding="utf-8"))
        )


class PublishedReportStore:
    """Filesystem store for formally published report snapshots."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def publish(
        self,
        report: "ExecutableReportSpec",
        gate_result: "Any",
    ) -> "tuple[Path, str]":
        """Publish a report if the gate result permits it.

        Fails with PublishBlockedError when gate_result.can_publish is False.
        Writes report JSON to root/<report_id>/<iso_timestamp>.json.
        Sets report.audit.last_modified_at to now (UTC).
        Returns (written_path, share_url) where
            share_url = '?mode=readonly&draft=<written_path>'.
        """
        if not gate_result.can_publish:
            raise PublishBlockedError(
                "Cannot publish: one or more blocking gate checks failed."
            )

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")

        report_dir = self.root / report.report_id
        report_dir.mkdir(parents=True, exist_ok=True)

        snapshot = report.deep_copy()
        snapshot.audit.last_modified_at = now.isoformat()
        snapshot.audit.last_modified_by = os.environ.get("ANALYST_NAME", "unknown")

        file_path = report_dir / f"{timestamp}.json"
        file_path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        share_url = f"?mode=readonly&draft={file_path}"
        return file_path, share_url

    def list_published(self, report_id: str) -> "list[Path]":
        """Return all published snapshots for report_id, newest first."""
        report_dir = self.root / report_id
        if not report_dir.exists():
            return []
        return sorted(report_dir.glob("*.json"), reverse=True)

    def load(self, path: str | Path) -> ExecutableReportSpec:
        """Load a published snapshot, restricted to this store's root."""
        candidate = Path(path)
        root = self.root.resolve()
        resolved = candidate.resolve()
        if root not in (resolved, *resolved.parents):
            raise ReportValidationError("Published snapshot path is outside the configured store.")
        if not resolved.exists() or resolved.suffix != ".json":
            raise ReportValidationError("Published snapshot path must point to an existing JSON file.")
        return ExecutableReportSpec.from_dict(
            json.loads(resolved.read_text(encoding="utf-8"))
        )
