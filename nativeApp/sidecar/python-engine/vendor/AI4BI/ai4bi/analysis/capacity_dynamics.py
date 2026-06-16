"""Capacity / flow dynamics analyses (pure pandas, unit-testable).

These cover the equipment/IE lens gaps surfaced in the deployment-validation
round: the bottleneck shifting over time, and the WIP <-> cycle-time
relationship (Little's Law). No Streamlit or DuckDB here.
"""
from __future__ import annotations

import pandas as pd


def _period(series: pd.Series, freq: str) -> pd.Series:
    """Map a datetime column to a period label for grouping."""
    dt = pd.to_datetime(series, errors="coerce")
    if freq == "D":
        return dt.dt.to_period("D").astype(str)
    if freq == "M":
        return dt.dt.to_period("M").astype(str)
    # default weekly (ISO week, anchored to week start)
    return dt.dt.to_period("W").astype(str)


def bottleneck_over_time(
    df: pd.DataFrame,
    date_col: str,
    group_col: str,
    value_col: str,
    *,
    freq: str = "W",
    agg: str = "mean",
):
    """Find which group is the bottleneck in each period and whether it shifts.

    The "bottleneck" each period is the group with the highest aggregated
    ``value_col`` (e.g. mean queue time, or summed move_count). Returns a frame
    with one row per period: ``period``, ``bottleneck`` (top group), ``value``,
    and ``changed`` (True when the top group differs from the prior period).
    """
    if df.empty or date_col not in df or group_col not in df or value_col not in df:
        return pd.DataFrame(columns=["period", "bottleneck", "value", "changed"])

    work = df[[date_col, group_col, value_col]].copy()
    work["period"] = _period(work[date_col], freq)
    work = work.dropna(subset=["period"])
    if work.empty:
        return pd.DataFrame(columns=["period", "bottleneck", "value", "changed"])

    grouped = getattr(work.groupby(["period", group_col])[value_col], agg)()
    grouped = grouped.reset_index()

    rows = []
    prev_top = None
    for period in sorted(grouped["period"].unique()):
        sub = grouped[grouped["period"] == period]
        top_idx = sub[value_col].idxmax()
        top_group = sub.loc[top_idx, group_col]
        top_value = float(sub.loc[top_idx, value_col])
        rows.append(
            {
                "period": period,
                "bottleneck": top_group,
                "value": round(top_value, 3),
                "changed": prev_top is not None and top_group != prev_top,
            }
        )
        prev_top = top_group

    return pd.DataFrame(rows)


def bottleneck_shift_summary(result: pd.DataFrame) -> dict:
    """Summarise a ``bottleneck_over_time`` frame into a headline-ready dict."""
    if result.empty:
        return {"shifted": False, "n_periods": 0, "shifts": []}
    shifts = []
    prev = None
    for _, row in result.iterrows():
        if prev is not None and row["bottleneck"] != prev["bottleneck"]:
            shifts.append(
                {
                    "period": row["period"],
                    "from": prev["bottleneck"],
                    "to": row["bottleneck"],
                }
            )
        prev = row
    return {
        "shifted": bool(shifts),
        "n_periods": int(len(result)),
        "shifts": shifts,
        "dominant": result["bottleneck"].mode().iloc[0]
        if not result.empty
        else None,
    }


def wip_vs_cycle_time(
    df: pd.DataFrame,
    date_col: str,
    cycle_col: str,
    *,
    lot_col: str | None = None,
    freq: str = "W",
):
    """Relate WIP to cycle time over time (Little's Law lens).

    Per period computes:
      * ``wip`` -- distinct lots active (proxy for work-in-progress level),
        or row count if no lot column is given;
      * ``throughput`` -- number of moves completed in the period;
      * ``avg_cycle_time`` -- mean of ``cycle_col``;
      * ``littles_law_ct`` -- Little's-Law implied cycle time = wip / throughput
        (in period units), provided as an honest cross-check, not a claim.

    Returns ``(per_period_df, summary_dict)`` where summary carries the Pearson
    correlation between WIP and cycle time plus a plain-language read.
    """
    cols = [date_col, cycle_col] + ([lot_col] if lot_col else [])
    empty = pd.DataFrame(
        columns=["period", "wip", "throughput", "avg_cycle_time", "littles_law_ct"]
    )
    if df.empty or any(c not in df for c in cols):
        return empty, {"r": None, "n": 0, "relationship": "資料不足"}

    work = df.copy()
    work["period"] = _period(work[date_col], freq)
    work = work.dropna(subset=["period"])
    if work.empty:
        return empty, {"r": None, "n": 0, "relationship": "資料不足"}

    rows = []
    for period, sub in work.groupby("period"):
        wip = sub[lot_col].nunique() if lot_col else len(sub)
        throughput = len(sub)
        avg_ct = float(pd.to_numeric(sub[cycle_col], errors="coerce").mean())
        ll_ct = (wip / throughput) if throughput else float("nan")
        rows.append(
            {
                "period": period,
                "wip": int(wip),
                "throughput": int(throughput),
                "avg_cycle_time": round(avg_ct, 3),
                "littles_law_ct": round(ll_ct, 4),
            }
        )
    per = pd.DataFrame(rows).sort_values("period").reset_index(drop=True)

    r = None
    relationship = "資料點不足以判斷"
    if len(per) >= 3 and per["wip"].nunique() > 1 and per["avg_cycle_time"].nunique() > 1:
        r = float(per["wip"].corr(per["avg_cycle_time"]))
        if pd.isna(r):
            r = None
        elif r >= 0.5:
            relationship = "WIP 越高、cycle time 越長（正相關，符合 Little's Law 直覺）"
        elif r <= -0.5:
            relationship = "WIP 與 cycle time 呈負相關（少見，建議檢查資料）"
        else:
            relationship = "WIP 與 cycle time 關聯不明顯"
    summary = {
        "r": None if r is None else round(r, 3),
        "n": int(len(per)),
        "relationship": relationship,
    }
    return per, summary
