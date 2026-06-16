"""Typed contracts for AI-grounded BI intent and proposal results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ai4bi.report.models import ReportProposal

IntentKind = Literal["style_change", "analysis_request", "unsupported"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class SemanticSelection:
    """Grounded BI fields selected from a report visual or semantic model."""

    metric_block_id: str | None = None
    metric_name: str | None = None
    dimension_block_id: str | None = None
    dimension_name: str | None = None
    filter_block_id: str | None = None
    filter_name: str | None = None
    filter_value: Any = None


@dataclass(frozen=True)
class AIIntent:
    """Classified user intent before execution or proposal staging."""

    intent_kind: IntentKind
    target_scope: str
    selection: SemanticSelection = field(default_factory=SemanticSelection)
    suggested_visuals: list[str] = field(default_factory=list)
    trust_notes: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "low"


@dataclass(frozen=True)
class AnalysisPlan:
    """Governed analysis plan. This contract is deliberately SQL-free."""

    question: str
    target_scope: str
    selection: SemanticSelection
    steps: list[str]
    suggested_visuals: list[str] = field(default_factory=list)
    trust_notes: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "medium"
    generated_sql: str | None = None


@dataclass(frozen=True)
class DirectAnswer:
    """A computed, sourced answer to a natural-language metric question (Round 078).

    Unlike AnalysisPlan (which describes *what would be done*), DirectAnswer
    carries the actual number computed through the governed executor — turning
    AI4BI from a report *builder* into an *answer engine*. It is still SQL-free
    from the user's perspective: the value comes from a VisualQuerySpec run on
    the certified semantic layer, with full metric/period/source lineage.
    """

    question: str
    metric_block_id: str
    metric_name: str
    metric_alias: str
    sentence: str                       # human-readable answer, ready to show
    value: float | None
    period: str = "all"                 # "all" | "week" | "month" | "quarter" | "year"
    previous: float | None = None
    delta_pct: float | None = None
    current_label: str = ""
    previous_label: str = ""
    unit: str = ""
    trust_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GovernanceRefusal:
    """Structured refusal for requests that bypass governed BI contracts."""

    reason: str
    blocked_terms: list[str] = field(default_factory=list)
    policy_ref: str = "governed_semantic_contract"
    trust_notes: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "high"


@dataclass(frozen=True)
class NL2ProposalResult:
    """Full structured result returned by NL2ProposalService."""

    intent: AIIntent
    message: str
    proposal: ReportProposal | None = None
    analysis_plan: AnalysisPlan | None = None
    direct_answer: "DirectAnswer | None" = None  # Round 078: computed NL answer
    result_table: Any = None  # Round 086: a result DataFrame to show in the answer pane
    refusal: GovernanceRefusal | None = None
    trust_notes: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "low"
    # Mixed-prompt split: when LLM detects both style and analysis intents,
    # each proposal is staged separately so the user can apply them individually.
    # split_proposals[0] = style (display-only), split_proposals[1] = analysis
    split_proposals: tuple[ReportProposal, ...] = ()
    disambiguation: str | None = None  # clarifying question shown when intent is ambiguous

    @property
    def is_refusal(self) -> bool:
        return self.refusal is not None

    @property
    def is_mixed(self) -> bool:
        return len(self.split_proposals) > 1
