"""Round 052: calculated-measure authoring — validation + queryability."""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec
from ai4bi.ui.calc_metric_panel import validate_formula, formula_lineage


def _block() -> DataBlockContract:
    return DataBlockContract(
        block_id="sales",
        block_type=BlockType.fact,
        grain="row per sale",
        version="1.0.0",
        description="sales",
        primary_keys=[],
        columns=[
            ColumnSchema(name="revenue", data_type="float"),
            ColumnSchema(name="cost", data_type="float"),
        ],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum)],
        data_source=InlineDataSource(records=[
            {"revenue": 100.0, "cost": 60.0},
            {"revenue": 200.0, "cost": 100.0},
        ]),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def test_validate_good_formula():
    ok, _ = validate_formula("(revenue - cost) / NULLIF(revenue, 0)", _block())
    assert ok


def test_validate_rejects_unknown_column():
    ok, msg = validate_formula("SUM(profit)", _block())
    assert not ok and "profit" in msg


def test_validate_rejects_injection():
    ok, _ = validate_formula("SUM(revenue); DROP TABLE sales", _block())
    assert not ok


# Round 176: lineage/溯源 is a stated requirement of scenario S10 — pin it.
def test_formula_lineage_lists_referenced_columns():
    cols, metrics = formula_lineage("(revenue - cost) / NULLIF(revenue, 0)", _block())
    assert set(cols) == {"revenue", "cost"}
    assert "revenue" in metrics  # 'revenue' is also a metric name


def test_formula_lineage_uses_word_boundaries_not_substrings():
    b = _block().model_copy(update={
        "columns": [ColumnSchema(name="rev", data_type="float"),
                    ColumnSchema(name="revenue", data_type="float")],
        "metrics": [],
    })
    cols, _ = formula_lineage("SUM(revenue)", b)
    assert "revenue" in cols
    assert "rev" not in cols  # substring of 'revenue' must not falsely match


def test_formula_lineage_empty_when_no_refs():
    cols, metrics = formula_lineage("1 + 2", _block())
    assert cols == [] and metrics == []


def test_authored_measure_is_queryable():
    """A measure authored as the panel does (model_copy append) runs in the executor."""
    contract = _block()
    margin = MetricDefinition(
        name="margin", formula="(SUM(revenue) - SUM(cost)) / NULLIF(SUM(revenue), 0)",
        disaggregation_method=DisaggregationMethod.none, unit="%",
    )
    updated = contract.model_copy(update={"metrics": list(contract.metrics) + [margin]})

    ex = Executor(extra_contracts={"sales": updated})
    spec = VisualQuerySpec("kpi", [BlockRef("sales")],
                           metrics=[MetricRef("sales", "margin", "Margin")])
    df = ex.run(spec)
    # (300 - 160) / 300 = 0.4667
    assert df["Margin"].iloc[0] == pytest.approx(140 / 300)


def test_unicode_metric_name_is_queryable():
    """Chinese-named calc metrics must work (executor quotes the alias)."""
    contract = _block()
    m = MetricDefinition(name="毛利率",
                         formula="(SUM(revenue) - SUM(cost)) / NULLIF(SUM(revenue), 0)",
                         disaggregation_method=DisaggregationMethod.none)
    updated = contract.model_copy(update={"metrics": list(contract.metrics) + [m]})
    ex = Executor(extra_contracts={"sales": updated})
    spec = VisualQuerySpec("k", [BlockRef("sales")],
                           metrics=[MetricRef("sales", "毛利率", "毛利率")])
    df = ex.run(spec)
    assert df["毛利率"].iloc[0] == pytest.approx(140 / 300)
