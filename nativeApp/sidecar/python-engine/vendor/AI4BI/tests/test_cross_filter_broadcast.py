"""Regression tests for Round 017 cross-filter broadcast."""

from __future__ import annotations

from dataclasses import replace

from ai4bi.query_spec import DimensionRef, FilterOperator
from ai4bi.report.models import query_from_dict, query_to_dict
from ai4bi.report.templates import build_semiconductor_queue_time_report
from ai4bi.ui.app import _apply_cross_filter_to_query


def test_visual_query_round_trip_preserves_cross_filter_emit():
    report = build_semiconductor_queue_time_report()
    query = report.pages["main"].visuals["bar_queue_by_tool_dimension"].query

    restored = query_from_dict(query_to_dict(query))

    assert restored.cross_filter_emit == DimensionRef("tool_dim", "tool_id", "Tool ID")


def test_cache_key_changes_when_cross_filter_emit_changes():
    report = build_semiconductor_queue_time_report()
    query = report.pages["main"].visuals["bar_queue_by_tool_dimension"].query

    changed = replace(
        query,
        cross_filter_emit=DimensionRef("tool_dim", "vendor", "Vendor"),
    )

    assert changed.cache_key() != query.cache_key()


def test_apply_cross_filter_skips_source_visual():
    report = build_semiconductor_queue_time_report()
    query = report.pages["main"].visuals["bar_queue_by_tool_dimension"].query
    payload = {
        "source_spec_id": "bar_queue_by_tool_dimension",
        "block_id": "tool_dim",
        "column_name": "tool_id",
        "value": "ETCH-01",
    }

    updated = _apply_cross_filter_to_query(query, payload, "bar_queue_by_tool_dimension")

    assert updated is query


def test_apply_cross_filter_semantic_match_on_primary_block():
    """Round 044: Cross-filter now uses semantic matching.

    If the cross-filter column (tool_id) exists in the target visual's primary
    block (process_move_fact, which is denormalized and has tool_id), the filter
    IS applied — the KPI responds to the bar chart click.
    """
    from ai4bi.blocks.loader import BlockLoader
    from pathlib import Path

    # Load the semiconductor contracts so semantic matching has schema info
    blocks_dir = Path(__file__).parent.parent / "data" / "semiconductor_demo" / "blocks"
    loader = BlockLoader()
    contracts = {}
    if blocks_dir.exists():
        for path in blocks_dir.glob("*.json"):
            try:
                c = loader.load_json(str(path))
                contracts[c.block_id] = c
            except Exception:
                pass

    report = build_semiconductor_queue_time_report()
    query = report.pages["main"].visuals["kpi_move_count"].query
    payload = {
        "source_spec_id": "bar_queue_by_tool_dimension",
        "block_id": "tool_dim",
        "column_name": "tool_id",
        "value": "ETCH-01",
    }

    updated = _apply_cross_filter_to_query(query, payload, "kpi_move_count", contracts=contracts)

    # Round 044: filter IS applied because process_move_fact has tool_id column
    assert updated is not query
    injected = updated.filters[-1]
    assert injected.column_name == "tool_id"
    assert injected.value == ["ETCH-01"]


def test_apply_cross_filter_appends_filter_for_compatible_target():
    report = build_semiconductor_queue_time_report()
    query = report.pages["main"].visuals["table_queue_by_tool_dimension"].query
    payload = {
        "source_spec_id": "bar_queue_by_tool_dimension",
        "block_id": "tool_dim",
        "column_name": "tool_id",
        "value": "ETCH-01",
    }

    updated = _apply_cross_filter_to_query(query, payload, "table_queue_by_tool_dimension")

    assert updated is not query
    injected = updated.filters[-1]
    assert injected.block_id == "tool_dim"
    assert injected.column_name == "tool_id"
    assert injected.operator == FilterOperator.in_
    assert injected.value == ["ETCH-01"]
    assert injected.inherit_global_filter is False


def test_apply_cross_filter_replaces_existing_same_key_filter():
    report = build_semiconductor_queue_time_report()
    query = report.pages["main"].visuals["table_queue_by_tool_dimension"].query
    first = _apply_cross_filter_to_query(
        query,
        {
            "source_spec_id": "bar_queue_by_tool_dimension",
            "block_id": "tool_dim",
            "column_name": "tool_id",
            "value": "ETCH-01",
        },
        "table_queue_by_tool_dimension",
    )

    second = _apply_cross_filter_to_query(
        first,
        {
            "source_spec_id": "bar_queue_by_tool_dimension",
            "block_id": "tool_dim",
            "column_name": "tool_id",
            "value": "ETCH-02",
        },
        "table_queue_by_tool_dimension",
    )

    matching = [
        filter_spec
        for filter_spec in second.filters
        if filter_spec.block_id == "tool_dim" and filter_spec.column_name == "tool_id"
    ]
    assert len(matching) == 1
    assert matching[0].value == ["ETCH-02"]
