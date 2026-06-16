"""Alert manager UI — Round 048.

Sidebar panel to create threshold alerts ("tell me when revenue drops below X")
and a page-top banner that fires when a rule's condition is currently true.

Rules live in st.session_state["alert_rules"] as a list[AlertRule].
"""

from __future__ import annotations

import uuid

import streamlit as st

from ai4bi.analysis.alerts import AlertRule, firing_alerts
from ai4bi.blocks.contracts import BlockType, DataBlockContract

_ALERT_RULES_KEY = "alert_rules"


def _rules() -> list[AlertRule]:
    if _ALERT_RULES_KEY not in st.session_state:
        st.session_state[_ALERT_RULES_KEY] = []
    return st.session_state[_ALERT_RULES_KEY]


def _metric_options(
    contracts: dict[str, DataBlockContract],
) -> list[tuple[str, str, str, str]]:
    """Return (block_id, metric_name, label, unit) for every fact-block metric."""
    options: list[tuple[str, str, str, str]] = []
    for block_id, contract in contracts.items():
        if contract.block_type not in (
            BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact
        ):
            continue
        for metric in contract.metrics:
            label = metric.description or metric.name
            options.append((block_id, metric.name, label, metric.unit or ""))
    return options


def render_alert_banner(executor) -> None:
    """Render firing alerts at the top of the page (Round 048)."""
    rules = _rules()
    if not rules:
        return
    fired = firing_alerts(executor, rules)
    for result in fired:
        st.error(result.message, icon="🔔")


def render_alert_manager(
    contracts: dict[str, DataBlockContract],
) -> None:
    """Render the alert creation + management panel (sidebar)."""
    rules = _rules()
    with st.expander(f"🔔 提醒設定（{len(rules)}）", expanded=False):
        st.caption("設定門檻，數字達到條件時會在報表最上方提醒你。例如：營收低於 100000。")

        options = _metric_options(contracts)
        if not options:
            st.info("目前沒有可設定提醒的指標。")
        else:
            labels = [f"{label}" for (_b, _m, label, _u) in options]
            idx = st.selectbox(
                "指標",
                range(len(options)),
                format_func=lambda i: labels[i],
                key="alert_metric_sel",
            )
            col1, col2 = st.columns([1, 2])
            with col1:
                op = st.selectbox(
                    "條件", ["lt", "gt"],
                    format_func=lambda o: {"lt": "低於", "gt": "高於"}[o],
                    key="alert_op_sel",
                )
            with col2:
                threshold = st.number_input("門檻值", value=0.0, step=1000.0, key="alert_threshold")

            if st.button("➕ 新增提醒", key="alert_add_btn", type="primary"):
                block_id, metric_name, label, unit = options[idx]
                rules.append(AlertRule(
                    rule_id=uuid.uuid4().hex[:8],
                    block_id=block_id,
                    metric_name=metric_name,
                    metric_label=label,
                    operator=op,
                    threshold=float(threshold),
                    unit=unit or None,
                ))
                st.rerun()

        # Existing rules
        if rules:
            st.markdown("---")
            st.caption("目前的提醒：")
            for rule in list(rules):
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.write(f"• {rule.describe()}")
                with c2:
                    if st.button("刪除", key=f"alert_del_{rule.rule_id}"):
                        st.session_state[_ALERT_RULES_KEY] = [
                            r for r in rules if r.rule_id != rule.rule_id
                        ]
                        st.rerun()
