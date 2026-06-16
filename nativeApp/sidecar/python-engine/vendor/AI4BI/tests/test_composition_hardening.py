"""
Round 014-B — SQL Hardening + grain_check tests.

Covers:
1. _build_agg_sql() returns (str, list) tuple; list contains filter values
2. CompositionExecutor.run() with filter_values returns correct results
3. SQL injection string in filter_values is safely parameterized (no SQL error)
4. grain_check() returns empty list when join_key is certified
5. grain_check() returns warning when join_key is not in certified_joins
6. CompositionPlanner.plan() with semantic_model=None does not raise
7. CompositionPlanner.plan() with uncertified join returns plan + logs warning
8. ETCH queue vs yield plan produces correct numeric results after parameterization
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from ai4bi.analysis.composition_executor import CompositionExecutor, _build_agg_sql
from ai4bi.blocks.loader import BlockLoader
from ai4bi.planning.composition_plan import (
    AggStep,
    ComposeStep,
    CompositionPlan,
    CompositionPlanner,
    RatioMetricExpr,
    SimpleMetricExpr,
    build_etch_queue_vs_yield_plan,
)
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec


# ---------------------------------------------------------------------------
# Paths & fixtures
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "semiconductor_demo"
BLOCKS_DIR = DATA_DIR / "blocks"
SEMANTIC_MODEL = json.loads(
    (DATA_DIR / "semantic_model.json").read_text(encoding="utf-8")
)

MOVE_BLOCK_PATH = BLOCKS_DIR / "process_move_fact.json"
YIELD_BLOCK_PATH = BLOCKS_DIR / "wafer_yield_fact.json"

loader = BlockLoader()


@pytest.fixture(scope="module")
def contracts():
    return {
        "process_move_fact": loader.load_json(str(MOVE_BLOCK_PATH)),
        "wafer_yield_fact": loader.load_json(str(YIELD_BLOCK_PATH)),
    }


@pytest.fixture(scope="module")
def duckdb_con_with_facts(contracts):
    """In-memory DuckDB connection with both fact tables registered."""
    con = duckdb.connect(database=":memory:")
    loader.register_to_duckdb(contracts["process_move_fact"], "process_move_fact", con)
    loader.register_to_duckdb(contracts["wafer_yield_fact"], "wafer_yield_fact", con)
    yield con
    con.close()


# ---------------------------------------------------------------------------
# Test 1: _build_agg_sql() returns (str, list) and list contains filter values
# ---------------------------------------------------------------------------

class TestBuildAggSqlReturnType:

    def test_returns_tuple_of_str_and_list(self):
        """_build_agg_sql must return a 2-tuple of (str, list)."""
        step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
        )
        result = _build_agg_sql(step, "process_move_fact", "agg_pmf")
        assert isinstance(result, tuple), "Must return a tuple"
        assert len(result) == 2, "Tuple must have exactly 2 elements"
        sql, params = result
        assert isinstance(sql, str), "First element must be a str"
        assert isinstance(params, list), "Second element must be a list"

    def test_no_filter_values_gives_empty_params(self):
        """AggStep with no filter_values must return an empty params list."""
        step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
        )
        _sql, params = _build_agg_sql(step, "process_move_fact", "agg_pmf")
        assert params == [], f"Expected empty params, got {params}"

    def test_filter_values_populate_params_list(self):
        """filter_values dict must produce the correct params list in order."""
        step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
            filter_values={"step_id": ["ETCH", "CVD"]},
        )
        sql, params = _build_agg_sql(step, "process_move_fact", "agg_pmf")
        assert params == ["ETCH", "CVD"], f"Expected ['ETCH', 'CVD'], got {params}"
        # SQL fragment must contain ? placeholders, not the literal values
        assert "?" in sql, "SQL fragment must contain ? placeholders"
        assert "ETCH" not in sql, "Literal values must not appear in SQL fragment"
        assert "CVD" not in sql, "Literal values must not appear in SQL fragment"

    def test_filter_values_placeholder_count_matches_values(self):
        """Number of ? in the SQL must equal the number of filter values."""
        vals = ["LOT-1001", "LOT-1002", "LOT-1003"]
        step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
            filter_values={"lot_id": vals},
        )
        sql, params = _build_agg_sql(step, "process_move_fact", "agg_pmf")
        placeholder_count = sql.count("?")
        assert placeholder_count == len(vals), (
            f"Expected {len(vals)} placeholders, found {placeholder_count}"
        )
        assert params == vals


# ---------------------------------------------------------------------------
# Test 2: CompositionExecutor.run() with filter_values returns correct results
# ---------------------------------------------------------------------------

class TestExecutorRunWithFilterValues:

    def test_filter_values_restricts_rows(self, contracts, duckdb_con_with_facts):
        """
        AggStep with filter_values={"lot_id": ["LOT-1001"]} must return only
        that lot in the composition result.
        """
        move_step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
            filter_values={"lot_id": ["LOT-1001"]},
        )
        yield_step = AggStep(
            block_id="wafer_yield_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[
                RatioMetricExpr("weighted_yield_pct", "good_die", "tested_die")
            ],
        )
        plan = CompositionPlan(
            plan_id="filter-test",
            agg_steps=[move_step, yield_step],
            compose_step=ComposeStep(
                join_key="lot_id",
                left_step_id="process_move_fact",
                right_step_id="wafer_yield_fact",
            ),
            final_metrics=["avg_q", "weighted_yield_pct"],
        )
        plan.validate(contracts)
        executor = CompositionExecutor()
        registered = {
            "process_move_fact": "process_move_fact",
            "wafer_yield_fact": "wafer_yield_fact",
        }
        df = executor.run(plan, duckdb_con_with_facts, registered)
        assert list(df["lot_id"]) == ["LOT-1001"], (
            f"Expected only LOT-1001, got {list(df['lot_id'])}"
        )


# ---------------------------------------------------------------------------
# Test 3: SQL injection string is safely parameterized
# ---------------------------------------------------------------------------

class TestSqlInjectionSafety:

    def test_injection_string_does_not_cause_sql_error(self, contracts):
        """
        A filter value containing a SQL injection payload must be treated as a
        literal value (parameterized), not interpreted as SQL.
        """
        injection_value = "'; DROP TABLE process_move_fact; --"
        move_step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
            filter_values={"step_id": [injection_value]},
        )
        yield_step = AggStep(
            block_id="wafer_yield_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[
                RatioMetricExpr("weighted_yield_pct", "good_die", "tested_die")
            ],
        )
        plan = CompositionPlan(
            plan_id="injection-test",
            agg_steps=[move_step, yield_step],
            compose_step=ComposeStep(
                join_key="lot_id",
                left_step_id="process_move_fact",
                right_step_id="wafer_yield_fact",
            ),
            final_metrics=["avg_q", "weighted_yield_pct"],
        )
        plan.validate(contracts)
        executor = CompositionExecutor(registry_root=BLOCKS_DIR)
        # No step_id in fixture data matches the injection string, so result is empty.
        # Crucially, no exception must be raised — injection is treated as a literal.
        df = executor.run_from_registry(plan, blocks_dir=BLOCKS_DIR)
        # The table must still be accessible (not dropped)
        assert df is not None, "DataFrame must be returned (no SQL error)"
        # Empty result expected (no rows match the injection string as a literal)
        assert len(df) == 0, (
            f"Injection string should match nothing; got {len(df)} rows"
        )

    def test_injection_string_not_in_sql_fragment(self):
        """The SQL fragment itself must NOT contain the injection string."""
        injection_value = "'; DROP TABLE x; --"
        step = AggStep(
            block_id="process_move_fact",
            group_by_columns=["lot_id"],
            metric_exprs=[SimpleMetricExpr("avg_q", "AVG", "queue_time_hr")],
            filter_values={"step_id": [injection_value]},
        )
        sql, params = _build_agg_sql(step, "process_move_fact", "agg_pmf")
        assert injection_value not in sql, (
            "Injection payload must not appear literally in the SQL fragment"
        )
        assert injection_value in params, (
            "Injection payload must be in the params list"
        )


# ---------------------------------------------------------------------------
# Test 4: grain_check() returns empty list when join_key is certified
# ---------------------------------------------------------------------------

class TestGrainCheckCertified:

    CERTIFIED_SM = {
        "certified_joins": [
            {
                "from_block": "process_move_fact",
                "to_block": "wafer_yield_fact",
                "join_key": "lot_id",
                "join_type": "many_to_one",
            }
        ]
    }

    def _make_plan(self) -> CompositionPlan:
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        return CompositionPlan(
            plan_id="grain-test",
            agg_steps=agg_steps,
            compose_step=compose_step,
            final_metrics=["avg_queue_time", "weighted_yield_pct"],
        )

    def test_certified_join_returns_no_warnings(self):
        """grain_check must return [] when the join is in certified_joins."""
        plan = self._make_plan()
        warnings = plan.grain_check(self.CERTIFIED_SM)
        assert warnings == [], f"Expected no warnings, got: {warnings}"

    def test_certified_join_reverse_direction_also_ok(self):
        """Grain check must pass regardless of from_block / to_block direction."""
        reversed_sm = {
            "certified_joins": [
                {
                    "from_block": "wafer_yield_fact",
                    "to_block": "process_move_fact",
                    "join_key": "lot_id",
                    "join_type": "many_to_one",
                }
            ]
        }
        plan = self._make_plan()
        warnings = plan.grain_check(reversed_sm)
        assert warnings == [], f"Expected no warnings for reversed direction, got: {warnings}"


# ---------------------------------------------------------------------------
# Test 5: grain_check() returns warning when join_key is not in certified_joins
# ---------------------------------------------------------------------------

class TestGrainCheckUncertified:

    UNCERTIFIED_SM = {
        "certified_joins": [
            {
                "from_block": "process_move_fact",
                "to_block": "tool_dim",
                "join_key": "tool_id",
                "join_type": "many_to_one",
            }
        ]
    }

    EMPTY_SM: dict = {"certified_joins": []}

    def _make_plan(self) -> CompositionPlan:
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        return CompositionPlan(
            plan_id="uncertified-grain-test",
            agg_steps=agg_steps,
            compose_step=compose_step,
            final_metrics=["avg_queue_time", "weighted_yield_pct"],
        )

    def test_uncertified_join_returns_one_warning(self):
        """grain_check must return a single warning when join not certified."""
        plan = self._make_plan()
        warnings = plan.grain_check(self.UNCERTIFIED_SM)
        assert len(warnings) == 1, f"Expected 1 warning, got {len(warnings)}: {warnings}"

    def test_warning_contains_join_key_and_block_ids(self):
        """Warning message must name the join_key and both block IDs."""
        plan = self._make_plan()
        warnings = plan.grain_check(self.UNCERTIFIED_SM)
        assert len(warnings) == 1
        w = warnings[0]
        assert "lot_id" in w, f"Warning must contain join_key 'lot_id': {w}"
        assert "process_move_fact" in w, f"Warning must contain left block id: {w}"
        assert "wafer_yield_fact" in w, f"Warning must contain right block id: {w}"
        assert "certified_joins" in w, f"Warning must mention certified_joins: {w}"

    def test_empty_certified_joins_returns_warning(self):
        """An empty certified_joins list must trigger a warning."""
        plan = self._make_plan()
        warnings = plan.grain_check(self.EMPTY_SM)
        assert len(warnings) == 1

    def test_no_certified_joins_key_returns_warning(self):
        """Semantic model with no 'certified_joins' key must trigger a warning."""
        plan = self._make_plan()
        warnings = plan.grain_check({})
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Test 6: CompositionPlanner.plan() with semantic_model=None does not raise
# ---------------------------------------------------------------------------

class TestPlannerWithNoSemanticModel:

    def test_plan_with_semantic_model_none_does_not_raise(self, contracts):
        """Passing semantic_model=None must not raise any exception."""
        spec = VisualQuerySpec(
            spec_id="no-sm-test",
            block_refs=[BlockRef("process_move_fact"), BlockRef("wafer_yield_fact")],
            metrics=[
                MetricRef("process_move_fact", "queue_time_hr"),
                MetricRef("wafer_yield_fact", "good_die"),
            ],
        )
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        planner = CompositionPlanner()
        plan = planner.plan(
            spec,
            contracts,
            None,  # semantic_model=None
            agg_steps=agg_steps,
            compose_step=compose_step,
        )
        assert plan is not None

    def test_plan_with_no_semantic_model_arg_does_not_raise(self, contracts):
        """Calling plan() without passing semantic_model at all must not raise."""
        spec = VisualQuerySpec(
            spec_id="no-sm-test-2",
            block_refs=[BlockRef("process_move_fact"), BlockRef("wafer_yield_fact")],
            metrics=[
                MetricRef("process_move_fact", "queue_time_hr"),
                MetricRef("wafer_yield_fact", "good_die"),
            ],
        )
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        planner = CompositionPlanner()
        plan = planner.plan(
            spec,
            contracts,
            agg_steps=agg_steps,
            compose_step=compose_step,
        )
        assert plan is not None


# ---------------------------------------------------------------------------
# Test 7: Planner with uncertified join returns plan (not exception) + warns
# ---------------------------------------------------------------------------

class TestPlannerGrainCheckWarning:

    UNCERTIFIED_SM = {
        "certified_joins": [
            # lot_id is NOT in this list between process_move_fact and wafer_yield_fact
            {
                "from_block": "process_move_fact",
                "to_block": "tool_dim",
                "join_key": "tool_id",
                "join_type": "many_to_one",
            }
        ],
        "prohibited_paths": [],
    }

    def test_uncertified_grain_returns_plan_not_exception(self, contracts, caplog):
        """CompositionPlanner.plan() with uncertified grain must return a plan."""
        import logging

        spec = VisualQuerySpec(
            spec_id="uncertified-grain",
            block_refs=[BlockRef("process_move_fact"), BlockRef("wafer_yield_fact")],
            metrics=[
                MetricRef("process_move_fact", "queue_time_hr"),
                MetricRef("wafer_yield_fact", "good_die"),
            ],
        )
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        planner = CompositionPlanner()
        with caplog.at_level(logging.WARNING):
            plan = planner.plan(
                spec,
                contracts,
                self.UNCERTIFIED_SM,
                agg_steps=agg_steps,
                compose_step=compose_step,
            )
        assert plan is not None, "Plan must be returned (not None) even with grain warning"
        # Confirm warning was logged
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("grain_check" in m for m in warning_msgs), (
            f"Expected grain_check warning in logs. Got: {warning_msgs}"
        )


# ---------------------------------------------------------------------------
# Test 8: ETCH queue vs yield plan produces correct results after parameterization
# ---------------------------------------------------------------------------

class TestEtchQueueVsYieldCorrectness:
    """
    Regression: parameterization must not change numeric results for the
    canonical ETCH queue-time vs weighted-yield plan.
    """

    EXPECTED = {
        "LOT-1001": {"avg_queue_time": 1.75, "weighted_yield_pct": 97.5},
        "LOT-1002": {"avg_queue_time": 2.25, "weighted_yield_pct": 95.0},
        "LOT-1003": {"avg_queue_time": 4.0,  "weighted_yield_pct": 91.15},
    }

    def test_avg_queue_time_matches_baseline_after_parameterization(self):
        """avg_queue_time per lot must match hand-computed values (parameterized path)."""
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        plan = CompositionPlan(
            plan_id="regression-param",
            agg_steps=agg_steps,
            compose_step=compose_step,
            final_metrics=["avg_queue_time", "weighted_yield_pct"],
        )
        executor = CompositionExecutor(registry_root=BLOCKS_DIR)
        df = executor.run_from_registry(plan, blocks_dir=BLOCKS_DIR)

        actual = dict(zip(df["lot_id"], df["avg_queue_time"]))
        for lot_id, expected in self.EXPECTED.items():
            assert actual[lot_id] == pytest.approx(expected["avg_queue_time"], rel=1e-4), (
                f"{lot_id}: expected avg_queue_time={expected['avg_queue_time']}, "
                f"got {actual[lot_id]}"
            )

    def test_weighted_yield_matches_baseline_after_parameterization(self):
        """weighted_yield_pct must be SUM/SUM*100 (parameterized path)."""
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        plan = CompositionPlan(
            plan_id="regression-param-yield",
            agg_steps=agg_steps,
            compose_step=compose_step,
            final_metrics=["avg_queue_time", "weighted_yield_pct"],
        )
        executor = CompositionExecutor(registry_root=BLOCKS_DIR)
        df = executor.run_from_registry(plan, blocks_dir=BLOCKS_DIR)

        actual = dict(zip(df["lot_id"], df["weighted_yield_pct"]))
        for lot_id, expected in self.EXPECTED.items():
            assert actual[lot_id] == pytest.approx(expected["weighted_yield_pct"], rel=1e-4), (
                f"{lot_id}: expected weighted_yield_pct={expected['weighted_yield_pct']}, "
                f"got {actual[lot_id]}"
            )

    def test_three_lots_returned_no_data_loss(self):
        """All 3 lots must be returned — parameterization must not filter data."""
        agg_steps, compose_step = build_etch_queue_vs_yield_plan(join_key="lot_id")
        plan = CompositionPlan(
            plan_id="regression-count",
            agg_steps=agg_steps,
            compose_step=compose_step,
            final_metrics=["avg_queue_time", "weighted_yield_pct"],
        )
        executor = CompositionExecutor(registry_root=BLOCKS_DIR)
        df = executor.run_from_registry(plan, blocks_dir=BLOCKS_DIR)
        assert len(df) == 3, f"Expected 3 lots, got {len(df)}"
