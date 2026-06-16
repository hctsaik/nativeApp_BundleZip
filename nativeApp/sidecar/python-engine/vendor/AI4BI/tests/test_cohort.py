"""Round 062: cohort / retention analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.analysis.cohort import cohort_retention


def test_retention_offset_zero_is_full():
    # 2 customers first buy in Jan; both active in Jan
    df = pd.DataFrame({
        "cust": ["A", "B"],
        "date": ["2026-01-05", "2026-01-20"],
    })
    res = cohort_retention(df, "cust", "date", "month")
    assert res.retention.loc["2026-01", 0] == 100.0
    assert int(res.cohort_sizes["2026-01"]) == 2


def test_retention_decay_across_months():
    # cohort Jan = {A, B}; A returns in Feb, B does not → offset1 = 50%
    df = pd.DataFrame({
        "cust": ["A", "B", "A"],
        "date": ["2026-01-10", "2026-01-15", "2026-02-10"],
    })
    res = cohort_retention(df, "cust", "date", "month")
    assert res.retention.loc["2026-01", 0] == 100.0
    assert res.retention.loc["2026-01", 1] == 50.0


def test_multiple_cohorts():
    df = pd.DataFrame({
        "cust": ["A", "B", "C", "A"],
        "date": ["2026-01-01", "2026-02-01", "2026-02-15", "2026-03-01"],
    })
    res = cohort_retention(df, "cust", "date", "month")
    # A is Jan cohort; B and C are Feb cohort
    assert set(res.retention.index) == {"2026-01", "2026-02"}
    assert int(res.cohort_sizes["2026-02"]) == 2
    # A returns 2 months later → Jan cohort offset 2 = 100%
    assert res.retention.loc["2026-01", 2] == 100.0


def test_empty_df_safe():
    res = cohort_retention(pd.DataFrame({"cust": [], "date": []}), "cust", "date")
    assert res.retention.empty


def test_retail_demo_cohort_runs():
    from ai4bi.report.retail_template import build_retail_sales_block
    from ai4bi.blocks.datastore import materialize_dataframe
    df = materialize_dataframe(build_retail_sales_block())
    assert "customer_id" in df.columns
    res = cohort_retention(df, "customer_id", "order_date", "month")
    # first-period retention is always 100%
    assert (res.retention[0].dropna() == 100.0).all()
    assert not res.cohort_sizes.empty
