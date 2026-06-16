"""Cross-fact composition convenience — Round 055.

Wires the existing (but previously UI-orphaned) CompositionExecutor /
CompositionPlanner into a simple two-metric-ratio helper, so a retail owner can
ask cross-table questions like "revenue per employee" — sales (one fact) ÷
headcount (another fact), joined on store — which single-fact GROUP BY cannot do.

Safety is unchanged: each fact is aggregated to the shared grain independently,
then the two aggregates are joined (no detail-level fact-to-fact join).
"""

from __future__ import annotations

import uuid
from typing import Optional

import duckdb
import pandas as pd

from ai4bi.analysis.composition_executor import CompositionExecutor
from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.blocks.loader import BlockLoader
from ai4bi.planning.composition_plan import (
    AggStep, ComposeStep, CompositionPlan, SimpleMetricExpr,
)


def shared_columns(a: DataBlockContract, b: DataBlockContract) -> list[str]:
    """Column names present in both blocks (candidate join keys)."""
    bcols = {c.name for c in b.columns}
    return [c.name for c in a.columns if c.name in bcols]


def combine(a: pd.Series, b: pd.Series, op: str) -> pd.Series:
    """Combine two aggregated columns. op ∈ {ratio, diff, margin_pct}."""
    if op == "diff":
        return (a - b)
    if op == "margin_pct":
        return ((a - b) / a.replace(0, pd.NA) * 100.0)
    # default ratio
    return a / b.replace(0, pd.NA)


def compose_two_facts(
    contracts: dict[str, DataBlockContract],
    *,
    block_a: str, agg_a: str, col_a: str, alias_a: str,
    block_b: str, agg_b: str, col_b: str, alias_b: str,
    join_key: str,
    ratio_alias: Optional[str] = None,
    op: str = "ratio",
) -> pd.DataFrame:
    """Aggregate two facts to ``join_key`` and join; optionally add a combined column.

    ``op`` selects how the two aggregates combine into ``ratio_alias``:
      - "ratio":      A / B
      - "diff":       A − B
      - "margin_pct": (A − B) / A * 100   (e.g. contribution margin %)

    Returns a DataFrame: [join_key, alias_a, alias_b, (ratio_alias)].
    Raises CompositionPlanningError if the plan violates safety rules.
    """
    agg_steps = [
        AggStep(block_id=block_a, group_by_columns=[join_key],
                metric_exprs=[SimpleMetricExpr(alias=alias_a, agg_function=agg_a, column=col_a)]),
        AggStep(block_id=block_b, group_by_columns=[join_key],
                metric_exprs=[SimpleMetricExpr(alias=alias_b, agg_function=agg_b, column=col_b)]),
    ]
    compose = ComposeStep(join_key=join_key, left_step_id=block_a,
                          right_step_id=block_b, join_type="INNER")
    plan = CompositionPlan(
        plan_id=str(uuid.uuid4()), agg_steps=agg_steps, compose_step=compose,
        final_metrics=[alias_a, alias_b],
    )
    plan.validate(contracts)

    loader = BlockLoader()
    con = duckdb.connect(database=":memory:")
    try:
        registered: dict[str, str] = {}
        for bid in (block_a, block_b):
            loader.register_to_duckdb(contracts[bid], bid, con)
            registered[bid] = bid
        df = CompositionExecutor().run(plan, con, registered)
    finally:
        con.close()

    if ratio_alias and alias_a in df.columns and alias_b in df.columns:
        df[ratio_alias] = combine(df[alias_a], df[alias_b], op).astype(float).round(2)
    return df
