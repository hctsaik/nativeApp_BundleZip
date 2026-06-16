"""Round 063: repeat-purchase funnel."""

from __future__ import annotations

import pandas as pd

from ai4bi.analysis.funnel import purchase_frequency_funnel


def test_funnel_counts_and_monotonic():
    # A bought 3x, B 2x, C 1x
    df = pd.DataFrame({"cust": ["A", "A", "A", "B", "B", "C"]})
    f = purchase_frequency_funnel(df, "cust", stages=(1, 2, 3))
    counts = dict(zip(f["stage"], f["customers"]))
    assert counts["≥1 次"] == 3
    assert counts["≥2 次"] == 2
    assert counts["≥3 次"] == 1
    # funnel must be non-increasing
    assert list(f["customers"]) == sorted(f["customers"], reverse=True)


def test_funnel_pct_of_top():
    df = pd.DataFrame({"cust": ["A", "A", "B", "C", "D"]})  # A=2, others=1
    f = purchase_frequency_funnel(df, "cust", stages=(1, 2))
    top = f.iloc[0]
    assert top["pct"] == 100.0
    # 1 of 4 customers reached >=2 → 25%
    assert f.iloc[1]["pct"] == 25.0


def test_funnel_empty_safe():
    f = purchase_frequency_funnel(pd.DataFrame({"cust": []}), "cust")
    assert f.empty


def test_funnel_on_retail_demo():
    from ai4bi.report.retail_template import build_retail_sales_block
    from ai4bi.blocks.datastore import materialize_dataframe
    df = materialize_dataframe(build_retail_sales_block())
    f = purchase_frequency_funnel(df, "customer_id")
    assert not f.empty
    assert list(f["customers"]) == sorted(f["customers"], reverse=True)
