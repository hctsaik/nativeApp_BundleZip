"""Round 087: Top-N 'best / worst' ranking answers."""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_ranking, _extract_rank_n, _ranking_is_ascending,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    contracts = {"retail_sales": build_retail_sales_block()}
    return (NL2ProposalService(), build_retail_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_detector():
    assert _looks_like_ranking("營收最高的 3 個地區", "營收最高的 3 個地區")
    assert _looks_like_ranking("top 5 products by revenue", "top 5 products by revenue")
    assert _looks_like_ranking("賣最差的品類", "賣最差的品類")
    assert not _looks_like_ranking("營收多少", "營收多少")
    assert not _looks_like_ranking("最近 30 天營收", "最近 30 天營收")


def test_rank_n_and_direction():
    assert _extract_rank_n("前 3 個地區", "前 3 個地區") == 3
    assert _extract_rank_n("top 10 products", "top 10 products") == 10
    assert _extract_rank_n("最賺的商品", "最賺的商品") == 5  # default
    assert _ranking_is_ascending("營收最低的地區", "營收最低的地區")
    assert not _ranking_is_ascending("營收最高的地區", "營收最高的地區")


def test_top_regions_descending():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("營收最高的 3 個地區", report, None, contracts=contracts, executor=ex)
    df = result.result_table
    assert df is not None
    assert len(df) == 3
    # SchemaIndex aliases the metric to its Title-cased name ("Revenue").
    vals = list(df["Revenue"])
    assert vals == sorted(vals, reverse=True)  # descending
    assert "city" in df.columns


def test_bottom_regions_ascending():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("營收最低的 2 個地區", report, None, contracts=contracts, executor=ex)
    df = result.result_table
    assert df is not None
    assert len(df) == 2
    vals = list(df["Revenue"])
    assert vals == sorted(vals)  # ascending


def test_default_n_is_five_or_fewer():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("營收最高的地區排名", report, None, contracts=contracts, executor=ex)
    assert result.result_table is not None
    assert len(result.result_table) <= 5


def test_no_executor_falls_through():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("營收最高的地區", report, None, contracts=contracts, executor=None)
    assert result.result_table is None
