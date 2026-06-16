"""Round 176: S3 (compare two sources' columns) + S4 (column rename/hide prefs).

Pure helpers, no Streamlit.
"""

from __future__ import annotations

import pandas as pd

from ai4bi.ui.data_model import compare_columns
from ai4bi.ui.data_inspector import apply_column_prefs


# --- S3: column-set comparison --------------------------------------------

def test_compare_columns_partitions_common_and_unique():
    diff = compare_columns(["id", "store", "rev"], ["id", "region", "rev"])
    assert diff["common"] == ["id", "rev"]
    assert diff["only_a"] == ["store"]
    assert diff["only_b"] == ["region"]


def test_compare_columns_disjoint():
    diff = compare_columns(["a"], ["b"])
    assert diff["common"] == []
    assert diff["only_a"] == ["a"] and diff["only_b"] == ["b"]


# --- S4: apply rename/hide prefs ------------------------------------------

def test_apply_prefs_renames_and_hides():
    df = pd.DataFrame({"amt": [1], "store_id": ["A"], "secret": [9]})
    out = apply_column_prefs(df, alias={"amt": "金額", "store_id": "門市"}, hidden=["secret"])
    assert list(out.columns) == ["金額", "門市"]
    assert "secret" not in out.columns


def test_apply_prefs_noop_when_empty():
    df = pd.DataFrame({"a": [1], "b": [2]})
    out = apply_column_prefs(df, alias={}, hidden=[])
    assert list(out.columns) == ["a", "b"]


def test_apply_prefs_ignores_alias_for_missing_or_blank():
    df = pd.DataFrame({"a": [1], "b": [2]})
    # alias for a hidden/absent column or a blank value must be ignored safely
    out = apply_column_prefs(df, alias={"a": "", "zzz": "X"}, hidden=["b"])
    assert list(out.columns) == ["a"]
