"""
Block Library — Data Block View for the sidebar (Round 021).

Design-council consensus (001-F, 002-E):
  Data Block View purpose: search/browse blocks, understand grain/metrics/
  compatibility/freshness/certification status.

Provides:
  - BlockCard: UI-ready summary of one DataBlockContract
  - build_block_library(): build all cards from loaded contracts
  - LIFECYCLE_BADGE: color + emoji map for lifecycle states
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai4bi.blocks.contracts import BlockType, DataBlockContract, LifecycleStatus


# ---------------------------------------------------------------------------
# Lifecycle badge config (002-E color rules)
# ---------------------------------------------------------------------------

LIFECYCLE_BADGE: dict[LifecycleStatus, dict] = {
    LifecycleStatus.certified:  {"emoji": "🔵", "label": "Certified",  "color": "#2563eb"},
    LifecycleStatus.validated:  {"emoji": "🟡", "label": "Validated",  "color": "#d97706"},
    LifecycleStatus.draft:      {"emoji": "⚪", "label": "Draft",      "color": "#6b7280"},
    LifecycleStatus.deprecated: {"emoji": "🔴", "label": "Deprecated", "color": "#dc2626"},
    LifecycleStatus.suspended:  {"emoji": "🟠", "label": "Suspended",  "color": "#ea580c"},
}

BLOCK_TYPE_ICON: dict[BlockType, str] = {
    BlockType.fact:           "📊",
    BlockType.snapshot_fact:  "📸",
    BlockType.target_fact:    "🎯",
    BlockType.dimension:      "🏷️",
    BlockType.date_dimension: "📅",
    BlockType.metric_set:     "📐",
    BlockType.derived_block:  "🔗",
    BlockType.relationship:   "↔️",
    BlockType.policy:         "🔒",
    BlockType.analysis:       "🔬",
}


# ---------------------------------------------------------------------------
# BlockCard dataclass
# ---------------------------------------------------------------------------

@dataclass
class RelationshipSummary:
    rel_id: str
    target_block_id: str
    cardinality: str
    status: str


@dataclass
class BlockCard:
    """UI-ready summary of one DataBlockContract."""

    block_id: str
    block_type: BlockType
    lifecycle: LifecycleStatus
    version: str
    description: str
    grain: str
    metric_names: list[str]
    column_names: list[str]
    relationships: list[RelationshipSummary]

    # Derived display helpers
    @property
    def type_icon(self) -> str:
        return BLOCK_TYPE_ICON.get(self.block_type, "📦")

    @property
    def lifecycle_badge(self) -> dict:
        return LIFECYCLE_BADGE.get(self.lifecycle, {"emoji": "❓", "label": "Unknown", "color": "#6b7280"})

    @property
    def is_certified(self) -> bool:
        return self.lifecycle == LifecycleStatus.certified

    @property
    def is_sandbox(self) -> bool:
        return self.lifecycle in (
            LifecycleStatus.draft,
            LifecycleStatus.validated,
        )

    @property
    def header(self) -> str:
        badge = self.lifecycle_badge
        return f"{self.type_icon} `{self.block_id}` {badge['emoji']} {badge['label']}"

    @property
    def summary_line(self) -> str:
        parts = [
            f"v{self.version}",
            self.block_type.value,
            f"{len(self.metric_names)} metric{'s' if len(self.metric_names) != 1 else ''}",
            f"{len(self.column_names)} col{'s' if len(self.column_names) != 1 else ''}",
        ]
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_block_library(
    contracts: dict[str, DataBlockContract],
    search_query: str = "",
) -> list[BlockCard]:
    """
    Build a list of BlockCards from loaded DataBlockContracts.

    Parameters
    ----------
    contracts : dict[str, DataBlockContract]
    search_query : str
        Optional filter string; case-insensitive match against block_id,
        block_type, and description.

    Returns
    -------
    list[BlockCard]
        Sorted: certified first, then by block_type, then by block_id.
    """
    q = search_query.strip().lower()
    cards: list[BlockCard] = []

    for block_id, contract in contracts.items():
        # Search filter
        if q and not (
            q in block_id.lower()
            or q in contract.block_type.value.lower()
            or q in (contract.description or "").lower()
        ):
            continue

        rels = [
            RelationshipSummary(
                rel_id=rel.target_block_id,  # RelationshipHint uses target_block_id as key
                target_block_id=rel.target_block_id,
                cardinality=str(rel.fanout_risk.value) if rel.fanout_risk else "unknown",
                status=str(rel.join_type.value) if rel.join_type else "unknown",
            )
            for rel in (contract.relationships or [])
        ]

        card = BlockCard(
            block_id=block_id,
            block_type=contract.block_type,
            lifecycle=contract.block_lifecycle,
            version=contract.version or "?",
            description=contract.description or "",
            grain=contract.grain or "",
            metric_names=[m.name for m in contract.metrics],
            column_names=[c.name for c in contract.columns],
            relationships=rels,
        )
        cards.append(card)

    # Sort: certified first, then by type, then alphabetically
    def _sort_key(c: BlockCard):
        lifecycle_order = {
            LifecycleStatus.certified:  0,
            LifecycleStatus.validated:  1,
            LifecycleStatus.draft:      2,
            LifecycleStatus.suspended:  3,
            LifecycleStatus.deprecated: 4,
        }
        return (lifecycle_order.get(c.lifecycle, 9), c.block_type.value, c.block_id)

    return sorted(cards, key=_sort_key)
