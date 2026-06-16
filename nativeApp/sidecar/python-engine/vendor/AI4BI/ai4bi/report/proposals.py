"""Allowlisted report changes generated from controls or prompt text."""

from __future__ import annotations

from dataclasses import dataclass

from ai4bi.ai import AnalysisPlan, DirectAnswer, NL2ProposalService
from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportChange,
    ReportProposal,
    ReportValidationError,
)


@dataclass(frozen=True)
class ProposalResult:
    proposal: ReportProposal | None
    message: str
    analysis_plan: AnalysisPlan | None = None
    direct_answer: DirectAnswer | None = None  # Round 078: computed NL answer
    result_table: object | None = None  # Round 086: analytics result DataFrame
    trust_notes: tuple[str, ...] = ()
    refusal: str | None = None
    split_proposals: tuple[ReportProposal, ...] = ()
    intent_kind: str = "unknown"    # "style"|"analysis"|"plan"|"answer"|"refused"|"mixed"|"unknown"
    disambiguation: str | None = None  # question to show when LLM confidence is low

    @property
    def is_mixed(self) -> bool:
        return len(self.split_proposals) > 1


def _control_change(
    report: ExecutableReportSpec,
    control_id: str,
    value,
    label: str,
) -> ReportChange | None:
    previous = report.controls[control_id].value
    if previous == value:
        return None
    return ReportChange(f"controls/{control_id}/value", label, previous, value, True)


def controls_to_proposal(
    report: ExecutableReportSpec,
    *,
    steps: list[str],
    products: list[str],
    breakdown: str,
) -> ReportProposal | None:
    changes = [
        change
        for change in [
            _control_change(report, "process_step", steps, "Process step"),
            _control_change(report, "product_family", products, "Product family"),
            _control_change(report, "breakdown", breakdown, "Comparison breakdown"),
        ]
        if change is not None
    ]
    previous_breakdown = report.controls["breakdown"].value
    if breakdown != previous_breakdown:
        before_column = "vendor" if previous_breakdown == "Vendor" else "tool_id"
        before_label = previous_breakdown
        after_column = "vendor" if breakdown == "Vendor" else "tool_id"
        changes.extend(
            [
                ReportChange(
                    "pages/main/visuals/bar_queue_by_tool_dimension/query/dimensions",
                    "Bar breakdown query",
                    [{"block_id": "tool_dim", "column_name": before_column, "alias": before_label, "truncate_date_to": None}],
                    [{"block_id": "tool_dim", "column_name": after_column, "alias": breakdown, "truncate_date_to": None}],
                    True,
                ),
                ReportChange(
                    "pages/main/visuals/bar_queue_by_tool_dimension/visualization/title",
                    "Bar title",
                    f"Queue Time by {before_label}",
                    f"Queue Time by {breakdown}",
                    False,
                ),
            ]
        )
    if not changes:
        return None
    return ReportProposal("Manual report control update", changes)


def build_resize_visual_proposal(
    page_id: str,
    visual_id: str,
    new_col_span: int,
    current_col_span: int,
) -> ReportProposal:
    """Create a proposal that changes a visual's col_span (grid width). Round 030."""
    _VALID_SPANS = {3, 4, 6, 12}
    if new_col_span not in _VALID_SPANS:
        raise ReportValidationError(
            f"col_span must be one of {sorted(_VALID_SPANS)}, got {new_col_span}."
        )
    _LABEL = {12: "100%", 6: "50%", 4: "33%", 3: "25%"}
    change = ReportChange(
        path=f"pages/{page_id}/visuals/{visual_id}/col_span",
        label=f"Visual width → {_LABEL.get(new_col_span, str(new_col_span))}",
        before=current_col_span,
        after=new_col_span,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Resize '{visual_id}' to {_LABEL.get(new_col_span, str(new_col_span))}",
        changes=[change],
        target_component_id=visual_id,
    )


def build_title_proposal(
    current_title: str,
    new_title: str,
) -> ReportProposal:
    """Creates a proposal to rename the report title. affects_data=False."""
    change = ReportChange(
        path="title",
        label="Report title",
        before=current_title,
        after=new_title,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Rename report title to '{new_title}'",
        changes=[change],
    )


