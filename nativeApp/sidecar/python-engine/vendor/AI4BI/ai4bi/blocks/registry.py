"""
FilesystemBlockRegistry — Round 009/014 P0 implementation.

Storage layout
--------------
<root>/
  <block_id>/
    1.0.0.json        # immutable version snapshot
    2.0.0.json        # immutable version snapshot
    _meta.json        # ONLY mutable file; atomic write via temp+rename

_meta.json schema
-----------------
{
  "block_id": "sales_fact",
  "certified_latest": "1.0.0",               # null when no certified version
  "certified_latest_updated_at": "<iso8601>",
  "certified_latest_updated_by": "AUTO_CERTIFY",
  "versions": [
    {
      "version": "1.0.0",
      "lifecycle": "certified",
      "registered_at": "<iso8601>",
      "certified_at": "<iso8601>",            # null when not certified
      "certified_by": "<str>",               # null when not certified
      "change_type": "ADDITIVE",             # optional
      "notes": null                          # optional
    }
  ]
}
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from ai4bi.blocks.contracts import DataBlockContract


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RegistryError(Exception):
    """Base class for all BlockRegistry errors."""


class BlockNotFoundError(RegistryError):
    """Raised when a block_id does not exist in the registry."""


class BlockVersionNotFoundError(RegistryError):
    """Raised when a specific pinned version does not exist."""


class NoCertifiedVersionError(RegistryError):
    """Raised when resolve() needs a certified version but none is set."""


# ---------------------------------------------------------------------------
# VersionLifecycle enum
# ---------------------------------------------------------------------------

class VersionLifecycle(str, Enum):
    draft      = "draft"
    certified  = "certified"
    deprecated = "deprecated"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VersionRecord:
    block_id: str
    version: str
    lifecycle: VersionLifecycle
    registered_at: str                    # ISO-8601 with UTC offset
    certified_at: Optional[str] = None
    certified_by: Optional[str] = None
    change_type: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class CertifiedLatestPointer:
    block_id: str
    certified_latest: str
    updated_at: str
    updated_by: str


@dataclass
class RegistrySnapshot:
    snapshot_id: str
    taken_at: str
    taken_by: str
    # mapping block_id -> certified version at time of snapshot
    pinned_versions: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class BlockRegistryProtocol(Protocol):
    def register(
        self,
        contract: DataBlockContract,
        version: str,
        change_type: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> VersionRecord: ...

    def certify(
        self,
        block_id: str,
        version: str,
        certified_by: str,
    ) -> CertifiedLatestPointer: ...

    def resolve(
        self,
        block_id: str,
        pinned_version: Optional[str] = None,
        *,
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> DataBlockContract: ...

    def list_versions(
        self,
        block_id: str,
        lifecycle_filter: Optional[VersionLifecycle] = None,
    ) -> list[VersionRecord]: ...

    def get_certified_latest(self, block_id: str) -> str: ...

    def take_snapshot(
        self,
        block_ids: list[str],
        snapshot_id: str,
        taken_by: str,
    ) -> RegistrySnapshot: ...

    def deprecate(
        self,
        block_id: str,
        version: str,
        deprecated_by: str,
        notes: Optional[str] = None,
    ) -> VersionRecord: ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via temp-file + rename (same directory)."""
    tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex}")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)   # atomic on POSIX; best-effort on Windows
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _load_meta(meta_path: Path) -> dict:
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _vr_from_dict(block_id: str, d: dict) -> VersionRecord:
    return VersionRecord(
        block_id=block_id,
        version=d["version"],
        lifecycle=VersionLifecycle(d["lifecycle"]),
        registered_at=d["registered_at"],
        certified_at=d.get("certified_at"),
        certified_by=d.get("certified_by"),
        change_type=d.get("change_type"),
        notes=d.get("notes"),
    )


def _vr_to_dict(vr: VersionRecord) -> dict:
    return {
        "version": vr.version,
        "lifecycle": vr.lifecycle.value,
        "registered_at": vr.registered_at,
        "certified_at": vr.certified_at,
        "certified_by": vr.certified_by,
        "change_type": vr.change_type,
        "notes": vr.notes,
    }


# ---------------------------------------------------------------------------
# FilesystemBlockRegistry
# ---------------------------------------------------------------------------

