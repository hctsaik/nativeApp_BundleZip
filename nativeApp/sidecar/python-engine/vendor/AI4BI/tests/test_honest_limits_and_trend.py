"""Round 138: honest limitation (no fake nearest-metric for unsupported asks),
yield excursion detection, and metric trend direction."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _honest_limitation, _looks_like_excursion,
    _looks_like_trend_direction,
)
from ai4bi.analysis.executor import Executor
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _ctx():
    contracts = fab_contracts()
    return (NL2ProposalService(), build_fab_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_honest_limit_detectors():
    assert _honest_limitation("給我每片晶圓的 X-Y 缺陷分佈圖", "x-y 缺陷分佈圖")
    assert _honest_limitation("逐站列出每片晶圓走過的機台", "逐站列出")
    assert _honest_limitation("平均良率多少", "平均良率多少") is None


def test_wafer_map_declined_not_faked():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("給我 ETCH-02 每片晶圓的 X-Y 缺陷分佈圖。", report, None,
                    contracts=contracts, executor=ex)
    # must NOT return a nearest-metric table; must honestly decline
    assert r.result_table is None
    assert "wafer map" in (r.message or "") or "X-Y" in (r.message or "")


def test_excursion_finds_low_yield_lots():
    svc, report, contracts, ex = _ctx()
    assert _looks_like_excursion("有沒有哪幾批良率突然掉下來？", "有沒有哪幾批良率突然掉下來？")
    r = svc.propose("有沒有哪幾批良率突然掉下來？", report, None,
                    contracts=contracts, executor=ex)
    # the demo seeds excursion lots ~72%; should surface specific lots, not overall
    assert "全期間" not in (r.message or "")
    assert r.result_table is not None and len(r.result_table) >= 1


def test_trend_direction():
    svc, report, contracts, ex = _ctx()
    assert _looks_like_trend_direction("良率這幾週是變好還是變差？", "良率這幾週是變好還是變差？")
    r = svc.propose("良率這幾週是變好還是變差？", report, None,
                    contracts=contracts, executor=ex)
    assert "趨勢" in (r.message or "") and "全期間" not in (r.message or "")
