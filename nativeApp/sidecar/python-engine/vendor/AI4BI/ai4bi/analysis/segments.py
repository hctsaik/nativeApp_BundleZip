"""Customer segmentation — Round 073.

Pure-pandas customer analytics on raw rows (via materialize_dataframe), bypassing
the executor's single-GROUP-BY limits:
  - new_vs_returning_revenue: revenue split into new vs returning customers per period
  - value_tier_summary: customers bucketed into value tiers (top 20% / next 30% / rest)
"""

from __future__ import annotations

import pandas as pd

_FREQ = {"month": "M", "week": "W"}


def new_vs_returning_revenue(
    df: pd.DataFrame,
    customer_col: str,
    date_col: str,
    revenue_col: str,
    period: str = "month",
) -> pd.DataFrame:
    """Revenue per period split by 新客 (first-ever period) vs 回頭客.

    Returns a DataFrame indexed by period label with 新客 / 回頭客 columns.
    """
    freq = _FREQ.get(period, "M")
    cols = [customer_col, date_col, revenue_col]
    if any(c not in df.columns for c in cols):
        return pd.DataFrame()
    w = df[cols].dropna(subset=[customer_col, date_col]).copy()
    if w.empty:
        return pd.DataFrame()
    w[date_col] = pd.to_datetime(w[date_col], errors="coerce")
    w = w.dropna(subset=[date_col])
    w["period"] = w[date_col].dt.to_period(freq)
    first = w.groupby(customer_col)["period"].transform("min")
    w["segment"] = (w["period"] == first).map({True: "新客", False: "回頭客"})
    out = (w.groupby(["period", "segment"])[revenue_col].sum()
           .unstack("segment").fillna(0.0).sort_index())
    out.index = out.index.astype(str)
    for c in ("新客", "回頭客"):
        if c not in out.columns:
            out[c] = 0.0
    return out[["新客", "回頭客"]]


def repeat_vs_onetime(
    df: pd.DataFrame,
    customer_col: str,
    date_col: str,
) -> pd.DataFrame:
    """Round 098: customer *counts* — repeat (≥2 purchase days) vs one-time.

    Returns a small DataFrame [客戶類型, 人數, 佔比%]. A "purchase occasion" is a
    distinct purchase day (no order id needed). Empty DataFrame when columns are
    missing or there are no customers.
    """
    if customer_col not in df.columns or date_col not in df.columns:
        return pd.DataFrame()
    w = df[[customer_col, date_col]].dropna().copy()
    w[date_col] = pd.to_datetime(w[date_col], errors="coerce")
    w = w.dropna(subset=[date_col])
    if w.empty:
        return pd.DataFrame()
    occasions = w.groupby(customer_col)[date_col].apply(lambda s: s.dt.normalize().nunique())
    total = int(len(occasions))
    repeat = int((occasions >= 2).sum())
    onetime = total - repeat
    rows = [
        {"客戶類型": "回頭客（≥2 次）", "人數": repeat,
         "佔比%": round(repeat / total * 100, 1) if total else 0.0},
        {"客戶類型": "一次性客", "人數": onetime,
         "佔比%": round(onetime / total * 100, 1) if total else 0.0},
    ]
    return pd.DataFrame(rows)


def value_tier_summary(
    df: pd.DataFrame,
    customer_col: str,
    revenue_col: str,
) -> pd.DataFrame:
    """Bucket customers by lifetime revenue into 高/中/低 value tiers.

    Top 20% of customers (by revenue) → 高價值, next 30% → 中價值, rest → 低價值.
    Returns [tier, customers, revenue, revenue_pct].
    """
    if customer_col not in df.columns or revenue_col not in df.columns:
        return pd.DataFrame()
    totals = df.groupby(customer_col)[revenue_col].sum().sort_values(ascending=False)
    n = len(totals)
    if n == 0:
        return pd.DataFrame()
    tier = pd.Series("低價值", index=totals.index)
    hi_cut = max(1, int(round(n * 0.2)))
    mid_cut = max(hi_cut, int(round(n * 0.5)))
    tier.iloc[:hi_cut] = "高價值"
    tier.iloc[hi_cut:mid_cut] = "中價值"
    grand = float(totals.sum()) or 1.0
    rows = []
    for t in ("高價值", "中價值", "低價值"):
        mask = tier == t
        rev = float(totals[mask].sum())
        rows.append({"tier": t, "customers": int(mask.sum()),
                     "revenue": round(rev, 1), "revenue_pct": round(rev / grand * 100, 1)})
    return pd.DataFrame(rows)
