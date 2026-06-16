"""Round 176 (Phase 3): REST/Service connector safety (scenario S6).

A user-supplied API URL is an SSRF vector. These tests pin the guard rails:
only public http(s) hosts are allowed; localhost / private / link-local (incl.
the cloud-metadata endpoint) are refused; header parsing is forgiving. No
network I/O — numeric hosts resolve to themselves via getaddrinfo.
"""

from __future__ import annotations

import pytest

from ai4bi.ui.connector_panel import (
    _ip_is_blocked, validate_fetch_url, safe_fetch_json, _parse_headers,
    validate_db_target, _execute_with_timeout, _pg_dsn,
)


@pytest.mark.parametrize("ip,blocked", [
    ("127.0.0.1", True),       # loopback
    ("10.0.0.1", True),        # private
    ("192.168.1.1", True),     # private
    ("172.16.0.1", True),      # private
    ("169.254.169.254", True), # link-local — cloud metadata SSRF target
    ("::1", True),             # ipv6 loopback
    ("0.0.0.0", True),         # unspecified
    ("8.8.8.8", False),        # public
    ("1.1.1.1", False),        # public
    ("not-an-ip", True),       # unparseable → fail closed
])
def test_ip_is_blocked(ip, blocked):
    assert _ip_is_blocked(ip) is blocked


@pytest.mark.parametrize("url", [
    "ftp://example.com/data",        # wrong scheme
    "file:///etc/passwd",            # wrong scheme
    "http://127.0.0.1/x",            # loopback
    "http://169.254.169.254/meta",   # cloud metadata
    "http://10.1.2.3/data",          # private
    "https://192.168.0.5/api",       # private
    "not-a-url",                     # no scheme/host
    "",                              # empty
])
def test_unsafe_urls_rejected(url):
    ok, reason = validate_fetch_url(url)
    assert ok is False
    assert reason  # a human-readable zh reason is given


@pytest.mark.parametrize("url", [
    "https://8.8.8.8/data.json",   # public IP (numeric → no DNS)
    "http://1.1.1.1/v1/records",
])
def test_public_urls_allowed(url):
    ok, reason = validate_fetch_url(url)
    assert ok is True
    assert reason == ""


def test_safe_fetch_json_refuses_blocked_url_before_io():
    # Must raise on validation (no socket opened) for a private address.
    with pytest.raises(ValueError):
        safe_fetch_json("http://127.0.0.1:9/should-not-connect")


def test_parse_headers():
    text = "Authorization: Bearer abc123\nX-Env: prod\n\nbad line no colon\n: novalue"
    assert _parse_headers(text) == {"Authorization": "Bearer abc123", "X-Env": "prod"}
    assert _parse_headers("") == {}


# --- DB target validation (the remote-URL connector is an SSRF vector too) ---

def test_db_url_branch_blocks_metadata_endpoint():
    ok, _ = validate_db_target({"type": "url", "url": "http://169.254.169.254/x.csv"})
    assert ok is False


def test_db_url_branch_allows_public():
    ok, reason = validate_db_target({"type": "url", "url": "https://8.8.8.8/data.csv"})
    assert ok is True and reason == ""


def test_db_url_rejects_quote_injection():
    ok, _ = validate_db_target({"type": "url", "url": "https://8.8.8.8/x.csv'--"})
    assert ok is False


def test_db_postgres_rejects_dsn_injection():
    ok, _ = validate_db_target({
        "type": "postgresql", "host": "localhost", "dbname": "d",
        "user": "u", "password": "p'; ATTACH evil", "port": "5432",
    })
    assert ok is False


@pytest.mark.parametrize("host", [
    "foo\\",                    # trailing backslash → would escape the closing quote
    "foo\\ sslmode=disable",    # backslash + injected param
    "foo bar' options=x",       # quote breakout
])
def test_db_postgres_rejects_backslash_and_quote_escapes(host):
    # libpq treats \' inside a quoted value as a literal quote, so a lone
    # backslash must be rejected or it can break out of _pg_dsn's quoting.
    ok, _ = validate_db_target({
        "type": "postgresql", "host": host, "dbname": "d",
        "user": "u", "password": "p", "port": "5432",
    })
    assert ok is False


def test_db_postgres_localhost_is_allowed():
    # a DB on localhost/LAN is the NORMAL case — must NOT be blocked
    ok, reason = validate_db_target({
        "type": "postgresql", "host": "localhost", "dbname": "d",
        "user": "u", "password": "p", "port": "5432",
    })
    assert ok is True and reason == ""


# --- query timeout wrapper ------------------------------------------------

class _FakeConn:
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.interrupted = False

    def execute(self, _q):
        import time
        time.sleep(self.delay)
        return self

    def df(self):
        return "DF"

    def interrupt(self):
        self.interrupted = True


def test_execute_with_timeout_returns_fast_result():
    assert _execute_with_timeout(_FakeConn(0.0), "SELECT 1", timeout=5) == "DF"


def test_execute_with_timeout_interrupts_slow_query():
    conn = _FakeConn(delay=2.0)
    with pytest.raises(TimeoutError):
        _execute_with_timeout(conn, "SELECT 1", timeout=1)
    assert conn.interrupted is True


def test_pg_dsn_quotes_values_to_block_param_injection():
    # A host with a space must be contained inside quotes, not become extra
    # libpq params (e.g. sslmode=disable). Quoting neutralizes the injection.
    dsn = _pg_dsn({"host": "localhost sslmode=disable", "port": "5432",
                   "dbname": "d", "user": "u", "password": "p"})
    assert dsn.startswith("host='localhost sslmode=disable'")
    assert "dbname='d'" in dsn and "password='p'" in dsn
