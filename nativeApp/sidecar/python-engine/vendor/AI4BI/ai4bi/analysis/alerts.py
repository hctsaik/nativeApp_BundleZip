"""Threshold alerts — Round 048.

Lets a non-technical owner say "tell me when revenue drops below X" without
writing code. An alert is a rule on a metric; rules are evaluated against the
current data on every page render and firing rules surface as a banner.

There is no background scheduler in the Streamlit MVP, so "notification" means
"shown at the top of the dashboard when the condition is currently true". The
rule model and evaluation are kept pure so a future scheduler/email job
(Round 050) can reuse evaluate_alerts() unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ai4bi.query_spec import (
    BlockRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    VisualQuerySpec,
)

# operator key → (display verb, comparator)
_OPERATORS = {
    "lt": "低於",
    "gt": "高於",
}


@dataclass
class AlertRule:
    """A user-defined threshold rule on a single metric."""
    rule_id: str
    block_id: str
    metric_name: str
    metric_label: str
    operator: str            # "lt" | "gt"
    threshold: float
    unit: Optional[str] = None
    filter_column: Optional[str] = None   # optional scope, e.g. store_name
    filter_value: Optional[str] = None

    def describe(self) -> str:
        verb = _OPERATORS.get(self.operator, self.operator)
        scope = f"（{self.filter_value}）" if self.filter_value else ""
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.metric_label}{scope} {verb} {self.threshold:,.0f}{unit}"


@dataclass
class AlertResult:
    rule: AlertRule
    value: Optional[float]
    fired: bool
    message: str


def _evaluate_one(executor, rule: AlertRule) -> AlertResult:
    filters: list[FilterSpec] = []
    if rule.filter_column and rule.filter_value is not None:
        filters.append(FilterSpec(
            rule.block_id, rule.filter_column, FilterOperator.eq,
            rule.filter_value, inherit_global_filter=False,
        ))
    spec = VisualQuerySpec(
        spec_id=f"alert_{rule.rule_id}",
        block_refs=[BlockRef(rule.block_id)],
        metrics=[MetricRef(rule.block_id, rule.metric_name, "__alert_value")],
        filters=filters,
        data_version=f"alert:{rule.rule_id}",
    )
    value: Optional[float] = None
    try:
        df = executor.run(spec)
        if df is not None and not df.empty and "__alert_value" in df.columns:
            raw = df["__alert_value"].iloc[0]
            value = None if pd.isna(raw) else float(raw)
    except Exception:  # noqa: BLE001 — a broken rule must not crash the page
        value = None

    fired = False
    if value is not None:
        if rule.operator == "lt":
            fired = value < rule.threshold
        elif rule.operator == "gt":
            fired = value > rule.threshold

    verb = _OPERATORS.get(rule.operator, rule.operator)
    if value is None:
        message = f"⚠️ 無法計算「{rule.metric_label}」"
    elif fired:
        unit = f" {rule.unit}" if rule.unit else ""
        scope = f"（{rule.filter_value}）" if rule.filter_value else ""
        message = (
            f"🔔 {rule.metric_label}{scope} 目前為 {value:,.0f}{unit}，"
            f"已{verb}你設定的 {rule.threshold:,.0f}{unit}"
        )
    else:
        message = ""
    return AlertResult(rule=rule, value=value, fired=fired, message=message)


def evaluate_alerts(executor, rules: list[AlertRule]) -> list[AlertResult]:
    """Evaluate all rules and return results (fired and not-fired)."""
    return [_evaluate_one(executor, rule) for rule in rules]


def firing_alerts(executor, rules: list[AlertRule]) -> list[AlertResult]:
    """Return only the alerts whose condition is currently true."""
    return [r for r in evaluate_alerts(executor, rules) if r.fired]
