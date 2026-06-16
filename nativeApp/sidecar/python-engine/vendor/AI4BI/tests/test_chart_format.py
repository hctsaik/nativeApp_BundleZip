"""Round 160: chart Format features — Y-axis range/scale, legend, sort patches."""

from __future__ import annotations

import plotly.graph_objects as go

from ai4bi.ui.components.line_chart import _apply_axis_and_legend_format
from ai4bi.report.models import _set_path, _get_path
from ai4bi.report.retail_template import build_retail_demo_report


class _Style:
    def __init__(self, extra):
        self.extra = extra


def test_yaxis_linear_range_applied():
    fig = go.Figure(); fig.add_scatter(x=[1, 2], y=[20, 80])
    _apply_axis_and_legend_format(fig, _Style({"y_min": 10.0, "y_max": 90.0, "y_scale": "linear"}))
    assert tuple(fig.layout.yaxis.range) == (10.0, 90.0)


def test_yaxis_log_scale_uses_log10_range():
    fig = go.Figure(); fig.add_scatter(x=[1, 2], y=[10, 100])
    _apply_axis_and_legend_format(fig, _Style({"y_scale": "log", "y_min": 1.0, "y_max": 1000.0}))
    assert fig.layout.yaxis.type == "log"
    assert tuple(fig.layout.yaxis.range) == (0.0, 3.0)  # log10(1)..log10(1000)


def test_legend_hide_and_position():
    fig = go.Figure(); fig.add_scatter(x=[1], y=[1])
    _apply_axis_and_legend_format(fig, _Style({"legend_position": "hide"}))
    assert fig.layout.showlegend is False
    fig2 = go.Figure(); fig2.add_scatter(x=[1], y=[1])
    _apply_axis_and_legend_format(fig2, _Style({"legend_position": "bottom"}))
    assert fig2.layout.showlegend is True


def _bar_or_line(report):
    pid = next(iter(report.pages))
    vid = next(v for v in report.pages[pid].visuals
               if report.pages[pid].visuals[v].visualization.visual_type.value
               in ("bar_chart", "line_chart"))
    return pid, vid


def test_extra_format_patch_roundtrip():
    rep = build_retail_demo_report()
    pid, vid = _bar_or_line(rep)
    for k, v in [("y_min", 0.0), ("y_max", 50.0), ("y_scale", "log"), ("legend_position", "bottom")]:
        _set_path(rep, f"pages/{pid}/visuals/{vid}/visualization/extra/{k}", v)
    ex = rep.pages[pid].visuals[vid].visualization.extra
    assert ex["y_min"] == 0.0 and ex["y_max"] == 50.0
    assert ex["y_scale"] == "log" and ex["legend_position"] == "bottom"


def test_sort_patch_roundtrip():
    rep = build_retail_demo_report()
    pid, vid = _bar_or_line(rep)
    _set_path(rep, f"pages/{pid}/visuals/{vid}/query/sort",
              [{"column_name": "Revenue", "direction": "asc"}])
    got = _get_path(rep, f"pages/{pid}/visuals/{vid}/query/sort")
    assert got == [{"column_name": "Revenue", "direction": "asc"}]
