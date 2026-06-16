"""Round 032: Trust Foundation tests — ratio column detection, health check, humanize."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.blocks.contracts import DisaggregationMethod
from ai4bi.ui.upload import classify_df, ColCategory, ColumnClassification, infer_block
from ai4bi.ui.render_visual import humanize_metadata


# ---------------------------------------------------------------------------
# Ratio column detection
# ---------------------------------------------------------------------------

def _df_with_ratios() -> pd.DataFrame:
    return pd.DataFrame({
        "store_id": ["A", "B", "C"],
        "revenue": [1000.0, 2000.0, 1500.0],
        "profit_margin": [0.25, 0.30, 0.22],
        "return_rate": [0.05, 0.03, 0.07],
        "order_count": [100, 200, 150],
        "conversion_rate": [0.12, 0.15, 0.11],
        "sale_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
    })


def test_ratio_columns_use_average_aggregation():
    df = _df_with_ratios()
    contract, metric_names, _ = infer_block(df, "sales", "sales.csv")
    metric_map = {m.name: m for m in contract.metrics}
    assert metric_map["profit_margin"].disaggregation_method == DisaggregationMethod.average
    assert metric_map["return_rate"].disaggregation_method == DisaggregationMethod.average
    assert metric_map["conversion_rate"].disaggregation_method == DisaggregationMethod.average


def test_non_ratio_columns_use_sum_aggregation():
    df = _df_with_ratios()
    contract, _, _ = infer_block(df, "sales", "sales.csv")
    metric_map = {m.name: m for m in contract.metrics}
    assert metric_map["revenue"].disaggregation_method == DisaggregationMethod.sum
    assert metric_map["order_count"].disaggregation_method == DisaggregationMethod.sum


def test_ratio_columns_included_in_metric_names():
    df = _df_with_ratios()
    _, metric_names, _ = infer_block(df, "sales", "sales.csv")
    assert "profit_margin" in metric_names
    assert "return_rate" in metric_names


def test_ratio_column_formula_uses_avg():
    df = _df_with_ratios()
    contract, _, _ = infer_block(df, "sales", "sales.csv")
    metric_map = {m.name: m for m in contract.metrics}
    assert "AVG" in metric_map["profit_margin"].formula.upper()


def test_revenue_formula_uses_sum():
    df = _df_with_ratios()
    contract, _, _ = infer_block(df, "sales", "sales.csv")
    metric_map = {m.name: m for m in contract.metrics}
    assert "SUM" in metric_map["revenue"].formula.upper()


# ---------------------------------------------------------------------------
# classify_df — ColumnClassification
# ---------------------------------------------------------------------------

def test_classify_df_returns_all_columns():
    df = _df_with_ratios()
    result = classify_df(df)
    names = [c.name for c in result]
    for col in df.columns:
        assert col in names


def test_classify_df_ratio_category():
    df = _df_with_ratios()
    result = classify_df(df)
    cat_map = {c.name: c.category for c in result}
    assert cat_map["profit_margin"] == "ratio_metric"
    assert cat_map["return_rate"] == "ratio_metric"
    assert cat_map["conversion_rate"] == "ratio_metric"


def test_classify_df_sum_category():
    df = _df_with_ratios()
    result = classify_df(df)
    cat_map = {c.name: c.category for c in result}
    assert cat_map["revenue"] == "sum_metric"
    assert cat_map["order_count"] == "sum_metric"


def test_classify_df_date_category():
    df = _df_with_ratios()
    result = classify_df(df)
    cat_map = {c.name: c.category for c in result}
    assert cat_map["sale_date"] == "date"


def test_classify_df_dimension_category():
    df = _df_with_ratios()
    result = classify_df(df)
    cat_map = {c.name: c.category for c in result}
    assert cat_map["store_id"] == "primary_key"  # ends in _id


def test_classify_df_sample_field():
    df = pd.DataFrame({"region": ["North", "South"], "revenue": [100.0, 200.0]})
    result = classify_df(df)
    region_cls = next(c for c in result if c.name == "region")
    assert region_cls.sample in ("North", "South")


# ---------------------------------------------------------------------------
# humanize_metadata
# ---------------------------------------------------------------------------

def test_humanize_metadata_none_returns_empty():
    assert humanize_metadata(None) == ""


def test_humanize_metadata_row_count():
    from ai4bi.analysis.executor import ResultMetadata
    meta = ResultMetadata(
        component_id="test",
        row_count=843,
        executed_at="2024-01-15T14:23:00+00:00",
        blocks_used=["sales_fact"],
    )
    result = humanize_metadata(meta)
    assert "843" in result


def test_humanize_metadata_blocks():
    from ai4bi.analysis.executor import ResultMetadata
    meta = ResultMetadata(
        component_id="test",
        row_count=100,
        executed_at="2024-01-15T14:23:00+00:00",
        blocks_used=["orders_fact"],
    )
    result = humanize_metadata(meta)
    assert "orders_fact" in result


def test_humanize_metadata_filters_applied():
    from ai4bi.analysis.executor import ResultMetadata
    meta = ResultMetadata(
        component_id="test",
        row_count=50,
        executed_at="2024-01-15T09:00:00+00:00",
        blocks_used=["sales"],
        filters_applied=["store = 'A'", "month = 2024-01"],
    )
    result = humanize_metadata(meta)
    assert "2" in result  # 2 filters


def test_humanize_metadata_cached():
    from ai4bi.analysis.executor import ResultMetadata
    meta = ResultMetadata(
        component_id="test",
        row_count=200,
        executed_at="2024-01-15T12:00:00+00:00 (cached)",
        blocks_used=["sales"],
    )
    result = humanize_metadata(meta)
    assert "快取" in result


def test_humanize_metadata_time_shown():
    from ai4bi.analysis.executor import ResultMetadata
    meta = ResultMetadata(
        component_id="test",
        row_count=100,
        executed_at="2024-01-15T14:23:55+00:00",
        blocks_used=["sales"],
    )
    result = humanize_metadata(meta)
    assert "14:23:55" in result


# ---------------------------------------------------------------------------
# Executor Arrow cache
# ---------------------------------------------------------------------------

def test_executor_arrow_cache_populated_after_first_query():
    from ai4bi.analysis.executor import Executor
    from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec

    df = pd.DataFrame({"region": ["A", "B"], "revenue": [100.0, 200.0]})
    contract, _, _ = infer_block(df, "cache_test", "test.csv")
    executor = Executor(extra_contracts={"cache_test": contract})

    spec = VisualQuerySpec(
        "kpi_rev",
        [BlockRef("cache_test")],
        metrics=[MetricRef("cache_test", "revenue", "Revenue")],
    )
    executor.run(spec)
    assert "cache_test" in executor._arrow_cache


def test_executor_produces_correct_results_with_ratio_col():
    """Ratio cols use AVG not SUM — verify DuckDB produces expected number."""
    from ai4bi.analysis.executor import Executor
    from ai4bi.query_spec import AggFunction, BlockRef, DimensionRef, MetricRef, VisualQuerySpec

    df = pd.DataFrame({
        "store": ["A", "A", "B"],
        "revenue": [100.0, 200.0, 150.0],
        "profit_margin": [0.20, 0.30, 0.25],
    })
    contract, _, _ = infer_block(df, "stores", "stores.csv")
    executor = Executor(extra_contracts={"stores": contract})

    # Query: total revenue (SUM)
    spec_sum = VisualQuerySpec(
        "kpi_rev",
        [BlockRef("stores")],
        metrics=[MetricRef("stores", "revenue", "Revenue")],
    )
    df_sum = executor.run(spec_sum)
    assert df_sum["Revenue"].iloc[0] == pytest.approx(450.0)

    # Query: avg profit_margin (AVG because ratio)
    spec_avg = VisualQuerySpec(
        "kpi_margin",
        [BlockRef("stores")],
        metrics=[MetricRef("stores", "profit_margin", "Margin")],
    )
    df_avg = executor.run(spec_avg)
    # AVG(0.20, 0.30, 0.25) = 0.25
    assert df_avg["Margin"].iloc[0] == pytest.approx(0.25)
