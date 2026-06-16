"""
tests.ux.scenarios — chart-usage / UI-UX scenarios for goal 3.

Each scenario is a realistic way an SMB semiconductor-fab analyst (or owner)
reads a chart, plus the theme we recommend and the sub-metric that scenario
stresses most. ``score_scenario`` re-weights the objective theme sub-scores by
that emphasis so, e.g., a print one-pager leans on text/background contrast
while a many-series comparison leans on palette distinctness + CVD safety.

Iteration log (see docs/theme-ux-validation.md):
  * Round 1 batch (10 scenarios) → multi-agent avg 71.9–80.9; surfaced 7 real
    defects (gray-as-data, near-white map ramps, text-color series collision,
    pale thin lines, serif chart furniture, no dark theme in menu).
  * Fixes applied to the theme system, then THIS round-2 batch was generated
    fresh and re-evaluated. It stresses the weak spots from round 1
    (7+ series, stacked, dual-axis, sequential, explicit CVD reader, grayscale
    print, dark control-room, small mobile text, brand screenshot, KPI wall).
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.ux.theme_score import score_theme


@dataclass(frozen=True)
class Scenario:
    sid: str
    title: str          # zh-TW
    chart_types: tuple[str, ...]
    theme: str          # recommended theme key
    emphasis: dict[str, float]  # sub-score weights for THIS scenario
    rationale: str


# Weight presets for common chart intents -----------------------------------
_COMPARE = {"contrast": 0.20, "distinct": 0.40, "cvd": 0.35, "depth": 0.05}   # many series
_SINGLE = {"contrast": 0.55, "distinct": 0.20, "cvd": 0.20, "depth": 0.05}    # 1–2 series
_PRINT = {"contrast": 0.50, "distinct": 0.25, "cvd": 0.20, "depth": 0.05}     # legibility-first
_DENSE = {"contrast": 0.30, "distinct": 0.35, "cvd": 0.30, "depth": 0.05}     # facets / dashboards
_CVD = {"contrast": 0.20, "distinct": 0.25, "cvd": 0.50, "depth": 0.05}       # CVD reader


SCENARIOS: list[Scenario] = [
    Scenario("multiseries_line", "7+ 機台良率多系列折線", ("line",), "tableau", _COMPARE,
             "七八條機台良率線同框，後段系列也要彼此分明。"),
    Scenario("stacked_structure", "缺陷類型 100% 堆疊長條", ("bar",), "powerbi", _COMPARE,
             "堆疊長條看每月缺陷結構，相鄰色塊不能糊在一起。"),
    Scenario("dual_axis", "良率 vs 產量 雙軸圖", ("line", "bar"), "executive", _SINGLE,
             "雙軸兩個量綱，兩條主色要強、互不干擾。"),
    Scenario("wafer_heatmap", "晶圓良率連續色階熱區", ("map", "histogram"), "executive", _SINGLE,
             "連續色階表示良率高低，低值區也要看得見、不被白底吃掉。"),
    Scenario("cvd_reader", "色盲工程師檢視多分群", ("scatter", "bar"), "tableau", _CVD,
             "紅綠色盲的工程師也要能分辨每個分群。"),
    Scenario("grayscale_print", "黑白列印的品質月報", ("line", "bar"), "editorial", _PRINT,
             "影印成黑白後，靠明度差仍能區分線條與文字。"),
    Scenario("darkroom_monitor", "產線大螢幕深色監控", ("line", "kpi"), "midnight", _COMPARE,
             "低光產線的大螢幕監控，深色底＋高亮資料色。"),
    Scenario("mobile_small", "手機小螢幕快速檢視", ("kpi", "bar"), "nordic", _SINGLE,
             "老闆用手機看，小字與小圖仍要清楚不刺眼。"),
    Scenario("brand_screenshot", "對外品牌簡報截圖", ("line", "kpi"), "executive", _SINGLE,
             "截圖貼到對外簡報，企業藍要穩重、有品牌感。"),
    Scenario("kpi_wall", "密集 KPI 監控牆", ("kpi",), "powerbi", _SINGLE,
             "十幾張 KPI 卡並排，紅黃綠燈與數字一眼可讀。"),
]


def score_scenario(scenario: Scenario) -> tuple[float, str]:
    """Objective score (0–100) for a scenario, using its recommended theme."""
    from ai4bi.ui import theme as theme_mod
    th = theme_mod.get_theme(scenario.theme)
    score, _ = score_theme(th, weights=scenario.emphasis)
    return score, th.key


def score_all() -> dict[str, float]:
    return {s.sid: score_scenario(s)[0] for s in SCENARIOS}
