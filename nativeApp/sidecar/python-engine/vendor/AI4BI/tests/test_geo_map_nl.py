"""Round 089: geo-aware NL → map (force a location dimension)."""

from __future__ import annotations

from ai4bi.ai.nl2proposal import NL2ProposalService, _find_location_col
from ai4bi.query_spec import VisualType
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    return NL2ProposalService(), build_retail_demo_report(), {"retail_sales": build_retail_sales_block()}


def _added(proposal):
    for ch in proposal.changes:
        if ch.path.endswith("/add_visual") and ch.after:
            return ch.after["visual"]
    return None


def test_find_location_col():
    assert _find_location_col(build_retail_sales_block()) == "city"


def test_add_map_uses_location_dimension():
    svc, report, contracts = _ctx()
    result = svc.propose("加一張地圖", report, None, semantic_model={}, contracts=contracts)
    assert result.proposal is not None, result.message
    visual = _added(result.proposal)
    assert visual is not None
    assert visual["visualization"]["visual_type"] == "map"
    dims = visual["query"]["dimensions"]
    assert len(dims) >= 1
    assert dims[0]["column_name"] == "city"   # a location, not an arbitrary category


def test_english_add_map():
    svc, report, contracts = _ctx()
    result = svc.propose("add a map", report, None, semantic_model={}, contracts=contracts)
    visual = _added(result.proposal)
    assert visual is not None
    assert visual["visualization"]["visual_type"] == "map"


def test_llm_vtype_map_includes_map():
    from ai4bi.ai.nl2proposal import NL2ProposalService
    # the LLM add_visual path's vtype map must know "map" (regression for the
    # round-5 finding that it was omitted)
    import inspect
    src = inspect.getsource(NL2ProposalService._add_visual_nl)
    assert '"map": VisualType.map' in src or "'map': VisualType.map" in src
