"""Round 179: the 🔗 關聯 (join) builder must offer the semiconductor demo's own
built-in tables (tool_dim + process_move_fact, both keyed on tool_id) — not only
files the user uploaded. Regression guard for "tool_id has no join option".
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"


def _load_semi(at: AppTest) -> None:
    # dismiss welcome if present, then switch to the semiconductor demo
    for b in at.button:
        if "半導體" in b.label:
            b.click()
            at.run(timeout=60)
            break
    for b in at.button:
        if b.label == "直接切換":
            b.click()
            at.run(timeout=60)
            break


def test_join_builder_offers_demo_tool_id_join():
    at = AppTest.from_file(str(APP_PATH)).run(timeout=60)
    _load_semi(at)
    at.session_state["_nav_mode"] = "🗂️ 資料"
    at.run(timeout=60)
    assert not at.exception
    # the join builder renders its source picker (join_from_block) only when it
    # sees ≥2 blocks. With the fix it sees the report's built-in blocks, so the
    # picker is present (instead of the "upload 2 files" info).
    sel_keys = {s.key for s in at.selectbox}
    assert "join_from_block" in sel_keys, (
        "join builder did not offer the demo's blocks — tool_id join unavailable")
    # and tool_id is auto-detected as the join key across the two built-in tables
    blob = "\n".join(
        [m.value for m in at.markdown if m.value]
        + [s.value for s in at.success if getattr(s, "value", None)]
        + [i.value for i in at.info if getattr(i, "value", None)])
    assert "tool_id" in blob, "tool_id was not auto-detected as a join key"


def test_backwards_pick_auto_corrects_to_safe_n_to_1():
    """Round 183: a backwards (dimension-as-main) pick must NOT strand the user on
    a 1:N warning — the builder auto-corrects to the safe N:1 orientation."""
    at = AppTest.from_file(str(APP_PATH)).run(timeout=60)
    _load_semi(at)
    at.session_state["_nav_mode"] = "🗂️ 資料"
    at.run(timeout=60)
    assert not at.exception
    warnings = "\n".join(w.value for w in at.warning if getattr(w, "value", None))
    # the 1:N "主從接反" warning is the opted-out branch; by default the demo's
    # tool_dim×process_move_fact pair auto-flips to N:1 and never shows it.
    assert "主從接反" not in warnings, "1:N pick was not auto-corrected to N:1"
