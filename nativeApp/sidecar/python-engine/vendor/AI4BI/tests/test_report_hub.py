"""Round 168: the report-entry hub + first-run welcome render the two clear
starting paths (use existing / create new) without error.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run(timeout=60)


def _labels(at) -> set[str]:
    return {b.label for b in at.button}


def test_hub_renders_both_start_paths_without_exception():
    at = _app()
    assert not at.exception, f"app raised: {at.exception}"
    labels = _labels(at)
    # ① 使用既有報表
    assert "🛍️ 零售示範" in labels
    assert "🔬 半導體示範" in labels  # exact label other tests/e2e rely on
    # ② 全新建立報表
    assert "✨ 用我的資料" in labels
    assert "📄 空白報表" in labels
    # file-lifecycle promoted out of 分享
    assert "💾 儲存" in labels


def test_first_run_welcome_card_and_breadcrumb_present():
    at = _app()
    text = " ".join(getattr(c, "value", "") or "" for c in (list(at.caption) + list(at.markdown)))
    assert "歡迎" in text          # welcome card
    assert "目前在" in text         # breadcrumb (which report / mode)


def test_welcome_dismiss_hides_card():
    at = _app()
    next(b for b in at.button if b.label == "✅ 就用這份範例").click().run(timeout=60)
    assert not at.exception
    text = " ".join(getattr(c, "value", "") or "" for c in (list(at.caption) + list(at.markdown)))
    assert "歡迎使用 AI for BI" not in text


def test_create_new_from_data_routes_to_data_mode():
    at = _app()
    next(b for b in at.button if b.label == "✨ 用我的資料").click().run(timeout=60)
    assert not at.exception
    assert at.session_state["_nav_mode"] == "🗂️ 資料"


def _mark_dirty(at) -> None:
    """Pretend the current report has unsaved edits (revision past baseline)."""
    at.session_state["_baseline_rev"] = at.session_state["_baseline_rev"] - 1


def test_switch_with_unsaved_changes_is_guarded():
    at = _app()
    _mark_dirty(at)
    next(b for b in at.button if b.label == "🔬 半導體示範").click().run(timeout=60)
    assert not at.exception
    # the switch is intercepted, not performed, and a confirm is shown
    assert at.session_state["_pending_switch"] == "semi"
    labels = {b.label for b in at.button}
    assert {"💾 先儲存再切", "直接切換", "取消"} <= labels


def test_switch_guard_discard_proceeds():
    at = _app()
    _mark_dirty(at)
    next(b for b in at.button if b.label == "🔬 半導體示範").click().run(timeout=60)
    next(b for b in at.button if b.label == "直接切換").click().run(timeout=60)
    assert not at.exception
    assert "_pending_switch" not in at.session_state
