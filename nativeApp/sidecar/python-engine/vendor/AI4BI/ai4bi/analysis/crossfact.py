"""Cross-fact analytics — Round 116.

The executor is single-fact, so a question that spans two facts (queue time in
process_move_fact, yield in wafer_yield_fact) can't be one query. This aligns the
two facts on a shared key (each aggregated independently, then joined — the safe
compose pattern) and runs cross-fact analytics on the aligned frame:

  * correlate_facts   — Pearson r between metric A and metric B per key
                        ("is high ETCH queue time linked to low yield, by lot?")
  * cohort_by_quantile— bucket keys by metric A's quantile, average metric B
                        ("worst-cycle-time 20% of lots — how much yield drop?")
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from ai4bi.analysis.cross_fact import compose_two_facts
from ai4bi.blocks.contracts import DataBlockContract


def align_two_facts(
    contracts: dict[str, DataBlockContract], *,
    block_a: str, col_a: str, agg_a: str, alias_a: str,
    block_b: str, col_b: str, agg_b: str, alias_b: str,
    join_key: str,
) -> pd.DataFrame:
    """Aggregate each fact to ``join_key`` and inner-join → [key, A, B]."""
    return compose_two_facts(
        contracts,
        block_a=block_a, agg_a=agg_a, col_a=col_a, alias_a=alias_a,
        block_b=block_b, agg_b=agg_b, col_b=col_b, alias_b=alias_b,
        join_key=join_key, ratio_alias=None, op="ratio",
    ).drop(columns=[c for c in ["ratio"] if "ratio" in []], errors="ignore")


def correlate_facts(merged: pd.DataFrame, a_alias: str, b_alias: str) -> Optional[dict]:
    """Pearson correlation between two aligned metric columns.

    Returns {r, n, direction, strength} or None when not computable.
    """
    if merged is None or a_alias not in merged.columns or b_alias not in merged.columns:
        return None
    pair = merged[[a_alias, b_alias]].dropna()
    if len(pair) < 3 or pair[a_alias].nunique() < 2 or pair[b_alias].nunique() < 2:
        return None
    r = float(pair[a_alias].corr(pair[b_alias]))
    if pd.isna(r):
        return None
    mag = abs(r)
    strength = ("很強" if mag >= 0.7 else "中等" if mag >= 0.4
                else "微弱" if mag >= 0.2 else "幾乎無")
    direction = "正" if r > 0 else "負"
    return {"r": round(r, 3), "n": int(len(pair)), "direction": direction, "strength": strength}


def commonality(
    detail_df: pd.DataFrame, entity_col: str, group_col: str, qualifying_groups: set,
) -> pd.DataFrame:
    """Round 117: which entity (tool) is common to a set of qualifying groups (lots)?

    Classic fab commonality: given the set of failing lots, find tools that the
    most of them passed through. Returns [entity_col, 涉及批數, 涵蓋率%] sorted
    most-shared first. Empty when nothing qualifies.
    """
    if (detail_df is None or entity_col not in detail_df.columns
            or group_col not in detail_df.columns or not qualifying_groups):
        return pd.DataFrame()
    qualifying = set(qualifying_groups)
    sub = detail_df[detail_df[group_col].isin(qualifying)]
    if sub.empty:
        return pd.DataFrame()
    n_fail = len(qualifying)
    n_all = detail_df[group_col].nunique()
    fail_counts = sub.groupby(entity_col)[group_col].nunique()
    all_counts = detail_df.groupby(entity_col)[group_col].nunique()

    # Round 134: statistical significance. lift alone can be noise at n=2 — a
    # Fisher's exact test on the 2×2 (failing/passing × through/not-through this
    # tool) gives a one-sided p-value for over-representation in failing lots.
    try:
        from scipy.stats import fisher_exact as _fisher
    except Exception:  # noqa: BLE001
        _fisher = None
    n_pass = max(n_all - n_fail, 0)

    rows = []
    for ent, cnt in fail_counts.items():
        base = all_counts.get(ent, cnt)
        # lift = (share of failing lots through this tool) / (share of all lots)
        lift = (cnt / n_fail) / (base / n_all) if base and n_all else 0.0
        row = {
            entity_col: ent,
            "涉及批數": int(cnt),
            "涵蓋率%": round(cnt / n_fail * 100, 1),
            "lift": round(lift, 2),  # >1 = over-represented in failing lots
        }
        if _fisher is not None and n_pass >= 0:
            a = int(cnt)                       # failing & through tool
            b = int(n_fail - cnt)             # failing & not through tool
            c = int(base - cnt)               # passing & through tool
            d = int(n_pass - (base - cnt))    # passing & not through tool
            if min(a, b, c, d) >= 0:
                try:
                    _, p = _fisher([[a, b], [c, d]], alternative="greater")
                    row["p_value"] = round(float(p), 4)
                    row["顯著"] = "✓" if p < 0.05 else ""
                except Exception:  # noqa: BLE001
                    pass
        rows.append(row)
    # rank by significance (p asc) when available, else lift; then coverage
    df = pd.DataFrame(rows)
    if "p_value" in df.columns:
        df = df.sort_values(["p_value", "lift", "涉及批數"],
                            ascending=[True, False, False])
    else:
        df = df.sort_values(["lift", "涉及批數"], ascending=[False, False])
    return df.reset_index(drop=True)


def cohort_by_quantile(
    merged: pd.DataFrame, bucket_col: str, outcome_col: str, q: int = 5,
) -> pd.DataFrame:
    """Bucket rows by ``bucket_col`` quantile and average ``outcome_col`` per bucket.

    Returns [分組, 範圍, 筆數, <outcome avg>] ordered low→high bucket. Empty when
    not computable.
    """
    if merged is None or bucket_col not in merged.columns or outcome_col not in merged.columns:
        return pd.DataFrame()
    work = merged[[bucket_col, outcome_col]].dropna()
    if len(work) < q:
        return pd.DataFrame()
    try:
        work["_bucket"] = pd.qcut(work[bucket_col], q=q, labels=False, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    rows = []
    for b, g in work.groupby("_bucket"):
        rows.append({
            "分組": f"Q{int(b) + 1}",
            f"{bucket_col} 範圍": f"{g[bucket_col].min():.2f}–{g[bucket_col].max():.2f}",
            "筆數": int(len(g)),
            f"平均{outcome_col}": round(float(g[outcome_col].mean()), 2),
        })
    return pd.DataFrame(rows)
