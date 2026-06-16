"""Round 139: cross-tab routing ("各X、各Y"), breakdown per-group population,
and honest partial multi-filter when a named condition can't map to the fact."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_matrix, _looks_like_multi_filter,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _ctx():
    contracts = fab_contracts()
    return (NL2ProposalService(), build_fab_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_detectors():
    assert _looks_like_matrix("各區、各班別的平均 queue time？", "各區、各班別的平均 queue time？")
    assert _looks_like_multi_filter("ETCH 區 Hot 批的平均良率", "etch 區 hot 批的平均良率")


def test_crosstab_two_dimensions():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("各區、各班別的平均 queue time？", report, None,
                    contracts=contracts, executor=ex)
    df = r.result_table
    assert df is not None and "交叉表" in (r.message or "")
    # a cross-tab has the second dimension spread across columns
    assert len(df.columns) >= 3


def test_breakdown_per_group_population():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("各產品的良率，分別是用幾片晶圓算的？", report, None,
                    contracts=contracts, executor=ex)
    df = r.result_table
    assert df is not None and any("片數" in str(c) or "筆數" in str(c) for c in df.columns)


def test_multifilter_honest_partial():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("ETCH 區 Hot 批的平均良率是多少？", report, None,
                    contracts=contracts, executor=ex)
    # applies the resolvable condition (priority=Hot) and discloses the area gap
    msg = r.message or ""
    assert "Hot" in msg and ("area" in msg or "區" in msg)
    assert "全期間" not in msg  # not the silent-wrong overall number
