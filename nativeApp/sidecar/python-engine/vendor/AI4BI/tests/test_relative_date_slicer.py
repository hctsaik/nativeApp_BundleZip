"""Round 069: relative-date slicer presets."""

from __future__ import annotations

from datetime import date

import pytest

import ai4bi.ui.report_slicer as rs
from ai4bi.ui.report_slicer import SlicerDefinition, _relative_bounds, get_slicer_filters
from ai4bi.query_spec import FilterOperator


ANCHOR = date(2026, 5, 30)


@pytest.mark.parametrize("preset,lo,hi", [
    ("last_7", date(2026, 5, 24), ANCHOR),
    ("last_30", date(2026, 5, 1), ANCHOR),
    ("mtd", date(2026, 5, 1), ANCHOR),
    ("ytd", date(2026, 1, 1), ANCHOR),
])
def test_relative_bounds(preset, lo, hi):
    assert _relative_bounds(preset, ANCHOR) == (lo, hi)


def test_relative_bounds_all_is_open():
    assert _relative_bounds("all", ANCHOR) == (None, None)


def _slicer():
    return SlicerDefinition(
        slicer_id="b_order_date", label="Order Date", block_id="b", column="order_date",
        slicer_type="relative_date", options=list(rs._REL_PRESETS), min_val=date(2026, 1, 1),
        max_val=ANCHOR,
    )


def test_get_filters_for_last_7(monkeypatch):
    monkeypatch.setattr(rs.st, "session_state", {"report_slicers": {"b_order_date": "last_7"}})
    filters = get_slicer_filters([_slicer()])
    assert len(filters) == 2
    gte = next(f for f in filters if f.operator == FilterOperator.gte)
    lte = next(f for f in filters if f.operator == FilterOperator.lte)
    assert gte.value == "2026-05-24" and lte.value == "2026-05-30"
    assert gte.column_name == "order_date"


def test_get_filters_all_is_no_filter(monkeypatch):
    monkeypatch.setattr(rs.st, "session_state", {"report_slicers": {"b_order_date": "all"}})
    assert get_slicer_filters([_slicer()]) == []
