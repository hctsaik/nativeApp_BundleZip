"""LLM adapter for governed NL-to-intent classification.

Modes
-----
LLM_MODE=mock   (default) — deterministic keyword routing; no API call.
LLM_MODE=anthropic         — calls Claude via Anthropic SDK for intent
                             classification; falls back to mock on error or
                             missing key.

The LLM is *only* responsible for recognising which governed intent the user
meant.  All governance / safety enforcement still runs in NL2ProposalService
— this layer is purely a smarter parser front-end.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported intent types (mirrors NL2ProposalService handler names)
# ---------------------------------------------------------------------------

SUPPORTED_INTENTS = (
    "style_change",           # change chart colour
    "chart_type_change",      # bar ↔ line
    "dimension_change",       # date granularity (month/week/day/quarter/year)
    "add_metric",             # add a metric to the visual
    "remove_metric",          # remove a metric from the visual
    "rename_visual",          # rename chart title
    "categorical_dimension_change",  # group by vendor / product / tool …
    "value_filter_change",    # only show ETCH / PHOTO / CVD …
    "date_filter_change",     # last 3 months / last quarter / ytd …
    "queue_analysis",         # governed queue-time analysis plan
    # ── Round 027: Visual Composer ──────────────────────────────────────
    "add_visual",             # create a new chart/table on the canvas
    "highlight_outliers",     # conditional formatting on table — colour outliers
    "add_trend_line",         # add trend-line overlay to a line/bar chart
    # ── Round 078-091: conversational answer engine (computed answers) ──────
    "answer_metric",          # "how much revenue last month?" → a number
    "ranking",                # "top 5 products by revenue" → ranked table
    "breakdown",              # "revenue by region" → grouped table (no superlative)
    "crossfact",              # cross-fact correlation / cohort / ratio (two facts)
    "spc",                    # SPC control-limit outliers (mean ± k-sigma)
    "commonality",            # shared tool across lots failing a yield cut
    "matrix",                 # 2-dimension cross-tab (dim1 x dim2)
    "multi_filter",           # multi-condition AND filter then a metric
    "capacity",               # utilization / loading / headroom / plan / throughput
    "oee",                    # overall equipment effectiveness
    "grouped_topn",           # "top 3 products per store" → per-group ranked table
    "segment_count",          # "customers who bought > 3 times" → list (HAVING)
    "explain_change",         # "why did revenue drop? decompose by region"
    "pacing_question",        # "are we on track to target?"
    "panel_analysis",         # churn/RFM, declining-streak, basket questions
    "measure_filter",         # filter an existing visual on an aggregate
    "seasonality",            # busiest day-of-week / hour
    "insights",               # weekly digest / anomaly scan
    "calendar_yoy",           # this month vs same month last year
    "analytics_chart",        # pareto/ABC, %-of-total, moving-average, forecast
    "entity_compare",         # compare two named entities side by side
    "unsupported",            # anything else
)

# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

@dataclass
class IntentClassification:
    intent: str
    parameters: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    mode: str = "mock"          # "mock" | "llm"
    confidence: float = 1.0
    # Mixed-prompt support: second intent when prompt contains both style and analysis
    secondary_intent: str | None = None
    secondary_parameters: dict[str, Any] = field(default_factory=dict)
    disambiguation: str | None = None  # clarifying question from LLM when ambiguous


# ---------------------------------------------------------------------------
# Anthropic tool schema
# ---------------------------------------------------------------------------

_CLASSIFY_TOOL = {
    "name": "classify_bi_intent",
    "description": (
        "Classify the user's natural-language BI request into one of the "
        "supported governed intent types.  The downstream system uses this "
        "classification to generate a safe, governed proposal — no SQL is "
        "ever generated.  Choose 'unsupported' only when the request cannot "
        "map to any supported intent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": list(SUPPORTED_INTENTS),
                "description": "The classified intent type.",
            },
            "parameters": {
                "type": "object",
                "description": (
                    "Intent-specific parameters.  Supply only the relevant "
                    "keys for the chosen intent:\n"
                    "- style_change: color (English name, e.g. 'red')\n"
                    "- chart_type_change: target_type ('bar_chart' | 'line_chart' | 'pie_chart' | 'scatter')\n"
                    "- dimension_change: granularity ('month'|'week'|'day'|'quarter'|'year')\n"
                    "- add_metric: metric_name (snake_case identifier)\n"
                    "- remove_metric: metric_name (snake_case identifier)\n"
                    "- rename_visual: new_title (the desired new title string)\n"
                    "- categorical_dimension_change: dimension_keyword "
                    "  (e.g. 'vendor', 'product family', 'tool')\n"
                    "- value_filter_change: filter_values (list of strings, "
                    "  e.g. ['ETCH'], ['PHOTO','CVD'])\n"
                    "- date_filter_change: period (e.g. 'last 3 months', "
                    "  '最近3個月', 'last quarter', 'ytd')\n"
                    "- queue_analysis: (no extra parameters needed)\n"
                    "- add_visual: visual_type ('line_chart'|'bar_chart'|'table'|'kpi_card'), "
                    "  metric (metric_name e.g. 'queue_time_hr'), "
                    "  dimension (keyword e.g. 'vendor', '月份', 'tool_id'), "
                    "  title (optional chart title), step_filter (optional e.g. 'ETCH')\n"
                    "- highlight_outliers: visual_id (null=auto), column (null=auto), "
                    "  method ('iqr'|'zscore'), color (hex default '#FF4444')\n"
                    "- add_trend_line: visual_id (null=auto), "
                    "  method ('linear'|'moving_avg'), window (int default 3)\n"
                    "- unsupported: reason (brief human-readable explanation)"
                ),
                "additionalProperties": True,
            },
            "reasoning": {
                "type": "string",
                "description": "One sentence explaining why you chose this intent.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Classification confidence 0–1.",
            },
            "secondary_intent": {
                "type": "string",
                "enum": list(SUPPORTED_INTENTS) + ["none"],
                "description": (
                    "Use when the prompt contains TWO distinct governed intents "
                    "(mixed prompt). Example: '用紅線顯示最近三個月' has both a "
                    "style_change (red) and a date_filter_change (last 3 months). "
                    "Set to 'none' or omit when there is only one intent. "
                    "IMPORTANT: style_change and analysis intents must NOT be merged "
                    "into one — set primary to the analysis intent and secondary to "
                    "style_change (or vice versa)."
                ),
            },
            "secondary_parameters": {
                "type": "object",
                "description": "Parameters for the secondary intent (same key conventions as 'parameters').",
                "additionalProperties": True,
            },
            "disambiguation_question": {
                "type": "string",
                "description": (
                    "When the request is ambiguous and you need the user to clarify, "
                    "set this to a short clarifying question (max 100 chars). "
                    "Example: '您想按「月份」還是「供應商」分組？' "
                    "Only set when intent='unsupported' and the request COULD match a governed "
                    "intent if clarified. Leave empty otherwise."
                ),
            },
        },
        "required": ["intent", "parameters", "reasoning", "confidence"],
    },
}

# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(
    prompt: str,
    report: Any,
    selected_component_id: str | None,
) -> str:
    """Build a compact context string to include in the LLM prompt."""
    lines: list[str] = [
        "=== BI Report Context ===",
    ]

    # Current visual info
    visual = None
    if selected_component_id and report is not None:
        for page in report.pages.values():
            v = page.visuals.get(selected_component_id)
            if v is not None:
                visual = v
                break

    if visual is not None:
        vtype = visual.visualization.visual_type.value
        title = visual.visualization.title or selected_component_id
        metrics = [m.metric_name for m in visual.query.metrics]
        dims = [d.column_name for d in visual.query.dimensions]
        lines.append(f"Selected visual: '{title}' (type: {vtype})")
        lines.append(f"Metrics: {', '.join(metrics) if metrics else 'none'}")
        lines.append(f"Dimensions: {', '.join(dims) if dims else 'none'}")
    else:
        lines.append("Selected visual: none")

    # Available metrics from semantic model (needed for add_metric governance)
    if report is not None and hasattr(report, "_semantic_model_ref"):
        pass  # will be added by caller if needed

    # Try to extract metrics from report's loaded semantic model context
    # (passed separately via the propose() call)
    lines.append("")
    lines.append(f"User request: \"{prompt}\"")
    lines.append("")
    lines.append(
        "Classify the user request into one of the supported intents and "
        "extract the relevant parameters.  Governance rules:\n"
        "- Never suggest generating SQL.\n"
        "- Never suggest modifying semantic model relationships.\n"
        "- Only suggest governed intents from the allowed list.\n"
        "- Use 'unsupported' only when no governed intent fits."
    )
    return "\n".join(lines)


def build_context_with_semantic_model(
    prompt: str,
    report: Any,
    selected_component_id: str | None,
    semantic_model: dict | None,
) -> str:
    """Extended context builder that includes semantic model metrics."""
    base = _build_context(prompt, report, selected_component_id)
    if not semantic_model:
        return base

    lines = [base, "", "=== Available Certified Metrics ==="]
    for m in semantic_model.get("metrics", []):
        mid = m.get("metric_id") or m.get("id") or m.get("name", "")
        label = m.get("label", mid)
        owner = m.get("owner_block") or m.get("base_dataset") or m.get("block_id", "")
        agg = m.get("aggregation") or m.get("aggregation_type", "")
        lines.append(f"- {mid} ({label}) [{agg}] owner: {owner}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Adapter
# ---------------------------------------------------------------------------

class LLMAdapter:
    """Intent classifier that switches between mock and Anthropic API modes.

    Usage
    -----
        adapter = LLMAdapter()
        classification = adapter.classify(prompt, report, visual_id)
    """

    def __init__(self) -> None:
        self._mode = os.getenv("LLM_MODE", "mock").strip().lower()
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self._model = os.getenv(
            "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"
        ).strip()

    @property
    def active_mode(self) -> str:
        """Return 'llm' if Anthropic API will be used, else 'mock'."""
        if self._mode == "anthropic" and self._api_key:
            return "llm"
        return "mock"

    def classify(
        self,
        prompt: str,
        report: Any,
        selected_component_id: str | None = None,
        semantic_model: dict | None = None,
    ) -> IntentClassification:
        """Classify the user prompt into a governed intent.

        Returns ``IntentClassification`` with ``mode='llm'`` when the API is
        used, or ``mode='mock'`` to signal the caller should fall through to
        keyword matching.
        """
        if self._mode != "anthropic":
            logger.debug("[llm_adapter] LLM_MODE=%s → mock pass-through", self._mode)
            return IntentClassification(intent="mock_passthrough", mode="mock")

        if not self._api_key:
            logger.warning(
                "[llm_adapter] LLM_MODE=anthropic but ANTHROPIC_API_KEY is not set "
                "— falling back to mock mode.  Set ANTHROPIC_API_KEY to enable LLM."
            )
            return IntentClassification(intent="mock_passthrough", mode="mock")

        try:
            return self._call_anthropic(prompt, report, selected_component_id, semantic_model)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[llm_adapter] Anthropic API error — falling back to mock: %s", exc
            )
            return IntentClassification(intent="mock_passthrough", mode="mock")

    # ------------------------------------------------------------------
    # Private: Anthropic API call
    # ------------------------------------------------------------------

    def _call_anthropic(
        self,
        prompt: str,
        report: Any,
        selected_component_id: str | None,
        semantic_model: dict | None = None,
    ) -> IntentClassification:
        import anthropic  # imported lazily to keep mock-mode free of the dep

        client = anthropic.Anthropic(api_key=self._api_key)
        context = build_context_with_semantic_model(prompt, report, selected_component_id, semantic_model)

        response = client.messages.create(
            model=self._model,
            max_tokens=512,
            tools=[_CLASSIFY_TOOL],
            tool_choice={"type": "any"},
            messages=[
                {
                    "role": "user",
                    "content": context,
                }
            ],
        )

        # Extract tool_use block
        tool_result = _extract_tool_result(response)
        if tool_result is None:
            logger.warning("[llm_adapter] No tool_use in response, falling back to mock")
            return IntentClassification(intent="mock_passthrough", mode="mock")

        intent = tool_result.get("intent", "unsupported")
        if intent not in SUPPORTED_INTENTS:
            intent = "unsupported"

        secondary_intent = tool_result.get("secondary_intent") or "none"
        if secondary_intent == "none" or secondary_intent not in SUPPORTED_INTENTS:
            secondary_intent = None

        disambiguation = tool_result.get("disambiguation_question") or None
        if disambiguation and len(disambiguation) > 200:
            disambiguation = disambiguation[:200]

        classification = IntentClassification(
            intent=intent,
            parameters=tool_result.get("parameters", {}),
            reasoning=tool_result.get("reasoning", ""),
            confidence=float(tool_result.get("confidence", 0.9)),
            mode="llm",
            secondary_intent=secondary_intent,
            secondary_parameters=tool_result.get("secondary_parameters", {}),
            disambiguation=disambiguation,
        )
        logger.debug(
            "[llm_adapter] LLM classified: intent=%s confidence=%.2f reasoning=%s",
            classification.intent,
            classification.confidence,
            classification.reasoning,
        )
        return classification


def _extract_tool_result(response: Any) -> dict | None:
    """Pull the tool_use input dict from an Anthropic Message."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_bi_intent":
            inp = block.input
            if isinstance(inp, str):
                try:
                    return json.loads(inp)
                except json.JSONDecodeError:
                    return None
            if isinstance(inp, dict):
                return inp
    return None


# ---------------------------------------------------------------------------
# Module-level helpers used by NL2ProposalService
# ---------------------------------------------------------------------------

def get_llm_mode_label() -> str:
    """Return a short status string for the UI badge."""
    adapter = LLMAdapter()
    mode = adapter.active_mode
    model = adapter._model if mode == "llm" else ""
    if mode == "llm":
        short = model.split("-")[1] if "-" in model else model
        return f"LLM: {short}"
    return "Mock NL2"
