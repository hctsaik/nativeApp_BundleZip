"""Round 156: advanced-analysis panels are data-driven — retail-only analyses
(cohort/basket/RFM) must NOT apply to semiconductor data; decline-detection does.
"""

from __future__ import annotations

from ai4bi.ui.rfm_panel import _rfm_applicable
from ai4bi.ui.cohort_panel import _cohort_applicable
from ai4bi.ui.basket_panel import _basket_applicable
from ai4bi.ui.trend_streak_panel import _streak_applicable
from ai4bi.report.retail_template import build_retail_sales_block
from ai4bi.report.fab_template import fab_contracts


def _fab_move():
    return fab_contracts()["fab_process_move"]


def test_retail_block_supports_customer_analyses():
    retail = build_retail_sales_block()
    assert _rfm_applicable(retail) is True
    assert _cohort_applicable(retail) is True
    assert _basket_applicable(retail) is True
    assert _streak_applicable(retail) is True


def test_fab_block_excludes_customer_analyses():
    fab = _fab_move()
    # no customer / money / order columns -> these retail analyses must not apply
    assert _rfm_applicable(fab) is False
    assert _cohort_applicable(fab) is False
    assert _basket_applicable(fab) is False


def test_fab_block_supports_decline_detection():
    # decline-detection works on tool x date x metric (queue time), so it applies
    assert _streak_applicable(_fab_move()) is True


# Round 174: the 分析-mode RESULT TABS (not just the sidebar panels) must be
# data-driven, or a semiconductor report shows irrelevant retail tabs.
from ai4bi.ui.app import _analysis_tabs_for_facts


def _labels(facts):
    return [lbl for lbl, _ in _analysis_tabs_for_facts(facts)]


def test_fab_analysis_tabs_exclude_retail():
    labels = _labels({"fab_process_move": _fab_move()})
    assert "客戶留存" not in labels
    assert "常一起購買" not in labels
    assert "RFM" not in labels
    # fab-applicable / general analyses remain
    assert "連續下滑" in labels
    assert "變化分解" in labels
    assert "業務摘要" in labels


def test_retail_analysis_tabs_include_customer_analyses():
    labels = _labels({"retail_sales": build_retail_sales_block()})
    for expected in ("客戶留存", "常一起購買", "RFM", "連續下滑", "變化分解", "業務摘要"):
        assert expected in labels


def test_change_and_summary_always_offered():
    # general business analyses are present even with no applicable fact data
    labels = _labels({})
    assert labels == ["變化分解", "業務摘要"]
