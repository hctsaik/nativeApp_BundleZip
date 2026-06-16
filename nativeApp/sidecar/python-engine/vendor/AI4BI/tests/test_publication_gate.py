"""Tests for the Publication Gate — ai4bi/report/publication.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4bi.blocks.contracts import DataBlockContract, LifecycleStatus
from ai4bi.report.models import ExecutableReportSpec
from ai4bi.report.publication import (
    GateCheckResult,
    PublicationGateResult,
    run_publication_gate,
)
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DATA_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_SEMANTIC_MODEL_PATH = _DATA_ROOT / "semantic_model.json"
_BLOCKS_DIR = _DATA_ROOT / "blocks"


def _load_semantic_model() -> dict:
    return json.loads(_SEMANTIC_MODEL_PATH.read_text(encoding="utf-8"))


def _load_contracts() -> dict[str, DataBlockContract]:
    from ai4bi.blocks.loader import BlockLoader
    loader = BlockLoader()
    contracts: dict[str, DataBlockContract] = {}
    if _BLOCKS_DIR.exists():
        for path in _BLOCKS_DIR.glob("*.json"):
            try:
                c = loader.load_json(str(path))
                contracts[c.block_id] = c
            except Exception:  # noqa: BLE001
                pass
    return contracts


@pytest.fixture()
def demo_report() -> ExecutableReportSpec:
    return build_semiconductor_queue_time_report()


@pytest.fixture()
def semantic_model() -> dict:
    return _load_semantic_model()


@pytest.fixture()
def contracts() -> dict[str, DataBlockContract]:
    return _load_contracts()


# ---------------------------------------------------------------------------
# Test 1: PublicationGateResult dataclass structure
# ---------------------------------------------------------------------------

def test_gate_result_dataclass_fields():
    """PublicationGateResult must expose can_publish and checks fields."""
    result = PublicationGateResult(can_publish=False, checks=[])
    assert result.can_publish is False
    assert result.checks == []


# ---------------------------------------------------------------------------
# Test 2: GateCheckResult dataclass structure
# ---------------------------------------------------------------------------

def test_gate_check_result_dataclass_fields():
    """GateCheckResult must expose check_name, passed, message, blocking."""
    check = GateCheckResult(
        check_name="block_lifecycle",
        passed=False,
        message="Not certified.",
        blocking=True,
    )
    assert check.check_name == "block_lifecycle"
    assert check.passed is False
    assert check.blocking is True
    assert "certified" in check.message.lower()


# ---------------------------------------------------------------------------
# Test 3: run_publication_gate returns all 5 expected check names
# ---------------------------------------------------------------------------

def test_gate_returns_all_five_checks(demo_report, contracts, semantic_model):
    """run_publication_gate must return exactly 5 checks with the expected names."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    check_names = {c.check_name for c in result.checks}
    assert check_names == {
        "block_lifecycle",
        "version_pin_safety",
        "relationship_certified",
        "policy_check",
        "audit_metadata",
    }


# ---------------------------------------------------------------------------
# Test 4: Demo report (validated, not certified) fails block_lifecycle check
# ---------------------------------------------------------------------------

def test_block_lifecycle_fails_for_validated_blocks(demo_report, contracts, semantic_model):
    """Round 165: uncertified blocks are reported (passed=False) but NON-blocking
    so SMB self-serve sharing isn't gated on formal certification."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    lifecycle_check = next(c for c in result.checks if c.check_name == "block_lifecycle")
    # Contracts are validated, not certified → still surfaced as not-passed…
    assert lifecycle_check.passed is False
    # …but advisory only (no longer blocks publication).
    assert lifecycle_check.blocking is False


# ---------------------------------------------------------------------------
# Test 5: can_publish is False when any blocking check fails
# ---------------------------------------------------------------------------

def test_can_publish_false_when_blocking_check_fails(demo_report, contracts, semantic_model):
    """A report with non-certified blocks must not be publishable."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    assert result.can_publish is False


# ---------------------------------------------------------------------------
# Test 6: version_pin_safety fails for BlockRefs with pinned_version=None
# ---------------------------------------------------------------------------

