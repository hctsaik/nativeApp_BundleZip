"""Round 065: NL2 'add a <chart>' creates a new visual (keyword mode).

Reproduces the user-reported bug: "加一個 pie chart" returned "no supported intent".
"""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_add_visual
from ai4bi.query_spec import VisualType
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}
    return NL2ProposalService(), report, contracts


def _added_visual_type(proposal):
    """Extract the VisualType.value of the visual an add_visual proposal creates."""
    for ch in proposal.changes:
        if ch.path.endswith("/add_visual") and ch.after:
            return ch.after["visual"]["visualization"]["visual_type"]
    return None


@pytest.mark.parametrize("prompt,expected", [
    ("加一個 pie chart", "pie_chart"),
    ("新增圓餅圖", "pie_chart"),
    ("add a bar chart", "bar_chart"),
    ("加一個折線圖", "line_chart"),
    ("建立一個散точ圖".replace("точ", "點"), "scatter"),
    ("加一個 KPI", "kpi_card"),
    ("新增一個看板", "kpi_card"),
    ("加一個表格", "table"),
])
def test_add_visual_creates_requested_type(prompt, expected):
    svc, report, contracts = _ctx()
    result = svc.propose(prompt, report, None, semantic_model={}, contracts=contracts)
    assert result.proposal is not None, f"got unsupported: {result.message}"
    assert _added_visual_type(result.proposal) == expected


def test_detector_distinguishes_add_from_change():
    assert _looks_like_add_visual("加一個 pie chart", "加一個 pie chart")
    # 'change to pie' is a chart-type change, NOT add
    assert not _looks_like_add_visual("change to pie chart", "change to pie chart")
    assert not _looks_like_add_visual("改成圓餅圖", "改成圓餅圖")


def test_added_pie_has_a_dimension():
    """A pie chart needs a slice dimension — the handler must attach one."""
    svc, report, contracts = _ctx()
    result = svc.propose("加一個 pie chart", report, None, semantic_model={}, contracts=contracts)
    after = next(c.after for c in result.proposal.changes if c.path.endswith("/add_visual"))
    assert len(after["visual"]["query"]["dimensions"]) >= 1