def pin_block_version_proposal(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
    block_id: str,
    certified_version: str,
    pin_reason: str = "manually pinned by user",
) -> ReportProposal:
    """
    Creates a proposal that pins the BlockRef for block_id in the given visual
    to certified_version.
    """
    page = report.pages.get(page_id)
    if page is None:
        raise ReportValidationError(f"Page '{page_id}' not found in report.")
    visual = page.visuals.get(visual_id)
    if visual is None:
        raise ReportValidationError(f"Visual '{visual_id}' not found on page '{page_id}'.")
    matching = [ref for ref in visual.query.block_refs if ref.block_id == block_id]
    if not matching:
        raise ReportValidationError(
            f"BlockRef '{block_id}' not found in visual '{visual_id}' on page '{page_id}'."
        )
    current_version = matching[0].pinned_version
    path = f"pages/{page_id}/visuals/{visual_id}/query/block_refs/{block_id}/pinned_version"
    change = ReportChange(
        path=path,
        label=f"Pin {block_id} to version {certified_version}",
        before=current_version,
        after=certified_version,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Pin block '{block_id}' to version {certified_version} ({pin_reason})",
        changes=[change],
    )


def unpin_block_version_proposal(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
    block_id: str,
) -> ReportProposal:
    """Creates a proposal that clears pinned_version and pin_reason for block_id in the given visual."""
    page = report.pages.get(page_id)
    if page is None:
        raise ReportValidationError(f"Page '{page_id}' not found in report.")
    visual = page.visuals.get(visual_id)
    if visual is None:
        raise ReportValidationError(f"Visual '{visual_id}' not found on page '{page_id}'.")
    matching = [ref for ref in visual.query.block_refs if ref.block_id == block_id]
    if not matching:
        raise ReportValidationError(
            f"BlockRef '{block_id}' not found in visual '{visual_id}' on page '{page_id}'."
        )
    current_version = matching[0].pinned_version
    path = f"pages/{page_id}/visuals/{visual_id}/query/block_refs/{block_id}/pinned_version"
    change = ReportChange(
        path=path,
        label=f"Unpin {block_id}",
        before=current_version,
        after=None,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Unpin block '{block_id}' (restore to latest certified)",
        changes=[change],
    )


def build_page_rename_proposal(
    page_id: str,
    current_name: str,
    new_name: str,
) -> ReportProposal:
    """Renames a page's display_name. affects_data=False."""
    change = ReportChange(
        path=f"pages/{page_id}/display_name",
        label=f"Rename page '{page_id}' display name",
        before=current_name,
        after=new_name,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Rename page '{page_id}' to '{new_name}'",
        changes=[change],
    )


def build_page_delete_proposal(
    report: ExecutableReportSpec,
    page_id: str,
) -> ReportProposal:
    """Deletes a page. The before value is the complete page dict for stale checks."""
    page = report.pages.get(page_id)
    if page is None:
        raise ReportValidationError(f"Page '{page_id}' not found in report.")
    change = ReportChange(
        path=f"pages/{page_id}/delete",
        label=f"Delete page '{page_id}'",
        before=page.to_dict(),
        after=None,
        affects_data=True,
    )
    return ReportProposal(
        description=f"Delete page '{page_id}'",
        changes=[change],
    )


def build_delete_visual_proposal(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
) -> ReportProposal:
    """Round 158: delete a single visual from a page. ``before`` carries the
    visual dict so the change is reviewable/undoable."""
    page = report.pages.get(page_id)
    if page is None or visual_id not in page.visuals:
        raise ReportValidationError(
            f"Visual '{visual_id}' not found on page '{page_id}'."
        )
    title = page.visuals[visual_id].visualization.title or visual_id
    change = ReportChange(
        path=f"pages/{page_id}/visuals/{visual_id}/delete",
        label=f"刪除圖表「{title}」",
        before=page.visuals[visual_id].to_dict(),
        after=None,
        affects_data=True,
    )
    return ReportProposal(
        description=f"刪除圖表「{title}」",
        changes=[change],
        target_component_id=visual_id,
    )


