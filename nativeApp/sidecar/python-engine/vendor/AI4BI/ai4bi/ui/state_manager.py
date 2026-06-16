"""
state_manager.py — Streamlit session-state manager for ReportSpec.

Design-council decisions (Round 006):

Key layout (all prefixed with _SM_):
    _SM_spec          : ReportSpec           — the live, current spec
    _SM_history       : list[ReportSpec]     — undo stack (oldest first)
    _SM_history_ptr   : int                  — index of _SM_spec in history
                                               == len(history) - 1 when at tip
    _SM_staging       : PatchProposal | None — pending confirmation
    _SM_max_history   : int                  — max undo steps (default 20)

Undo / Redo semantics:
    history  = [s0, s1, s2, s3]   ptr = 3   → current spec is s3
    undo()   → ptr becomes 2, current spec = s2
    redo()   → ptr becomes 3, current spec = s3
    new apply while ptr < tip  → truncate history[ptr+1:], append new spec

A `PatchProposal` with requires_confirmation=True is placed in _SM_staging.
`confirm_staging()` then calls the normal apply path.
`reject_staging()` clears _SM_staging without changing the spec.

Streamlit dependency is imported inside functions so the module can be
imported in non-Streamlit contexts (e.g., pytest with st mocked).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai4bi.spec_models import (
    ApplyResult,
    PatchProposal,
    ReportSpec,
    apply_proposal,
    apply_proposal_strict,
)

if TYPE_CHECKING:
    pass  # avoid circular imports

# ---------------------------------------------------------------------------
# Session-state key constants
# ---------------------------------------------------------------------------

_KEY_SPEC = "_SM_spec"
_KEY_HISTORY = "_SM_history"
_KEY_HISTORY_PTR = "_SM_history_ptr"
_KEY_STAGING = "_SM_staging"
_KEY_MAX_HISTORY = "_SM_max_history"

_DEFAULT_MAX_HISTORY = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _st():
    """Lazy import of streamlit — allows mocking in tests."""
    import streamlit as st  # type: ignore[import]
    return st


def _ss():
    """Return st.session_state."""
    return _st().session_state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_state(
    initial_spec: ReportSpec,
    max_history: int = _DEFAULT_MAX_HISTORY,
) -> None:
    """
    Initialise StateManager keys in st.session_state.

    Safe to call on every Streamlit rerun — existing keys are NOT overwritten
    (rerun-protection guard: ``if key not in st.session_state``).

    Parameters
    ----------
    initial_spec:
        The starting ReportSpec.  Deep-copied before storage so the caller's
        object is never mutated by the manager.
    max_history:
        Maximum number of undo steps to retain (default 20).
    """
    ss = _ss()
    spec_copy = initial_spec.deep_copy()

    if _KEY_MAX_HISTORY not in ss:
        ss[_KEY_MAX_HISTORY] = max_history
    if _KEY_SPEC not in ss:
        ss[_KEY_SPEC] = spec_copy
    if _KEY_HISTORY not in ss:
        ss[_KEY_HISTORY] = [spec_copy.deep_copy()]
    if _KEY_HISTORY_PTR not in ss:
        ss[_KEY_HISTORY_PTR] = 0
    if _KEY_STAGING not in ss:
        ss[_KEY_STAGING] = None


def get_current_spec() -> ReportSpec:
    """Return the live ReportSpec (not a copy — treat as read-only)."""
    return _ss()[_KEY_SPEC]


def can_undo() -> bool:
    """True when there is at least one step to undo."""
    ss = _ss()
    return ss[_KEY_HISTORY_PTR] > 0


def can_redo() -> bool:
    """True when there is at least one step to redo."""
    ss = _ss()
    return ss[_KEY_HISTORY_PTR] < len(ss[_KEY_HISTORY]) - 1


def undo() -> bool:
    """
    Move one step back in history.

    Returns
    -------
    bool
        True if undo was performed; False if the history stack is exhausted.
    """
    if not can_undo():
        return False
    ss = _ss()
    ss[_KEY_HISTORY_PTR] -= 1
    ss[_KEY_SPEC] = ss[_KEY_HISTORY][ss[_KEY_HISTORY_PTR]].deep_copy()
    return True


def redo() -> bool:
    """
    Move one step forward in history.

    Returns
    -------
    bool
        True if redo was performed; False if already at the tip.
    """
    if not can_redo():
        return False
    ss = _ss()
    ss[_KEY_HISTORY_PTR] += 1
    ss[_KEY_SPEC] = ss[_KEY_HISTORY][ss[_KEY_HISTORY_PTR]].deep_copy()
    return True


def apply_proposal_to_state(
    proposal: PatchProposal,
    strict: bool = False,
) -> bool:
    """
    Apply a PatchProposal to the live spec.

    If ``proposal.requires_confirmation`` is True, the proposal is placed in
    staging instead and the spec is NOT updated.  Call ``confirm_staging()``
    to complete the operation.

    Parameters
    ----------
    proposal:
        The proposal to apply.
    strict:
        If True, use atomic (all-or-nothing) apply semantics.

    Returns
    -------
    bool
        True  — spec was updated (or proposal sent to staging).
        False — apply failed (errors in the proposal).
    """
    if proposal.requires_confirmation:
        _ss()[_KEY_STAGING] = proposal
        return True  # "accepted into staging"

    return _do_apply(proposal, strict=strict)


def confirm_staging() -> bool:
    """
    Apply the staged proposal and clear staging.

    Returns
    -------
    bool
        True if the staged proposal was applied successfully.
        False if staging was empty or apply failed.
    """
    ss = _ss()
    staged: PatchProposal | None = ss.get(_KEY_STAGING)
    if staged is None:
        return False

    # Clear staging regardless of outcome
    ss[_KEY_STAGING] = None

    # Apply without requires_confirmation check (we're confirming it now)
    return _do_apply(staged, strict=False)


def reject_staging() -> None:
    """Discard the staged proposal without applying it."""
    _ss()[_KEY_STAGING] = None


def apply_ambiguity_choice(
    proposal: PatchProposal,
    chosen_option: PatchProposal,
) -> bool:
    """
    Resolve an ambiguous proposal by applying the user's chosen alternative.

    The original `proposal` is ignored; `chosen_option` (one of
    `proposal.ambiguity_options`) is applied directly.

    Returns
    -------
    bool
        True if the chosen option was applied successfully.
    """
    return _do_apply(chosen_option, strict=False)


def get_staging() -> PatchProposal | None:
    """Return the proposal currently in staging (or None)."""
    return _ss().get(_KEY_STAGING)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _do_apply(proposal: PatchProposal, *, strict: bool) -> bool:
    """
    Core apply logic: run apply_proposal / apply_proposal_strict,
    commit result into session_state, and push onto the undo stack.

    Returns True on success, False on failure.
    """
    ss = _ss()
    current: ReportSpec = ss[_KEY_SPEC]

    if strict:
        result: ApplyResult = apply_proposal_strict(current, proposal)
    else:
        result = apply_proposal(current, proposal)

    if not result.success:
        return False

    # Commit the new spec
    ss[_KEY_SPEC] = result.spec

    # Truncate redo branch (everything after the current pointer)
    ptr: int = ss[_KEY_HISTORY_PTR]
    history: list[ReportSpec] = ss[_KEY_HISTORY]
    history = history[: ptr + 1]  # drop redo branch

    # Push new state
    history.append(result.spec.deep_copy())

    # Enforce max_history limit (keep the most recent entries)
    max_h: int = ss.get(_KEY_MAX_HISTORY, _DEFAULT_MAX_HISTORY)
    if len(history) > max_h + 1:  # +1 because index 0 is the initial state
        history = history[-(max_h + 1):]

    ss[_KEY_HISTORY] = history
    ss[_KEY_HISTORY_PTR] = len(history) - 1

    return True
