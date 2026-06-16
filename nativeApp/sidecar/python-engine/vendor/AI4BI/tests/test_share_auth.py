"""Round 064: password-protected read-only shares."""

from __future__ import annotations

from ai4bi.report.share_auth import hash_password, verify_password
from ai4bi.report.retail_template import build_retail_demo_report
from ai4bi.report.models import ExecutableReportSpec
from dataclasses import replace


def test_hash_is_deterministic_and_not_plaintext():
    h = hash_password("secret123")
    assert h == hash_password("secret123")
    assert "secret123" not in h
    assert len(h) == 64  # sha256 hex


def test_verify_correct_and_wrong():
    h = hash_password("öpen sesame")
    assert verify_password("öpen sesame", h)
    assert not verify_password("wrong", h)


def test_verify_none_hash_is_false():
    assert not verify_password("anything", None)
    assert not verify_password("", "")


def test_share_password_hash_survives_serialization():
    report = build_retail_demo_report()
    protected = replace(report, share_password_hash=hash_password("pw"))
    roundtrip = ExecutableReportSpec.from_dict(protected.to_dict())
    assert roundtrip.share_password_hash == hash_password("pw")
    assert verify_password("pw", roundtrip.share_password_hash)


def test_default_report_has_no_share_password():
    report = build_retail_demo_report()
    assert report.share_password_hash is None
    # old drafts without the key still load
    payload = report.to_dict()
    del payload["share_password_hash"]
    assert ExecutableReportSpec.from_dict(payload).share_password_hash is None
