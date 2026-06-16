"""Round 059: distribution histogram (raw values + value-column resolution)."""

from __future__ import annotations

import pandas as pd

from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import BlockRef, DimensionRef, VisualizationSpec, VisualType, VisualQuerySpec
from ai4bi.report.retail_template import build_retail_sales_block
from ai4bi.ui.components.histogram import _value_column


def test_value_column_prefers_declared_dimension():
    df = pd.DataFrame({"revenue": [1.0, 2.0], "store": ["A", "B"]})
    spec = VisualQuerySpec("h", [BlockRef("b")],
                           dimensions=[DimensionRef("b", "revenue", "revenue")])
    assert _value_column(spec, df) == "revenue"


def test_value_column_falls_back_to_numeric():
    df = pd.DataFrame({"store": ["A"], "amount": [5.0]})
    spec = VisualQuerySpec("h", [BlockRef("b")])
    assert _value_column(spec, df) == "amount"


def test_value_column_none_when_no_numeric():
    df = pd.DataFrame({"store": ["A", "B"]})
    spec = VisualQuerySpec("h", [BlockRef("b")])
    assert _value_column(spec, df) is None


def test_histogram_query_returns_raw_unaggregated_values():
    """A single-dimension, no-metric query must return one row per source row."""
    block = build_retail_sales_block()
    ex = Executor(extra_contracts={block.block_id: block})
    spec = VisualQuerySpec(
        "hist", [BlockRef(block.block_id)],
        dimensions=[DimensionRef(block.block_id, "revenue", "revenue")],
        metrics=[],
    )
    df = ex.run(spec)
    # raw values → far more than the handful of distinct group rows
    assert len(df) > 100
    assert "revenue" in df.columns


def test_retail_demo_has_histogram_visual():
    from ai4bi.report.retail_template import build_retail_demo_report
    report = build_retail_demo_report()
    hist = report.pages["main"].visuals["hist_revenue"]
    assert hist.visualization.extra.get("chart_mode") == "histogram"
