"""Round 103: row-level security — executor injects a parameterized row filter.

Closes the long-standing 'RLS is fake' debt: PolicySpec declared a row filter
the executor never enforced. Now a structured (injection-safe) row_filter is
injected based on the session identity context.
"""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, VisualQuerySpec


def _block() -> DataBlockContract:
    rows = [
        {"city": "台北", "revenue": 100.0},
        {"city": "台北", "revenue": 100.0},
        {"city": "台中", "revenue": 50.0},
        {"city": "高雄", "revenue": 30.0},
    ]
    return DataBlockContract(
        block_id="sales", block_type=BlockType.fact, grain="row", version="1.0.0",
        description="s", primary_keys=[],
        columns=[ColumnSchema(name="city", data_type="string"),
                 ColumnSchema(name="revenue", data_type="float")],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum)],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal,
                          row_filter_column="city", row_filter_identity_key="city"),
    )


def _spec():
    return VisualQuerySpec("t", [BlockRef("sales")],
                           metrics=[MetricRef("sales", "revenue", "營收")])


def test_no_identity_sees_everything():
    ex = Executor(extra_contracts={"sales": _block()})
    df = ex.run(_spec())
    assert df["營收"].iloc[0] == 280.0  # 100+100+50+30


def test_identity_restricts_rows():
    ex = Executor(extra_contracts={"sales": _block()}, identity={"city": "台北"})
    df = ex.run(_spec())
    assert df["營收"].iloc[0] == 200.0  # only 台北's two rows


def test_identity_other_city():
    ex = Executor(extra_contracts={"sales": _block()}, identity={"city": "台中"})
    df = ex.run(_spec())
    assert df["營收"].iloc[0] == 50.0


def test_rls_applies_with_grouping():
    ex = Executor(extra_contracts={"sales": _block()}, identity={"city": "台北"})
    spec = VisualQuerySpec("t", [BlockRef("sales")],
                           metrics=[MetricRef("sales", "revenue", "營收")],
                           dimensions=[DimensionRef("sales", "city", "city")])
    df = ex.run(spec)
    assert set(df["city"]) == {"台北"}  # other cities filtered out entirely


def test_identity_key_absent_no_restriction():
    # identity present but without the policy's key → no RLS filter applied
    ex = Executor(extra_contracts={"sales": _block()}, identity={"role": "admin"})
    df = ex.run(_spec())
    assert df["營收"].iloc[0] == 280.0


def test_rls_value_is_parameterized_not_interpolated():
    # a SQL-injection-style identity value must be treated as a literal (match
    # nothing), never executed
    ex = Executor(extra_contracts={"sales": _block()},
                  identity={"city": "台北' OR '1'='1"})
    import pandas as pd
    df = ex.run(_spec())
    # no row matches the literal string → revenue is NULL/NaN/0, crucially NOT 280
    val = df["營收"].iloc[0]
    assert pd.isna(val) or val == 0.0
