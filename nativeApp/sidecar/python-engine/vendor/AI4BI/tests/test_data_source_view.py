"""Round 167: the 資料 view-mode renders the data-source manager/inspector.

This is the AppTest the suite was missing — the existing app workflow tests run
the default 探索 mode, so they never exercised render_data_source_manager (which
lazily imports datastore.source_row_count). A render-time ImportError there would
slip past the unit tests; this asserts the 資料 mode renders cleanly.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"


def _data_mode_app() -> AppTest:
    at = AppTest.from_file(str(APP_PATH)).run(timeout=60)
    radio = next(r for r in at.radio if r.key == "_nav_mode")
    radio.set_value("🗂️ 資料").run(timeout=60)
    return at


def test_data_mode_renders_without_exception():
    at = _data_mode_app()
    assert not at.exception, f"資料 mode raised: {at.exception}"


def test_data_source_manager_summarizes_sources():
    """The retail demo report references a built-in block, so the manager must
    render its summary (and thus call source_row_count / the inspector) cleanly."""
    at = _data_mode_app()
    assert not at.exception
    texts = " ".join(
        getattr(el, "value", "") or "" for el in (list(at.caption) + list(at.markdown))
    )
    assert "資料來源" in texts  # the "...使用 N 個資料來源..." summary rendered
