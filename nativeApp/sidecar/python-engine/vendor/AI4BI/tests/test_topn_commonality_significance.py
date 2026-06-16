"""Round 140: true top-N commonality (worst-by-measure lots share which tool,
with lift + Fisher) and Welch significance on subgroup comparison."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.analysis.executor import Executor
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _ctx():
    contracts = fab_contracts()
    return (NL2ProposalService(), build_fab_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_topdefect_commonality_is_real_not_ranking():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("defect die 最多的那幾批，共同走過哪一台 etch 機台？", report, None,
                    contracts=contracts, executor=ex)
    df = r.result_table
    assert df is not None
    # true commonality carries lift + Fisher columns, not a plain ranking
    assert "lift" in df.columns and "p_value" in df.columns
    assert "涵蓋率%" in df.columns
    assert "共同" in (r.message or "") and "Fisher" in (r.message or "")


def test_subgroup_compare_reports_significance():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("Hot 批的 cycle time 是不是比一般批長？", report, None,
                    contracts=contracts, executor=ex)
    # small Hot sample / tiny gap -> must surface a significance or small-sample caveat
    msg = r.message or ""
    assert ("t 檢定" in msg) or ("樣本" in msg)
