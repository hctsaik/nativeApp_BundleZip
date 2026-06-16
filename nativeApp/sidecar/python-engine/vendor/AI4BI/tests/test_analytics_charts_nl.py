"""Round 105: NL on-ramp for postprocess / forecast engines."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _detect_analytics_chart
from ai4bi.analysis.postprocess import add_share_of_total
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    return NL2ProposalService(), build_retail_demo_report(), {"retail_sales": build_retail_sales_block()}


def _added(proposal):
    for ch in proposal.changes:
        if ch.path.endswith("/add_visual") and ch.after:
            return ch.after["visual"]
    return None


def test_detector():
    assert _detect_analytics_chart("營收的 pareto 分析") == "pareto"
    # Round 120: a plain '佔比' question is now an inline share table; only with a
    # chart verb does it become a share *chart* proposal.
    assert _detect_analytics_chart("各地區營收佔比圖") == "share"
    assert _detect_analytics_chart("各地區營收佔比") is None
    assert _detect_analytics_chart("營收 3 個月移動平均") == "moving_avg"
    assert _detect_analytics_chart("預測下個月營收") == "forecast"
    assert _detect_analytics_chart("營收多少") is None


def test_share_of_total_helper():
    df = pd.DataFrame({"c": ["A", "B"], "v": [75.0, 25.0]})
    out = add_share_of_total(df, "v")
    assert list(out["佔總比(%)"]) == [75.0, 25.0]


def test_pareto_chart_proposal():
    svc, report, contracts = _ctx()
    result = svc.propose("營收的 pareto 分析 依商品", report, None, contracts=contracts)
    assert result.proposal is not None, result.message
    v = _added(result.proposal)
    assert v["visualization"]["extra"]["postprocess"] == "pareto"


def test_share_chart_proposal():
    # explicit '圖' → a share chart proposal
    svc, report, contracts = _ctx()
    result = svc.propose("各地區營收佔比圖", report, None, contracts=contracts)
    v = _added(result.proposal)
    assert v["visualization"]["extra"]["postprocess"] == "share_of_total"
    assert v["query"]["dimensions"]


def test_share_question_inline_table():
    # Round 120: a plain '佔比' question returns an inline share table (executor),
    # not a chart proposal.
    from ai4bi.analysis.executor import Executor
    from ai4bi.report.retail_template import build_retail_sales_block
    svc, report, contracts = _ctx()
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()})
    result = svc.propose("各地區營收佔比", report, None, contracts=contracts, executor=ex)
    assert result.result_table is not None
    assert "佔總比%" in result.result_table.columns


def test_moving_average_proposal_with_window():
    svc, report, contracts = _ctx()
    result = svc.propose("營收 3 期移動平均", report, None, contracts=contracts)
    v = _added(result.proposal)
    assert v["visualization"]["extra"]["postprocess"] == "moving_avg"
    assert v["visualization"]["extra"]["postprocess_window"] == 3
    assert v["visualization"]["visual_type"] == "line_chart"


def test_forecast_proposal_with_periods():
    svc, report, contracts = _ctx()
    result = svc.propose("預測未來 6 期營收", report, None, contracts=contracts)
    v = _added(result.proposal)
    tl = v["visualization"]["extra"]["trend_line"]
    assert tl["forecast_periods"] == 6


def test_absent_metric_does_not_crash():
    svc, report, contracts = _ctx()
    # gross margin doesn't exist → should not produce a wrong-metric chart
    result = svc.propose("毛利率 pareto", report, None, contracts=contracts)
    if result.proposal is not None:
        v = _added(result.proposal)
        # if a chart was built it must not be on return_rate (the old fuzzy match)
        metrics = v["query"]["metrics"]
        assert all(m["metric_name"] != "return_rate" for m in metrics)
