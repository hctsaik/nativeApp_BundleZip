"""Business summary generator — Round 050.

Produces the "morning digest" an SMB owner asked for: trailing-period revenue
with a period-over-period delta, the top movers, and any firing alerts — as
plain markdown so it can be shown in-app, downloaded, or (later) emailed.

Pure function: generate_summary() takes an executor + contracts and returns a
SummaryReport. It reuses Round 047 (period comparison) and Round 048 (alerts)
so the digest compounds those features rather than duplicating logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ai4bi.analysis.alerts import AlertRule, firing_alerts
from ai4bi.analysis.time_intelligence import compute_period_comparison
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, SortDirection, SortSpec, VisualQuerySpec

_DATE_SUFFIXES = ("_date", "_at", "_on", "_day", "_time")
_ID_HINTS = ("_id", "_key", "_code", "_no", "_sku")

_PERIOD_NOUN = {"week": "本週", "month": "本月", "quarter": "本季", "year": "今年"}


@dataclass
class SummarySection:
    heading: str
    lines: list[str] = field(default_factory=list)


@dataclass
class SummaryReport:
    title: str
    generated_at: str
    period: str
    sections: list[SummarySection] = field(default_factory=list)

    def to_markdown(self) -> str:
        out = [f"# {self.title}", f"_產生於 {self.generated_at[:16].replace('T', ' ')}_", ""]
        for sec in self.sections:
            out.append(f"## {sec.heading}")
            if sec.lines:
                out.extend(f"- {line}" for line in sec.lines)
            else:
                out.append("_（無）_")
            out.append("")
        return "\n".join(out).strip()


def _is_date_col(name: str, dtype: str) -> bool:
    if dtype in ("date", "timestamp"):
        return True
    n = name.lower()
    return n in ("date", "time", "timestamp") or n.endswith(_DATE_SUFFIXES)


def _is_id_col(name: str) -> bool:
    n = name.lower()
    return n == "id" or n.endswith(_ID_HINTS)


def _fmt(value: Optional[float], unit: Optional[str]) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        s = f"{value / 1_000_000:.1f}M"
    elif abs(value) >= 1_000:
        s = f"{value / 1_000:.1f}K"
    else:
        s = f"{value:,.0f}"
    return f"{s} {unit}" if unit else s


def _first_fact(
    contracts: dict[str, DataBlockContract],
    preferred_block_id: Optional[str] = None,
) -> Optional[tuple[str, DataBlockContract]]:
    def _is_summarizable(c: DataBlockContract) -> bool:
        return c.block_type in (
            BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact
        ) and bool(c.metrics)

    # Prefer the block the user is currently looking at, if it is summarizable.
    if preferred_block_id and preferred_block_id in contracts:
        c = contracts[preferred_block_id]
        if _is_summarizable(c):
            return preferred_block_id, c
    for block_id, contract in contracts.items():
        if _is_summarizable(contract):
            return block_id, contract
    return None


def generate_summary(
    executor,
    contracts: dict[str, DataBlockContract],
    *,
    period: str = "week",
    alert_rules: Optional[list[AlertRule]] = None,
    preferred_block_id: Optional[str] = None,
) -> SummaryReport:
    """Build a business digest for the preferred (or first) fact block."""
    now = datetime.now(timezone.utc).isoformat()
    report = SummaryReport(title="業務摘要", generated_at=now, period=period)

    fact = _first_fact(contracts, preferred_block_id)
    if fact is None:
        report.sections.append(SummarySection("沒有可摘要的資料", []))
        return report
    block_id, contract = fact

    sum_metric = next(
        (m for m in contract.metrics if m.disaggregation_method.value in ("sum", "count")),
        contract.metrics[0],
    )
    metric_label = sum_metric.description or sum_metric.name
    unit = sum_metric.unit
    date_col = next(
        (c.name for c in contract.columns if _is_date_col(c.name, c.data_type)
         and c.name not in contract.primary_keys),
        None,
    )
    item_dim = next(
        (c.name for c in contract.columns
         if c.data_type in ("string", "str", "object") and not _is_id_col(c.name)
         and c.name not in contract.primary_keys),
        None,
    )

    base_spec = VisualQuerySpec(
        spec_id="summary_base", block_refs=[BlockRef(block_id)],
        metrics=[MetricRef(block_id, sum_metric.name, sum_metric.name)],
    )

    # ── Headline: trailing-period total + delta ────────────────────────────
    headline = SummarySection(f"{_PERIOD_NOUN.get(period, period)}重點")
    if date_col:
        comp = compute_period_comparison(
            executor, base_spec, date_block_id=block_id, date_column=date_col,
            period=period, metric_col=sum_metric.name,
        )
        if comp and comp.current is not None:
            line = f"{metric_label}（{comp.current_label}）：{_fmt(comp.current, unit)}"
            if comp.delta_pct is not None:
                arrow = "▲" if comp.delta_pct >= 0 else "▼"
                line += f"，{arrow} {comp.delta_pct:+.1f}% 對比{comp.previous_label}"
            headline.lines.append(line)
    if not headline.lines:
        try:
            df = executor.run(base_spec)
            if not df.empty:
                headline.lines.append(
                    f"{metric_label}（全部）：{_fmt(float(df.iloc[0, 0]), unit)}"
                )
        except Exception:  # noqa: BLE001
            pass
    report.sections.append(headline)

    # ── Top movers ─────────────────────────────────────────────────────────
    if item_dim:
        top = SummarySection(f"{metric_label} 前 3 名（{item_dim}）")
        spec = VisualQuerySpec(
            spec_id="summary_top", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, sum_metric.name, "v")],
            dimensions=[DimensionRef(block_id, item_dim, "k")],
            sort=[SortSpec("v", SortDirection.desc)], limit=3,
        )
        try:
            df = executor.run(spec)
            for i, row in enumerate(df.itertuples(index=False), start=1):
                top.lines.append(f"{i}. {row.k}：{_fmt(float(row.v), unit)}")
        except Exception:  # noqa: BLE001
            pass
        report.sections.append(top)

    # ── Alerts ───────────────────────────────────────────────────────────────
    if alert_rules:
        fired = firing_alerts(executor, alert_rules)
        alerts = SummarySection("提醒")
        alerts.lines = [r.message.replace("🔔 ", "") for r in fired]
        report.sections.append(alerts)

    return report
