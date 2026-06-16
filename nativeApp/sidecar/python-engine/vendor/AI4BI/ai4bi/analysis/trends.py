"""Trend-streak analysis — Round 085.

"Which products are declining 3 months in a row?" — pure-pandas consecutive
run detection per entity, bypassing the executor's no-window/no-lag limit.

For each entity we bucket the date to a period (month/week), sum the value per
period, order chronologically, and measure the length of the *current* monotone
run ending at the latest period. Entities whose current declining run is at
least ``min_streak`` are returned worst-first — a ready-made "at-risk SKU" list.
"""

from __future__ import annotations

import pandas as pd

_PERIOD_FREQ = {"month": "MS", "week": "W", "quarter": "QS", "day": "D"}


def _current_streak(values: list[float]) -> tuple[int, str]:
    """Length + direction of the monotone run ending at the last value.

    Returns (run_length, "down"|"up"|"flat"). run_length counts the number of
    consecutive period-over-period moves in one direction at the tail.
    """
    if len(values) < 2:
        return 0, "flat"
    direction = "flat"
    run = 0
    for i in range(len(values) - 1, 0, -1):
        diff = values[i] - values[i - 1]
        step = "down" if diff < 0 else ("up" if diff > 0 else "flat")
        if step == "flat":
            break
        if direction == "flat":
            direction = step
            run = 1
        elif step == direction:
            run += 1
        else:
            break
    return run, direction


def new_products(
    df: pd.DataFrame,
    entity_col: str,
    date_col: str,
    value_col: str,
    period: str = "month",
    recent: int = 1,
) -> pd.DataFrame:
    """Round 107: newly-launched entities — first appeared in the recent period(s).

    "Which new products launched this period, and how are they doing?" — entities
    whose first-ever sales period is within the last ``recent`` period(s), ranked
    by their sales since launch. Columns: [entity_col, 首次售出, 上市以來].
    """
    needed = [entity_col, date_col, value_col]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    work = df[needed].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[entity_col, date_col])
    if work.empty:
        return pd.DataFrame()
    freq = _PERIOD_FREQ.get(period, "MS")
    work["_p"] = work[date_col].dt.to_period(freq[0] if freq != "MS" else "M")
    all_periods = sorted(work["_p"].unique())
    if len(all_periods) < 2:
        return pd.DataFrame()
    recent_set = set(all_periods[-recent:])

    first = work.groupby(entity_col)["_p"].min()
    totals = work.groupby(entity_col)[value_col].sum()
    rows = []
    for entity, fp in first.items():
        if fp in recent_set:
            rows.append({entity_col: entity, "首次售出": str(fp),
                         "上市以來": round(float(totals[entity]), 2)})
    if not rows:
        return pd.DataFrame()
    return (pd.DataFrame(rows).sort_values("上市以來", ascending=False)
            .reset_index(drop=True))


def dormant_products(
    df: pd.DataFrame,
    entity_col: str,
    date_col: str,
    value_col: str,
    period: str = "month",
    recent: int = 1,
) -> pd.DataFrame:
    """Round 101: dead-stock / dormant entities — sold historically but not lately.

    "Which products have stopped selling?" — entities with sales in an earlier
    period but zero across the most recent ``recent`` period(s). The actionable
    form of "never sold" that needs only a sales fact (no product master).

    Columns: [entity_col, 最後售出, 沉睡期數, 歷史總量]; worst (highest historical
    volume) first. Empty DataFrame when columns are missing or none qualify.
    """
    needed = [entity_col, date_col, value_col]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    work = df[needed].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[entity_col, date_col])
    if work.empty:
        return pd.DataFrame()

    freq = _PERIOD_FREQ.get(period, "MS")
    work["_p"] = work[date_col].dt.to_period(freq[0] if freq != "MS" else "M")
    all_periods = sorted(work["_p"].unique())
    if len(all_periods) <= recent:
        return pd.DataFrame()
    recent_set = set(all_periods[-recent:])

    agg = work.groupby([entity_col, "_p"])[value_col].sum().reset_index()
    rows = []
    for entity, g in agg.groupby(entity_col):
        sold = g[g[value_col] > 0]
        if sold.empty:
            continue
        recent_sales = g[g["_p"].isin(recent_set)][value_col].sum()
        if recent_sales > 0:
            continue  # still selling
        last_p = sold["_p"].max()
        dormancy = sum(1 for p in all_periods if p > last_p)
        rows.append({
            entity_col: entity,
            "最後售出": str(last_p),
            "沉睡期數": dormancy,
            "歷史總量": round(float(sold[value_col].sum()), 2),
        })
    if not rows:
        return pd.DataFrame()
    return (pd.DataFrame(rows)
            .sort_values(["歷史總量", "沉睡期數"], ascending=[False, False])
            .reset_index(drop=True))


