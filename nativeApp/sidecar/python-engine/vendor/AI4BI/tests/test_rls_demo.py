"""Round 106: the retail demo block enforces row-level security by city."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec
from ai4bi.report.retail_template import build_retail_sales_block


def _total_spec():
    return VisualQuerySpec("t", [BlockRef("retail_sales")],
                           metrics=[MetricRef("retail_sales", "revenue", "營收")])


def test_demo_policy_declares_row_filter():
    block = build_retail_sales_block()
    assert block.policy.row_filter_column == "city"
    assert block.policy.row_filter_identity_key == "city"


def test_admin_sees_all_cities():
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()})
    full = ex.run(_total_spec())["營收"].iloc[0]
    assert full > 0
    # scoped to one city must be strictly less than the full total
    ex_tpe = Executor(extra_contracts={"retail_sales": build_retail_sales_block()},
                      identity={"city": "台北"})
    tpe = ex_tpe.run(_total_spec())["營收"].iloc[0]
    assert 0 < tpe < full


def test_scope_excludes_other_cities():
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()},
                  identity={"city": "台北"})
    from ai4bi.query_spec import DimensionRef
    spec = VisualQuerySpec("t", [BlockRef("retail_sales")],
                           metrics=[MetricRef("retail_sales", "revenue", "營收")],
                           dimensions=[DimensionRef("retail_sales", "city", "city")])
    df = ex.run(spec)
    assert set(df["city"]) == {"台北"}
