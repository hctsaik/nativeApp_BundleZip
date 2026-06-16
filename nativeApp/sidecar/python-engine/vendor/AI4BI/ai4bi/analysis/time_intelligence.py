"""Time-intelligence helpers — Round 047.

Period-over-period comparison (WoW / MoM / YoY) for KPI cards.

Design
------
We use *trailing-window* comparison anchored on the latest date present in the
data, not the calendar boundary:

    period="week"    last 7 days   vs the 7 days before that
    period="month"   last 30 days  vs the 30 days before that
    period="quarter" last 90 days  vs the 90 days before that
    period="year"    last 365 days vs the 365 days before that (YoY)

Trailing windows avoid the "partial current month looks worse than full prior
month" trap that calendar-boundary comparison falls into, and they degrade
gracefully when there is no prior-period data (delta is simply omitted).

The executor has no window-function support, so we compute the two periods as
two ordinary aggregate queries with date filters and diff them in Python. This
keeps the governed single-fact execution path intact.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from ai4bi.query_spec import (
    DimensionRef,
    FilterOperator,
    FilterSpec,
    VisualQuerySpec,
)

_PERIOD_DAYS = {"week": 7, "month": 30, "quarter": 90, "year": 365}

_PERIOD_LABELS = {
    "week": ("最近 7 天", "前 7 天"),
    "month": ("最近 30 天", "前 30 天"),
    "quarter": ("最近 90 天", "前 90 天"),
    "year": ("最近 12 個月", "去年同期"),
}


@dataclass
class PeriodComparison:
    """Result of a period-over-period comparison for a single metric."""
    current: Optional[float]
    previous: Optional[float]
    delta_pct: Optional[float]
    current_label: str
    previous_label: str

    @property
    def has_delta(self) -> bool:
        return self.delta_pct is not None


def _coerce_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return pd.to_datetime(value).date()
    except (ValueError, TypeError):
        return None


def latest_date(
    executor,
    base_spec: VisualQuerySpec,
    date_block_id: str,
    date_column: str,
) -> Optional[date]:
    """Return the maximum value of ``date_column`` honouring base_spec filters."""
    probe = replace(
        base_spec,
        spec_id=f"{base_spec.spec_id}__anchor",
        metrics=[],
        dimensions=[DimensionRef(date_block_id, date_column, "__anchor_date")],
        sort=[],
        limit=None,
    )
    try:
        df = executor.run(probe)
    except Exception:  # noqa: BLE001 — anchor is best-effort
        return None
    if df is None or df.empty or "__anchor_date" not in df.columns:
        return None
    series = pd.to_datetime(df["__anchor_date"], errors="coerce").dropna()
    if series.empty:
        return None
    return series.max().date()


def _window_filters(
    block_id: str,
    column: str,
    start: date,
    end: date,
) -> list[FilterSpec]:
    return [
        FilterSpec(block_id, column, FilterOperator.gte, start.isoformat(),
                   inherit_global_filter=False),
        FilterSpec(block_id, column, FilterOperator.lte, end.isoformat(),
                   inherit_global_filter=False),
    ]


def _period_spec(
    base_spec: VisualQuerySpec,
    block_id: str,
    column: str,
    start: date,
    end: date,
    suffix: str,
) -> VisualQuerySpec:
    """Clone base_spec restricted to [start, end] on the date column."""
    kept = [
        f for f in base_spec.filters
        if not (f.block_id == block_id and f.column_name == column)
    ]
    window = _window_filters(block_id, column, start, end)
    return replace(
        base_spec,
        spec_id=f"{base_spec.spec_id}__{suffix}",
        filters=kept + window,
        data_version=f"{base_spec.data_version}:{suffix}:{start}:{end}",
    )


def compute_grouped_comparison(
    executor,
    base_spec: VisualQuerySpec,
    *,
    date_block_id: str,
    date_column: str,
    dimension_col: str,
    period: str,
    metric_col: str,
    anchor: Optional[date] = None,
    is_ratio: bool = False,
) -> pd.DataFrame:
    """Per-dimension current-vs-previous deltas (Round 071).

    Runs the metric GROUPED BY ``dimension_col`` for the current and previous
    trailing windows and returns a DataFrame:
        [dimension_col, current, previous, delta, delta_pct, contribution_pct]
    sorted by delta ascending (biggest decliners first). Answers
    "why did <metric> change?" by store/category, same-store YoY, etc.
    Returns an empty DataFrame if the period/anchor can't be resolved.

    Round 178: ``is_ratio`` must be True for ratio/average metrics (yield %, rate,
    margin). You CANNOT sum group ratios — doing so produced nonsense like
    "Memory ↓894%, overall +1.2%". For ratio metrics we (a) leave
    ``contribution_pct`` as NaN (a group's additive contribution to a weighted
    average is undefined without a mix/rate decomposition — we report per-group
    rate movers instead), and (b) attach the TRUE weighted overall current/
    previous (computed UNGROUPED, so the executor's SUM(num)/SUM(den) is correct)
    in ``df.attrs['overall_current'/'overall_previous']`` for the caller to use
    instead of summing the per-group rates.
    """
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return pd.DataFrame()
    if anchor is None:
        anchor = latest_date(executor, base_spec, date_block_id, date_column)
    if anchor is None:
        return pd.DataFrame()

    cur_start = anchor - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    dim = DimensionRef(date_block_id, dimension_col, dimension_col)

    def _grouped(start: date, end: date, suffix: str) -> pd.DataFrame:
        spec = _period_spec(base_spec, date_block_id, date_column, start, end, suffix)
        spec = replace(spec, dimensions=[dim], sort=[], limit=None)
        try:
            return executor.run(spec)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def _ungrouped(start: date, end: date, suffix: str) -> float:
        """The TRUE weighted metric over the window (no group sum) — used for
        ratio metrics so the overall delta is SUM(num)/SUM(den), not Σ rates."""
        spec = _period_spec(base_spec, date_block_id, date_column, start, end, suffix)
        spec = replace(spec, dimensions=[], sort=[], limit=None)
        try:
            r = executor.run(spec)
            if r is None or r.empty:
                return float("nan")
            col = metric_col if metric_col in r.columns else r.columns[-1]
            return float(r[col].iloc[0])
        except Exception:  # noqa: BLE001
            return float("nan")

    cur = _grouped(cur_start, anchor, "gcur")
    prev = _grouped(prev_start, prev_end, "gprev")
    if cur.empty and prev.empty:
        return pd.DataFrame()

    def _norm(df: pd.DataFrame, value_name: str) -> pd.DataFrame:
        if df.empty or dimension_col not in df.columns:
            return pd.DataFrame(columns=[dimension_col, value_name])
        col = metric_col if metric_col in df.columns else df.columns[-1]
        return df[[dimension_col, col]].rename(columns={col: value_name})

    merged = _norm(cur, "current").merge(
        _norm(prev, "previous"), on=dimension_col, how="outer"
    ).fillna(0.0)
    merged["delta"] = merged["current"] - merged["previous"]

    def _pct(row) -> float:
        return (row["delta"] / abs(row["previous"]) * 100.0) if row["previous"] else float("nan")

    merged["delta_pct"] = merged.apply(_pct, axis=1).round(1)
    if is_ratio:
        # Group ratios are NOT additive — a per-group "contribution %" to a
        # weighted average is undefined here. Report per-group rate movers only,
        # and carry the true weighted overall for the caller.
        merged["contribution_pct"] = float("nan")
        merged = merged.sort_values("delta").reset_index(drop=True)
        merged.attrs["overall_current"] = _ungrouped(cur_start, anchor, "ocur")
        merged.attrs["overall_previous"] = _ungrouped(prev_start, prev_end, "oprev")
        merged.attrs["is_ratio"] = True
        return merged
    total_change = merged["delta"].sum()
    merged["contribution_pct"] = (
        (merged["delta"] / total_change * 100.0).round(1) if total_change else 0.0
    )
    return merged.sort_values("delta").reset_index(drop=True)


def _safe_replace_year(d: date, year: int) -> date:
    """date.replace(year=…) that survives Feb 29 (→ Feb 28)."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def _calendar_window(anchor: date, grain: str) -> Optional[tuple[date, date, date, date]]:
    """(cur_start, cur_end, prev_start, prev_end) for a calendar period vs last year.

    Compares period-to-date this year against the *same* dates last year (so a
    partial current month is fairly compared to the same partial month a year
    ago — true calendar YoY, not a trailing window).
    """
    if grain == "month":
        cur_start = anchor.replace(day=1)
    elif grain == "quarter":
        q0 = ((anchor.month - 1) // 3) * 3 + 1
        cur_start = date(anchor.year, q0, 1)
    elif grain == "year":
        cur_start = date(anchor.year, 1, 1)
    else:
        return None
    cur_end = anchor
    prev_start = _safe_replace_year(cur_start, cur_start.year - 1)
    prev_end = _safe_replace_year(anchor, anchor.year - 1)
    return cur_start, cur_end, prev_start, prev_end


_CALENDAR_LABELS = {
    "month": ("本月至今", "去年同月同期"),
    "quarter": ("本季至今", "去年同季同期"),
    "year": ("今年至今", "去年同期"),
}


def compute_calendar_comparison(
    executor,
    base_spec: VisualQuerySpec,
    *,
    date_block_id: str,
    date_column: str,
    grain: str,
    metric_col: str,
    anchor: Optional[date] = None,
) -> Optional[PeriodComparison]:
    """Calendar YoY: period-to-date this year vs the same dates last year.

    Unlike compute_period_comparison (trailing windows), this honours calendar
    boundaries — "May 2026 MTD vs May 2025 MTD". Returns None when the grain is
    unknown or no anchor/data can be resolved.
    """
    if anchor is None:
        anchor = latest_date(executor, base_spec, date_block_id, date_column)
    if anchor is None:
        return None
    window = _calendar_window(anchor, grain)
    if window is None:
        return None
    cur_start, cur_end, prev_start, prev_end = window

    cur_spec = _period_spec(base_spec, date_block_id, date_column, cur_start, cur_end, "cyr")
    prev_spec = _period_spec(base_spec, date_block_id, date_column, prev_start, prev_end, "pyr")
    try:
        cur_df = executor.run(cur_spec)
        prev_df = executor.run(prev_spec)
    except Exception:  # noqa: BLE001
        return None

    current = _scalar(cur_df, metric_col)
    previous = _scalar(prev_df, metric_col)
    delta_pct: Optional[float] = None
    if current is not None and previous not in (None, 0):
        delta_pct = (current - previous) / abs(previous) * 100.0
    cur_label, prev_label = _CALENDAR_LABELS.get(grain, (grain, f"prev {grain}"))
    return PeriodComparison(
        current=current, previous=previous, delta_pct=delta_pct,
        current_label=cur_label, previous_label=prev_label,
    )


def _scalar(df: Optional[pd.DataFrame], col: str) -> Optional[float]:
    if df is None or df.empty:
        return None
    if col not in df.columns and len(df.columns) == 1:
        col = df.columns[0]
    if col not in df.columns:
        return None
    val = df[col].iloc[0]
    return None if pd.isna(val) else float(val)


def compute_period_comparison(
    executor,
    base_spec: VisualQuerySpec,
    *,
    date_block_id: str,
    date_column: str,
    period: str,
    metric_col: str,
    anchor: Optional[date] = None,
) -> Optional[PeriodComparison]:
    """Compute current vs previous trailing-window values for a single metric.

    Returns None if the period is unknown or no anchor date can be resolved
    (e.g. the data has no usable date column) — callers then fall back to a
    plain KPI.
    """
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return None
    if anchor is None:
        anchor = latest_date(executor, base_spec, date_block_id, date_column)
    if anchor is None:
        return None

    cur_start = anchor - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    cur_spec = _period_spec(base_spec, date_block_id, date_column, cur_start, anchor, "cur")
    prev_spec = _period_spec(base_spec, date_block_id, date_column, prev_start, prev_end, "prev")

    try:
        cur_df = executor.run(cur_spec)
        prev_df = executor.run(prev_spec)
    except Exception:  # noqa: BLE001
        return None

    current = _scalar(cur_df, metric_col)
    previous = _scalar(prev_df, metric_col)

    delta_pct: Optional[float] = None
    if current is not None and previous not in (None, 0):
        delta_pct = (current - previous) / abs(previous) * 100.0

    cur_label, prev_label = _PERIOD_LABELS.get(period, (period, f"prev {period}"))
    return PeriodComparison(
        current=current,
        previous=previous,
        delta_pct=delta_pct,
        current_label=cur_label,
        previous_label=prev_label,
    )
