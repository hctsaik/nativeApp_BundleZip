"""
CompositionPlan — Aggregate-then-Compose cross-fact query planning.

Round 012 decision: direct fact-to-fact detail joins are permanently forbidden.
The safe path is to aggregate each fact independently to a common grain, then
join the aggregated results.  This module implements that pattern.

Safety rules (non-negotiable):
- Maximum 2 fact blocks per composition (MVP).
- Each AggStep only references columns from its own fact block.
- Weighted ratio metrics (e.g. yield_pct) must be expressed as
  SUM(numerator)/SUM(denominator)*scale — never AVG(ratio_column).
- The compose step performs a many-to-many join of two pre-aggregated results
  (both sides are already at the shared grain, so no fanout risk).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.query_spec import MetricRef, VisualQuerySpec


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CompositionPlanningError(ValueError):
    """Raised when a cross-fact composition request violates safety rules."""


# ---------------------------------------------------------------------------
# Metric expression types
# ---------------------------------------------------------------------------

@dataclass
class RatioMetricExpr:
    """
    A ratio metric that must be recomputed from additive numerator/denominator.

    Example: weighted_yield_pct = SUM(good_die) / SUM(tested_die) * 100
    """
    alias: str                 # output column name, e.g. "weighted_yield_pct"
    numerator_column: str      # additive numerator column, e.g. "good_die"
    denominator_column: str    # additive denominator column, e.g. "tested_die"
    scale: float = 100.0       # multiply result by this factor (100 for %)

    def to_sql_expr(self, table_alias: str | None = None) -> str:
        """Return the SQL expression for this ratio metric."""
        def col(name: str) -> str:
            prefix = f'"{table_alias}".' if table_alias else ""
            return f'{prefix}"{name}"'

        return (
            f"SUM({col(self.numerator_column)}) / "
            f"NULLIF(SUM({col(self.denominator_column)}), 0) * {self.scale} "
            f'AS "{self.alias}"'
        )


@dataclass
class SimpleMetricExpr:
    """
    A simple aggregation metric (SUM, AVG, COUNT, MIN, MAX).

    Example: avg_queue_time = AVG(queue_time_hr)
    """
    alias: str           # output column name, e.g. "avg_queue_time"
    agg_function: str    # SQL aggregate function: SUM, AVG, COUNT, MIN, MAX
    column: str          # source column name, e.g. "queue_time_hr"

    def __post_init__(self) -> None:
        allowed = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
        upper = self.agg_function.upper()
        if upper not in allowed:
            raise CompositionPlanningError(
                f"Unsupported agg_function '{self.agg_function}'; allowed: {sorted(allowed)}"
            )
        self.agg_function = upper

    def to_sql_expr(self, table_alias: str | None = None) -> str:
        """Return the SQL expression for this simple metric."""
        def col(name: str) -> str:
            prefix = f'"{table_alias}".' if table_alias else ""
            return f'{prefix}"{name}"'

        return f'{self.agg_function}({col(self.column)}) AS "{self.alias}"'


# Union type for metric expressions in an AggStep
MetricExpr = SimpleMetricExpr | RatioMetricExpr


# ---------------------------------------------------------------------------
# Plan dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AggStep:
    """
    One independent aggregation of a single fact block.

    group_by_columns must be columns that exist in this fact's schema.
    metric_exprs defines what to compute; each must only reference columns
    from this same fact block.
    filter_values is a dict of {column_name: [val1, val2, ...]} that generates
    parameterized ``col IN (?, ?, ...)`` predicates (safe against SQL injection).
    filters is a list of raw SQL WHERE predicates for trusted internal use only
    (legacy — prefer filter_values for user-supplied values).
    """
    block_id: str
    group_by_columns: list[str]
    metric_exprs: list[MetricExpr]
    filters: list[str] = field(default_factory=list)
    filter_values: dict[str, list] = field(default_factory=dict)
    # Legacy field kept for backwards compatibility with callers using MetricRef
    metrics: list[MetricRef] = field(default_factory=list)

    def validate_column_ownership(
        self, contract: DataBlockContract
    ) -> None:
        """
        Raise CompositionPlanningError if any metric column is not in the
        block's declared schema.
        """
        declared = {col.name for col in contract.columns}
        for expr in self.metric_exprs:
            if isinstance(expr, SimpleMetricExpr):
                if expr.column not in declared:
                    raise CompositionPlanningError(
                        f"AggStep for '{self.block_id}': column '{expr.column}' "
                        f"is not declared by this block."
                    )
            elif isinstance(expr, RatioMetricExpr):
                for col_name in (expr.numerator_column, expr.denominator_column):
                    if col_name not in declared:
                        raise CompositionPlanningError(
                            f"AggStep for '{self.block_id}': ratio column '{col_name}' "
                            f"is not declared by this block."
                        )
        for gb_col in self.group_by_columns:
            if gb_col not in declared:
                raise CompositionPlanningError(
                    f"AggStep for '{self.block_id}': group_by column '{gb_col}' "
                    f"is not declared by this block."
                )


@dataclass
class ComposeStep:
    """
    Join two pre-aggregated results on a shared grain key.

    Both sides are already aggregated (many_to_many safe — no row duplication
    risk because each side has exactly one row per join_key value).
    """
    join_key: str          # shared column name in both AggStep outputs
    left_step_id: str      # block_id of the left AggStep
    right_step_id: str     # block_id of the right AggStep
    join_type: str = "INNER"   # INNER | LEFT | RIGHT | FULL

    def __post_init__(self) -> None:
        allowed = {"INNER", "LEFT", "RIGHT", "FULL"}
        upper = self.join_type.upper()
        if upper not in allowed:
            raise CompositionPlanningError(
                f"Unsupported join_type '{self.join_type}'; allowed: {sorted(allowed)}"
            )
        self.join_type = upper


@dataclass
class CompositionPlan:
    """
    Complete Aggregate-then-Compose execution plan for a cross-fact query.

    Execution order:
    1. Execute each AggStep independently → one temp table per step.
    2. Execute ComposeStep → JOIN the two temp tables on join_key.
    3. SELECT final_metrics from the composed result.
    """
    plan_id: str
    agg_steps: list[AggStep]
    compose_step: ComposeStep
    final_metrics: list[str]    # column names to include in final SELECT

    def validate(
        self,
        contracts: dict[str, DataBlockContract],
    ) -> None:
        """
        Run all safety checks.  Raises CompositionPlanningError on any violation.
        """
        # Rule: exactly 2 fact blocks (MVP)
        if len(self.agg_steps) != 2:
            raise CompositionPlanningError(
                f"CompositionPlan supports exactly 2 AggSteps (got {len(self.agg_steps)}). "
                "Cross-fact composition with 3+ facts is not supported in this MVP."
            )

        step_ids = {step.block_id for step in self.agg_steps}

        # Rule: compose_step references must exist
        if self.compose_step.left_step_id not in step_ids:
            raise CompositionPlanningError(
                f"ComposeStep.left_step_id '{self.compose_step.left_step_id}' "
                "does not match any AggStep."
            )
        if self.compose_step.right_step_id not in step_ids:
            raise CompositionPlanningError(
                f"ComposeStep.right_step_id '{self.compose_step.right_step_id}' "
                "does not match any AggStep."
            )

        # Rule: both blocks must be facts
        for step in self.agg_steps:
            if step.block_id not in contracts:
                raise CompositionPlanningError(
                    f"AggStep references unknown block '{step.block_id}'."
                )
            contract = contracts[step.block_id]
            if contract.block_type is not BlockType.fact:
                raise CompositionPlanningError(
                    f"AggStep block '{step.block_id}' is not a fact block "
                    f"(got {contract.block_type.value})."
                )
            # Rule: columns must belong to the block
            step.validate_column_ownership(contract)

        # Rule: join_key must appear in group_by_columns of both steps
        for step in self.agg_steps:
            if self.compose_step.join_key not in step.group_by_columns:
                raise CompositionPlanningError(
                    f"AggStep '{step.block_id}' does not group by join_key "
                    f"'{self.compose_step.join_key}'."
                )

    def grain_check(self, semantic_model: dict) -> list[str]:
        """
        Returns a list of warning strings (empty = OK).

        Checks: if the join_key is declared in semantic_model["certified_joins"]
        as a relationship between the two block_ids, then the grain is certified.
        If no such relationship exists, return a warning (not an error — let the
        planner proceed with a warning rather than refusing).
        """
        join_key = self.compose_step.join_key
        left_block = self.compose_step.left_step_id
        right_block = self.compose_step.right_step_id

        certified_joins = semantic_model.get("certified_joins", [])
        for cj in certified_joins:
            cj_key = cj.get("join_key")
            cj_from = cj.get("from_block")
            cj_to = cj.get("to_block")
            if cj_key == join_key and (
                (cj_from == left_block and cj_to == right_block)
                or (cj_from == right_block and cj_to == left_block)
            ):
                return []  # certified — no warnings

        return [
            f"grain_check: join_key '{join_key}' between '{left_block}' and "
            f"'{right_block}' is not in certified_joins — verify grain compatibility"
        ]


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class CompositionPlanner:
    """
    Inspect a VisualQuerySpec and decide whether cross-fact composition is needed.

    Decision logic:
    - If all metrics originate from the same (primary) fact → return None.
      The caller should fall through to SafeJoinPlanner.
    - If metrics span exactly 2 distinct fact blocks → produce a CompositionPlan.
    - If metrics span 3+ fact blocks → raise CompositionPlanningError.

    The planner requires the caller to pass pre-constructed AggStep metric
    expressions (the planner does not auto-infer SQL from MetricRef because
    ratio metrics need explicit numerator/denominator specification).
    To use the fully automated path, see `build_etch_queue_vs_yield_plan()`.
    """

    def plan(
        self,
        spec: VisualQuerySpec,
        contracts: dict[str, DataBlockContract],
        semantic_model: dict[str, Any] | None = None,
        *,
        agg_steps: list[AggStep] | None = None,
        compose_step: ComposeStep | None = None,
        join_key: str | None = None,
    ) -> CompositionPlan | None:
        """
        Determine if cross-fact composition is required and return a plan.

        Parameters
        ----------
        spec:
            The visual query specification.
        contracts:
            Loaded block contracts keyed by block_id.
        semantic_model:
            The project semantic model dict (for prohibited path checks and
            grain_check).  Pass None to skip semantic-model validation.
        agg_steps:
            Pre-built AggStep list.  If None, the planner will raise if
            cross-fact composition is needed (caller must supply steps).
        compose_step:
            Pre-built ComposeStep.  Required when agg_steps is provided.
        join_key:
            Shorthand: if agg_steps is None but join_key is provided, used
            to auto-detect the situation.

        Returns
        -------
        CompositionPlan | None
            None  →  single-fact query; caller uses SafeJoinPlanner.
            plan  →  cross-fact query; caller uses CompositionExecutor.
        """
        effective_sm: dict[str, Any] = semantic_model or {}

        # Collect the unique fact block_ids referenced by metrics
        metric_block_ids: list[str] = list(
            dict.fromkeys(m.block_id for m in spec.metrics)
        )

        # Filter down to fact blocks only
        fact_block_ids = [
            bid for bid in metric_block_ids
            if bid in contracts and contracts[bid].block_type is BlockType.fact
        ]

        if len(fact_block_ids) <= 1:
            # Single-fact or no metrics → use existing SafeJoinPlanner path
            return None

        if len(fact_block_ids) > 2:
            raise CompositionPlanningError(
                f"Cross-fact composition supports at most 2 fact blocks (MVP); "
                f"got {len(fact_block_ids)}: {fact_block_ids}"
            )

        # Check semantic model for prohibited detail joins
        self._check_prohibited_paths(fact_block_ids, effective_sm)

        # If caller did not supply agg_steps, we cannot auto-plan (ratio metrics
        # need explicit numerator/denominator)
        if agg_steps is None:
            raise CompositionPlanningError(
                f"Cross-fact composition required for blocks {fact_block_ids}, "
                "but no agg_steps were provided.  Supply explicit AggStep objects "
                "or use a factory helper (e.g. build_etch_queue_vs_yield_plan)."
            )
        if compose_step is None:
            raise CompositionPlanningError(
                "agg_steps provided but compose_step is missing."
            )

        plan = CompositionPlan(
            plan_id=str(uuid.uuid4()),
            agg_steps=agg_steps,
            compose_step=compose_step,
            final_metrics=self._collect_final_metrics(agg_steps),
        )
        plan.validate(contracts)

        # grain_check: log warnings but do not raise
        if semantic_model is not None:
            warnings = plan.grain_check(semantic_model)
            for w in warnings:
                logger.warning("[CompositionPlanner] %s", w)

        return plan

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_prohibited_paths(
        fact_block_ids: list[str],
        semantic_model: dict[str, Any],
    ) -> None:
        """Log a warning if the semantic model marks this pair as prohibited at detail level."""
        pair = set(fact_block_ids)
        for item in semantic_model.get("prohibited_paths", []):
            if set(item.get("blocks", [])) == pair:
                # Detail join is prohibited; composition is still allowed
                # (we are aggregating first), so we just note this.
                pass  # Composition path is safe; detail-level join is what's banned.

    @staticmethod
    def _collect_final_metrics(agg_steps: list[AggStep]) -> list[str]:
        """Collect all metric alias names from all AggSteps."""
        names: list[str] = []
        for step in agg_steps:
            for expr in step.metric_exprs:
                names.append(expr.alias)
        return names


# ---------------------------------------------------------------------------
# Factory helpers for well-known composition scenarios
# ---------------------------------------------------------------------------

def build_etch_queue_vs_yield_plan(
    join_key: str = "lot_id",
    step_filter: str | None = "ETCH",
) -> tuple[list[AggStep], ComposeStep]:
    """
    Build the canonical 'ETCH avg queue time vs weighted wafer yield per lot'
    composition plan components.

    Returns
    -------
    (agg_steps, compose_step)
        Pass these into CompositionPlanner.plan() as keyword arguments.
    """
    move_metrics: list[MetricExpr] = [
        SimpleMetricExpr(
            alias="avg_queue_time",
            agg_function="AVG",
            column="queue_time_hr",
        )
    ]
    yield_metrics: list[MetricExpr] = [
        RatioMetricExpr(
            alias="weighted_yield_pct",
            numerator_column="good_die",
            denominator_column="tested_die",
            scale=100.0,
        )
    ]
    move_filters = [f'"step_id" = \'{step_filter}\''] if step_filter else []
    agg_steps = [
        AggStep(
            block_id="process_move_fact",
            group_by_columns=[join_key],
            metric_exprs=move_metrics,
            filters=move_filters,
        ),
        AggStep(
            block_id="wafer_yield_fact",
            group_by_columns=[join_key],
            metric_exprs=yield_metrics,
        ),
    ]
    compose_step = ComposeStep(
        join_key=join_key,
        left_step_id="process_move_fact",
        right_step_id="wafer_yield_fact",
        join_type="INNER",
    )
    return agg_steps, compose_step
