"""Session workspace for executable report drafts and staged proposals."""

from __future__ import annotations

from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportProposal,
    ReportValidationError,
    apply_report_proposal,
)

_KEY_REPORT = "report_spec"
_KEY_HISTORY = "_report_history"
_KEY_PTR = "_report_history_ptr"
_KEY_PENDING = "pending_patch"
_KEY_MESSAGE = "user_message"


def _ss():
    import streamlit as st
    return st.session_state


def init_report(report: ExecutableReportSpec) -> None:
    state = _ss()
    if _KEY_REPORT not in state:
        initial = report.deep_copy()
        state[_KEY_REPORT] = initial
        state[_KEY_HISTORY] = [initial.deep_copy()]
        state[_KEY_PTR] = 0
        state[_KEY_PENDING] = None
        state[_KEY_MESSAGE] = "Validated demo draft loaded."


def current_report() -> ExecutableReportSpec:
    return _ss()[_KEY_REPORT]


def message() -> str:
    return _ss().get(_KEY_MESSAGE, "")


def set_message(text: str) -> None:
    _ss()[_KEY_MESSAGE] = text


def pending_proposal() -> ReportProposal | None:
    return _ss().get(_KEY_PENDING)


def stage_proposal(proposal: ReportProposal) -> None:
    _ss()[_KEY_PENDING] = proposal
    set_message("Proposal is awaiting review; the active report is unchanged.")


def cancel_pending() -> None:
    _ss()[_KEY_PENDING] = None
    set_message("Proposal cancelled; the active report is unchanged.")


def _commit(report: ExecutableReportSpec) -> None:
    state = _ss()
    history = state[_KEY_HISTORY][: state[_KEY_PTR] + 1]
    history.append(report.deep_copy())
    state[_KEY_HISTORY] = history[-21:]
    state[_KEY_PTR] = len(state[_KEY_HISTORY]) - 1
    state[_KEY_REPORT] = report


def apply_immediately(proposal: ReportProposal) -> bool:
    try:
        updated = apply_report_proposal(current_report(), proposal)
    except ReportValidationError as exc:
        set_message(f"Change rejected: {exc}")
        return False
    _commit(updated)
    set_message(f"Applied: {proposal.description}.")
    return True


def accept_pending() -> bool:
    proposal = pending_proposal()
    if proposal is None:
        return False
    if not apply_immediately(proposal):
        return False
    _ss()[_KEY_PENDING] = None
    return True


def can_undo() -> bool:
    return _ss()[_KEY_PTR] > 0


def can_redo() -> bool:
    state = _ss()
    return state[_KEY_PTR] < len(state[_KEY_HISTORY]) - 1


def undo() -> bool:
    if not can_undo():
        return False
    state = _ss()
    state[_KEY_PTR] -= 1
    state[_KEY_REPORT] = state[_KEY_HISTORY][state[_KEY_PTR]].deep_copy()
    state[_KEY_PENDING] = None
    set_message("Undid the last report change.")
    return True


def redo() -> bool:
    if not can_redo():
        return False
    state = _ss()
    state[_KEY_PTR] += 1
    state[_KEY_REPORT] = state[_KEY_HISTORY][state[_KEY_PTR]].deep_copy()
    state[_KEY_PENDING] = None
    set_message("Redid the report change.")
    return True


def replace_with_loaded(report: ExecutableReportSpec) -> None:
    loaded = report.deep_copy()
    state = _ss()
    state[_KEY_REPORT] = loaded
    state[_KEY_HISTORY] = [loaded.deep_copy()]
    state[_KEY_PTR] = 0
    state[_KEY_PENDING] = None
    set_message(f"Loaded local draft '{loaded.title}'.")
