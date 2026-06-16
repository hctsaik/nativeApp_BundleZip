"""App workflow integration tests.

Round 033 update: default report is now the retail demo.
Semiconductor-specific tests switch to semi demo via the "🔬 半導體示範" button.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"


def _click(app: AppTest, label: str) -> None:
    next(button for button in app.button if button.label == label).click().run(timeout=30)


def _new_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run(timeout=45)


def _visual_selectbox(app: AppTest):
    """Return the '① 選擇圖表' selectbox, looked up by its stable widget key."""
    return next(sb for sb in app.selectbox if sb.key == "selected_component_id")


def _load_semi_demo(app: AppTest) -> AppTest:
    """Switch the app to the semiconductor demo report (needed for semi-specific tests)."""
    _click(app, "🔬 半導體示範")
    return app


# ---------------------------------------------------------------------------
# Retail demo workflow tests
# ---------------------------------------------------------------------------

def test_style_prompt_previews_applies_and_undoes_without_changing_metrics():
    """Style change on retail demo's line chart — color change should not affect KPI numbers."""
    app = _new_app()
    original_metrics = [(metric.label, metric.value) for metric in app.metric]

    _visual_selectbox(app).set_value("line_revenue_trend").run(timeout=30)
    app.text_area[0].set_value("make trend line red").run(timeout=30)

    _click(app, "送出請求")
    report = app.session_state["report_spec"]
    # Proposal staged but not yet applied — color should still be None
    assert report.pages["main"].visuals["line_revenue_trend"].visualization.extra["line_color"] is None
    assert [(metric.label, metric.value) for metric in app.metric] == original_metrics

    _click(app, "Apply Proposal")
    report = app.session_state["report_spec"]
    assert report.pages["main"].visuals["line_revenue_trend"].visualization.extra["line_color"] == "#D62728"
    assert [(metric.label, metric.value) for metric in app.metric] == original_metrics

    _click(app, "復原")
    report = app.session_state["report_spec"]
    assert report.pages["main"].visuals["line_revenue_trend"].visualization.extra["line_color"] is None
    assert not app.exception


def test_unsupported_assistant_request_clears_stale_pending_proposal():
    """Unsupported request clears any previously staged proposal."""
    app = _new_app()
    _visual_selectbox(app).set_value("line_revenue_trend").run(timeout=30)
    app.text_area[0].set_value("make trend line red").run(timeout=30)

    _click(app, "送出請求")
    assert app.session_state["pending_patch"] is not None

    app.text_area[0].set_value("write SQL to join raw orders to inventory raw detail rows").run(timeout=30)
    _click(app, "送出請求")

    assert app.session_state["pending_patch"] is None
    assert not app.exception


# ---------------------------------------------------------------------------
# Semiconductor demo workflow tests (need semi data)
# ---------------------------------------------------------------------------

def test_analysis_prompt_waits_for_apply_and_then_undo_restores_controls_and_numbers():
    """Filter application and undo — semiconductor demo required for specific KPI values."""
    app = _new_app()
    _load_semi_demo(app)

    _visual_selectbox(app).set_value("line_queue_by_day").run(timeout=30)
    app.text_area[0].set_value("Only show Logic-B").run(timeout=30)

    _click(app, "送出請求")
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "6.0 moves"),
        ("Average Queue Time", "2.7 hr"),
    ]

    _click(app, "Apply Proposal")
    assert app.multiselect[1].value == ["Logic-B"]
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "2.0 moves"),
        ("Average Queue Time", "4.0 hr"),
    ]

    _click(app, "復原")
    assert app.multiselect[1].value == ["Logic-A", "Logic-B"]
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "6.0 moves"),
        ("Average Queue Time", "2.7 hr"),
    ]
    assert not app.exception


def test_manual_slicer_change_is_part_of_report_history():
    """Manual slicer change is undoable — semiconductor demo required for specific controls."""
    app = _new_app()
    _load_semi_demo(app)

    app.multiselect[1].set_value(["Logic-B"]).run(timeout=30)
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "2.0 moves"),
        ("Average Queue Time", "4.0 hr"),
    ]

    _click(app, "復原")
    assert app.multiselect[1].value == ["Logic-A", "Logic-B"]
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "6.0 moves"),
        ("Average Queue Time", "2.7 hr"),
    ]
    assert not app.exception
