"""SPC-style control-limit outliers — Round 117.

"Which tools have queue time beyond the fab average ± kσ?" — a statistical
threshold, not a literal constant. Groups a measure by an entity, computes the
population mean and standard deviation across entities, and returns the entities
outside μ ± kσ. Pure pandas on a materialized fact.
"""

from __future__ import annotations

import pandas as pd


def control_limit_outliers(
    df: pd.DataFrame, entity_col: str, value_col: str, k: float = 3.0, agg: str = "mean",
) -> tuple[pd.DataFrame, dict]:
    """Return (outlier_table, limits).

    outlier_table: [entity_col, <value>, 偏離] for entities outside μ ± kσ,
    sorted by distance. limits: {mean, sigma, ucl, lcl, k, n}. Empty table when
    there's no spread or too few groups.
    """
    if entity_col not in df.columns or value_col not in df.columns:
        return pd.DataFrame(), {}
    work = df[[entity_col, value_col]].dropna()
    if work.empty:
        return pd.DataFrame(), {}
    grouped = (work.groupby(entity_col)[value_col].mean() if agg == "mean"
               else work.groupby(entity_col)[value_col].sum())
    if len(grouped) < 3:
        return pd.DataFrame(), {}
    mu = float(grouped.mean())
    sigma = float(grouped.std(ddof=0))
    if sigma == 0 or pd.isna(sigma):
        return pd.DataFrame(), {}
    ucl, lcl = mu + k * sigma, mu - k * sigma
    out = grouped[(grouped > ucl) | (grouped < lcl)]
    rows = []
    for ent, val in out.sort_values(ascending=False).items():
        rows.append({
            entity_col: ent,
            value_col: round(float(val), 3),
            "偏離": "偏高 ↑" if val > ucl else "偏低 ↓",
            "離均(σ)": round((val - mu) / sigma, 2),
        })
    limits = {"mean": round(mu, 3), "sigma": round(sigma, 3),
              "ucl": round(ucl, 3), "lcl": round(lcl, 3), "k": k, "n": int(len(grouped))}
    return pd.DataFrame(rows), limits
