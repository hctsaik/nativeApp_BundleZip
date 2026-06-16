"""External Database Connector Panel — Round 043.

Allows users to connect to external data sources without writing code.
Supported connectors:
  - DuckDB file (.duckdb / .db) — local, no credentials needed
  - SQLite file (.sqlite / .db) — local, no credentials needed
  - PostgreSQL — host/port/dbname/user/password
  - CSV/Parquet URL — remote file over HTTPS

When connected, the user selects a table → the system generates a
DataBlockContract with ExternalDataSource pointing to the connection,
then registers it so NL2/executor can query it.

For the MVP, we execute the actual query via DuckDB's native connectors
and cache the result as an InlineDataSource (up to 50K rows), which is the
most compatible path with the current executor architecture.
"""

from __future__ import annotations

import io
from typing import Optional

import streamlit as st

from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, LifecycleStatus, MetricDefinition, PolicySpec,
)
from ai4bi.ui.upload import (
    _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY, _PENDING_NEW_BLOCK_KEY, infer_block, _slugify,
    json_record_paths, json_to_dataframe, _get_json_path, nested_json_columns,
)

_CONN_STATE_KEY = "db_connections"
_MAX_ROWS = 50_000

# ── REST / Service fetch with SSRF guards (Round 176) ───────────────────────
# A user-supplied URL is an SSRF vector: it could point at localhost, a private
# subnet, or the cloud metadata endpoint (169.254.169.254). We resolve the host
# and refuse any non-public address, allow only http(s), cap the response size,
# enforce a timeout, and do NOT follow redirects (a redirect could jump to a
# blocked host). Pure validation helpers are unit-tested without network I/O.
_REST_TIMEOUT_S = 15
_REST_MAX_BYTES = 64 * 1024 * 1024  # 64 MB hard cap on the response body


def _ip_is_blocked(ip_str: str) -> bool:
    import ipaddress
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → fail closed
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def validate_fetch_url(url: str) -> tuple[bool, str]:
    """Return (ok, reason). Allows only http(s) to a publicly-routable host."""
    import socket
    from urllib.parse import urlparse
    try:
        p = urlparse(url.strip())
    except Exception:  # noqa: BLE001
        return False, "無法解析這個網址。"
    if p.scheme not in ("http", "https"):
        return False, "只允許 http / https 連結。"
    if not p.hostname:
        return False, "網址缺少主機名稱。"
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except Exception:  # noqa: BLE001
        return False, "無法解析主機位址。"
    if any(_ip_is_blocked(ai[4][0]) for ai in infos):
        return False, "基於安全，禁止連往內部／私有網路位址（含 localhost 與雲端 metadata）。"
    return True, ""


def safe_fetch_json(url: str, headers: "dict | None" = None,
                    *, timeout: int = _REST_TIMEOUT_S, max_bytes: int = _REST_MAX_BYTES):
    """Fetch + parse JSON from a validated public URL (no redirects, size-capped)."""
    import json as _json
    import urllib.request
    ok, reason = validate_fetch_url(url)
    if not ok:
        raise ValueError(reason)

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ANN001, ARG002
            return None  # refuse redirects (could jump to a blocked host)

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url.strip(), headers=headers or {})
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("回應內容過大，已中止下載。")
    return _json.loads(raw.decode("utf-8", errors="replace"))


def _reject_injection(*vals) -> "str | None":
    """Return a zh reason if any value has chars that could break out of the
    single-quoted ATTACH DSN / path string; else None.

    Backslash is rejected too: libpq treats ``\\'`` inside a quoted DSN value as a
    LITERAL quote, so allowing ``\\`` would let a trailing backslash escape the
    closing quote and inject extra connection parameters. With both ``'`` and
    ``\\`` banned, a value can never break out of its single-quote wrapping."""
    for v in vals:
        if v and any(ch in str(v) for ch in ("'", "\\", ";", "\n", "\r")):
            return "連線參數包含不允許的字元（' \\ ; 或換行）。"
    return None


