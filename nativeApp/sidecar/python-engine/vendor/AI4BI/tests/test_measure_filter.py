"""Round 080: NL measure-filter → HAVING, end-to-end.

Makes the R079 HAVING engine reachable: "營收超過 100000 的地區",
"revenue over 100000" become a post-aggregate measure filter on a visual,
serialized + applied + re-executed.
"""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import (
    NL2ProposalService, _looks_like_measure_filter, _extract_measure_filter,
)
from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import FilterOperator
from ai4bi.report.models import apply_report_proposal, query_from_dict, query_to_dict
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block

_TARGET = "bar_revenue_by_store"  # revenue grouped by city — grouped+aggregated


def _ctx():
    return NL2ProposalService(), build_retail_demo_report(), {"retail_sales": build_retail_sales_block()}


def test_detector_requires_comparison_and_number():
    assert _looks_like_measure_filter("營收超過 100000 的地區", "營收超過 100000 的地區")
    assert _looks_like_measure_filter("revenue over 100000", "revenue over 100000")
    # comparison word but no number → not a measure filter
    assert not _looks_like_measure_filter("營收最高的地區", "營收最高的地區")
    # number but no comparison → not a measure filter
    assert not _looks_like_measure_filter("2026 年的營收", "2026 年的營收")


def test_proposal_adds_having_predicate():
    svc, report, contracts = _ctx()
    result = svc.propose("營收超過 100000 的地區", report, _TARGET, contracts=contracts)
    assert result.proposal is not None, result.message
    ch = next(c for c in result.proposal.changes if c.path.endswith("/query/having"))
    assert len(ch.after) == 1
    h = ch.after[0]
    assert h["metric_name"] == "revenue"
    assert h["operator"] == "gt"
    assert h["value"] == 100000


def test_english_phrasing_and_default_metric():
    svc, report, contracts = _ctx()
    # No explicit metric word, single projected metric → defaults to it (revenue).
    result = svc.propose("show regions over 100000", report, _TARGET, contracts=contracts)
    assert result.proposal is not None, result.message
    h = next(c for c in result.proposal.changes if c.path.endswith("/query/having")).after[0]
    assert h["metric_name"] == "revenue"
    assert h["operator"] == "gt"


def test_apply_then_execute_filters_groups():
    svc, report, contracts = _ctx()
    result = svc.propose("營收超過 100000 的地區", report, _TARGET, contracts=contracts)
    applied = apply_report_proposal(report, result.proposal)

    visual = applied.pages["main"].visuals[_TARGET]
    assert len(visual.query.having) == 1
    assert visual.query.having[0].operator == FilterOperator.gt

    ex = Executor(extra_contracts=contracts)
    df = ex.run(visual.query)
    # Every returned region's revenue must exceed the threshold.
    assert not df.empty
    assert (df["營收"] > 100000).all()


def test_below_threshold_operator():
    svc, report, contracts = _ctx()
    result = svc.propose("營收低於 50000 的地區", report, _TARGET, contracts=contracts)
    h = next(c for c in result.proposal.changes if c.path.endswith("/query/having")).after[0]
    assert h["operator"] == "lt"
    assert h["value"] == 50000


def test_having_survives_serialization_roundtrip():
    svc, report, contracts = _ctx()
    result = svc.propose("營收至少 80000 的地區", report, _TARGET, contracts=contracts)
    applied = apply_report_proposal(report, result.proposal)
    q = applied.pages["main"].visuals[_TARGET].query

    restored = query_from_dict(query_to_dict(q))
    assert len(restored.having) == 1
    assert restored.having[0].metric_name == "revenue"
    assert restored.having[0].operator == FilterOperator.gte
    assert restored.having[0].value == 80000


def test_extract_returns_projected_metric():
    _, report, _ = _ctx()
    visual = build_retail_demo_report().pages["main"].visuals[_TARGET]
    parsed = _extract_measure_filter("營收超過 100000", "營收超過 100000", visual)
    assert parsed is not None
    metric, op, value = parsed
    assert metric.metric_name == "revenue"
    assert op == FilterOperator.gt
    assert value == 100000
