"""Tests for analysis.capacity_dynamics (bottleneck drift + WIP/cycle-time)."""
import pandas as pd

from ai4bi.analysis.capacity_dynamics import (
    bottleneck_over_time,
    bottleneck_shift_summary,
    wip_vs_cycle_time,
)


def _moves():
    # Week 1: ETCH is the bottleneck (high queue). Week 2: PHOTO overtakes.
    rows = []
    for d, area, q in [
        ("2026-01-05", "ETCH", 50), ("2026-01-06", "ETCH", 48),
        ("2026-01-05", "PHOTO", 20), ("2026-01-06", "PHOTO", 22),
        ("2026-01-12", "ETCH", 18), ("2026-01-13", "ETCH", 17),
        ("2026-01-12", "PHOTO", 55), ("2026-01-13", "PHOTO", 60),
    ]:
        rows.append({"move_date": d, "area": area, "queue_time_hr": q, "lot_id": f"{area}-{d}"})
    return pd.DataFrame(rows)


def test_bottleneck_over_time_detects_shift():
    df = _moves()
    res = bottleneck_over_time(df, "move_date", "area", "queue_time_hr", freq="W")
    assert len(res) == 2
    assert res.iloc[0]["bottleneck"] == "ETCH"
    assert res.iloc[1]["bottleneck"] == "PHOTO"
    assert bool(res.iloc[1]["changed"]) is True
    assert bool(res.iloc[0]["changed"]) is False


def test_bottleneck_shift_summary():
    df = _moves()
    res = bottleneck_over_time(df, "move_date", "area", "queue_time_hr", freq="W")
    summ = bottleneck_shift_summary(res)
    assert summ["shifted"] is True
    assert summ["n_periods"] == 2
    assert summ["shifts"][0]["from"] == "ETCH"
    assert summ["shifts"][0]["to"] == "PHOTO"


def test_bottleneck_no_shift_when_stable():
    df = _moves()
    df = df[df["area"] == "ETCH"]  # only one area -> always the top
    res = bottleneck_over_time(df, "move_date", "area", "queue_time_hr", freq="W")
    summ = bottleneck_shift_summary(res)
    assert summ["shifted"] is False


def test_bottleneck_empty():
    res = bottleneck_over_time(pd.DataFrame(), "move_date", "area", "queue_time_hr")
    assert res.empty


def test_wip_vs_cycle_time_positive_correlation():
    # Construct periods where higher WIP coincides with longer cycle time.
    rows = []
    for week, (n_lots, ct) in {
        "2026-01-05": (2, 10), "2026-01-12": (4, 20), "2026-01-19": (6, 30),
    }.items():
        for i in range(n_lots):
            rows.append({"move_date": week, "cycle_time_hr": ct, "lot_id": f"{week}-{i}"})
    df = pd.DataFrame(rows)
    per, summ = wip_vs_cycle_time(df, "move_date", "cycle_time_hr", lot_col="lot_id", freq="W")
    assert len(per) == 3
    assert summ["r"] is not None and summ["r"] > 0.9
    assert "正相關" in summ["relationship"]


def test_wip_vs_cycle_time_insufficient():
    df = pd.DataFrame({"move_date": ["2026-01-05"], "cycle_time_hr": [10], "lot_id": ["a"]})
    per, summ = wip_vs_cycle_time(df, "move_date", "cycle_time_hr", lot_col="lot_id")
    assert summ["r"] is None


def test_wip_vs_cycle_time_missing_columns():
    df = pd.DataFrame({"x": [1, 2, 3]})
    per, summ = wip_vs_cycle_time(df, "move_date", "cycle_time_hr")
    assert per.empty
    assert summ["n"] == 0
