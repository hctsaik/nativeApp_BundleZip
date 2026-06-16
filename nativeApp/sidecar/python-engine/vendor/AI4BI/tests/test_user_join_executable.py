"""Round 183: a relationship the user builds in the 🔗 關聯 UI must actually be
USABLE in a chart on uploaded data — not just recorded.

Before R183, `_add_relationship` only wrote the session semantic model; the chart
Executor never received it (NL2-only) and the uploaded block contracts had no
`RelationshipHint`, so `SafeJoinPlanner` rejected every cross-table query. These
tests pin the end-to-end path: build relationship → wire contracts → execute.
"""

from __future__ import annotations

import pandas as pd
import pytest
import streamlit as st

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.contracts import BlockType
from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, VisualQuerySpec
from ai4bi.ui import data_model
from ai4bi.ui.data_model import detect_cardinality_multi
from ai4bi.ui.upload import _USER_BLOCKS_KEY, infer_block


def _contract(df: pd.DataFrame, bid: str):
    contract, _m, _d = infer_block(df, bid, bid)
    return contract


@pytest.fixture
def session(monkeypatch):
    """A plain-dict stand-in for st.session_state (item access is all we use)."""
    state: dict = {}
    monkeypatch.setattr(data_model.st, "session_state", state, raising=False)
    return state


def _two_uploaded_blocks(session):
    # fact: many rows per store; dim: one row per store
    fact = _contract(pd.DataFrame({
        "store_id": [1, 1, 2, 2, 3], "amount": [10, 20, 30, 40, 50]}), "sales")
    dim = _contract(pd.DataFrame({
        "store_id": [1, 2, 3], "city": ["TPE", "TXG", "KHH"]}), "stores")
    session[_USER_BLOCKS_KEY] = {"sales": fact, "stores": dim}
    return fact, dim


def test_n_to_1_relationship_wires_contracts(session):
    _two_uploaded_blocks(session)
    # user picks store_id↔store_id; sampling says N:1 (fact non-unique, dim unique)
    data_model._add_relationship("sales", "stores", [("store_id", "store_id")],
                                 cardinality="many_to_one")
    blocks = session[_USER_BLOCKS_KEY]
    # TO block became a dimension with the join key as a primary key
    assert blocks["stores"].block_type is BlockType.dimension
    assert "store_id" in blocks["stores"].primary_keys
    # FROM (fact) block got a LOW-fanout hint approving the key
    hints = [h for h in blocks["sales"].relationships if h.target_block_id == "stores"]
    assert len(hints) == 1 and "store_id" in hints[0].allowed_join_keys


def test_one_to_many_is_auto_swapped_to_n_to_1(session):
    _two_uploaded_blocks(session)
    # user built it BACKWARDS (dim as main, fact as sub) → detected 1:N.
    data_model._add_relationship("stores", "sales", [("store_id", "store_id")],
                                 cardinality="one_to_many")
    sm = data_model.get_user_semantic_model()
    rel = sm["relationships"][-1]
    # normalized: fact is the FROM (many) side, dim is the TO (one) side, N:1
    assert rel["from_block"] == "sales" and rel["to_block"] == "stores"
    assert rel["cardinality"] == "many_to_one"
    assert session[_USER_BLOCKS_KEY]["stores"].block_type is BlockType.dimension


def test_user_join_actually_executes_in_a_chart(session, tmp_path):
    fact, dim = _two_uploaded_blocks(session)
    data_model._add_relationship("sales", "stores", [("store_id", "store_id")],
                                 cardinality="many_to_one")
    sm = data_model.get_user_semantic_model()

    # Build the chart Executor exactly like app.py does (extra_contracts + the
    # user relationships) and run a cross-table visual: amount BY city.
    ex = Executor(
        registry_root=str(tmp_path),  # no demo registry needed
        extra_contracts=session[_USER_BLOCKS_KEY],
        extra_relationships=sm["relationships"],
    )
    spec = VisualQuerySpec(
        spec_id="x", block_refs=[BlockRef("sales"), BlockRef("stores")],
        metrics=[MetricRef("sales", "amount", "amount")],
        dimensions=[DimensionRef("stores", "city", "city")],
    )
    df = ex.run(spec)
    assert df is not None and not df.empty
    # N:1 join must NOT fan out: total amount stays 150 across the 3 cities
    assert int(df["amount"].sum()) == 150
    assert set(df["city"]) == {"TPE", "TXG", "KHH"}


def test_composite_key_relationship(session):
    # single key (region) is NOT unique on the dim → needs (region, store) together
    fact = _contract(pd.DataFrame({
        "region": ["N", "N", "S"], "store": [1, 2, 1], "amt": [10, 20, 30]}), "f")
    dim = _contract(pd.DataFrame({
        "region": ["N", "N", "S"], "store": [1, 2, 1], "mgr": ["a", "b", "c"]}), "d")
    session[_USER_BLOCKS_KEY] = {"f": fact, "d": dim}
    data_model._add_relationship(
        "f", "d", [("region", "region"), ("store", "store")],
        cardinality="many_to_one")
    rel = data_model.get_user_semantic_model()["relationships"][-1]
    assert rel["keys"] == [{"from": "region", "to": "region"},
                           {"from": "store", "to": "store"}]
    # both target keys must be primary keys; both source keys approved
    assert set(session[_USER_BLOCKS_KEY]["d"].primary_keys) >= {"region", "store"}
    hint = [h for h in session[_USER_BLOCKS_KEY]["f"].relationships
            if h.target_block_id == "d"][0]
    assert set(hint.allowed_join_keys) == {"region", "store"}


def test_composite_cardinality_combo_unique():
    # neither column alone is unique on the dim, but the (region, store) COMBO is →
    # composite key restores a safe N:1 (this is the user's "需要多欄位才不重複").
    fact = _contract(pd.DataFrame({
        "region": ["N", "N", "S", "S"], "store": [1, 1, 2, 2], "amt": [1, 2, 3, 4]}), "f")
    dim = _contract(pd.DataFrame({
        "region": ["N", "N", "S", "S"], "store": [1, 2, 1, 2], "mgr": list("abcd")}), "d")
    # single key 'region' alone → both sides non-unique → N:N (risky)
    single = data_model.detect_cardinality(fact, "region", dim, "region")
    assert single == ("N:N", True)
    # composite (region, store) → dim unique → N:1 (safe)
    combo, risky = detect_cardinality_multi(fact, ["region", "store"], dim, ["region", "store"])
    assert combo == "N:1" and risky is False
