"""Standalone multi-scenario E2E for the Power BI-style UI redesign (Round 147-157).

Drives a real Chromium browser against a real Streamlit server and checks the
view-mode IA, data-driven panels (no retail leak on the semi demo), the drag-drop
field-well component, and the right-hand Visualizations pane.

Run:  python tests/e2e/run_ux_e2e.py   (chromium + a free port; safe alongside :8502)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

_APP = Path(__file__).parents[2] / "ai4bi" / "ui" / "app.py"
_PORT = 8540
_URL = f"http://localhost:{_PORT}"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _start_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(_APP),
         "--server.port", str(_PORT), "--server.headless", "true",
         "--server.runOnSave", "false", "--browser.gatherUsageStats", "false"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            if requests.get(_URL, timeout=2).status_code == 200:
                return proc
        except Exception:
            pass
        time.sleep(1)
    proc.terminate()
    raise RuntimeError("server did not start")


def _load(pg):
    pg.goto(_URL, wait_until="networkidle", timeout=60_000)
    pg.wait_for_selector("[data-testid='stApp']", timeout=30_000)
    pg.wait_for_timeout(3_000)


def _set_mode(pg, text: str):
    lab = pg.get_by_test_id("stSidebar").locator("[data-testid='stRadio'] label").filter(has_text=text).first
    lab.click()
    pg.wait_for_timeout(2_500)


def _load_semi(pg):
    pg.get_by_text("進階示範").first.click()
    pg.wait_for_timeout(700)
    pg.get_by_role("button", name="🔬 半導體示範").click()
    pg.wait_for_timeout(3_500)


def _sidebar_text(pg) -> str:
    return pg.get_by_test_id("stSidebar").inner_text()


def _open_expander(pg, text: str):
    """Expand a (possibly collapsed) sidebar expander so its content is visible."""
    exp = pg.get_by_test_id("stSidebar").get_by_text(text, exact=False).first
    try:
        exp.click()
        pg.wait_for_timeout(800)
    except Exception:
        pass


# Round 176: data management moved into the main-canvas 🗂️ 資料 workspace tabs.
def _main_text(pg) -> str:
    return pg.get_by_test_id("stMain").inner_text()


def _click_tab(pg, text: str):
    pg.get_by_role("tab", name=text).first.click()
    pg.wait_for_timeout(1_500)


def _open_main_expander(pg, text: str):
    try:
        pg.get_by_test_id("stMain").get_by_text(text, exact=False).first.click()
        pg.wait_for_timeout(800)
    except Exception:
        pass


def _select_first_visual(pg):
    """Pick the first real visual in the canvas-top '① 選擇圖表' selector."""
    lbl = pg.get_by_text("選擇圖表").first
    box = lbl.locator("xpath=ancestor::div[contains(@data-testid,'stSelectbox')]//div[@data-baseweb='select']")
    (box.first if box.count() else pg.locator('div[data-baseweb="select"]').first).click()
    pg.wait_for_timeout(800)
    opts = pg.locator('li[role="option"]')
    if opts.count() > 1:
        opts.nth(1).click()
    pg.wait_for_timeout(4_000)


def main() -> int:
    proc = _start_server()
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page()

            # S1 — app loads with 4 view modes (Round 176: 模型 merged into 資料)
            _load(pg)
            sb = _sidebar_text(pg)
            check("S1 four view modes present",
                  all(m in sb for m in ["探索", "資料", "分析", "分享"]))

            # S2 — NL ask box at canvas top, data-driven placeholder (retail)
            ta = pg.locator("textarea").first
            ph = ta.get_attribute("placeholder") or ""
            check("S2 canvas ask box + retail-flavoured placeholder",
                  ("營收" in ph or "city" in ph), ph[:60])

            # S3 — retail 分析: all 6 advanced analyses
            _set_mode(pg, "分析")
            sb = _sidebar_text(pg)
            retail_six = ["客戶留存", "常一起購買", "RFM", "連續下滑", "變化分解", "業務摘要"]
            check("S3 retail shows all 6 advanced analyses",
                  all(x in sb for x in retail_six),
                  ", ".join(x for x in retail_six if x not in sb) or "all present")

            # S4 — retail 資料工作區 → 新增資料 tab: calc dataset = retail_sales, no fab leak
            _set_mode(pg, "資料")
            _click_tab(pg, "新增資料")
            _open_main_expander(pg, "新增計算欄位")
            mt = _main_text(pg)
            check("S4 retail workspace: retail_sales present, no fab leak",
                  ("retail_sales" in mt) and ("process_move_fact" not in mt))

            # switch to semiconductor demo
            _set_mode(pg, "探索")
            _load_semi(pg)

            # S5 — semi 分析: retail-only hidden, applicable shown
            _set_mode(pg, "分析")
            sb = _sidebar_text(pg)
            check("S5 semi hides retail-only analyses",
                  all(x not in sb for x in ["客戶留存", "常一起購買", "RFM"]),
                  "leaked: " + ", ".join(x for x in ["客戶留存", "常一起購買", "RFM"] if x in sb))
            check("S6 semi keeps applicable analyses (連續下滑/變化分解/業務摘要)",
                  all(x in sb for x in ["連續下滑", "變化分解", "業務摘要"]))

            # S7 — semi 資料工作區 → 新增資料 tab: calc dataset = fab blocks, no retail leak
            _set_mode(pg, "資料")
            _click_tab(pg, "新增資料")
            _open_main_expander(pg, "新增計算欄位")
            mt = _main_text(pg)
            check("S7 semi workspace: fab blocks present, no retail leak",
                  (("process_move_fact" in mt) or ("tool_dim" in mt))
                  and ("retail_sales" not in mt) and ("store_staffing" not in mt))

            # S8 — semi ask box placeholder is fab-flavoured (no retail terms)
            _set_mode(pg, "探索")
            ph = (pg.locator("textarea").first.get_attribute("placeholder") or "")
            check("S8 semi placeholder data-driven (no retail terms)",
                  all(t not in ph for t in ["營收", "商品", "客戶", "門市"]), ph[:60])

            # S9 — drag-drop field-well renders for a selected visual
            _select_first_visual(pg)
            found_well = False
            for fr in pg.frames:
                try:
                    if fr.locator("text=可用欄位").count() > 0:
                        found_well = fr.locator('[draggable="true"]').count() > 0
                        break
                except Exception:
                    pass
            check("S9 drag-drop field-well renders (draggable chips)", found_well)

            # S10 — right-hand Visualizations pane present
            check("S10 Visualizations pane present",
                  pg.get_by_text("視覺化").count() > 0 or pg.get_by_text("正在編輯").count() > 0)

            br.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== E2E: {passed}/{len(results)} scenarios passed ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