def test_version_pin_safety_fails_for_unpinned_block_refs(demo_report, contracts, semantic_model):
    """Demo report has unpinned BlockRefs; version_pin_safety must pass=False, blocking=True."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    pin_check = next(c for c in result.checks if c.check_name == "version_pin_safety")
    # All demo BlockRefs are unpinned (pinned_version=None)
    assert pin_check.blocking is True
    assert pin_check.passed is False
    assert "pinned" in pin_check.message.lower() or "pin" in pin_check.message.lower()


# ---------------------------------------------------------------------------
# Test 7: relationship_certified passes for demo report (all certified in semantic model)
# ---------------------------------------------------------------------------

def test_relationship_certified_passes_for_demo_report(demo_report, contracts, semantic_model):
    """All demo visuals use certified join paths; relationship_certified must pass."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    rel_check = next(c for c in result.checks if c.check_name == "relationship_certified")
    assert rel_check.passed is True


# ---------------------------------------------------------------------------
# Test 8: policy_check is non-blocking and honestly reports "not enforced"
# ---------------------------------------------------------------------------

def test_policy_check_is_non_blocking_and_not_enforced(demo_report, contracts, semantic_model):
    """Round 057 honesty fix: RBAC/RLS is NOT enforced, so the check must NOT
    assert passed=True. It reports passed=False (a warning) but stays
    non-blocking so PLG publishing still works."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    policy_check = next(c for c in result.checks if c.check_name == "policy_check")
    assert policy_check.passed is False
    assert policy_check.blocking is False
    # must not silently claim enforcement
    assert "RBAC" in policy_check.message or "尚未啟用" in policy_check.message


# ---------------------------------------------------------------------------
# Test 9: audit_metadata is non-blocking and fails (fields missing from model)
# ---------------------------------------------------------------------------

def test_audit_metadata_fails_but_nonblocking(demo_report, contracts, semantic_model):
    """ExecutableReportSpec lacks author/purpose/valid_period; audit_metadata must fail non-blocking."""
    result = run_publication_gate(demo_report, contracts, semantic_model)
    meta_check = next(c for c in result.checks if c.check_name == "audit_metadata")
    assert meta_check.passed is False
    assert meta_check.blocking is False


# ---------------------------------------------------------------------------
# Test 10: Gate passes when all contracts are certified and all refs are pinned
# ---------------------------------------------------------------------------

def test_can_publish_true_when_all_blocking_checks_pass(demo_report, semantic_model):
    """Simulate certified contracts + pinned refs → can_publish should be True."""
    from dataclasses import replace as dc_replace
    from datetime import datetime

    from ai4bi.blocks.contracts import DataBlockContract, LifecycleStatus, InlineDataSource
    from ai4bi.query_spec import BlockRef

    # Build synthetic certified contracts for every block_id referenced in the report
    all_block_ids: set[str] = set()
    for page in demo_report.pages.values():
        for visual in page.visuals.values():
            for ref in visual.query.block_refs:
                all_block_ids.add(ref.block_id)

    certified_contracts: dict[str, DataBlockContract] = {
        bid: DataBlockContract(
            block_id=bid,
            block_type="dimension",
            grain=f"one row per {bid}",
            version="1.0.0",
            block_lifecycle=LifecycleStatus.certified,
        )
        for bid in all_block_ids
    }

    # Build a patched report where every BlockRef has a pinned_version
    pinned_at = datetime(2026, 1, 1)
    report_dict = demo_report.to_dict()
    for page in report_dict["pages"].values():
        for visual in page["visuals"].values():
            for ref in visual["query"]["block_refs"]:
                ref["pinned_version"] = "1.0.0"
                ref["pin_reason"] = "test"
                ref["pinned_at"] = pinned_at.isoformat()

    pinned_report = ExecutableReportSpec.from_dict(report_dict)

    result = run_publication_gate(pinned_report, certified_contracts, semantic_model)
    # All blocking checks (lifecycle, pin, relationship) should now pass
    blocking_failed = [c for c in result.checks if c.blocking and not c.passed]
    assert blocking_failed == [], f"Unexpected blocking failures: {blocking_failed}"
    assert result.can_publish is True
