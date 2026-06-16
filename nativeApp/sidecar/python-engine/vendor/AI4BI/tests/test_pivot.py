"""Round 072: matrix / pivot visual."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.query_spec import VisualType
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def test_pivot_registered_in_render_registry():
    from ai4bi.ui.render_visual import _COMPONENT_REGISTRY
    assert VisualType.pivot in _COMPONENT_REGISTRY


def test_retail_demo_has_pivot_visual():
    report = build_retail_demo_report()
    pv = report.pages["main"].visuals["pivot_store_category"]
    assert pv.visualization.visual_type == VisualType.pivot
    assert len(pv.query.dimensions) == 2


def test_pivot_table_pivots_long_to_wide():
    """The component logic: pandas pivot_table turns long [r,c,v] into a wide matrix."""
    df = pd.DataFrame({
        "店": ["A", "A", "B", "B"],
        "類": ["x", "y", "x", "y"],
        "營收": [1.0, 2.0, 3.0, 4.0],
    })
    pv = pd.pivot_table(df, index="店", columns="類", values="營收",
                        aggfunc="sum", fill_value=0, margins=True, margins_name="總計")
    assert pv.loc["A", "x"] == 1.0
    assert pv.loc["B", "y"] == 4.0
    assert pv.loc["總計", "x"] == 4.0   # 1 + 3
    assert pv.loc["A", "總計"] == 3.0   # 1 + 2


def test_nl_add_pivot_creates_two_dim_pivot():
    svc = NL2ProposalService()
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}
    result = svc.propose("加一個樞紐表", report, None, semantic_model={}, contracts=contracts)
    assert result.proposal is not None, f"unsupported: {result.message}"
    after = next(c.after for c in result.proposal.changes if c.path.endswith("/add_visual"))
    assert after["visual"]["visualization"]["visual_type"] == "pivot"
    assert len(after["visual"]["query"]["dimensions"]) == 2
