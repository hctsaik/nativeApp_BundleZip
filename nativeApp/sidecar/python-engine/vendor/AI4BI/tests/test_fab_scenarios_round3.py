"""Round 3 advanced fab scenarios (WIP/hold/cycle/utilization/FPY/drift) — regression.

All 10 handled with the correct analytical method after R121-126; locked in here.
"""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


@pytest.fixture(scope="module")
def env():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def _ask(env, p):
    svc, report, c, ex = env
    return svc.propose(p, report, None, contracts=c, executor=ex)


def test_1_general_measure_filter(env):
    r = _ask(env, "哪些 lot 的平均 queue time 超過 2 小時？")
    assert r.result_table is not None and "lot_id" in r.result_table.columns


def test_2_tool_throughput_ranking(env):
    r = _ask(env, "每台 tool 的移動次數排名")
    assert r.result_table is not None and "tool_id" in r.result_table.columns


def test_3_moving_average_inline(env):
    r = _ask(env, "全廠每日移動次數的 14 日移動平均走勢")
    assert r.result_table is not None  # inline smoothed table, not just a proposal


def test_4_hold_aging_by_lot(env):
    r = _ask(env, "hold 的 lot 依平均保留時間排序")
    assert r.result_table is not None and "lot_id" in r.result_table.columns


def test_5_defect_density_breakdown(env):
    r = _ask(env, "依 product family 看 defect density")
    assert r.result_table is not None and "product_family" in r.result_table.columns


def test_6_tool_drift_decline(env):
    r = _ask(env, "哪台 etch 機台良率逐週退化？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["etch_tool_id"] == "ETCH-01"  # embedded drift


def test_7_first_pass_yield(env):
    r = _ask(env, "有返工跟無返工的良率差多少？")
    # entity-compare returns the two-row comparison table + a delta sentence
    assert r.result_table is not None
    assert "返工" in r.message and "Weighted Yield" in r.message


def test_8_cycle_time_sla(env):
    r = _ask(env, "哪些 lot 的 cycle time 超過 300 小時？")
    assert r.result_table is not None and "lot_id" in r.result_table.columns


def test_9_same_fact_correlation(env):
    r = _ask(env, "defect die 高的批 yield 有沒有關聯？")
    assert r.result_table is not None and ("相關" in r.message or "關聯" in r.message)


def test_10_shift_compare(env):
    r = _ask(env, "Day 班 vs Night 班的移動次數誰比較高？")
    assert r.result_table is not None
    # Day-heavy staffing → Day has more moves
    assert "Day" in r.message and "Night" in r.message


def test_all_ten_handled(env):
    prompts = [
        "哪些 lot 的平均 queue time 超過 2 小時？", "每台 tool 的移動次數排名",
        "全廠每日移動次數的 14 日移動平均走勢", "hold 的 lot 依平均保留時間排序",
        "依 product family 看 defect density", "哪台 etch 機台良率逐週退化？",
        "有返工跟無返工的良率差多少？", "哪些 lot 的 cycle time 超過 300 小時？",
        "defect die 高的批 yield 有沒有關聯？", "Day 班 vs Night 班的移動次數誰比較高？",
    ]
    for p in prompts:
        r = _ask(env, p)
        assert (r.direct_answer is not None or r.result_table is not None
                or r.proposal is not None), p
