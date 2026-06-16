"""Round 135: coverage matrix — every Format-pane control that is OFFERED for a
chart type must actually be honored by that chart's renderer.

This guards the whole class of "the toggle is shown but the renderer drops it"
bugs (the reported case: 顯示資料標籤 did nothing on a line chart; legend 位置
was ignored on pies). The (control × visual type) matrix is read from the same
source of truth the UI gates on — ``FORMAT_CONTROL_VTYPES`` — so the two can't
drift: add a control to the mapping and this test fails until the renderer
implements it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.query_spec import MetricRef, VisualizationSpec, VisualType
from ai4bi.ui.format_controls import FORMAT_CONTROL_VTYPES
from ai4bi.ui.components.line_chart import _build_figure as _line_fig
from ai4bi.ui.components.bar_chart import _build_figure as _bar_fig
from ai4bi.ui.components.pie_chart import _build_figure as _pie_fig

# Controls whose effect is visible on the Plotly figure (so a renderer test can
# assert them). "sort" is applied in the query/executor (not the figure) and
# "table" has no Plotly figure, so they're verified elsewhere.
_FIGURE_CONTROLS = {"data_labels", "legend_position", "y_axis", "baseline"}

_MATRIX = [
    (control, vtype)
    for control, vtypes in FORMAT_CONTROL_VTYPES.items()
    if control in _FIGURE_CONTROLS
    for vtype in vtypes
]


def _df() -> pd.DataFrame:
    return pd.DataFrame({"cat": ["A", "B", "C"], "val": [10.0, 20.0, 30.0]})


def _figure(vtype: str, **extra):
    """Build the renderer's Plotly figure for a chart type with `extra` applied.

    Raises if `vtype` is unknown — so any chart type newly added to
    FORMAT_CONTROL_VTYPES must also be wired here, keeping coverage honest.
    """
    style = VisualizationSpec(VisualType(vtype), title="t", extra=extra)
    df = _df()
    if vtype == "line_chart":
        return _line_fig(df, "cat", [MetricRef("b", "val", "val")], style)
    if vtype == "bar_chart":
        return _bar_fig(df, "cat", "val", None, "vertical", "group", style)
    if vtype == "pie_chart":
        return _pie_fig(df, "val", "cat", style)
    raise AssertionError(f"no figure builder wired for vtype={vtype!r}")


def test_matrix_is_non_empty():
    assert len(_MATRIX) >= 6  # guard the guard


@pytest.mark.parametrize("control,vtype", _MATRIX, ids=[f"{c}:{v}" for c, v in _MATRIX])
def test_offered_format_control_is_honored(control: str, vtype: str):
    if control == "data_labels":
        fig = _figure(vtype, data_labels=True)
        if vtype == "pie_chart":
            assert "value" in (fig.data[0].textinfo or ""), f"{vtype} ignores data_labels"
        else:
            assert any(getattr(t, "texttemplate", None) for t in fig.data), \
                f"{vtype} renderer ignores data_labels"

    elif control == "legend_position":
        fig = _figure(vtype, legend_position="right")
        assert fig.layout.legend.orientation == "v", f"{vtype} ignores legend_position"
        fig_hidden = _figure(vtype, legend_position="hide")
        assert fig_hidden.layout.showlegend is False, f"{vtype} ignores legend hide"

    elif control == "y_axis":
        fig = _figure(vtype, y_min=5, y_max=25)
        assert list(fig.layout.yaxis.range) == [5, 25], f"{vtype} ignores Y range"
        fig_log = _figure(vtype, y_scale="log")
        assert fig_log.layout.yaxis.type == "log", f"{vtype} ignores log scale"

    elif control == "baseline":
        # mean of [10,20,30] == 20 → a horizontal line shape at y=20
        fig = _figure(vtype, baseline="mean")
        lines = [s for s in fig.layout.shapes if s.type == "line"]
        assert any(abs((s.y0 or 0) - 20) < 1e-6 for s in lines), \
            f"{vtype} ignores baseline=mean"
        fig_c = _figure(vtype, baseline="custom", baseline_value=7)
        lines_c = [s for s in fig_c.layout.shapes if s.type == "line"]
        assert any(abs((s.y0 or 0) - 7) < 1e-6 for s in lines_c), \
            f"{vtype} ignores baseline=custom"
