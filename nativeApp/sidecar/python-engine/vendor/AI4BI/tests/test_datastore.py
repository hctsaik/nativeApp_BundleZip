"""Round 051: content-addressed DataFrame store + CachedDataSource execution."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.blocks import datastore
from ai4bi.blocks.contracts import (
    BlockType, CachedDataSource, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, MetricDefinition, PolicySpec,
)
from ai4bi.blocks.datastore import (
    get_dataframe, has, materialize_dataframe, put_dataframe,
)
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, VisualQuerySpec


@pytest.fixture(autouse=True)
def _clean_store():
    datastore.clear()
    yield
    datastore.clear()


def _df():
    return pd.DataFrame({
        "store": ["A", "A", "B"],
        "revenue": [100.0, 50.0, 30.0],
    })


def test_put_get_roundtrip():
    h = put_dataframe(_df())
    assert has(h)
    pd.testing.assert_frame_equal(get_dataframe(h), _df())


def test_identical_dataframes_dedupe():
    h1 = put_dataframe(_df())
    h2 = put_dataframe(_df())
    assert h1 == h2


def test_different_data_distinct_hash():
    h1 = put_dataframe(_df())
    h2 = put_dataframe(pd.DataFrame({"store": ["C"], "revenue": [1.0]}))
    assert h1 != h2


def test_missing_hash_raises():
    with pytest.raises(KeyError):
        get_dataframe("deadbeef")


def _cached_block() -> DataBlockContract:
    h = put_dataframe(_df())
    return DataBlockContract(
        block_id="sales",
        block_type=BlockType.fact,
        grain="row per sale",
        version="1.0.0",
        description="cached sales",
        primary_keys=[],
        columns=[
            ColumnSchema(name="store", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum)],
        data_source=CachedDataSource(content_hash=h, row_count=3),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def test_materialize_cached_block():
    contract = _cached_block()
    df = materialize_dataframe(contract)
    assert len(df) == 3


def test_executor_runs_cached_data_source():
    """The executor must query a CachedDataSource block exactly like inline."""
    contract = _cached_block()
    ex = Executor(extra_contracts={"sales": contract})
    spec = VisualQuerySpec(
        "kpi", [BlockRef("sales")],
        metrics=[MetricRef("sales", "revenue", "Revenue")],
    )
    df = ex.run(spec)
    assert df["Revenue"].iloc[0] == pytest.approx(180.0)


def test_executor_grouped_cached_data_source():
    ex = Executor(extra_contracts={"sales": _cached_block()})
    spec = VisualQuerySpec(
        "bar", [BlockRef("sales")],
        metrics=[MetricRef("sales", "revenue", "Revenue")],
        dimensions=[DimensionRef("sales", "store", "Store")],
    )
    df = ex.run(spec).set_index("Store")
    assert df.loc["A", "Revenue"] == pytest.approx(150.0)
    assert df.loc["B", "Revenue"] == pytest.approx(30.0)
