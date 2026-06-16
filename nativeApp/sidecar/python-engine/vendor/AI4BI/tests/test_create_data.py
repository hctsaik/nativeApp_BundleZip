"""Round 176: create-new-data transforms — union (S8) + pivot/aggregate (S9).

Pure transforms, no Streamlit. The UI materializes a (capped) frame, runs these,
and registers the result via infer_block → CachedDataSource.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.ui.create_data import union_frames, aggregate_frame


# --- union ----------------------------------------------------------------

def test_union_stacks_same_schema():
    a = pd.DataFrame({"m": ["Jan", "Jan"], "rev": [10, 20]})
    b = pd.DataFrame({"m": ["Feb"], "rev": [30]})
    out = union_frames([a, b])
    assert len(out) == 3
    assert list(out.columns) == ["m", "rev"]


def test_union_aligns_mismatched_columns_with_nulls():
    a = pd.DataFrame({"rev": [10], "store": ["A"]})
    b = pd.DataFrame({"rev": [20], "region": ["North"]})
    out = union_frames([a, b])
    assert set(out.columns) == {"rev", "store", "region"}
    assert len(out) == 2
    assert out["region"].isna().sum() == 1  # row from `a` has no region
    assert out["store"].isna().sum() == 1   # row from `b` has no store


def test_union_ignores_empty_and_handles_none():
    a = pd.DataFrame({"x": [1]})
    out = union_frames([a, pd.DataFrame(), None])
    assert len(out) == 1


# --- aggregate ------------------------------------------------------------

def test_aggregate_sum_by_group():
    df = pd.DataFrame({"store": ["A", "A", "B"], "rev": [10, 20, 5]})
    out = aggregate_frame(df, ["store"], "rev", "sum")
    assert set(out.columns) == {"store", "rev_sum"}
    got = dict(zip(out["store"], out["rev_sum"]))
    assert got == {"A": 30, "B": 5}


def test_aggregate_count_needs_no_measure():
    df = pd.DataFrame({"store": ["A", "A", "B"], "rev": [10, 20, 5]})
    out = aggregate_frame(df, ["store"], None, "count")
    assert "筆數" in out.columns
    got = dict(zip(out["store"], out["筆數"]))
    assert got == {"A": 2, "B": 1}


def test_aggregate_multi_group_mean():
    df = pd.DataFrame({
        "store": ["A", "A", "A"], "month": ["Jan", "Jan", "Feb"], "rev": [10, 30, 8],
    })
    out = aggregate_frame(df, ["store", "month"], "rev", "mean")
    jan = out[(out["store"] == "A") & (out["month"] == "Jan")]["rev_mean"].iloc[0]
    assert jan == 20  # (10+30)/2


def test_aggregate_rejects_no_group_cols():
    df = pd.DataFrame({"x": [1]})
    with pytest.raises(ValueError):
        aggregate_frame(df, [], "x", "sum")


def test_aggregate_rejects_missing_measure():
    df = pd.DataFrame({"g": ["a"], "x": [1]})
    with pytest.raises(ValueError):
        aggregate_frame(df, ["g"], "does_not_exist", "sum")
