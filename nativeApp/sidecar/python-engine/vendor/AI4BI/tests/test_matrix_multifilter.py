"""Round 118: 2-D matrix cross-tab + multi-condition filter."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_matrix, _looks_like_multi_filter
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _nl():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def test_matrix_detector():
    assert _looks_like_matrix("各 etch 機台在不同 product 上的良率", "各 etch 機台在不同 product 上的良率")
    assert not _looks_like_matrix("各製程站的移動次數", "各製程站的移動次數")


def test_matrix_pivots_two_dims():
    svc, report, c, ex = _nl()
    r = svc.propose("各 etch 機台在不同 product family 上的良率", report, None, contracts=c, executor=ex)
    assert r.result_table is not None
    cols = list(r.result_table.columns)
    # one dim is the index column, the other dim's values become columns
    assert "ETCH-01" in cols and "ETCH-02" in cols
    assert "product_family" in cols


def test_multi_filter_detector():
    assert _looks_like_multi_filter("夜班 Hot 批且有 rework", "夜班 Hot 批且有 rework")


def test_multi_filter_applies_all_conditions():
    svc, report, c, ex = _nl()
    r = svc.propose("夜班 Hot 批跑 LAM 機台且有 rework 的 move 數", report, None, contracts=c, executor=ex)
    assert r.direct_answer is not None
    # the target metric is move_count (not the rework filter word)
    assert r.direct_answer.metric_name == "move_count"
    # all four conditions appear in the explanation
    s = r.direct_answer.sentence
    assert "Night" in s and "Hot" in s and "LAM" in s and "rework_flag=1" in s


def test_multi_filter_two_conditions_basic():
    svc, report, c, ex = _nl()
    r = svc.propose("Hot 批且 Night 班的移動次數", report, None, contracts=c, executor=ex)
    assert r.direct_answer is not None
    assert r.direct_answer.value is not None
