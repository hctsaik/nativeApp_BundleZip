"""
CompositionExecutor — Execute Aggregate-then-Compose cross-fact plans.

Round 012 safety contract:
- Never JOIN fact tables at detail (row) level.
- Each fact is first aggregated to the shared grain (e.g. lot_id).
- Only then are the aggregated results joined.
- Ratio metrics (e.g. weighted yield) are always computed as
  SUM(numerator)/SUM(denominator)*scale — never AVG(ratio_column).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from ai4bi.blocks.loader import BlockLoader
from ai4bi.planning.composition_plan import (
    AggStep,
    CompositionPlan,
    CompositionPlanningError,
    RatioMetricExpr,
    SimpleMetricExpr,
)

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "blocks"


# ---------------------------------------------------------------------------
# SQL builder helpers
# ---------------------------------------------------------------------------

def _build_agg_sql(
    step: AggStep,
    registered_table: str,
    step_alias: str,
) -> tuple[str, list]:
    """
    Build a SQL CTE fragment that aggregates one fact to the shared grain.

    Returns a tuple of (sql_fragment, params) where sql_fragment uses ``?``
    placeholders for filter values and params is the ordered list of values.
    Pass the combined params list to ``con.execute(final_sql, params)``.

    Example output (for process_move_fact, group_by=[lot_id]):
        agg_process_move_fact AS (
            SELECT
                "lot_id",
                AVG("queue_time_hr") AS "avg_queue_time"
            FROM "process_move_fact"
            GROUP BY "lot_id"
        )
    """
    gb_cols = ", ".join(f'"{col}"' for col in step.group_by_columns)
    select_cols = [gb_cols]

    for expr in step.metric_exprs:
        if isinstance(expr, SimpleMetricExpr):
            select_cols.append(
                f'{expr.agg_function}("{expr.column}") AS "{expr.alias}"'
            )
        elif isinstance(expr, RatioMetricExpr):
            select_cols.append(
                f'SUM("{expr.numerator_column}") / '
                f'NULLIF(SUM("{expr.denominator_column}"), 0) * {expr.scale} '
                f'AS "{expr.alias}"'
            )
        else:
            raise CompositionPlanningError(
                f"Unknown metric expression type: {type(expr).__name__}"
            )

    select_clause = ",\n        ".join(select_cols)

    # Build parameterized WHERE clause from AggStep.filter_values (dict[str, list]).
    # Raw string filters (legacy AggStep.filters list) are kept for backward
    # compatibility but should not be used for user-supplied values.
    params: list = []
    where_parts: list[str] = []

    # New parameterized filters from filter_values dict
    for col, vals in (step.filter_values or {}).items():
        placeholders = ", ".join("?" for _ in vals)
        where_parts.append(f'"{col}" IN ({placeholders})')
        params.extend(vals)

    # Legacy raw-string filters (not parameterized — only for trusted internal use)
    where_parts.extend(step.filters)

    where_clause = ""
    if where_parts:
        where_clause = "\n    WHERE " + "\n      AND ".join(where_parts)

    sql_fragment = (
        f"{step_alias} AS (\n"
        f"    SELECT\n"
        f"        {select_clause}\n"
        f"    FROM \"{registered_table}\"{where_clause}\n"
        f"    GROUP BY {gb_cols}\n"
        f")"
    )
    return sql_fragment, params


def _build_compose_sql(
    plan: CompositionPlan,
    left_alias: str,
    right_alias: str,
) -> str:
    """
    Build the final SELECT SQL that joins the two aggregated CTEs.

    The join_key is selected from the left CTE to avoid ambiguity.
    All metric columns from both CTEs are included.
    """
    compose = plan.compose_step
    join_key = compose.join_key

    # Collect all metric aliases from each step
    left_step = next(s for s in plan.agg_steps if s.block_id == compose.left_step_id)
    right_step = next(s for s in plan.agg_steps if s.block_id == compose.right_step_id)

    select_parts = [f'"{left_alias}"."{join_key}"']
    for expr in left_step.metric_exprs:
        select_parts.append(f'"{left_alias}"."{expr.alias}"')
    for expr in right_step.metric_exprs:
        select_parts.append(f'"{right_alias}"."{expr.alias}"')

    select_clause = ",\n    ".join(select_parts)
    return (
        f"SELECT\n"
        f"    {select_clause}\n"
        f"FROM \"{left_alias}\"\n"
        f"{compose.join_type} JOIN \"{right_alias}\"\n"
        f'    ON "{left_alias}"."{join_key}" = "{right_alias}"."{join_key}"'
    )


# ---------------------------------------------------------------------------
# CompositionExecutor
# ---------------------------------------------------------------------------

class CompositionExecutor:
    """
    Execute a CompositionPlan against registered DuckDB tables.

    The executor:
    1. Validates the plan (calls plan.validate).
    2. Generates one CTE per AggStep — each independently aggregates its fact.
    3. Composes the CTEs with a JOIN on the shared grain key.
    4. Returns the result as a pandas DataFrame.

    No detail-level fact-to-fact join is ever performed.
    """

    def __init__(
        self,
        registry_root: Optional[str | Path] = None,
        loader: Optional[BlockLoader] = None,
    ) -> None:
        self._registry_root = Path(registry_root) if registry_root else _DEFAULT_REGISTRY
        self._loader = loader or BlockLoader()

    def run(
        self,
        plan: CompositionPlan,
        con: duckdb.DuckDBPyConnection,
        registered_tables: dict[str, str],
    ) -> pd.DataFrame:
        """
        Execute the CompositionPlan.

        Parameters
        ----------
        plan:
            The validated CompositionPlan.
        con:
            Open DuckDB connection with fact tables already registered.
        registered_tables:
            Mapping of block_id → DuckDB table name.
            Example: {"process_move_fact": "process_move_fact", "wafer_yield_fact": "wafer_yield_fact"}

        Returns
        -------
        pd.DataFrame
            One row per join_key value, with all metrics from both facts.

        Raises
        ------
        CompositionPlanningError
            If any safety rule is violated.
        """
        # Verify all required tables are registered
        for step in plan.agg_steps:
            if step.block_id not in registered_tables:
                raise CompositionPlanningError(
                    f"Block '{step.block_id}' is not in registered_tables. "
                    f"Available: {list(registered_tables.keys())}"
                )

        # Build CTE aliases (safe names for DuckDB identifiers)
        cte_aliases: dict[str, str] = {}
        for step in plan.agg_steps:
            cte_aliases[step.block_id] = f"agg_{step.block_id}"

        # Build CTE fragments (parameterized)
        cte_parts: list[str] = []
        all_params: list = []
        for step in plan.agg_steps:
            registered_name = registered_tables[step.block_id]
            step_alias = cte_aliases[step.block_id]
            cte_sql, step_params = _build_agg_sql(step, registered_name, step_alias)
            cte_parts.append(cte_sql)
            all_params.extend(step_params)

        # Build the final compose SELECT
        left_alias = cte_aliases[plan.compose_step.left_step_id]
        right_alias = cte_aliases[plan.compose_step.right_step_id]
        compose_sql = _build_compose_sql(plan, left_alias, right_alias)

        # Assemble full SQL with CTEs
        with_clause = "WITH\n" + ",\n".join(cte_parts)
        full_sql = f"{with_clause}\n{compose_sql}"

        logger.debug("[composition_executor] SQL:\n%s", full_sql)

        return con.execute(full_sql, all_params).df()

    def run_from_registry(
        self,
        plan: CompositionPlan,
        blocks_dir: Optional[str | Path] = None,
    ) -> pd.DataFrame:
        """
        Convenience method: load blocks from the JSON registry, register them
        into a fresh DuckDB connection, and execute the plan.

        Parameters
        ----------
        plan:
            The validated CompositionPlan.
        blocks_dir:
            Directory containing the block JSON files.  Defaults to registry_root.

        Returns
        -------
        pd.DataFrame
        """
        effective_dir = Path(blocks_dir) if blocks_dir else self._registry_root
        con = duckdb.connect(database=":memory:")
        registered: dict[str, str] = {}
        try:
            for step in plan.agg_steps:
                json_path = effective_dir / f"{step.block_id}.json"
                contract = self._loader.load_json(str(json_path))
                self._loader.register_to_duckdb(contract, step.block_id, con)
                registered[step.block_id] = step.block_id

            return self.run(plan, con, registered)
        finally:
            con.close()
