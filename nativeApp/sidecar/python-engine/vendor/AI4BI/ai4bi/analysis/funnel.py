"""Funnel analysis — Round 063.

A repeat-purchase funnel from existing rows: how many customers bought at least
1, 2, 3, ... times. Pure pandas; the result feeds a Plotly funnel chart.
"""

from __future__ import annotations

import pandas as pd

_DEFAULT_STAGES = (1, 2, 3, 5, 10)


def purchase_frequency_funnel(
    df: pd.DataFrame,
    customer_col: str,
    stages: tuple[int, ...] = _DEFAULT_STAGES,
) -> pd.DataFrame:
    """Return a funnel DataFrame [stage, customers, pct] of repeat-purchase depth.

    customers[stage] = # of customers whose row count >= stage.
    pct = customers / customers-at-first-stage * 100.
    """
    stages = tuple(sorted({int(s) for s in stages if int(s) >= 1})) or (1,)
    if df.empty or customer_col not in df.columns:
        return pd.DataFrame(columns=["stage", "customers", "pct"])

    counts = df.groupby(customer_col).size()
    top = int((counts >= stages[0]).sum())
    rows = []
    for s in stages:
        n = int((counts >= s).sum())
        rows.append({
            "stage": f"≥{s} 次",
            "customers": n,
            "pct": round(n / top * 100, 1) if top else 0.0,
        })
    return pd.DataFrame(rows)
