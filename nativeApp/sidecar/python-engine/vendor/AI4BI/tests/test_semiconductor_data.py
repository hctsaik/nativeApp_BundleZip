from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.loader import BlockLoader
from ai4bi.planning.join_planner import QueryPlanningError
from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    SortDirection,
    SortSpec,
    VisualQuerySpec,
)


DATA_DIR = Path(__file__).parent.parent / "data" / "semiconductor_demo"
BLOCKS_DIR = DATA_DIR / "blocks"
BASELINES = json.loads((DATA_DIR / "baselines.json").read_text(encoding="utf-8"))["expected"]

BLOCK_IDS = [
    "calendar_dim",
    "lot_dim",
    "wafer_dim",
    "tool_dim",
    "process_step_dim",
    "foup_dim",
    "process_move_fact",
    "wafer_yield_fact",
]


def _load(block_id: str):
    return BlockLoader().load_json(str(BLOCKS_DIR / f"{block_id}.json"))


class TestSemiconductorContracts:
    @pytest.mark.parametrize("block_id", BLOCK_IDS)
    def test_all_blocks_load_with_existing_contract(self, block_id: str):
        contract = _load(block_id)
        assert contract.block_id == block_id
        assert contract.data_source.source_type == "inline"

    @pytest.mark.parametrize("block_id", BLOCK_IDS)
    def test_records_match_declared_columns_and_primary_keys_are_unique(self, block_id: str):
        contract = _load(block_id)
        declared = {column.name for column in contract.columns}
        records = contract.data_source.records

        assert records
        assert all(set(record) == declared for record in records)

        keys = contract.primary_keys
        identifiers = [tuple(record[key] for key in keys) for record in records]
        assert len(identifiers) == len(set(identifiers))

    def test_semantic_model_marks_fact_to_fact_detail_join_as_prohibited(self):
        model = json.loads((DATA_DIR / "semantic_model.json").read_text(encoding="utf-8"))
        prohibited = {tuple(item["blocks"]) for item in model["prohibited_paths"]}
        assert ("process_move_fact", "wafer_yield_fact") in prohibited
        assert model["runtime_support"]["current_executor"] == "single_fact_with_certified_direct_dimensions"


class TestSemiconductorBaselines:
    def test_basic_fact_counts_match_baseline(self):
        loader = BlockLoader()
        conn = duckdb.connect(database=":memory:")
        try:
            loader.register_to_duckdb(_load("lot_dim"), "lot_dim", conn)
            loader.register_to_duckdb(_load("wafer_dim"), "wafer_dim", conn)
            loader.register_to_duckdb(_load("process_move_fact"), "process_move_fact", conn)
            loader.register_to_duckdb(_load("wafer_yield_fact"), "wafer_yield_fact", conn)

            assert conn.execute("SELECT COUNT(*) FROM lot_dim").fetchone()[0] == BASELINES["total_lots"]
            assert conn.execute("SELECT COUNT(*) FROM wafer_dim").fetchone()[0] == BASELINES["total_wafers"]
            assert conn.execute("SELECT COUNT(*) FROM process_move_fact").fetchone()[0] == BASELINES["total_process_moves"]
            assert conn.execute("SELECT COUNT(*) FROM wafer_yield_fact").fetchone()[0] == BASELINES["total_yield_results"]
            assert conn.execute("SELECT SUM(failed_wafer_count) FROM wafer_yield_fact").fetchone()[0] == BASELINES["failed_wafers"]
        finally:
            conn.close()

    def test_dimension_joins_preserve_move_row_count(self):
        loader = BlockLoader()
        conn = duckdb.connect(database=":memory:")
        try:
            for block_id in [
                "process_move_fact",
                "calendar_dim",
                "lot_dim",
                "wafer_dim",
                "tool_dim",
                "process_step_dim",
                "foup_dim",
            ]:
                loader.register_to_duckdb(_load(block_id), block_id, conn)

            joined_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM process_move_fact m
                LEFT JOIN calendar_dim c ON m.event_date = c.date_id
                LEFT JOIN lot_dim l ON m.lot_id = l.lot_id
                LEFT JOIN wafer_dim w ON m.wafer_id = w.wafer_id
                LEFT JOIN tool_dim t ON m.tool_id = t.tool_id
                LEFT JOIN process_step_dim s ON m.step_id = s.step_id
                LEFT JOIN foup_dim f ON m.foup_id = f.foup_id
                """
            ).fetchone()[0]
            assert joined_count == BASELINES["total_process_moves"]
        finally:
            conn.close()

    def test_etch_queue_time_by_tool_matches_baseline(self):
        loader = BlockLoader()
        conn = duckdb.connect(database=":memory:")
        try:
            loader.register_to_duckdb(_load("process_move_fact"), "process_move_fact", conn)
            rows = conn.execute(
                """
                SELECT tool_id, AVG(queue_time_hr)
                FROM process_move_fact
                WHERE step_id = 'ETCH'
                GROUP BY tool_id
                ORDER BY tool_id
                """
            ).fetchall()
            actual = {tool_id: avg_value for tool_id, avg_value in rows}
            assert actual == pytest.approx(BASELINES["avg_queue_time_hr_by_etch_tool"])
        finally:
            conn.close()

    def test_yield_is_recomputed_from_additive_die_counts(self):
        loader = BlockLoader()
        conn = duckdb.connect(database=":memory:")
        try:
            loader.register_to_duckdb(_load("wafer_yield_fact"), "wafer_yield_fact", conn)
            overall = conn.execute(
                "SELECT SUM(good_die) * 100.0 / SUM(tested_die) FROM wafer_yield_fact"
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT product_family, SUM(good_die) * 100.0 / SUM(tested_die)
                FROM wafer_yield_fact
                GROUP BY product_family
                ORDER BY product_family
                """
            ).fetchall()
            actual = {family: yield_pct for family, yield_pct in rows}

            assert overall == pytest.approx(BASELINES["overall_weighted_yield_pct"])
            assert actual == pytest.approx(BASELINES["weighted_yield_pct_by_product_family"])
        finally:
            conn.close()


