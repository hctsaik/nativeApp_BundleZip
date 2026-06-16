"""Round 090: per-group Top-N (top N within each group) — partitioned window."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_grouped_topn
from ai4bi.analysis.executor import Executor
from ai4bi.analysis.postprocess import top_n_per_group
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


# ---- pandas helper ----------------------------------------------------------

def test_top_n_per_group_keeps_n_per_group():
    df = pd.DataFrame({
        "store": ["A", "A", "A", "B", "B"],
        "product": ["p1", "p2", "p3", "q1", "q2"],
        "rev": [30, 20, 10, 5, 50],
    })
    out = top_n_per_group(df, "store", "rev", n=2)
    # 2 per store, descending within store
    a = out[out["store"] == "A"]
    assert list(a["product"]) == ["p1", "p2"]
    b = out[out["store"] == "B"]
    assert list(b["product"]) == ["q2", "q1"]
    assert len(out) == 4


def test_top_n_per_group_ascending():
    df = pd.DataFrame({"g": ["x", "x", "x"], "p": ["a", "b", "c"], "v": [3, 1, 2]})
    out = top_n_per_group(df, "g", "v", n=1, ascending=True)
    assert list(out["p"]) == ["b"]  # lowest


# ---- NL detection -----------------------------------------------------------

def test_detector():
    assert _looks_like_grouped_topn("每個地區最暢銷的 2 個商品", "每個地區最暢銷的 2 個商品")
    assert _looks_like_grouped_topn("top 3 products per store", "top 3 products per store")
    # "each store's revenue" has no ranking cue → not a per-group top-N
    assert not _looks_like_grouped_topn("每個門市的營收", "每個門市的營收")


# ---- end-to-end -------------------------------------------------------------

def _ctx():
    contracts = {"retail_sales": build_retail_sales_block()}
    return (NL2ProposalService(), build_retail_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_grouped_topn_end_to_end():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("每個地區營收最高的 2 個商品", report, None, contracts=contracts, executor=ex)
    df = result.result_table
    assert df is not None, result.message
    assert "city" in df.columns
    # at most 2 products per city
    assert (df.groupby("city").size() <= 2).all()
    # within each city, the metric is descending (alias is the Title-cased name)
    metric_col = df.columns[-1]
    for _, g in df.groupby("city"):
        vals = list(g[metric_col])
        assert vals == sorted(vals, reverse=True)


def test_no_executor_falls_through():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("每個地區營收最高的 2 個商品", report, None, contracts=contracts, executor=None)
    assert result.result_table is None
