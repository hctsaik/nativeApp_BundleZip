"""Round 093: cross-page drill-through detail-page builder."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import FilterOperator, VisualType
from ai4bi.report.drillthrough import build_detail_page
from ai4bi.report.models import ExecutableReportSpec, apply_report_proposal
from ai4bi.report.models import ReportChange, ReportProposal
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _contract():
    return build_retail_sales_block()


def test_builds_a_page_filtered_to_value():
    page = build_detail_page(_contract(), "retail_sales", "city", "台北")
    assert page.title == "台北 詳情"
    assert page.visuals  # has visuals
    page.validate()  # visual_order matches visuals
    # every visual carries the single city=台北 filter
    for v in page.visuals.values():
        flts = v.query.filters
        assert any(f.column_name == "city" and f.operator == FilterOperator.eq
                   and f.value == "台北" for f in flts)


def test_layout_has_kpi_trend_and_breakdown():
    page = build_detail_page(_contract(), "retail_sales", "city", "台中")
    types = {v.visualization.visual_type for v in page.visuals.values()}
    assert VisualType.kpi_card in types
    assert VisualType.line_chart in types
    assert VisualType.bar_chart in types


def test_breakdown_uses_a_different_dimension():
    page = build_detail_page(_contract(), "retail_sales", "city", "高雄")
    bars = [v for v in page.visuals.values()
            if v.visualization.visual_type == VisualType.bar_chart]
    assert bars
    dims = bars[0].query.dimensions
    assert dims and dims[0].column_name != "city"


def test_page_id_is_unique_and_safe():
    p1 = build_detail_page(_contract(), "retail_sales", "city", "台北")
    p2 = build_detail_page(_contract(), "retail_sales", "city", "台中")
    assert p1.page_id != p2.page_id
    assert p1.page_id.startswith("detail_")


def test_detail_page_serializes_and_applies_to_report():
    report = build_retail_demo_report()
    page = build_detail_page(_contract(), "retail_sales", "city", "台北")
    proposal = ReportProposal(
        description="drill",
        changes=[ReportChange(path=f"pages/{page.page_id}/delete",
                              label="add", before=None, after=page.to_dict(),
                              affects_data=True)],
    )
    updated = apply_report_proposal(report, proposal)
    assert page.page_id in updated.pages
    # full report still round-trips through serialization
    restored = ExecutableReportSpec.from_dict(updated.to_dict())
    assert page.page_id in restored.pages


def test_detail_visuals_execute_filtered():
    page = build_detail_page(_contract(), "retail_sales", "city", "台北")
    ex = Executor(extra_contracts={"retail_sales": _contract()})
    kpi = next(v for v in page.visuals.values()
               if v.visualization.visual_type == VisualType.kpi_card)
    df = ex.run(kpi.query)
    assert df is not None and not df.empty  # the filtered KPI computes a value