def validate_db_target(conn_info: dict) -> tuple[bool, str]:
    """Validate a connection target before we touch it.

    The remote-URL connector is a genuine SSRF vector (it fetches an arbitrary
    URL like the REST connector), so it gets the full public-host check. A
    PostgreSQL host is an *authenticated DB* and is normally on localhost / the
    LAN, so we do NOT block private hosts there — we only reject characters that
    could inject into the ATTACH string. Local files are fine.
    """
    t = conn_info.get("type")
    if t == "url":
        url = conn_info.get("url", "")
        if "'" in url:
            return False, "網址包含不允許的字元（'）。"
        return validate_fetch_url(url)
    if t == "postgresql":
        bad = _reject_injection(
            conn_info.get("host"), conn_info.get("dbname"), conn_info.get("user"),
            conn_info.get("password"), conn_info.get("port"),
        )
        return (False, bad) if bad else (True, "")
    if t == "sqlite":
        return (False, _reject_injection(conn_info.get("path"))) if _reject_injection(
            conn_info.get("path")) else (True, "")
    return True, ""


def _pg_dsn(conn_info: dict) -> str:
    """Build a libpq DSN with every value single-quoted, so a value containing a
    space or '=' (e.g. host="localhost sslmode=disable") can't inject extra
    connection parameters. Values containing a single quote are already rejected
    upstream by validate_db_target, so the quoting can't be broken out of."""
    return (
        f"host='{conn_info['host']}' port='{conn_info['port']}' "
        f"dbname='{conn_info['dbname']}' user='{conn_info['user']}' "
        f"password='{conn_info['password']}'"
    )


def _execute_with_timeout(conn, query: str, timeout: int = 30):
    """Run conn.execute(query).df() with a wall-clock timeout; on timeout,
    interrupt the connection so a slow query can't freeze the whole session."""
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(lambda: conn.execute(query).df())
        try:
            return fut.result(timeout=timeout)
        except _cf.TimeoutError:
            try:
                conn.interrupt()
            except Exception:  # noqa: BLE001
                pass
            raise TimeoutError(f"查詢超過 {timeout} 秒，已中止（避免卡住整個畫面）。")


def _execute_duckdb_query(conn_info: dict, query: str) -> "pd.DataFrame":
    """Execute a query using DuckDB and return a DataFrame (validated + timed)."""
    import duckdb

    ok, reason = validate_db_target(conn_info)
    if not ok:
        raise ValueError(reason)

    conn_type = conn_info.get("type")
    if conn_type == "duckdb_file":
        conn = duckdb.connect(conn_info["path"], read_only=True)
        return _execute_with_timeout(conn, query)
    elif conn_type == "sqlite":
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute(f"ATTACH '{conn_info['path']}' (TYPE sqlite, READ_ONLY);")
        return _execute_with_timeout(conn, query)
    elif conn_type == "postgresql":
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL postgres; LOAD postgres;")
        conn.execute(f"ATTACH '{_pg_dsn(conn_info)}' AS pg (TYPE postgres, READ_ONLY);")
        return _execute_with_timeout(conn, query)
    elif conn_type == "url":
        conn = duckdb.connect(":memory:")
        url = conn_info["url"]
        reader = "read_parquet" if url.endswith(".parquet") else "read_csv"
        return _execute_with_timeout(conn, f"SELECT * FROM {reader}('{url}') LIMIT {_MAX_ROWS}")
    raise ValueError(f"Unknown connector type: {conn_type}")


