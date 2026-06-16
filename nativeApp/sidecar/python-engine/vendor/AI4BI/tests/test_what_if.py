"""Round 060: what-if parameter substitution in derived formulas."""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor, _build_derived_formula_expr
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.planning.join_planner import QueryPlanningError
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec


def _block() -> DataBlockContract:
    return DataBlockContract(
        block_id="sales", block_type=BlockType.fact, grain="row", version="1.0.0",
        description="s", primary_keys=[],
        columns=[ColumnSchema(name="revenue", data_type="float")],
        metrics=[
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum),
            # discounted revenue uses a what-if parameter @discount
            MetricDefinition(name="discounted", formula="SUM(revenue) * (1 - @discount)",
                             disaggregation_method=DisaggregationMethod.none),
        ],
        data_source=InlineDataSource(records=[{"revenue": 100.0}, {"revenue": 200.0}]),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def test_formula_substitutes_parameter_value():
    expr = _build_derived_formula_expr(
        "SUM(revenue) * (1 - @discount)", "sales", {"revenue"}, parameters={"discount": 0.2}
    )
    assert "0.2" in expr
    assert "@" not in expr            # parameter fully resolved


def test_undefined_parameter_raises():
    with pytest.raises(QueryPlanningError):
        _build_derived_formula_expr("SUM(revenue) * @x", "sales", {"revenue"}, parameters={})


def test_executor_applies_parameter():
    ex = Executor(extra_contracts={"sales": _block()}, parameters={"discount": 0.25})
    spec = VisualQuerySpec("k", [BlockRef("sales")],
                           metrics=[MetricRef("sales", "discounted", "折後")])
    df = ex.run(spec)
    # total 300 * (1 - 0.25) = 225
    assert df["折後"].iloc[0] == pytest.approx(225.0)


def test_changing_parameter_changes_result():
    spec = VisualQuerySpec("k", [BlockRef("sales")],
                           metrics=[MetricRef("sales", "discounted", "折後")])
    r10 = Executor(extra_contracts={"sales": _block()}, parameters={"discount": 0.1}).run(spec)
    r50 = Executor(extra_contracts={"sales": _block()}, parameters={"discount": 0.5}).run(spec)
    assert r10["折後"].iloc[0] == pytest.approx(270.0)
    assert r50["折後"].iloc[0] == pytest.approx(150.0)


def test_parameter_injection_is_neutralized():
    """A parameter value is inlined as a numeric literal; non-numeric → error, no SQL."""
    with pytest.raises((QueryPlanningError, ValueError, TypeError)):
        _build_derived_formula_expr(
            "SUM(revenue) * @x", "sales", {"revenue"},
            parameters={"x": "1); DROP TABLE sales --"},  # not a float
        )