def prompt_to_proposal(
    prompt: str,
    report: ExecutableReportSpec,
    selected_component_id: str,
    semantic_model: "dict | None" = None,
    contracts: "dict | None" = None,
    executor: "object | None" = None,
    conversation_state: "dict | None" = None,
) -> ProposalResult:
    """Convert a natural-language prompt to a reviewable proposal or plan.

    The AI service owns governed style/analysis/refusal behavior. This wrapper
    preserves the older demo control intents while returning richer plan/trust
    metadata to the Streamlit surface. When ``executor`` is supplied, metric
    *questions* are answered directly (Round 078) instead of producing edits.
    ``conversation_state`` is a caller-owned dict (per session) that lets a
    follow-up like "只看 ETCH" inherit the prior turn's scope (Round 136).
    """
    normalized = prompt.strip().upper()
    if not normalized:
        return ProposalResult(None, "Enter a report change to create a proposal.")

    ai_result = NL2ProposalService().propose(
        prompt, report, selected_component_id,
        semantic_model=semantic_model, contracts=contracts, executor=executor,
        conversation_state=conversation_state,
    )
    if ai_result.refusal is not None:
        return ProposalResult(
            None,
            ai_result.message,
            trust_notes=tuple(ai_result.trust_notes),
            refusal=ai_result.refusal.reason,
            intent_kind="refused",
        )
    # Mixed prompt: return split_proposals so UI can stage them individually
    if ai_result.is_mixed:
        return ProposalResult(
            None,
            ai_result.message,
            trust_notes=tuple(ai_result.trust_notes),
            split_proposals=ai_result.split_proposals,
            intent_kind="mixed",
        )
    # Round 086: analytics-engine result (churn/decline/basket) — a table answer.
    if getattr(ai_result, "result_table", None) is not None:
        return ProposalResult(
            None,
            ai_result.message,
            result_table=ai_result.result_table,
            trust_notes=tuple(ai_result.trust_notes),
            intent_kind="answer",
        )
    # Round 078: direct computed answer to a metric question. Carries the
    # optional "add as KPI" proposal so the user can pin the answer in one click.
    if ai_result.direct_answer is not None:
        return ProposalResult(
            ai_result.proposal,
            ai_result.message,
            direct_answer=ai_result.direct_answer,
            trust_notes=tuple(ai_result.trust_notes),
            intent_kind="answer",
        )
    if ai_result.analysis_plan is not None:
        return ProposalResult(
            ai_result.proposal,
            ai_result.message,
            analysis_plan=ai_result.analysis_plan,
            trust_notes=tuple(ai_result.trust_notes),
            intent_kind="plan",
        )
    if ai_result.proposal is not None:
        kind = ai_result.intent.intent_kind if ai_result.intent else "unknown"
        return ProposalResult(
            ai_result.proposal,
            ai_result.message,
            trust_notes=tuple(ai_result.trust_notes),
            intent_kind="style" if kind == "style_change" else "analysis",
        )

    changes: list[ReportChange] = []
    steps = [step for step in ("PHOTO", "ETCH", "CVD") if step in normalized]
    if steps:
        change = _control_change(report, "process_step", steps, "Process step")
        if change:
            changes.append(change)
    products = [family for family in ("Logic-A", "Logic-B") if family.upper() in normalized]
    if products:
        change = _control_change(report, "product_family", products, "Product family")
        if change:
            changes.append(change)
    if "VENDOR" in normalized:
        breakdown_proposal = controls_to_proposal(
            report,
            steps=report.controls["process_step"].value,
            products=report.controls["product_family"].value,
            breakdown="Vendor",
        )
        if breakdown_proposal:
            changes.extend(breakdown_proposal.changes)
    if "RESET" in normalized:
        reset = controls_to_proposal(
            report,
            steps=["ETCH"],
            products=["Logic-A", "Logic-B"],
            breakdown="Tool ID",
        )
        changes = reset.changes if reset else []
        current_color = report.pages["main"].visuals["line_queue_by_day"].visualization.extra.get("line_color")
        if current_color is not None:
            changes.append(
                ReportChange(
                    "pages/main/visuals/line_queue_by_day/visualization/extra/line_color",
                    "Trend line color",
                    current_color,
                    None,
                    False,
                )
            )
    if not changes:
        return ProposalResult(
            None,
            ai_result.message or "No supported report change was detected.",
            trust_notes=tuple(ai_result.trust_notes),
            intent_kind="unknown",
            disambiguation=getattr(ai_result, "disambiguation", None),
        )
    return ProposalResult(
        ReportProposal("Prompt proposal", changes, selected_component_id),
        "Proposal created. Review the diff before applying it.",
    )