class TestSemiconductorCurrentExecutorPath:
    def test_executor_can_render_single_fact_move_trend_inputs(self):
        spec = VisualQuerySpec(
            spec_id="etch_queue_by_tool",
            block_refs=[BlockRef(block_id="process_move_fact")],
            metrics=[
                MetricRef(
                    block_id="process_move_fact",
                    metric_name="queue_time_hr",
                    alias="Average Queue Time",
                    agg_override=AggFunction.avg,
                )
            ],
            dimensions=[DimensionRef(block_id="process_move_fact", column_name="tool_id", alias="Tool")],
            sort=[SortSpec(column_name="Tool", direction=SortDirection.asc)],
        )

        result = Executor(registry_root=BLOCKS_DIR).run(spec)
        actual = dict(zip(result["Tool"], result["Average Queue Time"]))

        assert actual["ETCH-01"] == pytest.approx(2.0)
        assert actual["ETCH-02"] == pytest.approx(4.0)

    def test_executor_joins_certified_tool_dimension_for_etch_breakdown(self):
        spec = VisualQuerySpec(
            spec_id="etch_queue_joined_tool",
            block_refs=[BlockRef("process_move_fact"), BlockRef("tool_dim")],
            metrics=[MetricRef("process_move_fact", "queue_time_hr", "Average Queue Time", AggFunction.avg)],
            dimensions=[DimensionRef("tool_dim", "tool_id", "Tool ID")],
            filters=[FilterSpec("process_move_fact", "step_id", FilterOperator.eq, "ETCH")],
            sort=[SortSpec("Tool ID", SortDirection.asc)],
        )

        result = Executor(registry_root=BLOCKS_DIR).run(spec)
        actual = dict(zip(result["Tool ID"], result["Average Queue Time"]))

        assert actual == pytest.approx(BASELINES["avg_queue_time_hr_by_etch_tool"])

    def test_executor_uses_semantic_key_mapping_for_calendar_join(self):
        spec = VisualQuerySpec(
            spec_id="move_count_by_week",
            block_refs=[BlockRef("process_move_fact"), BlockRef("calendar_dim")],
            metrics=[MetricRef("process_move_fact", "move_count", "Moves")],
            dimensions=[DimensionRef("calendar_dim", "week", "Week")],
        )

        result = Executor(registry_root=BLOCKS_DIR).run(spec)

        assert result["Moves"].sum() == BASELINES["total_process_moves"]

    def test_executor_allows_filter_on_certified_dimension(self):
        spec = VisualQuerySpec(
            spec_id="etch_vendor_filter",
            block_refs=[BlockRef("process_move_fact"), BlockRef("tool_dim")],
            metrics=[MetricRef("process_move_fact", "move_count", "Moves")],
            filters=[
                FilterSpec("process_move_fact", "step_id", FilterOperator.eq, "ETCH"),
                FilterSpec("tool_dim", "vendor", FilterOperator.eq, "DemoVendor-B"),
            ],
        )

        result = Executor(registry_root=BLOCKS_DIR).run(spec)

        assert result["Moves"].iloc[0] == 6

    def test_executor_rejects_fact_to_fact_detail_join(self):
        spec = VisualQuerySpec(
            spec_id="unsafe_detail_join",
            block_refs=[BlockRef("process_move_fact"), BlockRef("wafer_yield_fact")],
            metrics=[MetricRef("process_move_fact", "move_count", "Moves")],
        )

        with pytest.raises(QueryPlanningError, match="Only dimensions"):
            Executor(registry_root=BLOCKS_DIR).run(spec)

    def test_executor_skips_unused_dimension_block(self):
        """Round 163: an unused joined dimension block self-heals (skipped, not
        rejected) — after a UI group-by edit a secondary block can be left
        unreferenced; an unused join can't fan out, so the query still succeeds."""
        spec = VisualQuerySpec(
            spec_id="unused_tool_lineage",
            block_refs=[BlockRef("process_move_fact"), BlockRef("tool_dim")],
            metrics=[MetricRef("process_move_fact", "move_count", "Moves")],
        )

        df = Executor(registry_root=BLOCKS_DIR).run(spec)  # no exception
        assert "Moves" in df.columns
        assert not any("tool" in c.lower() for c in df.columns)  # unused block absent

    def test_executor_rejects_undeclared_ratio_metric(self):
        spec = VisualQuerySpec(
            spec_id="unsafe_yield_average",
            block_refs=[BlockRef("wafer_yield_fact")],
            metrics=[MetricRef("wafer_yield_fact", "yield_pct", "Yield", AggFunction.avg)],
        )

        with pytest.raises(QueryPlanningError, match="not declared"):
            Executor(registry_root=BLOCKS_DIR).run(spec)

    def test_empty_global_selection_returns_no_rows(self):
        spec = VisualQuerySpec(
            spec_id="empty_step_selection",
            block_refs=[BlockRef("process_move_fact")],
            metrics=[MetricRef("process_move_fact", "move_count", "Moves")],
            filters=[
                FilterSpec(
                    "process_move_fact",
                    "step_id",
                    FilterOperator.in_,
                    ["ETCH"],
                    inherit_global_filter=True,
                )
            ],
            inherit_global_filter=True,
        )

        result = Executor(registry_root=BLOCKS_DIR).run(
            spec, {"process_move_fact.step_id": []}
        )

        assert result["Moves"].isna().iloc[0]
