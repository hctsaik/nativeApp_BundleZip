"""Round 2 advanced fab scenarios — locked in as regression tests.

All 10 are now handled with the correct analytical method (cross-fact,
SPC, commonality, matrix, multi-filter, ratio decomposition).
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


def _handled(r):
    return (r.direct_answer is not None or r.result_table is not None
            or r.proposal is not None)


def test_1_compare_with_filter(env):
    r = _ask(env, "ETCH 區的 Hot 批與 Normal 批平均 queue time 差多少？")
    assert r.result_table is not None and "priority" in r.result_table.columns


def test_2_spc_outliers(env):
    r = _ask(env, "哪些機台的 queue time 超出全廠平均 2 個標準差？")
    assert r.result_table is not None and "tool_id" in r.result_table.columns


def test_3_matrix(env):
    r = _ask(env, "各 etch 機台在不同 product family 上的良率")
    assert r.result_table is not None
    assert "ETCH-01" in r.result_table.columns and "ETCH-02" in r.result_table.columns


def test_4_crossfact_correlation(env):
    r = _ask(env, "ETCH queue time 和最後良率有沒有關聯？")
    assert r.result_table is not None
    assert "相關" in r.message or "關聯" in r.message


def test_5_cohort_quantile(env):
    r = _ask(env, "cycle time 最久的前 20% 批號平均良率掉多少？")
    assert r.result_table is not None and "分組" in r.result_table.columns


def test_6_multi_condition_filter(env):
    r = _ask(env, "夜班 Hot 批跑 LAM 機台且有 rework 的 move 數")
    assert r.direct_answer is not None and r.direct_answer.metric_name == "move_count"


def test_7_ratio_decomposition(env):
    r = _ask(env, "這週 rework rate 比上週高，主要是哪個 area 造成的？")
    assert r.direct_answer is not None and "拆解" in r.direct_answer.sentence


def test_8_defect_share(env):
    r = _ask(env, "各 defect type 的占比")
    assert _handled(r)


def test_9_crossfact_ratio(env):
    r = _ask(env, "各 product family 良率對 rework 次數比值")
    assert r.result_table is not None and "product_family" in r.result_table.columns


def test_10_commonality(env):
    r = _ask(env, "良率掉到 80% 以下的晶圓有沒有共同走過某台機台？")
    assert r.result_table is not None and r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_all_ten_handled(env):
    prompts = [
        "ETCH 區的 Hot 批與 Normal 批平均 queue time 差多少？",
        "哪些機台的 queue time 超出全廠平均 2 個標準差？",
        "各 etch 機台在不同 product family 上的良率",
        "ETCH queue time 和最後良率有沒有關聯？",
        "cycle time 最久的前 20% 批號平均良率掉多少？",
        "夜班 Hot 批跑 LAM 機台且有 rework 的 move 數",
        "這週 rework rate 比上週高，主要是哪個 area 造成的？",
        "各 defect type 的占比",
        "各 product family 良率對 rework 次數比值",
        "良率掉到 80% 以下的晶圓有沒有共同走過某台機台？",
    ]
    assert all(_handled(_ask(env, p)) for p in prompts)
