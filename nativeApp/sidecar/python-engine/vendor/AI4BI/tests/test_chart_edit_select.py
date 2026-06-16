"""Round 136: canvas ✏️ edit button selects a chart for the right 🎨 pane
(without the dropdown), and the pane is pinned (sticky) so data + controls are
visible together.

The headline regression guard is the widget-key collision: selected_component_id
is a selectbox widget key, so the canvas button must NOT write it directly —
it writes _edit_target_request, drained at the top of main() before the
selectbox instantiates. If that idiom breaks, AppTest surfaces the
"cannot be modified after widget instantiated" StreamlitAPIException.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"
_CID = "line_revenue_trend"  # exists in the default retail demo report


def _new_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run(timeout=45)


def _edit_button(app: AppTest, cid: str = _CID):
    return next(b for b in app.button if b.key == f"edit_main_{cid}")


def _visual_selectbox(app: AppTest):
    return next(sb for sb in app.selectbox if sb.key == "selected_component_id")


def test_edit_button_sets_pane_target_without_exception():
    app = _new_app()
    _edit_button(app).click().run(timeout=30)
    # No StreamlitAPIException from writing a widget key after instantiation.
    assert not app.exception
    # The pane now targets the clicked visual…
    assert app.session_state["selected_component_id"] == _CID
    # …and the deferred drain synced the dropdown fallback to match.
    assert _visual_selectbox(app).value == _CID


def test_edit_button_switches_between_charts():
    app = _new_app()
    _edit_button(app).click().run(timeout=30)
    assert app.session_state["selected_component_id"] == _CID
    # Pick any other editable visual on the page and switch to it.
    report = app.session_state["report_spec"]
    others = [c for c in report.pages["main"].visuals if c != _CID]
    if others:
        target = others[0]
        _edit_button(app, target).click().run(timeout=30)
        assert not app.exception
        assert app.session_state["selected_component_id"] == target


def test_dropdown_fallback_still_selects():
    app = _new_app()
    _visual_selectbox(app).set_value(_CID).run(timeout=30)
    assert app.session_state["selected_component_id"] == _CID


def test_edit_button_jumps_to_explore_from_fullwidth_mode():
    """Round 175: the right 🎨 視覺化 pane lives only in 探索 mode. Clicking ✏️
    from a full-width mode (分析/模型/資料) used to select the chart but show no
    pane ('右側不見了'). It must now jump to 探索 so the editor appears."""
    app = _new_app()
    app.session_state["_nav_mode"] = "📊 分析"
    app.run(timeout=30)
    _edit_button(app).click().run(timeout=30)
    assert not app.exception
    assert app.session_state["_nav_mode"] == "🔍 探索"
    assert app.session_state["selected_component_id"] == _CID


def test_edit_button_keeps_explore_mode_when_already_there():
    """In 探索 mode the ✏️ must NOT trigger a spurious mode change."""
    app = _new_app()  # defaults to 探索
    assert app.session_state["_nav_mode"] == "🔍 探索"
    _edit_button(app).click().run(timeout=30)
    assert app.session_state["_nav_mode"] == "🔍 探索"
    assert app.session_state["selected_component_id"] == _CID


def test_pane_sticky_css_is_emitted():
    # CSS layout can't be asserted in AppTest (no CSSOM); smoke that the rule is
    # emitted. Real sticky behavior is verified by the Playwright e2e.
    app = _new_app()
    blob = "\n".join(m.value for m in app.markdown if m.value)
    assert "viz-pane-anchor" in blob
    assert "position: sticky" in blob
