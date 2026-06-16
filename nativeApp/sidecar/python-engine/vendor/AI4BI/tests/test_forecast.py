"""Round 074: forecast / projection (future-x + linear extrapolation)."""

from __future__ import annotations

import numpy as np

from ai4bi.ui.components.line_chart import _future_x
from ai4bi.report.retail_template import build_retail_demo_report
from ai4bi.query_spec import VisualType


def test_future_x_extends_weekly_dates():
    xs = ["2026-05-01", "2026-05-08", "2026-05-15"]
    out = _future_x(xs, 2)
    assert out == ["2026-05-22", "2026-05-29"]   # +7 day step continued


def test_future_x_monthly_step():
    xs = ["2026-01-31", "2026-02-28"]
    out = _future_x(xs, 1)
    # step = 28 days → 2026-02-28 + 28 = 2026-03-28
    assert out == ["2026-03-28"]


def test_future_x_non_date_fallback():
    out = _future_x(["A", "B", "C"], 2)
    assert out == ["預測+1", "預測+2"]


def test_linear_extrapolation_continues_upward():
    y = np.array([10.0, 20.0, 30.0])           # slope +10
    coeffs = np.polyfit(np.arange(3), y, 1)
    fut = np.polyval(coeffs, np.arange(3, 5))
    assert list(np.round(fut)) == [40.0, 50.0]


def test_retail_demo_line_has_forecast():
    report = build_retail_demo_report()
    line = report.pages["main"].visuals["line_revenue_trend"]
    tl = line.visualization.extra.get("trend_line")
    assert tl and tl.get("forecast_periods") == 4