def _list_tables(conn_info: dict) -> list[str]:
    """List available tables from a connection."""
    import duckdb
    ok, reason = validate_db_target(conn_info)
    if not ok:
        st.error(f"連線設定無效：{reason}")
        return []
    try:
        conn_type = conn_info.get("type")
        if conn_type == "duckdb_file":
            conn = duckdb.connect(conn_info["path"], read_only=True)
            return [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        elif conn_type == "sqlite":
            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            conn.execute(f"ATTACH '{conn_info['path']}' (TYPE sqlite, READ_ONLY);")
            tables = conn.execute("SHOW ALL TABLES").fetchdf()
            return tables["name"].tolist() if not tables.empty else []
        elif conn_type == "postgresql":
            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL postgres; LOAD postgres;")
            conn.execute(f"ATTACH '{_pg_dsn(conn_info)}' AS pg (TYPE postgres, READ_ONLY);")
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchdf()
            return tables["table_name"].tolist() if not tables.empty else []
    except Exception as exc:  # noqa: BLE001
        st.error(f"連線錯誤：{exc}")
    return []


def _parse_headers(text: str) -> dict:
    """Parse a 'Name: Value' per-line textarea into a headers dict."""
    headers: dict = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip():
            headers[k.strip()] = v.strip()
    return headers


def _register_block(df, block_id: str, display_name: str, source: str) -> None:
    """Register a fetched/imported/derived DataFrame as a user block (shared by
    REST / DB / create-data). Caps rows here as a safety net so EVERY path that
    lands a block is bounded (the union creator can produce N×source rows)."""
    import datetime as _dt
    if len(df) > _MAX_ROWS:
        df = df.head(_MAX_ROWS)
    contract, metric_names, dim_names = infer_block(df, block_id, display_name)
    st.session_state.setdefault(_USER_BLOCKS_KEY, {})
    st.session_state.setdefault(_USER_BLOCK_META_KEY, {})
    st.session_state[_USER_BLOCKS_KEY][block_id] = contract
    st.session_state[_USER_BLOCK_META_KEY][block_id] = {
        "metric_names": metric_names, "dim_names": dim_names,
        "display_name": display_name, "row_count": len(df), "source": source,
        "uploaded_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    st.session_state[_PENDING_NEW_BLOCK_KEY] = block_id


def _render_rest_import() -> None:
    """Fetch JSON from a REST service (SSRF-guarded), pick the records path, and
    import it as a block — Round 176. Mirrors the JSON upload flow."""
    from urllib.parse import urlparse
    st.caption("輸入 API 網址，系統會抓取 JSON 並轉成資料表。基於安全，只允許**公開的 http(s)** 位址。")
    url = st.text_input("API 網址", placeholder="https://api.example.com/v1/sales", key="rest_url")
    headers_text = st.text_area(
        "標頭（每行一個「名稱: 值」，選填，例如授權 token）",
        placeholder="Authorization: Bearer xxxxx", key="rest_headers", height=80,
    )
    if st.button("🔍 取得資料", key="rest_fetch_btn"):
        if not url.strip():
            st.warning("請先輸入 API 網址。")
        else:
            with st.spinner("正在取得資料…"):
                try:
                    st.session_state["_rest_obj"] = safe_fetch_json(url, _parse_headers(headers_text))
                    st.session_state["_rest_url"] = url
                    st.success("已取得資料，請於下方選擇要匯入的內容。")
                except Exception as exc:  # noqa: BLE001
                    st.session_state.pop("_rest_obj", None)
                    st.error(f"取得失敗：{exc}")

    obj = st.session_state.get("_rest_obj")
    if obj is None:
        return

    paths = json_record_paths(obj)
    if len(paths) > 1:
        def _label(p: str) -> str:
            if p == "":
                return "最外層（整份就是資料列）"
            try:
                n = len(_get_json_path(obj, p))
            except Exception:  # noqa: BLE001
                n = "?"
            return f"{p}（{n} 筆）"
        path = st.selectbox("資料列在哪裡？", paths, format_func=_label, key="rest_record_path")
    else:
        path = paths[0]
        if path:
            st.caption(f"📍 已自動從 `{path}` 取出資料列。")

    try:
        df = json_to_dataframe(obj, path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"無法把回應轉成表格：{exc}")
        return
    if df.empty:
        st.warning("沒有可轉成表格的資料。")
        return
    _nested = nested_json_columns(df)
    if _nested:
        st.caption("🧩 巢狀欄位（內含多個值，目前以 JSON 文字保存）：" +
                   "、".join(f"`{c}`" for c in _nested))
    if len(df) > _MAX_ROWS:
        st.warning(f"資料有 {len(df):,} 列，已截取前 {_MAX_ROWS:,} 列。")
        df = df.head(_MAX_ROWS)

    st.caption(f"預覽（前 5 列，共 {len(df):,} 列 × {len(df.columns)} 欄）")
    st.dataframe(df.head(5), width="stretch", hide_index=True)

    _seg = (urlparse(st.session_state.get("_rest_url", "")).path.rstrip("/").split("/") or [""])[-1]
    name = st.text_input("這份資料的名稱", value=_slugify(_seg) or "api_data", key="rest_name")
    block_id = _slugify(name) or "api_data"
    if st.button("⬆️ 匯入此資料", key="rest_import_btn", type="primary"):
        _register_block(df, block_id, name, source="rest")
        st.session_state.pop("_rest_obj", None)
        st.success(f"✅ 已匯入「{name}」（{len(df):,} 列）")
        st.rerun()


def render_connector_panel() -> None:
    """Render the Database Connector expander — Round 043."""
    with st.expander("🔌 連接資料庫 / 服務", expanded=False):
        st.caption(
            "直接連接資料庫或網路服務，把資料匯入為可分析的資料集。\n"
            "支援：本機 DuckDB / SQLite 檔案、PostgreSQL、遠端 CSV/Parquet URL、REST/JSON 服務。"
        )

        # Connection type selection
        conn_type = st.selectbox(
            "連線類型",
            ["duckdb_file", "sqlite", "postgresql", "url", "rest"],
            format_func=lambda t: {
                "duckdb_file": "DuckDB 本機檔案 (.duckdb)",
                "sqlite": "SQLite 本機檔案 (.sqlite)",
                "postgresql": "PostgreSQL 伺服器",
                "url": "遠端 CSV / Parquet URL",
                "rest": "REST / JSON 服務 (API)",
            }[t],
            key="conn_type_sel",
        )

        conn_info: dict = {"type": conn_type}

        if conn_type in ("duckdb_file", "sqlite"):
            path = st.text_input("檔案路徑", placeholder="C:/data/my_db.duckdb", key="conn_path")
            conn_info["path"] = path
        elif conn_type == "postgresql":
            col1, col2 = st.columns([3, 1])
            with col1:
                conn_info["host"] = st.text_input("主機", value="localhost", key="pg_host")
                conn_info["dbname"] = st.text_input("資料庫名稱", key="pg_dbname")
                conn_info["user"] = st.text_input("使用者名稱", key="pg_user")
            with col2:
                conn_info["port"] = st.text_input("埠號", value="5432", key="pg_port")
                conn_info["password"] = st.text_input("密碼", type="password", key="pg_pw")
        elif conn_type == "url":
            conn_info["url"] = st.text_input(
                "URL",
                placeholder="https://example.com/data.parquet",
                key="conn_url",
            )
        elif conn_type == "rest":
            _render_rest_import()
            return

        if st.button("🔍 列出資料表", key="conn_list_tables"):
            tables = _list_tables(conn_info)
            if tables:
                st.session_state["_conn_tables"] = tables
                st.session_state["_conn_info"] = conn_info
                st.success(f"找到 {len(tables)} 個資料表。")
            else:
                st.warning("未找到任何資料表，請確認連線設定。")

        # Table picker
        tables = st.session_state.get("_conn_tables", [])
        stored_conn = st.session_state.get("_conn_info", {})
        if tables:
            selected_table = st.selectbox(
                "選擇要匯入的資料表",
                tables,
                key="conn_table_sel",
            )
            preview_limit = 1000
            if st.button("⬆️ 匯入此資料表", key="conn_import_btn", type="primary"):
                with st.spinner(f"正在從資料庫讀取 {selected_table}（最多 {_MAX_ROWS:,} 行）..."):
                    try:
                        query = f'SELECT * FROM "{selected_table}" LIMIT {_MAX_ROWS}'
                        df = _execute_duckdb_query(stored_conn, query)
                        if df.empty:
                            st.warning("資料表是空的。")
                            return
                        block_id = _slugify(selected_table) or "db_table"
                        contract, metric_names, dim_names = infer_block(df, block_id, selected_table)
                        if _USER_BLOCKS_KEY not in st.session_state:
                            st.session_state[_USER_BLOCKS_KEY] = {}
                        if _USER_BLOCK_META_KEY not in st.session_state:
                            st.session_state[_USER_BLOCK_META_KEY] = {}
                        st.session_state[_USER_BLOCKS_KEY][block_id] = contract
                        st.session_state[_USER_BLOCK_META_KEY][block_id] = {
                            "metric_names": metric_names,
                            "dim_names": dim_names,
                            "display_name": selected_table,
                            "row_count": len(df),
                            "source": conn_type,
                        }
                        st.session_state[_PENDING_NEW_BLOCK_KEY] = block_id
                        st.success(
                            f"✅ 已匯入「{selected_table}」（{len(df):,} 行，"
                            f"{len(metric_names)} 個指標，{len(dim_names)} 個維度）"
                        )
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"匯入失敗：{exc}")
