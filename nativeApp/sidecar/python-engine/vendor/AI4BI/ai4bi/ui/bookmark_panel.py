"""Bookmarks / saved views — Round 061.

Power BI bookmarks: capture the current interactive state (global slicers,
cross-filters, drill paths) under a name and restore it with one click — for
"save this view" and simple storytelling.

capture_state/restore_state are pure (operate on any mapping) so they're unit
testable. Restore also clears slicer widget keys so the slicer widgets re-read
the restored values instead of keeping their stale widget state.
"""

from __future__ import annotations

import copy

import streamlit as st

_BOOKMARKS_KEY = "bookmarks"
_TRACKED = ("report_slicers", "cross_filters", "drill_state")


def capture_state(state) -> dict:
    """Snapshot the tracked interactive keys (only non-empty ones)."""
    snap: dict = {}
    for k in _TRACKED:
        if k in state and state[k]:
            snap[k] = copy.deepcopy(state[k])
    return snap


def restore_state(state, snapshot: dict) -> None:
    """Restore tracked keys from a snapshot; clear ones absent from it.

    Also drops ``slicer_*`` widget keys so the slicer widgets re-initialise from
    the restored report_slicers values rather than their own stale widget state.
    """
    for k in _TRACKED:
        if k in snapshot:
            state[k] = copy.deepcopy(snapshot[k])
        elif k in state:
            del state[k]
    for wk in [k for k in list(state.keys()) if isinstance(k, str) and k.startswith("slicer_")]:
        if wk in state:
            del state[wk]


def render_bookmark_panel(cache) -> None:
    """Render the bookmarks sidebar panel."""
    bookmarks: dict = st.session_state.setdefault(_BOOKMARKS_KEY, {})
    with st.expander(f"🔖 書籤 / 儲存檢視（{len(bookmarks)}）", expanded=False):
        st.caption("把目前的篩選、鑽取、連動狀態存成書籤，下次一鍵還原。")

        name = st.text_input("書籤名稱", placeholder="例如：台北店 Q2 檢視", key="bm_name")
        if st.button("💾 儲存目前檢視", key="bm_save", type="primary", disabled=not name.strip()):
            bookmarks[name.strip()] = capture_state(st.session_state)
            st.success(f"已儲存書籤「{name.strip()}」")
            st.rerun()

        if bookmarks:
            st.markdown("---")
            for nm in list(bookmarks):
                c1, c2, c3 = st.columns([4, 1, 1])
                with c1:
                    st.write(f"🔖 {nm}")
                with c2:
                    if st.button("套用", key=f"bm_apply_{nm}"):
                        restore_state(st.session_state, bookmarks[nm])
                        cache.invalidate_all()
                        st.rerun()
                with c3:
                    if st.button("刪除", key=f"bm_del_{nm}"):
                        del bookmarks[nm]
                        st.rerun()
