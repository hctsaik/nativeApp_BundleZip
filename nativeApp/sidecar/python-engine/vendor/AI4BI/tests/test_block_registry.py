"""
tests/test_block_registry.py

10+ tests for FilesystemBlockRegistry covering all Round 009/014 requirements.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from ai4bi.blocks.contracts import (
    DataBlockContract,
    BlockType,
    LifecycleStatus,
    InlineDataSource,
)
from ai4bi.blocks.registry import (
    FilesystemBlockRegistry,
    VersionLifecycle,
    VersionRecord,
    CertifiedLatestPointer,
    RegistrySnapshot,
    BlockNotFoundError,
    BlockVersionNotFoundError,
    NoCertifiedVersionError,
    BlockRegistryProtocol,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry(tmp_path: Path) -> FilesystemBlockRegistry:
    return FilesystemBlockRegistry(tmp_path / "registry")


def _make_contract(block_id: str = "test_block", version: str = "1.0.0") -> DataBlockContract:
    return DataBlockContract(
        block_id=block_id,
        block_type=BlockType.fact,
        grain="one row per event",
        version=version,
        description="Test block",
        block_lifecycle=LifecycleStatus.draft,
        data_source=InlineDataSource(records=[{"id": 1, "value": 42}]),
    )


# ---------------------------------------------------------------------------
# Test 1: register → lifecycle is draft
# ---------------------------------------------------------------------------

def test_register_lifecycle_is_draft(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    vr = registry.register(contract, "1.0.0")

    assert isinstance(vr, VersionRecord)
    assert vr.lifecycle == VersionLifecycle.draft
    assert vr.block_id == "test_block"
    assert vr.version == "1.0.0"
    assert vr.certified_at is None
    assert vr.certified_by is None


# ---------------------------------------------------------------------------
# Test 2: certify → lifecycle is certified, certified_latest updated
# ---------------------------------------------------------------------------

def test_certify_updates_lifecycle_and_pointer(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    registry.register(contract, "1.0.0")
    pointer = registry.certify("test_block", "1.0.0", "qa_engineer")

    assert isinstance(pointer, CertifiedLatestPointer)
    assert pointer.certified_latest == "1.0.0"
    assert pointer.updated_by == "qa_engineer"

    # Confirm meta on disk reflects certified status
    versions = registry.list_versions("test_block")
    assert len(versions) == 1
    assert versions[0].lifecycle == VersionLifecycle.certified
    assert versions[0].certified_by == "qa_engineer"
    assert versions[0].certified_at is not None


# ---------------------------------------------------------------------------
# Test 3: resolve(pinned_version=None) → returns certified contract
# ---------------------------------------------------------------------------

def test_resolve_no_pin_returns_certified_contract(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    registry.register(contract, "1.0.0")
    registry.certify("test_block", "1.0.0", "AUTO_CERTIFY")

    resolved = registry.resolve("test_block")
    assert isinstance(resolved, DataBlockContract)
    assert resolved.block_id == "test_block"
    assert resolved.version == "1.0.0"


# ---------------------------------------------------------------------------
# Test 4: resolve(pinned_version="1.0.0") → correct version returned
# ---------------------------------------------------------------------------

def test_resolve_with_pinned_version(registry: FilesystemBlockRegistry) -> None:
    c1 = _make_contract(version="1.0.0")
    c2 = _make_contract(version="2.0.0")
    registry.register(c1, "1.0.0")
    registry.register(c2, "2.0.0")
    registry.certify("test_block", "2.0.0", "AUTO_CERTIFY")

    # Even though certified_latest is 2.0.0, pinning to 1.0.0 must return 1.0.0
    resolved = registry.resolve("test_block", pinned_version="1.0.0")
    assert resolved.version == "1.0.0"


# ---------------------------------------------------------------------------
# Test 5: resolve(pinned_version="9.9.9") → BlockVersionNotFoundError
# ---------------------------------------------------------------------------

def test_resolve_missing_pinned_version_raises(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    registry.register(contract, "1.0.0")
    registry.certify("test_block", "1.0.0", "AUTO_CERTIFY")

    with pytest.raises(BlockVersionNotFoundError):
        registry.resolve("test_block", pinned_version="9.9.9")


# ---------------------------------------------------------------------------
# Test 6: get_certified_latest → correct version string
# ---------------------------------------------------------------------------

def test_get_certified_latest(registry: FilesystemBlockRegistry) -> None:
    c1 = _make_contract(version="1.0.0")
    c2 = _make_contract(version="1.1.0")
    registry.register(c1, "1.0.0")
    registry.register(c2, "1.1.0")
    registry.certify("test_block", "1.0.0", "AUTO_CERTIFY")
    registry.certify("test_block", "1.1.0", "AUTO_CERTIFY")

    assert registry.get_certified_latest("test_block") == "1.1.0"


# ---------------------------------------------------------------------------
# Test 7: take_snapshot → RegistrySnapshot contains all requested blocks
# ---------------------------------------------------------------------------

def test_take_snapshot_includes_all_blocks(registry: FilesystemBlockRegistry) -> None:
    for bid in ["alpha", "beta", "gamma"]:
        c = _make_contract(block_id=bid)
        registry.register(c, "1.0.0")
        registry.certify(bid, "1.0.0", "AUTO_CERTIFY")

    snapshot = registry.take_snapshot(
        block_ids=["alpha", "beta", "gamma"],
        snapshot_id="snap-001",
        taken_by="ci_pipeline",
    )

    assert isinstance(snapshot, RegistrySnapshot)
    assert snapshot.snapshot_id == "snap-001"
    assert snapshot.taken_by == "ci_pipeline"
    assert set(snapshot.pinned_versions.keys()) == {"alpha", "beta", "gamma"}
    assert all(v == "1.0.0" for v in snapshot.pinned_versions.values())


# ---------------------------------------------------------------------------
# Test 8: certify is idempotent — second certify for same version does not error
# ---------------------------------------------------------------------------

def test_certify_idempotent(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    registry.register(contract, "1.0.0")
    p1 = registry.certify("test_block", "1.0.0", "AUTO_CERTIFY")
    p2 = registry.certify("test_block", "1.0.0", "AUTO_CERTIFY")  # must not raise

    assert p1.certified_latest == p2.certified_latest == "1.0.0"
    # _meta.json should still have exactly one version entry
    versions = registry.list_versions("test_block")
    assert len(versions) == 1


# ---------------------------------------------------------------------------
# Test 9: deprecate → lifecycle becomes deprecated
# ---------------------------------------------------------------------------

def test_deprecate_changes_lifecycle(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    registry.register(contract, "1.0.0")
    registry.certify("test_block", "1.0.0", "AUTO_CERTIFY")

    vr = registry.deprecate("test_block", "1.0.0", "data_steward", notes="superseded by 2.0.0")

    assert vr.lifecycle == VersionLifecycle.deprecated
    assert "superseded" in (vr.notes or "")

    versions = registry.list_versions("test_block")
    assert versions[0].lifecycle == VersionLifecycle.deprecated


# ---------------------------------------------------------------------------
# Test 10: list_versions with lifecycle_filter
# ---------------------------------------------------------------------------

def test_list_versions_lifecycle_filter(registry: FilesystemBlockRegistry) -> None:
    c1 = _make_contract(version="1.0.0")
    c2 = _make_contract(version="2.0.0")
    c3 = _make_contract(version="3.0.0")

    registry.register(c1, "1.0.0")
    registry.register(c2, "2.0.0")
    registry.register(c3, "3.0.0")

    # Certify 2.0.0 and deprecate 1.0.0; leave 3.0.0 as draft
    registry.certify("test_block", "2.0.0", "AUTO_CERTIFY")
    registry.deprecate("test_block", "1.0.0", "steward")

    drafts = registry.list_versions("test_block", lifecycle_filter=VersionLifecycle.draft)
    certified = registry.list_versions("test_block", lifecycle_filter=VersionLifecycle.certified)
    deprecated = registry.list_versions("test_block", lifecycle_filter=VersionLifecycle.deprecated)

    assert len(drafts) == 1 and drafts[0].version == "3.0.0"
    assert len(certified) == 1 and certified[0].version == "2.0.0"
    assert len(deprecated) == 1 and deprecated[0].version == "1.0.0"


# ---------------------------------------------------------------------------
# Test 11: BlockRegistryProtocol structural subtyping check
# ---------------------------------------------------------------------------

def test_filesystem_registry_satisfies_protocol(registry: FilesystemBlockRegistry) -> None:
    assert isinstance(registry, BlockRegistryProtocol)


# ---------------------------------------------------------------------------
# Test 12: resolve via version_snapshot (overrides certified_latest)
# ---------------------------------------------------------------------------

def test_resolve_via_version_snapshot(registry: FilesystemBlockRegistry) -> None:
    c1 = _make_contract(version="1.0.0")
    c2 = _make_contract(version="2.0.0")
    registry.register(c1, "1.0.0")
    registry.register(c2, "2.0.0")
    registry.certify("test_block", "2.0.0", "AUTO_CERTIFY")  # certified_latest = 2.0.0

    # Snapshot pins to 1.0.0 — should override certified_latest
    resolved = registry.resolve(
        "test_block",
        version_snapshot={"test_block": "1.0.0"},
    )
    assert resolved.version == "1.0.0"


# ---------------------------------------------------------------------------
# Test 13: resolve without certified version raises NoCertifiedVersionError
# ---------------------------------------------------------------------------

def test_resolve_no_certified_version_raises(registry: FilesystemBlockRegistry) -> None:
    contract = _make_contract()
    registry.register(contract, "1.0.0")  # draft — not certified

    with pytest.raises(NoCertifiedVersionError):
        registry.resolve("test_block")


# ---------------------------------------------------------------------------
# Test 14: resolve on unknown block raises BlockNotFoundError
# ---------------------------------------------------------------------------

def test_resolve_unknown_block_raises(registry: FilesystemBlockRegistry) -> None:
    with pytest.raises(BlockNotFoundError):
        registry.resolve("nonexistent_block")


# ---------------------------------------------------------------------------
# Test 15: semiconductor demo registry _meta.json integrity
# ---------------------------------------------------------------------------

def test_semiconductor_demo_registry_integrity() -> None:
    """Each block in the demo registry should have certified_latest == '1.0.0'."""
    registry_root = (
        Path(__file__).parent.parent
        / "data"
        / "semiconductor_demo"
        / "registry"
    )
    if not registry_root.exists():
        pytest.skip("Demo registry not initialized; run _init_demo_registry.py first.")

    expected_blocks = {
        "calendar_dim", "foup_dim", "lot_dim", "process_move_fact",
        "process_step_dim", "tool_dim", "wafer_dim", "wafer_yield_fact",
    }
    registry = FilesystemBlockRegistry(registry_root)

    for bid in expected_blocks:
        meta_path = registry_root / bid / "_meta.json"
        assert meta_path.exists(), f"Missing _meta.json for {bid}"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["certified_latest"] == "1.0.0", f"{bid}: certified_latest != '1.0.0'"
        assert meta["certified_latest_updated_by"] == "AUTO_CERTIFY"

        # Verify resolve works end-to-end
        contract = registry.resolve(bid)
        assert contract.block_id == bid
