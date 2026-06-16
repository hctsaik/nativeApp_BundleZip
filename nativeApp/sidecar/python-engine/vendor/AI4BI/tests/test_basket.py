"""Round 077: market-basket affinity."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.analysis.basket import basket_affinity


def test_pair_cooccurrence_counts():
    # 3 baskets: (A,B), (A,B), (A,C). Pair A-B appears in 2 baskets.
    df = pd.DataFrame({
        "order": [1, 1, 2, 2, 3, 3],
        "product": ["A", "B", "A", "B", "A", "C"],
    })
    out = basket_affinity(df, "product", ["order"], min_baskets=1)
    ab = out[(out["商品A"] == "A") & (out["商品B"] == "B")].iloc[0]
    assert ab["同買次數"] == 2
    # A appears in 3 baskets, A&B in 2 → confidence 2/3
    assert ab["信心度"] == pytest.approx(0.67, abs=0.01)


def test_lift_above_one_for_associated_pair():
    df = pd.DataFrame({
        "order": [1, 1, 2, 2, 3, 3, 4],
        "product": ["A", "B", "A", "B", "A", "B", "C"],
    })
    out = basket_affinity(df, "product", ["order"], min_baskets=1)
    ab = out[(out["商品A"] == "A") & (out["商品B"] == "B")].iloc[0]
    assert ab["提升度"] > 1.0   # A and B strongly associated


def test_single_item_baskets_yield_no_pairs():
    df = pd.DataFrame({"order": [1, 2, 3], "product": ["A", "B", "C"]})
    assert basket_affinity(df, "product", ["order"]).empty


def test_multi_key_basket_and_min_threshold():
    # basket = (customer, date). One co-purchase of A&B.
    df = pd.DataFrame({
        "cust": ["c1", "c1", "c2"],
        "date": ["2026-05-01", "2026-05-01", "2026-05-02"],
        "product": ["A", "B", "A"],
    })
    out = basket_affinity(df, "product", ["cust", "date"], min_baskets=2)
    assert out.empty   # only 1 co-occurrence, below min_baskets=2


def test_retail_demo_basket_runs():
    from ai4bi.report.retail_template import build_retail_sales_block
    from ai4bi.blocks.datastore import materialize_dataframe
    df = materialize_dataframe(build_retail_sales_block())
    out = basket_affinity(df, "product_name", ["customer_id", "order_date", "store_id"])
    # may or may not find pairs depending on synthetic overlap, but must not error
    assert isinstance(out, pd.DataFrame)
