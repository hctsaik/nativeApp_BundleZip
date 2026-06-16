"""
PromptRouter — R1 Mock Implementation
AI-for-BI Platform / Round 007

Classifies user prompts into:
  - "style"    : VisualizationSpec mutation only (no data re-query)
  - "analysis" : VisualQuerySpec mutation (triggers data re-query)
  - "both"     : both pipelines fire (style first, analysis second)
  - "unknown"  : confidence too low, triggers disambiguation UX

Design contract:
  Style = operations that do NOT change WHERE / GROUP BY / SELECT
  Analysis = operations that DO change WHERE / GROUP BY / SELECT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

RouteTarget = Literal["style", "analysis", "both", "unknown"]


# ---------------------------------------------------------------------------
# RouterResult
# ---------------------------------------------------------------------------

@dataclass
class RouterResult:
    """Output of PromptRouter.route()."""

    route_to: RouteTarget
    """Primary routing decision."""

    confidence: float
    """0.0 – 1.0.  < 0.60 triggers disambiguation UX."""

    style_fragment: dict
    """Partial VisualizationSpec fields inferred from the prompt.
    Empty dict when route_to == 'analysis'."""

    analysis_fragment: dict
    """Partial VisualQuerySpec fields inferred from the prompt.
    Empty dict when route_to == 'style'."""

    matched_style_signals: list[str] = field(default_factory=list)
    """Debug: style keywords that fired."""

    matched_analysis_signals: list[str] = field(default_factory=list)
    """Debug: analysis keywords that fired."""

    user_confirmed_route: Optional[RouteTarget] = None
    """Populated after disambiguation UX resolves."""

    ambiguity_reason: Optional[str] = None
    """Human-readable reason shown in disambiguation UX."""


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

# Each entry: (regex_pattern, confidence_weight, style_fragment_template)
STYLE_SIGNALS: list[tuple[str, float, dict]] = [

    # --- Tier 1: strong style (0.95) ---

    # colour
    (r"(改成|設為|換成|變成)?.*(紅|橙|黃|綠|藍|紫|黑|白|灰|粉)色", 0.95,
     {"lineColor": "__COLOR__"}),
    (r"color\s*[:=]\s*#?[0-9a-fA-F]{3,6}", 0.95,
     {"lineColor": "__COLOR__"}),

    # font
    (r"(字型|字體|font)(.*)(放大|縮小|改|換|大小|粗|細)", 0.90,
     {"fontSize": "__SIZE__", "fontFamily": "__FONT__"}),
    (r"(字體|字型)大小", 0.85,
     {"fontSize": "__SIZE__"}),

    # legend / label / axis visibility
    (r"隱藏.*(圖例|legend)", 0.95,
     {"legendVisible": False}),
    (r"顯示.*(圖例|legend)", 0.95,
     {"legendVisible": True}),
    (r"隱藏.*(標籤|label)", 0.90,
     {"labelVisible": False}),
    (r"顯示.*(標籤|label)", 0.90,
     {"labelVisible": True}),
    (r"隱藏.*(X軸|x軸|橫軸)", 0.90,
     {"xAxisVisible": False}),
    (r"隱藏.*(Y軸|y軸|縱軸)", 0.90,
     {"yAxisVisible": False}),

    # opacity / transparency
    (r"(透明度|opacity)\s*(\d{1,3}%?)", 0.95,
     {"opacity": "__VALUE__"}),

    # border
    (r"(加上|移除|加|去).*(邊框|border)", 0.90,
     {"borderWidth": "__VALUE__"}),

    # line style / width
    (r"(虛線|dashed)", 0.95,
     {"lineStyle": "dashed"}),
    (r"(實線|solid)", 0.90,
     {"lineStyle": "solid"}),
    (r"線(寬|粗|細)", 0.85,
     {"lineWidth": "__VALUE__"}),

    # tick format — time / date / number
    (r"(時間|日期|date|time).*(格式|format)", 0.90,
     {"tickFormat": "__FORMAT__"}),
    (r"格式.*(YYYY|yyyy|MM|DD|HH|mm|ss)", 0.95,
     {"tickFormat": "__FORMAT__"}),
    (r"(數字|number).*(格式|format)", 0.85,
     {"tickFormat": "__FORMAT__"}),

    # --- Tier 2: medium style (0.75) ---

    # chart type switch (ambiguous — may affect dimension requirements)
    (r"(改成|換成|變成).*(折線圖|line\s*chart)", 0.70,
     {"chartType": "line"}),
    (r"(改成|換成|變成).*(長條圖|bar\s*chart|柱狀圖)", 0.70,
     {"chartType": "bar"}),
    (r"(改成|換成|變成).*(圓餅圖|pie\s*chart|餅圖)", 0.70,
     {"chartType": "pie"}),
    (r"(改成|換成|變成).*(散點圖|scatter)", 0.70,
     {"chartType": "scatter"}),
    (r"(改成|換成|變成).*(面積圖|area\s*chart)", 0.70,
     {"chartType": "area"}),

    # theme
    (r"(主題|theme|配色)\s*(切換|改|換|暗|亮|dark|light)", 0.75,
     {"theme": "__THEME__"}),
    (r"(暗色|dark)\s*(模式|mode|主題|theme)", 0.80,
     {"theme": "dark"}),
    (r"(亮色|light)\s*(模式|mode|主題|theme)", 0.80,
     {"theme": "light"}),

    # Y-axis range (visual zoom, not data filter)
    (r"Y軸.*(範圍|range|最大|最小)", 0.70,
     {"yAxisMin": "__VALUE__", "yAxisMax": "__VALUE__"}),

    # --- Tier 3: weak style (0.55) ---
    # These alone are insufficient — they only contribute when combined
    (r"(百分比|percent|%)\s*(格式|format|顯示|show)", 0.55,
     {"tickFormat": "{:.0%}"}),
    (r"(格式化|格式)", 0.50,
     {"tickFormat": "__FORMAT__"}),
]


# Each entry: (regex_pattern, confidence_weight, analysis_fragment_template)
ANALYSIS_SIGNALS: list[tuple[str, float, dict]] = [

    # --- Tier 1: strong analysis (0.95) ---

    # metric selection / addition
    (r"(顯示|查詢|看|加入|新增).*(營收|收入|銷售額|revenue|sales)", 0.95,
     {"metrics": ["revenue"]}),
    (r"(顯示|查詢|看|加入|新增).*(利潤|profit|毛利)", 0.95,
     {"metrics": ["profit"]}),
    (r"(顯示|查詢|看|加入|新增).*(訂單數|訂單量|orders?)", 0.95,
     {"metrics": ["order_count"]}),
    (r"(顯示|查詢|看|加入|新增).*(使用者|用戶|用户|users?)", 0.95,
     {"metrics": ["user_count"]}),
    (r"(移除|拿掉|刪除).*(指標|metrics?|維度|dimension)", 0.92,
     {"_mutation": "remove_metric_or_dimension"}),

    # dimension grouping
    (r"(依|按|以|by)\s*.*(月|月份|month)", 0.95,
     {"dimensions": ["month"]}),
    (r"(依|按|以|by)\s*.*(季|季度|quarter)", 0.95,
     {"dimensions": ["quarter"]}),
    (r"(依|按|以|by)\s*.*(年|year)", 0.92,
     {"dimensions": ["year"]}),
    (r"(依|按|以|by)\s*.*(日|天|day|date)", 0.92,
     {"dimensions": ["date"]}),
    (r"(依|按|以|by)\s*.*(地區|區域|region)", 0.90,
     {"dimensions": ["region"]}),
    (r"(依|按|以|by)\s*.*(產品|品項|product)", 0.90,
     {"dimensions": ["product"]}),
    (r"(依|按|以|by)\s*.*(類別|category)", 0.90,
     {"dimensions": ["category"]}),
    (r"分組|group\s*by", 0.88,
     {"_mutation": "add_dimension"}),

    # filters — region
    (r"(北區|北部|north)", 0.93,
     {"filters": [{"field": "region", "op": "eq", "value": "north"}]}),
    (r"(南區|南部|south)", 0.93,
     {"filters": [{"field": "region", "op": "eq", "value": "south"}]}),
    (r"(中區|中部|central)", 0.93,
     {"filters": [{"field": "region", "op": "eq", "value": "central"}]}),
    (r"(東區|東部|east)", 0.93,
     {"filters": [{"field": "region", "op": "eq", "value": "east"}]}),

    # filters — time
    (r"(本月|這個月|this\s*month)", 0.92,
     {"filters": [{"field": "date", "op": "this_month"}]}),
    (r"(上月|上個月|last\s*month)", 0.92,
     {"filters": [{"field": "date", "op": "last_month"}]}),
    (r"(本季|這一季|this\s*quarter)", 0.92,
     {"filters": [{"field": "date", "op": "this_quarter"}]}),
    (r"(上季|上一季|last\s*quarter)", 0.92,
     {"filters": [{"field": "date", "op": "last_quarter"}]}),
    (r"(今年|本年|this\s*year)", 0.90,
     {"filters": [{"field": "date", "op": "this_year"}]}),
    (r"(去年|last\s*year)", 0.90,
     {"filters": [{"field": "date", "op": "last_year"}]}),

    # explicit filter verbs
    (r"(篩選|過濾|filter|只看|僅顯示|限定)", 0.88,
     {"_mutation": "add_filter"}),

    # comparison
    (r"(比較|compare|對比)\s*.+\s*(vs|和|與|跟|及)", 0.85,
     {"_mutation": "multi_series"}),

    # --- Tier 2: medium analysis (0.75) ---

    # metric computation type (may overlap with style %)
    (r"(計算|算出|新增).*(百分比|占比|比率|ratio|percent)", 0.78,
     {"metrics": ["__percent_metric__"]}),
    (r"(累計|cumulative|rolling|移動平均)", 0.80,
     {"_mutation": "add_derived_metric"}),

    # sorting by data dimension (not visual sort)
    (r"(依|按).*(營收|銷售|profit|revenue).*(排序|sort|排列)", 0.75,
     {"orderBy": "__METRIC__ DESC"}),
]


# Weak signals that raise ambiguity score
AMBIGUITY_SIGNALS: list[tuple[str, str]] = [
    (r"(更清楚|清楚一點|清晰)", "unclear_improvement"),
    (r"(更簡單|簡化|簡潔)", "simplify"),
    (r"(更好看|好看|美觀|漂亮)", "aesthetic_improvement"),
    (r"(更好|改善|優化)", "vague_improvement"),
    (r"(百分比|percent|%)(?!\s*(格式|format|顯示|show))", "percent_ambiguous"),
]


# ---------------------------------------------------------------------------
# PromptRouter
# ---------------------------------------------------------------------------

class PromptRouter:
    """
    Keyword-based intent router for R1 (no LLM call).

    Usage:
        router = PromptRouter()
        result = router.route("把線改成紅色", current_spec={})
        # result.route_to == "style", result.confidence == 0.95

    Confidence thresholds:
        >= 0.75  : confident route, execute directly
        0.60–0.74: confident enough, but show lightweight confirmation toast
        0.40–0.59: show disambiguation dialog
        0.00–0.39: NO_COMPREHENSION UX
    """

    CONFIDENT_THRESHOLD = 0.75
    DIALOG_THRESHOLD = 0.60
    TOAST_THRESHOLD = 0.40

    def __init__(self):
        self._style_patterns = [
            (re.compile(p, re.IGNORECASE | re.UNICODE), w, f)
            for p, w, f in STYLE_SIGNALS
        ]
        self._analysis_patterns = [
            (re.compile(p, re.IGNORECASE | re.UNICODE), w, f)
            for p, w, f in ANALYSIS_SIGNALS
        ]
        self._ambiguity_patterns = [
            (re.compile(p, re.IGNORECASE | re.UNICODE), reason)
            for p, reason in AMBIGUITY_SIGNALS
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, prompt: str, current_spec: dict | None = None) -> RouterResult:
        """
        Classify a user prompt.

        Parameters
        ----------
        prompt : str
            Raw user input text.
        current_spec : dict, optional
            Current VisualQuerySpec + VisualizationSpec merged context.
            Used for context-aware disambiguation (future use, R1 ignores).

        Returns
        -------
        RouterResult
        """
        current_spec = current_spec or {}

        style_score, style_signals, style_fragment = self._score_style(prompt)
        analysis_score, analysis_signals, analysis_fragment = self._score_analysis(prompt)
        ambiguity_reasons = self._detect_ambiguity(prompt)

        route_to, confidence, ambiguity_reason = self._decide(
            style_score, analysis_score, ambiguity_reasons
        )

        return RouterResult(
            route_to=route_to,
            confidence=confidence,
            style_fragment=style_fragment if route_to in ("style", "both") else {},
            analysis_fragment=analysis_fragment if route_to in ("analysis", "both") else {},
            matched_style_signals=style_signals,
            matched_analysis_signals=analysis_signals,
            ambiguity_reason=ambiguity_reason,
        )

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _score_style(self, prompt: str) -> tuple[float, list[str], dict]:
        """Return (max_confidence, matched_signals, merged_fragment)."""
        max_conf = 0.0
        signals: list[str] = []
        fragment: dict = {}

        for pattern, weight, template in self._style_patterns:
            m = pattern.search(prompt)
            if m:
                signals.append(m.group(0))
                max_conf = max(max_conf, weight)
                # Merge template into fragment (shallow; placeholders kept for R1)
                for k, v in template.items():
                    if k not in fragment:
                        fragment[k] = v

        return max_conf, signals, fragment

    def _score_analysis(self, prompt: str) -> tuple[float, list[str], dict]:
        """Return (max_confidence, matched_signals, merged_fragment)."""
        max_conf = 0.0
        signals: list[str] = []
        fragment: dict = {}

        for pattern, weight, template in self._analysis_patterns:
            m = pattern.search(prompt)
            if m:
                signals.append(m.group(0))
                max_conf = max(max_conf, weight)
                for k, v in template.items():
                    if k == "_mutation":
                        fragment.setdefault("_mutations", []).append(v)
                    elif k not in fragment:
                        fragment[k] = v

        return max_conf, signals, fragment

    def _detect_ambiguity(self, prompt: str) -> list[str]:
        reasons: list[str] = []
        for pattern, reason in self._ambiguity_patterns:
            if pattern.search(prompt):
                reasons.append(reason)
        return reasons

    def _decide(
        self,
        style_score: float,
        analysis_score: float,
        ambiguity_reasons: list[str],
    ) -> tuple[RouteTarget, float, Optional[str]]:
        """
        Core decision logic.

        Decision table:
        ┌──────────────┬──────────────┬──────────────────────────────────────┐
        │ style_score  │ analysis_score│ result                              │
        ├──────────────┼──────────────┼──────────────────────────────────────┤
        │ high (≥0.75) │ low (<0.60)  │ style, confidence = style_score     │
        │ low (<0.60)  │ high (≥0.75) │ analysis, confidence = analysis_score│
        │ both ≥ 0.60  │ both ≥ 0.60  │ both, confidence = min(s,a)         │
        │ ambiguity    │ —            │ unknown, confidence reduced          │
        │ both < 0.40  │ both < 0.40  │ unknown, NO_COMPREHENSION           │
        └──────────────┴──────────────┴──────────────────────────────────────┘
        """
        ambiguity_reason: Optional[str] = None

        # Ambiguity penalty: each ambiguity signal reduces combined confidence
        ambiguity_penalty = min(0.30, len(ambiguity_reasons) * 0.10)

        has_style = style_score >= 0.60
        has_analysis = analysis_score >= 0.60

        if has_style and has_analysis:
            confidence = min(style_score, analysis_score) - ambiguity_penalty
            return "both", max(0.0, confidence), None

        if has_style and not has_analysis:
            confidence = style_score - ambiguity_penalty
            return "style", max(0.0, confidence), None

        if has_analysis and not has_style:
            confidence = analysis_score - ambiguity_penalty
            return "analysis", max(0.0, confidence), None

        # Weak signals on one side
        if style_score >= 0.40 and analysis_score < 0.40:
            confidence = style_score - ambiguity_penalty
            if confidence >= 0.40:
                return "style", confidence, "low_confidence_style"
        if analysis_score >= 0.40 and style_score < 0.40:
            confidence = analysis_score - ambiguity_penalty
            if confidence >= 0.40:
                return "analysis", confidence, "low_confidence_analysis"

        # Both weak or ambiguity dominant
        if ambiguity_reasons:
            ambiguity_reason = ", ".join(ambiguity_reasons)
            return "unknown", max(style_score, analysis_score, 0.0), ambiguity_reason

        return "unknown", 0.0, "no_signal"


# ---------------------------------------------------------------------------
# Disambiguation UX helper
# ---------------------------------------------------------------------------

class DisambiguationUX:
    """
    Generates the correct UX instruction for the calling layer based on
    RouterResult.confidence.

    The actual UI rendering (dialog / toast / error) is done by the frontend.
    This class produces a structured payload the frontend consumes.
    """

    @staticmethod
    def get_ux_payload(result: RouterResult, original_prompt: str) -> dict:
        """
        Returns a dict the frontend uses to render the appropriate UX.

        UX types:
          "execute"            — confidence high enough, no UX needed
          "confirmation_toast" — light toast asking user to confirm
          "disambiguation_dialog" — modal dialog with route options
          "no_comprehension"   — error state, ask user to rephrase
        """
        c = result.confidence

        if c >= PromptRouter.CONFIDENT_THRESHOLD:
            return {"ux_type": "execute", "route": result.route_to}

        if c >= PromptRouter.DIALOG_THRESHOLD:
            # Toast: single candidate, just needs quick confirm
            return {
                "ux_type": "confirmation_toast",
                "message": DisambiguationUX._toast_message(result),
                "confirm_route": result.route_to,
                "original_prompt": original_prompt,
            }

        if c >= PromptRouter.TOAST_THRESHOLD:
            # Full dialog: present all route options
            return {
                "ux_type": "disambiguation_dialog",
                "message": f"我對「{original_prompt}」這個指令有點不確定，你是想要：",
                "options": DisambiguationUX._dialog_options(result),
                "ambiguity_reason": result.ambiguity_reason,
                "original_prompt": original_prompt,
            }

        # NO_COMPREHENSION
        return {
            "ux_type": "no_comprehension",
            "message": f"我看不懂「{original_prompt}」這個指令",
            "suggestions": [
                "指定要調整的圖表元素（圖例、X 軸、標題⋯）",
                "說明要改成什麼（隱藏、放大、換顏色⋯）",
                "或指定資料範圍（北區、本月、依月份⋯）",
            ],
            "original_prompt": original_prompt,
        }

    @staticmethod
    def _toast_message(result: RouterResult) -> str:
        if result.route_to == "style":
            return "我猜你想調整圖表外觀，先試試看？"
        if result.route_to == "analysis":
            return "我猜你想修改資料查詢條件，先試試看？"
        return "我猜你想同時調整外觀和查詢，先試試看？"

    @staticmethod
    def _dialog_options(result: RouterResult) -> list[dict]:
        options = [
            {
                "key": "style",
                "label": "調整圖表外觀（不重新查詢資料）",
                "description": "例：改顏色、隱藏標籤、調整格式",
            },
            {
                "key": "analysis",
                "label": "修改分析條件（重新查詢資料）",
                "description": "例：篩選地區、改變分組、新增指標",
            },
            {
                "key": "both",
                "label": "兩者都做",
                "description": "同時調整外觀和資料查詢",
            },
        ]
        # Pre-select the Router's best guess if confidence ≥ 0.40
        if result.route_to != "unknown" and result.confidence >= 0.40:
            for opt in options:
                opt["preselected"] = opt["key"] == result.route_to
        return options

    @staticmethod
    def apply_user_choice(result: RouterResult, chosen_route: RouteTarget) -> RouterResult:
        """
        Called after the user resolves disambiguation.
        Updates result in-place and returns it.
        """
        result.user_confirmed_route = chosen_route
        result.route_to = chosen_route
        result.confidence = 1.0  # User has confirmed, treat as certain
        return result


# ---------------------------------------------------------------------------
# Session-level confidence boost (short-term memory)
# ---------------------------------------------------------------------------

class SessionRouter:
    """
    Wraps PromptRouter with within-session preference memory.

    When a user resolves a disambiguation, we record which route they chose
    for that prompt pattern.  Subsequent similar prompts get a +0.10 boost
    toward the confirmed route.

    R1 scope: pattern similarity = same ambiguity_reason string.
    """

    BOOST = 0.10

    def __init__(self):
        self._router = PromptRouter()
        self._confirmed: dict[str, RouteTarget] = {}
        # key: ambiguity_reason → user_confirmed_route

    def route(self, prompt: str, current_spec: dict | None = None) -> RouterResult:
        result = self._router.route(prompt, current_spec)

        # Apply session boost
        if result.ambiguity_reason and result.ambiguity_reason in self._confirmed:
            preferred_route = self._confirmed[result.ambiguity_reason]
            if result.route_to == "unknown" or result.route_to == preferred_route:
                result.route_to = preferred_route
                result.confidence = min(1.0, result.confidence + self.BOOST)

        return result

    def record_user_choice(self, result: RouterResult, chosen_route: RouteTarget) -> RouterResult:
        if result.ambiguity_reason:
            self._confirmed[result.ambiguity_reason] = chosen_route
        return DisambiguationUX.apply_user_choice(result, chosen_route)


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    router = PromptRouter()
    ux = DisambiguationUX()

    test_cases = [
        # (prompt, expected_route)
        ("顯示北區營收", "analysis"),
        ("把線改成紅色", "style"),
        ("依月份分組", "analysis"),
        ("隱藏圖例", "style"),
        ("把 X 軸的時間格式改成 YYYY-MM", "style"),
        ("折線圖改成長條圖", "style"),           # chartType, ambiguous
        ("把這個指標改成百分比", "unknown"),     # ambiguous
        ("把這個圖改成更清楚的方式呈現", "unknown"),
        ("讓這個圖更簡單", "unknown"),
        ("依月份顯示北區營收並把線改成藍色", "both"),
    ]

    print(f"{'Prompt':<40} {'Expected':<10} {'Got':<10} {'Conf':>6}  Signals")
    print("-" * 90)
    for prompt, expected in test_cases:
        r = router.route(prompt)
        status = "OK" if r.route_to == expected else "DIFF"
        signals = r.matched_style_signals + r.matched_analysis_signals
        print(
            f"{prompt:<40} {expected:<10} {r.route_to:<10} {r.confidence:>6.2f}  "
            f"[{status}] {signals[:2]}"
        )

    print("\n--- Disambiguation UX payloads ---")
    for prompt in ["把這個圖改成更清楚的方式呈現", "讓這個圖更簡單", "顯示北區"]:
        r = router.route(prompt)
        payload = DisambiguationUX.get_ux_payload(r, prompt)
        print(f"\nPrompt: {prompt!r}")
        print(f"  UX type : {payload['ux_type']}")
        print(f"  Message : {payload.get('message', '')}")
