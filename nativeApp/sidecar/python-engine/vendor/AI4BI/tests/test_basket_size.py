"""Round 109: basket-size distribution ('how many items per order?')."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _detect_panel_analysis
from ai4bi.analysis.basket import basket_size_distribution
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _df():
    # basket = customer+date. Basket1 (A,d1): 2 distinct items, qty 3. Basket2
    # (A,d2): 1 item, qty 1. Basket3 (B,d1): 3 items, qty 6.
    rows = [
        {"cust": "A", "d": "d1", "product": "p1", "qty": 1},
        {"cust": "A", "d": "d1", "product": "p2", "qty": 2},
        {"cust": "A", "d": "d2", "product": "p1", "qty": 1},
        {"cust": "B", "d": "d1", "product": "p1", "qty": 1},
        {"cust": "B", "d": "d1", "product": "p2", "qty": 2},
        {"cust": "B", "d": "d1", "product": "p3", "qty": 3},
    ]
    return pd.DataFrame(rows)


def test_distinct_item_count_distribution():
    dist, summary = basket_size_distribution(_df(), ["cust", "d"], "product")
    # basket sizes (distinct items): 2, 1, 3 → avg 2.0
    assert summary["baskets"] == 3
    assert summary["avg"] == 2.0
    assert summary["max"] == 3
    assert set(dist["籃子大小"]) == {1, 2, 3}


def test_quantity_based_size():
    dist, summary = basket_size_distribution(_df(), ["cust", "d"], "product", qty_col="qty")
    # basket qty sums: 3, 1, 6 → avg 3.33
    assert summary["max"] == 6
    assert summary["avg"] == round((3 + 1 + 6) / 3, 2)


def test_missing_columns_empty():
    dist, summary = basket_size_distribution(_df(), ["nope"], "product")
    assert dist.empty and summary == {}


def test_nl_routes_basketsize():
    assert _detect_panel_analysis("平均一單幾件", "平均一單幾件") == "basketsize"
    svc = NL2ProposalService()
    contracts = {"retail_sales": build_retail_sales_block()}
    result = svc.propose("平均每單買幾樣商品？", build_retail_demo_report(), None,
                         contracts=contracts, executor=None)
    assert result.result_table is not None, result.message
    assert "籃子大小" in result.result_table.columns
    assert "平均每籃" in result.message
