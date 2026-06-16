"""Playwright pytest E2E for the Power BI-style UI redesign (Rounds 147-158).

Uses the session-scoped Streamlit server (conftest `app_url`) + pytest-playwright
`page`. Each test gets a fresh page → fresh Streamlit session (retail default);
semiconductor tests load the semi demo inline.

Run:  python -m pytest tests/e2e/test_ux_redesign_e2e.py
(requires the conftest server port to be free).
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _load(page: Page, url: str) -> None:
    page.goto(url, wait_until="networkidle", timeout=60_000)
    page.wait_for_selector("[data-testid='stApp']", timeout=30_000)
    page.wait_for_timeout(3_000)


def _sidebar_text(page: Page) -> str:
    return page.get_by_test_id("stSidebar").inner_text()


def _set_mode(page: Page, text: str) -> None:
    (page.get_by_test_id("stSidebar")
        .locator("[data-testid='stRadio'] label")
        .filter(has_text=text).first).click()
    page.wait_for_timeout(2_500)


def _load_semi(page: Page) -> None:
    page.get_by_text("進階示範").first.click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name="🔬 半導體示範").click()
    page.wait_for_timeout(3_500)


def _open_expander(page: Page, text: str) -> None:
    try:
        page.get_by_test_id("stSidebar").get_by_text(text, exact=False).first.click()
        page.wait_for_timeout(800)
    except Exception:
        pass


# Round 176: data management moved from the 🔗 模型 sidebar into the main-canvas
# 🗂️ 資料 workspace tabs, so these read the main area, not the sidebar.
def _main_text(page: Page) -> str:
    return page.get_by_test_id("stMain").inner_text()


def _click_tab(page: Page, text: str) -> None:
    page.get_by_role("tab", name=text).first.click()
    page.wait_for_timeout(1_500)


def _open_main_expander(page: Page, text: str) -> None:
    try:
        page.get_by_test_id("stMain").get_by_text(text, exact=False).first.click()
        page.wait_for_timeout(800)
    except Exception:
        pass


def _select_first_visual(page: Page) -> None:
    lbl = page.get_by_text("選擇圖表").first
    box = lbl.locator(
        "xpath=ancestor::div[contains(@data-testid,'stSelectbox')]//div[@data-baseweb='select']")
    (box.first if box.count() else page.locator('div[data-baseweb="select"]').first).click()
    page.wait_for_timeout(800)
    opts = page.locator('li[role="option"]')
    if opts.count() > 1:
        opts.nth(1).click()
    page.wait_for_timeout(4_000)


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #

def test_four_view_modes(page: Page, app_url: str):
    # Round 176: 🔗 模型 merged into 🗂️ 資料 workspace → 4 top-level modes.
    _load(page, app_url)
    sb = _sidebar_text(page)
    for m in ["探索", "資料", "分析", "分享"]:
        assert m in sb, f"view mode {m} missing"


def test_canvas_ask_box_is_data_driven_retail(page: Page, app_url: str):
    _load(page, app_url)
    ph = page.locator("textarea").first.get_attribute("placeholder") or ""
    assert "營收" in ph or "city" in ph, f"retail placeholder not data-driven: {ph!r}"


def test_retail_shows_all_advanced_analyses(page: Page, app_url: str):
    _load(page, app_url)
    _set_mode(page, "分析")
    sb = _sidebar_text(page)
    for x in ["客戶留存", "常一起購買", "RFM", "連續下滑", "變化分解", "業務摘要"]:
        assert x in sb, f"retail advanced analysis {x} missing"


def test_retail_model_has_no_fab_leak(page: Page, app_url: str):
    # Round 176: calc panel lives in 資料 workspace → ➕ 新增資料 tab (main area).
    _load(page, app_url)
    _set_mode(page, "資料")
    _click_tab(page, "新增資料")
    _open_main_expander(page, "新增計算欄位")
    mt = _main_text(page)
    assert "retail_sales" in mt
    assert "process_move_fact" not in mt


def test_semi_hides_retail_only_analyses(page: Page, app_url: str):
    _load(page, app_url)
    _load_semi(page)
    _set_mode(page, "分析")
    sb = _sidebar_text(page)
    for x in ["客戶留存", "常一起購買", "RFM"]:
        assert x not in sb, f"retail-only analysis {x} leaked onto semiconductor"
    for x in ["連續下滑", "變化分解", "業務摘要"]:
        assert x in sb, f"applicable analysis {x} missing on semiconductor"


def test_semi_model_has_no_retail_leak(page: Page, app_url: str):
    # Round 176: calc panel lives in 資料 workspace → ➕ 新增資料 tab (main area).
    _load(page, app_url)
    _load_semi(page)
    _set_mode(page, "資料")
    _click_tab(page, "新增資料")
    _open_main_expander(page, "新增計算欄位")
    mt = _main_text(page)
    assert ("process_move_fact" in mt) or ("tool_dim" in mt)
    assert "retail_sales" not in mt and "store_staffing" not in mt


def test_semi_ask_box_has_no_retail_terms(page: Page, app_url: str):
    _load(page, app_url)
    _load_semi(page)
    ph = page.locator("textarea").first.get_attribute("placeholder") or ""
    for t in ["營收", "商品", "客戶", "門市"]:
        assert t not in ph, f"retail term {t} leaked into semi placeholder: {ph!r}"


def test_drag_drop_field_well_renders(page: Page, app_url: str):
    _load(page, app_url)
    _select_first_visual(page)
    found = False
    for fr in page.frames:
        try:
            if fr.locator("text=可用欄位").count() > 0:
                found = fr.locator('[draggable="true"]').count() > 0
                break
        except Exception:
            pass
    assert found, "drag-drop field-well component did not render draggable chips"


def test_visualizations_pane_present(page: Page, app_url: str):
    _load(page, app_url)
    _select_first_visual(page)
    assert page.get_by_text("正在編輯").count() > 0 or page.get_by_text("視覺化").count() > 0


def _stable_delete_count(page: Page) -> int:
    """Count exact-🗑 visual delete buttons, waiting until the lazy canvas render
    settles (visuals load progressively via DuckDB)."""
    prev = -1
    for _ in range(10):
        page.wait_for_timeout(1_500)
        c = page.get_by_role("button", name="🗑", exact=True).count()
        if c == prev and c > 0:
            return c
        prev = c
    return prev


def test_delete_visual_button_removes_a_chart(page: Page, app_url: str):
    _load(page, app_url)
    # exact "🗑" = a visual delete button (the ribbon's cache button is "🗑 快取").
    before = _stable_delete_count(page)
    assert before >= 1, "no per-visual delete buttons present"
    page.get_by_role("button", name="🗑", exact=True).first.click()
    after = _stable_delete_count(page)
    assert after == before - 1, f"delete did not remove a chart ({before} -> {after})"