class FilesystemBlockRegistry:
    """
    Filesystem-backed implementation of BlockRegistryProtocol.

    Thread safety: NOT guaranteed.  For concurrent access upgrade to SQLite
    hybrid (P2 trigger: blocks > 80 or CI merge conflict on _meta.json).
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _block_dir(self, block_id: str) -> Path:
        return self._root / block_id

    def _version_path(self, block_id: str, version: str) -> Path:
        return self._block_dir(block_id) / f"{version}.json"

    def _meta_path(self, block_id: str) -> Path:
        return self._block_dir(block_id) / "_meta.json"

    def _assert_block_exists(self, block_id: str) -> None:
        if not self._meta_path(block_id).exists():
            raise BlockNotFoundError(f"Block '{block_id}' not found in registry.")

    def _read_meta(self, block_id: str) -> dict:
        self._assert_block_exists(block_id)
        return _load_meta(self._meta_path(block_id))

    def _write_meta(self, block_id: str, meta: dict) -> None:
        _atomic_write(self._meta_path(block_id), meta)

    def _load_contract(self, block_id: str, version: str) -> DataBlockContract:
        vpath = self._version_path(block_id, version)
        if not vpath.exists():
            raise BlockVersionNotFoundError(
                f"Version '{version}' of block '{block_id}' does not exist at {vpath}."
            )
        raw = json.loads(vpath.read_text(encoding="utf-8"))
        return DataBlockContract.model_validate(raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        contract: DataBlockContract,
        version: str,
        change_type: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> VersionRecord:
        """
        Register a new version of a DataBlockContract.

        - Writes <root>/<block_id>/<version>.json (immutable snapshot).
        - Creates or updates <root>/<block_id>/_meta.json (atomic write).
        - Lifecycle of the new record is always ``draft``.
        """
        block_id = contract.block_id
        block_dir = self._block_dir(block_id)
        block_dir.mkdir(parents=True, exist_ok=True)

        now = _utcnow()

        # Write immutable version snapshot (do not overwrite if already exists)
        vpath = self._version_path(block_id, version)
        if not vpath.exists():
            vpath.write_text(
                json.dumps(contract.model_dump(mode="json"), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        new_record = VersionRecord(
            block_id=block_id,
            version=version,
            lifecycle=VersionLifecycle.draft,
            registered_at=now,
            change_type=change_type,
            notes=notes,
        )

        # Load or bootstrap _meta.json
        meta_path = self._meta_path(block_id)
        if meta_path.exists():
            meta = _load_meta(meta_path)
            # Avoid duplicate version entries; replace if re-registering same version
            meta["versions"] = [v for v in meta["versions"] if v["version"] != version]
        else:
            meta = {
                "block_id": block_id,
                "certified_latest": None,
                "certified_latest_updated_at": None,
                "certified_latest_updated_by": None,
                "versions": [],
            }

        meta["versions"].append(_vr_to_dict(new_record))
        self._write_meta(block_id, meta)

        return new_record

    def certify(
        self,
        block_id: str,
        version: str,
        certified_by: str,
    ) -> CertifiedLatestPointer:
        """
        Mark *version* as certified and update the certified_latest pointer.

        Idempotent: if the version is already certified AND is already the
        certified_latest, returns the existing pointer without re-writing.
        """
        meta = self._read_meta(block_id)

        vpath = self._version_path(block_id, version)
        if not vpath.exists():
            raise BlockVersionNotFoundError(
                f"Version '{version}' of block '{block_id}' does not exist."
            )

        now = _utcnow()

        # Find or locate the version record
        updated_versions = []
        found = False
        already_certified = False
        for vd in meta["versions"]:
            if vd["version"] == version:
                found = True
                if (
                    vd["lifecycle"] == VersionLifecycle.certified.value
                    and meta.get("certified_latest") == version
                ):
                    already_certified = True
                    updated_versions.append(vd)
                else:
                    vd = dict(vd)
                    vd["lifecycle"] = VersionLifecycle.certified.value
                    vd["certified_at"] = vd.get("certified_at") or now
                    vd["certified_by"] = vd.get("certified_by") or certified_by
                    updated_versions.append(vd)
            else:
                updated_versions.append(vd)

        if not found:
            # Version exists on disk but not in _meta — add it
            updated_versions.append({
                "version": version,
                "lifecycle": VersionLifecycle.certified.value,
                "registered_at": now,
                "certified_at": now,
                "certified_by": certified_by,
                "change_type": None,
                "notes": None,
            })

        pointer = CertifiedLatestPointer(
            block_id=block_id,
            certified_latest=version,
            updated_at=now,
            updated_by=certified_by,
        )

        if not already_certified:
            meta["versions"] = updated_versions
            meta["certified_latest"] = version
            meta["certified_latest_updated_at"] = now
            meta["certified_latest_updated_by"] = certified_by
            self._write_meta(block_id, meta)
        else:
            # Return pointer from existing meta without touching disk
            pointer = CertifiedLatestPointer(
                block_id=block_id,
                certified_latest=meta["certified_latest"],
                updated_at=meta["certified_latest_updated_at"],
                updated_by=meta["certified_latest_updated_by"],
            )

        return pointer

    def resolve(
        self,
        block_id: str,
        pinned_version: Optional[str] = None,
        *,
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> DataBlockContract:
        """
        Resolve a block to a DataBlockContract.

        Resolution order:
        1. If *pinned_version* is provided → load exactly that version.
           Missing version → raise BlockVersionNotFoundError (no fallback).
        2. Elif *version_snapshot* dict has an entry for *block_id* → use it.
        3. Else → look up certified_latest from _meta.json.
           No certified version → raise NoCertifiedVersionError.
        """
        self._assert_block_exists(block_id)

        if pinned_version is not None:
            return self._load_contract(block_id, pinned_version)

        if version_snapshot is not None and block_id in version_snapshot:
            snapped = version_snapshot[block_id]
            return self._load_contract(block_id, snapped)

        # Fall back to certified_latest
        meta = _load_meta(self._meta_path(block_id))
        certified = meta.get("certified_latest")
        if not certified:
            raise NoCertifiedVersionError(
                f"Block '{block_id}' has no certified version. "
                "Run certify() before resolving without a pinned version."
            )
        return self._load_contract(block_id, certified)

    def list_versions(
        self,
        block_id: str,
        lifecycle_filter: Optional[VersionLifecycle] = None,
    ) -> list[VersionRecord]:
        """Return all VersionRecords for *block_id*, optionally filtered."""
        meta = self._read_meta(block_id)
        records = [_vr_from_dict(block_id, vd) for vd in meta["versions"]]
        if lifecycle_filter is not None:
            records = [r for r in records if r.lifecycle == lifecycle_filter]
        return records

    def get_certified_latest(self, block_id: str) -> str:
        """Return the certified_latest version string for *block_id*."""
        meta = self._read_meta(block_id)
        certified = meta.get("certified_latest")
        if not certified:
            raise NoCertifiedVersionError(
                f"Block '{block_id}' has no certified version."
            )
        return certified

    def take_snapshot(
        self,
        block_ids: list[str],
        snapshot_id: str,
        taken_by: str,
    ) -> RegistrySnapshot:
        """
        Capture the certified_latest for each block_id into a RegistrySnapshot.

        Raises NoCertifiedVersionError if any requested block lacks a certified
        version.  Raises BlockNotFoundError if any block_id is unknown.
        """
        now = _utcnow()
        pinned: dict[str, str] = {}
        for bid in block_ids:
            pinned[bid] = self.get_certified_latest(bid)

        return RegistrySnapshot(
            snapshot_id=snapshot_id,
            taken_at=now,
            taken_by=taken_by,
            pinned_versions=pinned,
        )

    def deprecate(
        self,
        block_id: str,
        version: str,
        deprecated_by: str,
        notes: Optional[str] = None,
    ) -> VersionRecord:
        """Mark *version* of *block_id* as deprecated."""
        meta = self._read_meta(block_id)

        vpath = self._version_path(block_id, version)
        if not vpath.exists():
            raise BlockVersionNotFoundError(
                f"Version '{version}' of block '{block_id}' does not exist."
            )

        updated_versions = []
        found = False
        result_record: Optional[VersionRecord] = None
        for vd in meta["versions"]:
            if vd["version"] == version:
                found = True
                vd = dict(vd)
                vd["lifecycle"] = VersionLifecycle.deprecated.value
                if notes:
                    vd["notes"] = notes
                updated_versions.append(vd)
                result_record = _vr_from_dict(block_id, vd)
            else:
                updated_versions.append(vd)

        if not found:
            now = _utcnow()
            new_vd = {
                "version": version,
                "lifecycle": VersionLifecycle.deprecated.value,
                "registered_at": now,
                "certified_at": None,
                "certified_by": None,
                "change_type": None,
                "notes": notes,
            }
            updated_versions.append(new_vd)
            result_record = _vr_from_dict(block_id, new_vd)

        meta["versions"] = updated_versions
        self._write_meta(block_id, meta)

        assert result_record is not None
        return result_record
