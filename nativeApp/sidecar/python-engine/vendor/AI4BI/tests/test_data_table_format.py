"""Round 159: data-table numeric columns must use a VALID Streamlit format.

Regression for the ",d" bug — that is a Python format spec, not a Streamlit
NumberColumn format (printf/preset), so cells rendered the literal text ",d".
"""

from __future__ import annotations

import pandas as pd

from ai4bi.ui.components.data_table import _build_column_config
from ai4bi.query_spec import VisualQuerySpec, BlockRef, MetricRef, DimensionRef

# Streamlit NumberColumn accepts printf strings ("%d", "%.2f", ...) or these presets.
_VALID_PRESETS = {"localized", "plain", "dollar", "euro", "percent",
                  "accounting", "compact", "scientific", "engineering"}


def _metric_format(cfg, col):
    return cfg[col]["type_config"]["format"]


def test_metric_column_format_is_valid_streamlit_format():
    q = VisualQuerySpec(
        "t", [BlockRef("b")],
        metrics=[MetricRef("b", "move_count", "move_count")],
        dimensions=[DimensionRef("b", "tool_id", "tool_id")],
    )
    df = pd.DataFrame({"tool_id": ["ETCH-01"], "move_count": [1234]})
    cfg = _build_column_config(q, df)
    fmt = _metric_format(cfg, "move_count")
    assert fmt != ",d", "',d' is a Python spec; Streamlit renders it literally"
    assert (fmt in _VALID_PRESETS) or fmt.startswith("%"), f"invalid format: {fmt!r}"


def test_float_metric_also_uses_valid_format():
    q = VisualQuerySpec(
        "t", [BlockRef("b")],
        metrics=[MetricRef("b", "avg_queue", "Avg Queue")],
        dimensions=[DimensionRef("b", "tool_id", "tool_id")],
    )
    df = pd.DataFrame({"tool_id": ["ETCH-01"], "avg_queue": [5.37]})
    cfg = _build_column_config(q, df)
    fmt = _metric_format(cfg, "avg_queue")
    assert (fmt in _VALID_PRESETS) or fmt.startswith("%")
