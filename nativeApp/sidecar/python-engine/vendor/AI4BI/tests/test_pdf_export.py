"""Round 075: PDF report export (matplotlib PdfPages, no extra deps)."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.analysis.pdf_export import build_report_pdf
from ai4bi.report.retail_template import (
    build_retail_demo_report, build_retail_sales_block, build_store_staffing_block,
)


def _executor():
    return Executor(extra_contracts={
        "retail_sales": build_retail_sales_block(),
        "store_staffing": build_store_staffing_block(),
    })


def test_pdf_is_valid_and_nonempty():
    pdf = build_report_pdf(build_retail_demo_report(), _executor())
    assert pdf[:5] == b"%PDF-"          # PDF magic
    assert len(pdf) > 5000               # real content, not an empty shell


def test_pdf_has_multiple_pages():
    pdf = build_report_pdf(build_retail_demo_report(), _executor())
    # crude page count: number of '/Type /Page' (not /Pages) markers
    n = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    assert n >= 3   # cover + several visuals


def test_pdf_empty_report_is_valid():
    class _Report:
        pages: dict = {}
        class audit:  # noqa: N801
            report_id = "empty"
        title = "Empty"
    pdf = build_report_pdf(_Report(), _executor())
    assert pdf[:5] == b"%PDF-"
