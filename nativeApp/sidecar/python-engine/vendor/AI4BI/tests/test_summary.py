"""Round 050: business summary generator."""

from __future__ import annotations

from datetime import date

from ai4bi.analysis.alerts import AlertRule
from ai4bi.analysis.executor import Executor
from ai4bi.analysis.summary import SummaryReport, generate_summary
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)


def _block() -> DataBlockContract:
    records = []
    d0 = date(2026, 1, 1)
    for i in range(60):
        d = date.fromordinal(d0.toordinal() + i).isoformat()
        # two products; B sells more
        records.append({"order_date": d, "product_name": "A", "revenue": 10.0})
        records.append({"order_date": d, "product_name": "B", "revenue": 25.0})
    return DataBlockContract(
        block_id="sales",
        block_type=BlockType.fact,
        grain="row per product per day",
        version="1.0.0",
        description="sales",
        primary_keys=[],
        columns=[
            ColumnSchema(name="order_date", data_type="date"),
            ColumnSchema(name="product_name", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[MetricDefinition(name="revenue", formula="SUM(revenue)",
                                  disaggregation_method=DisaggregationMethod.sum,
                                  unit="NT$", description="營收")],
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _ex():
    return Executor(extra_contracts={"sales": _block()})


def test_summary_has_headline_and_top_movers():
    report = generate_summary(_ex(), {"sales": _block()}, period="week")
    assert isinstance(report, SummaryReport)
    md = report.to_markdown()
    assert "業務摘要" in md
    assert "營收" in md
    # top movers: B should rank first (25 > 10)
    top_section = next(s for s in report.sections if "前 3 名" in s.heading)
    assert top_section.lines[0].startswith("1. B")


def test_summary_includes_firing_alerts():
    rules = [AlertRule(rule_id="a", block_id="sales", metric_name="revenue",
                       metric_label="營收", operator="gt", threshold=1.0, unit="NT$")]
    report = generate_summary(_ex(), {"sales": _block()}, period="week", alert_rules=rules)
    alert_section = next((s for s in report.sections if s.heading == "提醒"), None)
    assert alert_section is not None
    assert len(alert_section.lines) == 1


def test_preferred_block_is_chosen_over_first():
    from ai4bi.analysis.summary import _first_fact
    other = _block().model_copy(update={"block_id": "other"})
    contracts = {"first": _block(), "other": other}
    chosen = _first_fact(contracts, preferred_block_id="other")
    assert chosen is not None and chosen[0] == "other"


def test_summary_no_fact_block_is_safe():
    report = generate_summary(_ex(), {}, period="week")
    assert isinstance(report, SummaryReport)
    assert report.to_markdown()  # does not raise


def test_retail_demo_summary_generates():
    from ai4bi.report.retail_template import build_retail_sales_block
    block = build_retail_sales_block()
    ex = Executor(extra_contracts={block.block_id: block})
    report = generate_summary(ex, {block.block_id: block}, period="month")
    md = report.to_markdown()
    assert "業務摘要" in md
    assert "前 3 名" in md
