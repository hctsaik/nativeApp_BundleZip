"""Round 111: scheduled digest delivery with a pluggable transport."""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.report.retail_template import build_retail_sales_block
from ai4bi.report.scheduler import (
    DigestSchedule, FileOutboxTransport, InMemoryTransport, build_digest, run_digest,
)


def _ctx():
    contracts = {"retail_sales": build_retail_sales_block()}
    return Executor(extra_contracts=contracts), contracts


def test_build_digest_returns_subject_and_markdown():
    ex, contracts = _ctx()
    subject, body = build_digest(ex, contracts, period="week")
    assert subject and isinstance(body, str)
    assert body.startswith("#")  # markdown heading


def test_run_digest_delivers_via_transport():
    ex, contracts = _ctx()
    t = InMemoryTransport()
    schedule = DigestSchedule(recipients=["boss@example.com"], frequency="weekly")
    record = run_digest(ex, contracts, schedule, t)
    assert record["sent"] is True
    assert len(t.sent) == 1
    assert t.sent[0]["recipients"] == ["boss@example.com"]
    assert t.sent[0]["subject"] == record["subject"]


def test_disabled_schedule_does_not_send():
    ex, contracts = _ctx()
    t = InMemoryTransport()
    record = run_digest(ex, contracts,
                        DigestSchedule(recipients=["x@y.com"], enabled=False), t)
    assert record["sent"] is False
    assert t.sent == []


def test_no_recipients_does_not_send():
    ex, contracts = _ctx()
    t = InMemoryTransport()
    record = run_digest(ex, contracts, DigestSchedule(recipients=[]), t)
    assert record["sent"] is False


def test_invalid_frequency_raises():
    ex, contracts = _ctx()
    with pytest.raises(ValueError):
        run_digest(ex, contracts,
                   DigestSchedule(recipients=["x@y.com"], frequency="hourly"),
                   InMemoryTransport())


def test_file_outbox_writes_markdown(tmp_path):
    ex, contracts = _ctx()
    t = FileOutboxTransport(tmp_path / "outbox")
    record = run_digest(ex, contracts,
                        DigestSchedule(recipients=["a@b.com"], frequency="daily"), t)
    assert record["sent"]
    files = list((tmp_path / "outbox").glob("digest-*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "To: a@b.com" in text and "Subject:" in text
