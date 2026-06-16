"""Tests for Round 035: Dynamic NL2 SchemaIndex."""
from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.ai.schema_index import SchemaIndex
from ai4bi.ui.upload import infer_block


def _retail_contracts():
    df = pd.DataFrame({
        "store_name": ["A", "B", "C"],
        "city": ["Taipei", "Taichung", "Kaohsiung"],
        "category": ["Apparel", "Apparel", "Accessories"],
        "revenue": [1000.0, 2000.0, 1500.0],
        "order_count": [10, 20, 15],
        "return_rate": [0.05, 0.03, 0.07],
        "order_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
    })
    contract, _, _ = infer_block(df, "retail_sales", "retail.csv")
    return {"retail_sales": contract}


# ---------- SchemaIndex construction ----------

def test_schema_index_builds_from_contracts():
    idx = SchemaIndex.build(_retail_contracts())
    assert idx is not None


def test_find_dim_by_column_name():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_dim("store_name")
    assert entry is not None
    assert entry.column_name == "store_name"
    assert entry.block_id == "retail_sales"


def test_find_dim_by_token():
    """Single token 'store' should resolve to store_name."""
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_dim("store")
    assert entry is not None
    assert entry.block_id == "retail_sales"


def test_find_dim_by_zh_alias():
    """Chinese synonym '門市' should resolve to store_name via EN_TO_ZH table."""
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_dim("門市")
    assert entry is not None
    assert entry.column_name == "store_name"


def test_find_dim_city():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_dim("city")
    assert entry is not None
    assert entry.column_name == "city"


def test_find_dim_category_zh():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_dim("品類")
    assert entry is not None
    assert entry.column_name == "category"


def test_find_dim_date_col():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_dim("order_date")
    assert entry is not None
    assert entry.column_name == "order_date"


def test_find_metric_by_name():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_metric("revenue")
    assert entry is not None
    assert entry.metric_name == "revenue"
    assert entry.block_id == "retail_sales"


def test_find_metric_zh_alias():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.find_metric("收入")
    assert entry is not None
    assert entry.metric_name == "revenue"


def test_best_dim_match_in_prompt():
    idx = SchemaIndex.build(_retail_contracts())
    entry = idx.best_dim_match("按門市分析", "按門市分析")
    assert entry is not None
    assert entry.column_name == "store_name"


# ---------- NL2 integration ----------

def test_nl2_categorical_dimension_change_dynamic():
    """NL2 should accept 'group by store' for user-uploaded retail data."""
    from ai4bi.ai.nl2proposal import NL2ProposalService
    from ai4bi.report.models import (
        AuditMetadata, ExecutableReportSpec, ReportPageSpec, ReportVisualSpec,
    )
    from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec, VisualizationSpec, VisualType

    contracts = _retail_contracts()
    svc = NL2ProposalService()

    spec = VisualQuerySpec("bar_rev", [BlockRef("retail_sales")],
                           metrics=[MetricRef("retail_sales", "revenue", "Revenue")])
    viz = VisualizationSpec(VisualType.bar_chart, title="Revenue")
    visual = ReportVisualSpec("bar_rev", spec, viz)
    page = ReportPageSpec("main", "Overview", {"bar_rev": visual}, ["bar_rev"])
    report = ExecutableReportSpec(
        audit=AuditMetadata(report_id="test", created_by="tester"),
        title="Test",
        semantic_model_ref="test@1",
        status="user_draft",
        pages={"main": page},
        controls={},
    )

    result = svc.propose("按門市分析", report, "bar_rev", semantic_model={}, contracts=contracts)
    # Should NOT be unsupported
    assert result.proposal is not None, f"Expected proposal, got: {result.message}"


def test_nl2_unsupported_falls_back_when_no_match():
    """When no dim matches, NL2 should gracefully return unsupported."""
    from ai4bi.ai.nl2proposal import NL2ProposalService
    from ai4bi.report.models import (
        AuditMetadata, ExecutableReportSpec, ReportPageSpec, ReportVisualSpec,
    )
    from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec, VisualizationSpec, VisualType

    contracts = _retail_contracts()
    svc = NL2ProposalService()

    spec = VisualQuerySpec("bar_rev", [BlockRef("retail_sales")],
                           metrics=[MetricRef("retail_sales", "revenue", "Revenue")])
    viz = VisualizationSpec(VisualType.bar_chart, title="Revenue")
    visual = ReportVisualSpec("bar_rev", spec, viz)
    page = ReportPageSpec("main", "Overview", {"bar_rev": visual}, ["bar_rev"])
    report = ExecutableReportSpec(
        audit=AuditMetadata(report_id="test", created_by="tester"),
        title="Test",
        semantic_model_ref="test@1",
        status="user_draft",
        pages={"main": page},
        controls={},
    )

    result = svc.propose(
        "group by xyzzy_nonexistent", report, "bar_rev",
        semantic_model={}, contracts=contracts,
    )
    assert result.proposal is None  # No match → unsupported is fine
