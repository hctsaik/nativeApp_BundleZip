"""Tests for Round 031: AI chart suggestions engine."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.ai.suggestions import ChartSuggestion, generate_suggestions
from ai4bi.query_spec import VisualType
from ai4bi.ui.upload import infer_block


def _sales_contracts():
    df = pd.DataFrame({
        "order_id": [1, 2, 3, 4, 5],
        "region": ["North", "South", "East", "West", "North"],
        "product": ["A", "B", "A", "C", "B"],
        "channel": ["Online", "Store", "Online", "Store", "Online"],
        "revenue": [100.0, 200.0, 150.0, 300.0, 250.0],
        "units": [10, 20, 15, 30, 25],
        "order_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
    })
    contract, _, _ = infer_block(df, "sales", "sales.csv")
    return {"sales": contract}


def test_suggestions_returns_list():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    assert isinstance(result, list)
    assert len(result) > 0


def test_smart_suggestions_present_and_buildable():
    """Round 185: with date + ≥2 categories + ≥2 metrics, the generator offers the
    'smart' analyses (Pareto / moving-average / forecast / pivot / small-multiples)
    on top of the basic charts — and every suggestion builds without error."""
    from ai4bi.report.builder import build_visual_from_selection
    contracts = _sales_contracts()  # has order_date + region/product/channel + revenue/units
    sgs = generate_suggestions(contracts)
    titles = " ".join(s.title for s in sgs)
    assert "柏拉圖" in titles and "移動平均" in titles and "預測" in titles
    assert any(s.visual_type is VisualType.pivot for s in sgs)
    assert any(s.visual_type is VisualType.small_multiples for s in sgs)
    # the analytics ones carry an `extra` (postprocess / trend_line) config
    assert any(s.extra and "postprocess" in s.extra for s in sgs)        # Pareto / MA
    assert any(s.extra and "trend_line" in s.extra for s in sgs)         # forecast
    # every suggestion (incl. 2-dim pivot / small-multiples + extra) must build
    for i, s in enumerate(sgs):
        dims = [d for d in (s.dimension_name, s.second_dimension_name) if d]
        q, v = build_visual_from_selection(
            f"sg{i}", s.block_id, [s.metric_name], dims, s.visual_type, contracts, None)
        if s.extra:
            v.extra = {**(v.extra or {}), **s.extra}
            assert v.extra  # config carried onto the visualization


def test_suggestions_max_cap():
    # Round 185: cap raised 6 → 12 (added Pareto / moving-avg / forecast / pivot /
    # small-multiples "smart" suggestions on top of the basic charts).
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    assert len(result) <= 12


def test_suggestions_have_required_fields():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    for s in result:
        assert isinstance(s, ChartSuggestion)
        assert s.block_id
        assert s.metric_name
        assert s.visual_type in VisualType.__members__.values()
        assert s.title
        assert s.reason


def test_suggestions_include_kpi_card():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    types = [s.visual_type for s in result]
    assert VisualType.kpi_card in types


def test_suggestions_include_line_chart_for_date_data():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    types = [s.visual_type for s in result]
    assert VisualType.line_chart in types


def test_suggestions_include_bar_chart_for_categorical_data():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    types = [s.visual_type for s in result]
    assert VisualType.bar_chart in types


def test_suggestions_empty_for_no_metrics():
    df = pd.DataFrame({"category": ["A", "B"], "name": ["X", "Y"]})
    contract, _, _ = infer_block(df, "dims", "dims.csv")
    result = generate_suggestions({"dims": contract})
    # No metrics means no suggestions
    assert all(s.block_id != "dims" for s in result)


def test_suggestions_kpi_has_no_dimension():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    kpi_suggestions = [s for s in result if s.visual_type == VisualType.kpi_card]
    for s in kpi_suggestions:
        assert s.dimension_name is None


def test_suggestions_line_chart_has_date_dimension():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    line_suggestions = [s for s in result if s.visual_type == VisualType.line_chart]
    for s in line_suggestions:
        assert s.dimension_name is not None
        assert "date" in s.dimension_name.lower() or "time" in s.dimension_name.lower()


def test_suggestions_metric_names_valid_in_contract():
    contracts = _sales_contracts()
    contract = contracts["sales"]
    valid_metric_names = {m.name for m in contract.metrics}
    result = generate_suggestions(contracts)
    for s in result:
        if s.block_id == "sales":
            assert s.metric_name in valid_metric_names


def test_suggestions_unique_titles():
    contracts = _sales_contracts()
    result = generate_suggestions(contracts)
    titles = [s.title for s in result]
    assert len(titles) == len(set(titles))


def test_suggestions_no_suggestions_for_dimension_blocks():
    """Dimension blocks (non-fact) should not generate suggestions."""
    from ai4bi.blocks.contracts import BlockType, DataBlockContract, InlineDataSource, PolicySpec, DataClassification, ColumnSchema
    dim_contract = DataBlockContract(
        block_id="region_dim",
        block_type=BlockType.dimension,
        grain="one row per region",
        columns=[ColumnSchema(name="region_id", data_type="string"),
                 ColumnSchema(name="region_name", data_type="string")],
        metrics=[],
        data_source=InlineDataSource(records=[{"region_id": "1", "region_name": "North"}]),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    result = generate_suggestions({"region_dim": dim_contract})
    assert len(result) == 0
