"""Round 073: customer segmentation (new vs returning, value tiers)."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.analysis.segments import new_vs_returning_revenue, value_tier_summary


def test_new_vs_returning_split():
    # A first buys in Jan (new), returns in Feb (returning). B new in Feb.
    df = pd.DataFrame({
        "c": ["A", "A", "B"],
        "d": ["2026-01-10", "2026-02-05", "2026-02-20"],
        "rev": [100.0, 50.0, 30.0],
    })
    out = new_vs_returning_revenue(df, "c", "d", "rev", "month")
    assert out.loc["2026-01", "新客"] == 100.0
    assert out.loc["2026-02", "回頭客"] == 50.0   # A's Feb purchase
    assert out.loc["2026-02", "新客"] == 30.0      # B's first purchase


def test_new_vs_returning_empty_safe():
    assert new_vs_returning_revenue(pd.DataFrame({"c": [], "d": [], "rev": []}),
                                    "c", "d", "rev").empty


def test_value_tiers_buckets_and_revenue_pct():
    # 10 customers, revenue 100..10 (desc). Top 20% = 2 customers (高價值).
    df = pd.DataFrame({
        "c": [f"C{i}" for i in range(10)],
        "rev": [100.0, 90, 80, 70, 60, 50, 40, 30, 20, 10],
    })
    out = value_tier_summary(df, "c", "rev").set_index("tier")
    assert out.loc["高價值", "customers"] == 2     # top 20% of 10
    assert out.loc["中價值", "customers"] == 3     # next 30%
    assert out.loc["低價值", "customers"] == 5
    # revenue percentages sum to ~100
    assert abs(out["revenue_pct"].sum() - 100.0) < 0.5


def test_retail_demo_segments_run():
    from ai4bi.report.retail_template import build_retail_sales_block
    from ai4bi.blocks.datastore import materialize_dataframe
    df = materialize_dataframe(build_retail_sales_block())
    nvr = new_vs_returning_revenue(df, "customer_id", "order_date", "revenue", "month")
    assert not nvr.empty and "新客" in nvr.columns
    tiers = value_tier_summary(df, "customer_id", "revenue")
    assert set(tiers["tier"]) == {"高價值", "中價值", "低價值"}
