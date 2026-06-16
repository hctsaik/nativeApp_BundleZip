"""Round 097: NL route to weekly digest + anomaly detection."""

from __future__ import annotations

import pandas as pd

from ai4bi.ai.nl2proposal import NL2ProposalService, _looks_like_insights
from ai4bi.analysis.executor import Executor
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


def _ctx():
    contracts = {"retail_sales": build_retail_sales_block()}
    return (NL2ProposalService(), build_retail_demo_report(), contracts,
            Executor(extra_contracts=contracts))


def test_detector_classifies():
    assert _looks_like_insights("給我本週摘要", "給我本週摘要") == "digest"
    assert _looks_like_insights("有什麼異常嗎", "有什麼異常嗎") == "anomaly"
    assert _looks_like_insights("summary please", "summary please") == "digest"
    assert _looks_like_insights("營收多少", "營收多少") is None


def test_digest_returns_table():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("給我本週重點摘要", report, None, contracts=contracts, executor=ex)
    assert result.result_table is not None, result.message
    assert isinstance(result.result_table, pd.DataFrame)
    assert "重點" in result.result_table.columns
    assert not result.result_table.empty


def test_anomaly_returns_table_or_clean_message():
    svc, report, contracts, ex = _ctx()
    result = svc.propose("有什麼異常嗎？", report, None, contracts=contracts, executor=ex)
    # either a table of anomalies, or a clean "no anomalies" message — never a crash
    if result.result_table is not None:
        assert "說明" in result.result_table.columns
    else:
        assert "異常" in result.message or "👍" in result.message


def test_anomaly_works_without_executor():
    # detect_anomalies needs only contracts, not the executor
    svc, report, contracts, _ = _ctx()
    result = svc.propose("哪裡有問題嗎", report, None, contracts=contracts, executor=None)
    assert result.result_table is not None or "異常" in result.message or "👍" in result.message


def test_digest_needs_executor():
    svc, report, contracts, _ = _ctx()
    result = svc.propose("給我整體概況", report, None, contracts=contracts, executor=None)
    # digest needs the executor → falls through (no table)
    assert result.result_table is None
