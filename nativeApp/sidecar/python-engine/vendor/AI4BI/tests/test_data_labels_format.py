"""Round 058: bar data labels + KPI decimals/number-format."""

from __future__ import annotations

import pandas as pd

from ai4bi.ui.components.bar_chart import _build_figure
from ai4bi.ui.components.kpi_card import _fmt_number
from ai4bi.query_spec import VisualizationSpec, VisualType


def _df():
    return pd.DataFrame({"store": ["A", "B"], "rev": [1000.0, 2000.0]})


def _viz(**extra):
    return VisualizationSpec(VisualType.bar_chart, title="t", extra=extra)


# ── Bar data labels ──────────────────────────────────────────────────────────

def test_no_data_labels_by_default():
    fig = _build_figure(_df(), "store", "rev", None, "vertical", "group", _viz())
    assert not getattr(fig.data[0], "texttemplate", None)


def test_data_labels_enabled_vertical():
    fig = _build_figure(_df(), "store", "rev", None, "vertical", "group",
                        _viz(data_labels=True))
    assert fig.data[0].texttemplate == "%{y:,.0f}"


def test_data_labels_horizontal_uses_x_axis():
    fig = _build_figure(_df(), "store", "rev", None, "horizontal", "group",
                        _viz(data_labels=True))
    assert fig.data[0].texttemplate == "%{x:,.0f}"


def test_data_labels_custom_format():
    fig = _build_figure(_df(), "store", "rev", None, "vertical", "group",
                        _viz(data_labels=True, number_format=",.1f"))
    assert fig.data[0].texttemplate == "%{y:,.1f}"


# ── KPI decimals ─────────────────────────────────────────────────────────────

def test_kpi_default_one_decimal():
    assert _fmt_number(1234.0) == "1.2K"


def test_kpi_zero_decimals():
    assert _fmt_number(1234.0, decimals=0) == "1K"
    assert _fmt_number(12.0, decimals=0) == "12"


def test_kpi_two_decimals_with_unit():
    assert _fmt_number(1_500_000.0, "NT$", decimals=2) == "1.50M NT$"


def test_kpi_nan_safe():
    assert _fmt_number(float("nan")) == "—"
