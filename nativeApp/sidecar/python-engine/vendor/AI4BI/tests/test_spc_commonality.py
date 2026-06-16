"""Round 117: SPC control-limit outliers + cross-fact commonality."""

from __future__ import annotations

import pandas as pd

from ai4bi.analysis.crossfact import commonality
from ai4bi.analysis.executor import Executor
from ai4bi.analysis.spc import control_limit_outliers
from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_spc, _looks_like_commonality
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def test_spc_flags_outlier():
    # ten near-1.0 baseline tools + one clear outlier → flagged beyond mean+2sigma
    rows = []
    for i in range(10):
        rows.append({"tool": f"T{i}", "v": 1.0 + (i % 3) * 0.1})
    rows.append({"tool": "BAD", "v": 5.0})
    table, limits = control_limit_outliers(pd.DataFrame(rows), "tool", "v", k=2.0)
    assert not table.empty
    assert table.iloc[0]["tool"] == "BAD"
    assert limits["k"] == 2.0


def test_spc_no_outlier_when_uniform():
    df = pd.DataFrame({"t": ["A", "B", "C"], "v": [5.0, 5.0, 5.0]})
    table, limits = control_limit_outliers(df, "t", "v", k=3.0)
    assert table.empty


def test_commonality_lift_isolates_shared_tool():
    # failing wafers w1,w2 both used BADtool; w3 (passing) didn't
    detail = pd.DataFrame({
        "wafer": ["w1", "w1", "w2", "w2", "w3", "w3"],
        "tool":  ["BAD", "X1", "BAD", "X2", "G1", "X1"],
    })
    table = commonality(detail, "tool", "wafer", {"w1", "w2"})
    assert table.iloc[0]["tool"] == "BAD"
    assert table.iloc[0]["lift"] >= table.iloc[-1]["lift"]


def _nl():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def test_detectors():
    assert _looks_like_spc("超出平均 3 個標準差的機台", "超出平均 3 個標準差的機台")
    assert _looks_like_commonality("失敗 wafer 有沒有共同走過某台機台", "失敗 wafer 有沒有共同走過某台機台")


def test_nl_spc_routes():
    svc, report, c, ex = _nl()
    r = svc.propose("哪些機台 queue time 超出全廠平均 2 個標準差？", report, None, contracts=c, executor=ex)
    assert r.result_table is not None
    assert "tool_id" in r.result_table.columns


def test_nl_commonality_finds_etch02():
    svc, report, c, ex = _nl()
    r = svc.propose("良率掉到 80% 以下的晶圓有沒有共同走過某台機台？", report, None, contracts=c, executor=ex)
    assert r.result_table is not None
    # ETCH-02 is the embedded excursion tool → highest lift
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"
