"""CatalogBrowser — builds a UI-ready metric/dimension catalog from semantic_model.json
and loaded DataBlockContracts.

Design notes
------------
* ``build_catalog`` is the single public entry point.
* Only the *primary* fact block contributes metrics in the single-block MVP.
* Dimensions come from:
    1. Columns on the primary block itself (self-dimensions).
    2. Columns on any dimension block that has a *certified* relationship from
       the primary block in the semantic model.
* Prohibited dimension blocks (from ``prohibited_paths``) are never exposed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai4bi.blocks.contracts import DataBlockContract


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MetricEntry:
    block_id: str
    metric_name: str
    display_name: str
    aggregation: str          # SUM / AVG / COUNT etc.
    description: str | None


@dataclass
class DimensionEntry:
    block_id: str
    column_name: str
    display_name: str
    data_type: str


@dataclass
class BlockCatalog:
    block_id: str
    display_name: str
    metrics: list[MetricEntry] = field(default_factory=list)
    dimensions: list[DimensionEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aggregation_from_formula(formula: str) -> str:
    """Extract the leading aggregation keyword from a metric formula string.

    Examples
    --------
    'SUM(move_count)'           → 'SUM'
    'AVG(queue_time_hr)'        → 'AVG'
    'SUM(good_die) / SUM(...)' → 'SUM'  (first token)
    """
    upper = formula.upper().strip()
    for agg in ("COUNT_DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX"):
        if upper.startswith(agg + "("):
            return agg
    return "SUM"  # fallback


def _certified_dim_targets(primary_block_id: str, semantic_model: dict) -> set[str]:
    """Return block_ids reachable from *primary_block_id* via certified relationships."""
    certified: set[str] = set()
    for rel in semantic_model.get("relationships", []):
        if (
            rel.get("from_block") == primary_block_id
            and rel.get("status") == "certified"
        ):
            certified.add(rel["to_block"])
    return certified


def _prohibited_pairs(semantic_model: dict) -> set[frozenset[str]]:
    """Return frozensets of block_id pairs that are explicitly prohibited."""
    pairs: set[frozenset[str]] = set()
    for entry in semantic_model.get("prohibited_paths", []):
        blocks = entry.get("blocks", [])
        if len(blocks) == 2:
            pairs.add(frozenset(blocks))
    return pairs


def _make_display_name(block_id: str) -> str:
    """Convert snake_case block_id to a human-friendly label."""
    return block_id.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_catalog(
    semantic_model: dict,
    contracts: dict[str, DataBlockContract],
) -> list[BlockCatalog]:
    """Build a list of BlockCatalog objects from the semantic model and loaded contracts.

    Parameters
    ----------
    semantic_model:
        Parsed content of ``semantic_model.json``.
    contracts:
        Mapping of block_id → DataBlockContract for all loaded blocks.

    Returns
    -------
    list[BlockCatalog]
        One entry per *fact* block that has at least one metric.  Each entry
        carries all metrics from that block plus all dimensions reachable via
        certified relationships (excluding prohibited paths).
    """
    prohibited = _prohibited_pairs(semantic_model)
    result: list[BlockCatalog] = []

    # Identify fact blocks that own at least one metric in the semantic model.
    sm_metrics_by_block: dict[str, list[dict]] = {}
    for m in semantic_model.get("metrics", []):
        owner = m.get("owner_block", "")
        sm_metrics_by_block.setdefault(owner, []).append(m)

    for primary_block_id, sm_metric_list in sm_metrics_by_block.items():
        primary_contract = contracts.get(primary_block_id)
        if primary_contract is None:
            continue  # block not loaded — skip silently

        # Build metric entries from the contract's metric definitions
        # (semantic_model provides ownership metadata; contract provides formula detail).
        contract_metrics_by_name = {m.name: m for m in primary_contract.metrics}

        metric_entries: list[MetricEntry] = []
        for sm_metric in sm_metric_list:
            metric_id = sm_metric.get("metric_id", "")
            # Prefer contract formula; fall back to semantic model formula.
            contract_metric = contract_metrics_by_name.get(metric_id)
            formula = (
                contract_metric.formula
                if contract_metric is not None
                else sm_metric.get("formula", "SUM(unknown)")
            )
            aggregation = _aggregation_from_formula(formula)
            description = contract_metric.description if contract_metric else None
            metric_entries.append(
                MetricEntry(
                    block_id=primary_block_id,
                    metric_name=metric_id,
                    display_name=_make_display_name(metric_id),
                    aggregation=aggregation,
                    description=description,
                )
            )

        # Dimensions: columns on the primary block itself (self-dimensions).
        dim_entries: list[DimensionEntry] = []
        for col in primary_contract.columns:
            dim_entries.append(
                DimensionEntry(
                    block_id=primary_block_id,
                    column_name=col.name,
                    display_name=_make_display_name(col.name),
                    data_type=col.data_type,
                )
            )

        # Dimensions: certified related dimension blocks.
        certified_targets = _certified_dim_targets(primary_block_id, semantic_model)
        for target_block_id in sorted(certified_targets):  # sorted for determinism
            # Skip prohibited combinations.
            if frozenset({primary_block_id, target_block_id}) in prohibited:
                continue
            target_contract = contracts.get(target_block_id)
            if target_contract is None:
                continue
            for col in target_contract.columns:
                dim_entries.append(
                    DimensionEntry(
                        block_id=target_block_id,
                        column_name=col.name,
                        display_name=f"{_make_display_name(target_block_id)}: {_make_display_name(col.name)}",
                        data_type=col.data_type,
                    )
                )

        catalog = BlockCatalog(
            block_id=primary_block_id,
            display_name=_make_display_name(primary_block_id),
            metrics=metric_entries,
            dimensions=dim_entries,
        )
        result.append(catalog)

    # Sort by block_id for stable ordering.
    result.sort(key=lambda bc: bc.block_id)
    return result
