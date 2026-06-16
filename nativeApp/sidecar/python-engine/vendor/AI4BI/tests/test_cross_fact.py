"""Round 055: cross-fact composition (revenue per employee) wiring."""

from __future__ import annotations

import pytest

from ai4bi.analysis.cross_fact import compose_two_facts, shared_columns
from ai4bi.planning.composition_plan import CompositionPlanningError
from ai4bi.report.retail_template import build_retail_sales_block, build_store_staffing_block


def _contracts():
    return {
        "retail_sales": build_retail_sales_block(),
        "store_staffing": build_store_staffing_block(),
    }


def test_shared_columns_finds_join_key():
    c = _contracts()
    shared = shared_columns(c["retail_sales"], c["store_staffing"])
    assert "store_name" in shared


def test_revenue_per_employee_composition():
    c = _contracts()
    df = compose_two_facts(
        c,
        block_a="retail_sales", agg_a="SUM", col_a="revenue", alias_a="rev",
        block_b="store_staffing", agg_b="SUM", col_b="headcount", alias_b="emp",
        join_key="store_name", ratio_alias="人均營收",
    )
    # one row per store, both metrics present, ratio computed
    assert set(df["store_name"]) <= {
        "台北信義店", "台北西門店", "台中中港店", "高雄三多店", "台南成功店",
    }
    assert "人均營收" in df.columns
    row = df[df["store_name"] == "台北信義店"].iloc[0]
    assert row["人均營收"] == pytest.approx(row["rev"] / row["emp"], rel=1e-3)
    assert row["emp"] == 14


def test_diff_op_subtracts():
    from ai4bi.analysis.cross_fact import combine
    import pandas as pd
    out = combine(pd.Series([100.0, 50.0]), pd.Series([60.0, 20.0]), "diff")
    assert list(out) == [40.0, 30.0]


def test_margin_pct_op():
    from ai4bi.analysis.cross_fact import combine
    import pandas as pd
    out = combine(pd.Series([100.0, 200.0]), pd.Series([60.0, 50.0]), "margin_pct")
    # (100-60)/100*100 = 40 ; (200-50)/200*100 = 75
    assert list(out) == [40.0, 75.0]


def test_compose_margin_pct_end_to_end():
    """Contribution-margin %: revenue (A) vs cost (B) per product."""
    import pandas as pd
    from ai4bi.blocks.contracts import (
        BlockType, ColumnSchema, DataBlockContract, DataClassification,
        DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
    )

    def _blk(bid, col, vals):
        return DataBlockContract(
            block_id=bid, block_type=BlockType.fact, grain="row", version="1.0.0",
            description=bid, primary_keys=[],
            columns=[ColumnSchema(name="product", data_type="string"),
                     ColumnSchema(name=col, data_type="float")],
            metrics=[MetricDefinition(name=col, formula=f"SUM({col})",
                                      disaggregation_method=DisaggregationMethod.sum)],
            data_source=InlineDataSource(records=[
                {"product": "A", col: vals[0]}, {"product": "B", col: vals[1]}]),
            policy=PolicySpec(data_classification=DataClassification.internal),
        )
    contracts = {"rev": _blk("rev", "revenue", [100.0, 200.0]),
                 "cost": _blk("cost", "cost", [60.0, 50.0])}
    df = compose_two_facts(
        contracts,
        block_a="rev", agg_a="SUM", col_a="revenue", alias_a="rev",
        block_b="cost", agg_b="SUM", col_b="cost", alias_b="cost",
        join_key="product", ratio_alias="margin", op="margin_pct",
    ).set_index("product")
    assert df.loc["A", "margin"] == pytest.approx(40.0)
    assert df.loc["B", "margin"] == pytest.approx(75.0)


def test_composition_rejects_three_facts_via_validate():
    # compose_two_facts only ever builds 2 steps; ensure a bad join key is caught
    c = _contracts()
    with pytest.raises(CompositionPlanningError):
        compose_two_facts(
            c,
            block_a="retail_sales", agg_a="SUM", col_a="revenue", alias_a="rev",
            block_b="store_staffing", agg_b="SUM", col_b="headcount", alias_b="emp",
            join_key="nonexistent_column",   # not in group-by ownership → error
        )


def test_demo_registers_staffing_as_second_fact():
    from ai4bi.blocks.contracts import BlockType
    staffing = build_store_staffing_block()
    assert staffing.block_type == BlockType.fact
    assert {m.name for m in staffing.metrics} >= {"headcount", "labor_hours"}
