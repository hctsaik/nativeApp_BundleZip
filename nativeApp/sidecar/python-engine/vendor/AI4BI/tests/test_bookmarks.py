"""Round 061: bookmark capture / restore of interactive state."""

from __future__ import annotations

from ai4bi.ui.bookmark_panel import capture_state, restore_state


def test_capture_only_nonempty_tracked_keys():
    state = {
        "report_slicers": {"s1": ["A"]},
        "cross_filters": {},          # empty → not captured
        "drill_state": {"bar": {"path": [{"column": "city", "value": "台北"}]}},
        "unrelated": 123,             # ignored
    }
    snap = capture_state(state)
    assert set(snap.keys()) == {"report_slicers", "drill_state"}
    assert "unrelated" not in snap


def test_capture_is_deep_copy():
    state = {"report_slicers": {"s1": ["A"]}}
    snap = capture_state(state)
    state["report_slicers"]["s1"].append("B")   # mutate original
    assert snap["report_slicers"]["s1"] == ["A"]  # snapshot unaffected


def test_restore_sets_and_clears():
    state = {
        "report_slicers": {"s1": ["A"]},
        "cross_filters": {"main": {"x": 1}},
        "slicer_s1": ["A"],            # stale widget key
    }
    # snapshot has only drill_state → restore must clear slicers + cross_filters
    snap = {"drill_state": {"bar": {"path": []}}}
    restore_state(state, snap)
    assert state["drill_state"] == {"bar": {"path": []}}
    assert "report_slicers" not in state
    assert "cross_filters" not in state
    # slicer widget keys are reset so widgets re-init from restored values
    assert "slicer_s1" not in state


def test_restore_roundtrip():
    original = {
        "report_slicers": {"sales_city": ["台北", "台中"]},
        "drill_state": {"bar": {"path": [{"column": "city", "value": "台北"}]}},
    }
    snap = capture_state(original)
    # user changes things
    live = {"report_slicers": {"sales_city": ["高雄"]}, "slicer_sales_city": ["高雄"]}
    restore_state(live, snap)
    assert live["report_slicers"] == {"sales_city": ["台北", "台中"]}
    assert live["drill_state"]["bar"]["path"][0]["value"] == "台北"
    assert "slicer_sales_city" not in live
