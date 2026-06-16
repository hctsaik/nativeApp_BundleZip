"""Round 142: target verdict, inline forecast value, tool-dimension override,
cost honest-decline, and cross-fact attribution-washout honesty."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import NL2ProposalService, _honest_limitation
from ai4bi.analysis.executor import Executor
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


def _ctx():
    contracts = fab_contracts()
    return (NL2ProposalService(), build_fab_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_cost_is_declined_honestly():
    assert _honest_limitation("每片報廢晶圓的成本損失是多少？", "每片報廢晶圓的成本損失是多少？")
    svc, report, contracts, ex = _ctx()
    r = svc.propose("每片報廢晶圓的成本損失是多少？", report, None,
                    contracts=contracts, executor=ex)
    assert r.result_table is None and "成本" in (r.message or "")


def test_target_verdict():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("良率有沒有達到 95% 的目標？", report, None,
                    contracts=contracts, executor=ex)
    assert "未達標" in (r.message or "") or "已達標" in (r.message or "")


def test_forecast_gives_number():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("照這個趨勢，下個月良率大概多少？", report, None,
                    contracts=contracts, executor=ex)
    assert "外推" in (r.message or "") and "未來" in (r.message or "")


def test_which_tool_groups_by_tool_not_lot():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("哪一台機台最常造成 lot 被 hold？", report, None,
                    contracts=contracts, executor=ex)
    df = r.result_table
    assert df is not None and "tool_id" in df.columns and "lot_id" not in df.columns


def test_vendor_attribution_honesty_not_silent_overall():
    svc, report, contracts, ex = _ctx()
    r = svc.propose("哪一家設備供應商的良率比較差？", report, None,
                    contracts=contracts, executor=ex)
    msg = r.message or ""
    # must not silently return the unfiltered overall; must disclose attribution limit
    assert "全期間" not in msg
    assert "歸因" in msg or "commonality" in msg
