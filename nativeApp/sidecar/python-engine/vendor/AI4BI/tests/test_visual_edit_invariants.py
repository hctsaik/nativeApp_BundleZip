"""Round 163: exhaustive invariant — editing ANY chart's measure or group-by
dimension (as the field-well does) must never crash the query.

This brute-forces the (visual × edit × option) space across both demos so the
whole class of "stale spec after a UI edit" bugs is caught automatically:
  - a sort left referencing a removed measure/dimension column, and
  - a joined secondary block left unused after a group-by change.
Both now self-heal in the executor / join planner; this test guards that.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import VisualType, MetricRef, DimensionRef
from ai4bi.report.retail_template import build_retail_demo_report
from ai4bi.report.templates import build_semiconductor_queue_time_report
import ai4bi.ui.app as app

_CHART_TYPES = {VisualType.line_chart, VisualType.bar_chart,
                VisualType.pie_chart, VisualType.scatter}
_CAT = ("string", "str", "object", "text", "varchar")


def _executor():
    return Executor(registry_root=app._BLOCKS_DIR, semantic_model_path=app._SEMANTIC_MODEL)


def _chart_visuals(report, contracts):
    out = []
    for page in report.pages.values():
        for vid, v in page.visuals.items():
            if v.visualization.visual_type in _CHART_TYPES and v.query.metrics:
                out.append((vid, v))
    return out


def _cases():
    cases = []
    for name, builder in (("retail", build_retail_demo_report),
                          ("semi", build_semiconductor_queue_time_report)):
        report = builder()
        contracts = app._load_all_contracts()
        for vid, v in _chart_visuals(report, contracts):
            fb = v.query.metrics[0].block_id
            c = contracts.get(fb)
            if c is None:
                continue
            for m in getattr(c, "metrics", []) or []:
                cases.append((f"{name}:{vid}:measure={m.name}", report, vid, "measure", m.name))
            for col in getattr(c, "columns", []) or []:
                if getattr(col, "data_type", "") in _CAT and not col.name.lower().endswith("_code"):
                    cases.append((f"{name}:{vid}:dim={col.name}", report, vid, "dim", col.name))
    return cases


_CASES = _cases()


@pytest.mark.parametrize("label,report,vid,kind,value",
                         _CASES, ids=[c[0] for c in _CASES])
def test_visual_edit_never_crashes_query(label, report, vid, kind, value):
    """Applying a measure/dimension edit to a chart must produce a runnable query."""
    page = next(p for p in report.pages.values() if vid in p.visuals)
    v = page.visuals[vid]
    fb = v.query.metrics[0].block_id
    if kind == "measure":
        q = replace(v.query, metrics=[MetricRef(fb, value, value)])
    else:
        q = replace(v.query, dimensions=[DimensionRef(fb, value, value)])
    # Must not raise (executor/join-planner self-heal stale sort + unused blocks)
    _executor().run(q)


def test_there_are_enough_cases():
    # guard the guard: ensure the matrix actually covers multiple charts/options
    assert len(_CASES) >= 10
