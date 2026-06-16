"""
VisualQuerySpec — Round 007 schema with BlockRef migration.

Key change from Round 006:
  block_ids: list[str]  →  block_refs: list[BlockRef]

BlockRef adds optional version-pinning so a visual can lock to a specific
block contract version (e.g. to prevent silent schema drift) while still
allowing unpinned ("latest") references for exploratory dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VisualType(str, Enum):
    kpi_card    = "kpi_card"
    line_chart  = "line_chart"
    bar_chart   = "bar_chart"
    pie_chart   = "pie_chart"    # Round 029
    scatter     = "scatter"      # Round 029
    table       = "table"
    pivot       = "pivot"
    map         = "map"
    small_multiples = "small_multiples"  # Round 094: trellis / faceted grid


class AggFunction(str, Enum):
    sum   = "SUM"
    avg   = "AVG"
    count = "COUNT"
    min   = "MIN"
    max   = "MAX"
    count_distinct = "COUNT_DISTINCT"


class FilterOperator(str, Enum):
    eq          = "eq"
    neq         = "neq"
    gt          = "gt"
    gte         = "gte"
    lt          = "lt"
    lte         = "lte"
    in_         = "in"
    not_in      = "not_in"
    between     = "between"
    like        = "like"
    is_null     = "is_null"
    is_not_null = "is_not_null"


class SortDirection(str, Enum):
    asc  = "asc"
    desc = "desc"


# ---------------------------------------------------------------------------
# BlockRef — Round 007 replacement for bare block_id strings
# ---------------------------------------------------------------------------

@dataclass
class BlockRef:
    """
    A reference to a DataBlock, with optional version pinning.

    Fields
    ------
    block_id : str
        The globally unique identifier of the target block.
    pinned_version : str | None
        If set, the executor MUST use this exact semver of the block contract.
        None means "use the current certified version" (latest).
    pin_reason : str | None
        Human-readable explanation of why the version is pinned
        (e.g. "dashboard frozen for Q1-2024 board deck").
    pinned_at : datetime | None
        Timestamp when the pin was applied; used for audit trails.

    Examples
    --------
    Unpinned (resolves to latest certified):
        BlockRef(block_id="sales_fact")

    Pinned to a specific version:
        BlockRef(
            block_id="sales_fact",
            pinned_version="1.2.0",
            pin_reason="Q1 board deck — must not change mid-quarter",
            pinned_at=datetime(2024, 1, 15, 9, 0, 0),
        )
    """

    block_id: str
    pinned_version: Optional[str] = None
    pin_reason: Optional[str] = None
    pinned_at: Optional[datetime] = None

    @property
    def is_pinned(self) -> bool:
        """True if this ref is locked to a specific block contract version."""
        return self.pinned_version is not None

    def __post_init__(self) -> None:
        if not self.block_id or not self.block_id.strip():
            raise ValueError("BlockRef.block_id must be a non-empty string")
        if self.pinned_version is not None:
            parts = self.pinned_version.split(".")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise ValueError(
                    f"BlockRef.pinned_version must be semver (MAJOR.MINOR.PATCH), "
                    f"got: {self.pinned_version!r}"
                )


# ---------------------------------------------------------------------------
# Query building blocks
# ---------------------------------------------------------------------------

@dataclass
class MetricRef:
    """Reference to a named metric defined on a block."""
    block_id: str
    metric_name: str
    alias: Optional[str] = None                # display label override
    agg_override: Optional[AggFunction] = None  # override block-default aggregation


@dataclass
class DimensionRef:
    """Reference to a column used as a grouping dimension."""
    block_id: str
    column_name: str
    alias: Optional[str] = None
    truncate_date_to: Optional[str] = None  # "day" | "week" | "month" | "quarter" | "year"


@dataclass
class FilterSpec:
    """A single predicate applied during query execution."""
    block_id: str
    column_name: str
    operator: FilterOperator
    value: Any = None                          # scalar, list, or [lo, hi] for between
    inherit_global_filter: bool = False        # True → value is overridden by global filter


@dataclass
class HavingSpec:
    """A post-aggregation predicate on a projected metric (Round 079).

    Unlike FilterSpec (which filters raw rows *before* GROUP BY), HavingSpec
    filters aggregated groups *after* GROUP BY — the SQL HAVING clause. This is
    what makes "customers who bought more than 3 times", "products selling below
    NT$500", and churn/VIP/slow-mover lists expressible. The referenced metric
    must already be projected in the spec's ``metrics`` (visual-level measure
    filter), keeping execution on the certified semantic layer.
    """
    block_id: str
    metric_name: str
    operator: FilterOperator
    value: Any = None                          # scalar, or [lo, hi] for between


@dataclass
class SortSpec:
    column_name: str
    direction: SortDirection = SortDirection.desc


# ---------------------------------------------------------------------------
# Visualization style (separate from query concerns)
# ---------------------------------------------------------------------------

@dataclass
class VisualizationSpec:
    """
    Presentation hints consumed by UI components.
    Intentionally decoupled from VisualQuerySpec so the same query can be
    rendered in different visual forms without touching the data contract.
    """
    visual_type: VisualType = VisualType.kpi_card
    title: Optional[str] = None
    subtitle: Optional[str] = None
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None
    color_scheme: str = "plotly"               # Plotly colorscale name
    show_legend: bool = True
    show_sparkline: bool = False               # kpi_card only
    delta_metric: Optional[str] = None        # kpi_card: metric to show as delta
    height_px: int = 300
    extra: dict[str, Any] = field(default_factory=dict)  # escape hatch for future props


# ---------------------------------------------------------------------------
# VisualQuerySpec — main contract (Round 007)
# ---------------------------------------------------------------------------

@dataclass
class VisualQuerySpec:
    """
    Declarative specification for a single visual's data query.

    Round 007 change
    ----------------
    ``block_ids: list[str]`` replaced by ``block_refs: list[BlockRef]``.
    This enables per-visual version pinning without changing the executor
    interface — callers that previously passed bare IDs now wrap them in
    ``BlockRef(block_id=...)`` with no other changes required.

    Fields
    ------
    spec_id : str
        Stable identifier for this visual spec (used as cache key prefix).
    block_refs : list[BlockRef]
        Ordered list of blocks participating in this query.  The first entry
        is the primary (driving) block; subsequent entries are joined in order.
    metrics : list[MetricRef]
        Metrics to aggregate and return.
    dimensions : list[DimensionRef]
        Columns to group by.
    filters : list[FilterSpec]
        Predicates applied before aggregation.
    sort : list[SortSpec]
        Post-aggregation ordering.
    limit : int | None
        Maximum rows returned (None = no limit).
    data_version : str
        Monotonically increasing token from the data layer; used as the
        second component of the cache key so stale cache entries are
        automatically invalidated when data is refreshed.
    inherit_global_filter : bool
        If True, filters marked inherit_global_filter=True will have their
        values replaced by the dashboard's active global filters at runtime.
    cross_filter_emit : DimensionRef | None
        Optional dimension emitted by an interactive visual selection.  The UI
        layer can translate selected values for this dimension into page-scoped
        filters for compatible visuals.
    """

    spec_id: str
    block_refs: list[BlockRef]
    metrics: list[MetricRef] = field(default_factory=list)
    dimensions: list[DimensionRef] = field(default_factory=list)
    filters: list[FilterSpec] = field(default_factory=list)
    having: list[HavingSpec] = field(default_factory=list)  # Round 079: post-agg predicates
    sort: list[SortSpec] = field(default_factory=list)
    limit: Optional[int] = None
    data_version: str = "v1"
    inherit_global_filter: bool = False
    cross_filter_emit: Optional[DimensionRef] = None

    def __post_init__(self) -> None:
        if not self.spec_id or not self.spec_id.strip():
            raise ValueError("VisualQuerySpec.spec_id must be a non-empty string")
        if not self.block_refs:
            raise ValueError("VisualQuerySpec.block_refs must contain at least one BlockRef")

    @property
    def primary_block_id(self) -> str:
        """Convenience: block_id of the driving (first) block."""
        return self.block_refs[0].block_id

    @property
    def all_block_ids(self) -> list[str]:
        """All block IDs in the order they appear in block_refs."""
        return [ref.block_id for ref in self.block_refs]

    def cache_key(self) -> str:
        """
        Deterministic cache key for L1/L2 caches.

        Format: ``sha256(canonical_json):data_version``
        Canonical JSON excludes pinned_at timestamps so repinning the same
        version does not bust the cache unnecessarily.
        """
        import hashlib
        import json

        def _ref_to_dict(ref: BlockRef) -> dict:
            return {
                "block_id": ref.block_id,
                "pinned_version": ref.pinned_version,
                # deliberately excludes pinned_at and pin_reason
            }

        payload = {
            "spec_id": self.spec_id,
            "block_refs": [_ref_to_dict(r) for r in self.block_refs],
            "metrics": [
                {"block_id": m.block_id, "metric_name": m.metric_name,
                 "alias": m.alias, "agg_override": m.agg_override}
                for m in self.metrics
            ],
            "dimensions": [
                {"block_id": d.block_id, "column_name": d.column_name,
                 "alias": d.alias, "truncate_date_to": d.truncate_date_to}
                for d in self.dimensions
            ],
            "filters": [
                {"block_id": f.block_id, "column_name": f.column_name,
                 "operator": f.operator, "value": f.value,
                 "inherit_global_filter": f.inherit_global_filter}
                for f in self.filters
            ],
            "having": [
                {"block_id": h.block_id, "metric_name": h.metric_name,
                 "operator": h.operator, "value": h.value}
                for h in self.having
            ],
            "sort": [{"column_name": s.column_name, "direction": s.direction}
                     for s in self.sort],
            "limit": self.limit,
            "inherit_global_filter": self.inherit_global_filter,
            "cross_filter_emit": (
                {
                    "block_id": self.cross_filter_emit.block_id,
                    "column_name": self.cross_filter_emit.column_name,
                    "alias": self.cross_filter_emit.alias,
                    "truncate_date_to": self.cross_filter_emit.truncate_date_to,
                }
                if self.cross_filter_emit
                else None
            ),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        return f"{digest}:{self.data_version}"
