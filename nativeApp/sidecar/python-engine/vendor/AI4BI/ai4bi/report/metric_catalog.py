"""Metric Catalog Service — three-zone classification for governed BI.

Design-council consensus (003-E):
  Zone 1 – CERTIFIED_READY:  metric owner block is certified AND all
            dimension blocks reachable via certified relationships are also
            certified.  Business user can add this metric immediately.
  Zone 2 – NEEDS_BLOCKS:     metric owner block is certified, but at least
            one required dimension block is missing from the loaded contracts
            or is in a non-certified lifecycle state.
  Zone 3 – SANDBOX:          metric owner block is not certified (draft /
            validated / deprecated / suspended).  Requires certification
            before the metric can be used in a published report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ai4bi.blocks.contracts import DataBlockContract, LifecycleStatus


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

class MetricZone(str, Enum):
    CERTIFIED_READY = "certified_ready"
    NEEDS_BLOCKS    = "needs_blocks"
    SANDBOX         = "sandbox"


@dataclass
class CatalogMetricEntry:
    block_id: str
    metric_name: str
    display_name: str
    aggregation: str
    zone: MetricZone
    description: str | None = None
    missing_blocks: list[str] = field(default_factory=list)


@dataclass
class CatalogResult:
    certified_ready: list[CatalogMetricEntry] = field(default_factory=list)
    needs_blocks: list[CatalogMetricEntry] = field(default_factory=list)
    sandbox: list[CatalogMetricEntry] = field(default_factory=list)

    @property
    def all_entries(self) -> list[CatalogMetricEntry]:
        return self.certified_ready + self.needs_blocks + self.sandbox

    def is_empty(self) -> bool:
        return not self.all_entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _certified_dim_targets(primary_block_id: str, semantic_model: dict) -> set[str]:
    """Return block_ids reachable from primary_block_id via certified relationships."""
    result: set[str] = set()
    for rel in semantic_model.get("relationships", []):
        if rel.get("from_block") == primary_block_id and rel.get("status") == "certified":
            result.add(rel["to_block"])
    return result


def _aggregation_from_formula(formula: str) -> str:
    upper = formula.upper().strip()
    for agg in ("COUNT_DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX"):
        if upper.startswith(agg + "("):
            return agg
    return "SUM"


def _make_display_name(s: str) -> str:
    return s.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class MetricCatalogService:
    """Classifies all semantic-model metrics into three governance zones."""

    def classify(
        self,
        semantic_model: dict,
        contracts: dict[str, DataBlockContract],
    ) -> CatalogResult:
        result = CatalogResult()

        for sm_metric in semantic_model.get("metrics", []):
            entry = self._classify_metric(sm_metric, semantic_model, contracts)
            if entry is None:
                continue
            if entry.zone == MetricZone.CERTIFIED_READY:
                result.certified_ready.append(entry)
            elif entry.zone == MetricZone.NEEDS_BLOCKS:
                result.needs_blocks.append(entry)
            else:
                result.sandbox.append(entry)

        return result

    def _classify_metric(
        self,
        sm_metric: dict,
        semantic_model: dict,
        contracts: dict[str, DataBlockContract],
    ) -> CatalogMetricEntry | None:
        metric_id = sm_metric.get("metric_id", "")
        owner_block_id = sm_metric.get("owner_block", "")
        if not metric_id or not owner_block_id:
            return None

        owner_contract = contracts.get(owner_block_id)

        # Owner block missing or not certified → SANDBOX
        if owner_contract is None or owner_contract.block_lifecycle != LifecycleStatus.certified:
            formula = sm_metric.get("formula", "SUM(?)")
            agg = _aggregation_from_formula(formula)
            description: str | None = None
            if owner_contract is not None:
                metric_def = next(
                    (m for m in owner_contract.metrics if m.name == metric_id), None
                )
                if metric_def:
                    description = metric_def.description
            return CatalogMetricEntry(
                block_id=owner_block_id,
                metric_name=metric_id,
                display_name=_make_display_name(metric_id),
                aggregation=agg,
                zone=MetricZone.SANDBOX,
                description=description,
            )

        # Owner is certified — check required dimension blocks
        metric_def = next(
            (m for m in owner_contract.metrics if m.name == metric_id), None
        )
        formula = metric_def.formula if metric_def else sm_metric.get("formula", "SUM(?)")
        agg = _aggregation_from_formula(formula)
        description = metric_def.description if metric_def else None

        certified_targets = _certified_dim_targets(owner_block_id, semantic_model)
        missing: list[str] = []
        for dim_block_id in certified_targets:
            dim_contract = contracts.get(dim_block_id)
            if dim_contract is None or dim_contract.block_lifecycle != LifecycleStatus.certified:
                missing.append(dim_block_id)

        zone = MetricZone.NEEDS_BLOCKS if missing else MetricZone.CERTIFIED_READY

        return CatalogMetricEntry(
            block_id=owner_block_id,
            metric_name=metric_id,
            display_name=_make_display_name(metric_id),
            aggregation=agg,
            zone=zone,
            description=description,
            missing_blocks=missing,
        )
