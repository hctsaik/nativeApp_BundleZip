"""Tests for Round 028: self-serve data upload and user report builder."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.blocks.contracts import BlockType, DataBlockContract, InlineDataSource, LifecycleStatus
from ai4bi.ui.upload import infer_block
from ai4bi.report.user_report import build_report_from_block
from ai4bi.query_spec import VisualType


# ---------------------------------------------------------------------------
# infer_block
# ---------------------------------------------------------------------------

def _sales_df() -> pd.DataFrame:
    return pd.DataFrame({
        "order_id": [1, 2, 3, 4, 5],
        "region": ["North", "South", "East", "West", "North"],
        "product": ["A", "B", "A", "C", "B"],
        "revenue": [100.0, 200.0, 150.0, 300.0, 250.0],
        "units": [10, 20, 15, 30, 25],
        "order_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
    })


def test_infer_block_basic():
    df = _sales_df()
    contract, metric_names, dim_names = infer_block(df, "sales", "sales.csv")
    assert contract.block_id == "sales"
    assert contract.block_type == BlockType.fact
    assert contract.block_lifecycle == LifecycleStatus.draft
    # Round 051: uploads use the content-addressed store, not embedded records
    from ai4bi.blocks.contracts import CachedDataSource
    from ai4bi.blocks.datastore import materialize_dataframe
    assert isinstance(contract.data_source, CachedDataSource)
    assert contract.data_source.row_count == 5
    assert len(materialize_dataframe(contract)) == 5


def test_infer_block_detects_metrics():
    df = _sales_df()
    _, metric_names, _ = infer_block(df, "sales", "sales.csv")
    assert "revenue" in metric_names
    assert "units" in metric_names


def test_infer_block_detects_dimensions():
    df = _sales_df()
    _, _, dim_names = infer_block(df, "sales", "sales.csv")
    assert "region" in dim_names
    assert "product" in dim_names


def test_infer_block_id_col_not_a_metric():
    df = _sales_df()
    _, metric_names, _ = infer_block(df, "sales", "sales.csv")
    # order_id has _id suffix — should not be a metric
    assert "order_id" not in metric_names


def test_infer_block_column_schema_matches_df():
    df = _sales_df()
    contract, _, _ = infer_block(df, "sales", "sales.csv")
    col_names = {c.name for c in contract.columns}
    assert col_names == set(df.columns)


def test_infer_block_metric_definitions_in_contract():
    df = _sales_df()
    contract, metric_names, _ = infer_block(df, "sales", "sales.csv")
    contract_metric_names = {m.name for m in contract.metrics}
    for m in metric_names:
        assert m in contract_metric_names


def test_infer_block_date_col_not_metric():
    df = _sales_df()
    _, metric_names, dim_names = infer_block(df, "sales", "sales.csv")
    assert "order_date" not in metric_names
    assert "order_date" in dim_names


def test_infer_block_all_numeric_fallback():
    """When all columns are numeric, we still get at least one metric."""
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    contract, metric_names, _ = infer_block(df, "nums", "nums.csv")
    assert len(metric_names) >= 1


def test_infer_block_slugifies_block_id():
    df = pd.DataFrame({"value": [1, 2, 3]})
    contract, _, _ = infer_block(df, "my_data_2024", "My Data 2024.csv")
    assert contract.block_id == "my_data_2024"


# ---------------------------------------------------------------------------
# build_report_from_block
# ---------------------------------------------------------------------------

def test_build_report_has_kpi_card():
    df = _sales_df()
    contract, metrics, dims = infer_block(df, "sales", "sales.csv")
    report = build_report_from_block(contract, metrics, dims)
    all_visuals = report.pages["main"].visuals
    kpi_visuals = [v for v in all_visuals.values() if v.visualization.visual_type == VisualType.kpi_card]
    assert len(kpi_visuals) >= 1


def test_build_report_has_bar_chart_when_metric_and_dim():
    df = _sales_df()
    contract, metrics, dims = infer_block(df, "sales", "sales.csv")
    report = build_report_from_block(contract, metrics, dims)
    all_visuals = report.pages["main"].visuals
    bar_visuals = [v for v in all_visuals.values() if v.visualization.visual_type == VisualType.bar_chart]
    assert len(bar_visuals) >= 1


def test_build_report_has_table():
    df = _sales_df()
    contract, metrics, dims = infer_block(df, "sales", "sales.csv")
    report = build_report_from_block(contract, metrics, dims)
    all_visuals = report.pages["main"].visuals
    tables = [v for v in all_visuals.values() if v.visualization.visual_type == VisualType.table]
    assert len(tables) >= 1


def test_build_report_visual_order_matches_visuals():
    df = _sales_df()
    contract, metrics, dims = infer_block(df, "sales", "sales.csv")
    report = build_report_from_block(contract, metrics, dims)
    page = report.pages["main"]
    assert set(page.visual_order) == set(page.visuals.keys())


def test_build_report_metrics_only_no_bar_no_table():
    """When there are metrics but no dimensions, only KPI cards are created."""
    df = pd.DataFrame({"revenue": [100.0, 200.0], "units": [10, 20]})
    contract, metrics, dims = infer_block(df, "nums", "nums.csv")
    assert dims == []
    report = build_report_from_block(contract, metrics, dims)
    page = report.pages["main"]
    bar_visuals = [v for v in page.visuals.values() if v.visualization.visual_type == VisualType.bar_chart]
    assert len(bar_visuals) == 0


def test_build_report_title_includes_block_id():
    df = _sales_df()
    contract, metrics, dims = infer_block(df, "sales", "sales.csv")
    report = build_report_from_block(contract, metrics, dims)
    assert "sales" in report.title


# ---------------------------------------------------------------------------
# executor extra_contracts
# ---------------------------------------------------------------------------

def test_executor_extra_contracts_resolves_user_block():
    """Executor should resolve a user-uploaded block from extra_contracts."""
    from ai4bi.analysis.executor import Executor
    from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec

    df = pd.DataFrame({"region": ["A", "B", "A"], "revenue": [100.0, 200.0, 150.0]})
    contract, metrics, dims = infer_block(df, "sales_test", "test.csv")

    executor = Executor(extra_contracts={"sales_test": contract})
    spec = VisualQuerySpec(
        "kpi_test",
        [BlockRef("sales_test")],
        metrics=[MetricRef("sales_test", "revenue", "Revenue")],
    )
    result = executor.run(spec)
    assert not result.empty
    assert "Revenue" in result.columns
    assert result["Revenue"].iloc[0] == pytest.approx(450.0)
