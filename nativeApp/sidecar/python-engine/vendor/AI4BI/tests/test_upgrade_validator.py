"""
Tests for DataBlockContract upgrade validator (Round 020).

Validates 004-A design-council consensus:
  Breaking:     remove metric/column, grain change, type narrowing, disaggregation change
  Non-breaking: add metric/column, description change
  Forbidden:    change block_id, modify primary_keys
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.blocks.loader import BlockLoader
from ai4bi.blocks.upgrade_validator import UpgradeResult, validate_upgrade

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"


def _from_dict(d: dict) -> DataBlockContract:
    return DataBlockContract.model_validate(d)


@pytest.fixture
def loader() -> BlockLoader:
    return BlockLoader()


@pytest.fixture
def move_fact(loader):
    return loader.load_json(str(_BLOCKS_DIR / "process_move_fact.json"))


@pytest.fixture
def move_fact_v2(move_fact):
    """A minor bump: add a new metric 'setup_time_min'."""
    d = json.loads(move_fact.model_dump_json())
    d["version"] = "1.1.0"
    d["metrics"].append({
        "name": "setup_time_min",
        "formula": "AVG(setup_time_min)",
        "disaggregation_method": "average",
        "unit": "min",
        "description": "Average setup time in minutes",
    })
    return _from_dict(d)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clone_with(contract, **overrides) -> DataBlockContract:
    d = json.loads(contract.model_dump_json())
    d.update(overrides)
    return _from_dict(d)


def _remove_metric(contract, metric_name: str) -> DataBlockContract:
    d = json.loads(contract.model_dump_json())
    d["metrics"] = [m for m in d["metrics"] if m["name"] != metric_name]
    return _from_dict(d)


def _remove_column(contract, column_name: str) -> DataBlockContract:
    d = json.loads(contract.model_dump_json())
    d["columns"] = [c for c in d["columns"] if c["name"] != column_name]
    return _from_dict(d)


def _change_metric_disagg(contract, metric_name: str, new_disagg: str) -> DataBlockContract:
    d = json.loads(contract.model_dump_json())
    for m in d["metrics"]:
        if m["name"] == metric_name:
            m["disaggregation_method"] = new_disagg
    return _from_dict(d)


def _narrow_column_type(contract, col_name: str, new_type: str) -> DataBlockContract:
    d = json.loads(contract.model_dump_json())
    for col in d["columns"]:
        if col["name"] == col_name:
            col["data_type"] = new_type
    return _from_dict(d)


def _add_column(contract, name: str, data_type: str = "string") -> DataBlockContract:
    d = json.loads(contract.model_dump_json())
    d["columns"].append({"name": name, "data_type": data_type,
                         "pii_level": "none", "nullable": True, "description": ""})
    return _from_dict(d)


# ---------------------------------------------------------------------------
# FORBIDDEN change tests
# ---------------------------------------------------------------------------

class TestForbiddenChanges:

    def test_block_id_change_is_forbidden(self, move_fact):
        new = _clone_with(move_fact, block_id="process_move_fact_v2")
        result = validate_upgrade(move_fact, new)
        assert not result.is_valid
        assert len(result.forbidden) >= 1
        assert any("block_id" in msg for msg in result.forbidden)

    def test_primary_keys_change_is_forbidden(self, move_fact):
        new_pks = ["move_id", "extra_key"]
        new = _clone_with(move_fact, primary_keys=new_pks)
        result = validate_upgrade(move_fact, new)
        assert not result.is_valid
        assert any("primary_keys" in msg for msg in result.forbidden)

    def test_forbidden_makes_is_valid_false(self, move_fact):
        new = _clone_with(move_fact, block_id="different_id")
        result = validate_upgrade(move_fact, new)
        assert result.is_valid is False
        assert result.errors

    def test_forbidden_bump_is_major(self, move_fact):
        new = _clone_with(move_fact, block_id="changed_id")
        result = validate_upgrade(move_fact, new)
        assert result.required_bump == "major"


# ---------------------------------------------------------------------------
# BREAKING change tests
# ---------------------------------------------------------------------------

class TestBreakingChanges:

    def test_remove_metric_is_breaking(self, move_fact):
        new = _remove_metric(move_fact, "move_count")
        result = validate_upgrade(move_fact, new)
        assert result.is_valid  # breaking ≠ forbidden
        assert len(result.breaking) >= 1
        assert any("move_count" in msg for msg in result.breaking)
        assert result.required_bump == "major"

    def test_remove_column_is_breaking(self, move_fact):
        new = _remove_column(move_fact, "event_date")
        result = validate_upgrade(move_fact, new)
        assert any("event_date" in msg for msg in result.breaking)
        assert result.required_bump == "major"

    def test_grain_change_is_breaking(self, move_fact):
        new = _clone_with(move_fact, grain="one row per tool per day (daily summary)")
        result = validate_upgrade(move_fact, new)
        assert any("grain" in msg.lower() for msg in result.breaking)
        assert result.required_bump == "major"

    def test_disaggregation_method_change_is_breaking(self, move_fact):
        new = _change_metric_disagg(move_fact, "move_count", "average")
        result = validate_upgrade(move_fact, new)
        assert any("disaggregation_method" in msg for msg in result.breaking)
        assert result.required_bump == "major"

    def test_type_narrowing_is_breaking(self, move_fact):
        col_name = move_fact.columns[0].name
        # First widen to float
        widened = _narrow_column_type(move_fact, col_name, "float")
        # Then narrow back to int
        narrowed = _narrow_column_type(widened, col_name, "int")
        result = validate_upgrade(widened, narrowed)
        assert any(col_name in msg for msg in result.breaking)
        assert result.required_bump == "major"

    def test_breaking_change_is_valid_true(self, move_fact):
        """Breaking changes are valid (just require major bump), not forbidden."""
        new = _remove_metric(move_fact, "move_count")
        result = validate_upgrade(move_fact, new)
        assert result.is_valid  # breaking ≠ forbidden

    def test_metric_formula_change_is_breaking(self, move_fact):
        d = json.loads(move_fact.model_dump_json())
        for m in d["metrics"]:
            if m["name"] == "move_count":
                m["formula"] = "COUNT(move_id)"
        new = _from_dict(d)
        result = validate_upgrade(move_fact, new)
        assert any("move_count" in msg and "formula" in msg for msg in result.breaking)
        assert result.required_bump == "major"


# ---------------------------------------------------------------------------
# NON-BREAKING change tests
# ---------------------------------------------------------------------------

class TestNonBreakingChanges:

    def test_add_metric_is_minor(self, move_fact, move_fact_v2):
        result = validate_upgrade(move_fact, move_fact_v2)
        assert result.is_valid
        assert any("setup_time_min" in msg for msg in result.non_breaking)
        assert result.required_bump == "minor"

    def test_add_column_is_minor(self, move_fact):
        new = _add_column(move_fact, "operator_id")
        result = validate_upgrade(move_fact, new)
        assert any("operator_id" in msg for msg in result.non_breaking)
        assert result.required_bump == "minor"

    def test_description_change_is_patch(self, move_fact):
        new = _clone_with(move_fact, description="Updated description for v2.")
        result = validate_upgrade(move_fact, new)
        assert result.is_valid
        assert "description" in " ".join(result.non_breaking).lower()
        assert result.required_bump == "patch"

    def test_no_changes_is_none(self, move_fact):
        d = json.loads(move_fact.model_dump_json())
        same = _from_dict(d)
        result = validate_upgrade(move_fact, same)
        assert result.is_valid
        assert result.required_bump == "none"
        assert not result.breaking
        assert not result.non_breaking
        assert not result.forbidden


# ---------------------------------------------------------------------------
# Summary & bump ordering tests
# ---------------------------------------------------------------------------

class TestUpgradeResultMeta:

    def test_summary_no_changes(self, move_fact):
        same = _from_dict(json.loads(move_fact.model_dump_json()))
        result = validate_upgrade(move_fact, same)
        assert "No changes" in result.summary()

    def test_summary_breaking(self, move_fact):
        new = _remove_metric(move_fact, "move_count")
        result = validate_upgrade(move_fact, new)
        assert "MAJOR" in result.summary()

    def test_summary_invalid(self, move_fact):
        new = _clone_with(move_fact, block_id="new_id")
        result = validate_upgrade(move_fact, new)
        assert "INVALID" in result.summary()

    def test_has_breaking_property(self, move_fact):
        new = _remove_metric(move_fact, "move_count")
        result = validate_upgrade(move_fact, new)
        assert result.has_breaking is True

    def test_has_forbidden_property(self, move_fact):
        new = _clone_with(move_fact, block_id="other_id")
        result = validate_upgrade(move_fact, new)
        assert result.has_forbidden is True

    def test_both_breaking_and_non_breaking(self, move_fact, move_fact_v2):
        """Remove one metric and add another in same upgrade."""
        d = json.loads(move_fact_v2.model_dump_json())
        d["metrics"] = [m for m in d["metrics"] if m["name"] != "move_count"]
        combined = _from_dict(d)
        result = validate_upgrade(move_fact, combined)
        assert result.has_breaking
        assert result.non_breaking
        assert result.required_bump == "major"
