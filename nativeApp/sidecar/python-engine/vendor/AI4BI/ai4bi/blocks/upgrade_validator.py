"""
DataBlockContract upgrade validator — Round 020.

Design-council consensus (004-A):

Breaking changes (must bump MAJOR):
  - Remove a metric or rename a column
  - Change grain declaration
  - Narrow a column type (e.g. float → int)
  - Change disaggregation_method on any metric

Non-breaking changes (minor or patch):
  - Add a new metric (non-required)        → minor
  - Add a new column                       → minor
  - Modify description / display_name      → patch

Forbidden changes (is_valid=False, cannot be done in-place):
  - Change block_id itself
  - Modify primary_keys composition
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ai4bi.blocks.contracts import DataBlockContract

BumpKind = Literal["none", "patch", "minor", "major"]

_BUMP_ORDER: dict[BumpKind, int] = {"none": 0, "patch": 1, "minor": 2, "major": 3}


def _max_bump(a: BumpKind, b: BumpKind) -> BumpKind:
    return a if _BUMP_ORDER[a] >= _BUMP_ORDER[b] else b


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class UpgradeResult:
    """Result of validating a DataBlockContract upgrade."""

    is_valid: bool
    required_bump: BumpKind
    breaking: list[str] = field(default_factory=list)
    non_breaking: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_breaking(self) -> bool:
        return bool(self.breaking)

    @property
    def has_forbidden(self) -> bool:
        return bool(self.forbidden)

    def summary(self) -> str:
        if not self.is_valid:
            return f"INVALID: {'; '.join(self.errors)}"
        if self.required_bump == "none":
            return "No changes detected."
        return (
            f"Required bump: {self.required_bump.upper()}. "
            f"Breaking: {len(self.breaking)}, "
            f"Non-breaking: {len(self.non_breaking)}."
        )


# ---------------------------------------------------------------------------
# Type narrowing helpers
# ---------------------------------------------------------------------------

_NUMERIC_TYPES = {"int", "integer", "bigint", "smallint", "tinyint"}
_FLOAT_TYPES = {"float", "double", "decimal", "numeric", "real"}


def _is_narrowing(old_type: str, new_type: str) -> bool:
    """Return True if new_type is a narrower representation than old_type."""
    old = old_type.lower().split("(")[0].strip()
    new = new_type.lower().split("(")[0].strip()
    if old == new:
        return False
    # float → int is narrowing
    if old in _FLOAT_TYPES and new in _NUMERIC_TYPES:
        return True
    # string/varchar → fixed-width is narrowing
    if old in ("string", "text", "varchar") and new in ("char", "nchar"):
        return True
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_upgrade(
    old: DataBlockContract,
    new: DataBlockContract,
) -> UpgradeResult:
    """
    Compare two versions of a DataBlockContract and classify all changes.

    Parameters
    ----------
    old : DataBlockContract
        The currently deployed (or previous) version.
    new : DataBlockContract
        The proposed new version.

    Returns
    -------
    UpgradeResult
        is_valid=False when forbidden changes are present;
        required_bump indicates the minimum semver bump needed.
    """
    breaking: list[str] = []
    non_breaking: list[str] = []
    forbidden: list[str] = []
    errors: list[str] = []
    bump: BumpKind = "none"

    # ------------------------------------------------------------------
    # FORBIDDEN: block_id change
    # ------------------------------------------------------------------
    if old.block_id != new.block_id:
        msg = (
            f"block_id changed from '{old.block_id}' to '{new.block_id}'. "
            "Create a new block with a tombstone on the old one instead."
        )
        forbidden.append(msg)
        errors.append(msg)

    # ------------------------------------------------------------------
    # FORBIDDEN: primary_keys composition change
    # ------------------------------------------------------------------
    old_pks = sorted(old.primary_keys or [])
    new_pks = sorted(new.primary_keys or [])
    if old_pks != new_pks:
        msg = (
            f"primary_keys changed from {old_pks} to {new_pks}. "
            "Primary key composition changes are forbidden in-place."
        )
        forbidden.append(msg)
        errors.append(msg)

    # ------------------------------------------------------------------
    # BREAKING: grain change
    # ------------------------------------------------------------------
    old_grain = (old.grain or "").strip()
    new_grain = (new.grain or "").strip()
    if old_grain != new_grain:
        msg = f"grain changed: '{old_grain[:80]}' → '{new_grain[:80]}'"
        breaking.append(msg)
        bump = _max_bump(bump, "major")

    # ------------------------------------------------------------------
    # COLUMNS: removals (breaking), additions (minor), type narrowing (breaking)
    # ------------------------------------------------------------------
    old_cols = {c.name: c for c in old.columns}
    new_cols = {c.name: c for c in new.columns}

    for col_name in old_cols:
        if col_name not in new_cols:
            msg = f"column '{col_name}' removed"
            breaking.append(msg)
            bump = _max_bump(bump, "major")
        else:
            old_type = old_cols[col_name].data_type
            new_type = new_cols[col_name].data_type
            if _is_narrowing(old_type, new_type):
                msg = f"column '{col_name}' type narrowed: {old_type} → {new_type}"
                breaking.append(msg)
                bump = _max_bump(bump, "major")
            elif old_type.lower() != new_type.lower():
                # Type changed but not narrowing — treat as breaking (safe)
                msg = f"column '{col_name}' type changed: {old_type} → {new_type}"
                breaking.append(msg)
                bump = _max_bump(bump, "major")

    for col_name in new_cols:
        if col_name not in old_cols:
            msg = f"column '{col_name}' added"
            non_breaking.append(msg)
            bump = _max_bump(bump, "minor")

    # ------------------------------------------------------------------
    # METRICS: removals (breaking), additions (minor), disagg change (breaking)
    # ------------------------------------------------------------------
    old_metrics = {m.name: m for m in old.metrics}
    new_metrics = {m.name: m for m in new.metrics}

    for metric_name in old_metrics:
        if metric_name not in new_metrics:
            msg = f"metric '{metric_name}' removed"
            breaking.append(msg)
            bump = _max_bump(bump, "major")
        else:
            old_m = old_metrics[metric_name]
            new_m = new_metrics[metric_name]
            if old_m.disaggregation_method != new_m.disaggregation_method:
                msg = (
                    f"metric '{metric_name}' disaggregation_method changed: "
                    f"{old_m.disaggregation_method} → {new_m.disaggregation_method}"
                )
                breaking.append(msg)
                bump = _max_bump(bump, "major")
            # Formula change is treated as breaking — semantic change
            if old_m.formula != new_m.formula:
                msg = (
                    f"metric '{metric_name}' formula changed: "
                    f"'{old_m.formula}' → '{new_m.formula}'"
                )
                breaking.append(msg)
                bump = _max_bump(bump, "major")

    for metric_name in new_metrics:
        if metric_name not in old_metrics:
            msg = f"metric '{metric_name}' added"
            non_breaking.append(msg)
            bump = _max_bump(bump, "minor")

    # ------------------------------------------------------------------
    # NON-BREAKING: description change
    # ------------------------------------------------------------------
    if (old.description or "").strip() != (new.description or "").strip():
        non_breaking.append("description updated")
        bump = _max_bump(bump, "patch")

    # ------------------------------------------------------------------
    # Final result
    # ------------------------------------------------------------------
    is_valid = len(forbidden) == 0

    # Forbidden changes always require major if we somehow allow them
    if forbidden:
        bump = "major"

    return UpgradeResult(
        is_valid=is_valid,
        required_bump=bump,
        breaking=breaking,
        non_breaking=non_breaking,
        forbidden=forbidden,
        errors=errors,
    )
