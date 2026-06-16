"""Round 116: cross-fact analytics (correlation / cohort / ratio across two facts)."""

from __future__ import annotations

import pandas as pd

from ai4bi.analysis.crossfact import align_two_facts, cohort_by_quantile, correlate_facts
from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_crossfact
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def test_align_two_facts_on_lot():
    m = align_two_facts(fab_contracts(), block_a="fab_process_move", col_a="queue_time_hr",
                        agg_a="AVG", alias_a="Q", block_b="fab_wafer_yield", col_b="yield_pct",
                        agg_b="AVG", alias_b="Y", join_key="lot_id")
    assert {"lot_id", "Q", "Y"} <= set(m.columns)
    assert len(m) == 20  # 20 lots


def test_correlation_returns_stat():
    m = align_two_facts(fab_contracts(), block_a="fab_process_move", col_a="queue_time_hr",
                        agg_a="AVG", alias_a="Q", block_b="fab_wafer_yield", col_b="yield_pct",
                        agg_b="AVG", alias_b="Y", join_key="lot_id")
    stat = correlate_facts(m, "Q", "Y")
    assert stat is not None
    assert -1.0 <= stat["r"] <= 1.0 and stat["n"] == 20


def test_correlation_strong_when_coupled():
    m = pd.DataFrame({"k": range(10), "A": range(10), "B": range(10)})
    stat = correlate_facts(m, "A", "B")
    assert stat["r"] == 1.0 and stat["direction"] == "正" and stat["strength"] == "很強"


def test_cohort_by_quantile():
    m = align_two_facts(fab_contracts(), block_a="fab_process_move", col_a="queue_time_hr",
                        agg_a="AVG", alias_a="Q", block_b="fab_wafer_yield", col_b="yield_pct",
                        agg_b="AVG", alias_b="Y", join_key="lot_id")
    table = cohort_by_quantile(m, "Q", "Y", q=5)
    assert not table.empty
    assert "分組" in table.columns
    assert any("平均" in c for c in table.columns)


def _nl():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def test_detector():
    assert _looks_like_crossfact("queue 和良率有關聯嗎", "queue 和良率有關聯嗎")
    assert _looks_like_crossfact("前 20% 批號良率", "前 20% 批號良率")
    assert not _looks_like_crossfact("整體良率多少", "整體良率多少")


def test_nl_correlation_routes():
    svc, report, c, ex = _nl()
    r = svc.propose("ETCH queue time 和最後良率有關聯嗎？", report, None, contracts=c, executor=ex)
    assert r.result_table is not None
    assert "相關" in r.message or "關聯" in r.message


def test_nl_crossfact_ratio_routes():
    svc, report, c, ex = _nl()
    r = svc.propose("各 product family 良率對 rework 次數比值", report, None, contracts=c, executor=ex)
    assert r.result_table is not None
    assert "product_family" in r.result_table.columns
