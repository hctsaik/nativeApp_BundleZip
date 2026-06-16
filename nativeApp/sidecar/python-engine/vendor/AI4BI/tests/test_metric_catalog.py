"""Tests for MetricCatalogService three-zone classification (Round 018)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4bi.blocks.contracts import DataBlockContract, LifecycleStatus
from ai4bi.blocks.loader import BlockLoader
from ai4bi.report.metric_catalog import (
    CatalogMetricEntry,
    MetricCatalogService,
    MetricZone,
)

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"
_SEMANTIC_MODEL_PATH = _DEMO_ROOT / "semantic_model.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def semantic_model() -> dict:
    return json.loads(_SEMANTIC_MODEL_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def demo_contracts() -> dict[str, DataBlockContract]:
    loader = BlockLoader()
    contracts: dict[str, DataBlockContract] = {}
    for path in _BLOCKS_DIR.glob("*.json"):
        contract = loader.load_json(str(path))
        contracts[contract.block_id] = contract
    return contracts


@pytest.fixture
def certified_contracts(demo_contracts) -> dict[str, DataBlockContract]:
    """Return a copy of demo_contracts with all blocks set to 'certified'."""
    result = {}
    for block_id, contract in demo_contracts.items():
        # Use model_copy to override lifecycle for testing
        result[block_id] = contract.model_copy(
            update={"block_lifecycle": LifecycleStatus.certified}
        )
    return result


@pytest.fixture
def service() -> MetricCatalogService:
    return MetricCatalogService()


# ---------------------------------------------------------------------------
# Zone classification tests
# ---------------------------------------------------------------------------

class TestMetricCatalogService:

    def test_all_sandbox_when_all_validated(self, service, semantic_model, demo_contracts):
        """All demo blocks are validated → all metrics should land in SANDBOX zone."""
        result = service.classify(semantic_model, demo_contracts)

        # Demo has no certified blocks → no certified_ready or needs_blocks
        assert len(result.certified_ready) == 0
        assert len(result.needs_blocks) == 0
        # All metrics go to sandbox
        assert len(result.sandbox) > 0
        for entry in result.sandbox:
            assert entry.zone == MetricZone.SANDBOX

    def test_sandbox_entries_have_correct_block_ids(self, service, semantic_model, demo_contracts):
        """Sandbox entries reference the owner block from semantic model."""
        result = service.classify(semantic_model, demo_contracts)
        expected_owners = {m["owner_block"] for m in semantic_model.get("metrics", [])}
        actual_owners = {e.block_id for e in result.sandbox}
        assert actual_owners == expected_owners

    def test_all_certified_ready_when_all_certified(self, service, semantic_model, certified_contracts):
        """When all blocks are certified and present, all metrics → CERTIFIED_READY."""
        result = service.classify(semantic_model, certified_contracts)

        assert len(result.sandbox) == 0
        assert len(result.needs_blocks) == 0
        assert len(result.certified_ready) > 0
        for entry in result.certified_ready:
            assert entry.zone == MetricZone.CERTIFIED_READY

    def test_needs_blocks_when_dim_not_certified(self, service, semantic_model, certified_contracts):
        """If owner is certified but a dim block is not, metric → NEEDS_BLOCKS."""
        # Demote one dimension block back to validated
        demoted = dict(certified_contracts)
        tool_contract = demoted["tool_dim"]
        demoted["tool_dim"] = tool_contract.model_copy(
            update={"block_lifecycle": LifecycleStatus.validated}
        )

        result = service.classify(semantic_model, demoted)

        # Metrics from process_move_fact use tool_dim → should be NEEDS_BLOCKS
        move_fact_metrics = [e for e in result.needs_blocks if e.block_id == "process_move_fact"]
        # Some or all process_move_fact metrics should be needs_blocks
        assert len(move_fact_metrics) > 0
        for entry in move_fact_metrics:
            assert entry.zone == MetricZone.NEEDS_BLOCKS
            assert "tool_dim" in entry.missing_blocks

    def test_needs_blocks_when_dim_missing_from_contracts(self, service, semantic_model, certified_contracts):
        """If owner is certified but a dim block is missing entirely, metric → NEEDS_BLOCKS."""
        # Remove tool_dim from contracts
        partial = {k: v for k, v in certified_contracts.items() if k != "tool_dim"}

        result = service.classify(semantic_model, partial)

        move_fact_metrics = [e for e in result.needs_blocks if e.block_id == "process_move_fact"]
        assert len(move_fact_metrics) > 0
        for entry in move_fact_metrics:
            assert "tool_dim" in entry.missing_blocks

    def test_sandbox_when_owner_block_missing(self, service, semantic_model):
        """If owner block is not in contracts at all, metric → SANDBOX."""
        result = service.classify(semantic_model, {})

        assert len(result.certified_ready) == 0
        assert len(result.needs_blocks) == 0
        assert len(result.sandbox) > 0

    def test_metric_entries_have_required_fields(self, service, semantic_model, demo_contracts):
        result = service.classify(semantic_model, demo_contracts)
        for entry in result.all_entries:
            assert entry.metric_name
            assert entry.block_id
            assert entry.display_name
            assert entry.aggregation
            assert entry.zone in (MetricZone.CERTIFIED_READY, MetricZone.NEEDS_BLOCKS, MetricZone.SANDBOX)

    def test_catalog_result_all_entries(self, service, semantic_model, demo_contracts):
        result = service.classify(semantic_model, demo_contracts)
        total = len(result.certified_ready) + len(result.needs_blocks) + len(result.sandbox)
        assert total == len(result.all_entries)
        assert total == len(semantic_model.get("metrics", []))

    def test_is_empty_when_no_contracts_and_no_metrics(self, service):
        result = service.classify({"metrics": []}, {})
        assert result.is_empty()

    def test_aggregation_extracted_correctly(self, service, semantic_model, demo_contracts):
        result = service.classify(semantic_model, demo_contracts)
        # process_move_fact: move_count=SUM, queue_time_hr=AVG
        move_count = next(
            (e for e in result.all_entries if e.metric_name == "move_count"), None
        )
        assert move_count is not None
        assert move_count.aggregation == "SUM"

        # avg_queue_time_hr has AVG
        avg_queue = next(
            (e for e in result.all_entries if e.metric_name == "avg_queue_time_hr"), None
        )
        assert avg_queue is not None
        assert avg_queue.aggregation == "AVG"


# ---------------------------------------------------------------------------
# Sandbox detection helpers (used by app.py)
# ---------------------------------------------------------------------------

class TestSandboxDetection:

    def test_has_sandbox_blocks_returns_true_for_validated_blocks(self, demo_contracts):
        """Demo blocks are validated → _has_sandbox_blocks should return True."""
        from ai4bi.report.templates import build_semiconductor_queue_time_report
        from ai4bi.ui.app import _has_sandbox_blocks

        report = build_semiconductor_queue_time_report()
        assert _has_sandbox_blocks(report, demo_contracts) is True

    def test_has_sandbox_blocks_returns_false_for_all_certified(self, certified_contracts):
        from ai4bi.report.templates import build_semiconductor_queue_time_report
        from ai4bi.ui.app import _has_sandbox_blocks

        report = build_semiconductor_queue_time_report()
        assert _has_sandbox_blocks(report, certified_contracts) is False

    def test_has_sandbox_blocks_returns_true_for_missing_contract(self):
        """Missing contract entry → treated as sandbox."""
        from ai4bi.report.templates import build_semiconductor_queue_time_report
        from ai4bi.ui.app import _has_sandbox_blocks

        report = build_semiconductor_queue_time_report()
        assert _has_sandbox_blocks(report, {}) is True

    def test_is_sandbox_visual_per_visual(self, demo_contracts, certified_contracts):
        from ai4bi.report.templates import build_semiconductor_queue_time_report
        from ai4bi.ui.app import _is_sandbox_visual

        report = build_semiconductor_queue_time_report()
        main_page = report.pages["main"]
        first_visual_id = main_page.visual_order[0]
        first_visual = main_page.visuals[first_visual_id]

        # With validated contracts → sandbox
        assert _is_sandbox_visual(first_visual, demo_contracts) is True
        # With certified contracts → not sandbox
        assert _is_sandbox_visual(first_visual, certified_contracts) is False
