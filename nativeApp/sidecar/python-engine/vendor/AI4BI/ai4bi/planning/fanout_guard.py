"""
FanoutGuard — static analysis of RelationshipHint fanout risk.

Rules (design-council consensus):
  BLOCKED → raise FanoutGuardError immediately (query must not proceed)
  HIGH    → log a FanoutWarning (query proceeds with caution)
  MEDIUM  → log an informational warning (no error)
  LOW     → silent pass
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Sequence

from ai4bi.blocks.contracts import FanoutRisk, RelationshipHint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions / warnings
# ---------------------------------------------------------------------------

class FanoutGuardError(RuntimeError):
    """
    Raised when a BLOCKED fanout risk is detected.

    Attributes
    ----------
    relationship : RelationshipHint
        The relationship that triggered the error.
    """

    def __init__(self, relationship: RelationshipHint) -> None:
        self.relationship = relationship
        super().__init__(
            f"[FanoutGuard] Join to '{relationship.target_block_id}' is BLOCKED. "
            f"Fanout risk is BLOCKED — this join is not permitted. "
            f"Allowed join keys: {relationship.allowed_join_keys}"
        )


class FanoutWarning(UserWarning):
    """
    Issued (via warnings.warn) when a HIGH fanout risk is detected.

    The query is still allowed to proceed, but callers should surface this
    warning to the end-user.
    """


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class FanoutCheckResult:
    """Summary returned by FanoutGuard.check() on a clean pass."""

    high_risk_relationships: list[RelationshipHint] = field(default_factory=list)
    medium_risk_relationships: list[RelationshipHint] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.high_risk_relationships or self.medium_risk_relationships)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

class FanoutGuard:
    """
    Static fanout-risk analyser for a list of RelationshipHints.

    Usage
    -----
    ::

        result = FanoutGuard.check(block.relationships)
        # If no FanoutGuardError is raised, the join plan is safe to execute.
        if result.has_warnings:
            print("Proceed with caution:", result.high_risk_relationships)
    """

    @staticmethod
    def check(relationships: Sequence[RelationshipHint]) -> FanoutCheckResult:
        """
        Analyse every relationship for fanout risk.

        Parameters
        ----------
        relationships:
            The ``DataBlockContract.relationships`` list to inspect.

        Returns
        -------
        FanoutCheckResult
            Contains lists of HIGH and MEDIUM risk relationships that were
            encountered (after issuing warnings for them).

        Raises
        ------
        FanoutGuardError
            On the *first* relationship whose ``fanout_risk`` is BLOCKED.
        """
        result = FanoutCheckResult()

        for rel in relationships:
            risk = rel.fanout_risk

            if risk is FanoutRisk.BLOCKED:
                logger.error(
                    "[FanoutGuard] BLOCKED join detected → target=%s keys=%s",
                    rel.target_block_id,
                    rel.allowed_join_keys,
                )
                raise FanoutGuardError(rel)

            elif risk is FanoutRisk.HIGH:
                msg = (
                    f"[FanoutGuard] HIGH fanout risk on join to '{rel.target_block_id}' "
                    f"via keys {rel.allowed_join_keys}. "
                    "Results may include unexpected row multiplication. Proceed with caution."
                )
                logger.warning(msg)
                warnings.warn(msg, FanoutWarning, stacklevel=2)
                result.high_risk_relationships.append(rel)

            elif risk is FanoutRisk.MEDIUM:
                msg = (
                    f"[FanoutGuard] MEDIUM fanout risk on join to '{rel.target_block_id}' "
                    f"via keys {rel.allowed_join_keys}."
                )
                logger.info(msg)
                result.medium_risk_relationships.append(rel)

            # LOW → silent pass

        return result
