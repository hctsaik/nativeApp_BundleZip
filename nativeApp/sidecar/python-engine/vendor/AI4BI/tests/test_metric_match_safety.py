"""Round 104: don't return a confident WRONG answer for an absent metric.

Round-7 found that '毛利率最高的5個商品' (gross margin — no such metric in the
demo) matched the 1-char synonym '率' for return_rate and confidently ranked
the wrong metric. The fix: ignore <2-char metric keywords so the engine
declines instead of mis-answering.
"""

from __future__ import annotations

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.ai.schema_index import SchemaIndex
from ai4bi.analysis.executor import Executor
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _contracts():
    return {"retail_sales": build_retail_sales_block()}


def test_single_char_synonym_no_longer_matches():
    idx = SchemaIndex.build(_contracts())
    # '毛利率' contains the 1-char '率' (a return_rate synonym) but no real margin
    # metric exists → must NOT match return_rate.
    m = idx.best_metric_match("毛利率最高的商品", "毛利率最高的商品")
    assert m is None or m.metric_name != "return_rate"


def test_real_metric_still_matches():
    idx = SchemaIndex.build(_contracts())
    assert idx.best_metric_match("營收多少", "營收多少").metric_name == "revenue"
    assert idx.best_metric_match("退貨率多少", "退貨率多少").metric_name == "return_rate"


def test_ranking_declines_for_absent_metric():
    svc = NL2ProposalService()
    contracts = _contracts()
    ex = Executor(extra_contracts=contracts)
    result = svc.propose("毛利率最高的 5 個商品", build_retail_demo_report(), None,
                         contracts=contracts, executor=ex)
    # must NOT return a confident (wrong) ranking table for a non-existent metric
    if result.result_table is not None:
        # if anything came back, it must not be the wrong return_rate ranking
        assert "Return Rate" not in result.result_table.columns


def test_real_ranking_still_works():
    svc = NL2ProposalService()
    contracts = _contracts()
    ex = Executor(extra_contracts=contracts)
    result = svc.propose("營收最高的 3 個地區", build_retail_demo_report(), None,
                         contracts=contracts, executor=ex)
    assert result.result_table is not None
    assert len(result.result_table) == 3
