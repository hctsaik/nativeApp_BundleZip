"""Round 085: consecutive trend-streak detection."""

from __future__ import annotations

import pandas as pd

from ai4bi.analysis.trends import declining_streaks, _current_streak


def test_current_streak_down():
    assert _current_streak([10, 8, 6, 4]) == (3, "down")


def test_current_streak_up():
    assert _current_streak([1, 2, 3]) == (2, "up")


def test_current_streak_breaks_on_reversal():
    # ends ...5,7 → last move is up, run length 1 up (earlier declines ignored)
    assert _current_streak([10, 8, 6, 5, 7]) == (1, "up")


def test_current_streak_flat_tail():
    assert _current_streak([5, 5]) == (0, "flat")


def _df():
    # FadingSKU declines 4 months straight; HotSKU grows; SteadySKU flat-ish.
    rows = []
    months = ["2026-01-05", "2026-02-05", "2026-03-05", "2026-04-05", "2026-05-05"]
    fading = [500, 400, 300, 200, 100]
    hot = [100, 150, 200, 250, 300]
    steady = [200, 205, 198, 203, 200]
    for m, f, h, s in zip(months, fading, hot, steady):
        rows.append({"sku": "FadingSKU", "order_date": m, "revenue": f})
        rows.append({"sku": "HotSKU", "order_date": m, "revenue": h})
        rows.append({"sku": "SteadySKU", "order_date": m, "revenue": s})
    return pd.DataFrame(rows)


def test_declining_streak_flags_fading_sku():
    out = declining_streaks(_df(), "sku", "order_date", "revenue", period="month", min_streak=3)
    assert "FadingSKU" in set(out["sku"])
    assert "HotSKU" not in set(out["sku"])
    row = out[out["sku"] == "FadingSKU"].iloc[0]
    assert row["連續期數"] == 4
    assert row["趨勢"] == "連續下滑"


def test_growth_direction():
    out = declining_streaks(_df(), "sku", "order_date", "revenue",
                            period="month", min_streak=3, direction="up")
    assert "HotSKU" in set(out["sku"])
    assert "FadingSKU" not in set(out["sku"])


def test_min_streak_threshold():
    # require 5 in a row → FadingSKU has only 4 declines → excluded
    out = declining_streaks(_df(), "sku", "order_date", "revenue", period="month", min_streak=5)
    assert out.empty


def test_missing_columns_returns_empty():
    assert declining_streaks(_df(), "nope", "order_date", "revenue").empty
