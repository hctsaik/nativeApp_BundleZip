"""Round 056: multi-sheet Excel report export.

openpyxl isn't installed for *reading* xlsx, so we verify the bytes structurally
(xlsx is a zip): valid archive + one worksheet part per exported visual.
"""

from __future__ import annotations

import zipfile

from ai4bi.analysis.excel_export import _sheet_name, build_report_excel
from ai4bi.analysis.executor import Executor
from ai4bi.report.retail_template import (
    build_retail_demo_report, build_retail_sales_block, build_store_staffing_block,
)


def _worksheet_count(xlsx: bytes) -> int:
    with zipfile.ZipFile(__import__("io").BytesIO(xlsx)) as z:
        return sum(
            1 for n in z.namelist()
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        )


def _executor():
    return Executor(extra_contracts={
        "retail_sales": build_retail_sales_block(),
        "store_staffing": build_store_staffing_block(),
    })


def test_export_is_valid_xlsx_with_multiple_sheets():
    report = build_retail_demo_report()
    xlsx = build_report_excel(report, _executor())
    assert xlsx[:2] == b"PK"             # zip magic → valid xlsx
    assert _worksheet_count(xlsx) >= 5   # retail demo has many visuals


def test_export_never_empty_workbook():
    """A report whose visuals all fail still yields a valid one-sheet workbook."""
    class _Visual:
        from types import SimpleNamespace
    # minimal fake report with no pages
    class _Report:
        pages: dict = {}
        class audit:  # noqa: N801
            report_id = "empty"
    xlsx = build_report_excel(_Report(), _executor())
    assert xlsx[:2] == b"PK"
    assert _worksheet_count(xlsx) == 1


def test_sheet_name_sanitizes_truncates_dedupes():
    used: set[str] = set()
    a = _sheet_name("Sales: [2026]/Q1*", used)
    assert ":" not in a and "[" not in a and "/" not in a and "*" not in a
    assert len(a) <= 31
    long = _sheet_name("x" * 40, used)
    assert len(long) <= 31
    dup = _sheet_name("x" * 40, used)        # same base → must dedupe
    assert dup != long and len(dup) <= 31
