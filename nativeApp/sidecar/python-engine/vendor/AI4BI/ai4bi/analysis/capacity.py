"""Capacity / utilization / OEE analytics — Round 128.

Combines the move fact (actual moves), the tool-capacity reference (capacity,
planned, available/run hours, ideal time) and the yield fact (quality) — all
aligned on a shared key — to answer utilisation, loading, headroom, plan
attainment, throughput rate and OEE (Availability × Performance × Quality).
Builds on crossfact.align_two_facts (aggregate-then-join; no detail join).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from ai4bi.analysis.crossfact import align_two_facts
from ai4bi.blocks.contracts import DataBlockContract

_MOVE = "fab_process_move"
_CAP = "fab_tool_capacity"
_YIELD = "fab_wafer_yield"


def _aligned(contracts, group_key: str, cap_col: str, cap_alias: str, cap_agg: str = "SUM") -> pd.DataFrame:
    return align_two_facts(
        contracts, block_a=_MOVE, col_a="move_count", agg_a="SUM", alias_a="actual",
        block_b=_CAP, col_b=cap_col, agg_b=cap_agg, alias_b=cap_alias, join_key=group_key)


def utilization(contracts, group_key: str = "tool_id") -> pd.DataFrame:
    """Actual moves ÷ capacity per group. [group, 實際, 產能, 利用率%, 餘裕]."""
    m = _aligned(contracts, group_key, "capacity_moves", "capacity")
    if m is None or m.empty:
        return pd.DataFrame()
    m["利用率%"] = (m["actual"] / m["capacity"].replace(0, pd.NA) * 100).round(1)
    m["餘裕"] = (m["capacity"] - m["actual"]).round(0)
    out = m.rename(columns={"actual": "實際", "capacity": "產能"})
    return out.sort_values("利用率%", ascending=False).reset_index(drop=True)


def plan_attainment(contracts, group_key: str = "area") -> pd.DataFrame:
    """Actual ÷ planned per group. [group, 實際, 計畫, 達成率%]."""
    m = _aligned(contracts, group_key, "planned_moves", "planned")
    if m is None or m.empty:
        return pd.DataFrame()
    m["達成率%"] = (m["actual"] / m["planned"].replace(0, pd.NA) * 100).round(1)
    out = m.rename(columns={"actual": "實際", "planned": "計畫"})
    return out.sort_values("達成率%").reset_index(drop=True)


def throughput_rate(contracts, group_key: str = "tool_id") -> pd.DataFrame:
    """Moves per run-hour per group. [group, 實際, 運轉工時, moves_per_hr]."""
    m = _aligned(contracts, group_key, "run_hours", "run_hours")
    if m is None or m.empty:
        return pd.DataFrame()
    m["moves_per_hr"] = (m["actual"] / m["run_hours"].replace(0, pd.NA)).round(3)
    out = m.rename(columns={"actual": "實際"})
    return out.sort_values("moves_per_hr", ascending=False).reset_index(drop=True)


def compute_oee(contracts) -> pd.DataFrame:
    """OEE per tool = Availability × Performance × Quality.

    A = run_hours / available_hours (capacity ref)
    P = ideal_move_min × actual_moves / (run_hours × 60)
    Q = that tool's wafer yield where available (etch tools), else fab-wide yield.
    Returns [tool_id, 可用率A, 表現P, 良率Q, OEE] worst-first.
    """
    from ai4bi.blocks.datastore import materialize_dataframe
    cap = materialize_dataframe(contracts[_CAP])
    mv = materialize_dataframe(contracts[_MOVE])
    yd = materialize_dataframe(contracts[_YIELD])
    if cap.empty or mv.empty:
        return pd.DataFrame()
    actual = mv.groupby("tool_id")["move_count"].sum()
    fab_q = (yd["good_die"].sum() / yd["tested_die"].sum()) if yd["tested_die"].sum() else 1.0
    etch_q = (yd.groupby("etch_tool_id").apply(
        lambda g: g["good_die"].sum() / g["tested_die"].sum() if g["tested_die"].sum() else fab_q)
        if "etch_tool_id" in yd.columns else pd.Series(dtype=float))
    rows = []
    for _, r in cap.iterrows():
        tid = r["tool_id"]
        act = float(actual.get(tid, 0))
        avail_h, run_h = float(r["available_hours"]), float(r["run_hours"])
        a = run_h / avail_h if avail_h else 0.0
        p = (r["ideal_move_min"] * act) / (run_h * 60) if run_h else 0.0
        p = min(p, 1.0)
        q = float(etch_q.get(tid, fab_q)) if not etch_q.empty else fab_q
        oee = a * p * q
        rows.append({"tool_id": tid, "可用率A": round(a * 100, 1), "表現P": round(p * 100, 1),
                     "良率Q": round(q * 100, 1), "OEE": round(oee * 100, 1)})
    return pd.DataFrame(rows).sort_values("OEE").reset_index(drop=True)
