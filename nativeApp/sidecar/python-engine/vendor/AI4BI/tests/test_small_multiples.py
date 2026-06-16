"""Round 094: small multiples (trellis / faceted grid)."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _ADD_VISUAL_TYPE_KEYWORDS
from ai4bi.query_spec import (
    BlockRef, DimensionRef, MetricRef, VisualQuerySpec, VisualType,
)
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block
from ai4bi.ui.components.small_multiples import choose_facet_layout


def test_keywords_route_to_small_multiples():
    assert _ADD_VISUAL_TYPE_KEYWORDS["小倍數"] == VisualType.small_multiples
    assert _ADD_VISUAL_TYPE_KEYWORDS["small multiples"] == VisualType.small_multiples


def test_registered_in_component_registry():
    from ai4bi.ui.render_visual import _COMPONENT_REGISTRY
    assert VisualType.small_multiples in _COMPONENT_REGISTRY


def test_choose_facet_layout_two_dims():
    spec = VisualQuerySpec(
        "sm", [BlockRef("b")],
        metrics=[MetricRef("b", "revenue", "營收")],
        dimensions=[DimensionRef("b", "category", "category"),
                    DimensionRef("b", "order_date", "order_date")],
    )
    df = pd.DataFrame({"category": ["A", "A", "B"], "order_date": [1, 2, 1], "營收": [10, 20, 5]})
    facet, x, y = choose_facet_layout(spec, df)
    assert facet == "category"
    assert x == "order_date"
    assert y == "營收"


def test_choose_facet_layout_single_dim_has_no_x():
    spec = VisualQuerySpec(
        "sm", [BlockRef("b")],
        metrics=[MetricRef("b", "revenue", "營收")],
        dimensions=[DimensionRef("b", "category", "category")],
    )
    df = pd.DataFrame({"category": ["A", "B"], "營收": [10, 5]})
    facet, x, y = choose_facet_layout(spec, df)
    assert facet == "category" and x is None and y == "營收"


def test_choose_facet_layout_none_without_dim():
    spec = VisualQuerySpec("sm", [BlockRef("b")],
                           metrics=[MetricRef("b", "revenue", "營收")])
    df = pd.DataFrame({"營收": [10]})
    assert choose_facet_layout(spec, df) is None


def test_nl_add_small_multiples_builds_faceted_query():
    svc = NL2ProposalService()
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}
    result = svc.propose("加一張小倍數圖", report, None, semantic_model={}, contracts=contracts)
    assert result.proposal is not None, result.message
    added = next((c.after for c in result.proposal.changes if c.path.endswith("/add_visual")), None)
    assert added is not None
    assert added["visual"]["visualization"]["visual_type"] == "small_multiples"
    # facet + time dimension
    assert len(added["visual"]["query"]["dimensions"]) == 2
