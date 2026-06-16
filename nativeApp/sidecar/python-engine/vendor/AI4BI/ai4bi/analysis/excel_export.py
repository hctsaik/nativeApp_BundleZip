"""Excel report export — Round 056.

SMB owners live in Excel and need to forward a workbook (or a monthly report) to
staff. Only CSV existed. build_report_excel() runs every visual's query and
writes one sheet per visual into a single .xlsx (xlsxwriter), reusing the same
post-processing the dashboard applies so the numbers match what's on screen.
"""

from __future__ import annotations

import io
import re

import pandas as pd

from ai4bi.analysis.postprocess import apply_postprocess

_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(title: str, used: set[str]) -> str:
    """Excel sheet names: ≤31 chars, no []:*?/\\, unique."""
    name = _BAD_SHEET_CHARS.sub("", title or "Sheet").strip()[:31] or "Sheet"
    base, i, candidate = name, 1, name
    while candidate in used:
        suffix = f"_{i}"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate)
    return candidate


def build_report_excel(report, executor, active_filters=None) -> bytes:
    """Return a multi-sheet .xlsx (one sheet per visual) of the report's data."""
    buf = io.BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wrote = False
        for page in report.pages.values():
            for vid in page.visual_order:
                visual = page.visuals[vid]
                try:
                    df = executor.run(visual.query, active_filters)
                    df = apply_postprocess(df, visual.query, visual.visualization)
                except Exception:  # noqa: BLE001 — skip a failing visual, keep the rest
                    continue
                if df is None or df.empty:
                    continue
                sheet = _sheet_name(visual.visualization.title or vid, used)
                df.to_excel(writer, sheet_name=sheet, index=False)
                wrote = True
        if not wrote:
            pd.DataFrame({"訊息": ["目前沒有可匯出的資料"]}).to_excel(
                writer, sheet_name="報表", index=False
            )
    return buf.getvalue()
