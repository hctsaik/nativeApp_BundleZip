"""Round 176: unified Data Workspace — the 🗂️ 資料 mode absorbs 🔗 模型 and
becomes a master-detail workspace (sources/preview / relationships / create).

Covers:
  * nav is reduced to 4 modes (no standalone 模型);
  * _source_entries unifies built-in + user-loaded sources (metadata only);
  * the workspace renders its three sub-tabs without raising (a smoke test that
    join builder / upload / connector / calc panels all live here now);
  * the source selection is a remembered widget (_ws_source_sel).
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ai4bi.report.retail_template import build_retail_sales_block
from ai4bi.ui.data_model import _source_entries

APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"


def _new_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run(timeout=60)


# --- pure helper: unified source list (no Streamlit) ----------------------

def test_source_entries_marks_builtin_readonly():
    c = build_retail_sales_block()
    entries = _source_entries({"retail_sales": c}, meta={}, uploads={})
    assert "retail_sales" in entries
    e = entries["retail_sales"]
    assert e["removable"] is False
    assert e["icon"] == "📊"


def test_source_entries_marks_uploads_removable_with_badge():
    c = build_retail_sales_block()
    meta = {"retail_sales": {"display_name": "我的銷售", "source": "duckdb"}}
    entries = _source_entries({}, meta=meta, uploads={"retail_sales": c})
    e = entries["retail_sales"]
    assert e["removable"] is True
    assert e["name"] == "我的銷售"
    assert e["icon"] == "🦆"  # duckdb source badge


def test_source_entries_status_defaults_builtin_inuse_upload_eval():
    c = build_retail_sales_block()
    builtin = _source_entries({"retail_sales": c}, meta={}, uploads={})
    assert builtin["retail_sales"]["status_label"] == "報表使用中"
    up = _source_entries({}, meta={"u": {"display_name": "x"}}, uploads={"u": c})
    assert up["u"]["status_label"] == "評估中"
    assert up["u"]["status_icon"] == "🟡"


def test_source_entries_in_use_ids_marks_upload_as_inuse():
    c = build_retail_sales_block()
    e = _source_entries({}, meta={"u": {}}, uploads={"u": c}, in_use_ids={"u"})
    assert e["u"]["status_label"] == "報表使用中"
    assert e["u"]["status_icon"] == "🟢"


# --- nav structure --------------------------------------------------------

def test_nav_has_four_modes_no_standalone_model():
    at = _new_app()
    radio = next(r for r in at.radio if r.key == "_nav_mode")
    assert radio.options == ["🔍 探索", "🗂️ 資料", "📊 分析", "📤 分享"]
    assert not any("模型" in o for o in radio.options)


# --- workspace renders (smoke) -------------------------------------------

def test_data_workspace_renders_with_source_selector():
    at = _new_app()
    at.session_state["_nav_mode"] = "🗂️ 資料"
    at.run(timeout=60)
    assert not at.exception
    # the master-detail source picker is a remembered radio in the 來源與預覽 tab
    keys = {r.key for r in at.radio}
    assert "_ws_source_sel" in keys


def test_workspace_shows_content_sample_by_default():
    # Round 177: content-first — the selected source's sample rows render without
    # ticking any checkbox (previously the preview was opt-in behind a checkbox).
    at = _new_app()
    at.session_state["_nav_mode"] = "🗂️ 資料"
    at.run(timeout=60)
    assert not at.exception
    assert len(at.dataframe) >= 1  # a content sample is shown by default


def test_data_workspace_selection_persists_across_rerun():
    at = _new_app()
    at.session_state["_nav_mode"] = "🗂️ 資料"
    at.run(timeout=60)
    sel = at.session_state["_ws_source_sel"]
    assert sel  # a source is selected by default
    # a no-op rerun must keep the same source selected (the user's place is kept)
    at.run(timeout=60)
    assert at.session_state["_ws_source_sel"] == sel
