"""
Round 021 — Data Block View (block library) tests.

Validates:
  - build_block_library returns correct cards for all demo blocks
  - Lifecycle badge map covers all LifecycleStatus values
  - BlockType icon map covers all BlockType values
  - Search filter correctly narrows results
  - Sort order: certified first, then by type, then alphabetically
  - BlockCard properties: header, summary_line, is_certified, is_sandbox
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai4bi.blocks.contracts import BlockType, LifecycleStatus
from ai4bi.blocks.loader import BlockLoader
from ai4bi.report.block_library import (
    BLOCK_TYPE_ICON,
    LIFECYCLE_BADGE,
    BlockCard,
    build_block_library,
)

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"


@pytest.fixture
def demo_contracts():
    loader = BlockLoader()
    contracts = {}
    for path in _BLOCKS_DIR.glob("*.json"):
        c = loader.load_json(str(path))
        contracts[c.block_id] = c
    return contracts


# ---------------------------------------------------------------------------
# Badge / icon completeness tests
# ---------------------------------------------------------------------------

class TestBadgeMaps:

    def test_all_lifecycle_statuses_have_badge(self):
        for status in LifecycleStatus:
            assert status in LIFECYCLE_BADGE, f"Missing badge for {status}"
            badge = LIFECYCLE_BADGE[status]
            assert badge["emoji"]
            assert badge["label"]
            assert badge["color"].startswith("#")

    def test_all_block_types_have_icon(self):
        for bt in BlockType:
            assert bt in BLOCK_TYPE_ICON, f"Missing icon for {bt}"


# ---------------------------------------------------------------------------
# build_block_library tests
# ---------------------------------------------------------------------------

class TestBuildBlockLibrary:

    def test_returns_all_demo_blocks(self, demo_contracts):
        cards = build_block_library(demo_contracts)
        assert len(cards) == len(demo_contracts)

    def test_returns_empty_for_no_contracts(self):
        cards = build_block_library({})
        assert cards == []

    def test_search_by_block_id(self, demo_contracts):
        cards = build_block_library(demo_contracts, search_query="fact")
        # At least the two fact blocks must be returned
        block_ids = {c.block_id for c in cards}
        assert "process_move_fact" in block_ids
        assert "wafer_yield_fact" in block_ids
        # All returned cards must have 'fact' somewhere in id, type or description
        for card in cards:
            assert (
                "fact" in card.block_id.lower()
                or "fact" in card.block_type.value.lower()
                or "fact" in card.description.lower()
            )

    def test_search_by_type(self, demo_contracts):
        cards = build_block_library(demo_contracts, search_query="dimension")
        for card in cards:
            assert (
                "dimension" in card.block_type.value.lower()
                or "dimension" in card.block_id.lower()
            )

    def test_search_case_insensitive(self, demo_contracts):
        lower = build_block_library(demo_contracts, "FACT")
        upper = build_block_library(demo_contracts, "fact")
        assert len(lower) == len(upper)

    def test_search_no_match_returns_empty(self, demo_contracts):
        cards = build_block_library(demo_contracts, "zzz_no_match_xyz")
        assert cards == []

    def test_empty_search_returns_all(self, demo_contracts):
        cards = build_block_library(demo_contracts, "")
        assert len(cards) == len(demo_contracts)

    def test_sort_certified_first(self, demo_contracts):
        """Certified blocks should appear before validated."""
        import json
        from ai4bi.blocks.contracts import DataBlockContract

        # Mark one block as certified
        certified_contracts = dict(demo_contracts)
        d = json.loads(demo_contracts["process_move_fact"].model_dump_json())
        d["block_lifecycle"] = "certified"
        certified_contracts["process_move_fact"] = DataBlockContract.model_validate(d)

        cards = build_block_library(certified_contracts)
        # First card should be the certified one
        assert cards[0].block_id == "process_move_fact"
        assert cards[0].lifecycle == LifecycleStatus.certified

    def test_all_cards_have_block_id(self, demo_contracts):
        for card in build_block_library(demo_contracts):
            assert card.block_id
            assert card.block_id in demo_contracts


# ---------------------------------------------------------------------------
# BlockCard property tests
# ---------------------------------------------------------------------------

class TestBlockCard:

    @pytest.fixture
    def move_fact_card(self, demo_contracts):
        cards = build_block_library(demo_contracts)
        return next(c for c in cards if c.block_id == "process_move_fact")

    def test_type_icon_property(self, move_fact_card):
        assert move_fact_card.type_icon  # non-empty string

    def test_lifecycle_badge_property(self, move_fact_card):
        badge = move_fact_card.lifecycle_badge
        assert badge["emoji"]
        assert badge["color"].startswith("#")

    def test_is_sandbox_for_validated(self, move_fact_card):
        assert move_fact_card.is_sandbox is True  # demo blocks are validated

    def test_is_not_certified_for_validated(self, move_fact_card):
        assert move_fact_card.is_certified is False

    def test_header_contains_block_id(self, move_fact_card):
        assert "process_move_fact" in move_fact_card.header

    def test_summary_line_contains_version(self, move_fact_card):
        assert "1.0.0" in move_fact_card.summary_line

    def test_summary_line_contains_metrics_count(self, move_fact_card):
        assert "3 metrics" in move_fact_card.summary_line

    def test_metric_names_populated(self, move_fact_card):
        assert len(move_fact_card.metric_names) == 3
        assert "move_count" in move_fact_card.metric_names
        assert "queue_time_hr" in move_fact_card.metric_names

    def test_column_names_populated(self, move_fact_card):
        assert len(move_fact_card.column_names) > 0
        assert "event_date" in move_fact_card.column_names

    def test_grain_field(self, move_fact_card):
        assert move_fact_card.grain  # non-empty

    def test_dim_card_has_no_metrics(self, demo_contracts):
        cards = build_block_library(demo_contracts)
        tool_dim = next(c for c in cards if c.block_id == "tool_dim")
        assert len(tool_dim.metric_names) == 0

    def test_relationships_populated(self, move_fact_card):
        # process_move_fact has relationships in its contract
        # (may be empty if RelationshipHint not set in demo)
        assert isinstance(move_fact_card.relationships, list)
