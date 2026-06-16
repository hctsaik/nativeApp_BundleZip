"""Round 176 (Phase 2): JSON ingestion — turn arbitrary parsed JSON into a flat,
queryable table (scenario S5). Pure helpers, no Streamlit.
"""

from __future__ import annotations

import json

from ai4bi.ui.upload import (
    _parse_json_any_encoding, json_record_paths, json_to_dataframe, nested_json_columns,
)


# --- records-path detection -----------------------------------------------

def test_top_level_array_is_root_path():
    obj = [{"a": 1}, {"a": 2}]
    assert json_record_paths(obj) == [""]


def test_envelope_finds_the_list_key():
    obj = {"meta": {"count": 2}, "data": [{"a": 1}, {"a": 2}]}
    assert json_record_paths(obj) == ["data"]


def test_multiple_lists_ranked_by_size():
    obj = {"users": [{"u": 1}, {"u": 2}], "orders": [{"o": 1}, {"o": 2}, {"o": 3}]}
    assert json_record_paths(obj) == ["orders", "users"]


def test_nested_list_path_is_dotted():
    obj = {"result": {"items": [{"x": 1}]}}
    assert json_record_paths(obj) == ["result.items"]


def test_plain_object_falls_back_to_root():
    assert json_record_paths({"a": 1, "b": 2}) == [""]


# --- normalization to a flat table ----------------------------------------

def test_array_of_objects_becomes_rows():
    df = json_to_dataframe([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], "")
    assert list(df.columns) == ["id", "name"]
    assert len(df) == 2


def test_nested_objects_flatten_to_dotted_columns():
    df = json_to_dataframe([{"id": 1, "addr": {"city": "Taipei", "zip": "100"}}], "")
    assert "addr.city" in df.columns
    assert df.loc[0, "addr.city"] == "Taipei"


def test_residual_lists_become_json_strings():
    df = json_to_dataframe([{"id": 1, "tags": ["x", "y"]}], "")
    val = df.loc[0, "tags"]
    assert isinstance(val, str)
    assert json.loads(val) == ["x", "y"]


def test_envelope_path_selects_the_records():
    obj = {"data": [{"a": 1}, {"a": 2}], "meta": {"n": 2}}
    df = json_to_dataframe(obj, "data")
    assert len(df) == 2 and list(df.columns) == ["a"]


def test_single_object_becomes_one_row():
    df = json_to_dataframe({"a": 1, "b": 2}, "")
    assert len(df) == 1
    assert set(df.columns) == {"a", "b"}


# --- encoding-tolerant parse ----------------------------------------------

def test_parse_json_handles_utf8_and_big5():
    payload = [{"店名": "永康店", "營收": 100}]
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert _parse_json_any_encoding(raw) == payload
    raw_big5 = json.dumps(payload, ensure_ascii=False).encode("big5")
    assert _parse_json_any_encoding(raw_big5) == payload


def test_nested_json_columns_flags_residual_arrays():
    df = json_to_dataframe([{"id": 1, "tags": ["x", "y"], "name": "a"}], "")
    nested = nested_json_columns(df)
    assert "tags" in nested
    assert "name" not in nested and "id" not in nested
