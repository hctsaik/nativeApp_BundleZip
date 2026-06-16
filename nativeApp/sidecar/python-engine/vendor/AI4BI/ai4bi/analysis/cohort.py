"""Cohort / retention analysis — Round 062.

Groups customers by the period of their first purchase (the cohort), then measures
what fraction return in each subsequent period. Pure pandas on raw rows — the
executor needs no window functions; the result is a retention matrix
(rows = cohort, columns = period offset, values = retention %).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_FREQ = {"month": "M", "week": "W"}


@dataclass
class CohortResult:
    retention: pd.DataFrame   # index=cohort label, columns=offset (0,1,2,...), values=%
    cohort_sizes: pd.Series   # index=cohort label, value=unique customers


def cohort_retention(
    df: pd.DataFrame,
    customer_col: str,
    date_col: str,
    period: str = "month",
) -> CohortResult:
    """Compute a retention matrix from raw (customer, date) rows.

    Returns CohortResult; retention[c, k] = % of cohort c's customers active k
    periods after their first purchase (offset 0 is always 100%).
    """
    freq = _FREQ.get(period, "M")
    work = df[[customer_col, date_col]].dropna().copy()
    if work.empty:
        return CohortResult(retention=pd.DataFrame(), cohort_sizes=pd.Series(dtype=float))

    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    work["period"] = work[date_col].dt.to_period(freq)

    first = work.groupby(customer_col)["period"].min().rename("cohort")
    work = work.join(first, on=customer_col)
    # integer period offset (0,1,2,...)
    work["offset"] = work.apply(lambda r: (r["period"] - r["cohort"]).n, axis=1)

    cohort_sizes = work.groupby("cohort")[customer_col].nunique()
    active = work.groupby(["cohort", "offset"])[customer_col].nunique()

    retention = active.unstack("offset").sort_index()
    retention = retention.div(cohort_sizes, axis=0) * 100.0
    retention = retention.round(1)
    # label cohorts as strings (e.g. "2026-03")
    retention.index = retention.index.astype(str)
    cohort_sizes.index = cohort_sizes.index.astype(str)
    return CohortResult(retention=retention, cohort_sizes=cohort_sizes)
