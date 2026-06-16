"""Round 108: two-entity side-by-side comparison."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_entity_compare, _extract_compare_operands,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    contracts = {"retail_sales": build_retail_sales_block()}
    return (NL2ProposalService(), build_retail_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_detector_requires_compare_cue():
    assert _looks_like_entity_compare("比較台北和台中", "比較台北和台中")
    assert _looks_like_entity_compare("台北 vs 台中", "台北 vs 台中")
    # a list ('和') without a compare cue is NOT a comparison
    assert not _looks_like_entity_compare("營收和訂單數", "營收和訂單數")


def test_extract_operands():
    assert _extract_compare_operands("比較台北和台中的營收", "比較台北和台中的營收") == ("台北", "台中")
    assert _extract_compare_operands("台北 vs 台中", "台北 vs 台中") == ("台北", "台中")


def test_compare_two_cities_revenue():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("比較台北和台中的營收", report, None, contracts=contracts, executor=ex)
    df = result.result_table
    assert df is not None, result.message
    assert set(df["city"]) == {"台北", "台中"}
    assert "台北" in result.message and "台中" in result.message


def test_declines_when_value_not_found():
    svc, report, contracts, ex = _ctx()
    # 'Atlantis' isn't a city value → must decline (no result table), not guess
    result = svc.propose("比較 Atlantis 和 Narnia", report, None, contracts=contracts, executor=ex)
    assert result.result_table is None


def test_no_executor_falls_through():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("比較台北和台中", report, None, contracts=contracts, executor=None)
    assert result.result_table is None
