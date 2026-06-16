"""NL-to-proposal service for governed BI workflows.

Routing modes
-------------
LLM_MODE=mock (default)
    Deterministic keyword routing — no API calls, works in CI/offline.

LLM_MODE=anthropic + ANTHROPIC_API_KEY set
    Claude classifies the intent; the existing handler methods enforce
    governance (no SQL, certified-only metrics, etc.).  Falls back to
    keyword routing if the API call fails.
"""

from __future__ import annotations

import re
from typing import Any

from ai4bi.ai.intent_models import (
    AIIntent,
    AnalysisPlan,
    DirectAnswer,
    GovernanceRefusal,
    NL2ProposalResult,
    SemanticSelection,
)
from ai4bi.ai.llm_adapter import LLMAdapter
from ai4bi.ai.schema_index import MetricEntry, SchemaIndex  # Round 035: dynamic schema lookup
from ai4bi.query_spec import AggFunction, DimensionRef, MetricRef, VisualType
from ai4bi.report.models import ExecutableReportSpec, ReportChange, ReportProposal, ReportVisualSpec

# ---------------------------------------------------------------------------
# Round 027: Visual Composer — dimension keyword → (block_id, column, alias, truncate)
# ---------------------------------------------------------------------------
_DIM_KEYWORD_MAP: dict[str, tuple[str, str, str, str | None]] = {
    "月份": ("process_move_fact", "event_date", "Month", "month"),
    "月": ("process_move_fact", "event_date", "Month", "month"),
    "month": ("process_move_fact", "event_date", "Month", "month"),
    "weekly": ("process_move_fact", "event_date", "Week", "week"),
    "week": ("process_move_fact", "event_date", "Week", "week"),
    "週": ("process_move_fact", "event_date", "Week", "week"),
    "day": ("process_move_fact", "event_date", "Date", "day"),
    "daily": ("process_move_fact", "event_date", "Date", "day"),
    "日": ("process_move_fact", "event_date", "Date", "day"),
    "date": ("process_move_fact", "event_date", "Date", None),
    "vendor": ("tool_dim", "vendor", "Vendor", None),
    "供應商": ("tool_dim", "vendor", "Vendor", None),
    "廠商": ("tool_dim", "vendor", "Vendor", None),
    "tool": ("tool_dim", "tool_id", "Tool ID", None),
    "tool_id": ("tool_dim", "tool_id", "Tool ID", None),
    "工具": ("tool_dim", "tool_id", "Tool ID", None),
    "機台": ("tool_dim", "tool_id", "Tool ID", None),
    "step": ("process_step_dim", "step_name", "Step", None),
    "step_id": ("process_move_fact", "step_id", "Step ID", None),
    "製程": ("process_step_dim", "step_name", "Step", None),
    "product": ("lot_dim", "product_family", "Product Family", None),
    "product_family": ("lot_dim", "product_family", "Product Family", None),
    "產品": ("lot_dim", "product_family", "Product Family", None),
}

# ---------------------------------------------------------------------------
# Round 019: Chart-type change mappings
# Safe transitions: bar ↔ line only. table/kpi_card require different query
# contracts and are blocked (design-council 003-E safety review).
# ---------------------------------------------------------------------------

_CHART_TYPE_SAFE_TRANSITIONS: dict[VisualType, VisualType] = {
    VisualType.bar_chart:  VisualType.line_chart,
    VisualType.line_chart: VisualType.bar_chart,
    VisualType.pie_chart:  VisualType.bar_chart,
}

_CHART_TYPE_KEYWORDS: dict[str, VisualType] = {
    "bar": VisualType.bar_chart,
    "bar chart": VisualType.bar_chart,
    "長條圖": VisualType.bar_chart,
    "柱狀圖": VisualType.bar_chart,
    "line": VisualType.line_chart,
    "line chart": VisualType.line_chart,
    "折線圖": VisualType.line_chart,
    "trend chart": VisualType.line_chart,
    "pie": VisualType.pie_chart,
    "pie chart": VisualType.pie_chart,
    "donut": VisualType.pie_chart,
    "圓餅圖": VisualType.pie_chart,
    "甜甜圈圖": VisualType.pie_chart,
    "scatter": VisualType.scatter,
    "scatter chart": VisualType.scatter,
    "散點圖": VisualType.scatter,
    "散佈圖": VisualType.scatter,
    # Round 151: table + pivot are renderable conversion targets too.
    "table": VisualType.table,
    "表格": VisualType.table,
    "資料表": VisualType.table,
    "pivot": VisualType.pivot,
    "pivot table": VisualType.pivot,
    "樞紐": VisualType.pivot,
    "樞紐分析": VisualType.pivot,
    "交叉表": VisualType.pivot,
}

# Round 067: keyword → type for the *add a new visual* path (superset of
# _CHART_TYPE_KEYWORDS; KPI/table aren't valid in-place chart-type *changes*,
# but you can add them as new visuals). Kept separate so chart_type_change is
# unaffected.
_ADD_VISUAL_TYPE_KEYWORDS: dict[str, VisualType] = {
    **_CHART_TYPE_KEYWORDS,
    "kpi": VisualType.kpi_card,
    "kpi card": VisualType.kpi_card,
    "kpi 卡": VisualType.kpi_card,
    "看板": VisualType.kpi_card,
    "指標卡": VisualType.kpi_card,
    "table": VisualType.table,
    "資料表": VisualType.table,
    "表格": VisualType.table,
    "明細表": VisualType.table,
    "pivot": VisualType.pivot,
    "matrix": VisualType.pivot,
    "樞紐": VisualType.pivot,
    "樞紐表": VisualType.pivot,
    "交叉表": VisualType.pivot,
    "矩陣": VisualType.pivot,
    "map": VisualType.map,           # Round 083
    "地圖": VisualType.map,
    "地圖視覺": VisualType.map,
    "small multiples": VisualType.small_multiples,  # Round 094
    "small multiple": VisualType.small_multiples,
    "小倍數": VisualType.small_multiples,
    "小倍數圖": VisualType.small_multiples,
    "分面": VisualType.small_multiples,
    "分面圖": VisualType.small_multiples,
    "trellis": VisualType.small_multiples,
}

# ---------------------------------------------------------------------------
# Round 019: Dimension-change mappings (date truncation keywords)
# ---------------------------------------------------------------------------

_DIMENSION_DATE_KEYWORDS: dict[str, str] = {
    "month": "month",
    "monthly": "month",
    "月份": "month",
    "月": "month",
    "week": "week",
    "weekly": "week",
    "週": "week",
    "day": "day",
    "daily": "day",
    "日": "day",
    "quarter": "quarter",
    "季": "quarter",
    "year": "year",
    "yearly": "year",
    "年": "year",
}

# ---------------------------------------------------------------------------
# Round 019: Add-metric keywords
# ---------------------------------------------------------------------------

_METRIC_ADD_PATTERNS = (
    r"也加上\s*(\w+)",
    r"加上\s*(\w+)\s*指標",
    r"也顯示\s*(\w+)",
    r"add\s+metric\s+(\w+)",
    r"add\s+(\w+)\s*metric",
    r"add\s+the\s+(\w+)\s*metric",
    r"add\s+(\w+)\s+to\s+(?:this|the)\s+(?:chart|visual|graph)",
    r"include\s+(\w+)\s*metric",
    r"also\s+show\s+(\w+)",
    r"show\s+(?:also\s+)?(\w+)\s*metric",
    # Simple "add X" where X looks like a metric name (snake_case or known term)
    r"^add\s+(\w+(?:_\w+)+)$",           # "add move_count" (snake_case)
    r"^add\s+(move_count|queue_time|process_time|failed_wafer|weighted_yield)\b",
)

_REMOVE_METRIC_PATTERNS = (
    r"remove\s+(\w+)",
    r"delete\s+(\w+)\s*metric",
    r"移除\s*(\w+)",
    r"刪除\s*(\w+)\s*指標",
    r"drop\s+(\w+)\s*metric",
    r"取消\s*(\w+)\s*指標",
    r"hide\s+(\w+)\s*metric",
)

_RENAME_VISUAL_PATTERNS = (
    r"rename\s+(?:this\s+)?(?:chart|visual|graph)\s+to\s+[\"']?(.+?)[\"']?$",
    r"把[這这](?:張|个)?圖(?:改名|命名)(?:叫|為|成)\s*[\"']?(.+?)[\"']?$",
    r"change\s+(?:the\s+)?title\s+to\s+[\"']?(.+?)[\"']?$",
    r"set\s+title\s+(?:to\s+)?[\"']?(.+?)[\"']?$",
    r"名稱改成\s*[\"']?(.+?)[\"']?$",
    r"改名叫\s*[\"']?(.+?)[\"']?$",
)

_MAX_METRICS_PER_VISUAL = 3

_COLOR_HEX = {
    "red": "#D62728",
    "blue": "#1F77B4",
    "green": "#2CA02C",
    "orange": "#FF7F0E",
    "purple": "#9467BD",
    "gray": "#7F7F7F",
    "grey": "#7F7F7F",
    "black": "#111111",
}
_COLOR_ALIASES = {
    "red": "red",
    "blue": "blue",
    "green": "green",
    "orange": "orange",
    "purple": "purple",
    "gray": "gray",
    "grey": "grey",
    "black": "black",
    "紅": "red",
    "紅色": "red",
    "藍": "blue",
    "藍色": "blue",
    "綠": "green",
    "綠色": "green",
}
_STYLE_TERMS = (
    "color",
    "colour",
    "style",
    "line",
    "bar",
    "red",
    "blue",
    "green",
    "orange",
    "purple",
    "gray",
    "grey",
    "black",
)
_ANALYSIS_TERMS = (
    "analyze",
    "analysis",
    "explain",
    "why",
    "driver",
    "drivers",
    "breakdown",
    "trend",
    "compare",
    "investigate",
)
_QUEUE_TERMS = ("queue", "queue-time", "queue time", "wait", "waiting")
_SQL_REFUSAL_PATTERNS = (
    r"\bsql\b",
    r"\bjoin\b",
    r"\bselect\s+.+\bfrom\b",
    r"\byield\b.*\b(detail|row|raw|move|join)\b",
    r"\b(detail|row|raw|move)\b.*\byield\b.*\bjoin\b",
)

# ---------------------------------------------------------------------------
# Round 020: Date Filter keyword → relative period mapping
# Uses {anchor:"relative", period:...} — no datetime.now() call, deterministic.
# The execution layer resolves relative periods at query time.
# ---------------------------------------------------------------------------

_DATE_FILTER_PERIOD_MAP: dict[str, str] = {
    # last 3 months
    "最近3個月": "last_3m",
    "最近 3 個月": "last_3m",
    "最近三個月": "last_3m",
    "last 3 months": "last_3m",
    "last3months": "last_3m",
    "past 3 months": "last_3m",
    # last quarter
    "last quarter": "last_quarter",
    "上季": "last_quarter",
    "上一季": "last_quarter",
    "前一季": "last_quarter",
    # year to date
    "今年": "ytd",
    "ytd": "ytd",
    "year to date": "ytd",
    "this year": "ytd",
    "本年度": "ytd",
    # last 6 months
    "最近6個月": "last_6m",
    "最近 6 個月": "last_6m",
    "最近半年": "last_6m",
    "last 6 months": "last_6m",
    # last month
    "上個月": "last_month",
    "last month": "last_month",
    # clear date filter
    "清除日期": "clear",
    "clear date": "clear",
    "remove date filter": "clear",
    "取消日期篩選": "clear",
}

_DATE_FILTER_TRIGGER_TERMS = (
    "最近", "上季", "上一季", "前一季", "今年", "本年度",
    "last quarter", "last month", "last 3", "last 6",
    "ytd", "year to date", "this year", "past 3", "past 6",
    "清除日期", "clear date", "remove date",
)

_DATE_FILTER_GLOBAL_KEY = "date_range"


class NL2ProposalService:
    """Classifies natural-language BI requests into typed, governed outcomes.

    When LLM_MODE=anthropic and ANTHROPIC_API_KEY is set, Claude is used to
    classify the intent; the existing handler methods still enforce all
    governance rules (no SQL, certified-only paths, etc.).

    In all other cases the service falls back to the deterministic keyword
    router, ensuring offline / CI operation with zero external dependencies.
    """

    def propose(
        self,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None = None,
        semantic_model: dict[str, Any] | None = None,
        contracts: dict[str, Any] | None = None,
        executor: Any = None,
        conversation_state: dict[str, Any] | None = None,
    ) -> NL2ProposalResult:
        # Round 078: an executor lets the answer-engine compute a real number
        # through the governed query path. Stashed on self for the duration of
        # this call so the existing handler signatures stay untouched.
        self._executor = executor
        # Round 136: conversation memory for follow-up scope ("只看 ETCH",
        # "改成上週"). The app owns a per-session dict and passes it in; when none
        # is supplied (e.g. a reused service instance in tests/probe) we keep an
        # instance-level dict so multi-turn still works.
        if conversation_state is not None:
            self._convo_mem = conversation_state
        elif not hasattr(self, "_convo_mem"):
            self._convo_mem = {}
        normalized = _normalize(prompt)
        if not normalized:
            return self._unsupported(
                "Enter a governed BI request.",
                target_scope=_target_scope(selected_component_id),
            )

        # Governance hard-block runs before any routing (LLM or keyword).
        refusal = self._governance_refusal(normalized, semantic_model)
        if refusal is not None:
            intent = AIIntent(
                intent_kind="unsupported",
                target_scope=_target_scope(selected_component_id),
                trust_notes=refusal.trust_notes,
                risk_level=refusal.risk_level,
            )
            return NL2ProposalResult(
                intent=intent,
                message=refusal.reason,
                refusal=refusal,
                trust_notes=refusal.trust_notes,
                risk_level=refusal.risk_level,
            )

        # --- LLM-assisted intent classification (when enabled) ---
        try:
            classification = LLMAdapter().classify(
                prompt, report, selected_component_id, semantic_model=semantic_model
            )
            if classification.mode == "llm":
                result = self._dispatch_llm_intent(
                    classification, prompt, normalized, report,
                    selected_component_id, semantic_model, contracts,
                )
                if result is not None:
                    return result
                # None = LLM returned an intent we couldn't route; fall through
        except Exception:  # noqa: BLE001
            pass  # Any adapter failure → keyword fallback

        return self._keyword_propose(
            prompt, normalized, report, selected_component_id, semantic_model, contracts
        )

    # ------------------------------------------------------------------
    # LLM intent dispatcher
    # ------------------------------------------------------------------

    def _build_single_proposal(
        self,
        intent: str,
        params: dict,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Build a single proposal for one intent+params pair (used by mixed dispatch)."""
        clf = type("_C", (), {"intent": intent, "parameters": params, "mode": "llm",
                              "secondary_intent": None, "secondary_parameters": {}})()
        return self._dispatch_llm_intent(
            clf, prompt, _normalize(prompt), report, selected_component_id, semantic_model, contracts
        )

    def _dispatch_llm_intent(
        self,
        classification: Any,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Route an LLM IntentClassification to the appropriate handler.

        Returns None to signal the caller should fall through to keyword routing.
        """
        intent = classification.intent
        params = classification.parameters or {}

        # ------------------------------------------------------------------ #
        # Mixed-prompt: split into two proposals when LLM returns secondary_intent
        # ------------------------------------------------------------------ #
        secondary_intent = getattr(classification, "secondary_intent", None)
        if secondary_intent and secondary_intent != intent:
            secondary_params = getattr(classification, "secondary_parameters", {}) or {}
            primary_result = self._build_single_proposal(
                intent, params, prompt, report, selected_component_id, semantic_model, contracts
            )
            secondary_result = self._build_single_proposal(
                secondary_intent, secondary_params, prompt, report,
                selected_component_id, semantic_model, contracts
            )
            proposals = tuple(
                r.proposal for r in (primary_result, secondary_result)
                if r is not None and r.proposal is not None
            )
            if len(proposals) == 2:
                style_intents = {"style_change", "chart_type_change", "rename_visual"}
                if intent not in style_intents:
                    proposals = (proposals[1], proposals[0])  # style first
                notes = [
                    "Mixed prompt detected: style and analysis changes separated.",
                    "Apply them individually or together.",
                ]
                mixed_intent = AIIntent(
                    intent_kind="analysis_request",
                    target_scope=_target_scope(selected_component_id),
                    trust_notes=notes,
                    risk_level="medium",
                )
                return NL2ProposalResult(
                    intent=mixed_intent,
                    message="Mixed prompt: style and analysis proposals split. Apply each separately or together.",
                    split_proposals=proposals,
                    trust_notes=notes,
                    risk_level="medium",
                )
            elif len(proposals) == 1:
                result = primary_result if (primary_result and primary_result.proposal) else secondary_result
                return result

        # ------------------------------------------------------------------ #
        # Single intent dispatch
        # ------------------------------------------------------------------ #
        # Round 178 (S3): commonality ("are the failing wafers all on the same
        # tool?") is a high-confidence, specific ask — route it FIRST so a
        # "<80%" yield cut isn't mis-read as a count/value filter by the LLM
        # intent (which silently returned a wrong "100 wafers" answer). Falls
        # through if _answer_commonality can't handle the prompt.
        if _looks_like_commonality(prompt, normalized):
            cm = self._answer_commonality(prompt, normalized, report, contracts)
            if cm is not None:
                return cm

        if intent == "style_change":
            color_name = params.get("color", "")
            augmented = f"{prompt} {color_name}" if color_name else prompt
            return self._style_change(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "chart_type_change":
            target = params.get("target_type", "")
            augmented = f"change to {target}" if target else prompt
            return self._chart_type_change(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "dimension_change":
            granularity = params.get("granularity", "")
            augmented = f"group by {granularity}" if granularity else prompt
            return self._dimension_change(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "add_metric":
            metric_name = params.get("metric_name")
            if metric_name:
                return self._add_metric(metric_name, report, selected_component_id, semantic_model)

        if intent == "remove_metric":
            metric_name = params.get("metric_name")
            if metric_name:
                return self._remove_metric(metric_name, report, selected_component_id)

        if intent == "rename_visual":
            new_title = params.get("new_title")
            if new_title:
                augmented = f"rename this chart to \"{new_title}\""
                return self._rename_visual(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "categorical_dimension_change":
            dim_keyword = params.get("dimension_keyword", "")
            cat_dim = _CATEGORICAL_DIM_MAP.get(dim_keyword.lower()) or _extract_categorical_dimension(
                f"group by {dim_keyword}", f"group by {dim_keyword.lower()}"
            )
            if cat_dim:
                return self._categorical_dimension_change(cat_dim, report, selected_component_id, semantic_model)

        if intent == "value_filter_change":
            filter_values = params.get("filter_values")
            if filter_values:
                values_upper = [v.upper() for v in filter_values]
                col_name = "step_id"
                for v in values_upper:
                    if v.lower() in _VALUE_FILTER_MAP:
                        _, col_name = _VALUE_FILTER_MAP[v.lower()]
                        break
                return self._value_filter_change(col_name, values_upper, report, selected_component_id, semantic_model)

        if intent == "date_filter_change":
            period_raw = params.get("period", "")
            augmented = period_raw if period_raw else prompt
            return self._date_filter_change(augmented, _normalize(augmented), report)

        if intent == "panel_analysis":  # Round 086
            panel = self._run_panel_analysis(prompt, normalized, contracts)
            if panel is not None:
                return panel

        if intent == "segment_count":  # Round 091
            seg = self._answer_segment_count(prompt, normalized, report, contracts)
            if seg is not None:
                return seg

        if intent == "entity_compare":  # Round 108
            cmp = self._answer_entity_compare(prompt, normalized, report, contracts)
            if cmp is not None:
                return cmp

        if intent == "analytics_chart":  # Round 105
            ac = self._answer_analytics_chart(prompt, normalized, report, contracts)
            if ac is not None:
                return ac

        if intent == "calendar_yoy":  # Round 100
            yoy = self._answer_calendar_yoy(prompt, normalized, report, contracts)
            if yoy is not None:
                return yoy

        if intent == "insights":  # Round 097
            ins = self._answer_insights(prompt, normalized, report, contracts)
            if ins is not None:
                return ins

        if intent == "seasonality":  # Round 096
            season = self._answer_seasonality(prompt, normalized, report, contracts)
            if season is not None:
                return season

        if intent == "grouped_topn":  # Round 090
            gt = self._answer_grouped_topn(prompt, normalized, report, contracts)
            if gt is not None:
                return gt

        if intent == "ranking":  # Round 087
            ranked = self._answer_ranking(prompt, normalized, report, contracts)
            if ranked is not None:
                return ranked

        if intent == "oee":  # Round 128
            oee = self._answer_oee(prompt, normalized, report, contracts)
            if oee is not None:
                return oee

        if intent == "capacity":  # Round 128
            cap = self._answer_capacity(prompt, normalized, report, contracts)
            if cap is not None:
                return cap

        if intent == "spc":  # Round 117
            sp = self._answer_spc(prompt, normalized, report, contracts)
            if sp is not None:
                return sp

        if intent == "commonality":  # Round 117
            cm = self._answer_commonality(prompt, normalized, report, contracts)
            if cm is not None:
                return cm

        if intent == "crossfact":  # Round 116
            cf = self._answer_crossfact(prompt, normalized, report, contracts)
            if cf is not None:
                return cf

        if intent == "matrix":  # Round 118
            mx = self._answer_matrix(prompt, normalized, report, contracts)
            if mx is not None:
                return mx

        if intent == "multi_filter":  # Round 118
            mf2 = self._answer_multi_filter(prompt, normalized, report, contracts)
            if mf2 is not None:
                return mf2

        if intent == "breakdown":  # Round 114
            bd = self._answer_breakdown(prompt, normalized, report, contracts)
            if bd is not None:
                return bd

        if intent == "pacing_question":  # Round 088
            pace = self._answer_pacing(prompt, normalized, report, contracts)
            if pace is not None:
                return pace

        if intent == "explain_change":  # Round 081
            decomp = self._explain_change(prompt, normalized, report, contracts)
            if decomp is not None:
                return decomp

        if intent == "answer_metric":  # Round 078
            answer = self._answer_metric(prompt, normalized, report, semantic_model, contracts)
            if answer is not None:
                return answer

        if intent == "measure_filter":  # Round 080
            mf = self._measure_filter_change(prompt, normalized, report, selected_component_id)
            if mf is not None:
                return mf

        if intent == "queue_analysis":
            return self._queue_time_plan(prompt, report, selected_component_id, semantic_model, contracts)

        if intent == "add_visual":
            return self._add_visual_nl(params, report, semantic_model, contracts)

        if intent == "highlight_outliers":
            return self._highlight_outliers(params, report, selected_component_id)

        if intent == "add_trend_line":
            return self._add_trend_line(params, report, selected_component_id)

        if intent == "unsupported":
            # Round 095: critical reachability fix. The LLM's intent enum does not
            # include the R078-091 answer-engine intents, so a metric question
            # ("上個月營收多少？") is classified "unsupported". Rather than refuse,
            # fall through to the deterministic keyword router — which DOES handle
            # the answer engine and every edit intent. Only short-circuit with a
            # refusal when the LLM supplied a clarifying disambiguation to show.
            disam = getattr(classification, "disambiguation", None)
            if disam:
                reason = params.get("reason", "No supported governed BI intent was detected.")
                return self._unsupported(
                    reason, target_scope=_target_scope(selected_component_id),
                    disambiguation=disam,
                )
            return None  # fall through to keyword routing (answer engine + edits)

        return None  # Unknown intent → fall through to keyword routing

    # ------------------------------------------------------------------
    # Keyword-based routing (unchanged from Round 022)
    # ------------------------------------------------------------------

    def _keyword_propose(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        # Round 078: direct-answer engine. A *question* ("上個月營收多少？",
        # "how much revenue") asks for a number, not a canvas edit — answer it
        # before any edit-intent routing. Gated on explicit question markers so
        # imperative edit commands ("加一張營收圖") are never intercepted.
        # Round 086: route churn / declining-streak / basket questions to the
        # pre-built pandas analytics engines. Checked early — these are specific
        # named analyses, more specific than a plain metric question.
        # Round 136: conversational follow-up — "只看 ETCH 呢？" continues the
        # prior analysis by narrowing scope. Checked FIRST (when there is prior
        # context) so a short refinement isn't stolen by value_filter routing.
        mem = getattr(self, "_convo_mem", {})
        if isinstance(mem, dict) and mem.get("last") and \
                _looks_like_followup_scope(prompt, normalized):
            fu = self._answer_followup_scope(prompt, normalized, report, contracts)
            if fu is not None:
                return fu

        # Round 138: honest limitation — if the ask needs a capability we don't
        # have (wafer X-Y map, genealogy detail join), decline honestly and say
        # what IS possible, instead of grabbing the nearest metric (silent-wrong).
        limit_msg = _honest_limitation(prompt, normalized)
        if limit_msg is not None:
            return self._unsupported(
                limit_msg, target_scope=_target_scope(selected_component_id),
                disambiguation=limit_msg)

        if _detect_panel_analysis(prompt, normalized) is not None:
            panel = self._run_panel_analysis(prompt, normalized, contracts)
            if panel is not None:
                return panel

        # Round 097: "給我本週摘要 / 有什麼異常嗎" → digest / anomaly engines.
        if _looks_like_insights(prompt, normalized) is not None:
            ins = self._answer_insights(prompt, normalized, report, contracts)
            if ins is not None:
                return ins

        # Round 182 (S5): product-family questions, checked BEFORE the generic
        # two-entity comparison (whose regex over-captures "記憶體良率" / "邏輯差多"
        # as the entity tokens). ONE family ("邏輯良率是多少") → filter to that
        # family (before the plain-metric engine answers with the whole-fab number);
        # TWO families ("Memory 良率比 Logic 差多少") → group-prefix comparison.
        _fams = {"記憶體": "memory", "記憶": "memory", "邏輯": "logic", "類比": "analog",
                 "logic": "logic", "memory": "memory", "analog": "analog",
                 "dram": "memory", "sram": "memory"}
        _hay_fam = f"{prompt.lower()} {normalized}"
        _fam_hits = [(k, v) for k, v in _fams.items() if k in _hay_fam]
        _fam_prefixes = {v for _, v in _fam_hits}
        # Round 182 (S2): an exact entity-code value ("ETCH-02 的良率") with a single
        # code + a YIELD measure → filter to it (same engine, exact-value branch).
        # Exclude OEE/capacity/queue/what-if questions — those have dedicated
        # engines that must answer (they also name a tool but aren't yield lookups).
        _codes = set(re.findall(r"[A-Za-z]{2,}-?\d{1,3}", prompt))
        _yield_measure = any(w in _hay_fam for w in (
            "良率", "yield", "缺陷", "defect", "不良", "良品", "die",
            # Round 182 (S2): "ETCH-02 跟全廠比差多少" implies a yield comparison even
            # without the literal 良率 — bind yield so it isn't dropped to fallback.
            "跟全廠", "比全廠", "全廠平均", "整廠", "跟整廠", "vs 全廠", "對全廠"))
        _other_engine = any(w in _hay_fam for w in (
            "oee", "可用率", "稼動", "利用率", "queue", "等待", "cycle", "週期",
            "產能", "throughput", "move", "移動", "wip", "uptime", "瓶頸", "效率"))
        _whatif = any(w in _hay_fam for w in (
            "若", "假設", "如果", "提升到", "拉到", "故障", "what if", "whatif", "拉高到",
            "提升", "提高", "拉高", "個百分點"))  # Round 184 (S18): yield what-if
        # a commonality / threshold / TREND ask names a tool too, but must reach its
        # own engine — not a single-value lookup ("ETCH-01 良率逐週趨勢" is a trend,
        # "走過 ETCH-02…有沒有共同點" is commonality, "低於 80%" is a threshold cut).
        _ok_ctx = (not _other_engine and not _whatif
                   and not _looks_like_commonality(prompt, normalized)
                   and not _looks_like_trend_direction(prompt, normalized)
                   and not _is_trend_direction_question(prompt, normalized)
                   and not any(t in _hay_fam for t in (
                       "低於", "高於", "超過", "小於", "大於", "below", "<", "共同", "共通")))
        if len(_fam_prefixes) == 1 and not _codes and _ok_ctx:
            sg1 = self._answer_single_group_metric(prompt, normalized, report, contracts)
            if sg1 is not None:
                return sg1
        elif len(_codes) == 1 and len(_fam_prefixes) == 0 and _yield_measure and _ok_ctx:
            sg1 = self._answer_single_group_metric(prompt, normalized, report, contracts)
            if sg1 is not None:
                return sg1
        elif len(_fam_prefixes) >= 2:
            _reps: dict[str, str] = {}
            for _k, _v in _fam_hits:
                if _v not in _reps or len(_k) > len(_reps[_v]):
                    _reps[_v] = _k
            _two = list(_reps.values())[:2]
            gp = self._answer_group_prefix_compare(
                prompt, normalized, _two[0], _two[1], contracts)
            if gp is not None:
                return gp

        # Round 108: "比較台北和台中" → two-entity side-by-side comparison.
        if _looks_like_entity_compare(prompt, normalized):
            cmp = self._answer_entity_compare(prompt, normalized, report, contracts)
            if cmp is not None:
                return cmp

        # Round 182 (S1): an explicit direction QUESTION ("良率趨勢如何 / 有在下降
        # 嗎 / 越來越差嗎") wants a verdict (better/worse + slope + which tool is
        # declining), not just a smoothed chart — answer it BEFORE the moving-
        # average analytics chart grabs "趨勢/走勢". Falls through if no metric.
        if _is_trend_direction_question(prompt, normalized):
            td = self._answer_trend_direction(prompt, normalized, report, contracts)
            if td is not None:
                return td

        # Round 184 (S18): yield what-if ("若 ETCH-02 良率提升到 90% 全廠會怎樣") —
        # before forecast/metric so "良率…提升到…%" isn't read as a plain metric.
        _hay_yw = f"{prompt.lower()} {normalized}"
        if (("良率" in _hay_yw or "yield" in _hay_yw)
                and any(t in _hay_yw for t in ("若", "如果", "假設", "提升", "提高", "拉到", "拉高", "改善到"))
                and any(t in _hay_yw for t in ("提升到", "提高到", "拉到", "拉高到", "升到", "改善到",
                                               "增加到", "個百分點", "個%", "pp", "%"))):
            yw = self._answer_yield_whatif(prompt, normalized, report, contracts)
            if yw is not None:
                return yw

        # Round 105: Pareto/ABC, %-of-total, moving-average, forecast charts.
        if _detect_analytics_chart(f"{prompt.lower()} {normalized}") is not None:
            ac = self._answer_analytics_chart(prompt, normalized, report, contracts)
            if ac is not None:
                return ac

        # Round 134: bottleneck drift over time + WIP↔cycle-time (Little's Law).
        # Checked BEFORE capacity/metric: "瓶頸…這幾週" trips capacity, and
        # "cycle time" trips the plain metric answer — both must win here first.
        if _looks_like_bottleneck_drift(prompt, normalized):
            bd2 = self._answer_bottleneck_drift(prompt, normalized, report, contracts)
            if bd2 is not None:
                return bd2
        if _looks_like_wip_ct(prompt, normalized):
            wc = self._answer_wip_ct(prompt, normalized, report, contracts)
            if wc is not None:
                return wc

        # Round 117 / 182 (S3): commonality ("哪一站害的 / 拖累良率的元兇") is a
        # high-confidence culprit ask — checked BEFORE OEE so a "拖累良率" question
        # routes to the worst-quartile common-path analysis instead of OEE's
        # "良率(Q)" component view. Specific cues, falls through if not handled.
        if _looks_like_commonality(prompt, normalized):
            cm = self._answer_commonality(prompt, normalized, report, contracts)
            if cm is not None:
                return cm

        # Round 128: capacity / OEE analytics (move fact × capacity reference).
        if _looks_like_oee(prompt, normalized):
            oee = self._answer_oee(prompt, normalized, report, contracts)
            if oee is not None:
                return oee
        if _looks_like_capacity(prompt, normalized):
            cap = self._answer_capacity(prompt, normalized, report, contracts)
            if cap is not None:
                return cap

        # Round 117: SPC control-limit outliers. Specific cues, checked early.
        if _looks_like_spc(prompt, normalized):
            sp = self._answer_spc(prompt, normalized, report, contracts)
            if sp is not None:
                return sp

        # Round 137: subgroup comparison ("有重工的批 良率是不是比較差", "Day班 vs
        # Night班 queue time", "被hold的批 cycle time 比較長嗎"). Checked before
        # crossfact/category/metric so it isn't answered with an overall number.
        if _looks_like_subgroup_compare(prompt, normalized):
            sg = self._answer_subgroup_compare(prompt, normalized, report, contracts)
            if sg is not None:
                return sg

        # Round 138: yield excursion ("良率突然掉下來") + metric trend direction
        # ("良率這幾週變好還變差"). Before metric question so they aren't answered
        # with an overall single number (silent-wrong).
        if _looks_like_excursion(prompt, normalized):
            exc = self._answer_excursion(prompt, normalized, report, contracts)
            if exc is not None:
                return exc
        if _looks_like_trend_direction(prompt, normalized):
            td = self._answer_trend_direction(prompt, normalized, report, contracts)
            if td is not None:
                return td

        # Round 116: cross-fact analytics (correlation/cohort/ratio across two
        # facts). Checked before ranking/seasonality so "最長...有關聯" and "前 20%
        # ...良率" route to the cross-fact engine, not single-fact ranking.
        if _looks_like_crossfact(prompt, normalized):
            cf = self._answer_crossfact(prompt, normalized, report, contracts)
            if cf is not None:
                return cf

        # Round 096: "哪幾天最忙 / busiest day of week / 哪個時段" → weekday/hour
        # seasonality. Checked before ranking since it carries a date-bucket cue.
        if _looks_like_seasonality(prompt, normalized):
            season = self._answer_seasonality(prompt, normalized, report, contracts)
            if season is not None:
                return season

        # Round 090: "每個門市最暢銷的 3 個商品" → per-group Top-N. Checked before
        # plain ranking since it is the more specific (two-dimension) pattern.
        if _looks_like_grouped_topn(prompt, normalized):
            gt = self._answer_grouped_topn(prompt, normalized, report, contracts)
            if gt is not None:
                return gt

        # Round 087: "我最賺的 5 個商品" / "賣最差的品類" → ranked table. Checked
        # before the plain-answer engine; falls through if no dimension resolves.
        if _looks_like_ranking(prompt, normalized):
            ranked = self._answer_ranking(prompt, normalized, report, contracts)
            if ranked is not None:
                return ranked

        # Round 081: "why did <metric> change? decompose by <dim>" — checked
        # before the plain-answer engine so a "why" question decomposes instead
        # of returning a single total. Falls through if no dimension resolves.
        if _looks_like_explain_change(prompt, normalized):
            decomp = self._explain_change(prompt, normalized, report, contracts)
            if decomp is not None:
                return decomp

        # Round 100: calendar YoY ("本月 vs 去年同月") — checked before the plain
        # answer engine so '去年同期' uses calendar boundaries, not a trailing year.
        if _looks_like_calendar_yoy(prompt, normalized):
            yoy = self._answer_calendar_yoy(prompt, normalized, report, contracts)
            if yoy is not None:
                return yoy

        # Round 118: 2-D cross-tab ("各 X 在不同 Y 上的 Z") + multi-condition filter.
        if _looks_like_matrix(prompt, normalized):
            mx = self._answer_matrix(prompt, normalized, report, contracts)
            if mx is not None:
                return mx
        if _looks_like_multi_filter(prompt, normalized):
            mf2 = self._answer_multi_filter(prompt, normalized, report, contracts)
            if mf2 is not None:
                return mf2

        # Round 121: cold-start grouped measure filter ("queue > 5 小時的 lot")
        # — checked BEFORE the plain-answer engine, since '哪些…？' phrasing also
        # trips the question marker but wants a list, not a single total.
        if _looks_like_segment_count(prompt, normalized):
            seg = self._answer_segment_count(prompt, normalized, report, contracts)
            if seg is not None:
                return seg

        # Round 114: plain "metric by dimension" breakdown ("各製程站的移動次數").
        # After ranking/decompose (so superlatives/why still win), before the
        # generic single-number answer.
        if _looks_like_breakdown(prompt, normalized):
            bd = self._answer_breakdown(prompt, normalized, report, contracts)
            if bd is not None:
                return bd

        # Round 129: compare a metric across a fab category (重工 vs 非重工,
        # Hot vs 一般) when the category values aren't both literally named — after
        # breakdown (so "各班別…" plain breakdowns still win), before the scalar answer.
        if _looks_like_category_compare(prompt, normalized):
            cc = self._answer_category_compare(prompt, normalized, report, contracts)
            if cc is not None:
                return cc

        if _looks_like_metric_question(prompt, normalized):
            answer = self._answer_metric(prompt, normalized, report, semantic_model, contracts)
            if answer is not None:
                return answer

        # Round 088: "達標了嗎 / are we on track?" — read back KPI pacing. Checked
        # before set-target (a question, not a set command).
        if _looks_like_pacing_question(prompt, normalized):
            pace = self._answer_pacing(prompt, normalized, report, contracts)
            if pace is not None:
                return pace

        # Round 084: set a KPI goal/target. "把營收目標設為 100 萬". Checked before
        # measure-filter since "目標" + a number is goal-setting, not a HAVING.
        if _looks_like_set_target(prompt, normalized):
            st_res = self._set_target(prompt, normalized, report, selected_component_id)
            if st_res is not None:
                return st_res

        # Round 091: cold-start grouped measure filter — "買超過 3 次的客戶" builds
        # the entity×count grouped HAVING query from scratch (no existing visual
        # needed). Checked before the on-visual measure filter.
        if _looks_like_segment_count(prompt, normalized):
            seg = self._answer_segment_count(prompt, normalized, report, contracts)
            if seg is not None:
                return seg

        # Round 080: measure (post-aggregate) filter → HAVING. "把營收超過 500 的列出",
        # edits an *existing* grouped visual's HAVING. Carries a comparison + number
        # against a projected metric.
        if _looks_like_measure_filter(prompt, normalized):
            mf = self._measure_filter_change(prompt, normalized, report, selected_component_id)
            if mf is not None:
                return mf

        # Round 066: "add a trend line / 趨勢線" overlay (keyword mode). Checked
        # before add_visual since it is a more specific phrase.
        if _looks_like_add_trend_line(prompt, normalized):
            return self._add_trend_line({}, report, selected_component_id)

        # Round 065: "add a pie/bar/line chart" creates a NEW visual (keyword mode).
        # Checked before chart_type_change; the add-verb vs change-verb split keeps
        # them disjoint.
        if _looks_like_add_visual(prompt, normalized):
            return self._add_visual_keyword(
                prompt, normalized, report, selected_component_id, semantic_model, contracts
            )

        # Chart-type change is checked before style: both include "bar"/"line" keywords,
        # but chart-type requires a change verb + chart noun (more specific pattern).
        if _looks_like_chart_type_change(prompt, normalized):
            return self._chart_type_change(prompt, normalized, report, selected_component_id)

        if _looks_like_style_request(prompt, normalized):
            return self._style_change(prompt, normalized, report, selected_component_id)

        if _looks_like_dimension_change(prompt, normalized):
            return self._dimension_change(prompt, normalized, report, selected_component_id)

        add_metric_name = _extract_add_metric_name(prompt, normalized)
        if add_metric_name is not None:
            return self._add_metric(add_metric_name, report, selected_component_id, semantic_model)

        if _looks_like_date_filter(prompt, normalized):
            return self._date_filter_change(prompt, normalized, report)

        # Rename must be checked first — "rename this chart to Queue Trend" contains
        # "queue" + "trend" which would otherwise trigger queue_analysis.
        if _looks_like_rename_visual(prompt, normalized):
            return self._rename_visual(prompt, normalized, report, selected_component_id)

        # Queue analysis must be checked BEFORE categorical/value-filter to avoid
        # "analyze queue time drivers by tool" being intercepted by _CAT_DIM_TRIGGERS.
        if _looks_like_queue_analysis(normalized):
            return self._queue_time_plan(prompt, report, selected_component_id, semantic_model, contracts)

        remove_metric_name = _extract_remove_metric_name(prompt, normalized)
        if remove_metric_name is not None:
            return self._remove_metric(remove_metric_name, report, selected_component_id)

        # Round 035: pass contracts for dynamic schema fallback
        cat_dim = _extract_categorical_dimension(prompt, normalized, contracts)
        if cat_dim is not None:
            return self._categorical_dimension_change(cat_dim, report, selected_component_id, semantic_model)

        value_filter = _extract_value_filter(prompt, normalized)
        if value_filter is not None:
            col_name, values = value_filter
            return self._value_filter_change(col_name, values, report, selected_component_id, semantic_model)

        # Round 036: period-over-period comparison
        if _looks_like_period_comparison(prompt, normalized):
            return self._period_comparison(prompt, normalized, report, selected_component_id, contracts)

        # Round 135: nothing routed. Before giving up, if the prompt is a vague
        # evaluative question ("效率怎麼樣"), ASK a clarifying question rather than
        # silently guessing or flatly rejecting — silent-wrong destroys trust.
        clarify = _ambiguous_clarification(prompt, normalized)
        if clarify is not None:
            return self._unsupported(
                clarify,
                target_scope=_target_scope(selected_component_id),
                disambiguation=clarify,
            )

        return self._unsupported(
            "我看不太懂這個問法，沒有對應到支援的分析動作或問題。請換句話、說得更具體一點，"
            "例如：「依機台比較平均等待時間」「哪台機台等待時間最長」「最近的等待時間趨勢」；"
            "或展開下方「💡 你可以這樣問」看可用範例。",
            target_scope=_target_scope(selected_component_id),
        )

    def _style_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a line or bar chart before changing chart style.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found
        visual_type = visual.visualization.visual_type
        color = _extract_color(prompt, normalized)
        if color is None:
            return self._unsupported(
                "Specify a supported chart color such as red, blue, green, orange, purple, gray, or black.",
                target_scope=f"visual:{visual_id}",
            )

        selection = _selection_from_visual(visual)
        if visual_type == VisualType.line_chart:
            style_key = "line_color"
            label = "Line color"
        elif visual_type == VisualType.bar_chart:
            style_key = "bar_color"
            label = "Bar color"
        else:
            return self._unsupported(
                f"Style color changes are supported for line and bar charts, not {visual_type.value}.",
                target_scope=f"visual:{visual_id}",
                selection=selection,
            )

        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/{style_key}"
        before = visual.visualization.extra.get(style_key)
        notes = [
            f"Grounded to selected {visual_type.value} visual '{visual_id}'.",
            "Proposal changes visualization metadata only; query semantics are unchanged.",
        ]
        proposal = None
        if before != color:
            proposal = ReportProposal(
                description=f"Change {label.lower()} to {color}",
                changes=[
                    ReportChange(
                        path=path,
                        label=label,
                        before=before,
                        after=color,
                        affects_data=False,
                    )
                ],
                target_component_id=visual_id,
            )
        intent = AIIntent(
            intent_kind="style_change",
            target_scope=f"visual:{visual_id}",
            selection=selection,
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="low",
        )
        message = (
            "Style proposal created. Review the diff before applying it."
            if proposal
            else "The selected chart already uses that color."
        )
        return NL2ProposalResult(
            intent=intent,
            message=message,
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    # ------------------------------------------------------------------
    # Round 036: period_comparison — create two KPI cards for current vs prev period
    # ------------------------------------------------------------------

    def _add_visual_keyword(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        """Round 065: add a new chart of the requested type (keyword mode).

        Picks a sensible metric (from the selected/first visual) and dimension
        (date for line, a low-cardinality category for bar/pie) so it works even
        when the user only says "add a pie chart".
        """
        from ai4bi.report.builder import build_add_visual_proposal
        from ai4bi.query_spec import (
            BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec, VisualizationSpec,
        )

        vtype = VisualType.bar_chart
        for kw, vt in _ADD_VISUAL_TYPE_KEYWORDS.items():
            if kw in normalized or kw in prompt:
                vtype = vt
                break

        # Source metric + block: prefer the selected visual, else the first visual
        # in the report that has a metric.
        found = _find_visual(report, selected_component_id)
        page_id, metric, block_id = "main", None, None
        if found and found[2].query.metrics:
            page_id, _vid, v = found
            metric, block_id = v.query.metrics[0], v.query.metrics[0].block_id
        else:
            for pid, page in report.pages.items():
                for v in page.visuals.values():
                    if v.query.metrics:
                        page_id, metric, block_id = pid, v.query.metrics[0], v.query.metrics[0].block_id
                        break
                if metric:
                    break
        if metric is None or block_id is None:
            return self._unsupported("找不到可用的指標來建立圖表。", target_scope="canvas")

        metric_alias = metric.alias or metric.metric_name

        # Pick dimensions from the block's contract.
        date_col, cat_cols = None, []
        contract = (contracts or {}).get(block_id)
        if contract is not None:
            pk = set(getattr(contract, "primary_keys", []) or [])
            for col in contract.columns:
                nm, dt = col.name, col.data_type
                low = nm.lower()
                if date_col is None and (dt in ("date", "timestamp")
                                         or any(t in low for t in ("date", "time", "_dt", "day"))):
                    date_col = nm
                if (dt in ("string", "str", "object") and nm not in pk
                        and not (low == "id" or low.endswith(("_id", "_code", "_sku")))
                        and len(cat_cols) < 2):
                    cat_cols.append(nm)
        cat_col = cat_cols[0] if cat_cols else None

        dimensions, sort = [], []
        truncate = None
        if vtype == VisualType.map:
            # Round 089: a map needs a *location* dimension — prefer a geo column
            # (city / 縣市 / region / store) over an arbitrary categorical.
            loc_col = _find_location_col(contract) or cat_col
            if loc_col:
                dimensions = [DimensionRef(block_id, loc_col, loc_col)]
                sort = [SortSpec(metric_alias, SortDirection.desc)]
        elif vtype == VisualType.small_multiples:
            # Round 094: facet by a category, x-axis over time → one mini trend
            # per category. Falls back to a single facet dimension if no date.
            if cat_col and date_col:
                dimensions = [DimensionRef(block_id, cat_col, cat_col),
                              DimensionRef(block_id, date_col, date_col, truncate_date_to="week")]
                sort = [SortSpec(date_col, SortDirection.asc)]
            elif cat_col:
                dimensions = [DimensionRef(block_id, cat_col, cat_col)]
                sort = [SortSpec(metric_alias, SortDirection.desc)]
        elif vtype == VisualType.pivot and len(cat_cols) >= 2:
            dimensions = [DimensionRef(block_id, cat_cols[0], cat_cols[0]),
                          DimensionRef(block_id, cat_cols[1], cat_cols[1])]
        elif vtype == VisualType.kpi_card:
            pass  # no dimension
        elif vtype == VisualType.line_chart and date_col:
            dimensions = [DimensionRef(block_id, date_col, date_col, truncate_date_to="week")]
            sort = [SortSpec(date_col, SortDirection.asc)]
            truncate = "week"
        elif cat_col:
            dimensions = [DimensionRef(block_id, cat_col, cat_col)]
            sort = [SortSpec(metric_alias, SortDirection.desc)]
        elif date_col:  # fall back to date if no categorical column
            dimensions = [DimensionRef(block_id, date_col, date_col)]

        # Unique visual id
        base_vid = f"{vtype.value}_{metric.metric_name}"
        existing = {vid for p in report.pages.values() for vid in p.visuals}
        vid, c = base_vid, 1
        while vid in existing:
            vid = f"{base_vid}_{c}"; c += 1

        query = VisualQuerySpec(
            spec_id=vid,
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric.metric_name, metric_alias)],
            dimensions=dimensions,
            sort=sort,
            inherit_global_filter=True,
        )
        _type_label = {
            VisualType.pie_chart: "圓餅圖", VisualType.bar_chart: "長條圖",
            VisualType.line_chart: "折線圖", VisualType.scatter: "散點圖",
            VisualType.kpi_card: "KPI", VisualType.table: "表格",
            VisualType.pivot: "樞紐表", VisualType.map: "地圖",
            VisualType.small_multiples: "小倍數圖",
        }.get(vtype, vtype.value)
        viz = VisualizationSpec(vtype, title=f"{metric_alias}（{_type_label}）", extra={})
        proposal = build_add_visual_proposal(page_id, vid, query, viz)

        notes = [
            f"新增一個{_type_label}，指標：{metric_alias}（來源：{block_id}）。",
        ]
        if dimensions:
            notes.append(f"維度：{dimensions[0].column_name}" + ("（依週彙總）" if truncate else ""))
        intent = AIIntent(
            intent_kind="add_visual",
            target_scope=f"page:{page_id}",
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已準備新增一個{_type_label}：{metric_alias}。",
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    def _period_comparison(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        """Add two side-by-side KPI cards: current period vs previous period."""
        from ai4bi.report.builder import build_add_visual_proposal
        from ai4bi.query_spec import BlockRef, FilterOperator, FilterSpec, VisualQuerySpec, VisualizationSpec
        from ai4bi.report.models import ReportVisualSpec
        import datetime

        period, period_label, prev_label = _extract_comparison_period(normalized, prompt)

        # Find the primary fact block and first SUM metric from the current visual or report
        found = _find_visual(report, selected_component_id)
        if found is None:
            # Use first visual in report
            for page in report.pages.values():
                for vid, v in page.visuals.items():
                    if v.query.metrics:
                        found = (list(report.pages.keys())[0], vid, v)
                        break
                if found:
                    break
        if found is None:
            return self._unsupported("找不到可以用於比較的圖表，請先選擇一個圖表。", target_scope="canvas")

        page_id, _vid, visual = found
        if not visual.query.metrics:
            return self._unsupported("所選圖表沒有指標，無法建立比較。", target_scope=f"visual:{_vid}")

        metric = visual.query.metrics[0]
        fact_block = metric.block_id
        today = datetime.date.today()

        if period == "week":
            start_curr = today - datetime.timedelta(days=today.weekday())
            start_prev = start_curr - datetime.timedelta(weeks=1)
            end_prev = start_curr - datetime.timedelta(days=1)
        elif period == "month":
            start_curr = today.replace(day=1)
            prev_month = (start_curr - datetime.timedelta(days=1)).replace(day=1)
            start_prev = prev_month
            end_prev = start_curr - datetime.timedelta(days=1)
        else:  # default: last 7 days vs prev 7 days
            start_curr = today - datetime.timedelta(days=6)
            start_prev = start_curr - datetime.timedelta(days=7)
            end_prev = start_curr - datetime.timedelta(days=1)

        # Find the date column in the fact block
        date_col = None
        if contracts and fact_block in contracts:
            for col in contracts[fact_block].columns:
                if col.data_type in ("date", "timestamp") or any(
                    t in col.name.lower() for t in ("date", "time", "dt", "ts", "day")
                ):
                    date_col = col.name
                    break

        existing = set(report.pages.get("main", type("_", (), {"visuals": {}})()).visuals.keys())
        proposals = []
        for label, start, end in [
            (period_label, start_curr, today),
            (prev_label, start_prev, end_prev),
        ]:
            vid = f"kpi_cmp_{metric.metric_name}_{label.replace(' ', '_')}"
            c = 1
            while vid in existing:
                vid = f"kpi_cmp_{metric.metric_name}_{label.replace(' ', '_')}_{c}"; c += 1
            existing.add(vid)

            filters = []
            if date_col:
                filters = [
                    FilterSpec(fact_block, date_col, FilterOperator.gte, str(start), False),
                    FilterSpec(fact_block, date_col, FilterOperator.lte, str(end), False),
                ]

            q = VisualQuerySpec(
                spec_id=vid,
                block_refs=[BlockRef(fact_block)],
                metrics=[MetricRef(fact_block, metric.metric_name, f"{metric.alias or metric.metric_name}")],
                filters=filters,
                inherit_global_filter=False,
            )
            v = VisualizationSpec(VisualType.kpi_card, title=f"{label}", extra={})
            rv = ReportVisualSpec(vid, q, v, col_span=6)
            proposals.append(build_add_visual_proposal(page_id, vid, q, v))

        from dataclasses import replace as _replace
        # Apply both proposals
        notes = [
            f"建立兩個 KPI 看板比較 {period_label} vs {prev_label}。",
            f"指標：{metric.alias or metric.metric_name}（來源：{fact_block}）",
            "日期過濾器已嵌入各 KPI 看板，不影響其他圖表。",
        ]

        # Merge two proposals into one by combining their changes
        all_changes = proposals[0].changes + proposals[1].changes
        merged = ReportProposal(
            description=f"Period comparison: {period_label} vs {prev_label}",
            changes=all_changes,
        )

        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=f"page:{page_id}",
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已建立 {period_label} vs {prev_label} 的比較 KPI。",
            proposal=merged,
            trust_notes=notes,
            risk_level="low",
        )

    def _answer_entity_compare(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 108: "比較台北和台中" / "Taipei vs Taichung" — two-entity compare.

        Resolves two dimension *values*, finds the categorical column holding
        both, and compares a metric between them. Returns None (declines) when
        the operands or column can't be resolved — never guesses.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        ops = _extract_compare_operands(prompt, normalized)
        if ops is None:
            return None
        a, b = ops

        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe

        # Find fact blocks + categorical columns whose values include both operands.
        candidates: list[tuple[str, str]] = []
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            for col in [cc.name for cc in c.columns
                        if cc.data_type in ("string", "str", "object")]:
                vals = set(df[col].astype(str).unique()) if col in df.columns else set()
                if a in vals and b in vals:
                    candidates.append((bid, col))
                    break
        if not candidates:
            # Round 178 (S5): operands may name value GROUPS by prefix
            # (memory → Memory-X/Memory-Y, logic → Logic-A/Logic-B) — compare the
            # two groups directly ("memory 比 logic 差嗎").
            return self._answer_group_prefix_compare(prompt, normalized, a, b, contracts)

        # Round 178 (S2): the same entities can live in multiple facts (tool_id in
        # process-move AND etch_tool_id in wafer-yield). Prefer the block holding
        # the metric the prompt actually asked for, so "兩台機台的良率" compares
        # yield — not move_count from whichever fact happened to be first.
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is not None:
            _pref = next(((b, cc) for (b, cc) in candidates if b == match.block_id), None)
            block_id, col = _pref if _pref is not None else candidates[0]
        else:
            block_id, col = candidates[0]
        if match is not None and match.block_id == block_id:
            metric_name, alias = match.metric_name, match.alias
        else:
            # Round 124: the global best metric may be on another block; prefer the
            # best metric ON the comparison column's block before defaulting.
            on_block = _best_metric_on_block(idx, prompt, normalized, block_id)
            if on_block is not None:
                metric_name, alias = on_block
            else:
                dm = _default_count_metric(contracts, block_id)
                if dm is None:
                    return None
                metric_name, alias = dm

        from ai4bi.query_spec import (
            BlockRef, DimensionRef, FilterOperator, FilterSpec, VisualQuerySpec,
        )
        # Round 119: apply any OTHER categorical value named in the prompt as a
        # scope filter — "ETCH 區的 Hot vs Normal" compares within area=ETCH.
        filters = [FilterSpec(block_id, col, FilterOperator.in_, [a, b], False)]
        hay = f"{prompt} {normalized}"
        from ai4bi.blocks.datastore import materialize_dataframe
        try:
            mdf = materialize_dataframe(contracts[block_id])
        except Exception:  # noqa: BLE001
            mdf = None
        if mdf is not None:
            for ccol in [cc.name for cc in contracts[block_id].columns
                         if cc.data_type in ("string", "str", "object") and cc.name != col]:
                if ccol not in mdf.columns:
                    continue
                for v in {str(x) for x in mdf[ccol].dropna().unique()}:
                    if v and v not in (a, b) and v.lower() in hay.lower():
                        filters.append(FilterSpec(block_id, ccol, FilterOperator.eq, v, False))
                        break
        spec = VisualQuerySpec(
            spec_id=f"cmp_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, col, col)],
            filters=filters,
            inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or col not in df.columns or alias not in df.columns:
            return None

        vals = {str(r[col]): float(r[alias]) for _, r in df.iterrows()}
        va, vb = vals.get(a), vals.get(b)
        unit = _metric_unit(contracts, block_id, metric_name)
        if va is not None and vb is not None:
            hi, lo = (a, b) if va >= vb else (b, a)
            hv, lv = (va, vb) if va >= vb else (vb, va)
            # Round 178 (S2): for a PERCENTAGE metric (yield %) the gap is percentage
            # POINTS — report "高 8.8 個百分點", not the misleading relative "多 10.5%".
            # Round 184 (S14): only when the unit is "%" — a time average (hr/min) is
            # a ratio (don't-sum) but NOT a percentage, so show the absolute diff.
            _is_ratio_metric = _metric_is_ratio(contracts, block_id, metric_name)
            if _is_ratio_metric and unit == "%":
                gap = f"，{hi} 高 {abs(hv - lv):.1f} 個百分點。"
            elif _is_ratio_metric:
                gap = f"，{hi} 高 {abs(hv - lv):.2f}{unit}。"
            else:
                diff_pct = ((hv - lv) / abs(lv) * 100) if lv else None
                gap = (f"，{hi} 較高，多 {diff_pct:.1f}%。" if diff_pct is not None else f"，{hi} 較高。")
            sentence = (f"{a} {alias} {_format_metric_value(va, unit)}　vs　"
                        f"{b} {_format_metric_value(vb, unit)}。{gap.lstrip('，')}")
        else:
            sentence = f"比較 {a} 與 {b} 的 {alias}。"
        notes = [f"比較「{col}」中 {a} 與 {b} 的「{alias}」（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_group_prefix_compare(self, prompt, normalized, a, b, contracts):
        """Round 178 (S5): compare two value-PREFIX groups, e.g. "memory 比 logic
        差嗎" where memory→Memory-*, logic→Logic-*. Weighted for yield ratios,
        mean otherwise. Returns None if there's no clean prefix grouping."""
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        # Round 178 (S5): map Chinese / abbreviated product-family names to the
        # value prefixes used in the data (記憶體→memory, 邏輯→logic, DRAM→memory…).
        _ALIAS = {"記憶體": "memory", "記憶": "memory", "邏輯": "logic", "類比": "analog",
                  "dram": "memory", "sram": "memory", "cpu": "logic", "mem": "memory",
                  "記憶體類": "memory", "邏輯類": "logic"}

        def _alias(x: str) -> str:
            xl = x.strip().lower()
            if xl in _ALIAS:
                return _ALIAS[xl]
            # tolerate the regex over-capturing a measure ("邏輯良率" → logic):
            # if a known group token is a substring, use it.
            for k, v in _ALIAS.items():
                if k in xl:
                    return v
            return xl

        al, bl = _alias(a), _alias(b)
        if len(al) < 2 or len(bl) < 2 or not contracts:
            return None
        hay = f"{prompt.lower()} {normalized}"
        is_yield_q = ("良率" in hay or "yield" in hay)
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            for col in [cc.name for cc in c.columns if cc.data_type in ("string", "str", "object")]:
                if col not in df.columns:
                    continue
                low = df[col].astype(str).str.lower()
                # Round 182 (S5): if the prompt names EXACT sub-family values
                # ("Memory-Y 跟 Logic-A"), compare those values, not the parent
                # prefixes (hyphen/space-insensitive). Else fall back to prefixes.
                _hay_norm = hay.replace("-", "").replace(" ", "")
                _exact: list[str] = []
                for _v in df[col].dropna().astype(str).unique():
                    _vn = _v.lower().replace("-", "").replace(" ", "")
                    if len(_vn) >= 4 and _vn in _hay_norm and _v not in _exact:
                        _exact.append(_v)
                if len(_exact) >= 2:
                    a_disp, b_disp = _exact[0], _exact[1]
                    ga = df[col].astype(str) == a_disp
                    gb = df[col].astype(str) == b_disp
                else:
                    a_disp, b_disp = a, b
                    ga, gb = low.str.startswith(al), low.str.startswith(bl)
                if not (ga.any() and gb.any()) or (ga & gb).any():
                    continue  # need two disjoint, non-empty groups
                cols = set(df.columns)
                mcol = _resolve_numeric_column(prompt, normalized, c)
                # Default to weighted yield when no explicit measure is named — in a
                # fab "A 比 B 差/好" about products almost always means yield.
                if (is_yield_q or not mcol) and {"good_die", "tested_die"} <= cols:
                    va = df.loc[ga, "good_die"].sum() / max(df.loc[ga, "tested_die"].sum(), 1) * 100.0
                    vb = df.loc[gb, "good_die"].sum() / max(df.loc[gb, "tested_die"].sum(), 1) * 100.0
                    alias, pp = "良率（加權）", True
                elif mcol and mcol in df.columns:
                    va, vb = float(df.loc[ga, mcol].mean()), float(df.loc[gb, mcol].mean())
                    alias, pp = mcol, False
                else:
                    continue
                hi, hv, lv = (a_disp, va, vb) if va >= vb else (b_disp, vb, va)
                _u = "%" if pp else ""
                gap = (f"{hi} 高 {abs(va - vb):.1f} 個百分點" if pp
                       else f"{hi} 較高（{max(va, vb):.2f} vs {min(va, vb):.2f}）")
                sentence = (f"比較「{a_disp}」與「{b_disp}」的{alias}：{a_disp} {va:.2f}{_u}　vs　"
                            f"{b_disp} {vb:.2f}{_u}。{gap}。")
                notes = [f"以「{col}」比較（{a_disp}/{b_disp}）{alias}，來源：{bid}。"]
                intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                  trust_notes=notes, risk_level="low")
                return NL2ProposalResult(intent=intent, message=sentence,
                                         trust_notes=notes, risk_level="low")
        return None

    def _answer_single_group_metric(self, prompt, normalized, report, contracts):
        """Round 182 (S5): a metric for ONE value-prefix group — "邏輯良率是多少 /
        memory 的良率 / logic 良率". Filters the fact to that product family and
        reports its value with the overall for context (instead of answering with
        the whole-fab number, which was silently wrong). None if no single group /
        measure resolves, or if TWO groups are named (that's a comparison)."""
        if not contracts:
            return None
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        _ALIAS = {"記憶體": "memory", "記憶": "memory", "邏輯": "logic", "類比": "analog",
                  "dram": "memory", "sram": "memory", "cpu": "logic", "mem": "memory",
                  "記憶體類": "memory", "邏輯類": "logic", "logic": "logic",
                  "memory": "memory", "analog": "analog"}
        hay = f"{prompt.lower()} {normalized}"
        prefixes = {v for k, v in _ALIAS.items() if k in hay}
        if len(prefixes) >= 2:
            return None  # 2+ families → a comparison (handled elsewhere)
        pref = next(iter(prefixes)) if prefixes else None
        # Round 182 (S2): also support an EXACT named value with no family alias
        # ("ETCH-02 的良率" → filter etch_tool_id=ETCH-02). Detected per-column below;
        # if neither a prefix nor an exact value resolves, bail.
        # need a measure context — a yield/metric word, else this isn't a "how much" ask
        is_yield_q = ("良率" in hay or "yield" in hay)
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            cols = set(df.columns)
            for col in [cc.name for cc in c.columns if cc.data_type in ("string", "str", "object")]:
                if col not in df.columns:
                    continue
                low = df[col].astype(str).str.lower()
                # Round 182 (S5/S2): if the prompt names an EXACT value ("Memory-Y
                # 的良率", "ETCH-02 的良率"), filter to it rather than the broad prefix
                # group. Match hyphen/space-insensitively so "ETCH02" finds "ETCH-02".
                _hay_norm = hay.replace("-", "").replace(" ", "")
                exact = None
                for _v in df[col].dropna().astype(str).unique():
                    _vl = _v.lower()
                    _vn = _vl.replace("-", "").replace(" ", "")
                    if len(_vn) >= 3 and _vn in _hay_norm and (
                            exact is None or len(_vn) > len(exact[1])):
                        exact = (_v, _vn)
                if exact is not None:
                    grp = df[col].astype(str) == exact[0]
                    disp_exact = exact[0]
                elif pref is not None:
                    grp = low.str.startswith(pref)
                    disp_exact = None
                else:
                    continue  # no prefix and no exact value on this column
                if not grp.any() or grp.all():
                    continue  # need a proper non-trivial subset
                if (is_yield_q or True) and {"good_die", "tested_die"} <= cols:
                    gv = df.loc[grp, "good_die"].sum() / max(df.loc[grp, "tested_die"].sum(), 1) * 100.0
                    ov = df["good_die"].sum() / max(df["tested_die"].sum(), 1) * 100.0
                    label, pp = "良率（加權）", True
                else:
                    mcol = _resolve_numeric_column(prompt, normalized, c)
                    if not mcol or mcol not in df.columns:
                        continue
                    gv, ov = float(df.loc[grp, mcol].mean()), float(df[mcol].mean())
                    label, pp = mcol, False
                u = "%" if pp else ""
                delta = gv - ov
                cmp_word = "高" if delta >= 0 else "低"
                tail = (f"（全廠 {ov:.2f}{u}，{cmp_word} {abs(delta):.1f} "
                        f"{'個百分點' if pp else ''}）") if pp else \
                       f"（全廠 {ov:.2f}{u}）"
                # show the matched family label in the user's own wording (prefer
                # the longest matching token so "memory" wins over "mem"); an exact
                # sub-family value is shown verbatim.
                disp = disp_exact or max(
                    (k for k in _ALIAS if k in hay and _ALIAS[k] == pref),
                    key=len, default=pref)
                sentence = f"「{disp}」的{label}為 {gv:.2f}{u}{tail}。"
                _filt = (f"{col} = {disp_exact}" if disp_exact else f"{col} 前綴 = {pref}")
                notes = [f"以「{_filt}」過濾後計算{label}，來源：{bid}。"]
                intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                  trust_notes=notes, risk_level="low")
                return NL2ProposalResult(intent=intent, message=sentence,
                                         trust_notes=notes, risk_level="low")
        return None

    def _answer_analytics_chart(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 105: NL on-ramp for the postprocess / forecast engines.

        Pareto/ABC, %-of-total, moving-average and forecast were render-wired but
        only reachable from the canned demo. This builds a new visual with the
        right extra config so the ask box can request them. Returns None to fall
        through.
        """
        if not contracts:
            return None
        kind = _detect_analytics_chart(f"{prompt.lower()} {normalized}")
        if kind is None:
            return None
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias

        # Round 178 (S4): a Pareto is the cumulative share of a COUNT/quantity, so
        # lock onto an additive metric — a "%" or "累積" in the prompt must not make
        # us build the Pareto on a ratio column (e.g. defect_density_pct).
        if kind == "pareto" and _metric_is_ratio(contracts, block_id, metric_name):
            _c = (contracts or {}).get(block_id)
            # leading token, e.g. defect_density_pct → "defect", to find the
            # matching count metric (defect_die) rather than just any sum metric.
            _stem = metric_name.lower().split("_")[0]
            _sum_metrics = [m for m in getattr(_c, "metrics", [])
                            if getattr(getattr(m, "disaggregation_method", None), "value", None) == "sum"]
            _alt = next((m for m in _sum_metrics if _stem and m.name.lower().startswith(_stem)), None)
            _alt = _alt or (_sum_metrics[0] if _sum_metrics else None)
            if _alt is not None:
                metric_name, alias = _alt.name, _alt.name

        from ai4bi.report.builder import build_add_visual_proposal
        from ai4bi.query_spec import (
            BlockRef, DimensionRef, SortDirection, SortSpec, VisualizationSpec, VisualQuerySpec,
        )

        page_id = "main" if "main" in report.pages else next(iter(report.pages), None)
        if page_id is None:
            return None
        existing = {vid for p in report.pages.values() for vid in p.visuals}

        n = _extract_analytics_n(prompt, normalized)
        if kind in ("pareto", "share"):
            dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
            if dim_col is None:
                return None
            vid = _unique_id(f"{kind}_{metric_name}", existing)
            q = VisualQuerySpec(vid, [BlockRef(block_id)],
                                metrics=[MetricRef(block_id, metric_name, alias)],
                                dimensions=[DimensionRef(block_id, dim_col, dim_col)],
                                sort=[SortSpec(alias, SortDirection.desc)],
                                inherit_global_filter=False)
            mode = "pareto" if kind == "pareto" else "share_of_total"
            title = (f"{alias} Pareto/ABC（依{dim_col}）" if kind == "pareto"
                     else f"{alias} 佔比（依{dim_col}）")
            viz = VisualizationSpec(VisualType.bar_chart, title=title,
                                    extra={"postprocess": mode, "data_labels": True})
            msg = f"已準備{('Pareto/ABC' if kind=='pareto' else '佔比')}分析：{alias} 依 {dim_col}。"
            # Round 135: "最近有沒有哪一類在惡化" — Pareto answers the static ranking;
            # add a recent-vs-earlier trend so a worsening category is named.
            worsen_cue = any(t in f"{prompt.lower()} {normalized}" for t in (
                "惡化", "變多", "變嚴重", "上升", "增加", "最近", "趨勢", "worsen",
                "worse", "rising", "increas", "trend", "近期", "走高"))
            if kind == "pareto" and worsen_cue:
                trend_msg, trend_tbl = self._pareto_trend(contracts, block_id, metric_name, dim_col)
                if trend_msg:
                    notes_trend = trend_msg
                    intent = AIIntent(intent_kind="analysis_request",
                                      target_scope=f"page:{page_id}",
                                      trust_notes=[trend_msg], risk_level="low")
                    return NL2ProposalResult(
                        intent=intent,
                        message=f"{msg} {trend_msg}",
                        result_table=trend_tbl,
                        proposal=build_add_visual_proposal(page_id, vid, q, viz),
                        trust_notes=[trend_msg], risk_level="low")
        else:  # moving_avg or forecast → time series
            date_col = _find_date_column(contracts, block_id)
            if date_col is None:
                return None
            vid = _unique_id(f"{kind}_{metric_name}", existing)
            q = VisualQuerySpec(vid, [BlockRef(block_id)],
                                metrics=[MetricRef(block_id, metric_name, alias)],
                                dimensions=[DimensionRef(block_id, date_col, date_col,
                                                         truncate_date_to="week")],
                                sort=[SortSpec(date_col, SortDirection.asc)],
                                inherit_global_filter=False)
            if kind == "moving_avg":
                extra = {"postprocess": "moving_avg", "postprocess_window": n or 4}
                title = f"{alias} 趨勢 + {n or 4} 期移動平均"
                msg = f"{alias} 的 {n or 4} 期移動平均平滑趨勢（下表為各期值）。"
            else:  # forecast
                extra = {"trend_line": {"method": "linear", "forecast_periods": n or 1}}
                title = f"{alias} 趨勢 + 未來 {n or 1} 期預測"
                msg = f"已準備 {alias} 的趨勢預測（外推 {n or 1} 期）。"
            viz = VisualizationSpec(VisualType.line_chart, title=title, extra=extra)

        proposal = build_add_visual_proposal(page_id, vid, q, viz)
        notes = [msg, f"指標：{alias}（{metric_name} @ {block_id}）；套用後重新查詢。"]
        # Round 126: also compute the result INLINE (executor + postprocess) so a
        # '走勢/移動平均/Pareto' question gets a direct table, not only a chart to
        # apply.
        executor = getattr(self, "_executor", None)
        inline = None
        if executor is not None and kind in ("pareto", "share", "moving_avg"):
            try:
                from ai4bi.analysis.postprocess import apply_postprocess
                df = executor.run(q)
                if df is not None and not df.empty:
                    inline = apply_postprocess(df, q, viz)
            except Exception:  # noqa: BLE001
                inline = None
        # Round 142: forecast — also give a PROJECTED NUMBER inline (linear
        # extrapolation), so "下個月良率大概多少" gets a value, not just a chart.
        if executor is not None and kind == "forecast":
            try:
                import numpy as _np
                df = executor.run(q)
                if df is not None and len(df) >= 3 and alias in df.columns:
                    ys = df[alias].astype(float).to_numpy()
                    xs = _np.arange(len(ys))
                    a, b = _np.polyfit(xs, ys, 1)
                    horizon = n or 1
                    proj = float(a * (len(ys) - 1 + horizon) + b)
                    unit = _metric_unit(contracts, block_id, metric_name) or ""
                    recent = float(ys[-1])
                    msg = (f"依線性趨勢外推，{alias} 未來第 {horizon} 期約 "
                           f"{round(proj, 2)}{unit}（最近一期 {round(recent,2)}{unit}，"
                           f"每期斜率 {round(float(a),3)}）。註：簡單線性外推，僅供參考，"
                           f"不計季節性/製程變更。")
                    inline = df
            except Exception:  # noqa: BLE001
                pass
        intent = AIIntent(intent_kind="analysis_request" if inline is not None else "add_visual",
                          target_scope=f"page:{page_id}", trust_notes=notes, risk_level="low")
        if inline is not None:
            return NL2ProposalResult(intent=intent, message=msg, result_table=inline,
                                     proposal=proposal, trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, proposal=proposal,
                                 trust_notes=notes, risk_level="low")

    def _pareto_trend(self, contracts, block_id, metric_col, dim_col):
        """Round 135: split a category metric into earlier vs recent halves by
        date and find which category is worsening (largest share increase).

        Returns (message, per-category trend DataFrame) or (None, None)."""
        from ai4bi.blocks.datastore import materialize_dataframe
        import pandas as _pd
        try:
            df = materialize_dataframe(contracts[block_id])
        except Exception:  # noqa: BLE001
            return None, None
        date_col = _find_date_column(contracts, block_id)
        # the additive base column behind the metric (defect_die etc.)
        val = metric_col if metric_col in df.columns else next(
            (c for c in df.columns if "defect" in c.lower() and df[c].dtype.kind in "if"), None)
        if date_col is None or val is None or dim_col not in df.columns:
            return None, None
        work = df[[date_col, dim_col, val]].copy()
        work[date_col] = _pd.to_datetime(work[date_col], errors="coerce")
        work = work.dropna(subset=[date_col])
        if work.empty:
            return None, None
        midpoint = work[date_col].median()
        earlier = work[work[date_col] <= midpoint]
        recent = work[work[date_col] > midpoint]
        if earlier.empty or recent.empty:
            return None, None
        e_share = earlier.groupby(dim_col)[val].sum()
        r_share = recent.groupby(dim_col)[val].sum()
        e_tot, r_tot = e_share.sum() or 1, r_share.sum() or 1
        rows = []
        for cat in set(e_share.index) | set(r_share.index):
            ep = e_share.get(cat, 0) / e_tot * 100
            rp = r_share.get(cat, 0) / r_tot * 100
            rows.append({dim_col: cat, "前期佔比%": round(ep, 1),
                         "近期佔比%": round(rp, 1), "變化(點)": round(rp - ep, 1)})
        tbl = _pd.DataFrame(rows).sort_values("變化(點)", ascending=False).reset_index(drop=True)
        if tbl.empty:
            return None, None
        w = tbl.iloc[0]
        if w["變化(點)"] > 0:
            tmsg = (f"惡化趨勢：「{w[dim_col]}」近期佔比由 {w['前期佔比%']}% 升到 {w['近期佔比%']}%"
                    f"（+{w['變化(點)']} 點，以 {date_col} 中位數切前後期），最該關注。")
        else:
            tmsg = f"各類近期佔比皆未上升，無明顯惡化（以 {date_col} 中位數切前後期）。"
        return tmsg, tbl

    def _answer_calendar_yoy(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 100: "本月 vs 去年同月" / "same month last year" — calendar YoY.

        Compares period-to-date this year against the same dates last year
        (calendar boundaries), unlike the trailing-window comparison. Returns
        None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        hay = f"{prompt.lower()} {normalized}"
        grain = ("year" if any(t in hay for t in ("今年", "年增", "全年", "ytd", "this year"))
                 else "quarter" if any(t in hay for t in ("本季", "這季", "季")) else "month")

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        date_col = _find_date_column(contracts, block_id)
        if date_col is None:
            return None

        from ai4bi.analysis.time_intelligence import compute_calendar_comparison
        from ai4bi.query_spec import BlockRef, VisualQuerySpec

        base = VisualQuerySpec(
            spec_id=f"yoy_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)], inherit_global_filter=False)
        comp = compute_calendar_comparison(
            executor, base, date_block_id=block_id, date_column=date_col,
            grain=grain, metric_col=alias)
        if comp is None or comp.current is None:
            return None

        unit = _metric_unit(contracts, block_id, metric_name)
        cur_txt = _format_metric_value(comp.current, unit)
        sentence = f"{comp.current_label}「{alias}」為 {cur_txt}。"
        if comp.delta_pct is not None and comp.previous is not None:
            arrow = "↑" if comp.delta_pct >= 0 else "↓"
            sentence += (f"　較{comp.previous_label} {_format_metric_value(comp.previous, unit)} "
                         f"{arrow}{abs(comp.delta_pct):.1f}%（年增率）。")
        else:
            sentence += "　（去年同期無可比資料。）"
        notes = [f"日曆同期比較（{comp.current_label} vs {comp.previous_label}），治理查詢路徑。",
                 f"指標：{alias}（{metric_name} @ {block_id}）。"]
        answer = DirectAnswer(
            question=prompt.strip(), metric_block_id=block_id, metric_name=metric_name,
            metric_alias=alias, sentence=sentence, value=comp.current, period=grain,
            previous=comp.previous, delta_pct=comp.delta_pct,
            current_label=comp.current_label, previous_label=comp.previous_label,
            unit=unit, trust_notes=notes)
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, direct_answer=answer,
                                 trust_notes=notes, risk_level="low")

    def _answer_insights(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 097: "給我本週摘要" / "有什麼異常嗎？".

        Routes to the already-built generate_summary / detect_anomalies engines
        (previously sidebar-only) and returns the result as a table. Returns None
        to fall through.
        """
        if not contracts:
            return None
        kind = _looks_like_insights(prompt, normalized)
        if kind is None:
            return None
        import pandas as pd

        if kind == "anomaly":
            from ai4bi.ai.suggestions import detect_anomalies
            try:
                obs = detect_anomalies(contracts, max_observations=5)
            except Exception:  # noqa: BLE001
                return None
            # Round 184 (S10): a YIELD-scoped anomaly ask ("機台良率有沒有異常") must
            # not surface capacity_moves/uptime volume spread — keep only quality
            # (yield/defect) findings when the prompt is explicitly about yield.
            if any(t in f"{prompt.lower()} {normalized}" for t in ("良率", "yield", "不良", "缺陷")):
                _q = [o for o in obs if any(t in (o.metric or "").lower()
                      for t in ("yield", "良率", "defect", "不良", "pct", "rate"))]
                if _q:
                    obs = _q
            if not obs:
                notes = ["已掃描各資料集的離群與波動，未發現明顯異常。"]
                intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                                  trust_notes=notes, risk_level="low")
                return NL2ProposalResult(intent=intent, message="目前沒有發現明顯異常 👍",
                                         trust_notes=notes, risk_level="low")
            df = pd.DataFrame([{"嚴重度": {"high": "🔴 高", "medium": "🟡 中"}.get(o.severity, "ℹ️"),
                                "重點": f"{o.icon} {o.headline}", "說明": o.detail} for o in obs])
            # Round 137: name the actual findings inline (was a vague "發現 N 個重點").
            tops = "；".join(o.headline for o in obs[:3])
            sentence = f"掃描後發現 {len(obs)} 個值得注意的點：{tops}{'…' if len(obs) > 3 else ''}（詳見下表）。"
            notes = ["以離群（z-score）、波動（變異係數）等檢查掃描各資料集。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                     trust_notes=notes, risk_level="low")

        # kind == "digest"
        executor = getattr(self, "_executor", None)
        if executor is None:
            return None
        from ai4bi.analysis.summary import generate_summary
        try:
            rep = generate_summary(executor, contracts)
        except Exception:  # noqa: BLE001
            return None
        rows = [{"類別": sec.heading, "重點": line} for sec in rep.sections for line in sec.lines]
        # Round 184 (S15): lead the weekly summary with the top anomaly (e.g. the
        # yield excursion) so it surfaces what to ACT on, not just volume counts.
        try:
            from ai4bi.ai.suggestions import detect_anomalies
            _an = detect_anomalies(contracts, max_observations=2)
        except Exception:  # noqa: BLE001
            _an = []
        anom_rows = [{"類別": "⚠️ 異常", "重點": f"{o.icon} {o.headline}（{o.detail}）"}
                     for o in _an if o.severity == "high"]
        rows = anom_rows + rows
        if not rows:
            return None
        df = pd.DataFrame(rows)
        # Round 142: surface the top highlights inline, not just the title.
        tops = "；".join(r["重點"] for r in rows[:3])
        headline = f"{rep.title}：{tops}{'…（詳見下表）' if len(rows) > 3 else ''}"
        notes = ["整合期間重點、Top 排名與已觸發的提醒（與側欄『業務摘要』同源）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=headline, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_seasonality(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 096: "哪幾天最忙？" / "busiest day of week" / "哪個時段" .

        Groups a metric by weekday (DAYNAME) or hour (EXTRACT) — date buckets the
        single-GROUP-BY executor now supports — and ranks busiest-first. Surfaces
        the day-of-week / hour seasonality that was previously un-askable.
        Returns None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        hay = f"{prompt.lower()} {normalized}"
        bucket = "hour" if _is_hour_seasonality(hay) else "dow"
        label = "時段" if bucket == "hour" else "星期"

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        block_id = metric_name = alias = None
        if match is not None:
            block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        else:
            # No metric word ("最忙") → a count-like metric on a dated fact block.
            from ai4bi.blocks.contracts import BlockType
            for bid, c in contracts.items():
                if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                    continue
                if _find_date_column(contracts, bid) and (m := _default_count_metric(contracts, bid)):
                    block_id, (metric_name, alias) = bid, m
                    break
        if block_id is None:
            return None
        date_col = _find_date_column(contracts, block_id)
        if date_col is None:
            return None

        from ai4bi.query_spec import (
            BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec,
        )
        spec = VisualQuerySpec(
            spec_id=f"season_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, date_col, label, truncate_date_to=bucket)],
            sort=[SortSpec(alias, SortDirection.desc)],
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or label not in df.columns:
            return None

        top = df.iloc[0]
        sentence = (f"依「{label}」看「{alias}」，最高的是 {top[label]}"
                    f"（最忙排前；共 {len(df)} 個{label}）。")
        notes = [f"依 {label} 分組彙總「{alias}」並排序（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_segment_count(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 091: cold-start grouped measure filter.

        "買超過 3 次的客戶" / "customers who bought more than 3 times" — builds a
        grouped query (entity × count-metric) with a HAVING from scratch, even
        when no such visual exists, and returns the qualifying list. Returns None
        to fall through (e.g. to the on-visual measure filter).
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        operator = _measure_operator(f"{prompt.lower()} {normalized}")
        if operator is None:
            return None
        num = re.search(r"(\d[\d,]*\.?\d*)", f"{prompt} {normalized}")
        if num is None:
            return None
        try:
            threshold = float(num.group(1).replace(",", ""))
            if threshold.is_integer():
                threshold = int(threshold)
        except ValueError:
            return None

        idx = SchemaIndex.build(contracts)
        # Round 122: resolve the metric FIRST, then the entity on the SAME block —
        # 'cycle time > 200 的 lot' has cycle on the yield fact but lot_id on both,
        # so entity-first would mis-bind lot to the move fact and drop the metric.
        metric_match = idx.best_metric_match(prompt, normalized)
        if metric_match is not None:
            block_id = metric_match.block_id
            metric_name, alias = metric_match.metric_name, metric_match.alias
            # Round 129: a threshold expressed in hours ("卡關超過 4 小時") wants an
            # hour-unit measure, not a count. If the resolved metric isn't in hours,
            # switch to the best hour-unit sibling on the same block by keyword overlap
            # (卡關/卡住/停留→hold_age, 等待→queue_time).
            thay = f"{prompt.lower()} {normalized}"
            if any(t in thay for t in ("小時", "hours", "hour", " hr", "鐘頭")) and \
                    _metric_unit(contracts, block_id, metric_name) != "hr":
                pref = ("hold_age" if any(t in thay for t in ("卡關", "卡住", "停留", "滯留", "保留", "hold"))
                        else "queue" if any(t in thay for t in ("等待", "queue", "等候")) else "")
                best = None
                for mm in idx._metrics.values():
                    if mm.block_id != block_id:
                        continue
                    if _metric_unit(contracts, block_id, mm.metric_name) != "hr":
                        continue
                    score = (2 if pref and pref in mm.metric_name.lower() else 0) + \
                            (1 if mm.metric_name.lower().startswith("max_") else 0)
                    if best is None or score > best[0]:
                        best = (score, mm.metric_name, mm.alias)
                if best is not None and best[0] > 0:
                    metric_name, alias = best[1], best[2]
            entity_col = _entity_col_on_block(idx, prompt, normalized, contracts, block_id)
        else:
            entity_col, block_id = _resolve_entity_dimension(idx, prompt, normalized, contracts)
            if block_id is None:
                return None
            dm = _default_count_metric(contracts, block_id)
            if dm is None:
                return None
            metric_name, alias = dm
        if entity_col is None or block_id is None:
            return None

        from ai4bi.query_spec import (
            BlockRef, DimensionRef, HavingSpec, SortDirection, SortSpec, VisualQuerySpec,
        )

        spec = VisualQuerySpec(
            spec_id=f"segcount_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, entity_col, entity_col)],
            having=[HavingSpec(block_id, metric_name, operator, threshold)],
            sort=[SortSpec(alias, SortDirection.desc)],
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None:
            return None

        op_sym = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "neq": "≠"}.get(
            operator.value, operator.value)
        if df.empty:
            sentence = f"沒有「{entity_col}」符合 {alias} {op_sym} {threshold}。"
        else:
            top = df.iloc[0]
            tv = round(float(top[alias]), 2) if alias in df.columns else ""
            sentence = (f"共 {len(df)} 個「{entity_col}」符合 {alias} {op_sym} {threshold}，"
                        f"最高 {top[entity_col]}（{tv}）。")
        notes = [
            f"分組：{entity_col}；指標：{alias}；彙總後篩選 {alias} {op_sym} {threshold}（HAVING）。",
            f"治理查詢路徑（認證語意層），來源：{block_id}。",
        ]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence,
                                 result_table=df if not df.empty else None,
                                 direct_answer=None, trust_notes=notes, risk_level="low")

    def _answer_grouped_topn(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 090: "每個門市最暢銷的 3 個商品" / "top 3 products per store".

        Runs a two-dimension grouped query (outer group × inner entity) and keeps
        the top-N inner rows within each outer group — emulating a partitioned
        window function as a pandas post-pass. Returns None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        metric = idx.best_metric_match(prompt, normalized)
        if metric is None:
            return None
        block_id, metric_name, alias = metric.block_id, metric.metric_name, metric.alias

        outer_col, inner_col = _resolve_two_dims(idx, prompt, normalized, contracts, block_id)
        if outer_col is None or inner_col is None or outer_col == inner_col:
            return None

        n = _extract_rank_n(prompt, normalized, default=3)
        ascending = _ranking_is_ascending(prompt, normalized)

        from ai4bi.analysis.postprocess import top_n_per_group
        from ai4bi.query_spec import BlockRef, DimensionRef, VisualQuerySpec

        spec = VisualQuerySpec(
            spec_id=f"grouptopn_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, outer_col, outer_col),
                        DimensionRef(block_id, inner_col, inner_col)],
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or alias not in df.columns:
            return None

        table = top_n_per_group(df, outer_col, alias, n=n, ascending=ascending)
        if table is None or table.empty:
            return None

        superlative = "最低" if ascending else "最高"
        n_groups = table[outer_col].nunique()
        sentence = (f"每個「{outer_col}」中{alias}{superlative}的前 {n} 個「{inner_col}」"
                    f"（共 {n_groups} 組）。")
        notes = [
            f"先依「{outer_col}」「{inner_col}」分組彙總，再於每組內取前 {n}"
            f"（分區 Top-N，pandas 後處理；治理查詢路徑）。",
            f"來源：{block_id}。",
        ]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                 trust_notes=notes, risk_level="low")

    def _answer_capacity(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 128: capacity analytics — utilization / loading / headroom /
        plan attainment / throughput rate (move fact × capacity reference)."""
        if not contracts or "fab_tool_capacity" not in contracts:
            return None
        hay = f"{prompt.lower()} {normalized}"
        gk = ("area" if any(t in hay for t in ("區", "area", "區域")) else
              "vendor" if any(t in hay for t in ("vendor", "供應商", "廠商")) else
              "tool_group" if any(t in hay for t in ("機台群", "tool group", "群組")) else "tool_id")
        from ai4bi.analysis import capacity as _cap
        asc = any(t in hay for t in ("最低", "最少", "最差", "停機最多", "最閒", "lowest", "worst", "least"))
        # Round 130: what-if simulation (uptime uplift / tool failure) — checked first
        # since "稼動率…提升到 85%" / "故障" otherwise trip the availability branch.
        wif = self._answer_capacity_whatif(prompt, normalized, hay, contracts)
        if wif is not None:
            return wif
        # Round 130: overall single-number utilisation / attainment ("全廠整體利用率").
        if any(t in hay for t in ("整體", "總體", "整廠", "全廠整體", "全廠的產能利用")) and \
                not any(t in hay for t in ("各", "每", "依", "by ", "排名", "哪一", "哪台", "哪個", "哪區")):
            from ai4bi.blocks.datastore import materialize_dataframe
            mv = materialize_dataframe(contracts["fab_process_move"])
            cp = materialize_dataframe(contracts["fab_tool_capacity"])
            import pandas as _pd
            act, capm = float(mv["move_count"].sum()), float(cp["capacity_moves"].sum())
            plan = float(cp["planned_moves"].sum())
            if "達成" in hay or "計畫" in hay or "計劃" in hay or "plan" in hay:
                rate = round(act / plan * 100, 1) if plan else 0.0
                summ = _pd.DataFrame([{"範圍": "全廠", "實際": round(act), "計畫": round(plan), "達成率%": rate}])
                msg = f"全廠總體計畫達成率：{rate}%（實際 {round(act)} / 計畫 {round(plan)}）。"
                return self._capacity_result(msg, summ, "全廠總體達成率")
            util = round(act / capm * 100, 1) if capm else 0.0
            summ = _pd.DataFrame([{"範圍": "全廠", "實際": round(act), "產能": round(capm),
                                   "利用率%": util, "餘裕": round(capm - act)}])
            msg = f"全廠總體產能利用率：{util}%（實際 {round(act)} / 產能 {round(capm)}，餘裕 {round(capm - act)}）。"
            return self._capacity_result(msg, summ, "全廠總體利用率")
        # Round 130: gap-to-target loading ("距滿載 90% 還差多少 move").
        m_tgt = re.search(r"(?:滿載|目標|到|達|load)\D{0,4}(\d{2,3})\s*%", hay)
        if m_tgt and any(t in hay for t in ("還差", "差多少", "缺口", "還能接", "還可接", "可再接", "可多接")):
            target = float(m_tgt.group(1)) / 100
            tbl = _cap.utilization(contracts, gk)
            if tbl is not None and not tbl.empty:
                tbl = tbl.copy()
                tbl[f"距{int(target*100)}%缺口"] = (tbl["產能"] * target - tbl["實際"]).round(0)
                tbl = tbl.sort_values(f"距{int(target*100)}%缺口", ascending=False).reset_index(drop=True)
                gkcol = "tool_id" if gk == "tool_id" else gk
                w = tbl.iloc[0]
                msg = (f"距 {int(target*100)}% 滿載的可接單空間（依 {gk}）：最多 {w[gkcol]}"
                       f"（還可接 {w[f'距{int(target*100)}%缺口']} moves，目前利用率 {w['利用率%']}%）。")
                return self._capacity_result(msg, tbl, f"距 {int(target*100)}% 滿載缺口")
        # Round 130/184 (S13): expansion / "該加哪區產能 / 要擴哪站". Constraint theory
        # — you expand the BOTTLENECK (highest utilization), NOT wherever the plan
        # gap is biggest. An under-utilized station with a large plan miss (e.g.
        # THINFILM at 40% util) is a demand/scheduling issue, not a capacity one;
        # adding machines there does nothing for line output. Rank by utilization.
        if any(t in hay for t in ("擴產", "加機台", "增購", "加產能", "該加", "投資哪",
                                  "瓶頸區", "要擴", "擴充", "加哪", "擴哪", "該擴")):
            ut = _cap.utilization(contracts, gk)
            if ut is not None and not ut.empty and "利用率%" in ut.columns:
                ut = ut.sort_values("利用率%", ascending=False).reset_index(drop=True)
                gcol = ut.columns[0]
                w = ut.iloc[0]
                msg = (f"擴產應優先「瓶頸」——利用率最高處（依 {gcol}）：{w[gcol]}"
                       f"（利用率 {w['利用率%']}%）。擴沒滿載的站對整線產出無益（瓶頸理論：先解約束）。")
                return self._capacity_result(msg, ut, "擴產優先序（依利用率／瓶頸）")
        # Round 130: pure plan-gap question ("產能缺口最大的區 / 計畫差距") — where
        # you're MISSING plan most (a demand/scheduling view), distinct from where
        # to ADD capacity (the bottleneck, handled above).
        if any(t in hay for t in ("缺口", "計畫差距", "達成缺口", "未達計畫", "差計畫")):
            tbl = _cap.plan_attainment(contracts, gk if gk != "tool_id" else "area")
            if tbl is not None and not tbl.empty:
                tbl = tbl.copy()
                tbl["缺口"] = (tbl["計畫"] - tbl["實際"]).round(0).clip(lower=0)
                tbl = tbl.sort_values("缺口", ascending=False).reset_index(drop=True)
                gcol = tbl.columns[0]
                w = tbl.iloc[0]
                msg = (f"產能缺口（計畫−實際，依 {gcol}）最大：{w[gcol]}（缺口 {w['缺口']} moves，"
                       f"達成率 {w['達成率%']}%）。")
                return self._capacity_result(msg, tbl, "產能缺口（計畫−實際）")
        # availability (run ÷ available hours) lives on the capacity reference
        if any(t in hay for t in ("可用率", "availability", "停機", "稼動率")) and \
                not any(t in hay for t in ("利用率", "loading", "負載", "餘裕", "達成", "throughput")):
            from ai4bi.blocks.datastore import materialize_dataframe
            cap = materialize_dataframe(contracts["fab_tool_capacity"])
            cap = cap[["tool_id", "uptime_pct", "run_hours", "available_hours"]].copy()
            cap = cap.rename(columns={"uptime_pct": "可用率%"}).sort_values(
                "可用率%", ascending=asc or any(t in hay for t in ("停機", "最低"))).reset_index(drop=True)
            w = cap.iloc[0]
            msg = f"機台可用率（運轉÷可用工時）：{'最低' if asc else '最高'} {w['tool_id']}（{w['可用率%']}%）。"
            return self._capacity_result(msg, cap, "可用率 availability")
        if any(t in hay for t in ("達成率", "計畫", "plan", "達標", "計劃", "vs actual", "實際對計畫")):
            tbl = _cap.plan_attainment(contracts, gk if gk != "tool_id" else "area")
            if tbl is None or tbl.empty:
                return None
            w = tbl.iloc[0]
            msg = f"計畫達成率（依 {gk if gk!='tool_id' else 'area'}）：最低 {w.iloc[0]}（{w['達成率%']}%）。"
            return self._capacity_result(msg, tbl, "計畫達成率（實際÷計畫）")
        if any(t in hay for t in ("throughput", "每小時", "每工時", "單位工時", "moves/hr", "moves per", "產出率")):
            tbl = _cap.throughput_rate(contracts, gk)
            if tbl is None or tbl.empty:
                return None
            if asc:
                tbl = tbl.sort_values("moves_per_hr").reset_index(drop=True)
            w = tbl.iloc[0]
            msg = (f"產出率（moves/運轉小時，依 {gk}）："
                   f"{'最低' if asc else '最高'} {w.iloc[0]}（{w['moves_per_hr']}/hr）。")
            return self._capacity_result(msg, tbl, "產出率 moves/run-hour")
        # default: utilization / loading / headroom
        tbl = _cap.utilization(contracts, gk)
        if tbl is None or tbl.empty:
            return None
        # filter to a named area/tool value if the prompt scopes one ("ETCH 區的餘裕")
        gkcol = "tool_id" if gk == "tool_id" else gk
        if gkcol in tbl.columns:
            vals = {str(x) for x in tbl[gkcol].unique()}
            picked = next((v for v in vals if v and v.lower() in hay and len(v) >= 3), None)
            if picked:
                tbl = tbl[tbl[gkcol] == picked].reset_index(drop=True)
            elif gkcol == "tool_id":
                # tool-family prefix ("CVD 機台" → CVD-01/CVD-02)
                fams = {v.split("-")[0] for v in vals if "-" in v}
                fam = next((f for f in fams if f and f.lower() in hay and len(f) >= 3), None)
                if fam:
                    tbl = tbl[tbl[gkcol].str.startswith(fam + "-")].reset_index(drop=True)
        # "瓶頸/拖累/constraint" = highest loading (least headroom), never headroom-sorted
        is_bottleneck = any(t in hay for t in ("瓶頸", "constraint", "滿載", "最滿", "拖累", "卡整線", "拖垮"))
        is_headroom = (not is_bottleneck) and any(
            t in hay for t in ("餘裕", "headroom", "閒置", "還能", "空間", "line balance", "落差"))
        if is_headroom:
            tbl = tbl.sort_values("餘裕", ascending=False).reset_index(drop=True)
            w = tbl.iloc[0]
            msg = (f"產能餘裕（依 {gk}）：最多 {w.iloc[0]}（餘裕 {w['餘裕']}，利用率 {w['利用率%']}%）。"
                   f"註：餘裕＝產能−實際，反映「可吸收量」；實際接單仍需確認有需求、"
                   f"且不會把下游或瓶頸站推爆（建議搭配瓶頸/Little's Law 一起看）。")
        else:
            w = tbl.iloc[0]
            label = "負載率" if any(t in hay for t in ("負載", "loading", "滿載")) else "利用率"
            msg = f"{label}（依 {gk}）：最高 {w.iloc[0]}（{w['利用率%']}%），最該關注的瓶頸/滿載點。"
        return self._capacity_result(msg, tbl, "產能利用率（實際÷產能）")

    def _answer_yield_whatif(self, prompt, normalized, report, contracts) -> "NL2ProposalResult | None":
        """Round 184 (S18): yield what-if — "若 ETCH-02 良率提升到 90% / 良率提升 5
        個百分點，全廠會怎樣". Computes the extra good die and the new fab-wide
        die-weighted yield, holding tested wafers constant. None if no pattern."""
        if not contracts:
            return None
        import re as _re
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        hay = f"{prompt.lower()} {normalized}"
        if "良率" not in hay and "yield" not in hay:
            return None
        m_to = _re.search(r"(?:提升到|提高到|拉到|拉高到|升到|改善到|增加到|到)\s*(\d{1,3}(?:\.\d+)?)\s*%", hay)
        m_d = _re.search(r"(?:提升|提高|增加|多|拉高)\s*(\d{1,2}(?:\.\d+)?)\s*(?:個百分點|個%|pp|%)", hay)
        if not m_to and not m_d:
            return None
        # find the yield fact (good_die + tested_die)
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            cols = {col.name for col in getattr(c, "columns", [])}
            if not ({"good_die", "tested_die"} <= cols):
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            fab_good = float(df["good_die"].sum())
            fab_tested = float(df["tested_die"].sum())
            if fab_tested <= 0:
                return None
            fab_yield = fab_good / fab_tested * 100.0
            # optional scope: a named tool/family value present in the prompt
            scope, sub = "全廠", df
            hay_norm = hay.replace("-", "").replace(" ", "")
            for col in [x.name for x in c.columns if x.data_type in ("string", "str", "object")]:
                if col not in df.columns or _is_pk_like(col):
                    continue
                for v in df[col].dropna().astype(str).unique():
                    vn = str(v).lower().replace("-", "").replace(" ", "")
                    if len(vn) >= 4 and vn in hay_norm:
                        sub = df[df[col].astype(str) == v]
                        scope = str(v)
                        break
                if scope != "全廠":
                    break
            s_good = float(sub["good_die"].sum())
            s_tested = float(sub["tested_die"].sum())
            if s_tested <= 0:
                return None
            cur = s_good / s_tested * 100.0
            new = float(m_to.group(1)) if m_to else cur + float(m_d.group(1))
            extra = s_tested * (new - cur) / 100.0
            new_fab_yield = (fab_good + extra) / fab_tested * 100.0
            verb = "提升" if new >= cur else "下降"
            msg = (f"假設「{scope}」良率由 {cur:.1f}% {verb}到 {new:.1f}%（受測片數不變）："
                   f"該範圍約{'多' if extra >= 0 else '少'} {abs(extra):,.0f} 個良品晶粒；"
                   f"全廠加權良率由 {fab_yield:.1f}% → {new_fab_yield:.1f}%"
                   f"（{'+' if new_fab_yield >= fab_yield else ''}{new_fab_yield - fab_yield:.2f} 個百分點）。")
            notes = [f"以 good_die/tested_die die-count 加權重算；假設受測晶粒數不變，"
                     f"僅良率改變。來源：{bid}。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg, trust_notes=notes,
                                     risk_level="low")
        return None

    def _answer_capacity_whatif(self, prompt, normalized, hay, contracts) -> "NL2ProposalResult | None":
        """Round 130: light capacity what-if — uptime uplift (X%→Y%) or tool failure.

        Throughput per run-hour is fixed, so output scales with uptime; a failed tool
        loses its actual moves. Reports the resulting capacity delta, scoped to the
        tool/area named in the prompt. Returns None when no what-if pattern matches.
        """
        import re as _re
        from ai4bi.blocks.datastore import materialize_dataframe
        import pandas as _pd
        cp = materialize_dataframe(contracts["fab_tool_capacity"])
        mv = materialize_dataframe(contracts["fab_process_move"])
        actual = mv.groupby("tool_id")["move_count"].sum()
        # scope: a tool_id named in the prompt
        tool = next((t for t in cp["tool_id"].astype(str) if t.lower() in hay), None)

        is_fail = any(t in hay for t in ("故障", "當機", "壞掉", "失效", "掉機", "停機一",
                                         "停擺", "下線")) and \
            any(t in hay for t in ("產能", "產出", "掉多少", "少多少", "影響", "會掉", "損失"))
        # Round 184 (S18 bug): match on a SINGLE copy — hay is prompt+" "+normalized
        # (the same sentence twice), which made "提升到 85%" match the same 85 twice
        # → "85%→85% +0". Use prompt.lower() so the two-value regex only fires on a
        # genuine "從 X% 到 Y%".
        _one = prompt.lower()
        m_up = _re.search(r"(\d{1,3})\s*%.{0,12}?(?:提升到|提高到|拉到|升到|到|→|->|改善到)\s*(\d{1,3})\s*%", _one)
        m_up1 = _re.search(r"(?:提升到|提高到|拉到|升到|改善到)\s*(\d{1,3})\s*%", _one)

        if is_fail and tool is not None:
            lost = float(actual.get(tool, 0))
            total = float(actual.sum())
            share = round(lost / total * 100, 1) if total else 0.0
            tbl = _pd.DataFrame([{"情境": f"{tool} 故障停機", "損失 moves": round(lost),
                                  "占全廠%": share, "剩餘產出": round(total - lost)}])
            msg = (f"若 {tool} 故障停機，預估直接損失其產出 ~{round(lost)} moves"
                   f"（占全廠 {share}%）。{tool} 是瓶頸，實務上整線產出可能等比下滑。")
            return self._capacity_result(msg, tbl, "what-if：機台故障")

        if (m_up or m_up1) and tool is not None:
            row = cp[cp["tool_id"].astype(str) == tool].iloc[0]
            u0 = float(row["uptime_pct"]) / 100
            # only treat as "from X% to Y%" when X≠Y; otherwise it's a single-target
            # ("提升到 85%") whose baseline is the tool's ACTUAL current uptime.
            if m_up and m_up.group(1) != m_up.group(2):
                u0, u1 = float(m_up.group(1)) / 100, float(m_up.group(2)) / 100
            elif m_up1:
                u1 = float(m_up1.group(1)) / 100
            else:
                u1 = float(m_up.group(2)) / 100
            if u0 <= 0:
                return None
            act = float(actual.get(tool, 0))
            extra = round(act * (u1 / u0 - 1))
            tbl = _pd.DataFrame([{"情境": f"{tool} 稼動率 {int(u0*100)}%→{int(u1*100)}%",
                                  "目前產出": round(act), "增量 moves": extra,
                                  "新產出": round(act + extra)}])
            msg = (f"{tool} 稼動率從 {int(u0*100)}% 提升到 {int(u1*100)}%，產出可由運轉工時等比增加"
                   f"約 +{extra} moves（{round(act)} → {round(act+extra)}）。")
            return self._capacity_result(msg, tbl, "what-if：稼動率提升")
        return None

    def _answer_oee(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 128: OEE = Availability × Performance × Quality per tool."""
        if not contracts or "fab_tool_capacity" not in contracts:
            return None
        import re as _re
        from ai4bi.analysis.capacity import compute_oee
        tbl = compute_oee(contracts)
        if tbl is None or tbl.empty:
            return None
        hay = f"{prompt.lower()} {normalized}"
        # Round 134: reliability / honesty question ("這個數字可靠嗎 / 準不準 / 怎麼來的").
        # OEE here is DERIVED from the fab_tool_capacity reference table, not measured
        # from SEMI E10 equipment states — be explicit instead of implying precision.
        asks_reliable = any(t in hay for t in (
            "可靠", "準嗎", "準不準", "可信", "怎麼算", "怎麼來", "靠譜", "信得過",
            "reliable", "accurate", "trust", "how is it", "資料夠"))
        if asks_reliable and "oee" in hay:
            tool = next((t for t in tbl["tool_id"].astype(str) if t.lower() in hay), None)
            if tool is not None:
                w = tbl[tbl["tool_id"].astype(str) == tool].iloc[0]
                num = (f"{tool} 的 OEE 為 {w['OEE']}%（A {w['可用率A']}%、P {w['表現P']}%、"
                       f"Q {w['良率Q']}%）。")
                show = tbl[tbl["tool_id"].astype(str) == tool].reset_index(drop=True)
            else:
                avg = tbl[["可用率A", "表現P", "良率Q", "OEE"]].mean().round(1)
                num = (f"全廠平均 OEE 為 {avg['OEE']}%（A {avg['可用率A']}%、P {avg['表現P']}%、"
                       f"Q {avg['良率Q']}%）。")
                show = tbl
            honesty = (
                "可靠性說明：此 OEE 由「機台產能參考表 (fab_tool_capacity)」推導，"
                "非量測自 SEMI E10 設備狀態（PRD/SBY/DWN/ENG/UDT）。可用率A 來自參考表的"
                " uptime、表現P 來自理想節拍假設、良率Q 才是實測良率。"
                "因此 A、P 屬規劃/假設值，要量測級精度需接入 FDC/EAP 的 E10 狀態紀錄。"
                "把它當「相對比較與趨勢」可信，當「絕對精確值」則需保留。")
            notes = [honesty]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="medium")
            return NL2ProposalResult(intent=intent, message=num + honesty, result_table=show,
                                     trust_notes=notes, risk_level="medium")
        # Round 131: OEE what-if — "把 X 的 OEE 拉到全廠平均/Y%，產能可多多少".
        if ("oee" in hay) and any(t in hay for t in ("拉到", "提升到", "改善到", "拉高到", "提高到", "升到")):
            tool = next((t for t in tbl["tool_id"].astype(str) if t.lower() in hay), None)
            if tool is not None:
                cur = float(tbl[tbl["tool_id"].astype(str) == tool].iloc[0]["OEE"])
                if any(t in hay for t in ("全廠平均", "整廠平均", "平均水準", "平均")):
                    tgt = round(float(tbl["OEE"].mean()), 1)
                else:
                    mm = _re.search(r"(\d{2,3})\s*%", hay)
                    tgt = float(mm.group(1)) if mm else None
                if tgt and cur > 0:
                    import pandas as _pd
                    from ai4bi.blocks.datastore import materialize_dataframe
                    mv = materialize_dataframe(contracts["fab_process_move"])
                    act = float(mv.groupby("tool_id")["move_count"].sum().get(tool, 0))
                    extra = round(act * (tgt / cur - 1))
                    wt = _pd.DataFrame([{"情境": f"{tool} OEE {cur}%→{tgt}%", "目前產出": round(act),
                                         "增量 moves": extra, "新產出": round(act + extra)}])
                    msg = (f"把 {tool} 的 OEE 由 {cur}% 拉到 {tgt}%，等比可多產出約 +{extra} moves"
                           f"（{round(act)} → {round(act + extra)}）。")
                    return self._capacity_result(msg, wt, "what-if：OEE 提升")
        # optional grouping: roll per-tool OEE up to vendor / area / tool_group
        grp = ("vendor" if any(t in hay for t in ("vendor", "供應商", "廠商")) else
               "area" if any(t in hay for t in ("區", "area", "區域")) else
               "tool_group" if any(t in hay for t in ("機台群", "tool group", "群組")) else None)
        if grp:
            from ai4bi.blocks.datastore import materialize_dataframe
            cap = materialize_dataframe(contracts["fab_tool_capacity"])[["tool_id", grp]]
            j = tbl.merge(cap, on="tool_id", how="left")
            tbl = (j.groupby(grp)[["可用率A", "表現P", "良率Q", "OEE"]]
                   .mean().round(1).reset_index().sort_values("OEE").reset_index(drop=True))
            w = tbl.iloc[0]
            msg = (f"OEE（依 {grp}）最低：{w[grp]}（OEE {w['OEE']}%；A {w['可用率A']}%、"
                   f"P {w['表現P']}%、Q {w['良率Q']}%）。")
            return self._capacity_result(msg, tbl, "OEE = 可用率 × 表現 × 良率（依群組平均）")
        asks_which_tool = any(t in hay for t in (
            "哪一台", "哪台", "哪一", "哪個機台", "which tool", "先處理", "處理哪", "優先處理"))
        # fab-wide average (no per-tool drill asked)
        if (not asks_which_tool) and any(
                t in hay for t in ("全廠", "整廠", "全廠平均", "overall", "whole fab", "平均 oee", "平均oee")):
            import pandas as _pd
            avg = tbl[["可用率A", "表現P", "良率Q", "OEE"]].mean().round(1)
            summ = _pd.DataFrame([{"範圍": "全廠平均", **avg.to_dict()}])
            msg = (f"全廠平均 OEE：{avg['OEE']}%（A {avg['可用率A']}%、P {avg['表現P']}%、"
                   f"Q {avg['良率Q']}%）。世界級標竿約 85%。")
            return self._capacity_result(msg, summ, "OEE 全廠平均")
        # threshold filter ("OEE 低於 60% 的機台")
        m = _re.search(r"(低於|小於|below|under|<)\s*([0-9]+(?:\.[0-9]+)?)", hay)
        if m and any(t in hay for t in ("oee",)):
            thr = float(m.group(2))
            sub = tbl[tbl["OEE"] < thr].reset_index(drop=True)
            msg = (f"OEE 低於 {thr:g}% 的機台共 {len(sub)} 台"
                   + (f"：{', '.join(sub['tool_id'])}。" if len(sub) else "（無）。"))
            return self._capacity_result(msg, sub if len(sub) else tbl, "OEE 門檻篩選")
        # factor focus: performance / quality / availability worst — but only when ONE
        # factor is named. A question listing all three ("是A、P還是Q拖累？") wants the
        # actual dragging factor, so fall through to the default worst-factor naming.
        factor_words = sum(bool(any(t in hay for t in grp_words)) for grp_words in (
            ("可用率", "availability"), ("表現", "performance"), ("良率", "quality", "品質")))
        # Round 131: OEE loss decomposition / Pareto — "三大損失各幾個百分點 / 損失 Pareto".
        # When losses are asked without singling out ONE factor, rank each factor's loss
        # (100 − factor, in points) so the user sees where to attack first.
        is_loss = any(t in hay for t in ("損失", "loss", "pareto", "百分點", "六大損失", "拆解"))
        if is_loss and factor_words != 1:
            import pandas as _pd
            avg = tbl[["可用率A", "表現P", "良率Q"]].mean()
            lt = _pd.DataFrame([
                {"因子": "可用率(A)", "平均%": round(float(avg["可用率A"]), 1)},
                {"因子": "表現(P)", "平均%": round(float(avg["表現P"]), 1)},
                {"因子": "良率(Q)", "平均%": round(float(avg["良率Q"]), 1)},
            ])
            lt["損失百分點"] = (100 - lt["平均%"]).round(1)
            lt = lt.sort_values("損失百分點", ascending=False).reset_index(drop=True)
            top = lt.iloc[0]
            msg = (f"OEE 三大損失（全廠平均，百分點）：{top['因子']} 損失最大 {top['損失百分點']} 點，"
                   f"其次見表。Pareto 上應優先改善 {top['因子']}。")
            return self._capacity_result(msg, lt, "OEE 損失拆解（Pareto）")
        _WORST = ("最差", "最低", "最大", "影響最大", "拖累", "嚴重", "損失", "worst", "loss")
        focus = None
        if factor_words == 1 and any(t in hay for t in ("表現", "performance")) and \
                any(t in hay for t in _WORST):
            focus = ("表現P", "表現(P)")
        elif factor_words == 1 and any(t in hay for t in ("良率", "quality", "品質")) and any(
                t in hay for t in _WORST):
            focus = ("良率Q", "良率(Q)")
        elif factor_words == 1 and any(t in hay for t in ("可用率", "availability")) and any(
                t in hay for t in _WORST):
            focus = ("可用率A", "可用率(A)")
        if focus:
            col, label = focus
            tbl = tbl.sort_values(col).reset_index(drop=True)
            w = tbl.iloc[0]
            msg = (f"{label} 最低：{w['tool_id']}（{col} {w[col]}%；OEE {w['OEE']}%）。"
                   f"這是該機台 OEE 最該優先改善的環節。")
            return self._capacity_result(msg, tbl, f"OEE 因子聚焦：{label}")
        w = tbl.iloc[0]
        # name the dragging factor for the worst tool
        factors = {"可用率(A)": w["可用率A"], "表現(P)": w["表現P"], "良率(Q)": w["良率Q"]}
        worst_factor = min(factors, key=factors.get)
        msg = (f"OEE 最低：{w['tool_id']}（OEE {w['OEE']}%；A {w['可用率A']}%、"
               f"P {w['表現P']}%、Q {w['良率Q']}%）。主要拖累：{worst_factor}。")
        return self._capacity_result(msg, tbl, "OEE = 可用率 × 表現 × 良率")

    def _capacity_result(self, msg: str, table, note: str) -> "NL2ProposalResult":
        notes = [note + "（move fact × 產能參考對齊，跨表彙總）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, result_table=table,
                                 trust_notes=notes, risk_level="low")

    def _answer_bottleneck_drift(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 134: does the bottleneck station shift over time? Wires the
        analysis/capacity_dynamics.bottleneck_over_time engine into NL."""
        if not contracts or "fab_process_move" not in contracts:
            return None
        from ai4bi.analysis.capacity_dynamics import (
            bottleneck_over_time, bottleneck_shift_summary)
        from ai4bi.blocks.datastore import materialize_dataframe
        hay = f"{prompt.lower()} {normalized}"
        group_col = ("area" if any(t in hay for t in ("區", "area", "區域"))
                     else "tool_id")
        # value defining "the bottleneck" each period: queue time is the honest
        # constraint signal; move_count when the prompt is about loading/throughput.
        value_col = ("move_count" if any(t in hay for t in ("移動", "move", "產出", "吞吐", "loading", "負載"))
                     else "queue_time_hr")
        freq = ("M" if any(t in hay for t in ("每個月", "逐月", "月")) else "W")
        try:
            df = materialize_dataframe(contracts["fab_process_move"])
        except Exception:  # noqa: BLE001
            return None
        res = bottleneck_over_time(df, "event_date", group_col, value_col, freq=freq, agg="mean")
        if res is None or res.empty:
            return None
        summary = bottleneck_shift_summary(res)
        unit = {"W": "週", "M": "月"}.get(freq, "期")
        vlabel = "佇列時間" if value_col == "queue_time_hr" else "移動次數"
        # Round 145: attach the bottleneck VALUE at each period so a swap shows its
        # magnitude (e.g. ETCH-02 5.9hr → IMP-02 6.1hr), not just the names.
        val_at = {row["period"]: row["value"] for _, row in res.iterrows()}
        if summary["shifted"]:
            ch000 = summary["shifts"]
            parts = "；".join(
                f"{s['period']} {s['from']}→{s['to']}（{vlabel} {val_at.get(s['period'], '?')}）"
                for s in ch000[:4])
            msg = (f"瓶頸（依{vlabel}最高的 {group_col}）在 {summary['n_periods']} 個{unit}內"
                   f"換過 {len(ch000)} 次：{parts}。最常居首：{summary['dominant']}。"
                   f"註：以{vlabel}為瓶頸代理指標；切換幅度小時可能只是週間波動，"
                   f"建議連看 2-3 {unit}確認是否真的轉移。")
        else:
            msg = (f"瓶頸（依{vlabel}最高的 {group_col}）在 {summary['n_periods']} 個{unit}內"
                   f"沒有換站，始終是 {summary['dominant']}。")
        notes = [f"瓶頸漂移：每{unit}取各 {group_col} 的{vlabel}平均，取最高者為當期瓶頸"
                 f"（母體 {len(df)} 筆 move，期間欄 event_date）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, result_table=res,
                                 trust_notes=notes, risk_level="low")

    def _answer_wip_ct(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 134: WIP ↔ cycle-time relationship (Little's Law lens). Wires
        analysis/capacity_dynamics.wip_vs_cycle_time into NL."""
        if not contracts:
            return None
        from ai4bi.analysis.capacity_dynamics import wip_vs_cycle_time
        from ai4bi.blocks.datastore import materialize_dataframe
        # Cycle time lives on the yield fact (cycle_time_hr); pick whichever fact
        # actually carries a cycle-time column.
        target = None
        for bid in ("fab_wafer_yield", "fab_process_move"):
            c = contracts.get(bid)
            if c is None:
                continue
            cols = {col.name for col in getattr(c, "columns", [])}
            ct = next((x for x in cols if "cycle" in x.lower()), None)
            if ct:
                date_col = next((x for x in cols if x.lower() in ("test_date", "event_date", "date")), None)
                lot_col = "lot_id" if "lot_id" in cols else None
                if date_col:
                    target = (bid, date_col, ct, lot_col)
                    break
        if target is None:
            return None
        bid, date_col, ct, lot_col = target
        try:
            df = materialize_dataframe(contracts[bid])
        except Exception:  # noqa: BLE001
            return None
        per, summary = wip_vs_cycle_time(df, date_col, ct, lot_col=lot_col, freq="W")
        if per is None or per.empty or summary.get("r") is None:
            # honest "not enough data" rather than a wrong number
            msg = ("資料的週期點不足以可靠估計 WIP 與 cycle time 的關係"
                   f"（有效週數 {summary.get('n', 0)}）。")
            notes = [msg]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg,
                                     result_table=per if per is not None and not per.empty else None,
                                     trust_notes=notes, risk_level="low")
        # Round 146: add average WIP/throughput context + an actionable Little's Law
        # read, so a weak r still yields a useful operational takeaway.
        avg_wip = round(float(per["wip"].mean()), 1)
        avg_tp = round(float(per["throughput"].mean()), 1)
        weak = abs(summary["r"]) < 0.5
        action = ("（r 偏弱，cycle time 受 WIP 以外因素影響較大，如 hold/批量/機台可用率；"
                  "建議連看 hold 時間與瓶頸站）" if weak else
                  "（符合 Little's Law：要縮短 cycle time，優先降 WIP 或提 throughput）")
        msg = (f"{summary['relationship']}；WIP 與 cycle time 的相關係數 r={summary['r']}"
               f"（依週對齊，n={summary['n']} 週；平均 WIP≈{avg_wip}、throughput≈{avg_tp}/週）。"
               f"{action}表中 littles_law_ct = WIP/throughput 為誠實對照。")
        notes = [f"WIP↔cycle time：每週以 {lot_col or '列數'} 計 WIP、以 {ct} 取平均 cycle time，"
                 f"Pearson r。Little's Law 對照欄非宣稱值。來源：{bid}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, result_table=per,
                                 trust_notes=notes, risk_level="low")

    def _answer_spc(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 117: SPC control-limit outliers (μ ± kσ) of a measure by entity."""
        if not contracts:
            return None
        from ai4bi.analysis.spc import control_limit_outliers
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        idx = SchemaIndex.build(contracts)
        hay = f"{prompt.lower()} {normalized}"
        km = re.search(r"(\d+(?:\.\d+)?)\s*(?:個|倍)?\s*(?:標準差|σ|sigma)", hay)
        k = float(km.group(1)) if km else 3.0
        # Round 184 (S10): a bare SPC ask ("幫我看管制圖") with no named measure
        # defaults to YIELD — the natural quality metric — rather than failing.
        _other_measure = any(t in hay for t in (
            "等待", "queue", "cycle", "週期", "oee", "可用率", "稼動", "利用率",
            "move", "移動", "產能", "throughput", "稼動率", "uptime", "缺陷", "defect"))
        _yld_q = any(t in hay for t in ("良率", "yield", "不良", "壞", "低良")) or not _other_measure
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            cols = {col.name for col in getattr(c, "columns", [])}
            # Round 184 (S10): a YIELD SPC question must run on the yield block with
            # the yield column — never fall through to a move/capacity block (which
            # would scan an unrelated measure like capacity_moves → wrong answer).
            yld_col = next((x for x in ("yield_pct", "weighted_yield_pct", "yield")
                            if x in cols), None)
            if _yld_q and not yld_col:
                continue
            ent = _resolve_decomp_dimension(idx, prompt, normalized, contracts, bid)
            val = yld_col if (_yld_q and yld_col) else _resolve_numeric_column(prompt, normalized, c)
            # bare yield SPC with no dimension → default to the tool axis (the
            # few-tools honest path then names ETCH-02 + drills to wafer/lot).
            if _yld_q and yld_col and not ent:
                ent = next((x for x in ("etch_tool_id", "tool_id", "wafer_id", "lot_id")
                            if x in cols), None)
            if not ent or not val:
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            extra_note = ""
            table, limits = control_limit_outliers(df, ent, val, k=k)
            if not limits and ent in df.columns and val in df.columns:
                # Round 184 (S10): σ-based outlier detection needs ≥3 groups; a
                # tool axis with only 2 machines (ETCH-01/02) can't be judged that
                # way. Be honest + name the extreme tool, then drop to a finer grain
                # (wafer/lot) that DOES have enough groups so real excursions show.
                _per = df.groupby(ent)[val].mean()
                if 0 < len(_per) < 3:
                    _lo = _per.idxmin()
                    extra_note = (
                        f"「{ent}」只有 {len(_per)} 個，樣本太少無法做嚴格的機台間 SPC 離群判定；"
                        f"但以平均「{val}」看，最低是「{_lo}」（{round(float(_per.min()), 2)}）、"
                        f"最高「{_per.idxmax()}」（{round(float(_per.max()), 2)}），差距明顯，建議優先檢視「{_lo}」。")
                    for finer in ("wafer_id", "lot_id"):
                        if finer in cols and finer != ent:
                            t2, l2 = control_limit_outliers(df, finer, val, k=k)
                            if l2:
                                table, limits, ent = t2, l2, finer
                                extra_note += f" 另以「{finer}」層級掃描如下。"
                                break
            if not limits:
                if extra_note:  # too few groups AND no finer grain — answer honestly
                    notes = [f"SPC：依 {ent} 的 μ±{k:g}σ 離群掃描。來源：{bid}。"]
                    intent = AIIntent(intent_kind="analysis_request",
                                      target_scope="semantic_model",
                                      trust_notes=notes, risk_level="low")
                    return NL2ProposalResult(intent=intent, message=extra_note,
                                             trust_notes=notes, risk_level="low")
                continue
            if table.empty:
                msg = (f"沒有「{ent}」的「{val}」超出 μ±{k:g}σ"
                       f"（μ={limits['mean']}, σ={limits['sigma']}）。")
                # Round 178 (S9): no outlier at k σ — still surface the entity
                # CLOSEST to the limit so the engineer isn't left with a bare
                # "nothing" and knows where the next risk sits.
                try:
                    sig = float(limits.get("sigma") or 0)
                    mu = float(limits.get("mean") or 0)
                    if sig > 0 and ent in df.columns and val in df.columns:
                        per = df.groupby(ent)[val].mean()
                        z = ((per - mu) / sig).abs()
                        top = z.idxmax()
                        zt = round(float(z.max()), 2)
                        arrow = "偏高↑" if per[top] > mu else "偏低↓"
                        msg += (f" 最接近界限的是「{top}」（{round(float(per[top]), 2)}，"
                                f"約 {zt:g}σ {arrow}）；放寬到 {zt:g}σ 就會超出。")
                except Exception:  # noqa: BLE001
                    pass
            else:
                names = "、".join(str(x) for x in table[ent].head(3).tolist())
                msg = (f"{len(table)} 個「{ent}」超出管制界限 μ±{k:g}σ：{names}"
                       f"（μ={limits['mean']}, UCL={limits['ucl']}, LCL={limits['lcl']}）。")
            if extra_note:  # Round 184 (S10): prepend the too-few-tools honesty
                msg = f"{extra_note}\n\n{msg}"
            notes = [f"SPC：依 {ent} 取平均後，以全體 μ±{k:g}σ 為管制界限。來源：{bid}。"]
            # Round 137: SPC honesty — answer "這算管制圖嗎 / Cpk" honestly. This is a
            # cross-entity μ±kσ outlier scan, NOT a time-ordered control chart.
            if any(t in hay for t in ("管制圖", "control chart", "cpk", "ppk", "spc 嗎",
                                      "算 spc", "算spc", "是 spc", "西電", "western electric", "管制圖嗎")):
                honest = ("說明：這是「跨機台 μ±kσ 離群掃描」，非嚴格的時序管制圖——"
                          "未做合理分組(rational subgrouping)、無 I-MR/X̄-R 圖、無 Western Electric 連串判讀、"
                          "也未對規格上下限算 Cpk/Ppk。當「相對離群篩選」可用；要正式 SPC/製程能力需時序樣本與規格界限。")
                msg = msg + honest
                notes.append(honest)
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg,
                                     result_table=table if not table.empty else None,
                                     trust_notes=notes, risk_level="low")
        return None

    def _answer_commonality(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 117: commonality — which tool is shared by lots failing a yield cut."""
        if not contracts:
            return None
        from ai4bi.analysis.crossfact import commonality
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        idx = SchemaIndex.build(contracts)
        hay = f"{prompt.lower()} {normalized}"

        # threshold metric (yield) + value, e.g. 良率 < 80.
        # Round 137 fix: must NOT grab digits embedded in a tool name ("ETCH-02"
        # → 2.0). Prefer a number adjacent to a comparison cue or a % sign; only
        # then a standalone number not glued to letters/hyphens.
        threshold = _parse_threshold(hay)
        op = "lt" if any(t in hay for t in ("以下", "低於", "小於", "<", "below", "under", "掉到")) else "gt"

        facts = {b: c for b, c in contracts.items()
                 if getattr(c, "block_type", None) in (
                     BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)}
        # the fact holding the qualifying measure (yield) and the detail fact (moves)
        measure_block = measure_col = group_key = None
        # Round 178 (S3): "不良/壞/低良" wafers are a yield question too — bind the
        # yield column so abbreviated commonality phrasings resolve.
        # a culprit question ("良率殺手 / 最大元兇 / 拖累良率") is a YIELD question even
        # without the literal "良率" — bind the yield column so worst-quartile
        # commonality finds ETCH-02. Unless the prompt explicitly says 缺陷/defect.
        _defect_q = any(t in hay for t in ("缺陷", "defect", "瑕疵", "壞點", "破片", "不良類"))
        _culprit_q = any(t in hay for t in (
            "殺手", "兇手", "凶手", "元兇", "元凶", "禍首", "罪魁", "拖累", "害", "搞鬼"))
        _yield_q = (any(t in hay for t in ("良率", "yield", "不良", "壞", "低良", "差的"))
                    or _culprit_q) and not _defect_q
        for bid, c in facts.items():
            # Round 178 (S3): a yield question must bind the YIELD column, not a
            # count like failed_wafer_count that the longest-token match grabs
            # (which then fails the yield filter and silently aborts commonality).
            col = None
            if _yield_q:
                _numcols = [cc.name for cc in getattr(c, "columns", [])
                            if getattr(cc, "data_type", "") in ("integer", "float", "int",
                                                                "number", "numeric", "double", "bigint")]
                col = next((n for n in _numcols
                            if "yield" in n.lower() or n.lower().endswith("_pct")), None)
            if col is None:
                col = _resolve_numeric_column(prompt, normalized, c)
            if col and any(t in col.lower() for t in ("yield", "pct", "rate", "defect")):
                measure_block, measure_col = bid, col
                break
        if measure_block is None:
            # Round 178 (S3): a commonality cue fired but no measure was named
            # ("是不是都經過同一台機台") — default to a yield column (low yield = the
            # "bad" wafers) so we don't abort and fall through to a wrong handler.
            for bid, c in facts.items():
                yc = next((cc.name for cc in getattr(c, "columns", [])
                           if "yield" in cc.name.lower()
                           and getattr(cc, "data_type", "") in ("integer", "float")), None)
                if yc:
                    measure_block, measure_col = bid, yc
                    break
        if measure_block is None:
            return None
        # No explicit threshold: qualify the WORST quantile of the measure (low
        # yield / high defect) and run a TRUE commonality (lift + Fisher). We only
        # reach here because a commonality cue fired, so "共通點 / 元兇 / 都經過同一台"
        # all mean "the common tool among the bad ones" — always default to the
        # worst quartile rather than returning None (Round 140 + 178 S3).
        if threshold is None:
            # Round 182 (S3): the WORST end depends on the MEASURE, not on a "最大/
            # 最差" modifier — "良率最大殺手" still means LOWEST yield, not highest.
            # Only flip to the high end for a defect count, or when the user
            # explicitly asks for the BEST wafers' shared tool.
            _wants_high = any(t in hay for t in (
                "良率最高", "最高良率", "最高的良率", "良率最好", "最好", "表現最好", "良率最佳"))
            if "defect" in measure_col.lower():
                worst_high = True
            elif any(t in measure_col.lower() for t in ("yield", "pct", "rate")):
                worst_high = _wants_high
            else:
                worst_high = any(t in hay for t in ("最多", "最高", "最大", "最嚴重"))
            topn = self._answer_commonality_topn(
                prompt, normalized, contracts, measure_block, measure_col,
                worst_high=worst_high)
            if topn is not None:
                return topn
            return None
        # shared group key (lot) and the detail fact + entity (tool)
        detail_block = next((b for b in facts if b != measure_block), None)
        if detail_block is None:
            return None
        shared = ({x.name for x in facts[measure_block].columns}
                  & {x.name for x in facts[detail_block].columns})
        # The yield measure is per-wafer, so commonality must group at the finest
        # shared grain (wafer) — at lot grain every lot uses every tool and the
        # signal washes out. Prefer wafer_id, else the prompt-mentioned key.
        group_key = ("wafer_id" if "wafer_id" in shared
                     else _pick_join_key(prompt, normalized, shared))
        detail_cols = [c.name for c in facts[detail_block].columns]
        # the shared *entity* is a tool/machine, NOT the group key (lot). Prefer a
        # tool-like column; fall back to a categorical dim that isn't the key.
        entity = _guess_col(detail_cols, ("tool", "機台", "設備", "equipment"))
        if not entity or entity == group_key:
            cand = _resolve_decomp_dimension(idx, prompt, normalized, contracts, detail_block)
            entity = cand if cand and cand != group_key else entity
        if not group_key or not entity or entity == group_key:
            return None
        try:
            mdf = materialize_dataframe(facts[measure_block])
            ddf = materialize_dataframe(facts[detail_block])
        except Exception:  # noqa: BLE001
            return None
        grp = mdf.groupby(group_key)[measure_col].mean()
        qualifying = set(grp[grp < threshold].index if op == "lt" else grp[grp > threshold].index)
        if not qualifying:
            msg = f"沒有 {measure_col} {'<' if op=='lt' else '>'} {threshold} 的 {group_key}。"
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=[msg], risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg, trust_notes=[msg], risk_level="low")
        table = commonality(ddf, entity, group_key, qualifying)
        if table is None or table.empty:
            return None
        top = table.iloc[0]
        sentence = (f"{len(qualifying)} 個不良 {group_key} 中，最常共同經過的「{entity}」是 "
                    f"{top[entity]}（{top['涉及批數']} 批，涵蓋率 {top['涵蓋率%']}%，lift {top.get('lift', '—')}）。")
        if "p_value" in table.columns:
            p = top["p_value"]
            sig = ("統計上顯著（p<0.05，這個共同性不太可能是巧合）" if p < 0.05
                   else f"但統計上不顯著（p={p}，可能是巧合，建議多收幾批再下結論）")
            sentence += f"Fisher 精確檢定 p={p}，{sig}。"
            # Round 144: actionable next-step so the engineer knows what to do next.
            if p < 0.05:
                sentence += (f"建議：優先排查 {top[entity]}（調 SPC/維護紀錄/recipe 與 chamber 狀態），"
                             f"並比對良率正常批是否也高度經過它以排除誤判。")
        notes = [f"Commonality：先以 {measure_col} {'<' if op=='lt' else '>'} {threshold} 篩 {group_key}，"
                 f"再於 {detail_block} 找共同 {entity}；以 Fisher 精確檢定評估顯著性（失敗×經過此機台 2×2）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                 trust_notes=notes, risk_level="low")

    def _answer_commonality_topn(
        self, prompt, normalized, contracts, measure_block, measure_col, *, worst_high,
    ) -> "NL2ProposalResult | None":
        """Round 140: TRUE commonality for "the worst-by-measure lots — which tool
        did they share?". Qualify the top/bottom quantile of lots by the measure,
        then run the lift+Fisher commonality on the tool column. The tool may be in
        the same fact (etch_tool_id in yield) or in the detail fact (moves)."""
        from ai4bi.analysis.crossfact import commonality
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        hay = f"{prompt.lower()} {normalized}"
        facts = {b: c for b, c in contracts.items()
                 if getattr(c, "block_type", None) in (
                     BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)}
        try:
            mdf = materialize_dataframe(contracts[measure_block])
        except Exception:  # noqa: BLE001
            return None
        # Prefer the finest grain (wafer): the measure (defect/yield) is per-wafer
        # and at lot grain a lot has wafers on BOTH etch tools, so commonality
        # washes out (lift→1). Use wafer_id when present.
        key = "wafer_id" if "wafer_id" in mdf.columns else (
            "lot_id" if "lot_id" in mdf.columns else None)
        if key is None:
            return None
        # find the tool column + which fact holds it; prefer the prompt's hint
        want_etch = "etch" in hay
        tool_block = tool_col = None
        for bid in ([measure_block] + [b for b in facts if b != measure_block]):
            cols = [x.name for x in facts[bid].columns]
            cand = (_guess_col(cols, ("etch_tool", "etch")) if want_etch else None) \
                or _guess_col(cols, ("tool", "機台", "設備", "equipment"))
            if cand and cand != key and (key in cols):
                tool_block, tool_col = bid, cand
                break
        if tool_col is None:
            return None
        # qualify the worst lots by the measure (top quantile of defect, or bottom of yield)
        per_lot = mdf.groupby(key)[measure_col].sum() if "defect" in measure_col.lower() \
            else mdf.groupby(key)[measure_col].mean()
        if per_lot.empty:
            return None
        n_lots = len(per_lot)
        k = max(3, round(n_lots * 0.2))  # top ~20%, at least 3
        worst = (per_lot.sort_values(ascending=not worst_high).head(k))
        qualifying = set(worst.index)
        try:
            tdf = materialize_dataframe(contracts[tool_block])
        except Exception:  # noqa: BLE001
            return None
        table = commonality(tdf, tool_col, key, qualifying)
        if table is None or table.empty:
            return None
        top = table.iloc[0]
        kind = "缺陷最多" if worst_high else "良率最低"
        sentence = (f"{kind}的前 {len(qualifying)} 個 {key} 中，最常共同經過的「{tool_col}」是 "
                    f"{top[tool_col]}（{top['涉及批數']} 批，涵蓋率 {top['涵蓋率%']}%，lift {top.get('lift','—')}）。")
        if "p_value" in table.columns:
            p = top["p_value"]
            sig = ("統計上顯著（p<0.05，不太可能是巧合）" if p < 0.05
                   else f"但統計上不顯著（p={p}，建議多收幾批）")
            sentence += f"Fisher 精確檢定 p={p}，{sig}。"
        notes = [f"Commonality（top-N）：依 {measure_col} 取最{'高' if worst_high else '低'} "
                 f"~20%（{len(qualifying)} 個 {key}）為不良群，於 {tool_block} 找共同 {tool_col}，"
                 f"lift + Fisher 檢定。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                 trust_notes=notes, risk_level="low")

    def _answer_crossfact(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 116: cross-fact analytics (correlation / cohort / ratio).

        Aligns two facts on a shared key and answers questions that span them —
        "is high queue time linked to low yield (by lot)?", "worst-cycle-time 20%
        of lots — yield drop?", "yield per rework by product". Returns None when
        it isn't a resolvable two-fact question.
        """
        if not contracts:
            return None
        from ai4bi.blocks.contracts import BlockType
        facts = {b: c for b, c in contracts.items()
                 if getattr(c, "block_type", None) in (
                     BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)}
        hay0 = f"{prompt.lower()} {normalized}"
        is_corr0 = any(t in hay0 for t in ("關聯", "相關", "關係", "correlat", "linked", "有沒有關"))
        # Round 121: same-fact correlation — two numeric columns in ONE fact
        # (e.g. defect_density vs yield, both in fab_wafer_yield). Checked first.
        if is_corr0:
            from ai4bi.analysis.crossfact import correlate_facts as _corr
            from ai4bi.blocks.datastore import materialize_dataframe as _mat
            for bid, c in facts.items():
                two = _resolve_two_numeric_cols(prompt, normalized, c)
                # Round 129: two columns that share a token (capacity_moves vs
                # actual_moves_ref) aren't two distinct concepts — skip so a genuinely
                # cross-fact question (cycle@yield vs move@move) reaches the join path.
                if len(two) == 2:
                    t0 = set(re.split(r"[_\s]+", two[0].lower())) - _GENERIC_NUM_TOKENS
                    t1 = set(re.split(r"[_\s]+", two[1].lower())) - _GENERIC_NUM_TOKENS
                    if t0 & t1:
                        continue
                if len(two) == 2:
                    try:
                        df1 = _mat(c)
                    except Exception:  # noqa: BLE001
                        continue
                    stat = _corr(df1, two[0], two[1])
                    if stat is None:
                        continue
                    sentence = (f"「{two[0]}」與「{two[1]}」（同表 {bid}，n={stat['n']}）"
                                f"相關係數 r={stat['r']}（{stat['direction']}相關，{stat['strength']}）。"
                                f"註：相關不等於因果，可能有共同潛在因素（如同一機台/時段）；"
                                f"要確認因果需控制其他變因或做實驗。")
                    notes = [f"同表相關：直接以每列計算 Pearson 相關（相關≠因果）。來源：{bid}。"]
                    intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                      trust_notes=notes, risk_level="low")
                    return NL2ProposalResult(intent=intent, message=sentence,
                                             result_table=df1[two].head(50),
                                             trust_notes=notes, risk_level="low")
        # Round 129: same-fact cohort — bucket rows by one column's quantile and
        # compare another column across buckets when BOTH live in one fact
        # ("cycle time 最久的前 20% 批號的良率掉多少" → cycle & yield, both in yield).
        is_cohort0 = bool(re.search(r"前\s*\d+\s*%|後\s*\d+\s*%|\d+\s*%|分位|cohort|quantile|四分位", hay0))
        if is_cohort0:
            from ai4bi.analysis.crossfact import cohort_by_quantile as _cohort
            from ai4bi.blocks.datastore import materialize_dataframe as _mat
            _OUTCOME = ("yield", "良率", "pct", "rate", "defect", "缺陷", "good", "bad", "報廢")
            for bid, c in facts.items():
                two = _resolve_two_numeric_cols(prompt, normalized, c)
                if len(two) != 2:
                    continue
                t0 = set(re.split(r"[_\s]+", two[0].lower())) - _GENERIC_NUM_TOKENS
                t1 = set(re.split(r"[_\s]+", two[1].lower())) - _GENERIC_NUM_TOKENS
                if t0 & t1:
                    continue
                outcome = next((x for x in two if any(o in x.lower() for o in _OUTCOME)), None)
                bucket = next((x for x in two if x != outcome), None)
                if outcome is None or bucket is None:
                    bucket, outcome = two[0], two[1]
                try:
                    df1 = _mat(c)
                except Exception:  # noqa: BLE001
                    continue
                table = _cohort(df1, bucket, outcome, q=5)
                if table is None or table.empty:
                    continue
                ocol = next((cc for cc in table.columns if cc.startswith("平均")), None)
                if ocol is not None and len(table) >= 2:
                    worst, best = float(table.iloc[-1][ocol]), float(table.iloc[0][ocol])
                    sentence = (f"依「{bucket}」分位分 {len(table)} 組（同表 {bid}）："
                                f"{bucket} 最高組平均{outcome} {worst} vs 最低組 {best}"
                                f"（差 {round(best - worst, 2)}）。")
                else:
                    sentence = f"依「{bucket}」分位分組，比較各組「{outcome}」（同表 {bid}）。"
                notes = [f"同表 cohort：以 {bucket} 分位分桶，平均 {outcome}。來源：{bid}。"]
                intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                  trust_notes=notes, risk_level="low")
                return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                         trust_notes=notes, risk_level="low")
        if len(facts) < 2:
            return None
        # A numeric column the prompt references, per fact.
        cols = {}
        for bid, c in facts.items():
            col = _resolve_numeric_column(prompt, normalized, c)
            if col:
                cols[bid] = col
        if len(cols) < 2:
            return None
        (ba, ca), (bb, cb) = list(cols.items())[:2]
        shared = ({x.name for x in facts[ba].columns}
                  & {x.name for x in facts[bb].columns})
        key = _pick_join_key(prompt, normalized, shared)
        if key is None:
            return None

        def _agg(col: str) -> str:
            low = col.lower()
            return "AVG" if any(t in low for t in ("pct", "rate", "ratio", "_hr", "_min", "avg", "yield", "density")) else "SUM"

        from ai4bi.analysis.crossfact import align_two_facts, cohort_by_quantile, correlate_facts
        try:
            merged = align_two_facts(
                contracts, block_a=ba, col_a=ca, agg_a=_agg(ca), alias_a=ca,
                block_b=bb, col_b=cb, agg_b=_agg(cb), alias_b=cb, join_key=key)
        except Exception:  # noqa: BLE001
            return None
        if merged is None or merged.empty:
            return None

        hay = f"{prompt.lower()} {normalized}"
        is_cohort = bool(re.search(r"前\s*\d+\s*%|\d+\s*%|分位|cohort|quantile|四分位", hay))
        is_corr = any(t in hay for t in ("關聯", "相關", "關係", "correlat", "linked", "有沒有關"))

        if is_corr and not is_cohort:
            stat = correlate_facts(merged, ca, cb)
            if stat is None:
                # degenerate: a constant column has no variance to correlate. Report
                # it honestly (with the aligned table) instead of declining silently.
                const = next((col for col in (ca, cb)
                              if col in merged.columns and merged[col].nunique(dropna=True) < 2), None)
                if const is not None:
                    sentence = (f"無法計算相關：「{const}」在每個 {key} 上皆相同"
                                f"（值={merged[const].dropna().iloc[0] if not merged[const].dropna().empty else 'NA'}，"
                                f"無變異），因此與「{cb if const == ca else ca}」無相關性可言。")
                    notes = [f"跨表分析：各自彙總到 {key} 後對齊；{const} 無變異。"]
                    intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                      trust_notes=notes, risk_level="low")
                    return NL2ProposalResult(intent=intent, message=sentence, result_table=merged,
                                             trust_notes=notes, risk_level="low")
                return None
            sentence = (f"「{ca}」與「{cb}」（依 {key} 對齊，n={stat['n']}）相關係數 r={stat['r']}"
                        f"（{stat['direction']}相關，{stat['strength']}）。"
                        f"註：相關不等於因果，可能有共同潛在因素；要確認需控制其他變因或實驗驗證。")
            notes = [f"跨表分析：各自彙總到 {key} 後對齊計算 Pearson 相關（非明細 join，相關≠因果）。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=sentence, result_table=merged,
                                     trust_notes=notes, risk_level="low")
        if is_cohort:
            # bucket by the move-side metric (cycle/queue proxy), outcome = the other
            table = cohort_by_quantile(merged, ca, cb, q=5)
            if table is None or table.empty:
                return None
            ocol = next((c for c in table.columns if c.startswith("平均")), None)
            if ocol is not None and len(table) >= 2:
                worst = float(table.iloc[-1][ocol])  # highest bucket of ca
                best = float(table.iloc[0][ocol])
                sentence = (f"依「{ca}」分位分 {len(table)} 組：{ca} 最高組的平均{cb} {worst} "
                            f"vs 最低組 {best}（差 {round(best - worst, 2)}）。")
            else:
                sentence = f"依「{ca}」分位分組，看各組「{cb}」（共 {len(table)} 組）。"
            notes = [f"跨表 cohort：依 {key} 對齊後，用 {ca} 分位分桶，平均 {cb}。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                     trust_notes=notes, risk_level="low")
        # default: ratio A/B per key
        merged = merged.copy()
        rcol = f"{ca}/{cb}"
        merged[rcol] = (merged[ca] / merged[cb].replace(0, float("nan"))).round(3)
        ranked = merged.dropna(subset=[rcol]).sort_values(rcol, ascending=False)
        if not ranked.empty:
            hi = ranked.iloc[0]
            sentence = (f"「{ca} ÷ {cb}」依「{key}」：最高 {hi[key]}（{hi[rcol]}），"
                        f"共 {len(merged)} 列。")
            merged = ranked
        else:
            sentence = f"依「{key}」計算「{ca} ÷ {cb}」（跨表比值，共 {len(merged)} 列）。"
        notes = [f"跨表比值：各自彙總到 {key} 後相除（非明細 join）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=merged,
                                 trust_notes=notes, risk_level="low")

    def _answer_matrix(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 118: 2-dimension cross-tab ("各 etch 機台在不同 product 上的良率").

        Groups a metric by two categorical dimensions and pivots into a matrix
        (dim1 rows × dim2 columns). Returns None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        idx = SchemaIndex.build(contracts)
        _conf = any(t in f"{prompt.lower()} {normalized}" for t in (
            "混淆", "搞混", "誤判", "認錯", "預測成", "搞錯成", "confusion"))
        match = idx.best_metric_match(prompt, normalized)
        # Round 186 (CV S9): a bare confusion question ("哪兩類最常搞混") names no
        # metric — default to a count metric on whichever block carries the
        # true_class × pred_class pair, so it still produces the confusion matrix.
        if match is None and _conf:
            # "搞混/誤判/認錯" focuses on the OFF-diagonal (errors) → error_count;
            # a plain "混淆矩陣" wants the full matrix incl. the diagonal → pred_count.
            _err_focus = any(t in f"{prompt.lower()} {normalized}"
                             for t in ("誤判", "搞混", "認錯", "搞錯成"))
            _prefer = ("error_count", "pred_count") if _err_focus else ("pred_count", "error_count")
            for _bid, _c in contracts.items():
                _cn = {x.name for x in getattr(_c, "columns", [])}
                if {"true_class", "pred_class"} <= _cn:
                    _names = {m.name for m in getattr(_c, "metrics", [])}
                    _pick = next((p for p in _prefer if p in _names), None)
                    if _pick is not None:
                        match = MetricEntry(_bid, _pick, _pick.replace("_", " ").title())
                        break
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        dims = _resolve_n_dims(idx, prompt, normalized, contracts, block_id, n=2)
        # Round 186 (CV S9): a confusion question ("最常被誤判成哪類 / 搞混") is a
        # true_class × pred_class cross-tab — default those two axes when the block
        # has them and the prompt didn't name two dims explicitly.
        if len(dims) < 2 and _conf:
            _cols = {c.name for c in getattr(contracts.get(block_id), "columns", [])}
            if {"true_class", "pred_class"} <= _cols:
                dims = ["true_class", "pred_class"]
        if len(dims) < 2:
            return None
        d1, d2 = dims[0], dims[1]

        from ai4bi.query_spec import BlockRef, DimensionRef, VisualQuerySpec
        spec = VisualQuerySpec(
            spec_id=f"mtx_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, d1, d1), DimensionRef(block_id, d2, d2)],
            inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or alias not in df.columns:
            return None
        try:
            import pandas as pd
            pivot = pd.pivot_table(df, index=d1, columns=d2, values=alias, aggfunc="first").round(2)
            pivot = pivot.reset_index()
        except Exception:  # noqa: BLE001
            return None
        # headline BOTH extremes — the combos to watch — plus the population N.
        extremes_txt = ""
        try:
            numcols = [c for c in pivot.columns if c != d1]
            stacked = pivot.set_index(d1)[numcols].stack()
            if not stacked.empty:
                (lri, lci), lmv = stacked.idxmin(), stacked.min()
                (hri, hci), hmv = stacked.idxmax(), stacked.max()
                extremes_txt = (f"最高：{hri} × {hci} = {round(float(hmv),2)}；"
                                f"最低：{lri} × {lci} = {round(float(lmv),2)}。")
        except Exception:  # noqa: BLE001
            pass
        n_rows = None
        try:
            from ai4bi.blocks.datastore import materialize_dataframe
            n_rows = len(materialize_dataframe(contracts[block_id]))
        except Exception:  # noqa: BLE001
            n_rows = None
        pop = f"（母體 {n_rows} 列 @ {block_id}）" if n_rows else ""
        sentence = f"「{alias}」交叉表：{d1}（列）× {d2}（欄）。{extremes_txt}{pop}"
        notes = [f"依「{d1}」×「{d2}」交叉彙總「{alias}」（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=pivot,
                                 trust_notes=notes, risk_level="low")

    def _answer_multi_filter(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 118: multi-condition filtered metric ("夜班 Hot 批 LAM 機台 rework 的 move 數").

        Scans each fact for categorical VALUES (and boolean flags) named in the
        prompt, ANDs them into filters, and returns the requested metric. Returns
        None when fewer than two conditions resolve (let simpler intents handle).
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        from ai4bi.query_spec import BlockRef, FilterOperator, FilterSpec, VisualQuerySpec
        idx = SchemaIndex.build(contracts)
        hay = f"{prompt.lower()} {normalized}"
        # ZH shift synonyms (values are Day/Night)
        _SHIFT = {"夜班": "Night", "晚班": "Night", "日班": "Day", "白班": "Day"}

        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            metric = idx.best_metric_match(prompt, normalized)
            if metric is None or metric.block_id != bid:
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            filters = []
            str_cols = [col.name for col in c.columns
                        if col.data_type in ("string", "str", "object")]
            for col in str_cols:
                vals = {str(v) for v in df[col].dropna().unique()} if col in df.columns else set()
                hit = None
                for v in vals:
                    if v and v.lower() in hay:
                        hit = v
                        break
                if hit is None:  # ZH shift synonyms
                    for zh, en in _SHIFT.items():
                        if zh in hay and en in vals:
                            hit = en
                            break
                if hit is not None:
                    filters.append(FilterSpec(bid, col, FilterOperator.eq, hit, False))
            # boolean flags
            flag_cols = [col.name for col in c.columns if col.name.endswith("_flag")]
            for fc in flag_cols:
                word = fc.replace("_flag", "")
                zh = {"rework": "重工", "hold": "保留"}.get(word, "")
                if word in hay or (zh and zh in hay):
                    filters.append(FilterSpec(bid, fc, FilterOperator.eq, 1, False))
            # Round 139: honest partial filtering. If only one condition resolves
            # on the metric's fact but the prompt clearly named another that maps
            # to a column NOT on this fact (e.g. "ETCH 區" → area lives in moves,
            # not in the yield fact), apply what we can and DISCLOSE the gap,
            # rather than silently returning an unfiltered overall number.
            unresolved_note = None
            if len(filters) == 1:
                this_cols = {col.name for col in c.columns}
                area_vals = set()
                for bb, cc in contracts.items():
                    if "area" in {x.name for x in getattr(cc, "columns", [])}:
                        try:
                            area_vals |= {str(v).lower() for v in
                                          materialize_dataframe(cc)["area"].dropna().unique()}
                        except Exception:  # noqa: BLE001
                            pass
                named_area = any(a in hay for a in area_vals) or "區" in hay
                if named_area and "area" not in this_cols:
                    unresolved_note = ("註：『區/area』欄位在 move fact，不在良率資料"
                                       f"（{bid}），無法依區別篩選；已套用其餘條件。"
                                       "若要依區看，請改問 move 類指標或 etch 機台別。")
            if len(filters) < 2 and unresolved_note is None:
                return None
            # A flag word (rework/hold) used as a FILTER shouldn't also be the
            # target metric — '...rework 的 move 數' wants move_count. Re-resolve
            # the metric with filtered flag words stripped out. (Round 118)
            flag_words = [f.column_name.replace("_flag", "") for f in filters
                          if f.column_name.endswith("_flag")]
            if flag_words and any(w in metric.metric_name for w in flag_words):
                cleaned = hay
                for w in flag_words:
                    cleaned = cleaned.replace(w, " ").replace(
                        {"rework": "重工", "hold": "保留"}.get(w, w), " ")
                alt = idx.best_metric_match(cleaned, cleaned)
                if alt is not None and alt.block_id == bid:
                    metric = alt
            spec = VisualQuerySpec(
                spec_id=f"mf_{metric.metric_name}", block_refs=[BlockRef(bid)],
                metrics=[MetricRef(bid, metric.metric_name, metric.alias)],
                filters=filters, inherit_global_filter=False)
            try:
                res = executor.run(spec)
            except Exception:  # noqa: BLE001
                return None
            val = _first_scalar(res, metric.alias)
            conds = "、".join(f"{f.column_name}={f.value}" for f in filters)
            if val is None:
                sentence = f"在條件（{conds}）下沒有符合的資料（{metric.alias} = 0）。"
                val = 0
            else:
                sentence = (f"在條件（{conds}）下，{metric.alias} = "
                            f"{_format_metric_value(val, _metric_unit(contracts, bid, metric.metric_name))}。")
            if unresolved_note:
                sentence = f"{sentence}{unresolved_note}"
            notes = [f"多條件 AND 篩選後彙總（治理查詢路徑），來源：{bid}。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            answer = DirectAnswer(question=prompt.strip(), metric_block_id=bid,
                                  metric_name=metric.metric_name, metric_alias=metric.alias,
                                  sentence=sentence, value=val, trust_notes=notes)
            return NL2ProposalResult(intent=intent, message=sentence, direct_answer=answer,
                                     trust_notes=notes, risk_level="low")
        return None

    def _answer_breakdown(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 114: plain "metric BY dimension" breakdown ("各製程站的移動次數").

        Like ranking but without a superlative — groups a metric by a categorical
        dimension and returns every group (sorted desc). Returns None to fall
        through when no metric/dimension resolves.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        # Round 127: if the prompt explicitly names categorical VALUES (Hot/Normal),
        # group by the column that holds them — a stronger signal than a classifier
        # keyword ('批' would otherwise resolve lot_id). Else resolve by keyword.
        dim_col = (_column_holding_values(prompt, normalized, contracts, block_id)
                   or _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id))
        if dim_col is None:
            return None
        # Round 120: share-of-total only makes sense on an ADDITIVE measure; if a
        # share question resolved a rate/pct/density metric, switch to the additive
        # sibling (defect_density_pct → defect_die) so the % column is meaningful.
        hay0 = f"{prompt.lower()} {normalized}"
        is_share0 = any(t in hay0 for t in ("占比", "佔比", "比重", "占總", "佔總", "佔全", "占全", "佔多少", "佔了"))
        # A share resolved on a non-additive metric (rate/pct OR avg_/max_/min_) must
        # switch to its additive sibling so the % column is meaningful:
        #   defect_density_pct → defect_die,  avg_queue_time_hr → total_queue_hr.
        non_additive = any(t in metric_name.lower() for t in ("rate", "pct", "ratio", "density")) or \
            metric_name.lower().startswith(("avg_", "max_", "min_", "mean_"))
        if is_share0 and non_additive:
            drop = {"pct", "rate", "ratio", "density", "avg", "max", "min", "mean", "total"}
            base = set(re.split(r"[_\s]+", metric_name.lower())) - drop
            best_sib = None
            for mm in idx._metrics.values():
                nm = mm.metric_name.lower()
                if mm.block_id != block_id or nm == metric_name.lower():
                    continue
                if any(t in nm for t in ("rate", "pct", "ratio", "density")):
                    continue
                overlap = base & (set(re.split(r"[_\s]+", nm)) - drop)
                if not overlap:
                    continue
                # prefer an explicit total_/sum sibling
                score = len(overlap) + (1 if nm.startswith(("total_", "sum_")) else 0)
                if best_sib is None or score > best_sib[0]:
                    best_sib = (score, mm.metric_name, mm.alias)
            if best_sib is not None:
                metric_name, alias = best_sib[1], best_sib[2]

        from ai4bi.query_spec import BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec
        spec = VisualQuerySpec(
            spec_id=f"by_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, dim_col, dim_col)],
            sort=[SortSpec(alias, SortDirection.desc)], inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None
        # Round 120: a "占比/share" breakdown gets an inline 佔總比% column.
        hay = f"{prompt.lower()} {normalized}"
        is_share = any(t in hay for t in ("占比", "佔比", "比重", "占總", "佔總", "佔全", "占全",
                                          "佔多少", "占多少", "佔了", "share", "%", "百分比"))
        if is_share and alias in df.columns:
            total = float(df[alias].sum())
            if total:
                df = df.copy()
                df["佔總比%"] = (df[alias] / total * 100).round(1)
            top = df.iloc[0]
            sentence = (f"「{alias}」依「{dim_col}」占比：最高 {top[dim_col]}"
                        + (f"（{top['佔總比%']}%）。" if "佔總比%" in df.columns else "。"))
        else:
            top = df.iloc[0]
            tv = top[alias] if alias in df.columns else top.iloc[-1]
            tv = round(float(tv), 2) if isinstance(tv, (int, float)) else tv
            sentence = (f"「{alias}」依「{dim_col}」分組（共 {len(df)} 組）："
                        f"最高 {top[dim_col]}（{tv}）。")
        # Round 139: per-group population when asked ("各產品的良率，分別用幾片算的").
        if any(t in f"{prompt.lower()} {normalized}" for t in (
                "幾片", "幾筆", "幾個", "分別", "母體", "幾批", "how many", "based on")):
            try:
                from ai4bi.blocks.datastore import materialize_dataframe
                raw = materialize_dataframe(contracts[block_id])
                if dim_col in raw.columns:
                    keycol = "wafer_id" if "wafer_id" in raw.columns else None
                    if keycol:
                        cnt = raw.groupby(dim_col)[keycol].nunique().rename("片數")
                        unit_lbl = "片數"
                    else:
                        cnt = raw.groupby(dim_col).size().rename("筆數")
                        unit_lbl = "筆數"
                    df = df.merge(cnt, left_on=dim_col, right_index=True, how="left")
                    sentence = f"{sentence}（已附各組{unit_lbl}；母體 {len(raw)} 列 @ {block_id}）"
            except Exception:  # noqa: BLE001
                pass
        notes = [f"依「{dim_col}」分組彙總「{alias}」（治理查詢路徑），來源：{block_id}。"]
        self._remember(block_id=block_id, metric_name=metric_name, alias=alias,
                       dim_col=dim_col, kind="breakdown")
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    # ------------------------------------------------------------------ #
    # Round 136: conversational follow-up (scope inheritance)
    # ------------------------------------------------------------------ #

    def _remember(self, **ctx) -> None:
        """Stash the last resolved analysis so a follow-up can inherit its scope."""
        mem = getattr(self, "_convo_mem", None)
        if mem is not None:
            mem["last"] = ctx

    def _answer_followup_scope(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 136: a follow-up like "只看 ETCH 呢？" inherits the prior turn's
        metric + dimension and just narrows the scope to one value. Without this,
        the prompt is an island and falls through to "select a visual first"."""
        executor = getattr(self, "_executor", None)
        mem = getattr(self, "_convo_mem", {})
        last = mem.get("last") if isinstance(mem, dict) else None
        if executor is None or not contracts or not last:
            return None
        block_id = last.get("block_id")
        metric_name, alias = last.get("metric_name"), last.get("alias")
        dim_col = last.get("dim_col")
        if not block_id or not metric_name or block_id not in contracts:
            return None
        # candidate value = the follow-up minus the refinement cue words
        cand = _extract_followup_value(prompt)
        if not cand:
            return None
        # resolve which categorical column holds the candidate (prefer prior dim)
        from ai4bi.blocks.datastore import materialize_dataframe
        try:
            df0 = materialize_dataframe(contracts[block_id])
        except Exception:  # noqa: BLE001
            return None
        col, value = None, None
        search_cols = ([dim_col] if dim_col and dim_col in df0.columns else []) + \
            [c for c in df0.columns if df0[c].dtype == object and c != dim_col]
        for c in search_cols:
            vals = {str(x) for x in df0[c].dropna().unique()}
            hit = next((v for v in vals if v and (v.lower() == cand.lower()
                        or cand.lower() in v.lower() or v.lower().startswith(cand.lower()))), None)
            if hit:
                col, value = c, hit
                break
        if col is None:
            return None
        from ai4bi.query_spec import (
            BlockRef, DimensionRef, FilterOperator, FilterSpec, SortDirection,
            SortSpec, VisualQuerySpec)
        gdim = dim_col if dim_col and dim_col in df0.columns else col
        spec = VisualQuerySpec(
            spec_id=f"followup_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, gdim, gdim)],
            filters=[FilterSpec(block_id=block_id, column_name=col,
                                operator=FilterOperator.eq, value=value)],
            sort=[SortSpec(alias, SortDirection.desc)], inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None
        if alias in df.columns:
            v = df.iloc[0][alias]
            v = round(float(v), 2) if isinstance(v, (int, float)) else v
            sentence = f"（延續上一題）只看「{value}」：「{alias}」為 {v}。"
        else:
            sentence = f"（延續上一題）已篩選 {col}={value}。"
        notes = [f"沿用前一輪分析（{alias} 依 {gdim}），新增篩選 {col}={value}。來源：{block_id}。"]
        # keep memory so a further follow-up still works
        self._remember(block_id=block_id, metric_name=metric_name, alias=alias,
                       dim_col=gdim, kind="followup")
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_category_compare(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 129: compare a metric across a fab category (rework vs non-rework,
        Hot vs Normal priority, day vs night) when the column's values are not both
        literally named — keyword maps to the column, then breaks the metric down."""
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        col = _keyword_category_column(prompt, normalized, contracts, block_id)
        if col is None:
            return None
        from ai4bi.query_spec import BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec
        spec = VisualQuerySpec(
            spec_id=f"catcmp_{metric_name}_{col}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, col, col)],
            sort=[SortSpec(alias, SortDirection.desc)], inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or col not in df.columns or alias not in df.columns:
            return None
        disp = df.copy()
        # readable labels for boolean flag columns (0/1 → 否/是)
        uniq = {str(v) for v in disp[col].unique()}
        if uniq <= {"0", "1", "0.0", "1.0", "True", "False"}:
            lab = {"1": "是", "1.0": "是", "True": "是", "0": "否", "0.0": "否", "False": "否"}
            disp[col] = disp[col].astype(str).map(lambda v: lab.get(v, v))
        hi, lo = disp.iloc[0], disp.iloc[-1]
        hv, lv = float(hi[alias]), float(lo[alias])
        diff = ((hv - lv) / abs(lv) * 100) if lv else None
        msg = (f"「{alias}」依「{col}」比較（共 {len(disp)} 組）：{hi[col]} {round(hv, 2)} 最高、"
               f"{lo[col]} {round(lv, 2)} 最低"
               + (f"，相差 {diff:.1f}%。" if diff is not None else "。"))
        notes = [f"依「{col}」分組比較「{alias}」（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, result_table=disp,
                                 trust_notes=notes, risk_level="low")

    def _answer_subgroup_compare(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 137: compare a MEASURE across a binary/categorical FLAG, aligning
        by lot when the flag and the measure live in different facts (rework/hold
        in moves, yield/cycle in yield). Prevents the silent-wrong overall number."""
        if not contracts:
            return None
        from ai4bi.blocks.datastore import materialize_dataframe
        import pandas as _pd
        hay = f" {prompt.lower()} {normalized} "
        # resolve flag column + which fact holds it
        flag_col = flag_block = None
        for kws, col in _SUBGROUP_FLAGS:
            if any(k in hay for k in kws):
                for bid, c in contracts.items():
                    if col in {x.name for x in getattr(c, "columns", [])}:
                        flag_col, flag_block = col, bid
                        break
            if flag_col:
                break
        # resolve measure column + which fact holds it (first preference that exists)
        meas_col = meas_block = None
        for kws, cands in _SUBGROUP_MEASURES:
            if any(k in hay for k in kws):
                for cand in cands:
                    for bid, c in contracts.items():
                        if cand in {x.name for x in getattr(c, "columns", [])}:
                            meas_col, meas_block = cand, bid
                            break
                    if meas_col:
                        break
            if meas_col:
                break
        # Round 184 (S14): a shift comparison with no measure named ("白天班 vs 夜班
        # 比較") defaults to wait time — the metric a fab engineer means by default.
        if flag_col == "shift" and not meas_col:
            for bid, c in contracts.items():
                if "queue_time_hr" in {x.name for x in getattr(c, "columns", [])}:
                    meas_col, meas_block = "queue_time_hr", bid
                    break
        if not flag_col or not meas_col:
            return None
        try:
            fdf = materialize_dataframe(contracts[flag_block])
            mdf = materialize_dataframe(contracts[meas_block])
        except Exception:  # noqa: BLE001
            return None
        is_binary = flag_col in ("rework_flag", "hold_flag")
        higher_better = "yield" in meas_col.lower()
        # Round 178 (S5): a yield ratio must be aggregated WEIGHTED (SUM good /
        # SUM tested), not mean(yield_pct) — correct when die counts differ per
        # wafer. Only the same-fact case (e.g. product_family in the yield fact);
        # cross-fact alignment keeps the mean fallback.
        is_wy = (higher_better and flag_block == meas_block
                 and {"good_die", "tested_die"} <= set(getattr(fdf, "columns", [])))

        if flag_block == meas_block:
            work = fdf[[flag_col] + (["good_die", "tested_die"] if is_wy else [meas_col])].copy()
        else:
            if "lot_id" not in fdf.columns or "lot_id" not in mdf.columns:
                return None
            agg_flag = fdf.groupby("lot_id")[flag_col].max() if is_binary \
                else fdf.groupby("lot_id")[flag_col].agg(lambda s: s.mode().iloc[0] if len(s.mode()) else s.iloc[0])
            agg_meas = mdf.groupby("lot_id")[meas_col].mean()
            work = _pd.concat([agg_flag, agg_meas], axis=1, join="inner").reset_index()
        work = work.dropna(subset=[flag_col] + (["good_die", "tested_die"] if is_wy else [meas_col]))
        if work.empty:
            return None
        if is_binary:
            work[flag_col] = work[flag_col].map(lambda v: "有" if float(v) > 0 else "無")
        if is_wy:
            grp = work.groupby(flag_col).agg(
                _g=("good_die", "sum"), _t=("tested_die", "sum"), count=(flag_col, "size")).reset_index()
            grp["mean"] = (grp["_g"] / grp["_t"].where(grp["_t"] != 0) * 100.0)
            grp = grp[[flag_col, "mean", "count"]]
        else:
            grp = work.groupby(flag_col)[meas_col].agg(["mean", "count"]).reset_index()
        if len(grp) < 2:
            # Round 142: cross-fact attribution washout — e.g. a wafer's yield can't
            # be pinned to one vendor because it passes through many vendors' tools,
            # so vendor-per-lot collapses to a single value. Say so honestly instead
            # of returning None (which would fall through to a misleading overall).
            if flag_block != meas_block:
                msg = (f"無法把「{meas_col}」乾淨地歸因到單一「{flag_col}」："
                       f"一個 {meas_block} 單位（如晶圓）會經過多個 {flag_col}（{flag_block}），"
                       f"以 lot 對齊後幾乎都落在同一個 {flag_col}，比較會失真。"
                       f"建議改用 commonality：低良率晶圓是否較常經過某「{flag_col}」的機台。")
                notes = [msg]
                intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                  trust_notes=notes, risk_level="medium")
                return NL2ProposalResult(intent=intent, message=msg, trust_notes=notes,
                                         risk_level="medium")
            return None
        grp = grp.sort_values("mean", ascending=not higher_better).reset_index(drop=True)
        grp["mean"] = grp["mean"].round(2)
        a, b = grp.iloc[0], grp.iloc[-1]
        unit = "%" if "yield" in meas_col.lower() or "pct" in meas_col.lower() else ""
        diff = round(abs(float(a["mean"]) - float(b["mean"])), 2)
        worse_word = "差" if higher_better else "高/長"
        # the flagged subgroup ("有") — does it do worse?
        flagged = grp[grp[flag_col].astype(str).isin(["有", "Day", "Night"])]
        out = grp.rename(columns={flag_col: flag_col, "mean": f"平均{meas_col}", "count": "lot數"})
        msg = (f"依「{flag_col}」比較「{meas_col}」：{a[flag_col]} {a['mean']}{unit}"
               f"（{int(a['count'])} lot）vs {b[flag_col]} {b['mean']}{unit}"
               f"（{int(b['count'])} lot），相差 {diff}{unit}。")
        if is_binary:
            hv = grp[grp[flag_col] == "有"]["mean"]
            nv = grp[grp[flag_col] == "無"]["mean"]
            if not hv.empty and not nv.empty:
                hv0, nv0 = float(hv.iloc[0]), float(nv.iloc[0])
                if higher_better:
                    verdict = "較差" if hv0 < nv0 else "沒有比較差，反而較好"
                else:
                    verdict = "較高/較長" if hv0 > nv0 else "沒有比較高/長"
                msg = (f"有{flag_col.replace('_flag','')} 的批「{meas_col}」為 {round(hv0,2)}{unit}、"
                       f"無的為 {round(nv0,2)}{unit}（相差 {round(abs(hv0-nv0),2)}{unit}）"
                       f"→ 有此狀況者{verdict}。")
        # Round 140: significance + small-sample honesty. A 0.4% gap on n=3 isn't a
        # finding; run Welch t-test and flag tiny groups so users don't over-read.
        min_n = int(grp["count"].min())
        try:
            from scipy.stats import ttest_ind as _tt
            g0 = grp.iloc[0][flag_col]
            v0 = work[work[flag_col] == g0][meas_col].astype(float)
            v1 = work[work[flag_col] != g0][meas_col].astype(float)
            if len(v0) >= 2 and len(v1) >= 2:
                p = float(_tt(v0, v1, equal_var=False).pvalue)
                if p < 0.05:
                    msg += f"（Welch t 檢定 p={round(p,3)}，差異統計上顯著）"
                else:
                    msg += (f"（Welch t 檢定 p={round(p,3)}，差異不顯著"
                            f"{'，且樣本偏少' if min_n < 5 else ''}，這個差距可能只是雜訊）")
        except Exception:  # noqa: BLE001
            if min_n < 5:
                msg += f"（注意：較小的一組僅 {min_n} 個樣本，差距未必有意義）"
        method = ("同表分組比較" if flag_block == meas_block
                  else f"以 lot 對齊跨表（{flag_block} 的 {flag_col} × {meas_block} 的 {meas_col}）")
        notes = [f"子群比較：{method}；各組以平均彙總並列出 lot 數，並以 Welch t 檢定評估顯著性。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, result_table=out,
                                 trust_notes=notes, risk_level="low")

    def _answer_trend_direction(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 138: is a metric trending better or worse over recent weeks?
        Computes the metric by week and reports direction (slope + recent vs early)."""
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            # Round 182 (S1): a bare "有在下降嗎 / 還在掉嗎" names no measure — in a
            # yield-centric fab report it means yield. Retry with an implicit yield
            # measure — UNLESS another metric is named (e.g. "OEE 趨勢如何"), in
            # which case answering with yield would be answering the wrong question.
            _hay_t = f"{prompt.lower()} {normalized}"
            _other_metric = any(w in _hay_t for w in (
                "oee", "可用率", "稼動", "利用率", "queue", "等待", "cycle", "週期",
                "產能", "throughput", "move", "移動", "wip", "uptime", "稼動率",
                "設備效率", "綜合效率", "總合效率"))
            if not _other_metric:
                match = idx.best_metric_match("良率 yield", "liang lv yield")
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        date_col = _find_date_column(contracts, block_id)
        if date_col is None:
            return None
        from ai4bi.query_spec import (
            BlockRef, DimensionRef, FilterOperator, FilterSpec, SortDirection,
            SortSpec, VisualQuerySpec)
        # Round 182 (S1): if the prompt names a specific tool ("ETCH-01 的良率趨勢"),
        # filter the trend to it — an unfiltered overall can read "flat" even when
        # that one tool is clearly declining.
        entity_col = _trend_tool_column(contracts, block_id)
        named_value = (
            _trend_named_value(prompt, normalized, (contracts or {}).get(block_id), entity_col)
            if entity_col else None)
        filters = (
            [FilterSpec(block_id, entity_col, FilterOperator.eq, named_value)]
            if named_value else [])
        spec = VisualQuerySpec(
            spec_id=f"trend_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, date_col, date_col, truncate_date_to="week")],
            filters=filters,
            sort=[SortSpec(date_col, SortDirection.asc)], inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or len(df) < 3 or alias not in df.columns:
            return None
        import numpy as _np
        ys = df[alias].astype(float).to_numpy()
        xs = _np.arange(len(ys))
        slope = float(_np.polyfit(xs, ys, 1)[0]) if len(ys) >= 2 else 0.0
        first, last = float(ys[0]), float(ys[-1])
        higher_better = "yield" in metric_name.lower() or "良" in alias
        # "near-flat" guard: slope tiny relative to the metric level → say flat,
        # so we don't claim a direction the endpoints visibly contradict.
        scale = float(_np.nanmean(_np.abs(ys))) or 1.0
        rising = slope > 0
        if abs(slope) < 0.01 * scale:
            direction = "大致持平（無明顯趨勢）"
        elif (rising and higher_better) or (not rising and not higher_better):
            direction = "變好（往好的方向）"
        else:
            direction = "變差（往不好的方向）"
        scope_label = f"「{named_value}」的" if named_value else ""
        msg = (f"{scope_label}「{alias}」近 {len(df)} 週趨勢：{direction}。期初 {round(first,2)}"
               f" → 期末 {round(last,2)}，整體每週斜率 {round(slope,3)}。")
        # Round 182 (S1): when the overall reads flat but ONE tool is clearly
        # sliding, name it — that's the helpful answer for "良率趨勢如何". Skip if
        # the user already scoped to a single tool.
        if named_value is None and entity_col is not None:
            worst = self._worst_declining_entity(
                executor, block_id, metric_name, alias, date_col, entity_col,
                higher_better, scale)
            if worst is not None:
                ent, e_first, e_last = worst
                verb = "下滑" if higher_better else "上升"
                msg += (f" 其中「{ent}」最明顯{verb}（{round(e_first,2)} → {round(e_last,2)}）。")
        notes = [f"以 {date_col} 週彙總 {alias} 後取線性斜率與期初/期末對比，來源：{block_id}。"]
        if named_value:
            notes.append(f"已過濾到 {entity_col} = {named_value}。")
        self._remember(block_id=block_id, metric_name=metric_name, alias=alias,
                       dim_col=None, kind="trend")
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _worst_declining_entity(
        self, executor, block_id: str, metric_name: str, alias: str,
        date_col: str, entity_col: str, higher_better: bool, scale: float,
    ) -> "tuple[str, float, float] | None":
        """Round 182 (S1): run a per-entity weekly trend and return the entity
        whose slope is most adverse (declining for higher-is-better metrics),
        as (entity, first_week_value, last_week_value). None if none qualify."""
        try:
            from ai4bi.query_spec import (
                BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec)
            gspec = VisualQuerySpec(
                spec_id=f"trend_grp_{metric_name}", block_refs=[BlockRef(block_id)],
                metrics=[MetricRef(block_id, metric_name, alias)],
                dimensions=[
                    DimensionRef(block_id, date_col, date_col, truncate_date_to="week"),
                    DimensionRef(block_id, entity_col, entity_col)],
                sort=[SortSpec(date_col, SortDirection.asc)], inherit_global_filter=False)
            gdf = executor.run(gspec)
        except Exception:  # noqa: BLE001
            return None
        if gdf is None or entity_col not in gdf.columns or alias not in gdf.columns:
            return None
        import numpy as _np
        worst: tuple[str, float, float] | None = None
        worst_move = 0.0
        for ent, sub in gdf.groupby(entity_col):
            yv = sub[alias].astype(float).to_numpy()
            if len(yv) < 3:
                continue
            sl = float(_np.polyfit(_np.arange(len(yv)), yv, 1)[0])
            adverse = sl < 0 if higher_better else sl > 0
            # rank by the total adverse endpoint move (period start → end), which
            # surfaces a sustained slide even when the per-week slope is modest.
            move = float(yv[0]) - float(yv[-1]) if higher_better else float(yv[-1]) - float(yv[0])
            if adverse and move > worst_move:
                worst_move = move
                worst = (str(ent), float(yv[0]), float(yv[-1]))
        # only surface a meaningful slide (≥2.5% of the metric level, end-to-end)
        if worst is not None and worst_move >= 0.025 * scale:
            return worst
        return None

    def _answer_excursion(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 138: yield excursion — lots/wafers whose yield dropped abnormally
        low (below μ−kσ). Answers "有沒有哪幾批良率突然掉下來" instead of an overall."""
        if not contracts:
            return None
        from ai4bi.analysis.spc import control_limit_outliers
        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe
        # find the yield fact + its yield column + a lot/wafer key
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            cols = {x.name for x in getattr(c, "columns", [])}
            yld = next((x for x in cols if x.lower() in ("yield_pct", "yield")), None)
            key = "lot_id" if "lot_id" in cols else ("wafer_id" if "wafer_id" in cols else None)
            if not yld or not key:
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            table, limits = control_limit_outliers(df, key, yld, k=2.0)
            if not limits:
                continue
            low = table[table[yld] < limits["mean"]].reset_index(drop=True) \
                if not table.empty and yld in table.columns else table
            if low is None or low.empty:
                msg = (f"沒有 {key} 的平均 {yld} 低於 μ−2σ"
                       f"（μ={limits['mean']}, LCL={limits['lcl']}）→ 無明顯良率異常下掉。")
                notes = [f"良率 excursion：以 {key} 平均 {yld}，低於 μ−2σ 視為異常下掉。來源：{bid}。"]
                intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                                  trust_notes=notes, risk_level="low")
                return NL2ProposalResult(intent=intent, message=msg, trust_notes=notes,
                                         risk_level="low")
            names = "、".join(str(x) for x in low[key].head(5).tolist())
            # Round 141: make it time-aware — say WHEN the flagged lots dropped, so
            # "突然掉" gets an actual timing instead of a "this isn't temporal" caveat.
            date_col = _find_date_column(contracts, bid)
            timing = ""
            if date_col and date_col in df.columns:
                try:
                    import pandas as _pd
                    flagged_keys = set(low[key].tolist())
                    sub = df[df[key].isin(flagged_keys)].copy()
                    sub["_wk"] = _pd.to_datetime(sub[date_col], errors="coerce").dt.to_period("W").astype(str)
                    wk = sub.dropna(subset=["_wk"]).groupby("_wk").size().sort_values(ascending=False)
                    if not wk.empty:
                        weeks = "、".join(wk.index[:2])
                        low = low.merge(
                            sub.groupby(key)[date_col].min().rename("首次異常日"),
                            left_on=key, right_index=True, how="left")
                        timing = f" 發生時間集中在 {weeks}（已附首次異常日）。"
                except Exception:  # noqa: BLE001
                    timing = ""
            msg = (f"{len(low)} 個 {key} 良率異常下掉（低於 μ−2σ，μ={limits['mean']}, "
                   f"LCL={limits['lcl']}）：{names}。{timing}"
                   f"（採 2σ 作早期預警較敏感；要更保守可改 3σ。）"
                   f"建議：對這些批跑 commonality 找它們共同經過的機台，"
                   f"並比對該時段的 SPC/維護紀錄以定位根因。")
            notes = [f"良率 excursion：以 {key} 平均 {yld} 低於 μ−2σ 為異常（2σ＝較敏感的預警門檻），"
                     f"並對齊 {date_col} 標示發生週。來源：{bid}。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg, result_table=low,
                                     trust_notes=notes, risk_level="low")
        return None

    def _answer_ranking(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 087: "我最賺的 5 個商品" / "賣最差的品類" → ranked table answer.

        Resolves a metric + a categorical dimension, runs a grouped query with
        the executor's existing sort+limit, and returns the ranked rows. Returns
        None to fall through when metric/dimension/executor can't be resolved.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        metric = idx.best_metric_match(prompt, normalized)
        if metric is None:
            hay0 = f"{prompt.lower()} {normalized}"
            # Round 182 (S4): a "壞/缺陷/不良/瑕疵 主要在哪" with no explicit measure
            # means the defect COUNT — retry with an implicit defect measure.
            if any(t in hay0 for t in ("缺陷", "不良", "瑕疵", "壞", "defect", "bad ")):
                metric = idx.best_metric_match("缺陷 defect 不良", "que xian defect")
            # Round 182 (S2): "最差的機台是哪台" names no measure, but in a yield-
            # centric fab report the worst tool/product most naturally means worst
            # YIELD — retry with an implicit yield measure instead of refusing.
            if metric is None and any(t in hay0 for t in (
                    "機台", "機臺", "設備", "機器", "chamber", "腔", "tool", "產品",
                    "品類", "product", "批", "lot", "站", "step", "區", "area",
                    "哪台", "哪臺", "哪部", "哪一台", "哪一臺", "誰", "關注", "注意")):
                metric = idx.best_metric_match("良率 yield", "liang lv yield")
        if metric is None:
            return None
        block_id, metric_name, alias = metric.block_id, metric.metric_name, metric.alias

        dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
        if dim_col is None:
            # Round 182 (S4): a defect-count ranking with no named dimension → group
            # by defect_type (the natural "which defects" axis) if present.
            _names = {col.name for col in getattr(contracts.get(block_id), "columns", [])}
            for _cand in ("defect_type", "bin_code", "defect_code"):
                if _cand in _names and _is_categorical_col(contracts, block_id, _cand):
                    dim_col = _cand
                    break
        if dim_col is None:
            return None
        # Round 142: an explicit "哪一台機台 / which tool" must group by the tool
        # column even when another entity word (lot) also appears in the prompt.
        hay_r = f"{prompt.lower()} {normalized}"
        if any(t in hay_r for t in ("哪一台", "哪台", "機台", "which tool", "哪個機台",
                                    "哪部機", "chamber", "腔體", "哪個 chamber", "哪個chamber")):
            block_cols = [col.name for col in getattr(contracts.get(block_id), "columns", [])]
            tool_c = _guess_col(block_cols, ("tool_id", "tool", "機台", "設備", "equipment", "chamber"))
            if tool_c and tool_c != dim_col:
                dim_col = tool_c

        # Round 184 (S19): "不良率最高的是哪個 / 缺陷率最差的是哪一個" asks which TOOL
        # (an entity), not which defect TYPE — so a rate ranking that resolved
        # defect_type via "不良" must flip to the tool axis when an entity-asking
        # word is present and NO defect-type word ("哪種/類型/種類") is.
        if (dim_col and dim_col.lower() in ("defect_type", "bin_code", "defect_code")
                and any(t in hay_r for t in ("哪個", "哪一", "誰", "哪台", "哪部"))
                and not any(t in hay_r for t in ("哪種", "哪類", "類型", "種類", "哪一種"))):
            block_cols = [col.name for col in getattr(contracts.get(block_id), "columns", [])]
            tool_c = _guess_col(block_cols, ("etch_tool_id", "tool_id", "tool", "機台"))
            if tool_c and tool_c != dim_col:
                dim_col = tool_c

        # Round 182 (S4): "良率主要壞在哪種缺陷" picks the YIELD metric but a per-
        # defect-type breakdown ("壞在哪種缺陷") wants the defect COUNT — ranking a
        # ratio (yield) by defect_type would return the highest-yield bin (reversed).
        # Switch to a defect count metric so it surfaces the dominant defect.
        if (dim_col and dim_col.lower() in ("defect_type", "bin_code", "defect_code")
                and _metric_is_ratio(contracts, block_id, metric_name)
                and any(t in hay_r for t in ("缺陷", "defect", "不良", "瑕疵", "壞"))):
            _dm = idx.best_metric_match("缺陷 defect 不良", "que xian defect")
            if _dm is not None and _dm.block_id == block_id:
                metric_name, alias = _dm.metric_name, _dm.alias

        n = _extract_rank_n(prompt, normalized)
        ascending = _ranking_is_ascending(prompt, normalized)
        # Round 184 (S19): for a "higher is WORSE" metric (defect/scrap rate), the
        # worst is the HIGHEST — so "最差/最糟/最嚴重/比較差" must sort DESCENDING, not
        # ascending (which是 correct only for higher-is-better metrics like yield).
        _worse_is_high = any(t in metric_name.lower() for t in (
            "defect", "scrap", "fail", "reject", "density", "不良"))
        if _worse_is_high and any(t in hay_r for t in (
                "最差", "最糟", "最嚴重", "最爛", "比較差", "較差", "最不好", "不理想")):
            ascending = False
        unit = _metric_unit(contracts, block_id, metric_name)

        from ai4bi.query_spec import BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec

        spec = VisualQuerySpec(
            spec_id=f"rank_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, dim_col, dim_col)],
            sort=[SortSpec(alias, SortDirection.asc if ascending else SortDirection.desc)],
            limit=n,
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None

        superlative = "最低" if ascending else "最高"
        top = df.iloc[0]
        top_val = _format_metric_value(float(top[alias]) if alias in df.columns else None, unit) \
            if alias in df.columns else ""
        sentence = (f"{alias}{superlative}的前 {len(df)} 個「{dim_col}」。"
                    f"第一名：{top[dim_col]}（{top_val}）。")
        # Round 182 (S2): for a "比較/差多少/差異" question over exactly two groups,
        # spell out BOTH sides and the gap (個百分點 for a ratio) — the headline
        # "第一名 X" alone doesn't answer "差多少".
        if (len(df) == 2 and alias in df.columns
                and any(t in f"{prompt.lower()} {normalized}" for t in (
                    "比較", "差多少", "差異", "相差", "差距", "比一比", "對比", "之間", "兩台"))):
            a_row, b_row = df.iloc[0], df.iloc[1]
            av, bv = float(a_row[alias]), float(b_row[alias])
            _is_ratio2 = _metric_is_ratio(contracts, block_id, metric_name)
            gap_txt = (f"相差 {abs(av - bv):.1f} 個百分點" if (_is_ratio2 and unit == "%")
                       else f"相差 {_format_metric_value(abs(av - bv), unit)}")
            sentence = (f"{a_row[dim_col]} {_format_metric_value(av, unit)}　vs　"
                        f"{b_row[dim_col]} {_format_metric_value(bv, unit)}，{gap_txt}。")
        notes = [
            f"依「{alias}」對「{dim_col}」排序取前 {n}（治理查詢 sort+limit，認證語意層）。",
            f"來源：{block_id}。",
        ]
        # Round 137: provenance on ranking when asked ("用幾筆資料算的").
        if any(t in f"{prompt.lower()} {normalized}" for t in (
                "幾筆", "幾片", "母體", "幾個資料", "用幾", "how many", "population", "based on")):
            prov = _provenance_note(contracts, block_id, _find_date_column(contracts, block_id), metric_name)
            if prov:
                sentence = f"{sentence} {prov}"
                notes.append(prov)
        # Round 135: when ranking by a weighted-yield metric and the user asks about
        # weighting ("是用晶圓數加權的嗎"), confirm the method explicitly in plain words.
        if "weighted_yield" in metric_name.lower():
            wnote = ("此「加權良率」＝SUM(良品)/SUM(受測晶粒)，以晶粒數加權（非各晶圓良率的"
                     "簡單平均），故大晶圓不會被小晶圓等權稀釋。")
            notes.append(wnote)
            if any(t in f"{prompt.lower()} {normalized}" for t in (
                    "加權", "weighted", "晶圓數", "晶粒", "die", "平均", "怎麼算")):
                sentence = f"{sentence} {wnote}"
        self._remember(block_id=block_id, metric_name=metric_name, alias=alias,
                       dim_col=dim_col, kind="ranking")
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(
            intent=intent, message=sentence, result_table=df,
            trust_notes=notes, risk_level="low",
        )

    def _run_panel_analysis(
        self,
        prompt: str,
        normalized: str,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 086: route a question to a pre-built pandas analytics engine.

        Churn/RFM, declining-streaks and market-basket are fully implemented and
        tested but were sidebar-only. This bridges them to the ask box: it picks
        the analysis from keywords, auto-guesses the columns (same heuristics the
        panels use), materialises the fact, runs the engine, and returns a
        summary sentence + the result table. Returns None to fall through.
        """
        if not contracts:
            return None
        kind = _detect_panel_analysis(prompt, normalized)
        if kind is None:
            return None

        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe

        # Pick the fact block whose columns best fit this analysis.
        facts = {
            bid: c for bid, c in contracts.items()
            if getattr(c, "block_type", None) in (
                BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)
        }
        if not facts:
            return None

        best = _pick_fact_for_analysis(facts, kind)
        if best is None:
            return None
        block_id, contract, cols_map = best

        # Round 115: prompt-aware override for entity×value analyses. Prefer the
        # block where the dimension the user NAMED (機台/製程/product) and the
        # measure they NAMED (良率/等待/缺陷) both resolve, instead of guessing
        # from column order (which picked lot_id / queue_time for '機台良率').
        if kind in ("decline", "dormant", "newproduct"):
            idx = SchemaIndex.build(contracts)
            # Round 182 (S1): when NO measure is named ("哪台機台連續下滑"), prefer the
            # YIELD fact/column — otherwise the first fact (queue_time) is picked and
            # the answer contradicts "良率一直在跌→ETCH-01". Order yield blocks first.
            _hay_pa = f"{prompt.lower()} {normalized}"
            _named_measure = any(w in _hay_pa for w in (
                "良率", "yield", "等待", "queue", "cycle", "週期", "缺陷", "defect",
                "move", "移動", "產能", "可用率", "oee", "稼動", "利用率"))
            _blocks = sorted(
                facts.items(),
                key=lambda kv: 0 if (not _named_measure and any(
                    "yield" in cc.name.lower() for cc in getattr(kv[1], "columns", [])))
                else 1)
            for bid, c in _blocks:
                ent = _resolve_decomp_dimension(idx, prompt, normalized, contracts, bid)
                val = _resolve_numeric_column(prompt, normalized, c)
                if not _named_measure:
                    _yc = next((cc.name for cc in getattr(c, "columns", [])
                                if "yield" in cc.name.lower() and getattr(cc, "data_type", "")
                                in ("integer", "float", "int", "double", "number")), None)
                    if _yc:
                        val = _yc
                date = _find_date_column(contracts, bid)
                if val and date and not ent:
                    # Round 178 (S1): a decline question with a measure+date but no
                    # explicit entity ("良率最近怎麼一直掉?") → default to a sensible
                    # entity axis (tool/product/step) so we name WHAT is declining
                    # instead of collapsing to a single overall trend.
                    _scols = [cc.name for cc in getattr(c, "columns", [])
                              if getattr(cc, "data_type", "") in ("string", "str", "object")
                              and not _is_pk_like(cc.name)]
                    ent = (_guess_col(_scols, ("etch_tool", "tool_id", "tool"))
                           or _guess_col(_scols, ("product", "family"))
                           or _guess_col(_scols, ("step",))
                           or (_scols[0] if _scols else None))
                if ent and val and date:
                    block_id, contract, cols_map = bid, c, {
                        "entity": ent, "date": date, "value": val}
                    break

        if kind in ("decline", "dormant", "newproduct"):
            # Period: explicit word wins; default monthly for dormancy/launches,
            # weekly for streaks (more periods available).
            period = _extract_answer_period(normalized, prompt)
            default = "week" if kind == "decline" else "month"
            cols_map["period"] = {"all": default, "year": "month"}.get(period, period)
        if kind == "decline":
            sm = re.search(r"連續\s*(\d+)|(\d+)\s*(?:期|個月|個週|週|周|months?)", f"{prompt} {normalized}")
            cols_map["min_streak"] = int(next(g for g in sm.groups() if g)) if sm else 3

        try:
            df = materialize_dataframe(contract)
        except Exception:  # noqa: BLE001 — external connectors aren't materialisable
            return None
        if df is None or df.empty:
            return None

        table, sentence = _execute_panel_analysis(kind, df, cols_map)
        if table is None or table.empty:
            # Round 115: the analysis ran but found nothing qualifying. Report
            # that honestly instead of falling through to "unsupported intent".
            msg = f"沒有符合「{_PANEL_LABELS[kind]}」條件的結果。"
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=[msg], risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg,
                                     trust_notes=[msg], risk_level="low")

        notes = [
            f"使用「{_PANEL_LABELS[kind]}」分析（純 pandas，於記憶體資料計算）。",
            f"自動選用欄位：{', '.join(f'{k}={v}' for k, v in cols_map.items() if v)}。",
            f"來源資料集：{block_id}。",
        ]
        intent = AIIntent(
            intent_kind="analysis_request", target_scope="semantic_model",
            trust_notes=notes, risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent, message=sentence, result_table=table,
            trust_notes=notes, risk_level="low",
        )

    def _answer_metric(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 078: answer a metric question with a real, sourced number.

        Resolves the metric from the certified schema, runs it through the
        governed executor (whole-period total, or current-vs-previous trailing
        window when a time phrase is present), and returns a one-sentence answer
        plus a one-click "add as KPI" proposal. Returns None to fall through to
        edit-intent routing when no metric resolves or no executor is wired.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None

        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        unit = _metric_unit(contracts, block_id, metric_name)
        period = _extract_answer_period(normalized, prompt)
        date_col = _find_date_column(contracts, block_id)

        from ai4bi.query_spec import BlockRef, VisualQuerySpec

        base = VisualQuerySpec(
            spec_id=f"nl_answer_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            inherit_global_filter=False,
        )

        notes = [
            f"指標「{alias}」來自認證語意層（{metric_name} @ {block_id}），未產生自由 SQL。",
            "數字由治理查詢路徑即時計算，與儀表板 KPI 同源。",
        ]

        value: float | None = None
        previous: float | None = None
        delta_pct: float | None = None
        cur_label = prev_label = ""

        if period != "all" and date_col is not None:
            from ai4bi.analysis.time_intelligence import compute_period_comparison

            comp = compute_period_comparison(
                executor, base, date_block_id=block_id, date_column=date_col,
                period=period, metric_col=alias,
            )
            if comp is not None and comp.current is not None:
                value, previous = comp.current, comp.previous
                delta_pct = comp.delta_pct
                cur_label, prev_label = comp.current_label, comp.previous_label
                notes.append(f"比較窗：{cur_label} vs {prev_label}（錨定資料最新日期）。")
            else:
                # No usable date/anchor — degrade to whole-period total.
                period = "all"

        if value is None and period == "all":
            try:
                df = executor.run(base)
            except Exception:  # noqa: BLE001
                return None
            value = _first_scalar(df, alias)

        if value is None:
            return None

        sentence = _compose_answer_sentence(
            alias, value, unit, period, previous, delta_pct, cur_label, prev_label
        )

        # Round 135: faithfulness provenance — population N, date span, method,
        # exclusions. Always added to trust notes; appended to the sentence when
        # the user explicitly asks ("幾片晶圓 / 母體 / 排除了什麼 / 怎麼算").
        prov = _provenance_note(contracts, block_id, date_col, metric_name)
        if prov:
            notes.append(prov)
            asks_prov = any(t in f"{prompt.lower()} {normalized}" for t in (
                "幾片", "幾筆", "母體", "排除", "怎麼算", "用什麼算", "幾個", "幾批",
                "how many", "population", "exclud", "based on",
                "加權", "簡單平均", "weighted", "simple average", "怎麼來"))
            if asks_prov:
                sentence = f"{sentence} {prov}"

        # Round 142: target verdict — "良率有沒有達到 95% 的目標？" → state met/missed
        # against the target named in the prompt, instead of just the number.
        hay_t = f"{prompt.lower()} {normalized}"
        if any(t in hay_t for t in ("達到", "達標", "目標", "有沒有達", "是否達", "target", "goal")):
            tgt = _parse_threshold(hay_t)
            if tgt is not None and value is not None:
                gap = round(value - tgt, 2)
                u = unit or ""
                if value >= tgt:
                    verdict = f"已達標 ✅（{round(value,2)}{u} ≥ 目標 {tgt}{u}，高出 {abs(gap)}{u}）。"
                else:
                    verdict = f"未達標 ⚠️（{round(value,2)}{u} < 目標 {tgt}{u}，差 {abs(gap)}{u}）。"
                sentence = f"{sentence} {verdict}"

        answer = DirectAnswer(
            question=prompt.strip(),
            metric_block_id=block_id,
            metric_name=metric_name,
            metric_alias=alias,
            sentence=sentence,
            value=value,
            period=period,
            previous=previous,
            delta_pct=delta_pct,
            current_label=cur_label,
            previous_label=prev_label,
            unit=unit,
            trust_notes=notes,
        )

        # One-click "add as KPI" — reuse the governed add-visual proposal path.
        proposal = self._build_answer_kpi_proposal(report, block_id, metric_name, alias, period, date_col)

        self._remember(block_id=block_id, metric_name=metric_name, alias=alias,
                       dim_col=None, kind="metric")
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="semantic_model",
            selection=SemanticSelection(metric_block_id=block_id, metric_name=metric_name),
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=sentence,
            proposal=proposal,
            direct_answer=answer,
            trust_notes=notes,
            risk_level="low",
        )

    def _explain_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 081: answer "why did <metric> change?" by decomposing the
        period-over-period delta across a dimension.

        Reuses time_intelligence.compute_grouped_comparison (today only reachable
        from the sidebar panel) to rank the biggest contributors to the change,
        and returns them as a sentence. Returns None to fall through when a
        metric/dimension/date can't be resolved.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        metric = idx.best_metric_match(prompt, normalized)
        if metric is None:
            return None
        block_id, metric_name, alias = metric.block_id, metric.metric_name, metric.alias

        dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
        if dim_col is None:
            # Round 182 (S1): "為什麼良率變差" names no dimension — default to the most
            # explanatory categorical (tool, else product) so we decompose into a
            # culprit instead of falling back to an overall single number.
            _names = {col.name for col in getattr(contracts.get(block_id), "columns", [])}
            for _cand in ("etch_tool_id", "tool_id", "product_family", "tool_group"):
                if _cand in _names and _is_categorical_col(contracts, block_id, _cand):
                    dim_col = _cand
                    break
        if dim_col is None:
            return None
        date_col = _find_date_column(contracts, block_id)
        if date_col is None or date_col == dim_col:
            return None

        period = _extract_answer_period(normalized, prompt)
        if period == "all":
            period = "month"  # decomposition needs two comparable windows

        from ai4bi.analysis.time_intelligence import compute_grouped_comparison
        from ai4bi.query_spec import BlockRef, VisualQuerySpec

        base = VisualQuerySpec(
            spec_id=f"explain_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            inherit_global_filter=False,
        )
        is_ratio = _metric_is_ratio(contracts, block_id, metric_name)
        try:
            df = compute_grouped_comparison(
                executor, base, date_block_id=block_id, date_column=date_col,
                dimension_col=dim_col, period=period, metric_col=alias,
                is_ratio=is_ratio,
            )
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None

        unit = _metric_unit(contracts, block_id, metric_name)
        if is_ratio:
            # ratio metrics: TRUE weighted overall (not a sum of group rates),
            # carried in df.attrs by compute_grouped_comparison (Round 178).
            cur_total = float(df.attrs.get("overall_current", float("nan")))
            prev_total = float(df.attrs.get("overall_previous", float("nan")))
            total = (cur_total - prev_total) if (cur_total == cur_total and prev_total == prev_total) else 0.0
        else:
            total = float(df["delta"].sum())
            cur_total = float(df["current"].sum())
            prev_total = float(df["previous"].sum())
        delta_pct = ((cur_total - prev_total) / abs(prev_total) * 100.0) if prev_total else None
        scope = _PERIOD_TITLE.get(period, period)

        sentence = _compose_decomposition_sentence(
            alias, dim_col, df, total, unit, scope, is_ratio=is_ratio
        )
        notes = [
            f"指標「{alias}」依「{dim_col}」拆解（{scope} vs 前一期），重用治理查詢路徑。",
            "依各維度對總變化的貢獻排序，未產生自由 SQL。",
        ]
        answer = DirectAnswer(
            question=prompt.strip(),
            metric_block_id=block_id,
            metric_name=metric_name,
            metric_alias=alias,
            sentence=sentence,
            value=cur_total,
            period=period,
            previous=prev_total,
            delta_pct=delta_pct,
            unit=unit,
            trust_notes=notes,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="semantic_model",
            selection=SemanticSelection(metric_block_id=block_id, metric_name=metric_name),
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent, message=sentence, direct_answer=answer,
            trust_notes=notes, risk_level="low",
        )

    def _build_answer_kpi_proposal(
        self,
        report: ExecutableReportSpec,
        block_id: str,
        metric_name: str,
        alias: str,
        period: str,
        date_col: str | None,
    ) -> "ReportProposal | None":
        """Build an optional 'add this answer as a KPI card' proposal."""
        try:
            from ai4bi.report.builder import build_add_visual_proposal
            from ai4bi.query_spec import BlockRef, VisualQuerySpec, VisualizationSpec

            page_id = "main" if "main" in report.pages else next(iter(report.pages), None)
            if page_id is None:
                return None
            existing = set(report.pages[page_id].visuals.keys())
            vid = f"kpi_answer_{metric_name}"
            c = 1
            while vid in existing:
                vid = f"kpi_answer_{metric_name}_{c}"; c += 1

            q = VisualQuerySpec(
                spec_id=vid,
                block_refs=[BlockRef(block_id)],
                metrics=[MetricRef(block_id, metric_name, alias)],
                inherit_global_filter=False,
            )
            title = f"{alias}" if period == "all" else f"{alias}（{_PERIOD_TITLE.get(period, period)}）"
            v = VisualizationSpec(VisualType.kpi_card, title=title, extra={})
            return build_add_visual_proposal(page_id, vid, q, v)
        except Exception:  # noqa: BLE001 — the answer itself must not depend on this
            return None

    def _queue_time_plan(
        self,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            found = _first_queue_visual(report)
        visual_id = found[1] if found is not None else None
        visual = found[2] if found is not None else None
        selection = _selection_from_visual(visual) if visual is not None else _selection_from_semantic_model(semantic_model)
        scope = f"visual:{visual_id}" if visual_id is not None else "semantic_model"
        suggested_visuals = _queue_visual_ids(report)
        model_ref = getattr(report, "semantic_model_ref", "unknown")
        contract_count = len(contracts or {})
        notes = [
            "Uses governed queue-time metric selection; no SQL is generated.",
            f"Report semantic model reference: {model_ref}.",
            f"Contracts available for grounding: {contract_count}.",
        ]
        plan = AnalysisPlan(
            question=prompt.strip(),
            target_scope=scope,
            selection=selection,
            steps=[
                "Confirm the queue-time metric and inherited report filters.",
                "Compare the queue-time trend across the selected date dimension.",
                "Break down queue time by certified dimensions already present in the report.",
                "Return observations with metric, dimension, and filter lineage.",
            ],
            suggested_visuals=suggested_visuals,
            trust_notes=notes,
            risk_level="medium",
            generated_sql=None,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=scope,
            selection=selection,
            suggested_visuals=suggested_visuals,
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message="Analysis plan created. It does not generate SQL or change the report.",
            analysis_plan=plan,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 022: rename_visual intent
    # ------------------------------------------------------------------

    def _rename_visual(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a visual before renaming it.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found
        new_title = _extract_rename_title(prompt, normalized)
        if new_title is None or not new_title.strip():
            return self._unsupported(
                "Specify the new chart name, e.g. 'rename this chart to Queue Trend'.",
                target_scope=f"visual:{visual_id}",
            )
        # XSS-safe: strip HTML tags and limit length
        import html
        new_title = re.sub(r"<[^>]+>", "", new_title).strip()[:80]
        if not new_title:
            return self._unsupported("Chart name must not be empty.", target_scope=f"visual:{visual_id}")
        before_title = visual.visualization.title
        if before_title == new_title:
            return self._unsupported(f"Chart title is already '{new_title}'.", target_scope=f"visual:{visual_id}")
        path = f"pages/{page_id}/visuals/{visual_id}/visualization/title"
        notes = [f"Renaming '{visual_id}' from '{before_title}' to '{new_title}'.", "Display-only change; query is unchanged."]
        proposal = ReportProposal(
            description=f"Rename chart to '{new_title}'",
            changes=[ReportChange(path=path, label="Chart title", before=before_title, after=new_title, affects_data=False)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="style_change", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=f"Rename proposal created: '{new_title}'.", proposal=proposal, trust_notes=notes, risk_level="low")

    # ------------------------------------------------------------------
    # Round 022: remove_metric intent
    # ------------------------------------------------------------------

    def _remove_metric(
        self,
        metric_name: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported("Select a visual before removing a metric.", target_scope=_target_scope(selected_component_id))
        page_id, visual_id, visual = found
        current_names = [m.metric_name for m in visual.query.metrics]
        if metric_name not in current_names:
            return self._unsupported(f"Metric '{metric_name}' is not in this visual.", target_scope=f"visual:{visual_id}")
        if len(visual.query.metrics) <= 1:
            refusal = GovernanceRefusal(
                reason=f"Cannot remove '{metric_name}': a visual must retain at least one metric.",
                blocked_terms=[metric_name],
                trust_notes=["Removing the last metric would create an empty query.", "Add a replacement metric before removing this one."],
                risk_level="medium",
            )
            intent = AIIntent(intent_kind="unsupported", target_scope=f"visual:{visual_id}", trust_notes=refusal.trust_notes, risk_level="medium")
            return NL2ProposalResult(intent=intent, message=refusal.reason, refusal=refusal, trust_notes=refusal.trust_notes, risk_level="medium")
        before = [{"block_id": m.block_id, "metric_name": m.metric_name, "alias": m.alias, "agg_override": m.agg_override.value if m.agg_override else None} for m in visual.query.metrics]
        after = [m for m in before if m["metric_name"] != metric_name]
        path = f"pages/{page_id}/visuals/{visual_id}/query/metrics"
        notes = [f"Removing metric '{metric_name}' from visual '{visual_id}'.", "This change re-queries the visual after approval."]
        proposal = ReportProposal(
            description=f"Remove metric '{metric_name}'",
            changes=[ReportChange(path=path, label=f"Remove metric: {metric_name}", before=before, after=after, affects_data=True)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium")
        return NL2ProposalResult(intent=intent, message=f"Remove metric proposal created for '{metric_name}'.", proposal=proposal, trust_notes=notes, risk_level="medium")

    # ------------------------------------------------------------------
    # Round 022: categorical_dimension_change intent
    # ------------------------------------------------------------------

    def _categorical_dimension_change(
        self,
        cat_dim: dict,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported("Select a visual before changing the grouping dimension.", target_scope=_target_scope(selected_component_id))
        page_id, visual_id, visual = found
        block_id = cat_dim["block_id"]
        column_name = cat_dim["column_name"]
        alias = cat_dim.get("alias", column_name)
        # Governance: block_id must be in visual's certified dimension targets
        if not visual.query.metrics:
            return self._unsupported("No metrics in this visual; cannot determine dimension block.", target_scope=f"visual:{visual_id}")
        fact_block = visual.query.metrics[0].block_id
        certified = _certified_dim_targets_for_fact(fact_block, semantic_model or {})
        if block_id not in certified and block_id != fact_block:
            refusal = GovernanceRefusal(
                reason=f"Block '{block_id}' is not a certified dimension of '{fact_block}'. Only certified relationships are allowed.",
                blocked_terms=[block_id],
                trust_notes=["Ask your data team to certify this relationship before using it.", "Available certified dimensions: " + ", ".join(sorted(certified))],
                risk_level="high",
            )
            intent = AIIntent(intent_kind="unsupported", target_scope=f"visual:{visual_id}", trust_notes=refusal.trust_notes, risk_level="high")
            return NL2ProposalResult(intent=intent, message=refusal.reason, refusal=refusal, trust_notes=refusal.trust_notes, risk_level="high")
        before_dims = [{"block_id": d.block_id, "column_name": d.column_name, "alias": d.alias, "truncate_date_to": d.truncate_date_to} for d in visual.query.dimensions]
        after_dims = [{"block_id": block_id, "column_name": column_name, "alias": alias, "truncate_date_to": None}]
        path = f"pages/{page_id}/visuals/{visual_id}/query/dimensions"
        notes = [f"Grouping by '{column_name}' from block '{block_id}' (certified).", "This change re-queries the visual after approval."]
        proposal = ReportProposal(
            description=f"Group by {alias} ({block_id}.{column_name})",
            changes=[ReportChange(path=path, label=f"Dimension → {alias}", before=before_dims, after=after_dims, affects_data=True)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium")
        return NL2ProposalResult(intent=intent, message=f"Dimension change proposal: group by {alias}.", proposal=proposal, trust_notes=notes, risk_level="medium")

    # ------------------------------------------------------------------
    # Round 022: value_filter_change intent
    # ------------------------------------------------------------------

    def _value_filter_change(
        self,
        column_name: str,
        values: list[str],
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported("Select a visual before adding a value filter.", target_scope=_target_scope(selected_component_id))
        page_id, visual_id, visual = found
        # Determine block_id: search current block_refs for the column
        block_id = _find_block_for_column(visual, column_name, semantic_model or {})
        if block_id is None:
            return self._unsupported(f"Column '{column_name}' was not found in this visual's blocks.", target_scope=f"visual:{visual_id}")
        before_filters = [
            {"block_id": f.block_id, "column_name": f.column_name, "operator": f.operator.value,
             "value": f.value, "inherit_global_filter": f.inherit_global_filter}
            for f in visual.query.filters
        ]
        # Remove any existing filter for the same column, then append new one
        after_filters = [f for f in before_filters if not (f["block_id"] == block_id and f["column_name"] == column_name)]
        after_filters.append({"block_id": block_id, "column_name": column_name, "operator": "in", "value": values, "inherit_global_filter": False})
        path = f"pages/{page_id}/visuals/{visual_id}/query/filters"
        notes = [f"Filtering '{column_name}' to {values} on block '{block_id}'.", "This change re-queries the visual after approval."]
        proposal = ReportProposal(
            description=f"Filter {column_name} to {values}",
            changes=[ReportChange(path=path, label=f"Filter: {column_name} IN {values}", before=before_filters, after=after_filters, affects_data=True)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium")
        return NL2ProposalResult(intent=intent, message=f"Value filter proposal: {column_name} IN {values}.", proposal=proposal, trust_notes=notes, risk_level="medium")

    # ------------------------------------------------------------------
    # Round 080: measure (post-aggregate) filter → HAVING
    # ------------------------------------------------------------------

    def _measure_filter_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> "NL2ProposalResult | None":
        """Turn "customers who bought more than 3 times" into a HAVING predicate.

        Adds a post-aggregate measure filter to a target visual. The measure
        must already be projected by the visual (visual-level measure filter),
        which the executor enforces — so we resolve the threshold against the
        visual's own metrics. Returns None to fall through when no target/metric
        can be resolved.
        """
        found = _find_visual(report, selected_component_id)
        if found is None:
            # Fall back to the first visual that both groups and aggregates —
            # HAVING is only meaningful on a grouped, aggregated visual.
            for pid, page in report.pages.items():
                for vid, v in page.visuals.items():
                    if v.query.metrics and v.query.dimensions:
                        found = (pid, vid, v)
                        break
                if found:
                    break
        if found is None:
            return None
        page_id, visual_id, visual = found
        if not visual.query.metrics:
            return None

        parsed = _extract_measure_filter(prompt, normalized, visual)
        if parsed is None:
            return None
        metric, operator, value = parsed

        before = [
            {"block_id": h.block_id, "metric_name": h.metric_name,
             "operator": h.operator.value, "value": h.value}
            for h in visual.query.having
        ]
        # Replace any existing predicate on the same metric+operator, then append.
        after = [
            h for h in before
            if not (h["metric_name"] == metric.metric_name and h["operator"] == operator.value)
        ]
        after.append({
            "block_id": metric.block_id,
            "metric_name": metric.metric_name,
            "operator": operator.value,
            "value": value,
        })
        label_name = metric.alias or metric.metric_name
        op_sym = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "neq": "≠"}.get(operator.value, operator.value)
        notes = [
            f"在彙總後篩選「{label_name}」{op_sym} {value}（HAVING，逐組篩選）。",
            "僅篩選此圖已投影的指標，仍走認證語意層；套用後重新查詢。",
        ]
        path = f"pages/{page_id}/visuals/{visual_id}/query/having"
        proposal = ReportProposal(
            description=f"Measure filter: {label_name} {op_sym} {value}",
            changes=[ReportChange(
                path=path, label=f"HAVING: {label_name} {op_sym} {value}",
                before=before, after=after, affects_data=True,
            )],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="analysis_request", target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已建立彙總後篩選：{label_name} {op_sym} {value}。",
            proposal=proposal, trust_notes=notes, risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 088: "are we on track?" — read back KPI pacing
    # ------------------------------------------------------------------

    def _answer_pacing(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Answer "達標了嗎 / are we on track?" by reading each KPI's target.

        Computes the KPI's current value the same way the card does (trailing
        window when compare_period is set, else the plain aggregate) and reports
        on-track / behind. Returns None when no executor; a guiding message when
        no KPI has a target.
        """
        executor = getattr(self, "_executor", None)
        if executor is None:
            return None

        from ai4bi.ui.components.kpi_card import _pacing_status

        targets = []
        for pid, page in report.pages.items():
            for vid, v in page.visuals.items():
                if v.visualization.visual_type != VisualType.kpi_card:
                    continue
                tgt = v.visualization.extra.get("target")
                if tgt is None or not v.query.metrics:
                    continue
                targets.append((pid, vid, v, float(tgt)))

        if not targets:
            return self._unsupported(
                "目前沒有任何 KPI 設定目標。試試「把營收目標設為 100 萬」之後再問達標進度。",
                target_scope="report",
            )

        lines: list[str] = []
        headline_value = None
        for _pid, _vid, v, tgt in targets:
            value = self._kpi_current_value(executor, v)
            if value is None:
                continue
            if headline_value is None:
                headline_value = value
            good_if = v.visualization.extra.get("target_good_if") or _infer_target_good_if(v)
            pacing = _pacing_status(value, tgt, good_if)
            label = v.visualization.title or v.query.metrics[0].alias or v.query.metrics[0].metric_name
            if pacing:
                _frac, cap, _ok = pacing
                lines.append(f"「{label}」：{cap}")
        if not lines:
            return None

        sentence = "　|　".join(lines)
        notes = ["依各 KPI 設定的目標即時計算進度（與儀表板 KPI 同源）。"]
        answer = DirectAnswer(
            question=prompt.strip(),
            metric_block_id=targets[0][2].query.metrics[0].block_id,
            metric_name=targets[0][2].query.metrics[0].metric_name,
            metric_alias="達標進度",
            sentence=sentence,
            value=headline_value,
            period="all",
            trust_notes=notes,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, direct_answer=answer,
                                 trust_notes=notes, risk_level="low")

    def _kpi_current_value(self, executor, visual) -> float | None:
        """Current value of a KPI visual — trailing window if compare_period set."""
        from ai4bi.query_spec import BlockRef, VisualQuerySpec
        metric = visual.query.metrics[0]
        alias = metric.alias or metric.metric_name
        extra = visual.visualization.extra or {}
        compare_period = extra.get("compare_period")
        date_col = extra.get("compare_date_column")
        base = VisualQuerySpec(
            spec_id=f"pace_{metric.metric_name}",
            block_refs=[BlockRef(metric.block_id)],
            metrics=[MetricRef(metric.block_id, metric.metric_name, alias)],
            inherit_global_filter=False,
        )
        if compare_period and date_col:
            from ai4bi.analysis.time_intelligence import compute_period_comparison
            comp = compute_period_comparison(
                executor, base, date_block_id=metric.block_id, date_column=date_col,
                period=compare_period, metric_col=alias)
            if comp is not None and comp.current is not None:
                return comp.current
        try:
            df = executor.run(base)
        except Exception:  # noqa: BLE001
            return None
        return _first_scalar(df, alias)

    # ------------------------------------------------------------------
    # Round 084: set a KPI goal / target (pacing)
    # ------------------------------------------------------------------

    def _set_target(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> "NL2ProposalResult | None":
        """"把營收目標設為 100 萬" → set a KPI card's target for pacing.

        Resolves a KPI-card visual (the selected one, or the KPI whose metric
        keyword appears in the prompt, else the first KPI) and stages a
        display-only change to visualization.extra["target"].
        """
        value = _extract_target_value(prompt, normalized)
        if value is None:
            return None

        # Resolve the target KPI visual.
        found = _find_visual(report, selected_component_id)
        target_tuple = None
        if found is not None and found[2].visualization.visual_type == VisualType.kpi_card:
            target_tuple = found
        if target_tuple is None:
            hay = f"{prompt.lower()} {normalized}"
            first_kpi = None
            for pid, page in report.pages.items():
                for vid, v in page.visuals.items():
                    if v.visualization.visual_type != VisualType.kpi_card or not v.query.metrics:
                        continue
                    if first_kpi is None:
                        first_kpi = (pid, vid, v)
                    m = v.query.metrics[0]
                    for kw in {m.metric_name.lower(), (m.alias or "").lower()}:
                        if kw and kw in hay:
                            target_tuple = (pid, vid, v)
                            break
                    if target_tuple:
                        break
                if target_tuple:
                    break
            if target_tuple is None:
                target_tuple = first_kpi
        if target_tuple is None:
            return self._unsupported(
                "找不到可設定目標的 KPI 卡。請先選擇一張 KPI 卡。",
                target_scope=_target_scope(selected_component_id),
            )

        page_id, visual_id, visual = target_tuple
        metric_label = visual.visualization.title or (
            visual.query.metrics[0].alias or visual.query.metrics[0].metric_name
        )
        before = visual.visualization.extra.get("target")
        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/target"
        # Honesty fix (Round 088): also set good_if so a lower-is-better KPI
        # (return rate / cost / churn) doesn't render an inverted progress bar.
        good_if = _infer_target_good_if(visual)
        good_if_before = visual.visualization.extra.get("target_good_if")
        good_if_path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/target_good_if"
        sense = "越低越好" if good_if == "lte" else "越高越好"
        notes = [
            f"為「{metric_label}」設定目標 {value:,.0f}（{sense}），顯示達成進度條。",
            "顯示用變更，不影響查詢數字。",
        ]
        changes = [ReportChange(path=path, label=f"KPI 目標：{metric_label}",
                                before=before, after=value, affects_data=False)]
        if good_if_before != good_if:
            changes.append(ReportChange(
                path=good_if_path, label="目標方向（越高/越低越好）",
                before=good_if_before, after=good_if, affects_data=False))
        proposal = ReportProposal(
            description=f"Set target for '{metric_label}' = {value:,.0f}",
            changes=changes,
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}",
                          suggested_visuals=[visual_id], trust_notes=notes, risk_level="low")
        return NL2ProposalResult(
            intent=intent, message=f"已為「{metric_label}」設定目標 {value:,.0f}（{sense}）。",
            proposal=proposal, trust_notes=notes, risk_level="low",
        )

    # ------------------------------------------------------------------
    # Round 020: date_filter_change intent (global_filters/date_range)
    # ------------------------------------------------------------------

    def _date_filter_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
    ) -> NL2ProposalResult:
        period = _extract_date_period(prompt, normalized)
        if period is None:
            return self._unsupported(
                "請指定時間範圍：最近 3 個月、上一季、今年，或「清除日期篩選」。",
                target_scope="report",
            )

        before = report.global_filters.get(_DATE_FILTER_GLOBAL_KEY)

        # Round 184 (S17): plain-Chinese labels — never leak English to the user.
        _PERIOD_ZH = {
            "week": "最近 7 天", "month": "最近 30 天", "quarter": "最近一季",
            "year": "最近一年", "last_month": "上個月", "last_quarter": "上一季",
            "last_3m": "最近 3 個月", "last_6m": "最近 6 個月", "ytd": "今年迄今",
            "this_month": "本月", "this_week": "本週", "clear": "清除篩選"}
        _zh = _PERIOD_ZH.get(period, period)
        if period == "clear":
            after = None
            description = "清除日期範圍篩選"
            label = "日期範圍篩選"
        else:
            after = {"anchor": "relative", "period": period}
            description = f"日期範圍設為「{_zh}」"
            label = f"日期範圍 → {_zh}"

        if before == after:
            notes = [f"日期篩選已是「{_zh}」。"]
            intent = AIIntent(
                intent_kind="analysis_request",
                target_scope="report",
                trust_notes=notes,
                risk_level="low",
            )
            return NL2ProposalResult(
                intent=intent,
                message=f"日期篩選已經是「{_zh}」了。",
                trust_notes=notes,
                risk_level="low",
            )

        notes = [
            f"將報表層級的日期範圍篩選設為「{_zh}」。",
            "會套用到所有繼承全域篩選的圖表。",
            "不產生 SQL —— 執行層在查詢時才解析相對期間。",
        ]
        proposal = ReportProposal(
            description=description,
            changes=[
                ReportChange(
                    path=f"global_filters/{_DATE_FILTER_GLOBAL_KEY}",
                    label=label,
                    before=before,
                    after=after,
                    affects_data=True,
                )
            ],
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="report",
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已建立日期篩選：{description}。",
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    # ------------------------------------------------------------------
    # Round 019: chart_type_change intent
    # ------------------------------------------------------------------

    def _chart_type_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a bar or line chart before changing the chart type.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found
        current_type = visual.visualization.visual_type

        # Detect target chart type from prompt
        target_type = _extract_chart_type(prompt, normalized)
        if target_type is None:
            return self._unsupported(
                "Specify a supported chart type: bar chart (長條圖) or line chart (折線圖).",
                target_scope=f"visual:{visual_id}",
            )

        # Round 151: table ↔ chart conversions are now allowed (the data_table
        # renderer accepts any query), as is converting to a pivot when the visual
        # has ≥2 dimensions. kpi_card and map keep different contracts → blocked.
        _UNSUPPORTED_SOURCE = {VisualType.kpi_card, VisualType.map}
        _UNSUPPORTED_TARGET = {VisualType.kpi_card, VisualType.map}
        if current_type in _UNSUPPORTED_SOURCE:
            return self._unsupported(
                f"Chart type change is not supported for {current_type.value} visuals.",
                target_scope=f"visual:{visual_id}",
            )
        if target_type in _UNSUPPORTED_TARGET:
            return self._unsupported(
                "無法轉成 KPI 卡或地圖（需要不同的查詢結構）。",
                target_scope=f"visual:{visual_id}",
            )
        if target_type == VisualType.pivot and len(visual.query.dimensions) < 2:
            return self._unsupported(
                "樞紐分析需要兩個維度（例如「各區 × 各班別」）；請先用分組加入第二個維度。",
                target_scope=f"visual:{visual_id}",
            )
        if current_type == target_type:
            notes = [f"Visual '{visual_id}' is already a {target_type.value}."]
            intent = AIIntent(
                intent_kind="style_change",
                target_scope=f"visual:{visual_id}",
                trust_notes=notes,
                risk_level="low",
            )
            return NL2ProposalResult(
                intent=intent,
                message=f"Visual '{visual_id}' is already a {target_type.value}.",
                trust_notes=notes,
                risk_level="low",
            )

        path = f"pages/{page_id}/visuals/{visual_id}/visualization/visual_type"
        notes = [
            f"Grounded to visual '{visual_id}' ({current_type.value}).",
            "Only bar ↔ line conversions are allowed; query semantics are unchanged.",
            "Presentation-only change: no data re-query required.",
        ]
        proposal = ReportProposal(
            description=f"Change chart type from {current_type.value} to {target_type.value}",
            changes=[
                ReportChange(
                    path=path,
                    label="Chart type",
                    before=current_type.value,
                    after=target_type.value,
                    affects_data=False,
                )
            ],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="style_change",
            target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message="Chart type proposal created. Review the diff before applying it.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    # ------------------------------------------------------------------
    # Round 019: dimension_change intent
    # ------------------------------------------------------------------

    def _dimension_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a visual before changing the grouping dimension.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found

        # Detect target date truncation granularity
        truncate_to = _extract_date_granularity(prompt, normalized)
        if truncate_to is None:
            return self._unsupported(
                "Specify a time granularity: month (月份), week (週), day (日), quarter (季), or year (年).",
                target_scope=f"visual:{visual_id}",
            )

        # Derive block_id from the visual's first metric block
        if not visual.query.metrics:
            return self._unsupported(
                "This visual has no metrics; cannot determine the dimension block.",
                target_scope=f"visual:{visual_id}",
            )
        block_id = visual.query.metrics[0].block_id

        # Find a date/time column to group by — use the first time column in current dimensions
        # or fall back to detecting a date column in the existing query dimensions.
        time_column = _find_time_column(visual)
        if time_column is None:
            return self._unsupported(
                "Could not find a time dimension in this visual to apply date grouping.",
                target_scope=f"visual:{visual_id}",
            )

        before_dims = [
            {
                "block_id": d.block_id,
                "column_name": d.column_name,
                "alias": d.alias,
                "truncate_date_to": d.truncate_date_to,
            }
            for d in visual.query.dimensions
        ]
        after_dims = [
            {
                "block_id": d.block_id,
                "column_name": d.column_name,
                "alias": d.alias if d.column_name != time_column else truncate_to.title(),
                "truncate_date_to": d.truncate_date_to if d.column_name != time_column else truncate_to,
            }
            for d in visual.query.dimensions
        ]

        path = f"pages/{page_id}/visuals/{visual_id}/query/dimensions"
        notes = [
            f"Grounded to visual '{visual_id}', time column '{time_column}'.",
            f"Applying date truncation: {truncate_to}.",
            "This change affects the query grouping — numbers will update after approval.",
        ]
        proposal = ReportProposal(
            description=f"Group by {truncate_to} (truncate {time_column})",
            changes=[
                ReportChange(
                    path=path,
                    label=f"Date grouping → {truncate_to}",
                    before=before_dims,
                    after=after_dims,
                    affects_data=True,
                )
            ],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message="Dimension change proposal created. This will re-query after approval.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 019: add_metric intent
    # ------------------------------------------------------------------

    def _add_metric(
        self,
        metric_name: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a visual before adding a metric.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found

        # Governance check: metric must exist in semantic model
        sm_metrics = {m["metric_id"]: m for m in (semantic_model or {}).get("metrics", [])}
        if metric_name not in sm_metrics:
            refusal = GovernanceRefusal(
                reason=f"Metric '{metric_name}' is not in the semantic model. "
                       "Only certified metrics may be added to a report.",
                blocked_terms=[metric_name],
                trust_notes=[
                    "The metric was not found in the semantic model's certified metric list.",
                    "Ask your data team to certify this metric before adding it.",
                ],
                risk_level="high",
            )
            intent = AIIntent(
                intent_kind="unsupported",
                target_scope=f"visual:{visual_id}",
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )
            return NL2ProposalResult(
                intent=intent,
                message=refusal.reason,
                refusal=refusal,
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )

        sm_metric = sm_metrics[metric_name]
        owner_block = sm_metric.get("owner_block", "")

        # Governance check: owner_block must match existing visual block
        visual_block_ids = [ref.block_id for ref in visual.query.block_refs]
        if owner_block not in visual_block_ids:
            refusal = GovernanceRefusal(
                reason=(
                    f"Metric '{metric_name}' belongs to block '{owner_block}', "
                    f"which is not in this visual's block refs {visual_block_ids}. "
                    "Cross-block metric addition requires a certified relationship."
                ),
                blocked_terms=[metric_name, owner_block],
                trust_notes=[
                    f"Owner block '{owner_block}' not in visual block refs.",
                    "Add the block to the visual first, or choose a metric from the same block.",
                ],
                risk_level="high",
            )
            intent = AIIntent(
                intent_kind="unsupported",
                target_scope=f"visual:{visual_id}",
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )
            return NL2ProposalResult(
                intent=intent,
                message=refusal.reason,
                refusal=refusal,
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )

        # Governance check: max metrics per visual
        if len(visual.query.metrics) >= _MAX_METRICS_PER_VISUAL:
            return self._unsupported(
                f"This visual already has {len(visual.query.metrics)} metrics "
                f"(maximum {_MAX_METRICS_PER_VISUAL}). Remove one before adding another.",
                target_scope=f"visual:{visual_id}",
            )

        # Check not already present
        if any(m.metric_name == metric_name for m in visual.query.metrics):
            return self._unsupported(
                f"Metric '{metric_name}' is already in this visual.",
                target_scope=f"visual:{visual_id}",
            )

        before_metrics = [
            {
                "block_id": m.block_id,
                "metric_name": m.metric_name,
                "alias": m.alias,
                "agg_override": m.agg_override.value if m.agg_override else None,
            }
            for m in visual.query.metrics
        ]
        new_metric = {"block_id": owner_block, "metric_name": metric_name, "alias": None, "agg_override": None}
        after_metrics = before_metrics + [new_metric]

        path = f"pages/{page_id}/visuals/{visual_id}/query/metrics"
        notes = [
            f"Adding certified metric '{metric_name}' from block '{owner_block}'.",
            "This change re-queries the visual after approval.",
        ]
        proposal = ReportProposal(
            description=f"Add metric '{metric_name}' to visual '{visual_id}'",
            changes=[
                ReportChange(
                    path=path,
                    label=f"Add metric: {metric_name}",
                    before=before_metrics,
                    after=after_metrics,
                    affects_data=True,
                )
            ],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"Metric '{metric_name}' proposal created. This will re-query after approval.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 027: add_visual — create a new visual on the canvas
    # ------------------------------------------------------------------

    def _add_visual_nl(
        self,
        params: dict,
        report: ExecutableReportSpec,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        from ai4bi.report.builder import build_add_visual_proposal, build_visual_from_selection
        from ai4bi.query_spec import DimensionRef, FilterSpec, FilterOperator
        from dataclasses import replace as _replace

        visual_type_str = (params.get("visual_type") or "bar_chart").lower()
        metric_name = (params.get("metric") or "").strip()
        dimension_kw = (params.get("dimension") or "").strip().lower()
        title = (params.get("title") or "").strip() or None
        step_filter = (params.get("step_filter") or "").strip().upper() or None

        # Map visual_type string to VisualType enum
        _vtype_map = {
            "line_chart": VisualType.line_chart, "line": VisualType.line_chart,
            "bar_chart": VisualType.bar_chart, "bar": VisualType.bar_chart,
            "table": VisualType.table,
            "kpi_card": VisualType.kpi_card, "kpi": VisualType.kpi_card,
            "pie_chart": VisualType.pie_chart, "pie": VisualType.pie_chart,
            "scatter": VisualType.scatter, "scatter_chart": VisualType.scatter,
            "pivot": VisualType.pivot, "matrix": VisualType.pivot,
            "map": VisualType.map, "geo": VisualType.map,  # Round 089
        }
        vtype = _vtype_map.get(visual_type_str, VisualType.bar_chart)

        # Resolve metric → block_id
        sm_metrics = {m.get("metric_id") or m.get("name", ""): m
                      for m in (semantic_model or {}).get("metrics", [])}
        if metric_name not in sm_metrics and contracts:
            # Fallback: scan all block contracts
            for bid, contract in (contracts or {}).items():
                for m in getattr(contract, "metrics", []):
                    if m.name == metric_name:
                        sm_metrics[metric_name] = {"metric_id": metric_name, "owner_block": bid}
                        break
        if metric_name not in sm_metrics:
            return self._unsupported(
                f"指標 '{metric_name}' 不在語意模型中，無法新增圖表。",
                target_scope="canvas",
            )
        sm_entry = sm_metrics[metric_name]
        owner_block = sm_entry.get("owner_block") or sm_entry.get("base_dataset", "")

        # Resolve semantic-model metric_id → block metric name
        # e.g. "avg_queue_time_hr" (sm) → "queue_time_hr" (block formula column)
        if contracts and owner_block in contracts:
            block_contract = contracts[owner_block]
            block_metric_names = [m.name for m in getattr(block_contract, "metrics", [])]
            if metric_name not in block_metric_names:
                # Try extracting column from formula: AVG(queue_time_hr) → queue_time_hr
                import re as _re
                formula = sm_entry.get("formula", "")
                col_match = _re.search(r'\((\w+)\)', formula)
                if col_match and col_match.group(1) in block_metric_names:
                    metric_name = col_match.group(1)
                else:
                    # Fuzzy: find block metric whose name is contained in the sm metric_id
                    for bm in block_metric_names:
                        if bm in metric_name or metric_name.endswith(bm):
                            metric_name = bm
                            break
        if not owner_block:
            return self._unsupported(
                f"找不到指標 '{metric_name}' 的所屬積木。",
                target_scope="canvas",
            )

        # Resolve dimension keyword → "block_id.column_name"
        # Round 035: static map first, then dynamic SchemaIndex fallback
        dim_spec = _DIM_KEYWORD_MAP.get(dimension_kw)
        dimension_names: list[str] = []
        if dim_spec:
            dim_block, dim_col, _dim_alias, _truncate = dim_spec
            dimension_names = [f"{dim_block}.{dim_col}"]
        elif dimension_kw and contracts:
            _idx = SchemaIndex.build(contracts)
            _entry = _idx.find_dim(dimension_kw) or _idx.best_dim_match(
                dimension_kw, dimension_kw.lower()
            )
            if _entry:
                dimension_names = [f"{_entry.block_id}.{_entry.column_name}"]

        # Generate unique visual_id
        existing = set(report.pages.get("main", type("_", (), {"visuals": {}})()).visuals.keys())
        base_id = f"nl_{vtype.value}_{metric_name}"
        visual_id = base_id
        counter = 1
        while visual_id in existing:
            visual_id = f"{base_id}_{counter}"
            counter += 1

        if not contracts:
            return self._unsupported("合約資料尚未載入，無法新增圖表。", target_scope="canvas")

        try:
            query_spec, viz_spec = build_visual_from_selection(
                visual_id=visual_id,
                block_id=owner_block,
                metric_names=[metric_name],
                dimension_names=dimension_names,
                visual_type=vtype,
                contracts=contracts,
                semantic_model=semantic_model,
            )
        except (ValueError, KeyError) as exc:
            return self._unsupported(
                f"無法建立圖表：{exc}",
                target_scope="canvas",
            )

        # Apply optional step filter
        if step_filter:
            from ai4bi.query_spec import FilterSpec, FilterOperator
            from dataclasses import replace as _r
            new_filter = FilterSpec(
                block_id=owner_block,
                column_name="step_id",
                operator=FilterOperator.in_,
                value=[step_filter],
                inherit_global_filter=False,
            )
            query_spec = _r(query_spec, filters=list(query_spec.filters) + [new_filter])

        # Override title if provided
        if title:
            from dataclasses import replace as _r
            viz_spec = _r(viz_spec, title=title)

        proposal = build_add_visual_proposal(
            page_id="main",
            visual_id=visual_id,
            query_spec=query_spec,
            viz_spec=viz_spec,
        )
        notes = [
            f"新增圖表 '{visual_id}' ({vtype.value})，指標：{metric_name}，積木：{owner_block}。",
            f"維度：{dimension_names or '無'}。",
            "確認後圖表會加入報表畫布。",
        ]
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="canvas",
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"新增圖表提案已建立：{title or visual_id}。確認後加入畫布。",
            proposal=proposal,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 027: highlight_outliers — conditional formatting on tables
    # ------------------------------------------------------------------

    def _highlight_outliers(
        self,
        params: dict,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        visual_id = params.get("visual_id") or selected_component_id
        if not visual_id:
            # Auto-detect: find first table visual
            for page in report.pages.values():
                for vid, visual in page.visuals.items():
                    if visual.visualization.visual_type == VisualType.table:
                        visual_id = vid
                        break
                if visual_id:
                    break
        if not visual_id:
            return self._unsupported("找不到表格圖表，請先選擇一個表格。", target_scope="canvas")

        found = _find_visual(report, visual_id)
        if found is None:
            return self._unsupported(f"找不到圖表 '{visual_id}'。", target_scope=f"visual:{visual_id}")
        page_id, visual_id, visual = found

        if visual.visualization.visual_type != VisualType.table:
            return self._unsupported("離群值標色只支援表格類型的圖表。", target_scope=f"visual:{visual_id}")

        column = params.get("column") or None
        method = params.get("method") or "iqr"
        color = params.get("color") or "#FF4444"

        before_extra = dict(visual.visualization.extra)
        after_extra = dict(visual.visualization.extra)
        after_extra["conditional_formats"] = [
            {"column": column, "method": method, "color": color}
        ]
        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/conditional_formats"
        notes = [
            f"對表格 '{visual_id}' 的 {'所有數值欄位' if column is None else column} 套用離群值標色。",
            f"方法：{method}，顏色：{color}。",
            "這是視覺化效果，不影響原始資料。",
        ]
        proposal = ReportProposal(
            description=f"離群值標色（{method}）",
            changes=[ReportChange(
                path=path,
                label="條件格式：離群值",
                before=before_extra.get("conditional_formats"),
                after=after_extra["conditional_formats"],
                affects_data=False,
            )],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="style_change", target_scope=f"visual:{visual_id}", trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message="離群值標色提案已建立。", proposal=proposal, trust_notes=notes, risk_level="low")

    # ------------------------------------------------------------------
    # Round 027: add_trend_line — Plotly trend-line overlay
    # ------------------------------------------------------------------

    def _add_trend_line(
        self,
        params: dict,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        visual_id = params.get("visual_id") or selected_component_id
        if not visual_id:
            for page in report.pages.values():
                for vid, visual in page.visuals.items():
                    if visual.visualization.visual_type in (VisualType.line_chart, VisualType.bar_chart):
                        visual_id = vid
                        break
                if visual_id:
                    break
        if not visual_id:
            return self._unsupported("找不到折線圖，請先選擇一個圖表。", target_scope="canvas")

        found = _find_visual(report, visual_id)
        if found is None:
            return self._unsupported(f"找不到圖表 '{visual_id}'。", target_scope=f"visual:{visual_id}")
        page_id, visual_id, visual = found

        if visual.visualization.visual_type not in (VisualType.line_chart, VisualType.bar_chart):
            return self._unsupported("趨勢線只支援折線圖和長條圖。", target_scope=f"visual:{visual_id}")

        method = params.get("method") or "linear"
        window = int(params.get("window") or 3)
        before_extra = dict(visual.visualization.extra)
        after_extra = dict(before_extra)
        after_extra["trend_line"] = {"method": method, "window": window, "color": "#888888", "dash": "dot"}

        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/trend_line"
        notes = [
            f"在圖表 '{visual_id}' 上加入趨勢線（方法：{method}）。",
            "趨勢線是視覺化覆蓋，不影響查詢資料。",
        ]
        proposal = ReportProposal(
            description=f"加入趨勢線（{method}）",
            changes=[ReportChange(
                path=path,
                label="趨勢線",
                before=before_extra.get("trend_line"),
                after=after_extra["trend_line"],
                affects_data=False,
            )],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="style_change", target_scope=f"visual:{visual_id}", trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=f"趨勢線提案已建立（{method}）。", proposal=proposal, trust_notes=notes, risk_level="low")

    def _governance_refusal(
        self,
        normalized: str,
        semantic_model: dict[str, Any] | None,
    ) -> GovernanceRefusal | None:
        blocked = [pattern for pattern in _SQL_REFUSAL_PATTERNS if re.search(pattern, normalized)]
        if not blocked:
            return None
        policy_note = "Free-form SQL and detail joins must go through certified semantic workflows."
        prohibited = semantic_model.get("prohibited_paths", []) if semantic_model else []
        if "yield" in normalized and prohibited:
            policy_note = "Yield detail joins are prohibited by the semantic model because they can duplicate quality metrics."
        return GovernanceRefusal(
            reason="This request needs a governed metric or certified relationship workflow and cannot be staged as a draft proposal.",
            blocked_terms=_blocked_terms(normalized),
            trust_notes=[
                policy_note,
                "Ask for a governed analysis plan or select certified metrics/dimensions instead.",
            ],
        )

    def _unsupported(
        self,
        message: str,
        *,
        target_scope: str,
        selection: SemanticSelection | None = None,
        disambiguation: str | None = None,
    ) -> NL2ProposalResult:
        notes = ["No report changes were staged."]
        intent = AIIntent(
            intent_kind="unsupported",
            target_scope=target_scope,
            selection=selection or SemanticSelection(),
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=message,
            trust_notes=notes,
            risk_level="medium",
            disambiguation=disambiguation,
        )


def _normalize(prompt: str) -> str:
    return " ".join(prompt.strip().lower().split())


# Round 138: requests that need a capability this tool genuinely does NOT have.
# Returning the nearest metric here is the worst silent-wrong, so we decline
# honestly and say what IS possible. Keep cues specific to avoid over-declining.
_UNSUPPORTED_CAPABILITIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("x-y", "x﹣y", "xy 座標", "座標", "晶圓圖", "wafer map", "晶粒圖", "缺陷分佈圖",
      "缺陷分布圖", "bin map", "晶圓地圖"),
     "目前沒有 wafer 級的 X-Y 晶粒座標 / wafer map 資料，無法畫缺陷空間分佈圖。"
     "現有資料是 lot/wafer 級的良率與缺陷『數量』，我可以給：各機台/各產品的缺陷數 Pareto、"
     "良率 commonality、或缺陷類型佔比與趨勢。"),
    (("逐站列出", "每一站", "每一台機台逐站", "完整路徑", "genealogy", "族譜", "逐站",
      "走過的每一台", "每一台都列"),
     "目前引擎是單一 fact 查詢，無法做 wafer 逐站 genealogy 的 fact-to-fact 明細串接"
     "（治理上禁止會扇出的明細 join）。但我可以用 commonality 分析：給定不良批，"
     "找出它們最常共同經過、且統計顯著（Fisher 檢定）的機台。"),
    # Round 178: bare "元" removed — it false-matched 元兇/元件/還原 and hijacked
    # commonality ("低良率的元兇") into a money refusal.
    (("成本", "金額", "費用", "損失多少錢", "cost", "scrap cost", "報廢成本", "$",
      "美元", "台幣", "多少錢", "塊錢"),
     "目前資料集沒有成本/金額欄位（只有良率、缺陷數、queue/cycle time 等製造指標），"
     "無法換算金錢損失。我可以給：報廢/不良晶圓『數量』、良率損失、缺陷數，"
     "若你提供單片成本，我再幫你乘上數量估算。"),
    # Round 186 (CV S11): I work on TABLES, not pixels. A "show me the blurry
    # images / let me look at the photos" ask is a hard boundary — but turn it
    # into what IS possible: rank by a quantifiable quality column to shortlist.
    (("看圖", "看影像", "看照片", "看這些圖", "顯示影像", "顯示圖", "秀出圖", "秀圖",
      "秀給我看", "打開圖", "點開圖", "圖片給我看", "給我看圖", "給我看這些圖", "縮圖",
      "原圖", "畫質", "清晰度", "像素", "目視", "肉眼", "影像模糊", "圖片模糊",
      "模糊的影像", "模糊的圖", "很模糊", "糊掉", "挑出來看", "挑出來人工看"),
     "我分析的是『資料表』不是影像像素，沒辦法直接顯示圖片或判斷模糊/清晰——那需要 "
     "CV 標註/檢視工具（如 FiftyOne、CVAT）。但只要表裡有可量化的品質欄位，例如 "
     "blur_score（模糊分數）、qc_flag（品質旗標）、iou（標註一致性）、confidence（信心），"
     "我就能幫你排序、篩出『最該人工複檢的前 N 張』，把要看的範圍縮到最小。"),
)


def _honest_limitation(prompt: str, normalized: str) -> str | None:
    """Return an honest 'can't do that, but here's what I can' message when the
    request needs an unsupported capability (wafer map / genealogy detail join)."""
    hay = f"{prompt.lower()} {normalized}"
    for cues, message in _UNSUPPORTED_CAPABILITIES:
        if any(c in hay for c in cues):
            return message
    return None


# Round 135: vague evaluative terms that could map to several governed analyses.
# When such a term is the gist of an otherwise-unroutable prompt, return a
# clarifying question instead of a silent wrong guess (the product-lens #1 risk).
_AMBIGUOUS_TERMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("效率", "efficiency", "效能"),
     "「效率」可以指好幾種分析，您想看哪一個？(1) 設備 OEE　(2) 產能利用率/loading　"
     "(3) 瓶頸或 cycle time　(4) 產出率 moves/hr。請指定其一，我就能給可信的數字。"),
    (("提升產量", "增加產量", "提高產量", "拉高產量", "增加產出", "提升產能",
      "怎麼提升", "如何提升", "怎麼改善", "如何增加產"),
     "要提升產量，先看哪個切入點？(1) 找瓶頸站（依佇列時間/利用率）　(2) 產能餘裕/距滿載缺口　"
     "(3) OEE 損失拆解（可用率/表現/良率哪個拖累）　(4) WIP↔cycle time。選一個我就能定位。"),
    (("表現", "績效", "performance", "怎麼樣", "怎樣", "如何", "好不好", "狀況"),
     "想了解「表現」的哪個面向？可選：良率、queue time、OEE、產能利用率、瓶頸、缺陷率。"
     "指定指標（與要看的維度，如各機台/各區/各週）我就能分析。"),
)


def _parse_threshold(hay: str) -> float | None:
    """Round 137: extract a numeric threshold from a prompt, ignoring digits that
    are part of an identifier like "ETCH-02". Priority: number after a comparison
    cue, then number before %, then a bare number not glued to letters/hyphens."""
    cues = r"(?:低於|小於|以下|大於|高於|超過|至少|不到|below|under|above|over|less than|<|>|=)"
    m = re.search(cues + r"\s*(\d+(?:\.\d+)?)\s*%?", hay)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", hay)  # "80%" / "80 %"
    if m:
        return float(m.group(1))
    # bare number, but not one preceded by a letter/hyphen (so "etch-02" is skipped)
    m = re.search(r"(?<![\w-])(\d+(?:\.\d+)?)(?![\w-])", hay)
    return float(m.group(1)) if m else None


def _provenance_note(contracts, block_id: str, date_col: str | None,
                     metric_name: str = "") -> str | None:
    """Round 135: build a population/method/exclusions provenance line for an
    answer. States N rows, the date span, and the aggregation method (so a
    weighted yield isn't mistaken for a simple average)."""
    if not contracts or block_id not in contracts:
        return None
    try:
        from ai4bi.blocks.datastore import materialize_dataframe
        df = materialize_dataframe(contracts[block_id])
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None
    n = len(df)
    grain = ("片晶圓" if "wafer_id" in df.columns and df["wafer_id"].nunique() == n
             else "筆")
    span = ""
    if date_col and date_col in df.columns:
        try:
            import pandas as _pd
            d = _pd.to_datetime(df[date_col], errors="coerce").dropna()
            if not d.empty:
                span = f"，期間 {d.min().date()}～{d.max().date()}"
        except Exception:  # noqa: BLE001
            span = ""
    method = ""
    if "weighted_yield" in metric_name.lower() or metric_name.lower() == "weighted_yield_pct":
        method = "；方法＝SUM(良品)/SUM(受測晶粒)（以晶粒數加權，非各晶圓良率的簡單平均）"
    return (f"母體：N={n} {grain}（{block_id}）{span}{method}"
            f"；未套用額外排除規則，null 值不計入彙總。")


# Round 136: follow-up scope refinement cues. A short prompt carrying one of
# these is a continuation of the prior analysis, not a fresh question.
_FOLLOWUP_CUES: tuple[str, ...] = (
    "只看", "只要看", "只要", "看 ", "那 ", "改看", "改成只看", "換成", "改用",
    "filter to", "just ", "only ", "what about", "how about", "限定", "聚焦",
)
_FOLLOWUP_STRIP = ("只看", "只要看", "只要", "改看", "改成只看", "換成看", "換成",
                   "改用", "限定", "聚焦", "看", "那", "呢", "就好", "的話",
                   "filter to", "just", "only", "what about", "how about",
                   "?", "？", "、", "，", ",", "。", " 區", "區")


def _looks_like_followup_scope(prompt: str, normalized: str) -> bool:
    """A short continuation like "只看 ETCH 呢？" / "那 PHOTO 呢" / "just ETCH"."""
    hay = f"{prompt.lower()} {normalized}"
    if len(prompt.strip()) > 24:  # follow-ups are short; long prompts are fresh asks
        return False
    return any(c in hay for c in _FOLLOWUP_CUES)


def _extract_followup_value(prompt: str) -> str | None:
    """Strip the refinement cue words, leaving the value to scope to (e.g. ETCH)."""
    s = prompt.strip()
    for tok in _FOLLOWUP_STRIP:
        s = s.replace(tok, " ")
    s = " ".join(s.split())
    return s or None


def _ambiguous_clarification(prompt: str, normalized: str) -> str | None:
    """Return a clarifying question when the prompt is a vague evaluative ask.

    Only reached after all handlers declined, so it won't shadow real routes.
    Requires the prompt be short-ish and lack a concrete metric cue, so a
    specific question that merely failed to route isn't turned into a clarify.
    """
    hay = f"{prompt.lower()} {normalized}"
    # If a concrete fab metric is already named, this isn't "vague" — let the
    # plain unsupported message stand (the user was specific; routing has a gap).
    concrete = ("良率", "yield", "queue", "等待", "缺陷", "defect", "oee", "利用率",
                "cycle", "週期", "wip", "重工", "rework", "良品", "稼動")
    if any(c in hay for c in concrete):
        return None
    for terms, question in _AMBIGUOUS_TERMS:
        if any(t in hay for t in terms):
            return question
    return None


# ---------------------------------------------------------------------------
# Round 078: direct-answer engine helpers
# ---------------------------------------------------------------------------

# Explicit question markers. An imperative edit ("加一張營收圖") has none of these,
# so gating on them keeps the answer engine from stealing edit commands.
_QUESTION_MARKERS: tuple[str, ...] = (
    "多少", "幾", "是多少", "有多少", "總共", "共有", "平均是", "占比", "佔比",
    "為何", "為什麼", "?", "？",
    "how much", "how many", "what is", "what's", "what was", "what are",
    "tell me", "show me the", "total of", "average of", "sum of",
    # Round 184 (S17): period-comparison phrasings ("本期 vs 上期 / 環比") that
    # carry no "多少/?" but still ask for the current-vs-prior number.
    "環比", "比上期", "跟上期", "和上期", "與上期", "本期比", "這期比", "跟之前比", "和之前比",
)

_PERIOD_TITLE: dict[str, str] = {
    "week": "最近 7 天", "month": "最近 30 天", "quarter": "最近 90 天", "year": "最近 12 個月",
}


def _looks_like_metric_question(prompt: str, normalized: str) -> bool:
    """True when the prompt reads as a question asking for a metric value."""
    hay = f"{prompt.lower()} {normalized}"
    return any(marker in hay for marker in _QUESTION_MARKERS)


def _extract_answer_period(normalized: str, prompt: str) -> str:
    """Map a time phrase to a trailing-window period, else 'all' (whole period)."""
    hay = f"{prompt.lower()} {normalized}"
    # Round 184 (S17): vague "最近一段 vs 前一段 / 近期 vs 前期 / 本期 vs 上期 / 環比 /
    # 最近這幾週跟之前" → compare the recent trailing window against the prior one.
    if any(t in hay for t in ("最近一段", "前一段", "上一段", "近期", "前期",
                              "最近這幾週", "最近幾週", "跟之前", "和之前", "比之前", "與之前",
                              "本期", "這期", "上期", "環比", "這期比", "本期比")):
        return "week"
    if any(t in hay for t in ("本週", "這週", "上週", "這周", "上周", "this week", "last week", "wow", "最近 7", "最近7", "近 7", "近7", "7 天", "7天")):
        return "week"
    if any(t in hay for t in ("本月", "這個月", "上個月", "當月", "this month", "last month", "mom", "最近 30", "最近30", "近 30", "近30", "30 天", "30天")):
        return "month"
    if any(t in hay for t in ("本季", "這季", "上季", "季度", "this quarter", "last quarter", "qtd", "qoq", "90 天", "90天")):
        return "quarter"
    if any(t in hay for t in ("今年", "去年", "全年", "年度", "this year", "last year", "yoy", "ytd", "12 個月", "12個月")):
        return "year"
    return "all"


def _find_date_column(contracts: dict[str, Any] | None, block_id: str) -> str | None:
    """Find the best date column on a block's contract for period filtering."""
    if not contracts or block_id not in contracts:
        return None
    contract = contracts[block_id]
    cols = getattr(contract, "columns", None) or []
    for col in cols:
        if getattr(col, "data_type", None) in ("date", "timestamp", "datetime"):
            return col.name
    for col in cols:
        name = col.name.lower()
        if any(t in name for t in ("date", "_at", "time", "_dt", "_ts", "day")):
            return col.name
    return None


def _metric_unit(contracts: dict[str, Any] | None, block_id: str, metric_name: str) -> str:
    """Return the metric's declared unit (e.g. 'NT$', '%') for formatting."""
    if not contracts or block_id not in contracts:
        return ""
    for m in getattr(contracts[block_id], "metrics", None) or []:
        if getattr(m, "name", None) == metric_name:
            return getattr(m, "unit", "") or ""
    return ""


def _first_scalar(df, col: str) -> float | None:
    """Pull the single aggregate value out of a one-row result frame."""
    if df is None or getattr(df, "empty", True):
        return None
    use = col if col in df.columns else (df.columns[-1] if len(df.columns) else None)
    if use is None:
        return None
    try:
        import pandas as pd  # local import keeps module import light
        val = df[use].iloc[0]
        return None if pd.isna(val) else float(val)
    except (ValueError, TypeError, IndexError):
        return None


def _format_metric_value(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:,.1f}%"
    if unit in ("NT$", "$", "USD", "TWD"):
        prefix = "NT$" if unit in ("NT$", "TWD") else "$"
        return f"{prefix}{value:,.0f}"
    if abs(value - round(value)) < 1e-9:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


# --- Round 087: Top-N ranking ("best / worst") parsing -----------------------

_RANK_TRIGGERS: tuple[str, ...] = (
    "最高", "最低", "最多", "最少", "最賺", "最好", "最差", "最大", "最小",
    "最長", "最久", "最短", "最快", "最慢", "最忙", "最閒", "最嚴重", "最常",
    "賣最", "排名", "排行", "前幾", "前十", "前五", "前三",
    "top ", "bottom ", "best ", "worst ", "highest", "lowest", "ranking", "rank ",
    "longest", "shortest", "slowest", "fastest", "most ", "least ",
    # Round 178 (S2/S4): colloquial superlatives that were missing from the gate.
    # (NOT "主要是哪/主要有哪" — those clash with decomposition "主要是哪個…造成".)
    "最爛", "最佳", "最主要", "佔大宗", "占大宗",
    # Round 182 (S4): "主要不良項目有哪些 / 主要缺陷 / 主要壞在哪" → ranked defect list.
    "主要不良", "主要缺陷", "不良項目", "缺陷項目", "不良類型", "缺陷種類", "主要的不良",
    "缺陷主要", "不良主要", "瑕疵主要", "壞在哪", "主要壞", "壞最多", "哪種缺陷",
    "哪些缺陷", "哪種不良", "哪種瑕疵", "哪些不良",
    # Round 182 (S2): "tool matching / 機台比對 / 機台良率比較" → compare/rank tools.
    "tool matching", "toolmatching", "tool-matching", "機台比對", "機台對比", "機台匹配",
    "機台之間", "機台間", "機台良率差異", "各機台良率差異", "機台的良率差異",
    "機台良率比較", "機台比較", "兩台機台", "兩台etch", "兩台 etch", "各機台比較",
    # Round 184 (S08): explicit sort wording ("由多到少/由大到小/降序排列").
    "由多到少", "由大到小", "由高到低", "從多到少", "從大到小", "從高到低",
    "降序", "遞減排序", "排序",
)
_RANK_ASC_WORDS: tuple[str, ...] = (
    "最低", "最少", "最差", "最小", "最短", "最快", "最閒", "賣最差", "賣最少", "最不", "墊底",
    "bottom", "worst", "lowest", "least", "fewest", "shortest", "fastest",
    # Round 178 (S2): non-superlative "worse/lower" comparatives must sort ASC
    # ("哪台良率比較差" was wrongly returning the highest). Avoid bare 差/低 (clash
    # with 差多少/差異) — use the explicit comparative forms.
    "比較差", "較差", "比較爛", "較爛", "最爛", "比較低", "較低", "比較少", "較少",
    "差的", "低的", "爛的", "表現差", "表現最差", "比較慢", "較慢", "比較短", "較短",
    # Round 182 (S2): more "underperforming" synonyms map to worst-first sort.
    "不理想", "表現不好", "表現最不好", "不好", "最不好", "不佳", "較不理想", "比較不理想",
    # "拉低/拖累 良率" → the culprit group is the LOWEST one.
    "拉低", "拖累", "害良率",
    # Round 182 (S2): "哪台需要關注/要注意" — the one needing attention is the worst.
    "需要關注", "要注意", "該注意", "該關注", "需要注意", "要關注",
    # "tool matching / 機台比對" surfaces the yield-mismatched (lowest) tool first.
    "tool matching", "toolmatching", "tool-matching", "機台比對", "機台對比", "機台匹配",
)


_BREAKDOWN_MARKERS: tuple[str, ...] = (
    "各", "每個", "每一", "每種", "每類", "依", "按", "照", "分布", "分佈", "分組",
    " by ", " per ", "breakdown", "group by", "分別",
    "產品別", "機台別", "班別", "區域別", "廠別", "站別",  # Round 182 (S5): "X別" = by X
    "占比", "佔比", "比重", "占總", "佔總",  # Round 127: share questions
    "佔全", "占全", "佔多少", "占多少", "佔了",  # Round 129: 佔全廠 share
)
_EDIT_VERBS: tuple[str, ...] = ("改成", "換成", "改為", "改用", "變成", "change to", "switch to")


def _looks_like_breakdown(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(v in hay for v in _EDIT_VERBS):
        return False  # "改成依月份" is an edit, not a breakdown answer
    return any(m in hay for m in _BREAKDOWN_MARKERS)


_MATRIX_CUES: tuple[str, ...] = (
    "在不同", "交叉", "矩陣", "樞紐", "cross", "matrix", "pivot", "×", " x ",
    "對照", "各...在", "依...與", "兩個維度",
    # Round 186 (CV S9): a confusion question is a true_class × pred_class cross-tab.
    "混淆", "搞混", "搞錯成", "誤判成", "認錯", "被預測成", "預測成", "confusion",
)
_MULTI_FILTER_CUES: tuple[str, ...] = (
    "且", "並且", "而且", "同時", " and ", "又", "兼",
)


def _looks_like_matrix(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _MATRIX_CUES):
        return True
    # "各 X ... 不同 Y" pattern (two dimension words around 不同)
    if "各" in hay and "不同" in hay:
        return True
    # Round 186: "各 X 在 A 跟 B" names the SECOND axis by its values ("各 class 在
    # train 跟 val", "各類別在 v1 跟 v2") — a cross-tab. Needs a per-group marker +
    # 在 + a list separator; the handler returns None (→ breakdown) if no real 2nd
    # dimension resolves, so this can't manufacture a wrong matrix.
    if (("各" in hay or "每" in hay) and "在" in hay
            and any(s in hay for s in ("跟", "和", "與", " vs ", "、"))):
        return True
    # Round 139: "各X、各Y" / "每X每Y" — two grouped dimensions = a cross-tab.
    return prompt.count("各") >= 2 or prompt.count("每") >= 2


_MF_AREA_WORDS = ("etch", "litho", "cmp", "implant", "thinfilm", "photo", "區")
_MF_COND_WORDS = ("hot", "normal", "急件", "趕貨", "一般批", "重工", "rework",
                  "hold", "保留", "夜班", "日班", "白班", "晚班", "優先", "priority")


def _looks_like_multi_filter(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _MULTI_FILTER_CUES):
        return True
    # Round 139: implicit two-condition scope ("ETCH 區 Hot 批的…") with no 且.
    return any(a in hay for a in _MF_AREA_WORDS) and any(c in hay for c in _MF_COND_WORDS)


def _resolve_n_dims(idx, prompt: str, normalized: str, contracts, block_id: str, n: int = 2) -> list:
    """Resolve up to ``n`` DISTINCT categorical columns on ``block_id`` that the
    prompt references, longest keyword first."""
    hay = f"{prompt.lower()} {normalized}"

    def _is_cat(col: str) -> bool:
        return _is_categorical_col(contracts, block_id, col)

    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for kw, entry in idx._dims.items():
        col = entry.column_name
        if kw in hay and _is_cat(col) and col not in seen:
            scored.append((len(kw), col))
    # keep the longest-keyword match per column, then take top n distinct columns
    best_per_col: dict[str, int] = {}
    for ln, col in scored:
        best_per_col[col] = max(best_per_col.get(col, 0), ln)
    ordered = sorted(best_per_col.items(), key=lambda kv: kv[1], reverse=True)
    return [col for col, _ in ordered[:n]]


_SHARE_MARKERS = ("佔總", "占總", "比重", "佔全", "占全", "佔多少", "占多少", "佔了")


def _looks_like_ranking(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    # Round 129: a "...佔總比重" question is about share-of-total, not a Top-N cut —
    # let breakdown (which adds the 佔總比% column) handle it.
    if any(s in hay for s in _SHARE_MARKERS):
        return False
    if any(t in hay for t in _RANK_TRIGGERS):
        return True
    # Round 178 (S2): "哪台/哪個…好/高/差/低" is a rank-by-entity request even
    # without an explicit superlative (最高/最低). Pair a "which-one" word with a
    # comparative — but NOT in a change/period context ("比上週高…哪個 area 造成"
    # is a decomposition, not a ranking), so guard against those cues.
    which = any(w in hay for w in ("哪台", "哪臺", "哪個", "哪一", "哪部", "哪區",
                                   "哪站", "which", "誰"))
    comp = any(c in hay for c in ("好", "佳", "高", "差", "低", "長", "短", "慢", "快",
                                  "多", "少", "嚴重", "不理想", "不佳", "理想", "久",
                                  "需要關注", "要注意", "該注意", "該關注", "需要注意"))
    change_ctx = any(t in hay for t in (
        "比上", "比前", "比這", "升高", "升至", "變化", "造成", "原因", "為什麼", "為何",
        "拆解", "上週", "上周", "上月", "去年同期", "vs 上", "相比"))
    if which and comp and not change_ctx:
        return True
    # Round 182 (S2): an entity + a worst/best word with no explicit "哪" is still
    # a ranking ("良率比較差的機台", "表現不好的機台", "不理想的 chamber"). Same
    # change-context guard so a period/why question isn't grabbed.
    entity = any(e in hay for e in (
        "機台", "機臺", "設備", "機器", "chamber", "腔", "tool", "產品", "品類",
        "product", "站", "step", "區", "area", "批", "lot", "vendor", "供應商"))
    rankword = any(w in hay for w in (
        "最差", "最爛", "最低", "最高", "最好", "最佳", "最不", "比較差", "較差",
        "比較好", "較好", "比較高", "較高", "比較低", "較低", "差的", "低的", "高的",
        "好的", "不理想", "表現差", "表現好", "表現不好", "表現最不好", "排名", "排序"))
    if entity and rankword and not change_ctx:
        return True
    # "前 5 名 / top 5" expressed with a number.
    return bool(re.search(r"(前\s*\d+|top\s*\d+|bottom\s*\d+)", hay))


def _ranking_is_ascending(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(w in hay for w in _RANK_ASC_WORDS)


def _extract_rank_n(prompt: str, normalized: str, default: int = 5) -> int:
    hay = f"{prompt.lower()} {normalized}"
    m = re.search(r"(?:前|top|bottom|前面|頭)\s*(\d+)", hay)
    if m is None:
        m = re.search(r"(\d+)\s*(?:個|名|筆|項|大|台|家|站|種|款|支|組|個商品|個地區|台機台)", hay)
    if m:
        try:
            n = int(m.group(1))
            return max(1, min(n, 100))
        except ValueError:
            pass
    return default


# --- Round 108: two-entity comparison ----------------------------------------

# Unambiguous compare cues (so "營收和訂單" — a list, not a comparison — is ignored).
_COMPARE_CUES = ("比較", "對比", "相比", "比一比", " vs ", " versus ", " v.s ", "對上", "比起",
                 "差多少", "相差", "差異", "快多少", "慢多少", "高多少", "低多少",
                 "哪個比較", "誰比較", "哪個快", "哪個高", "哪個低")
_COMPARE_CONNECTORS = (" vs ", " versus ", " v.s ", "對上", "對比", "相比", "比起",
                       "跟", "和", "與", "還是", "、", "對")


# Guard: 比 must NOT be 比較 (=compare) nor a period comparison (比上週/比去年/…),
# so this only matches a true "entity A 比 entity B {comparative}" (Round 178 S5).
_BI_COMPARE_RE = re.compile(
    r"([A-Za-z一-鿿][\w-]*?)\s*比(?!較|\s*上|\s*去|\s*前|\s*本|\s*這|\s*今|\s*昨|\s*同期)\s*"
    r"([A-Za-z一-鿿][\w-]*?)(?:的[^比]*?)?\s*(差|好|高|低|嚴重|長|短|快|慢|多|少)(?:嗎|呢|啊|\?|？|$|，|。| )")


def _looks_like_entity_compare(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _COMPARE_CUES):
        return True
    # Round 178 (S5): "X 比 Y 差/好/高/低…" — guarded by a trailing comparative so
    # 比較 / 比率 / 百分比 don't false-trigger.
    if _BI_COMPARE_RE.search(prompt) or _BI_COMPARE_RE.search(normalized):
        return True
    # "X 和/跟/與 Y 哪個/誰 … 高/低/好/差" two-entity pick-best.
    return bool(re.search(
        r"(和|跟|與|vs)\S{0,12}?(哪個|哪一個|誰|哪邊)\S{0,8}?(高|低|好|差|快|慢|多|少|長|短|爛|佳)", hay))


# Chinese classifiers/units that trail an operand and should be dropped, so
# "Hot 批" / "ETCH 站" → "Hot" / "ETCH". (Round 119)
_OPERAND_CLASSIFIERS = frozenset({
    "批", "批號", "個", "台", "站", "區", "顆", "片", "組", "群", "類", "種", "家", "間",
    "班", "班別", "機台", "設備", "產品",
    "的", "區的", "平均", "差", "差多少", "相差", "queue", "time", "良率", "rate",
    "移動次數", "誰比較高", "誰比較低", "誰較高", "比較高", "move", "count",
})


def _clean_operand(s: str, side: str) -> str | None:
    s = s.strip(" ,。，?？!！的")
    for w in ("請比較", "幫我比較", "比較一下", "比一比", "比較", "看看", "對比一下",
              "對比", "誰的", "哪個", "哪一個", "compare", "誰", "的"):
        s = s.replace(w, " ")
    parts = [p for p in re.split(r"[的\s,，、]+", s) if p]
    # drop trailing/leading classifier+unit tokens so the real operand surfaces
    parts = [p for p in parts if p not in _OPERAND_CLASSIFIERS]
    if not parts:
        return None
    return parts[-1] if side == "left" else parts[0]


def _extract_compare_operands(prompt: str, normalized: str) -> "tuple[str, str] | None":
    text = prompt.strip()
    # Round 178 (S5): "X 比 Y 差/好/…" (guarded by a trailing comparative) before
    # the generic connectors, so "memory 比 logic 差嗎" yields ("memory","logic").
    for src in (text, normalized):
        m = _BI_COMPARE_RE.search(src)
        if m and m.group(1) != m.group(2):
            return m.group(1), m.group(2)
    for conn in _COMPARE_CONNECTORS:
        i = text.find(conn)
        if i > 0:
            a = _clean_operand(text[:i], "left")
            b = _clean_operand(text[i + len(conn):], "right")
            if a and b and a != b and len(a) >= 1 and len(b) >= 1:
                return a, b
    return None


# --- Round 105: postprocess / forecast analytics charts ----------------------

_PARETO_TRIGGERS = ("pareto", "柏拉圖", "柏拉图", "帕累托", "帕雷托", "abc 分析", "abc分析", "80/20", "80-20",
                    "關鍵少數", "关键少数", "重要少數", "80%的營收", "8 成", "八成",
                    # Round 178 (S4): textbook cumulative-share phrasings.
                    "累積80", "累積 80", "累計80", "累計 80", "累積佔", "累積占", "累計佔",
                    "累積百分", "累積比例", "cumulative", "貢獻80", "佔80")
_SHARE_TRIGGERS = ("佔總比", "占總比", "佔比", "占比", "百分比", "% of total", "share of total",
                   "占總", "佔總", "比重", "佔多少比例", "占多少比例")
_MOVING_AVG_TRIGGERS = ("移動平均", "移动平均", "moving average", "moving avg", "平滑", "smooth",
                        "均線", "ma 線", "ma線", "走勢")
_FORECAST_TRIGGERS = ("預測", "预测", "forecast", "未來幾", "未来几", "推估", "外推",
                      "下個月會", "預估", "project", "下個月", "下月", "下週", "下周",
                      "照這個趨勢", "依這個趨勢", "按這個趨勢", "大概多少", "會是多少",
                      "估計", "估算未來")


_CHART_VERBS: tuple[str, ...] = ("圖", "chart", "視覺", "畫", "plot", "graph", "視覺化")


def _detect_analytics_chart(hay: str) -> str | None:
    if any(t in hay for t in _PARETO_TRIGGERS):
        return "pareto"
    # forecast before moving_avg so '趨勢並預測' is a forecast, not just smoothing.
    if any(t in hay for t in _FORECAST_TRIGGERS):
        return "forecast"
    if any(t in hay for t in _MOVING_AVG_TRIGGERS):
        return "moving_avg"
    # '趨勢/走勢' over time → smoothed trend, but NOT '趨勢線' (an overlay edit) and
    # NOT when a forecast was asked. Require a time word so it's a time trend.
    if (("趨勢" in hay or "trend" in hay) and "趨勢線" not in hay and "trend line" not in hay
            and any(t in hay for t in ("週", "周", "日", "月", "每", "天", "daily", "weekly", "monthly"))):
        return "moving_avg"
    # Round 120: a plain "占比/share" question is answered inline (breakdown +
    # share %); only build a chart proposal when a chart is explicitly asked for.
    if any(t in hay for t in _SHARE_TRIGGERS) and any(v in hay for v in _CHART_VERBS):
        return "share"
    return None


def _extract_analytics_n(prompt: str, normalized: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:期|個月|個週|週|周|months?|weeks?|points?)", f"{prompt} {normalized}")
    if m:
        try:
            return max(1, min(int(m.group(1)), 52))
        except ValueError:
            return None
    return None


def _unique_id(base: str, existing: set) -> str:
    vid, c = base, 1
    while vid in existing:
        vid = f"{base}_{c}"; c += 1
    existing.add(vid)
    return vid


# --- Round 100: calendar YoY (same period last year) -------------------------

_CALENDAR_YOY_TRIGGERS: tuple[str, ...] = (
    "同期", "去年同月", "去年同季", "去年同期", "同月去年", "年增率", "年增",
    "same month last year", "same period last year", "same quarter last year",
    "year over year", "year-over-year", "vs last year", "yoy vs",
)


def _looks_like_calendar_yoy(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(t in hay for t in _CALENDAR_YOY_TRIGGERS)


# --- Round 097: digest / anomaly insight routing -----------------------------

_DIGEST_TRIGGERS: tuple[str, ...] = (
    "摘要", "總結", "重點", "概況", "整體狀況", "本週如何", "近況", "給我重點",
    "summary", "digest", "overview", "tldr", "recap", "how are we doing",
)
_ANOMALY_TRIGGERS: tuple[str, ...] = (
    "異常", "不對勁", "怪怪", "有什麼問題", "哪裡有問題", "可疑", "outlier",
    "anomaly", "anomalies", "anything wrong", "what's off", "unusual",
    # Round 184 (S15): colloquial "anything to watch / worth noting" entries.
    "要注意", "該注意", "值得注意", "注意的問題", "需要注意", "要留意", "要關心",
)


def _looks_like_insights(prompt: str, normalized: str) -> str | None:
    hay = f"{prompt.lower()} {normalized}"
    # Round 184 (S10): a specific yield-EXCURSION ask ("良率異常下掉的批次") belongs
    # to the excursion handler (which names the actual lots + timing), not the
    # generic anomaly digest — defer so excursion can claim it.
    if _looks_like_excursion(prompt, normalized) and any(
            t in hay for t in ("良率", "yield", "批", "wafer", "晶圓", "lot")):
        return None
    if any(t in hay for t in _ANOMALY_TRIGGERS):
        return "anomaly"
    if any(t in hay for t in _DIGEST_TRIGGERS):
        return "digest"
    return None


# --- Round 096: weekday / hour seasonality parsing ---------------------------

_DOW_TRIGGERS: tuple[str, ...] = (
    "星期幾", "週幾", "周幾", "禮拜幾", "星期", "哪一天", "哪幾天", "哪天最",
    "day of week", "weekday", "busiest day", "which day", "by day of week",
)
_HOUR_TRIGGERS: tuple[str, ...] = (
    "時段", "幾點", "哪個小時", "哪個時間", "哪個時段", "busiest hour",
    "what hour", "time of day", "by hour", "peak hour",
)


def _looks_like_seasonality(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(t in hay for t in _DOW_TRIGGERS) or any(t in hay for t in _HOUR_TRIGGERS)


def _is_hour_seasonality(hay: str) -> bool:
    return any(t in hay for t in _HOUR_TRIGGERS)


# --- Round 091: cold-start grouped measure filter ("buyers with > N orders") -

_ENTITY_CUE_HINTS: tuple[str, ...] = (
    "客戶", "顧客", "會員", "customer", "member", "buyer", "client",
    "商品", "產品", "品項", "product", "item", "sku", "門市", "store",
    # Round 121: fab entities
    "lot", "批", "批號", "wafer", "晶圓", "機台", "設備", "tool", "製程", "站", "step",
)
_COUNT_CUE_HINTS: tuple[str, ...] = (
    "次", "筆", "訂單", "下單", "購買", "買", "回購", "單",
    "times", "orders", "order", "purchase", "bought", "transactions",
)


def _looks_like_segment_count(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if _measure_operator(hay) is None or re.search(r"\d", hay) is None:
        return False
    # An entity to group by + a comparison + a number is enough — the threshold
    # may be on a count (買超過 3 次) OR any measure (queue > 5 小時的 lot).
    return any(h in hay for h in _ENTITY_CUE_HINTS)


def _best_metric_on_block(idx, prompt: str, normalized: str, block_id: str):
    """Round 124: best metric the prompt names that lives ON ``block_id``."""
    hay = f"{prompt.lower()} {normalized}"
    best, best_key = None, (0, 0)
    for entry, kws in getattr(idx, "_metric_keywords", []):
        if entry.block_id != block_id:
            continue
        matched = [k for k in kws if k in hay]
        if not matched:
            continue
        key = (len(matched), max(len(k) for k in matched))
        if key > best_key:
            best_key, best = key, (entry.metric_name, entry.alias)
    return best


def _entity_col_on_block(idx, prompt: str, normalized: str, contracts, block_id: str) -> str | None:
    """Resolve the categorical entity dimension on a specific block (Round 122)."""
    return _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)


def _resolve_entity_dimension(idx, prompt: str, normalized: str, contracts):
    """Pick the categorical entity dimension to group by (customer / product …)."""
    hay = f"{prompt.lower()} {normalized}"
    best, best_block, best_len = None, None, 0
    for kw, e in idx._dims.items():
        if (kw in hay and _is_categorical_col(contracts, e.block_id, e.column_name)
                and len(kw) > best_len):
            best, best_block, best_len = e.column_name, e.block_id, len(kw)
    return best, best_block


def _default_count_metric(contracts, block_id: str):
    """A count-like metric on the block (orders/count), else the first SUM metric."""
    contract = (contracts or {}).get(block_id)
    metrics = getattr(contract, "metrics", None) or []
    for m in metrics:
        nm = m.name.lower()
        meth = getattr(getattr(m, "disaggregation_method", None), "value", "")
        if meth == "count" or any(t in nm for t in ("count", "order", "orders", "qty", "quantity", "次", "筆")):
            return m.name, m.name.replace("_", " ").title()
    for m in metrics:
        if getattr(getattr(m, "disaggregation_method", None), "value", "") == "sum":
            return m.name, m.name.replace("_", " ").title()
    return None


# --- Round 090: per-group Top-N parsing --------------------------------------

_PER_GROUP_MARKERS: tuple[str, ...] = (
    "每個", "每一個", "每家", "每間", "每位", "各個", "各家", "各",
    "per ", "each ", "within each", "by each", "for each",
)


def _looks_like_grouped_topn(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if not any(m in hay for m in _PER_GROUP_MARKERS):
        return False
    # Needs a ranking cue too (最/暢銷/賺/top/best/前N) — otherwise it's a plain
    # "show each store's revenue", not a per-group ranking.
    return (any(t in hay for t in _RANK_TRIGGERS)
            or any(w in hay for w in ("暢銷", "熱賣", "賺", "賣最"))
            or bool(re.search(r"(前\s*\d+|top\s*\d+)", hay)))


def _column_holding_values(prompt: str, normalized: str, contracts, block_id: str) -> str | None:
    """Round 127: find the categorical column whose VALUES the prompt names most
    (e.g. 'Hot 與 Normal' → priority), so a share/breakdown can group by it."""
    from ai4bi.blocks.contracts import BlockType
    from ai4bi.blocks.datastore import materialize_dataframe
    contract = (contracts or {}).get(block_id)
    if getattr(contract, "block_type", None) not in (
            BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
        return None
    try:
        df = materialize_dataframe(contract)
    except Exception:  # noqa: BLE001
        return None
    hay = f"{prompt.lower()} {normalized}"
    best, best_hits = None, 0
    for c in getattr(contract, "columns", []) or []:
        if c.data_type not in ("string", "str", "object") or _is_pk_like(c.name):
            continue
        if c.name not in df.columns:
            continue
        vals = {str(v) for v in df[c.name].dropna().unique()}
        if len(vals) > 20:  # skip high-cardinality columns
            continue
        hits = sum(1 for v in vals if v and v.lower() in hay)
        if hits >= 2 and hits > best_hits:
            best, best_hits = c.name, hits
    return best


# Round 129: fab categorical keywords → a low-cardinality column, so a
# compare-by-category question ("重工 vs 非重工", "Hot lot 比一般") can group by it
# even when the column's VALUES (0/1) are not literally named in the prompt.
_FAB_CATEGORY_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("重工", "返工", "rework"), "rework_flag"),
    (("優先", "priority", "hot", "急件", "趕貨", "一般批", "normal"), "priority"),
    (("hold", "保留", "扣留", "held", "卡住"), "hold_flag"),
    (("日班", "夜班", "白班", "晚班", "班別", "shift"), "shift"),
)
_ALL_FAB_CAT_KW = tuple(k for kws, _ in _FAB_CATEGORY_KEYWORDS for k in kws)
_CATEGORY_COMPARE_CUES = (
    " vs ", "v.s", "versus", "差異", "差別", "比較", "對比", "相比", "比一般",
    "短嗎", "長嗎", "高嗎", "低嗎", "快嗎", "慢嗎", "多嗎", "少嗎", "有沒有差", "對照")


def _keyword_category_column(prompt: str, normalized: str, contracts, block_id: str) -> str | None:
    """Round 129: map a fab category keyword (rework/priority/hold/shift) to its
    column on block_id, for compare-by-category breakdowns."""
    from ai4bi.blocks.datastore import materialize_dataframe
    contract = (contracts or {}).get(block_id)
    if contract is None:
        return None
    try:
        df = materialize_dataframe(contract)
    except Exception:  # noqa: BLE001
        return None
    cols = {c.name for c in getattr(contract, "columns", []) or []}
    hay = f"{prompt.lower()} {normalized}"
    for kws, col in _FAB_CATEGORY_KEYWORDS:
        if col in cols and col in df.columns and any(k in hay for k in kws):
            return col
    return None


def _looks_like_category_compare(prompt: str, normalized: str) -> bool:
    hay = f" {prompt.lower()} {normalized} "
    return (any(c in hay for c in _CATEGORY_COMPARE_CUES)
            and any(k in hay for k in _ALL_FAB_CAT_KW))


# Round 137: subgroup comparison — "有重工的批，良率是不是比較差" / "Day班和Night班
# queue time 有差嗎" / "被hold的批 cycle time 比較長嗎". The grouping FLAG and the
# MEASURE may live in different facts (rework_flag/hold_flag in moves, yield/cycle
# in yield), so this aligns by lot when needed. Fixes the silent-wrong where an
# overall single number was returned instead of the subgroup comparison.
_SUBGROUP_FLAGS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("重工", "返工", "rework"), "rework_flag"),
    (("被hold", "被 hold", "hold 住", "hold住", "hold", "保留", "扣留", "held", "卡住"), "hold_flag"),
    (("日班", "夜班", "白班", "白天班", "晚班", "早班", "大夜", "班別", "shift", "day班",
      "night班", "day 班", "night 班"), "shift"),
    (("優先", "priority", "hot", "急件", "趕貨"), "priority"),
    (("供應商", "廠商", "設備商", "vendor", "供货商", "原廠"), "vendor"),
    (("產品", "product", "品項", "產品別", "product family"), "product_family"),
)
_SUBGROUP_MEASURES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("良率", "yield", "良品率"), ("weighted_yield_pct", "yield_pct")),
    (("cycle", "週期", "周期", "在線時間", "在製時間"), ("cycle_time_hr",)),
    (("queue", "等待", "佇列", "排隊"), ("queue_time_hr",)),
    (("缺陷", "defect"), ("defect_die", "defect_density_pct")),
    (("加工", "process time", "處理時間"), ("process_time_min",)),
)
_SUBGROUP_CMP_CUES = (
    "比較", "有差", "有沒有差", "差異", "差別", "是不是", "會不會", "vs", "versus",
    "對比", "相比", "比一般", "短嗎", "長嗎", "高嗎", "低嗎", "快嗎", "慢嗎",
    "多嗎", "少嗎", "更差", "更好", "更高", "更低", "更長", "更短")
_SHIFT_WORDS = ("日班", "夜班", "白班", "白天班", "晚班", "早班", "大夜", "班別",
                "day班", "night班", "day 班", "night 班")
# Round 184 (S14): a BROADER compare cue set used only for shift questions (so a
# default wait-time comparison fires); kept OUT of the general cues above because
# "哪個/誰" are which-words that would steal a plain ranking ("哪個產品良率最差").
_SHIFT_CMP_CUES = _SUBGROUP_CMP_CUES + (
    "差多少", "差幾", "哪個", "誰", "比一比", "久嗎", "比較久", "誰高", "誰久", "久", "比")


def _looks_like_subgroup_compare(prompt: str, normalized: str) -> bool:
    hay = f" {prompt.lower()} {normalized} "
    # Round 182 (S5): "各/所有/每個 X 良率比較" is an ALL-group comparison — defer to
    # the breakdown/ranking engine (lists every group, die-weighted), not the
    # two-extreme subgroup compare which reports only the top vs bottom with a
    # raw-% gap on mean(yield_pct).
    if any(t in hay for t in ("各", "所有", "每個", "每一", "全部", "各個", "每種", "每類")):
        return False
    # Round 184 (S14): a SHIFT comparison defaults to wait time when no measure is
    # named ("白天班 vs 夜班 比較") — the handler picks queue_time_hr. Uses the
    # broader shift cue set, but ONLY when shift words are present.
    if any(s in hay for s in _SHIFT_WORDS) and any(c in hay for c in _SHIFT_CMP_CUES):
        return True
    has_flag = any(k in hay for kws, _ in _SUBGROUP_FLAGS for k in kws)
    has_measure = any(k in hay for kws, _ in _SUBGROUP_MEASURES for k in kws)
    has_cmp = any(c in hay for c in _SUBGROUP_CMP_CUES)
    return has_flag and has_measure and has_cmp


# Round 138: metric trend DIRECTION over time ("良率這幾週是變好還是變差").
_TREND_DIR_CUES = ("變好", "變差", "變高", "變低", "變壞", "上升", "下降", "走高",
                   "走低", "趨勢", "走勢", "往上", "往下", "是不是越來越", "越來越")
_TREND_TIME_CUES = ("這幾週", "這幾周", "近幾週", "近幾周", "逐週", "逐周", "每週",
                    "每周", "最近", "這陣子", "這幾個月", "逐月", "近期")
# Round 138: excursion — "良率突然掉下來 / 暴跌 / 異常下降".
_EXCURSION_CUES = ("突然掉", "掉下來", "掉到", "暴跌", "驟降", "異常下降", "突然變差",
                   "突然變低", "掉了", "excursion", "突然下滑", "急遽下降", "崩",
                   # Round 184 (S10): "良率異常下掉 / 異常的批次" → yield excursion,
                   # not the generic anomaly digest (which leaked capacity_moves).
                   "下掉", "異常下掉", "異常的批", "良率異常", "異常偏低的批", "突然降")


_TREND_QUESTION_CUES = (
    "趨勢如何", "走勢如何", "趨勢怎樣", "趨勢怎麼", "的趨勢", "看趨勢", "趨勢呢",
    "走勢呢", "有在下降", "有在下滑", "有沒有下降", "有沒有下滑", "有沒有變差",
    "有在變差", "有變差嗎", "越來越差嗎", "越來越好嗎", "是不是越來越",
    "變好還是變差", "變差還是變好", "是變好還是", "在往下嗎", "在下滑嗎",
    "有在掉", "還在掉", "在掉嗎", "有在跌", "還在跌", "在跌嗎", "有在惡化",
    "持續下滑嗎", "持續惡化嗎", "在變差嗎", "有改善嗎", "有沒有改善",
    "在惡化", "惡化嗎", "有沒有惡化", "有惡化", "變差了嗎", "變差了沒",
    "是不是變差", "是否變差", "是不是惡化", "在變糟", "變糟了嗎",
    # Round 182 (S1): positive-direction & "降很多/退步" colloquials (both directions
    # of a trend question — the verdict covers improving or worsening).
    "變好嗎", "有沒有變好", "有變好", "變好了嗎", "變好了沒", "是不是變好", "好轉",
    "降很多嗎", "掉很多嗎", "降很多", "掉很多", "降了嗎", "是不是降了", "是不是掉了",
    "退步", "退步了嗎", "進步了嗎", "有進步", "有起色")


def _is_trend_direction_question(prompt: str, normalized: str) -> bool:
    """A direction *question* that wants a verdict (better/worse + slope), not a
    smoothed chart — checked before the moving-average analytics chart so an
    explicit "良率趨勢如何 / 有在下降嗎" isn't answered with only a chart."""
    hay = f"{prompt.lower()} {normalized}"
    # a forecast ("…並預測未來4週") is a forecast-chart request — let that engine
    # build the proposal, don't pre-empt it with a backward-looking verdict.
    if any(t in hay for t in ("預測", "forecast", "predict", "預估未來", "推估未來")):
        return False
    if any(p in hay for p in _TREND_QUESTION_CUES):
        return True
    # Round 182 (S4): a NAMED entity + any time-series wording ("ETCH-01 良率逐週
    # 趨勢 / 走勢 / 週良率變化 / 這幾週怎麼走") wants that entity's trend verdict —
    # route it to the trend engine (which filters to the named tool) instead of
    # the unfiltered moving-average chart or a single-value lookup.
    has_code = bool(re.search(r"[a-z]{2,}-?\d", hay))
    trendish = any(t in hay for t in (
        "趨勢", "走勢", "逐週", "逐周", "每週", "每周", "這幾週", "這幾周",
        "週變化", "周變化", "隨時間", "怎麼走", "如何變", "怎麼變", "走向"))
    if has_code and trendish:
        return True
    # period + change wording even without a named code ("週良率變化", "逐週怎麼變")
    time_word = any(t in hay for t in (
        "逐週", "逐周", "每週", "每周", "這幾週", "這幾周", "近幾週", "近幾周",
        "逐月", "每月", "隨時間", "週", "周"))
    change_word = any(t in hay for t in (
        "趨勢", "走勢", "變化", "怎麼走", "如何變", "怎麼變", "變動", "走向"))
    return time_word and change_word


def _looks_like_trend_direction(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    # Round 178 (S1): an explicit "趨勢如何 / 走勢如何 / 的趨勢" is itself a time-series
    # ask — don't also require a separate time cue (it was falling to an overall KPI).
    if any(p in hay for p in ("趨勢如何", "走勢如何", "趨勢怎樣", "趨勢怎麼", "的趨勢",
                              "看趨勢", "趨勢呢", "走勢呢", "趨勢圖", "走勢圖")):
        return True
    # Round 182 (S1): a bare "趨勢/走勢" noun is a time-series ask on its own —
    # "良率趨勢", "ETCH-01 趨勢" were falling through to "unsupported". (This sits
    # AFTER decline/analytics-chart routing, so it only catches leftovers.)
    if "趨勢" in hay or "走勢" in hay:
        return True
    # A directional change verb is a trend ask — UNLESS it's a "why/vs-period"
    # decomposition ("為什麼…下降", "哪個 area 造成…比上週下降"), which must reach
    # explain_change instead of being answered with an overall trend line.
    change_ctx = any(t in hay for t in (
        "比上", "比前", "比這", "為什麼", "為何", "造成", "原因", "拆解", "歸因",
        "上週", "上周", "上月", "去年同期", "vs 上", "相比", "哪個", "哪一個", "哪些"))
    if not change_ctx:
        if any(v in hay for v in ("上升", "下降", "下滑", "走高", "走低", "越來越",
                                  "往上走", "往下走", "惡化", "變糟")):
            return True
        if any(t in hay for t in _TREND_TIME_CUES) and any(
                v in hay for v in ("變化", "變動", "變好", "變差", "改善", "惡化")):
            return True
    return any(d in hay for d in _TREND_DIR_CUES) and any(t in hay for t in _TREND_TIME_CUES)


def _looks_like_excursion(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(c in hay for c in _EXCURSION_CUES)


def _is_pk_like(col: str) -> bool:
    """Round 127: a row-identifier column that must never be a grouping dimension
    (move_id, yield_event_id, …) even though it's categorical."""
    low = col.lower()
    return any(t in low for t in ("move_id", "_event_id", "event_id", "record_id",
                                  "row_id", "_uid", "txn_id", "transaction_id"))


def _is_categorical_col(contracts, block_id: str, col: str) -> bool:
    if _is_pk_like(col):  # Round 127: row PKs are not grouping dimensions
        return False
    contract = (contracts or {}).get(block_id)
    for c in getattr(contract, "columns", None) or []:
        if c.name == col:
            return getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar")
    return False


def _resolve_two_dims(idx, prompt: str, normalized: str, contracts, block_id: str):
    """Resolve (outer_group_col, inner_entity_col) for a per-group Top-N.

    Outer = the dimension after a per/each marker; inner = the best other
    categorical dimension keyword. Both must be categorical columns on
    ``block_id``. Returns (None, None) when they can't be resolved.
    """
    hay = f"{prompt.lower()} {normalized}"
    outer = None
    for marker in _PER_GROUP_MARKERS:
        i = hay.find(marker)
        if i < 0:
            continue
        # Chinese has no word spaces, so match the longest dimension keyword the
        # text right after the marker *starts with* (handles "每個地區營收..." and
        # the spaced English "per store").
        tail = hay[i + len(marker):].lstrip(" 的")
        cand, clen = None, 0
        for kw, e in idx._dims.items():
            if (e.block_id == block_id and tail.startswith(kw) and len(kw) > clen
                    and _is_categorical_col(contracts, block_id, e.column_name)):
                cand, clen = e.column_name, len(kw)
        if cand:
            outer = cand
            break
    if outer is None:
        return None, None

    inner = None
    best_len = 0
    for kw, e in idx._dims.items():
        if (e.block_id == block_id and e.column_name != outer
                and _is_categorical_col(contracts, block_id, e.column_name)
                and kw in hay and len(kw) > best_len):
            inner = e.column_name
            best_len = len(kw)
    return outer, inner


# --- Round 089: location-column detection for map visuals --------------------

# Strong hints resolve to coordinates (city/region/縣市); weak hints (store/門市)
# are usually too granular for the geo lookup, so they're only a fallback.
_STRONG_LOCATION_HINTS: tuple[str, ...] = (
    "city", "region", "country", "state", "province", "county",
    "市", "縣", "省", "城市", "縣市", "地區", "國家", "geo",
)
_WEAK_LOCATION_HINTS: tuple[str, ...] = (
    "store", "branch", "location", "area", "district", "門市", "分店",
    "據點", "地點", "區",
)


def _find_location_col(contract) -> str | None:
    """Return the best string column that looks like a geographic location.

    Prefers coordinate-resolvable levels (city/region/縣市) over store-level
    names, since the map's geo lookup keys on administrative names.
    """
    if contract is None:
        return None
    cols = [
        c.name for c in (getattr(contract, "columns", []) or [])
        if getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar")
        and not c.name.lower().endswith(("_id", "_code"))
    ]
    for hints in (_STRONG_LOCATION_HINTS, _WEAK_LOCATION_HINTS):
        for name in cols:
            if any(h in name.lower() for h in hints):
                return name
    return None


# --- Round 086: NL routing to pandas analytics engines -----------------------

_PANEL_LABELS = {
    "churn": "客戶流失風險 / RFM",
    "decline": "連續下滑偵測",
    "basket": "商品關聯（常一起買）",
    "repeat": "回頭客 vs 一次性客",
    "dormant": "滯銷 / 停售商品",
    "newproduct": "新品上市表現",
    "basketsize": "客單品項數 / 籃子大小",
}
_BASKETSIZE_TRIGGERS = ("客單品項", "一單幾", "一次買幾", "平均幾件", "平均幾樣", "每單幾",
                        "籃子大小", "購物籃大小", "平均購買數", "items per order",
                        "items per basket", "basket size", "average basket", "每筆幾件",
                        "每單", "一單", "每筆", "買幾樣", "買幾件", "幾樣商品", "幾件商品")
_NEWPRODUCT_TRIGGERS = ("新品", "新商品", "新產品", "新上市", "最近上架", "這季新", "本季新",
                        "new product", "newly launched", "new arrival", "just launched",
                        "上新", "新推出")
_REPEAT_TRIGGERS = ("回頭客", "回購客", "回頭率", "一次性客", "一次性顧客", "回頭還是",
                    "多少回頭", "repeat customer", "repeat vs", "one-time", "one time customer",
                    "repeat or", "returning vs")
_DORMANT_TRIGGERS = ("滯銷", "賣不動", "沒在賣", "停售", "停止銷售", "不再賣", "賣不出去",
                     "沉睡商品", "呆料", "dead stock", "dormant", "stopped selling",
                     "no longer selling", "slow-moving", "slow moving")
_CHURN_TRIGGERS = ("流失", "churn", "rfm", "快走", "要走", "好久沒來", "沉睡", "回購率", "誰快不來", "快不來")
_DECLINE_TRIGGERS = ("連續下滑", "連續下跌", "一直下滑", "持續下滑", "持續下跌", "持續衰退",
                     "連續衰退", "一直在掉", "一直掉", "一直跌", "一直在跌", "持續探低",
                     "一直變差", "越來越差", "走弱", "連續成長", "持續成長",
                     "持續變差", "持續惡化", "持續退步", "一直惡化", "越來越糟",  # Round 184 (S11)
                     "趨勢往下", "趨勢下降", "趨勢下滑", "一直退步", "往下的趨勢",  # Round 184 (S11)
                     "退步", "在退步", "連續退步", "一直在退",  # Round 184 (S11): bare 退步 → streak
                     "往下掉", "一直往下", "持續往下", "往下走", "越掉越", "一路下滑", "一路往下",
                     "逐週下滑", "逐周下滑", "逐月下滑", "逐週退化", "逐步下滑", "趨勢下滑", "退化",
                     "drift", "degrad", "走低",
                     "keeps declining", "declining", "consecutive", "months in a row",
                     "in a row", "streak")
_BASKET_TRIGGERS = ("一起買", "一起購買", "常買在一起", "搭配", "連帶", "商品關聯", "組合銷售",
                    "bought together", "market basket", "affinity", "cross-sell", "cross sell")

_CUSTOMER_HINTS = ("customer", "member", "client", "user", "客戶", "顧客", "會員")
_DATE_COL_HINTS = ("date", "_at", "time", "日期", "時間")
_MONEY_HINTS = ("revenue", "amount", "sales", "spend", "price", "total", "營收", "金額", "銷售", "消費")
_ENTITY_HINTS = ("product", "sku", "item", "store", "category", "商品", "品項", "門市", "品類",
                 # Round 114: fab entities
                 "tool", "step", "lot", "wafer", "vendor", "機台", "設備", "製程", "站",
                 "批", "晶圓", "供應商", "product_family", "tool_group", "tool_id", "step_name")
_VALUE_HINTS = ("revenue", "amount", "sales", "qty", "quantity", "count", "營收", "金額", "銷售", "數量",
                # Round 114: fab measures
                "yield", "queue", "move", "defect", "die", "rework", "良率", "等待",
                "移動", "缺陷", "晶粒", "重工", "time", "process")
_PRODUCT_HINTS = ("product", "item", "sku", "商品", "品項")
_BASKET_KEY_HINTS = ("customer", "member", "date", "_at", "store", "客戶", "門市", "日期")


def _detect_panel_analysis(prompt: str, normalized: str) -> str | None:
    hay = f"{prompt.lower()} {normalized}"
    if any(t in hay for t in _BASKETSIZE_TRIGGERS):
        return "basketsize"
    if any(t in hay for t in _NEWPRODUCT_TRIGGERS):
        return "newproduct"
    if any(t in hay for t in _DORMANT_TRIGGERS):
        return "dormant"
    if any(t in hay for t in _REPEAT_TRIGGERS):
        return "repeat"
    if any(t in hay for t in _CHURN_TRIGGERS):
        return "churn"
    if any(t in hay for t in _DECLINE_TRIGGERS):
        return "decline"
    if any(t in hay for t in _BASKET_TRIGGERS):
        return "basket"
    return None


_CAPACITY_CUES: tuple[str, ...] = (
    "利用率", "稼動率", "稼動", "使用率", "utilization", "util", "負載", "負載率",
    "loading", "滿載", "餘裕", "headroom", "閒置", "產能", "capacity",
    "達成率", "達標", "計畫 vs", "throughput", "每工時", "單位工時", "moves/hr",
    "moves per", "產出率", "瓶頸機台", "瓶頸是哪", "瓶頸",
    "可用率", "availability", "停機", "line balance", "線平衡", "產線平衡",
    "擴產", "加機台", "增購", "加產能", "缺口", "投資哪", "瓶頸區", "拖累",  # Round 130
    "要擴", "擴哪", "該擴", "加哪", "該加", "擴充",  # Round 184 (S13)
)
_OEE_CUES: tuple[str, ...] = ("oee", "設備總合效率", "設備綜合效率", "綜合效率",
                              "總合效率", "設備效率", "設備總效率", "設備稼動效率")


# a wait/queue share-of-total question ("ETCH 等待佔全廠多少%") is about queue time,
# not capacity — even though "瓶頸" trips a capacity cue. Let breakdown handle it.
_CAPACITY_VETO = ("等待", "queue", "佇列", "wait time", "等候")
_SHARE_WORDS = ("佔總", "占總", "佔全", "占全", "比重", "佔多少", "占多少", "佔了", "share of")


_UTIL_CUES: tuple[str, ...] = (
    "利用率", "稼動", "使用率", "utiliz", "util", "負載", "loading", "滿載", "餘裕",
    "headroom", "閒置", "產能", "capacity", "可用率", "availab", "停機", "擴產",
    "加機台", "增購", "加產能", "缺口", "throughput", "產出率", "達成率", "達標",
)


def _looks_like_capacity(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(v in hay for v in _CAPACITY_VETO) and any(s in hay for s in _SHARE_WORDS):
        return False
    # Round 178 (S8): a queue/wait question ("哪一站等待最長？瓶頸在哪？") is about
    # queue time per step, NOT machine utilization — don't let the word 瓶頸 hijack
    # it to a capacity/utilization answer unless an actual utilization cue is there.
    queue_q = any(t in hay for t in ("等待", "等候", "queue", "wait"))
    if queue_q and not any(c in hay for c in _UTIL_CUES):
        return False
    return any(c in hay for c in _CAPACITY_CUES)


def _looks_like_oee(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _OEE_CUES):
        return True
    # A factor-LOSS question ("表現損失最大的機台", "可用率拖累最嚴重") is an OEE question
    # even without the literal "OEE" — route it to OEE before the capacity cues so the
    # "停機/速度" wording doesn't divert it to the plain availability table.
    factor = any(f in hay for f in ("可用率", "availability", "表現", "performance",
                                    "良率", "quality", "品質", "稼動"))
    lossword = any(w in hay for w in ("損失", "loss", "拖累", "六大損失"))
    return factor and lossword


# Round 134: bottleneck-drift (over time) and WIP↔cycle-time (Little's Law).
# Both wire the already-tested analysis/capacity_dynamics engine into NL routing.
# They must be checked BEFORE _looks_like_capacity/_looks_like_metric, since
# "瓶頸" trips capacity and "cycle time" trips the plain metric answer.
_DRIFT_TIME_CUES: tuple[str, ...] = (
    "換站", "換過", "漂移", "drift", "這幾週", "這幾周", "每週", "每周", "隨時間",
    "over time", "轉移", "有沒有變", "有沒有換", "週週", "逐週", "逐周", "歷週",
    "幾週下來", "近幾週", "近幾周", "每個月", "逐月", "隨週",
)
_BOTTLENECK_WORDS: tuple[str, ...] = ("瓶頸", "bottleneck", "最塞", "最卡", "卡關", "最忙的站")
_WIP_CUES: tuple[str, ...] = ("wip", "在製", "在制", "在线", "在線品", "work in progress", "在製品", "在制品")
_CT_CUES: tuple[str, ...] = (
    "cycle time", "cycle_time", "週期時間", "周期時間", "製程週期", "在線時間",
    "在制時間", "在製時間", "生產週期", "cycletime", "循環時間",
)


def _looks_like_bottleneck_drift(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(b in hay for b in _BOTTLENECK_WORDS) and any(t in hay for t in _DRIFT_TIME_CUES)


def _looks_like_wip_ct(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if "little" in hay or "利特" in hay:
        return True
    return any(w in hay for w in _WIP_CUES) and any(c in hay for c in _CT_CUES)


_SPC_CUES: tuple[str, ...] = (
    "標準差", "σ", "sigma", "管制界限", "管制上限", "管制下限", "control limit",
    "超出平均", "異常偏高", "異常偏低", "spc", "幾個標準差", "離群",
    "管制圖", "控制圖", "control chart", "管制",  # Round 184 (S10)
)
_COMMONALITY_CUES: tuple[str, ...] = (
    "共同", "共通", "都走過", "共用", "共同經過", "commonality", "common tool",
    "同一台", "共同的機台", "有沒有共同",
    # Round 178 (S3): colloquial commonality phrasings.
    "共通點", "共同點", "共同路徑", "共同因素", "共同的問題", "元兇", "元凶", "禍首",
    "都經過", "都用到", "common", "共通的", "共同走",
    # Round 182 (S3): "良率殺手 / 兇手 / 罪魁" = the common tool among the bad wafers.
    "殺手", "兇手", "凶手", "罪魁",
    # Round 182 (S3): RCA wording — "root cause / 根本原因 / 根因" of low yield.
    "root cause", "rootcause", "根本原因", "根因", "根本問題",
    # Round 182 (S3): "低良率批次最常經過哪台" — the shared/most-traversed tool of
    # the bad wafers is a commonality ask, not a yield Top-N ("最常經過" mis-read as
    # ranking returned the HIGHEST-yield tool — direction reversed).
    "最常經過", "最常走過", "最常走", "常經過", "經過哪台", "經過哪一台", "最常用到",
)


def _looks_like_spc(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(c in hay for c in _SPC_CUES)


def _looks_like_commonality(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _COMMONALITY_CUES):
        return True
    # Round 182 (S3): "哪一站/哪台 造成/害/問題 良率掉/不良" attributes low yield to a
    # shared station/tool → commonality (worst-quartile common path), NOT a temporal
    # decomposition. Requires a culprit verb/phrase so it doesn't steal a plain
    # ranking ("哪台良率差"), and is skipped in a vs-period context (那走 explain_change).
    which_station = any(w in hay for w in (
        "哪一站", "哪站", "哪一台", "哪台", "哪臺", "哪個機台", "哪個站", "哪個站點",
        "哪個製程", "哪一個站", "哪個設備", "哪部機", "站點", "製程站", "誰",
        "什麼", "甚麼", "啥",
        # Round 182 (S3): "造成良率變差的關鍵設備" — the key/culprit equipment.
        "關鍵設備", "關鍵機台", "關鍵的設備", "關鍵的機台", "關鍵站", "問題設備"))
    bad_yield = any(w in hay for w in (
        "良率掉", "良率低", "良率差", "不良", "低良", "良率下降", "良率不好",
        "拉低良率", "良率出問題", "良率有問題", "良率"))
    # strong "harm/culprit" verbs imply a quality culprit on their own; weak ones
    # ("造成/導致") are too generic, so they additionally need a bad-yield word.
    strong_culprit = any(w in hay for w in (
        "害", "拖累", "搞鬼", "搞的", "禍首", "元凶", "元兇", "罪魁", "毛病", "的問題",
        "殺手", "兇手", "凶手",
        # Round 182 (S3): "關鍵設備 / 問題設備 / 問題出在哪台 / 有問題" name the
        # culprit equipment on their own (bare phrasings should reach commonality).
        "關鍵設備", "關鍵機台", "問題設備", "問題機台", "關鍵的設備", "關鍵的機台",
        "問題出在", "出問題", "有問題", "出在哪",
        # Round 184 (S09): "低良率跟哪台最相關 / 有關" — attributing low yield to a
        # shared tool is commonality, not a yield ranking (which returned the
        # HIGHEST-yield tool — direction reversed).
        "相關", "有關", "關聯", "有關係"))
    weak_culprit = any(w in hay for w in ("造成", "導致", "拉低"))
    change_ctx = any(t in hay for t in (
        "比上", "比前", "比這", "上週", "上周", "上月", "去年同期", "vs 上", "這週比", "本週比"))
    # commonality is about low-YIELD wafers sharing a tool — if the prompt names a
    # different metric (可用率/OEE/queue/cycle/產能…), it's that engine's question,
    # not commonality (e.g. "哪台機台的可用率拖累最嚴重" → OEE, not commonality).
    other_metric = any(w in hay for w in (
        "可用率", "availability", "oee", "稼動", "利用率", "queue", "等待", "cycle",
        "週期", "move", "移動", "產能", "throughput", "wip", "稼動率", "uptime"))
    if which_station and not change_ctx and not other_metric and (
            strong_culprit or (weak_culprit and bad_yield)):
        return True
    return False


_CROSSFACT_CUES: tuple[str, ...] = (
    "關聯", "相關", "關係", "有沒有關", "correlat", "linked",
    "比值", "換來", "每次", "分位", "四分位", "cohort", "quantile",
    "前20%", "前 20%", "前10%", "前 10%", "前30%", "前 30%",
)


def _looks_like_crossfact(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _CROSSFACT_CUES):
        return True
    return bool(re.search(r"前\s*\d+\s*%", hay))


def _pick_join_key(prompt: str, normalized: str, shared: set) -> str | None:
    """Pick a shared join key, preferring one the prompt mentions."""
    if not shared:
        return None
    hay = f"{prompt.lower()} {normalized}"
    # prompt-mentioned key wins (lot/批, product/產品, week/週, wafer/晶圓)
    pref = [
        (("lot", "批", "批號"), "lot_id"),
        (("product", "產品", "品項", "family"), "product_family"),
        (("week", "週", "周"), "week"),
        (("wafer", "晶圓"), "wafer_id"),
    ]
    for words, col in pref:
        if col in shared and any(w in hay for w in words):
            return col
    # sensible defaults present in both facts
    for col in ("lot_id", "product_family", "wafer_id", "week"):
        if col in shared:
            return col
    return sorted(shared)[0]


# Round 129: generic numeric-suffix tokens that must NOT alone bind a column —
# "cycle time" should not match queue_time/process_time via the shared "time".
_GENERIC_NUM_TOKENS = frozenset({
    "time", "時間", "hr", "hour", "hours", "min", "mins", "minute", "minutes", "鐘頭",
    "count", "cnt", "次數", "rate", "ratio", "pct", "percent", "百分比", "num", "value",
    "amount", "total", "qty", "age", "id", "date", "日期", "數",
})


def _resolve_two_numeric_cols(prompt: str, normalized: str, contract) -> list:
    """Round 121: up to 2 DISTINCT numeric columns the prompt references (for
    same-fact correlation), longest keyword first."""
    from ai4bi.ai.schema_index import _EN_TO_ZH
    hay = f"{prompt.lower()} {normalized}"
    best_per_col: dict[str, int] = {}
    for c in getattr(contract, "columns", []) or []:
        if getattr(c, "data_type", "") not in ("integer", "float", "int", "number",
                                               "numeric", "double", "bigint"):
            continue
        low = c.name.lower()
        if low.endswith(("_id", "_code", "_no")):
            continue
        kws: set[str] = set()
        for tok in re.split(r"[_\s]+", low):
            if tok and tok not in _GENERIC_NUM_TOKENS:
                kws.add(tok)
                for zh in _EN_TO_ZH.get(tok, []):
                    if zh not in _GENERIC_NUM_TOKENS:
                        kws.add(zh)
        for kw in kws:
            if len(kw) >= 2 and kw in hay:
                best_per_col[c.name] = max(best_per_col.get(c.name, 0), len(kw))
    ordered = sorted(best_per_col.items(), key=lambda kv: kv[1], reverse=True)
    return [col for col, _ in ordered[:2]]


def _resolve_numeric_column(prompt: str, normalized: str, contract) -> str | None:
    """Round 115: match the prompt to a NUMERIC column via tokens + ZH synonyms.

    So '良率' resolves the yield_pct column, '等待' the queue_time_hr column, etc.
    Used to make panel analyses (decline/dormant/launch) prompt-aware instead of
    guessing from column order. Returns None when nothing matches.
    """
    from ai4bi.ai.schema_index import _EN_TO_ZH
    hay = f"{prompt.lower()} {normalized}"
    best, best_len = None, 0
    for c in getattr(contract, "columns", []) or []:
        if getattr(c, "data_type", "") not in ("integer", "float", "int", "number",
                                               "numeric", "double", "bigint"):
            continue
        low = c.name.lower()
        if low.endswith(("_id", "_code", "_no")):
            continue
        kws: set[str] = set()
        for tok in re.split(r"[_\s]+", low):
            if tok and tok not in _GENERIC_NUM_TOKENS:
                kws.add(tok)
                for zh in _EN_TO_ZH.get(tok, []):
                    if zh not in _GENERIC_NUM_TOKENS:
                        kws.add(zh)
        for kw in kws:
            if len(kw) >= 2 and kw in hay and len(kw) > best_len:
                best, best_len = c.name, len(kw)
    return best


def _guess_col(cols: list[str], hints: tuple[str, ...], exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    for c in cols:
        if c in exclude:
            continue
        if any(h in c.lower() for h in hints):
            return c
    return None


def _pick_fact_for_analysis(facts: dict, kind: str):
    """Choose the fact block whose columns best satisfy ``kind`` + its column map."""
    best = None
    best_score = 0
    for bid, contract in facts.items():
        cols = [c.name for c in getattr(contract, "columns", [])]
        if kind == "churn":
            cmap = {
                "customer": _guess_col(cols, _CUSTOMER_HINTS),
                "date": _guess_col(cols, _DATE_COL_HINTS),
                "money": _guess_col(cols, _MONEY_HINTS),
            }
            required = ("customer", "date", "money")
        elif kind == "repeat":
            cmap = {
                "customer": _guess_col(cols, _CUSTOMER_HINTS),
                "date": _guess_col(cols, _DATE_COL_HINTS),
            }
            required = ("customer", "date")
        elif kind in ("decline", "dormant", "newproduct"):
            # value must be a NUMERIC, non-id column — else 'move' matches move_id
            # (a string) and the streak math crashes. (Round 114)
            numeric = {c.name for c in contract.columns
                       if getattr(c, "data_type", "") in ("integer", "float", "int", "number",
                                                          "numeric", "double", "bigint")}
            num_cols = [c for c in cols
                        if c in numeric and not c.lower().endswith(("_id", "_code", "_no"))]
            entity = _guess_col(cols, _ENTITY_HINTS)
            date = _guess_col(cols, _DATE_COL_HINTS)
            value = _guess_col(num_cols, _VALUE_HINTS, exclude={entity} if entity else set())
            cmap = {"entity": entity, "date": date, "value": value}
            required = ("entity", "date", "value")
        elif kind == "basketsize":
            item = _guess_col(cols, _PRODUCT_HINTS)
            keys = [c for c in cols
                    if any(h in c.lower() for h in _BASKET_KEY_HINTS) and c != item]
            qty = _guess_col(cols, ("qty", "quantity", "數量", "件數", "pcs"))
            cmap = {"item": item, "basket": keys[:3], "qty": qty}
            required = ("item", "basket")
        else:  # basket
            product = _guess_col(cols, _PRODUCT_HINTS)
            keys = [c for c in cols
                    if any(h in c.lower() for h in _BASKET_KEY_HINTS) and c != product]
            cmap = {"product": product, "basket": keys[:3]}
            required = ("product", "basket")
        score = sum(1 for r in required if cmap.get(r))
        if score == len(required) and score > best_score:
            best, best_score = (bid, contract, cmap), score
    return best


def _execute_panel_analysis(kind: str, df, cols_map: dict):
    """Run the chosen analysis; return (result_table, summary_sentence)."""
    if kind == "churn":
        from ai4bi.analysis.rfm import compute_rfm
        table = compute_rfm(df, cols_map["customer"], cols_map["date"], cols_map["money"])
        if table is None or table.empty:
            return table, ""
        at_risk = int(table["流失風險"].sum())
        top = table[table["流失風險"]].head(3)
        names = "、".join(str(x) for x in top[cols_map["customer"]].tolist())
        sentence = (f"共 {len(table)} 位客戶，其中 ⚠️ {at_risk} 位有流失風險。"
                    + (f"最該優先聯繫（高價值且久未回購）：{names}。" if names else ""))
        return table.head(25), sentence
    if kind == "basketsize":
        from ai4bi.analysis.basket import basket_size_distribution
        dist, summary = basket_size_distribution(
            df, cols_map["basket"], cols_map["item"], cols_map.get("qty"))
        if dist is None or dist.empty:
            return dist, ""
        sentence = (f"平均每籃 {summary['avg']} 項（中位數 {summary['median']}，"
                    f"最多 {summary['max']}），共 {summary['baskets']} 籃。")
        return dist, sentence
    if kind == "newproduct":
        from ai4bi.analysis.trends import new_products
        table = new_products(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                             period=cols_map.get("period", "month"))
        if table is None or table.empty:
            return table, ""
        best = table.iloc[0]
        sentence = (f"{len(table)} 個新上市對象。表現最好："
                    f"{best[cols_map['entity']]}（上市以來 {best['上市以來']}）。")
        return table.head(25), sentence
    if kind == "dormant":
        from ai4bi.analysis.trends import dormant_products
        period = cols_map.get("period", "month")
        table = dormant_products(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                                 period=period)
        if table is None or table.empty:
            return table, ""
        worst = table.iloc[0]
        sentence = (f"{len(table)} 個對象已停止銷售（沉睡）。"
                    f"最該注意：{worst[cols_map['entity']]}"
                    f"（最後售出 {worst['最後售出']}，已沉睡 {worst['沉睡期數']} 期）。")
        return table.head(25), sentence
    if kind == "repeat":
        from ai4bi.analysis.segments import repeat_vs_onetime
        table = repeat_vs_onetime(df, cols_map["customer"], cols_map["date"])
        if table is None or table.empty:
            return table, ""
        rep_rows = table[table["客戶類型"].str.startswith("回頭")]
        rep_pct = float(rep_rows["佔比%"].iloc[0]) if not rep_rows.empty else 0.0
        sentence = f"回頭客佔 {rep_pct}%，共 {int(table['人數'].sum())} 位客戶。"
        return table, sentence
    if kind == "decline":
        from ai4bi.analysis.trends import declining_by_trend, declining_streaks
        period = cols_map.get("period", "month")
        min_streak = cols_map.get("min_streak", 3)
        table = declining_streaks(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                                  period=period, min_streak=min_streak)
        if table is not None and not table.empty:
            worst = table.iloc[0]
            sentence = (f"{len(table)} 個對象連續下滑 ≥ {min_streak} 期。"
                        f"最嚴重：{worst[cols_map['entity']]}（連續 {worst['連續期數']} 期，"
                        f"最新一期 {worst['變化%']}%）。")
            return table.head(25), sentence
        # Round 126: no strict monotone streak → fall back to a NEGATIVE-TREND
        # detector (least-squares slope) so a noisy-but-degrading entity (tool
        # drift) is still surfaced.
        ttable = declining_by_trend(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                                    period=period if period != "month" else "week")
        if ttable is None or ttable.empty:
            return ttable, ""
        worst = ttable.iloc[0]
        sentence = (f"{len(ttable)} 個對象呈下滑趨勢（負斜率）。最嚴重："
                    f"{worst[cols_map['entity']]}（斜率 {worst['斜率/期']}/期，"
                    f"{worst['起始']}→{worst['最新']}）。")
        return ttable.head(25), sentence
    # basket
    from ai4bi.analysis.basket import basket_affinity
    table = basket_affinity(df, cols_map["product"], cols_map["basket"])
    if table is None or table.empty:
        return table, ""
    top = table.iloc[0]
    sentence = (f"找到 {len(table)} 組常一起購買的商品。最強關聯："
                f"「{top['商品A']}」＋「{top['商品B']}」（提升度 {top['提升度']}）。")
    return table.head(25), sentence


# --- Round 084: KPI target / pacing parsing ----------------------------------

_TARGET_MARKERS: tuple[str, ...] = ("目標", "達標", "target", "goal", "objective")


def _looks_like_set_target(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if not any(t in hay for t in _TARGET_MARKERS):
        return False
    # Needs a number and a "set" verb (設/設定/set/=) — "達標了嗎" is a question,
    # not a set-target command, so require an assignment cue.
    has_set = any(v in hay for v in ("設", "設定", "設為", "訂", "定為", "set", "="))
    return has_set and re.search(r"\d", hay) is not None


_LOWER_IS_BETTER_WORDS: tuple[str, ...] = (
    "退貨", "退款", "退回", "成本", "費用", "流失", "churn", "cost", "return",
    "error", "錯誤", "缺貨", "客訴", "抱怨", "complaint", "defect", "瑕疵", "延遲", "delay",
)


def _infer_target_good_if(visual) -> str:
    """Infer whether higher or lower is better for a KPI's target/pacing.

    Prefers an existing RAG config; otherwise reads the metric/title text for
    lower-is-better signals (return rate, cost, churn, ...). Defaults to "gte".
    """
    extra = visual.visualization.extra or {}
    rag = extra.get("rag") or {}
    if rag.get("good_if") in ("gte", "lte"):
        return rag["good_if"]
    text = " ".join(filter(None, [
        visual.visualization.title or "",
        *(m.alias or m.metric_name for m in visual.query.metrics),
    ])).lower()
    return "lte" if any(w in text for w in _LOWER_IS_BETTER_WORDS) else "gte"


_PACING_TRIGGERS: tuple[str, ...] = (
    "達標了嗎", "達標嗎", "有沒有達標", "達成了嗎", "達成率", "進度如何", "進度怎樣",
    "離目標", "達標進度", "on track", "on-track", "hit the target", "hit target",
    "reach the goal", "progress to target", "進度多少",
)


def _looks_like_pacing_question(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(t in hay for t in _PACING_TRIGGERS)


def _extract_target_value(prompt: str, normalized: str) -> float | None:
    """Parse a target number, honouring 萬/億/k/m/百萬 multipliers."""
    hay = f"{prompt} {normalized}"
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(億|百萬|萬|千|k|m|b)?", hay, re.IGNORECASE)
    if m is None:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"億": 1e8, "百萬": 1e6, "萬": 1e4, "千": 1e3,
            "k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower())
    if mult:
        val *= mult
    return val


# --- Round 081: explain-change (decomposition) parsing -----------------------

_EXPLAIN_TRIGGERS: tuple[str, ...] = (
    "為何", "為什麼", "為甚麼", "原因", "怎麼會", "怎會",
    "變化分解", "拆解", "分解", "貢獻",
    "造成", "主因", "歸因", "主要是哪", "元凶", "禍首", "誰造成", "哪個.*造成",
    "why did", "why is", "why has", "what caused", "what drove",
    "decompose", "break down", "breakdown", "contribut",
)
_CHANGE_WORDS: tuple[str, ...] = (
    "變", "升", "降", "增", "減", "漲", "跌", "掉", "成長", "衰退", "高", "低",
    "上升", "下降", "變高", "變低", "惡化", "改善",
    "change", "changed", "dip", "drop", "fell", "fall", "rose", "rise",
    "grew", "grow", "increase", "decrease", "decline", "down", "up", "higher", "lower",
)
# "by <dim>" / "依/按/照 <dim>" decomposition-axis markers.
_DECOMP_BY_MARKERS: tuple[str, ...] = ("依", "按", "照", "以", "by ", "per ", "across ")


def _looks_like_explain_change(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    has_trigger = any(t in hay for t in _EXPLAIN_TRIGGERS)
    if not has_trigger:
        return False
    # A "why" / "原因" needs an accompanying change word; explicit decompose
    # verbs ("拆解", "decompose", "break down") stand on their own.
    explicit = any(t in hay for t in ("變化分解", "拆解", "分解", "decompose", "break down", "breakdown"))
    return explicit or any(c in hay for c in _CHANGE_WORDS)


def _resolve_decomp_dimension(idx, prompt: str, normalized: str, contracts, block_id: str):
    """Pick a categorical column on ``block_id`` to decompose by.

    Prefers an explicit "by <dim>" phrase, else the best dimension keyword
    match; rejects date columns (decomposition needs a categorical axis).
    """
    hay = f"{prompt.lower()} {normalized}"

    def _is_categorical(col: str) -> bool:
        if _is_pk_like(col):  # Round 127: never group by a row PK (move_id …)
            return False
        contract = contracts.get(block_id)
        for c in getattr(contract, "columns", None) or []:
            if c.name == col:
                if getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar"):
                    return True
                return False
        return False

    # Try the token right after a "by"/"依" marker first. Note: we check the
    # column exists & is categorical ON THE METRIC'S BLOCK rather than requiring
    # SchemaIndex to have attributed the dim to that block — denormalized facts
    # share column names (e.g. product_family on both move & yield facts), and
    # SchemaIndex only records the first block, which would otherwise block a
    # "yield by product" ranking. (Round 114)
    for marker in _DECOMP_BY_MARKERS:
        i = hay.find(marker)
        if i >= 0:
            tail = hay[i + len(marker):].strip()
            token = re.split(r"[\s,。.，?？]+", tail)[0] if tail else ""
            if token:
                entry = idx.find_dim(token)
                if entry and _is_categorical(entry.column_name):
                    return entry.column_name

    # Pick the LONGEST categorical-on-block keyword match. (Round 114: don't just
    # take best_dim_match's single longest — that can be a non-categorical column
    # like a duration measure, causing the resolver to give up instead of falling
    # back to a real categorical dimension like step_name.)
    # Round 126/127: prefer an explicitly-named ENTITY column (lot/wafer/tool/
    # product/step/area …) over a descriptive ATTRIBUTE column (reason/status/
    # type/bin). Use entity TOKENS, NOT the '_id' suffix — a row-PK like move_id /
    # yield_event_id ends in _id but is not a grouping entity and must not win.
    def _is_entity_col(col: str) -> bool:
        low = col.lower()
        if any(t in low for t in ("move_id", "event_id", "record_id", "row_id", "_uid")):
            return False
        return any(t in low for t in ("lot", "wafer", "tool", "product", "customer",
                                      "store", "item", "sku", "member", "step", "area",
                                      "category", "family", "vendor", "group", "machine"))

    ent_col, ent_len, any_col, any_len = None, 0, None, 0
    for kw, entry in idx._dims.items():
        if kw in hay and _is_categorical(entry.column_name):
            if len(kw) > any_len:
                any_col, any_len = entry.column_name, len(kw)
            if _is_entity_col(entry.column_name) and len(kw) > ent_len:
                ent_col, ent_len = entry.column_name, len(kw)
    # An entity dim (tool/product/step…) always wins. But a non-entity ATTRIBUTE
    # match (e.g. defect_type via "不良" inside "不良率") must NOT beat an explicitly
    # named axis below — so only return any_col AFTER the explicit-axis fallbacks
    # (Round 184 S19: "依機台看不良率" was grouping by defect_type, not the tool).
    if ent_col:
        return ent_col
    # Round 184 (S14): a colloquial SHIFT value ("Day班/Night班/白天班/夜班") names
    # the shift dimension — resolve it FIRST, before the tool fallback below (whose
    # "誰" would otherwise hijack "Day班…誰高" to a tool axis).
    if any(t in hay for t in ("day班", "night班", "白天班", "夜班", "日班", "早班",
                              "晚班", "大夜", "班別", "輪班", "shift", "白班")):
        contract = contracts.get(block_id)
        names = {c.name for c in getattr(contract, "columns", None) or []}
        for cand in ("shift", "shift_name", "班別"):
            if cand in names and _is_categorical(cand):
                return cand
    # Round 178 (S1): a generic "機台/設備/機器/tool" with no specific dim keyword
    # should still resolve a tool axis (etch_tool_id / tool_id) on this block,
    # instead of giving up and letting the caller fall back to a wrong column.
    if any(t in hay for t in ("機台", "機臺", "設備", "機器", "machine", "tool",
                              "chamber", "腔體", "哪台", "哪臺", "誰", "哪部")):
        contract = contracts.get(block_id)
        names = {c.name for c in getattr(contract, "columns", None) or []}
        for cand in ("etch_tool_id", "tool_id", "tool_group"):
            if cand in names and _is_categorical(cand):
                return cand
    # Round 182 (S5): a generic "產品/產品族/各族/product family" with no specific
    # dim keyword resolves the product_family axis on this block.
    if any(t in hay for t in ("產品族", "產品別", "各族", "品族", "product family",
                              "product_family", "產品", "product")):
        contract = contracts.get(block_id)
        names = {c.name for c in getattr(contract, "columns", None) or []}
        for cand in ("product_family", "product", "product_id", "sku"):
            if cand in names and _is_categorical(cand):
                return cand
    # last resort: a non-entity attribute that matched (e.g. defect_type, status).
    return any_col


def _trend_tool_column(contracts, block_id: str) -> str | None:
    """Round 182 (S1): the categorical TOOL/entity column on a yield block, used
    to (a) filter a trend to a named tool and (b) name the worst-declining tool.
    Prefers an explicit tool id; never returns a row-PK."""
    c = (contracts or {}).get(block_id)
    names = [col.name for col in getattr(c, "columns", None) or []]

    def _is_cat(name: str) -> bool:
        for col in getattr(c, "columns", None) or []:
            if col.name == name:
                return getattr(col, "data_type", "") in (
                    "string", "str", "object", "text", "varchar")
        return False

    for pref in ("etch_tool_id", "tool_id", "tool_group", "machine_id"):
        if pref in names and _is_cat(pref):
            return pref
    for col in names:
        low = col.lower()
        if _is_pk_like(col):
            continue
        if any(t in low for t in ("tool", "machine", "chamber", "腔")) and _is_cat(col):
            return col
    return None


def _trend_named_value(prompt: str, normalized: str, contract, col: str) -> str | None:
    """Round 182 (S1): if the prompt names a specific value of ``col`` (e.g.
    "ETCH-01 的良率趨勢"), return that value so the trend can be filtered to it.
    Matches case-/space-insensitively against the column's distinct values."""
    if contract is None or not col:
        return None
    try:
        from ai4bi.blocks.datastore import materialize_dataframe
        df = materialize_dataframe(contract)
    except Exception:  # noqa: BLE001
        return None
    if df is None or col not in getattr(df, "columns", []):
        return None
    hay = f"{prompt} {normalized}".upper().replace(" ", "")
    best: str | None = None
    best_len = 0
    try:
        values = df[col].dropna().astype(str).unique()
    except Exception:  # noqa: BLE001
        return None
    for v in values:
        token = str(v).upper().replace(" ", "")
        if len(token) >= 3 and token in hay and len(token) > best_len:
            best, best_len = str(v), len(token)
    return best


def _metric_is_ratio(contracts, block_id: str, metric_name: str) -> bool:
    """True if the metric is a ratio/average (yield %, rate, margin) — Round 178:
    such metrics must NOT be summed across groups in a change decomposition."""
    c = (contracts or {}).get(block_id)
    if c is not None:
        for m in getattr(c, "metrics", []) or []:
            if getattr(m, "name", None) == metric_name:
                val = getattr(getattr(m, "disaggregation_method", None), "value", None)
                if val in ("average", "none"):
                    return True
                if val in ("sum", "count"):
                    return False
    n = (metric_name or "").lower()
    return any(k in n for k in ("yield", "pct", "percent", "rate", "ratio", "margin", "avg", "average"))


def _compose_decomposition_sentence(alias, dim_col, df, total, unit, scope,
                                    is_ratio: bool = False) -> str:
    """Build the ranked-contributor answer sentence for a change decomposition."""
    arrow = "成長" if total >= 0 else "下降"
    _recompute = "（加權重算）" if is_ratio else ""
    # Round 178: a CHANGE in a ratio metric (yield %) is in percentage POINTS, not
    # "%" — say 個百分點 so a -8.8pp drop isn't misread as a -8.8% relative change.
    _pp = is_ratio and (unit or "").strip() in ("%", "％")

    def _fmt(v: float) -> str:
        return f"{abs(v):,.2f} 個百分點" if _pp else _format_metric_value(abs(v), unit)

    head = (f"{scope}「{alias}」整體{arrow} {_fmt(total)}{_recompute}，"
            f"依「{dim_col}」拆解：")
    dim_name = df.columns[0]

    def _suffix(row) -> str:
        # ratio metrics have no additive contribution (NaN) — show movers only.
        pct = row.get("contribution_pct")
        return f"（佔{abs(pct):.0f}%）" if pct is not None and pct == pct else ""

    # df is sorted by delta ascending (biggest decliners first).
    decliners = df[df["delta"] < 0].head(2)
    risers = df[df["delta"] > 0].sort_values("delta", ascending=False).head(2)
    parts: list[str] = []
    for _, row in decliners.iterrows():
        parts.append(f"{row[dim_name]} ↓{_fmt(row['delta'])}{_suffix(row)}")
    for _, row in risers.iterrows():
        parts.append(f"{row[dim_name]} ↑{_fmt(row['delta'])}{_suffix(row)}")
    if not parts:
        return head + "各維度變化不顯著。"
    return head + "；".join(parts) + "。"


# --- Round 080: measure-filter (HAVING) parsing -----------------------------

# Comparison phrase → FilterOperator. Longer/more-specific phrases first so
# "至少" wins over "少" and "no less than" isn't read as "less than".
_MEASURE_OP_PHRASES: tuple[tuple[str, str], ...] = (
    ("at least", "gte"), ("no less than", "gte"), ("不少於", "gte"), ("至少", "gte"),
    ("at most", "lte"), ("no more than", "lte"), ("不超過", "lte"), ("不多於", "lte"), ("至多", "lte"),
    ("greater than or equal", "gte"), ("less than or equal", "lte"),
    ("more than", "gt"), ("greater than", "gt"), ("over", "gt"), ("above", "gt"),
    ("超過", "gt"), ("大於", "gt"), ("多於", "gt"), ("高於", "gt"),
    ("less than", "lt"), ("fewer than", "lt"), ("below", "lt"), ("under", "lt"),
    ("低於", "lt"), ("少於", "lt"), ("小於", "lt"), ("不到", "lt"),
    (">=", "gte"), ("<=", "lte"), (">", "gt"), ("<", "lt"),
)


def _looks_like_measure_filter(prompt: str, normalized: str) -> bool:
    """True when the prompt is a post-aggregate threshold on a measure."""
    hay = f"{prompt.lower()} {normalized}"
    if not any(phrase in hay for phrase, _ in _MEASURE_OP_PHRASES):
        return False
    return re.search(r"\d", hay) is not None


def _measure_operator(hay: str):
    from ai4bi.query_spec import FilterOperator
    for phrase, opname in _MEASURE_OP_PHRASES:
        if phrase in hay:
            return getattr(FilterOperator, opname if opname != "in" else "in_")
    return None


def _extract_measure_filter(prompt: str, normalized: str, visual):
    """Resolve (MetricRef, operator, numeric_value) against a visual's metrics.

    Returns None when no operator, number, or projected metric can be found.
    The metric must be one the visual already projects (the executor requires a
    HAVING to reference a projected measure).
    """
    hay = f"{prompt.lower()} {normalized}"
    operator = _measure_operator(hay)
    if operator is None:
        return None

    num_match = re.search(r"(\d[\d,]*\.?\d*)", hay)
    if num_match is None:
        return None
    raw = num_match.group(1).replace(",", "")
    try:
        value: float = float(raw)
        if value.is_integer():
            value = int(value)
    except ValueError:
        return None

    metrics = visual.query.metrics
    if not metrics:
        return None

    # Match the threshold to one of the visual's projected metrics by keyword.
    def _metric_keywords(m) -> list[str]:
        kws = {m.metric_name.lower(), (m.alias or "").lower()}
        for tok in re.split(r"[_\s]+", m.metric_name.lower()):
            if tok:
                kws.add(tok)
                for zh in _METRIC_SYNONYMS.get(tok, []):
                    kws.add(zh)
        return [k for k in kws if k]

    chosen = None
    best_len = 0
    for m in metrics:
        for kw in _metric_keywords(m):
            if kw and kw in hay and len(kw) > best_len:
                chosen = m
                best_len = len(kw)
    if chosen is None:
        # No explicit metric word — default to the sole/first projected metric.
        chosen = metrics[0]

    return chosen, operator, value


# Light ZH/EN synonyms for matching a metric word in a measure-filter prompt.
_METRIC_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["營收", "收入", "業績", "銷售額"],
    "sales": ["銷售", "業績"],
    "orders": ["訂單", "次", "次數", "筆數", "購買"],
    "order": ["訂單", "次"],
    "count": ["次數", "筆數", "數量"],
    "quantity": ["數量", "件數"],
    "amount": ["金額"],
    "profit": ["利潤", "獲利"],
    "margin": ["毛利", "利潤率"],
    "headcount": ["員工", "人數"],
}


def _compose_answer_sentence(
    alias: str,
    value: float | None,
    unit: str,
    period: str,
    previous: float | None,
    delta_pct: float | None,
    cur_label: str,
    prev_label: str,
) -> str:
    """Build the human-readable answer sentence (with delta when available)."""
    vtxt = _format_metric_value(value, unit)
    scope = _PERIOD_TITLE.get(period, "全期間")
    base = f"{scope}「{alias}」為 {vtxt}。"
    if delta_pct is not None and previous is not None:
        arrow = "↑" if delta_pct >= 0 else "↓"
        ptxt = _format_metric_value(previous, unit)
        base += f"　較{prev_label} {ptxt} {arrow}{abs(delta_pct):.1f}%。"
    return base


def _target_scope(selected_component_id: str | None) -> str:
    return f"visual:{selected_component_id}" if selected_component_id else "report"


def _looks_like_style_request(prompt: str, normalized: str) -> bool:
    return (
        any(term in normalized for term in _STYLE_TERMS)
        or any(alias in prompt for alias in _COLOR_ALIASES)
        or "蝝" in prompt
    )


def _looks_like_queue_analysis(normalized: str) -> bool:
    return any(term in normalized for term in _QUEUE_TERMS) and any(term in normalized for term in _ANALYSIS_TERMS)


def _extract_color(prompt: str, normalized: str) -> str | None:
    for source, color_name in _COLOR_ALIASES.items():
        if source in prompt:
            return _COLOR_HEX[color_name]
    if "蝝" in prompt:
        return _COLOR_HEX["red"]
    for name, value in _COLOR_HEX.items():
        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return value
    hex_match = re.search(r"#[0-9a-fA-F]{6}\b", prompt)
    return hex_match.group(0).upper() if hex_match else None


def _find_visual(
    report: ExecutableReportSpec,
    selected_component_id: str | None,
) -> tuple[str, str, ReportVisualSpec] | None:
    if not selected_component_id:
        return None
    for page_id, page in report.pages.items():
        visual = page.visuals.get(selected_component_id)
        if visual is not None:
            return page_id, selected_component_id, visual
    return None


def _selection_from_visual(visual: ReportVisualSpec) -> SemanticSelection:
    metric = visual.query.metrics[0] if visual.query.metrics else None
    dimension = visual.query.dimensions[0] if visual.query.dimensions else None
    filter_spec = visual.query.filters[0] if visual.query.filters else None
    return SemanticSelection(
        metric_block_id=metric.block_id if metric else None,
        metric_name=metric.metric_name if metric else None,
        dimension_block_id=dimension.block_id if dimension else None,
        dimension_name=dimension.column_name if dimension else None,
        filter_block_id=filter_spec.block_id if filter_spec else None,
        filter_name=filter_spec.column_name if filter_spec else None,
        filter_value=filter_spec.value if filter_spec else None,
    )


def _selection_from_semantic_model(semantic_model: dict[str, Any] | None) -> SemanticSelection:
    for metric in (semantic_model or {}).get("metrics", []):
        metric_id = metric.get("metric_id", "")
        if "queue" in metric_id:
            return SemanticSelection(
                metric_block_id=metric.get("owner_block"),
                metric_name=metric_id,
            )
    return SemanticSelection(metric_block_id="process_move_fact", metric_name="queue_time_hr")


def _first_queue_visual(report: ExecutableReportSpec) -> tuple[str, str, ReportVisualSpec] | None:
    for page_id, page in report.pages.items():
        for visual_id, visual in page.visuals.items():
            if _visual_mentions_queue(visual_id, visual):
                return page_id, visual_id, visual
    return None


def _queue_visual_ids(report: ExecutableReportSpec) -> list[str]:
    return [
        visual_id
        for page in report.pages.values()
        for visual_id, visual in page.visuals.items()
        if _visual_mentions_queue(visual_id, visual)
    ]


def _visual_mentions_queue(visual_id: str, visual: ReportVisualSpec) -> bool:
    title = visual.visualization.title or ""
    metric_names = " ".join(metric.metric_name for metric in visual.query.metrics)
    return "queue" in f"{visual_id} {title} {metric_names}".lower()


# ---------------------------------------------------------------------------
# Round 019: Detection helpers for new intents
# ---------------------------------------------------------------------------

def _looks_like_chart_type_change(prompt: str, normalized: str) -> bool:
    """Detect requests to change chart type."""
    chart_keywords = (
        "bar chart", "line chart", "pie chart", "scatter chart", "donut",
        "長條圖", "柱狀圖", "折線圖", "trend chart", "圓餅圖", "甜甜圈圖", "散點圖", "散佈圖",
    )
    change_keywords = ("change", "convert", "switch", "改成", "換成", "轉成", "改為", "換為")
    has_chart = any(k in normalized or k in prompt for k in chart_keywords)
    has_change = any(k in normalized or k in prompt for k in change_keywords)
    if has_chart and has_change:
        return True
    if re.search(r"(改|換|轉)(成|為|做)\s*(長條圖|折線圖|圓餅圖|散點圖|bar|line|pie|scatter)", prompt):
        return True
    return False


def _extract_chart_type(prompt: str, normalized: str) -> VisualType | None:
    """Extract the target chart type from a change request."""
    for keyword, vtype in _CHART_TYPE_KEYWORDS.items():
        if keyword in normalized or keyword in prompt:
            return vtype
    return None


_ADD_VISUAL_VERBS = (
    "add", "create", "新增", "加一", "加個", "加上", "加 ", "建立", "做一", "做個", "畫一", "畫個", "畫個",
)


def _looks_like_add_trend_line(prompt: str, normalized: str) -> bool:
    """Detect a request to ADD a trend line / regression overlay.

    Must be an *add* intent — a style request like "make the trend line red"
    is a colour change, not an add, and must fall through to the style handler.
    """
    keys = ("趨勢線", "trend line", "trendline", "迴歸線", "回歸線", "regression")
    if not any(k in normalized or k in prompt for k in keys):
        return False
    has_add = ("加" in prompt or any(v in normalized or v in prompt for v in _ADD_VISUAL_VERBS))
    # exclude colour/style verbs ("make ... red", "改成紅色")
    style_words = ("red", "blue", "green", "color", "colour", "紅", "藍", "綠",
                   "顏色", "make", "改成", "換成", "改為", "換為", "style")
    has_style = any(w in normalized or w in prompt for w in style_words)
    return has_add and not has_style


def _looks_like_add_visual(prompt: str, normalized: str) -> bool:
    """Detect a request to ADD a NEW chart (vs change an existing one).

    Requires an add-verb plus a chart-type keyword; the change-verb path
    (_looks_like_chart_type_change) handles 'change to pie' separately.
    """
    has_chart = any(k in normalized or k in prompt for k in _ADD_VISUAL_TYPE_KEYWORDS)
    if not has_chart:
        return False
    has_add = any(v in normalized or v in prompt for v in _ADD_VISUAL_VERBS)
    has_change = any(k in normalized or k in prompt
                     for k in ("change", "convert", "switch", "改成", "換成", "轉成", "改為", "換為"))
    return has_add and not has_change


def _looks_like_dimension_change(prompt: str, normalized: str) -> bool:
    """Detect requests to change date grouping: 月份, week, daily, etc."""
    granularity_terms = list(_DIMENSION_DATE_KEYWORDS.keys())
    group_terms = ("group by", "groupby", "按", "改用", "以", "用", "分組", "分析")
    has_granularity = any(k in normalized or k in prompt for k in granularity_terms)
    has_group = any(k in normalized or k in prompt for k in group_terms)
    return has_granularity and has_group


def _extract_date_granularity(prompt: str, normalized: str) -> str | None:
    """Extract date truncation value: 'month', 'week', 'day', 'quarter', 'year'."""
    for keyword, granularity in _DIMENSION_DATE_KEYWORDS.items():
        if keyword in normalized or keyword in prompt:
            return granularity
    return None


def _find_time_column(visual: ReportVisualSpec) -> str | None:
    """Find the first dimension column that looks like a time/date column."""
    time_suffixes = ("date", "time", "day", "month", "year", "ts", "at", "_dt",
                     "日期", "時間", "日", "月", "年")
    for dim in visual.query.dimensions:
        col = dim.column_name.lower()
        if any(col.endswith(s) or s in col for s in time_suffixes):
            return dim.column_name
    # If no obvious time column, return the first dimension column
    if visual.query.dimensions:
        return visual.query.dimensions[0].column_name
    return None


def _extract_add_metric_name(prompt: str, normalized: str) -> str | None:
    """Extract a metric name from an add-metric request."""
    for pattern in _METRIC_ADD_PATTERNS:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    # Also try: "也顯示 move_count"
    match = re.search(r"也\s*(顯示|加入|加)\s*(\w+)", prompt)
    if match:
        return match.group(2).strip()
    return None


def _extract_remove_metric_name(prompt: str, normalized: str) -> str | None:
    """Extract a metric name from a remove-metric request."""
    for pattern in _REMOVE_METRIC_PATTERNS:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _looks_like_remove_metric(prompt: str, normalized: str) -> bool:
    return _extract_remove_metric_name(prompt, normalized) is not None


def _extract_rename_title(prompt: str, normalized: str) -> str | None:
    """Extract the new title from a rename-visual request."""
    for pattern in _RENAME_VISUAL_PATTERNS:
        match = re.search(pattern, prompt, re.IGNORECASE | re.UNICODE)
        if match:
            title = match.group(1).strip().strip("'\"")
            if title:
                return title
    return None


def _looks_like_rename_visual(prompt: str, normalized: str) -> bool:
    rename_triggers = (
        "rename", "change title", "set title", "把這張圖改名", "把这张图改名",
        "名稱改成", "改名叫", "命名為", "命名成",
    )
    has_trigger = any(t.lower() in normalized or t in prompt for t in rename_triggers)
    return has_trigger and _extract_rename_title(prompt, normalized) is not None


def _blocked_terms(normalized: str) -> list[str]:
    terms = []
    for term in ("sql", "join", "yield", "detail", "raw"):
        if term in normalized:
            terms.append(term)
    return terms


# ---------------------------------------------------------------------------
# Round 020: Date filter detection helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Round 022: Categorical dimension detection helpers
# ---------------------------------------------------------------------------

# Known categorical dimension columns in semiconductor demo (and generic aliases)
_CATEGORICAL_DIM_MAP: dict[str, dict] = {
    # product family
    "product family": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    "product_family": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    "產品": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    "產品族": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    # vendor
    "vendor": {"block_id": "tool_dim", "column_name": "vendor", "alias": "Vendor"},
    "供應商": {"block_id": "tool_dim", "column_name": "vendor", "alias": "Vendor"},
    "廠商": {"block_id": "tool_dim", "column_name": "vendor", "alias": "Vendor"},
    # tool_id
    "tool": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "tool id": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "tool_id": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "設備": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "機台": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    # process step
    "process step": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    "step": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    "製程": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    "製程步驟": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    # lot
    "lot": {"block_id": "lot_dim", "column_name": "lot_id", "alias": "Lot"},
    "批次": {"block_id": "lot_dim", "column_name": "lot_id", "alias": "Lot"},
}

_CAT_DIM_TRIGGERS = ("group by", "分組", "按", "group", "breakdown by", "by ", "改用", "按照")


def _extract_categorical_dimension(
    prompt: str,
    normalized: str,
    contracts: dict | None = None,
) -> dict | None:
    """Extract a categorical dimension target from the prompt.

    Round 035: Falls back to SchemaIndex (dynamic lookup from loaded contracts)
    when the static semiconductor map has no match.

    Returns {"block_id": ..., "column_name": ..., "alias": ...} or None.
    Only triggers when a group/dimension change verb is present.
    """
    has_trigger = any(t.lower() in normalized or t in prompt for t in _CAT_DIM_TRIGGERS)
    if not has_trigger:
        return None
    # Longest match wins — static map first
    best: dict | None = None
    best_len = 0
    for keyword, dim in _CATEGORICAL_DIM_MAP.items():
        kw_lower = keyword.lower()
        if kw_lower in normalized or keyword in prompt:
            if len(keyword) > best_len:
                best = dim
                best_len = len(keyword)

    # Round 035: dynamic fallback via SchemaIndex
    if best is None and contracts:
        idx = SchemaIndex.build(contracts)
        entry = idx.best_dim_match(prompt, normalized)
        if entry is not None:
            best = {
                "block_id": entry.block_id,
                "column_name": entry.column_name,
                "alias": entry.alias,
            }
    return best


def _certified_dim_targets_for_fact(fact_block_id: str, semantic_model: dict) -> set[str]:
    """Return block_ids of certified dimension targets reachable from fact_block_id."""
    result: set[str] = set()
    for rel in semantic_model.get("relationships", []):
        if rel.get("from_block") == fact_block_id and rel.get("status") == "certified":
            result.add(rel["to_block"])
    return result


# ---------------------------------------------------------------------------
# Round 022: Value filter detection helpers
# ---------------------------------------------------------------------------

# Known filterable categorical values in the semiconductor demo
_VALUE_FILTER_MAP: dict[str, tuple[str, str]] = {
    # process steps — step_id in process_move_fact
    # (Logic-A/B are handled via report controls, not direct query filter)
    "photo": ("process_move_fact", "step_id"),
    "etch": ("process_move_fact", "step_id"),
    "cvd": ("process_move_fact", "step_id"),
    "cmp": ("process_move_fact", "step_id"),
    "implant": ("process_move_fact", "step_id"),
}

_VALUE_FILTER_TRIGGER_TERMS = (
    "only show", "filter to", "only", "just show", "show only",
    "只看", "只顯示", "只有", "篩選到", "過濾到", "filter",
)


def _extract_value_filter(prompt: str, normalized: str) -> tuple[str, list[str]] | None:
    """
    Extract (column_name, [values]) from a value filter request.
    Returns None if no recognizable filter pattern detected.
    """
    has_trigger = any(t.lower() in normalized or t in prompt for t in _VALUE_FILTER_TRIGGER_TERMS)
    if not has_trigger:
        return None
    matched_values: dict[tuple[str, str], list[str]] = {}  # (block_id, column) → values
    for keyword, (block_id, column) in _VALUE_FILTER_MAP.items():
        if keyword in normalized:
            key = (block_id, column)
            matched_values.setdefault(key, []).append(keyword.upper())
    if not matched_values:
        return None
    # Return the first column group found (most specific match)
    for (block_id, column), values in matched_values.items():
        return column, values
    return None


def _find_block_for_column(visual: ReportVisualSpec, column_name: str, semantic_model: dict) -> str | None:
    """Find which block in the visual's block_refs contains the given column."""
    # Check fact block first (process_move_fact has step_id, product_family)
    for ref in visual.query.block_refs:
        block_id = ref.block_id
        # Check semantic model certified relationships
        if column_name in ("step_id", "product_family", "tool_id", "wafer_id", "lot_id"):
            return block_id  # These are FK columns on the fact block
    # Fallback: return primary block
    if visual.query.block_refs:
        return visual.query.block_refs[0].block_id
    return None


def _looks_like_date_filter(prompt: str, normalized: str) -> bool:
    """Detect relative date period requests."""
    # Direct keyword match (fast path)
    for keyword in _DATE_FILTER_PERIOD_MAP:
        if keyword.lower() in normalized or keyword in prompt:
            return True
    # Trigger term match (broader)
    return any(term.lower() in normalized or term in prompt for term in _DATE_FILTER_TRIGGER_TERMS)


def _extract_date_period(prompt: str, normalized: str) -> str | None:
    """Extract the canonical period key from a date filter request."""
    # Check exact keyword match first (longest match wins)
    best_match: str | None = None
    best_len = 0
    for keyword, period in _DATE_FILTER_PERIOD_MAP.items():
        kw_lower = keyword.lower()
        if kw_lower in normalized or keyword in prompt:
            if len(keyword) > best_len:
                best_match = period
                best_len = len(keyword)
    return best_match


# ---------------------------------------------------------------------------
# Round 036: Period comparison detection
# ---------------------------------------------------------------------------

_PERIOD_COMPARISON_KEYWORDS = (
    "vs", "versus", "compare", "comparison", "compared",
    "比較", "對比", "比", "vs.", "相比",
    # Round 184 (S17): "這週跟上週 / 本月和上月" — the most natural connectors. Safe
    # because a period word is also required (won't fire on "記憶體跟邏輯").
    "跟", "和", "與",
)
_PERIOD_COMPARISON_PERIOD_KEYWORDS = (
    "week", "weekly", "週", "這週", "本週", "上週",
    "month", "monthly", "月", "這月", "本月", "上月",
)


def _looks_like_period_comparison(prompt: str, normalized: str) -> bool:
    has_vs = any(k in normalized or k in prompt for k in _PERIOD_COMPARISON_KEYWORDS)
    has_period = any(k in normalized or k in prompt for k in _PERIOD_COMPARISON_PERIOD_KEYWORDS)
    return has_vs and has_period


def _extract_comparison_period(normalized: str, prompt: str) -> tuple:
    if any(k in normalized or k in prompt for k in ("month", "monthly", "月", "本月", "這月", "上月")):
        return ("month", "本月", "上月")
    if any(k in normalized or k in prompt for k in ("week", "weekly", "週", "本週", "這週", "上週")):
        return ("week", "本週", "上週")
    return ("week", "近 7 天", "前 7 天")
