"""Tests for PublishedReportStore and PublishBlockedError — Round 015-A."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from ai4bi.blocks.contracts import DataBlockContract, LifecycleStatus
from ai4bi.report.models import (
    ExecutableReportSpec,
    PublishBlockedError,
    PublishedReportStore,
    ReportValidationError,
)
from ai4bi.report.publication import PublicationGateResult, GateCheckResult, run_publication_gate
from ai4bi.report.templates import build_semiconductor_queue_time_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATA_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_SEMANTIC_MODEL_PATH = _DATA_ROOT / "semantic_model.json"
_BLOCKS_DIR = _DATA_ROOT / "blocks"


def _make_passing_gate() -> PublicationGateResult:
    """Return a PublicationGateResult where can_publish=True."""
    return PublicationGateResult(
        can_publish=True,
        checks=[
            GateCheckResult(
                check_name="block_lifecycle",
                passed=True,
                message="All blocks certified.",
                blocking=True,
            )
        ],
    )


def _make_failing_gate() -> PublicationGateResult:
    """Return a PublicationGateResult where can_publish=False."""
    return PublicationGateResult(
        can_publish=False,
        checks=[
            GateCheckResult(
                check_name="block_lifecycle",
                passed=False,
                message="Blocks not certified.",
                blocking=True,
            )
        ],
    )


def _demo_report() -> ExecutableReportSpec:
    return build_semiconductor_queue_time_report()


# ---------------------------------------------------------------------------
# Test 1: publish() writes a JSON file under published/<report_id>/
# ---------------------------------------------------------------------------

def test_publish_writes_json_file_under_report_id_directory(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_passing_gate()

    written_path, _ = store.publish(report, gate)

    assert written_path.exists(), "Published file must exist on disk."
    assert written_path.suffix == ".json", "Published file must be a JSON file."
    # Must be nested under a directory named after the report_id
    assert written_path.parent.name == report.report_id


# ---------------------------------------------------------------------------
# Test 2: Written file deserializes back to ExecutableReportSpec with all fields intact
# ---------------------------------------------------------------------------

def test_publish_written_file_round_trips_to_report(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_passing_gate()

    written_path, _ = store.publish(report, gate)

    payload = json.loads(written_path.read_text(encoding="utf-8"))
    restored = ExecutableReportSpec.from_dict(payload)

    assert restored.report_id == report.report_id
    assert restored.title == report.title
    assert restored.semantic_model_ref == report.semantic_model_ref
    assert set(restored.pages.keys()) == set(report.pages.keys())
    assert set(restored.controls.keys()) == set(report.controls.keys())


# ---------------------------------------------------------------------------
# Test 3: publish() sets audit.last_modified_at on the snapshot
# ---------------------------------------------------------------------------

def test_publish_sets_last_modified_at(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    original_modified = report.audit.last_modified_at
    gate = _make_passing_gate()

    written_path, _ = store.publish(report, gate)

    payload = json.loads(written_path.read_text(encoding="utf-8"))
    restored = ExecutableReportSpec.from_dict(payload)

    assert restored.audit.last_modified_at is not None
    # The timestamp must be parseable as ISO-8601
    parsed = datetime.fromisoformat(restored.audit.last_modified_at)
    assert parsed is not None


# ---------------------------------------------------------------------------
# Test 4: list_published() returns paths newest-first
# ---------------------------------------------------------------------------

def test_list_published_returns_newest_first(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_passing_gate()

    path_a, _ = store.publish(report, gate)
    # Ensure distinct timestamps (filenames are timestamp-based)
    time.sleep(0.01)
    path_b, _ = store.publish(report, gate)

    listed = store.list_published(report.report_id)

    assert len(listed) >= 2
    # newest first → path_b (later) should appear before path_a (earlier)
    b_index = listed.index(path_b)
    a_index = listed.index(path_a)
    assert b_index < a_index, f"Expected {path_b.name} before {path_a.name} but got order {[p.name for p in listed]}"


# ---------------------------------------------------------------------------
# Test 5: publish() raises PublishBlockedError when gate_result.can_publish=False
# ---------------------------------------------------------------------------

def test_publish_raises_when_gate_blocked(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_failing_gate()

    with pytest.raises(PublishBlockedError):
        store.publish(report, gate)


# ---------------------------------------------------------------------------
# Test 6: Multiple publishes for the same report create multiple timestamped files
# ---------------------------------------------------------------------------

def test_multiple_publishes_create_multiple_files(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_passing_gate()

    path_1, _ = store.publish(report, gate)
    time.sleep(0.01)
    path_2, _ = store.publish(report, gate)

    assert path_1 != path_2, "Each publish should produce a distinct file."
    assert path_1.exists()
    assert path_2.exists()

    all_files = list((tmp_path / "published" / report.report_id).glob("*.json"))
    assert len(all_files) == 2


# ---------------------------------------------------------------------------
# Test 7: Share URL format is correct and path exists
# ---------------------------------------------------------------------------

def test_share_url_format_and_path_exists(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_passing_gate()

    written_path, share_url = store.publish(report, gate)

    assert share_url.startswith("?mode=readonly&draft="), (
        f"Share URL must start with '?mode=readonly&draft=' but got: {share_url!r}"
    )
    # The path embedded in the URL must exist on disk
    embedded = share_url[len("?mode=readonly&draft="):]
    assert Path(embedded).exists(), f"Embedded path does not exist: {embedded}"
    assert Path(embedded) == written_path


# ---------------------------------------------------------------------------
# Test 8: PublishedReportStore auto-creates the published/ directory
# ---------------------------------------------------------------------------

def test_published_store_autocreates_directory(tmp_path):
    publish_root = tmp_path / "does_not_exist_yet" / "published"
    assert not publish_root.exists(), "Pre-condition: directory must not exist."

    store = PublishedReportStore(publish_root)
    report = _demo_report()
    gate = _make_passing_gate()

    written_path, _ = store.publish(report, gate)

    assert publish_root.exists(), "PublishedReportStore must auto-create the root directory."
    assert written_path.exists()


def test_load_published_snapshot_round_trips(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    report = _demo_report()
    gate = _make_passing_gate()
    written_path, _ = store.publish(report, gate)

    restored = store.load(written_path)

    assert restored.report_id == report.report_id
    assert restored.title == report.title


def test_load_published_snapshot_rejects_path_outside_root(tmp_path):
    store = PublishedReportStore(tmp_path / "published")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_demo_report().to_dict()), encoding="utf-8")

    with pytest.raises(ReportValidationError, match="outside"):
        store.load(outside)


def test_load_published_snapshot_rejects_missing_json(tmp_path):
    store = PublishedReportStore(tmp_path / "published")

    with pytest.raises(ReportValidationError, match="existing JSON"):
        store.load(tmp_path / "published" / "missing.json")
