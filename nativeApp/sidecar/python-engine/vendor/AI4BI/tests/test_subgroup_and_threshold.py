"""Round 137: subgroup comparison (cross-fact aware) + commonality threshold
parse that ignores digits embedded in identifiers like "ETCH-02"."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _parse_threshold, _looks_like_subgroup_compare,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _ctx():
    contracts = fab_contracts()
    return (NL2ProposalService(), build_fab_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_parse_threshold_ignores_identifier_digits():
    # "ETCH-02 ... 良率低於 80%" must parse 80, not 2 (from ETCH-02)
    assert _parse_threshold("走過 etch-02 的批，良率低於 80% 的") == 80.0
    assert _parse_threshold("yield below 75") == 75.0
    assert _parse_threshold("良率 90% 以上") == 90.0
    assert _parse_threshold("沒有數字") is None


def test_commonality_threshold_not_hijacked_by_tool_name():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("走過 ETCH-02 的批，良率低於 80% 的有沒有共同點？",
                    report, None, contracts=contracts, executor=ex)
    # should NOT say "沒有 yield_pct < 2.0"; should find the common tool
    assert "< 2.0" not in (r.message or "")
    assert r.result_table is not None and "lift" in r.result_table.columns


def test_subgroup_detector():
    assert _looks_like_subgroup_compare("有重工的批，良率是不是比較差？", "有重工的批，良率是不是比較差？")
    assert _looks_like_subgroup_compare("被 hold 的批 cycle time 比較長嗎", "被 hold 的批 cycle time 比較長嗎")
    assert not _looks_like_subgroup_compare("全廠平均良率多少", "全廠平均良率多少")


def test_subgroup_crossfact_rework_yield():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("有重工的批，良率是不是比較差？", report, None,
                    contracts=contracts, executor=ex)
    df = r.result_table
    assert df is not None and len(df) == 2  # 有 vs 無
    assert "yield" in "".join(df.columns).lower()
    assert "有" in (r.message or "") and "%" in (r.message or "")


def test_subgroup_samefact_shift_queue():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("Day 班和 Night 班的 queue time 有差嗎？", report, None,
                    contracts=contracts, executor=ex)
    df = r.result_table
    assert df is not None and len(df) == 2
    assert "shift" in df.columns
    # must NOT be the overall single-number answer
    assert "全期間" not in (r.message or "")
