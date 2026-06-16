"""Publication Gate — validate a local draft before formal publication.

Round 012 decision: local drafts are explicitly non-published.  This module
defines the gate checks that must all pass before a draft can transition to a
published report.  Currently no check passes for a standard validated_demo_draft;
the gate is intentionally strict so that the UI can show an honest readiness
summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai4bi.blocks.contracts import DataBlockContract, LifecycleStatus
from ai4bi.report.models import ExecutableReportSpec


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GateCheckResult:
    """Result of a single publication gate check."""

    check_name: str
    passed: bool
    message: str
    blocking: bool  # True = must fix before publish; False = warning only


@dataclass
class PublicationGateResult:
    """Aggregated result of all gate checks."""

    can_publish: bool
    checks: list[GateCheckResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------


def _check_block_lifecycle(
    report: ExecutableReportSpec,
    contracts: dict[str, DataBlockContract],
) -> GateCheckResult:
    """Surface which blocks aren't certified — as a NON-blocking advisory.

    Round 165: for the SMB self-serve product, requiring every block to be
    formally "certified" before a report can be shared was pure friction
    (uploaded files and the bundled demo data are never certified). The check
    still reports the status so the user is informed, but it no longer blocks
    publishing — consistent with how the policy check works (see ``_check_policy``).
    """
    non_certified: list[str] = []
    for page in report.pages.values():
        for visual in page.visuals.values():
            for block_ref in visual.query.block_refs:
                contract = contracts.get(block_ref.block_id)
                if contract is None:
                    non_certified.append(f"{block_ref.block_id} (contract not found)")
                elif contract.block_lifecycle != LifecycleStatus.certified:
                    non_certified.append(
                        f"{block_ref.block_id} (status={contract.block_lifecycle.value})"
                    )

    if non_certified:
        return GateCheckResult(
            check_name="block_lifecycle",
            passed=False,
            message=(
                "提醒：下列資料尚未經過正式認證（仍可分享，請自行確認資料可信）："
                + ", ".join(sorted(set(non_certified)))
            ),
            blocking=False,
        )
    return GateCheckResult(
        check_name="block_lifecycle",
        passed=True,
        message="All referenced blocks are certified.",
        blocking=False,
    )


def _check_version_pin_safety(report: ExecutableReportSpec) -> GateCheckResult:
    """All BlockRefs must have an explicit pinned_version before publication."""
    unpinned: list[str] = []
    for page in report.pages.values():
        for visual in page.visuals.values():
            for block_ref in visual.query.block_refs:
                if block_ref.pinned_version is None:
                    unpinned.append(block_ref.block_id)

    if unpinned:
        return GateCheckResult(
            check_name="version_pin_safety",
            passed=False,
            message=(
                "BlockRefs without a pinned version (must be resolved before publish): "
                + ", ".join(sorted(set(unpinned)))
            ),
            blocking=True,
        )
    return GateCheckResult(
        check_name="version_pin_safety",
        passed=True,
        message="All BlockRefs carry an explicit pinned_version.",
        blocking=True,
    )


def _check_relationship_certified(
    report: ExecutableReportSpec,
    semantic_model: dict,
) -> GateCheckResult:
    """Every block-to-block join used in the report must have a certified relationship in the semantic model."""
    certified_pairs: set[tuple[str, str]] = set()
    for rel in semantic_model.get("relationships", []):
        if rel.get("status") == "certified":
            certified_pairs.add((rel["from_block"], rel["to_block"]))

    uncertified: list[str] = []
    for page in report.pages.values():
        for visual_id, visual in page.visuals.items():
            block_ids = [ref.block_id for ref in visual.query.block_refs]
            if len(block_ids) < 2:
                continue
            # Check each consecutive pair (first block is assumed to be the fact)
            fact = block_ids[0]
            for dim in block_ids[1:]:
                if (fact, dim) not in certified_pairs:
                    uncertified.append(f"{visual_id}: {fact} → {dim}")

    if uncertified:
        return GateCheckResult(
            check_name="relationship_certified",
            passed=False,
            message=(
                "Joins without a certified semantic-model relationship: "
                + "; ".join(uncertified)
            ),
            blocking=True,
        )
    return GateCheckResult(
        check_name="relationship_certified",
        passed=True,
        message="All block joins are backed by certified semantic-model relationships.",
        blocking=True,
    )


def _check_policy(
    report: ExecutableReportSpec,  # noqa: ARG001
    contracts: dict[str, DataBlockContract],  # noqa: ARG001
) -> GateCheckResult:
    """Audience role policy check.

    Round 057 (honesty fix): role-based access control (RBAC) and row-level
    security (RLS) are NOT enforced in this MVP, and read-only share links are
    not password-protected. Previously this returned passed=True ("not yet
    enforced"), which actively asserted a guarantee the system does not provide.
    We now return passed=False (non-blocking) so the gate surfaces the real risk
    instead of hiding it — PLG publishing still works, but the user is warned.
    """
    return GateCheckResult(
        check_name="policy_check",
        passed=False,
        message=(
            "⚠️ 角色權限（RBAC/RLS）尚未啟用：此版本不依使用者角色限制資料存取，"
            "且唯讀分享連結未加密碼保護。請勿用於發布機密或個人資料。"
        ),
        blocking=False,
    )


def _check_audit_metadata(report: ExecutableReportSpec) -> GateCheckResult:
    """Report must declare author, purpose, and valid_period metadata fields."""
    # Verify core AuditMetadata fields are present.
    missing = []
    if not report.audit.report_id:
        missing.append("audit.report_id")
    if report.audit.revision < 0:
        missing.append("audit.revision (must be >= 0)")
    # These extended fields are not yet carried; mark as a warning.
    if not getattr(report, "author", None):
        missing.append("author")
    if not getattr(report, "purpose", None):
        missing.append("purpose")
    if not getattr(report, "valid_period", None):
        missing.append("valid_period")

    if missing:
        return GateCheckResult(
            check_name="audit_metadata",
            passed=False,
            message=(
                "Missing audit metadata fields (add to ExecutableReportSpec): "
                + ", ".join(missing)
            ),
            blocking=False,
        )
    return GateCheckResult(
        check_name="audit_metadata",
        passed=True,
        message="All required audit metadata fields are present.",
        blocking=False,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_publication_gate(
    report: ExecutableReportSpec,
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> PublicationGateResult:
    """Run all publication gate checks and return an aggregated result.

    A report can only be published when every *blocking* check passes.
    Non-blocking checks produce warnings that should be reviewed but do not
    prevent publication.
    """
    checks: list[GateCheckResult] = [
        _check_block_lifecycle(report, contracts),
        _check_version_pin_safety(report),
        _check_relationship_certified(report, semantic_model),
        _check_policy(report, contracts),
        _check_audit_metadata(report),
    ]

    can_publish = all(
        check.passed for check in checks if check.blocking
    )

    return PublicationGateResult(can_publish=can_publish, checks=checks)
