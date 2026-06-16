"""Tests for ai4bi.report.catalog (CatalogBrowser) and ai4bi.report.builder (build_visual_from_selection).

At least 8 test cases covering:
1. build_catalog returns correct metric entries for fact blocks.
2. build_catalog includes self-dimensions from the primary block.
3. build_catalog includes certified related dimension blocks.
4. build_catalog excludes prohibited block pairs.
5. build_catalog handles missing contracts gracefully.
6. build_visual_from_selection: happy-path single-block kpi_card.
7. build_visual_from_selection: happy-path multi-metric table with dimensions.
8. Safety rule: kpi_card rejects dimensions.
9. Safety rule: line_chart requires at least one dimension.
10. Safety rule: max 2 metrics enforced.
11. Safety rule: max 2 dimensions enforced.
12. Safety rule: cross-block dimension must have a certified relationship.
13. Safety rule: unknown metric name raises ValueError.
14. build_visual_from_selection: bar_chart with certified cross-block dimension.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.blocks.loader import BlockLoader
from ai4bi.query_spec import VisualType
from ai4bi.report.catalog import (
    BlockCatalog,
    DimensionEntry,
    MetricEntry,
    _aggregation_from_formula,
    build_catalog,
)
from ai4bi.report.builder import build_visual_from_selection

# ---------------------------------------------------------------------------
# Fixtures — load demo blocks once
# ---------------------------------------------------------------------------

_DEMO_ROOT = Path(__file__).parent.parent / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"
_SEMANTIC_MODEL_PATH = _DEMO_ROOT / "semantic_model.json"


@pytest.fixture(scope="module")
def semantic_model() -> dict:
    return json.loads(_SEMANTIC_MODEL_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contracts() -> dict[str, DataBlockContract]:
    loader = BlockLoader()
    result: dict[str, DataBlockContract] = {}
    for path in _BLOCKS_DIR.glob("*.json"):
        contract = loader.load_json(str(path))
        result[contract.block_id] = contract
    return result


@pytest.fixture(scope="module")
def catalog(semantic_model: dict, contracts: dict[str, DataBlockContract]) -> list[BlockCatalog]:
    return build_catalog(semantic_model, contracts)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _block_by_id(catalog: list[BlockCatalog], block_id: str) -> BlockCatalog:
    for bc in catalog:
        if bc.block_id == block_id:
            return bc
    raise KeyError(f"No catalog entry for block '{block_id}'")


# ===========================================================================
# Test 1 — build_catalog returns correct metric entries for fact blocks
# ===========================================================================

def test_build_catalog_returns_metrics_for_process_move_fact(catalog: list[BlockCatalog]) -> None:
    bc = _block_by_id(catalog, "process_move_fact")
    metric_names = {m.metric_name for m in bc.metrics}
    # semantic_model defines: move_count, avg_queue_time_hr, avg_process_time_min
    assert "move_count" in metric_names
    assert "avg_queue_time_hr" in metric_names
    assert "avg_process_time_min" in metric_names
    # All metric entries have the correct block_id
    for m in bc.metrics:
        assert m.block_id == "process_move_fact"


# ===========================================================================
# Test 2 — aggregation is extracted correctly from formula strings
# ===========================================================================

@pytest.mark.parametrize("formula,expected", [
    ("SUM(move_count)", "SUM"),
    ("AVG(queue_time_hr)", "AVG"),
    ("COUNT(wafer_id)", "COUNT"),
    ("MIN(queue_time_hr)", "MIN"),
    ("MAX(queue_time_hr)", "MAX"),
    ("COUNT_DISTINCT(lot_id)", "COUNT_DISTINCT"),
    ("SUM(good_die) / SUM(tested_die) * 100", "SUM"),
    ("unknown_formula(x)", "SUM"),   # fallback
])
def test_aggregation_from_formula(formula: str, expected: str) -> None:
    assert _aggregation_from_formula(formula) == expected


# ===========================================================================
# Test 3 — build_catalog includes self-dimensions from the primary block
# ===========================================================================

def test_build_catalog_includes_self_dimensions(catalog: list[BlockCatalog]) -> None:
    bc = _block_by_id(catalog, "process_move_fact")
    self_dim_col_names = {
        d.column_name for d in bc.dimensions if d.block_id == "process_move_fact"
    }
    # process_move_fact has event_date, product_family, step_id, etc.
    assert "event_date" in self_dim_col_names
    assert "product_family" in self_dim_col_names
    assert "step_id" in self_dim_col_names


# ===========================================================================
# Test 4 — build_catalog includes certified related dimension block columns
# ===========================================================================

def test_build_catalog_includes_certified_dim_block_columns(catalog: list[BlockCatalog]) -> None:
    bc = _block_by_id(catalog, "process_move_fact")
    # tool_dim is a certified direct dimension; its columns should be in catalog.
    cross_block_dims = {
        d.column_name
        for d in bc.dimensions
        if d.block_id == "tool_dim"
    }
    assert "tool_id" in cross_block_dims
    assert "vendor" in cross_block_dims


# ===========================================================================
# Test 5 — build_catalog handles missing contracts gracefully
# ===========================================================================

def test_build_catalog_missing_contract_is_skipped(
    semantic_model: dict,
    contracts: dict[str, DataBlockContract],
) -> None:
    # Provide a contracts dict that is missing tool_dim.
    partial = {k: v for k, v in contracts.items() if k != "tool_dim"}
    catalog = build_catalog(semantic_model, partial)
    bc = _block_by_id(catalog, "process_move_fact")
    # tool_dim columns must be absent.
    tool_dim_cols = {d.column_name for d in bc.dimensions if d.block_id == "tool_dim"}
    assert len(tool_dim_cols) == 0
    # But self-dimensions are still present.
    assert any(d.block_id == "process_move_fact" for d in bc.dimensions)


# ===========================================================================
# Test 6 — build_visual_from_selection: kpi_card happy path (no dimensions)
# ===========================================================================

def test_build_visual_kpi_card_no_dimensions(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    query, viz = build_visual_from_selection(
        visual_id="test_kpi_move_count",
        block_id="process_move_fact",
        metric_names=["move_count"],
        dimension_names=[],
        visual_type=VisualType.kpi_card,
        contracts=contracts,
        semantic_model=semantic_model,
    )
    assert query.spec_id == "test_kpi_move_count"
    assert len(query.metrics) == 1
    assert query.metrics[0].metric_name == "move_count"
    assert query.dimensions == []
    assert viz.visual_type == VisualType.kpi_card
    assert query.block_refs[0].block_id == "process_move_fact"


# ===========================================================================
# Test 7 — build_visual_from_selection: table with two metrics + two dimensions
# ===========================================================================

def test_build_visual_table_two_metrics_two_dims(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    query, viz = build_visual_from_selection(
        visual_id="test_table_full",
        block_id="process_move_fact",
        metric_names=["move_count", "queue_time_hr"],
        dimension_names=[
            "tool_dim.tool_id",
            "tool_dim.vendor",
        ],
        visual_type=VisualType.table,
        contracts=contracts,
        semantic_model=semantic_model,
    )
    assert len(query.metrics) == 2
    assert len(query.dimensions) == 2
    assert viz.visual_type == VisualType.table
    # tool_dim should be added as a second block_ref.
    block_ids = [ref.block_id for ref in query.block_refs]
    assert "process_move_fact" in block_ids
    assert "tool_dim" in block_ids


# ===========================================================================
# Test 8 — Safety rule: kpi_card rejects dimensions
# ===========================================================================

def test_kpi_card_rejects_dimensions(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    with pytest.raises(ValueError, match="does not support dimensions"):
        build_visual_from_selection(
            visual_id="bad_kpi",
            block_id="process_move_fact",
            metric_names=["move_count"],
            dimension_names=["process_move_fact.event_date"],
            visual_type=VisualType.kpi_card,
            contracts=contracts,
            semantic_model=semantic_model,
        )


# ===========================================================================
# Test 9 — Safety rule: line_chart requires at least one dimension
# ===========================================================================

def test_line_chart_requires_dimension(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    with pytest.raises(ValueError, match="requires at least one dimension"):
        build_visual_from_selection(
            visual_id="bad_line",
            block_id="process_move_fact",
            metric_names=["move_count"],
            dimension_names=[],
            visual_type=VisualType.line_chart,
            contracts=contracts,
            semantic_model=semantic_model,
        )


# ===========================================================================
# Test 10 — Safety rule: max 2 metrics enforced
# ===========================================================================

def test_too_many_metrics_raises(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    with pytest.raises(ValueError, match="At most 2 metrics"):
        build_visual_from_selection(
            visual_id="bad_metrics",
            block_id="process_move_fact",
            metric_names=["move_count", "queue_time_hr", "process_time_min"],
            dimension_names=[],
            visual_type=VisualType.kpi_card,
            contracts=contracts,
            semantic_model=semantic_model,
        )


# ===========================================================================
# Test 11 — Safety rule: max 2 dimensions enforced
# ===========================================================================

def test_too_many_dimensions_raises(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    with pytest.raises(ValueError, match="At most 2 dimensions"):
        build_visual_from_selection(
            visual_id="bad_dims",
            block_id="process_move_fact",
            metric_names=["move_count"],
            dimension_names=[
                "process_move_fact.event_date",
                "process_move_fact.step_id",
                "process_move_fact.product_family",
            ],
            visual_type=VisualType.table,
            contracts=contracts,
            semantic_model=semantic_model,
        )


# ===========================================================================
# Test 12 — Safety rule: cross-block dimension must have a certified relationship
# ===========================================================================

def test_uncertified_cross_block_dimension_raises(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    # wafer_yield_fact is NOT a certified dimension of process_move_fact
    # (they are in the prohibited_paths list and have no certified relationship from
    # process_move_fact to wafer_yield_fact).
    # We simulate by requesting a column from a block with no certified link.
    with pytest.raises(ValueError, match="certified relationship"):
        build_visual_from_selection(
            visual_id="bad_cross_block",
            block_id="process_move_fact",
            metric_names=["move_count"],
            dimension_names=["wafer_yield_fact.test_date"],
            visual_type=VisualType.bar_chart,
            contracts=contracts,
            semantic_model=semantic_model,
        )


# ===========================================================================
# Test 13 — Safety rule: unknown metric name raises ValueError
# ===========================================================================

def test_unknown_metric_name_raises(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    with pytest.raises(ValueError, match="not defined on block"):
        build_visual_from_selection(
            visual_id="bad_metric_name",
            block_id="process_move_fact",
            metric_names=["nonexistent_metric"],
            dimension_names=[],
            visual_type=VisualType.kpi_card,
            contracts=contracts,
            semantic_model=semantic_model,
        )


# ===========================================================================
# Test 14 — bar_chart with certified cross-block dimension
# ===========================================================================

def test_build_visual_bar_chart_with_certified_dim_block(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict,
) -> None:
    query, viz = build_visual_from_selection(
        visual_id="test_bar_tool",
        block_id="process_move_fact",
        metric_names=["queue_time_hr"],
        dimension_names=["tool_dim.tool_id"],
        visual_type=VisualType.bar_chart,
        contracts=contracts,
        semantic_model=semantic_model,
    )
    assert viz.visual_type == VisualType.bar_chart
    assert query.dimensions[0].block_id == "tool_dim"
    assert query.dimensions[0].column_name == "tool_id"
    assert len(query.block_refs) == 2
    assert query.block_refs[1].block_id == "tool_dim"
