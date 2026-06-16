"""RFM / churn-risk analysis — Round 082.

"Which customers are about to churn?" / "Who are my VIPs?" — pure-pandas
Recency-Frequency-Monetary scoring, bypassing the executor's no-window limit
(per-customer MAX(date) + COUNT + SUM with quintile ranking).

    Recency   = days since the customer's last purchase (lower = better)
    Frequency = number of distinct purchase days (higher = better)
    Monetary  = total spend (higher = better)

Each dimension is scored 1–5 by quintile rank; a segment label and a churn-risk
flag (bottom-two recency quintiles) are derived. Rows are returned most-at-risk
and most-valuable first, so the output doubles as a win-back call list.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


def _quintile_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """Score a numeric series 1–5 by percentile rank (robust to ties / few values)."""
    if series.empty:
        return series
    pct = series.rank(method="average", pct=True)
    score = np.ceil(pct * 5).clip(1, 5)
    if not higher_is_better:
        score = 6 - score
    return score.astype(int)


def _segment(r: int, f: int, m: int) -> str:
    if r >= 4 and f >= 4 and m >= 4:
        return "VIP / 核心客"
    if r >= 4:
        return "活躍客"
    if r <= 2 and (f >= 3 or m >= 4):
        return "高價值流失風險"
    if r <= 2:
        return "流失風險"
    return "一般客"


def compute_rfm(
    df: pd.DataFrame,
    customer_col: str,
    date_col: str,
    monetary_col: str,
    anchor: Optional[date] = None,
) -> pd.DataFrame:
    """Return a per-customer RFM table.

    Columns: [customer_col, 最近購買, 距今天數, 購買次數, 累計金額,
              R, F, M, 分群, 流失風險]
    sorted with at-risk + high-value customers first. Empty DataFrame when the
    required columns are missing or there are no usable rows.
    """
    needed = [customer_col, date_col, monetary_col]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    work = df[needed].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[customer_col, date_col])
    if work.empty:
        return pd.DataFrame()

    anchor_ts = pd.Timestamp(anchor) if anchor is not None else work[date_col].max()

    grouped = work.groupby(customer_col)
    rfm = pd.DataFrame({
        "最近購買": grouped[date_col].max(),
        "購買次數": grouped[date_col].apply(lambda s: s.dt.normalize().nunique()),
        "累計金額": grouped[monetary_col].sum(),
    }).reset_index()
    rfm["距今天數"] = (anchor_ts - rfm["最近購買"]).dt.days

    rfm["R"] = _quintile_score(rfm["距今天數"], higher_is_better=False)
    rfm["F"] = _quintile_score(rfm["購買次數"], higher_is_better=True)
    rfm["M"] = _quintile_score(rfm["累計金額"], higher_is_better=True)
    rfm["分群"] = [_segment(r, f, m) for r, f, m in zip(rfm["R"], rfm["F"], rfm["M"])]
    rfm["流失風險"] = rfm["R"] <= 2

    rfm["最近購買"] = rfm["最近購買"].dt.date
    # At-risk first; within that, highest-value first → ready-made win-back list.
    rfm = rfm.sort_values(["流失風險", "累計金額"], ascending=[False, False]).reset_index(drop=True)
    return rfm[[customer_col, "最近購買", "距今天數", "購買次數", "累計金額",
                "R", "F", "M", "分群", "流失風險"]]