def declining_by_trend(
    df: pd.DataFrame,
    entity_col: str,
    date_col: str,
    value_col: str,
    period: str = "week",
    min_periods: int = 4,
) -> pd.DataFrame:
    """Round 126: entities whose periodic value has a NEGATIVE linear trend.

    A robust "degrading over time / tool drift" detector — unlike a strict
    consecutive-decline streak, it fits a least-squares slope to each entity's
    per-period mean, so a noisy-but-downward series (real chamber drift) is still
    flagged. Returns [entity_col, 斜率/期, 期數, 起始, 最新] for entities with a
    negative slope, steepest first. Empty when nothing qualifies.
    """
    needed = [entity_col, date_col, value_col]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    work = df[needed].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[entity_col, date_col])
    if work.empty:
        return pd.DataFrame()
    freq = _PERIOD_FREQ.get(period, "MS")
    work["_p"] = work[date_col].dt.to_period(freq[0] if freq != "MS" else "M")
    agg = work.groupby([entity_col, "_p"])[value_col].mean().reset_index()
    rows = []
    for entity, g in agg.groupby(entity_col):
        g = g.sort_values("_p")
        vals = g[value_col].tolist()
        if len(vals) < min_periods:
            continue
        xs = list(range(len(vals)))
        n = len(vals)
        mx = sum(xs) / n
        my = sum(vals) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            continue
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / denom
        if slope < 0:
            rows.append({
                entity_col: entity,
                "斜率/期": round(slope, 3),
                "期數": n,
                "起始": round(vals[0], 2),
                "最新": round(vals[-1], 2),
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("斜率/期").reset_index(drop=True)


def declining_streaks(
    df: pd.DataFrame,
    entity_col: str,
    date_col: str,
    value_col: str,
    period: str = "month",
    min_streak: int = 3,
    direction: str = "down",
) -> pd.DataFrame:
    """Return entities with a current monotone run of length >= ``min_streak``.

    Columns: [entity_col, 連續期數, 趨勢, 最新值, 前一期, 變化%].
    Empty DataFrame when columns are missing or no entity qualifies.
    """
    needed = [entity_col, date_col, value_col]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    work = df[needed].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[entity_col, date_col])
    if work.empty:
        return pd.DataFrame()

    freq = _PERIOD_FREQ.get(period, "MS")
    work["_period"] = work[date_col].dt.to_period(freq[0] if freq != "MS" else "M").dt.to_timestamp()
    agg = (work.groupby([entity_col, "_period"])[value_col].sum()
           .reset_index().sort_values([entity_col, "_period"]))

    label = {"down": "連續下滑", "up": "連續成長"}.get(direction, "連續")
    rows = []
    for entity, g in agg.groupby(entity_col):
        vals = g[value_col].tolist()
        run, dir_ = _current_streak(vals)
        if dir_ != direction or run < min_streak:
            continue
        latest, prev = vals[-1], vals[-2]
        pct = ((latest - prev) / abs(prev) * 100.0) if prev else float("nan")
        rows.append({
            entity_col: entity,
            "連續期數": run,
            "趨勢": label,
            "最新值": round(latest, 2),
            "前一期": round(prev, 2),
            "變化%": round(pct, 1),
        })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(["連續期數", "變化%"],
                                         ascending=[False, True])
    return out.reset_index(drop=True)
