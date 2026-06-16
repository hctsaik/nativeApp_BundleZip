"""Conservative join planning for governed DataBlock queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai4bi.blocks.contracts import BlockType, DataBlockContract, FanoutRisk, JoinType
from ai4bi.query_spec import VisualQuerySpec


class QueryPlanningError(ValueError):
    """Raised when a visual requests a query outside the certified model."""


@dataclass(frozen=True)
class ResolvedJoin:
    """One direct, certified fact-to-dimension join."""

    relationship_id: str
    from_block: str
    to_block: str
    key_pairs: tuple[tuple[str, str], ...]
    cardinality: str = "many_to_one"
    certification_status: str = "certified"


class SafeJoinPlanner:
    """Allow only direct certified many-to-one left joins from one fact."""

    def __init__(self, semantic_model: dict[str, Any] | None = None) -> None:
        self._semantic_model = semantic_model or {}

    def resolve(
        self,
        spec: VisualQuerySpec,
        contracts: dict[str, DataBlockContract],
    ) -> list[ResolvedJoin]:
        block_ids = spec.all_block_ids
        if len(block_ids) != len(set(block_ids)):
            raise QueryPlanningError("A visual may not reference the same block twice.")

        referenced_ids = {
            *(metric.block_id for metric in spec.metrics),
            *(dimension.block_id for dimension in spec.dimensions),
            *(filter_spec.block_id for filter_spec in spec.filters),
        }
        unregistered = referenced_ids - set(block_ids)
        if unregistered:
            raise QueryPlanningError(
                f"Query fields reference blocks not included in block_refs: {sorted(unregistered)}"
            )

        primary_id = spec.primary_block_id
        primary = contracts[primary_id]
        for metric in spec.metrics:
            if metric.block_id != primary_id:
                raise QueryPlanningError(
                    "Metrics must originate from the primary fact block in this MVP."
                )

        if len(block_ids) == 1:
            return []
        if primary.block_type is not BlockType.fact:
            raise QueryPlanningError("Joined queries require one primary fact block.")
        if not self._semantic_model:
            raise QueryPlanningError("No semantic model is configured for joined queries.")

        resolved: list[ResolvedJoin] = []
        for secondary_id in block_ids[1:]:
            secondary = contracts[secondary_id]
            if secondary.block_type not in (BlockType.dimension, BlockType.date_dimension):
                raise QueryPlanningError(
                    f"Only dimensions can be joined to a primary fact; rejected '{secondary_id}'."
                )
            if secondary_id not in referenced_ids:
                # Round 163: self-heal. After a UI edit changes the group-by off a
                # joined dimension's column, that secondary block can be left
                # unreferenced. An unused join can't cause fan-out, so simply skip
                # it instead of crashing the visual.
                continue
            resolved.append(self._resolve_direct_relationship(primary, secondary))
        return resolved

    def _resolve_direct_relationship(
        self,
        primary: DataBlockContract,
        secondary: DataBlockContract,
    ) -> ResolvedJoin:
        matches = [
            relationship
            for relationship in self._semantic_model.get("relationships", [])
            if relationship.get("from_block") == primary.block_id
            and relationship.get("to_block") == secondary.block_id
            and relationship.get("status") == "certified"
            and relationship.get("cardinality") == "many_to_one"
            and relationship.get("join_type") == "left"
        ]
        if len(matches) != 1:
            raise QueryPlanningError(
                f"No single certified many-to-one left relationship from "
                f"'{primary.block_id}' to '{secondary.block_id}'."
            )

        hints = [
            hint for hint in primary.relationships
            if hint.target_block_id == secondary.block_id
            and hint.join_type is JoinType.left
            and hint.fanout_risk is FanoutRisk.LOW
        ]
        if len(hints) != 1:
            raise QueryPlanningError(
                f"Block contract does not approve a LOW-risk left join to '{secondary.block_id}'."
            )

        relationship = matches[0]
        pairs = tuple(
            (str(key["from"]), str(key["to"]))
            for key in relationship.get("keys", [])
        )
        if not pairs:
            raise QueryPlanningError(
                f"Certified relationship to '{secondary.block_id}' has no join keys."
            )

        primary_columns = {column.name for column in primary.columns}
        secondary_columns = {column.name for column in secondary.columns}
        approved_keys = set(hints[0].allowed_join_keys)
        for source_key, target_key in pairs:
            if source_key not in primary_columns or source_key not in approved_keys:
                raise QueryPlanningError(f"Unapproved source join key '{source_key}'.")
            if target_key not in secondary_columns or target_key not in secondary.primary_keys:
                raise QueryPlanningError(f"Unsafe target join key '{target_key}'.")

        return ResolvedJoin(
            relationship_id=str(relationship["relationship_id"]),
            from_block=primary.block_id,
            to_block=secondary.block_id,
            key_pairs=pairs,
            cardinality=relationship.get("cardinality", "many_to_one"),
            certification_status=relationship.get("certification_status", "certified"),
        )
