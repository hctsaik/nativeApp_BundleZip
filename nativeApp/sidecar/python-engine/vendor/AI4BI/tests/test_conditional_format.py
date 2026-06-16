"""Round 053: KPI RAG status + table threshold conditional formatting."""

from __future__ import annotations

import pandas as pd

from ai4bi.ui.components.kpi_card import _rag_status


# ── KPI RAG ─────────────────────────────────────────────────────────────────

def test_rag_higher_is_better_green_amber_red():
    rag = {"good_if": "gte", "target": 100, "warn": 80}
    assert _rag_status(120, rag)[0] == "🟢"
    assert _rag_status(90, rag)[0] == "🟡"
    assert _rag_status(50, rag)[0] == "🔴"


def test_rag_lower_is_better():
    rag = {"good_if": "lte", "target": 0.06, "warn": 0.10}
    assert _rag_status(0.05, rag)[0] == "🟢"
    amber = _rag_status(0.08, rag)
    assert amber[0] == "🟡"
    # ratio thresholds must keep decimals, not round to 0
    assert "0.1" in amber[1]
    assert _rag_status(0.15, rag)[0] == "🔴"


def test_rag_without_warn_band():
    rag = {"good_if": "gte", "target": 100}
    assert _rag_status(120, rag)[0] == "🟢"
    assert _rag_status(50, rag)[0] == "🔴"


def test_rag_none_when_no_target_or_nan():
    assert _rag_status(10, {}) is None
    assert _rag_status(float("nan"), {"target": 5}) is None


# ── Table threshold mask (the logic mirrored from data_table) ────────────────

def test_threshold_mask_gt():
    series = pd.Series([0.05, 0.09, 0.12])
    mask = series > 0.08
    assert list(mask) == [False, True, True]


def test_retail_demo_wires_rag_and_threshold():
    from ai4bi.report.retail_template import build_retail_demo_report
    report = build_retail_demo_report()
    visuals = report.pages["main"].visuals
    assert visuals["kpi_return_rate"].visualization.extra.get("rag", {}).get("good_if") == "lte"
    cfs = visuals["table_top_products"].visualization.extra.get("conditional_formats", [])
    assert any(c.get("method") == "threshold" for c in cfs)
