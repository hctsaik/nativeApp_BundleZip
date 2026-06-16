"""Round 048: threshold alert evaluation."""

from __future__ import annotations

from ai4bi.analysis.alerts import AlertRule, evaluate_alerts, firing_alerts
from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
)


def _block() -> DataBlockContract:
    records = [
        {"store": "A", "revenue": 100.0},
        {"store": "A", "revenue": 50.0},
        {"store": "B", "revenue": 30.0},
    ]
    return DataBlockContract(
        block_id="sales",
        block_type=BlockType.fact,
        grain="one row per sale",
        version="1.0.0",
        description="sales",
        primary_keys=[],
        columns=[
            ColumnSchema(name="store", data_type="string"),
            ColumnSchema(name="revenue", data_type="float"),
        ],
        metrics=[
            MetricDefinition(name="revenue", formula="SUM(revenue)",
                             disaggregation_method=DisaggregationMethod.sum,
                             unit="NT$", description="營收"),
        ],
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )


def _ex():
    return Executor(extra_contracts={"sales": _block()})


def _rule(op: str, threshold: float, **kw) -> AlertRule:
    return AlertRule(
        rule_id="r1", block_id="sales", metric_name="revenue",
        metric_label="營收", operator=op, threshold=threshold, unit="NT$", **kw,
    )


def test_alert_fires_when_below_threshold():
    # total revenue = 180; threshold 200; lt → fires
    results = evaluate_alerts(_ex(), [_rule("lt", 200)])
    assert results[0].fired
    assert results[0].value == 180.0
    assert "🔔" in results[0].message


def test_alert_does_not_fire_when_above_threshold():
    results = evaluate_alerts(_ex(), [_rule("lt", 100)])
    assert not results[0].fired
    assert results[0].message == ""


def test_gt_alert_fires():
    results = evaluate_alerts(_ex(), [_rule("gt", 100)])  # 180 > 100
    assert results[0].fired


def test_scoped_alert_filters_by_dimension():
    # store A revenue = 150 ; threshold 200 lt → fires
    rule = _rule("lt", 200, filter_column="store", filter_value="A")
    fired = firing_alerts(_ex(), [rule])
    assert len(fired) == 1
    assert fired[0].value == 150.0


def test_describe_is_human_readable():
    assert _rule("lt", 100000).describe() == "營收 低於 100,000 NT$"


def test_broken_rule_does_not_raise():
    bad = AlertRule(rule_id="bad", block_id="sales", metric_name="nonexistent",
                    metric_label="X", operator="lt", threshold=1)
    results = evaluate_alerts(_ex(), [bad])
    assert results[0].value is None
    assert not results[0].fired
