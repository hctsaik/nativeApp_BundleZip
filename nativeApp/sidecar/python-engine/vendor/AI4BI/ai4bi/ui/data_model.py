"""Data Model UI — Round 037/038.

Round 037: Join Builder — lets users connect two uploaded CSV tables by
           selecting a common key column, creating a governed relationship
           stored in session_state["user_semantic_model"].

Round 038: Data Model View — visual table/column browser showing all loaded
           blocks and their declared relationships.

These two features unlock Power BI's core "Relationships" panel, enabling:
- Cross-table visuals (revenue from sales_data, NPS from nps_data)
- Governed joins validated by SafeJoinPlanner
- Visual exploration of the data model before building reports
"""

from __future__ import annotations

import re
from typing import Optional

import streamlit as st

from ai4bi.blocks.contracts import (
    BlockType, DataBlockContract, FanoutRisk, JoinType, RelationshipHint)
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_USER_SEMANTIC_MODEL_KEY = "user_semantic_model"

_SOURCE_BADGE = {
    "duckdb": "🦆 DuckDB", "sqlite": "💾 SQLite", "postgres": "🐘 Postgres",
    "postgresql": "🐘 Postgres", "url": "🌐 URL", "rest": "🌐 REST",
    "derived": "🔄 衍生資料",
}


def _user_loaded_blocks() -> dict[str, DataBlockContract]:
    """Round 156: genuinely user-loaded sources (upload / DB import carry a meta
    entry). Excludes demo blocks seeded into user_blocks, so join/data-model show
    your data — not retail leftovers when you're on another report."""
    meta = st.session_state.get(_USER_BLOCK_META_KEY, {})
    all_blocks = st.session_state.get(_USER_BLOCKS_KEY, {})
    return {bid: c for bid, c in all_blocks.items() if bid in meta}


def _friendly_time(ts: "str | None") -> "str | None":
    """Format a stored 'YYYY-MM-DD HH:MM' upload time as 今天/昨天/日期."""
    if not ts:
        return None
    try:
        import datetime as _dt
        dt = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")
        today = _dt.date.today()
        if dt.date() == today:
            return f"今天 {dt:%H:%M}"
        if dt.date() == today - _dt.timedelta(days=1):
            return f"昨天 {dt:%H:%M}"
        return ts
    except Exception:  # noqa: BLE001
        return ts


def _source_entries(report_sources: dict, meta: dict, uploads: dict,
                    in_use_ids: "set | None" = None) -> dict:
    """Round 176: unified {block_id: entry} of EVERY source powering the report.

    entry = {contract, name, icon, origin, subtitle, removable, status_icon,
    status_label}. Metadata only — builds no frames. Built-in/demo blocks come
    first, then user-loaded (upload / DB import, removable).

    ``status`` distinguishes a source the report actually USES (🟢 報表使用中) from
    one merely loaded and still being checked (🟡 評估中) — a lifecycle STATUS, not
    a separate place. ``in_use_ids`` (block_ids referenced by a report visual) is
    the source of truth; without it, built-in blocks default to in-use.
    """
    def _status(bid: str, default_in_use: bool) -> tuple[str, str]:
        in_use = (bid in in_use_ids) if in_use_ids is not None else default_in_use
        return ("🟢", "報表使用中") if in_use else ("🟡", "評估中")

    entries: dict = {}
    builtin = {bid: c for bid, c in report_sources.items() if bid not in meta}
    for bid, c in builtin.items():
        dot, label = _status(bid, True)
        entries[bid] = {
            "contract": c, "name": getattr(c, "description", None) or bid,
            "icon": "📊", "origin": "📊 內建／示範資料",
            "subtitle": None, "removable": False,
            "status_icon": dot, "status_label": label,
        }
    for bid, c in uploads.items():
        m = meta.get(bid, {})
        origin = _SOURCE_BADGE.get(str(m.get("source", "")).lower(), "📄 上傳檔案")
        up = _friendly_time(m.get("uploaded_at"))
        dot, label = _status(bid, False)
        entries[bid] = {
            "contract": c, "name": m.get("display_name", bid),
            "icon": origin.split()[0] if origin else "📄", "origin": origin,
            "subtitle": f"🕒 載入於 {up}" if up else None, "removable": True,
            "status_icon": dot, "status_label": label,
        }
    return entries


def render_data_source_manager(report_sources: "dict | None" = None,
                               in_use_ids: "set | None" = None) -> None:
    """Round 147/166/176: unified data-source workspace — a master-detail view of
    EVERY source powering the current report.

    Left = a single source list whose selection is **remembered across reruns**
    (you never lose your place); right = the chosen source's schema (shown
    immediately) + an opt-in, resource-safe sampled preview. Replaces the old
    "one expander per source, tick-to-preview" layout where re-previewing meant
    hunting for the card, expanding it, and re-ticking the box every rerun.

    ``report_sources`` is ``{block_id: contract}`` for the blocks the current
    report references (passed from app._report_block_contracts).
    """
    meta: dict = st.session_state.get(_USER_BLOCK_META_KEY, {})
    uploads = _user_loaded_blocks()  # genuinely user-loaded (meta-tracked)
    report_sources = dict(report_sources or {})
    entries = _source_entries(report_sources, meta, uploads, in_use_ids)

    total = len(entries)
    if total == 0:
        st.info(
            "目前沒有資料來源。用「➕ 新增」上傳檔案或連接資料庫加入第一份資料；"
            "加入 2 份以上後，可在「🔗 關聯」把它們關聯起來。",
            icon="📂",
        )
        return

    # Totals are metadata-only (CachedDataSource.row_count) — never load a frame.
    from ai4bi.blocks.datastore import source_row_count
    from ai4bi.ui.data_inspector import render_source_inspector, source_shape

    n_rel = len(get_user_semantic_model().get("relationships", []))
    total_rows, any_known = 0, False
    for e in entries.values():
        rc = source_row_count(e["contract"])
        if rc is not None:
            total_rows += rc
            any_known = True
    rows_txt = f" · 約 {total_rows:,} 列" if any_known else ""
    st.caption(f"**這份報表使用 {total} 個資料來源 · {n_rel} 個關聯{rows_txt}**")

    ids = list(entries.keys())
    # Remember the selected source across reruns (set the widget default BEFORE
    # the radio instantiates; never write its key afterwards).
    if st.session_state.get("_ws_source_sel") not in ids:
        st.session_state["_ws_source_sel"] = ids[0]

    _DOT = {"small": "🟢", "medium": "🟡", "large": "🔴", "unknown": "⚪"}

    def _fmt(bid: str) -> str:
        e = entries[bid]
        sh = source_shape(e["contract"])  # metadata only — no rows loaded
        rc = "?" if sh.row_count is None else f"{sh.row_count:,}"
        return f"{e['status_icon']} {e['name']}　{_DOT[sh.cost_tier]} {sh.n_cols}欄·{rc}列"

    left, right = st.columns([1, 2.4], gap="medium")
    with left:
        st.caption("📂 選擇資料來源　🟢 報表使用中　🟡 評估中")
        chosen = st.radio(
            "資料來源", ids, format_func=_fmt, key="_ws_source_sel",
            label_visibility="collapsed",
        )
    with right:
        e = entries[chosen]
        st.caption(f"{e['status_icon']} **{e['status_label']}**　·　{e['origin']}")
        if e["status_label"] == "評估中":
            st.caption("（這份是你載入、還在確認的資料。看過沒問題後，到「➕ 新增資料 → 從這份資料"
                       "建立新報表」就會開始使用它。）")
        render_source_inspector(
            e["contract"], display_name=e["name"], origin=e["origin"],
            key_prefix=f"ws_{chosen}", subtitle=e.get("subtitle"), embedded=True,
        )
        if e.get("removable"):
            if st.button("🗑 移除此來源", key=f"ws_remove_{chosen}"):
                st.session_state.get(_USER_BLOCKS_KEY, {}).pop(chosen, None)
                st.session_state.get(_USER_BLOCK_META_KEY, {}).pop(chosen, None)
                st.session_state.pop("_ws_source_sel", None)
                st.rerun()

    if total >= 2:
        st.caption("💡 想把多份資料合併分析？到「🔗 關聯」建立關聯（join）。")
    st.divider()


# ---------------------------------------------------------------------------
# User semantic model helpers
# ---------------------------------------------------------------------------

def get_user_semantic_model() -> dict:
    """Return the user-managed semantic model from session_state.

    Merges user-defined relationships with an empty base structure.
    Used by NL2, catalog, and executor to understand cross-table joins.
    """
    sm = st.session_state.get(_USER_SEMANTIC_MODEL_KEY)
    if sm is None:
        sm = {
            "model_id": "user_data_model",
            "version": "1.0.0",
            "label": "使用者資料模型",
            "blocks": [],
            "relationships": [],
            "metrics": [],
            "prohibited_paths": [],
        }
        st.session_state[_USER_SEMANTIC_MODEL_KEY] = sm
    return sm


def _wire_join_contracts(
    fact_block: str, dim_block: str,
    fact_keys: list[str], dim_keys: list[str],
) -> None:
    """Round 183: make a user-built relationship actually EXECUTABLE.

    SafeJoinPlanner only resolves a join when the block CONTRACTS approve it
    (the semantic-model relationship alone isn't enough). For uploaded blocks we
    therefore: mark the TO block as a dimension + ensure its primary_keys cover
    the join targets, and append a LOW-fanout RelationshipHint(allowed_join_keys)
    to the FROM (fact) block. Built-in/demo blocks already ship these on disk and
    aren't in _USER_BLOCKS_KEY, so they're left untouched.
    """
    blocks = st.session_state.get(_USER_BLOCKS_KEY)
    if not isinstance(blocks, dict):
        return
    dim_c = blocks.get(dim_block)
    if dim_c is not None:
        pks = list(getattr(dim_c, "primary_keys", []) or [])
        for k in dim_keys:
            if k not in pks:
                pks.append(k)
        blocks[dim_block] = dim_c.model_copy(
            update={"block_type": BlockType.dimension, "primary_keys": pks})
    fact_c = blocks.get(fact_block)
    if fact_c is not None:
        hints = [h for h in (getattr(fact_c, "relationships", []) or [])
                 if getattr(h, "target_block_id", None) != dim_block]
        hints.append(RelationshipHint(
            target_block_id=dim_block,
            allowed_join_keys=list(fact_keys),
            join_type=JoinType.left,
            fanout_risk=FanoutRisk.LOW,
            description="使用者於『資料關聯設定』建立（取樣判定為 N:1，安全不爆量）。",
        ))
        blocks[fact_block] = fact_c.model_copy(update={"relationships": hints})
    st.session_state[_USER_BLOCKS_KEY] = blocks


def _add_relationship(
    from_block: str,
    to_block: str,
    key_pairs: list[tuple[str, str]],
    *,
    rel_id: Optional[str] = None,
    cardinality: str = "many_to_one",
) -> None:
    """Add a user-defined relationship to the session semantic model and wire up
    the governance the executor needs so the join really runs (Round 183).

    Round 176: ``cardinality`` comes from the detected join shape.
    Round 182: ``key_pairs`` (list of (from_col, to_col)) supports COMPOSITE keys.
    Round 183: normalize the direction to fact(many) → dimension(one) = N:1 (so a
    1:N the user built backwards is auto-corrected), then wire the contracts.
    """
    # Normalize to the only shape a governed BI join should take: fact→dim, N:1.
    if cardinality == "one_to_many":  # user built it backwards → swap
        from_block, to_block = to_block, from_block
        key_pairs = [(t, f) for (f, t) in key_pairs]
        cardinality = "many_to_one"
    elif cardinality == "one_to_one":
        cardinality = "many_to_one"  # 1:1 is safe; treat TO as the dimension side

    from_cols = [f for f, _ in key_pairs]
    to_cols = [t for _, t in key_pairs]
    sm = get_user_semantic_model()
    rel_id = rel_id or f"user_{from_block}_to_{to_block}_{'_'.join(from_cols)}"
    # Remove any existing relationship with same id
    sm["relationships"] = [r for r in sm["relationships"] if r.get("relationship_id") != rel_id]
    sm["relationships"].append({
        "relationship_id": rel_id,
        "from_block": from_block,
        "to_block": to_block,
        "keys": [{"from": f, "to": t} for f, t in key_pairs],
        "cardinality": cardinality,
        "join_type": "left",
        "status": "certified",  # user-defined = trusted for their own data
    })
    # Update blocks list
    for bid in (from_block, to_block):
        if bid not in sm["blocks"]:
            sm["blocks"].append(bid)
    # Only a safe N:1 gets the contract wiring; N:N / 未知 stay un-executable on
    # purpose (a fan-out join must not silently inflate the numbers).
    if cardinality == "many_to_one":
        _wire_join_contracts(from_block, to_block, from_cols, to_cols)


def _remove_relationship(rel_id: str) -> None:
    sm = get_user_semantic_model()
    sm["relationships"] = [r for r in sm["relationships"] if r.get("relationship_id") != rel_id]


def _auto_detect_join_cols(
    block_a: DataBlockContract,
    block_b: DataBlockContract,
) -> list[tuple[str, str, float]]:
    """Find common column pairs between two blocks and score them.

    Returns list of (col_a, col_b, confidence_score) sorted by score desc.
    """
    a_cols = {c.name.lower(): c.name for c in block_a.columns}
    b_cols = {c.name.lower(): c.name for c in block_b.columns}

    matches: list[tuple[str, str, float]] = []

    # Exact name matches
    for lower_a, orig_a in a_cols.items():
        if lower_a in b_cols:
            orig_b = b_cols[lower_a]
            score = 1.0
            matches.append((orig_a, orig_b, score))

    # Fuzzy: strip common suffixes and match
    _STRIP = re.compile(r"(_id|_key|_code|_no|_num|_name)$", re.I)
    _exact = {(a, b) for a, b, _ in matches}
    for lower_a, orig_a in a_cols.items():
        stem_a = _STRIP.sub("", lower_a)
        for lower_b, orig_b in b_cols.items():
            stem_b = _STRIP.sub("", lower_b)
            if stem_a == stem_b and (orig_a, orig_b) not in _exact:
                matches.append((orig_a, orig_b, 0.7))

    # Round 178: qualified-synonym keys — one stem is a suffix/substring of the
    # other (tool_id ↔ etch_tool_id, lot_id ↔ parent_lot_id). Lower confidence so
    # the UI asks the user to confirm. Skip generic 1-2 char stems to avoid noise.
    for lower_a, orig_a in a_cols.items():
        stem_a = _STRIP.sub("", lower_a)
        for lower_b, orig_b in b_cols.items():
            stem_b = _STRIP.sub("", lower_b)
            if (stem_a and stem_b and stem_a != stem_b
                    and min(len(stem_a), len(stem_b)) >= 3
                    and (stem_a.endswith(stem_b) or stem_b.endswith(stem_a)
                         or stem_a in stem_b or stem_b in stem_a)
                    and (orig_a, orig_b) not in _exact
                    and not any(m[0] == orig_a and m[1] == orig_b for m in matches)):
                matches.append((orig_a, orig_b, 0.6))

    # Deduplicate and sort
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str, float]] = []
    for a, b, score in sorted(matches, key=lambda x: -x[2]):
        if (a, b) not in seen:
            seen.add((a, b))
            unique.append((a, b, score))
    return unique[:10]


# ── Cardinality detection (Round 176) ──────────────────────────────────────
# Map a display label to the semantic-model cardinality string (and back).
_CARD_TO_SEMANTIC = {
    "1:1": "one_to_one", "N:1": "many_to_one",
    "1:N": "one_to_many", "N:N": "many_to_many",
}
_SEMANTIC_TO_CARD = {v: k for k, v in _CARD_TO_SEMANTIC.items()}


def cardinality_from_keys(left_unique: "bool | None",
                          right_unique: "bool | None") -> tuple[str, bool]:
    """Pure: per-side key-uniqueness → (label, is_risky).

    label ∈ {"1:1","N:1","1:N","N:N","未知"}. N:N (neither side unique) is the
    fanout-risk case a non-technical user must be warned about; "未知" (a side
    could not be sampled) is also flagged so we don't silently assume safety.
    """
    if left_unique is None or right_unique is None:
        return "未知", True
    if left_unique and right_unique:
        return "1:1", False
    if not left_unique and right_unique:
        return "N:1", False
    if left_unique and not right_unique:
        return "1:N", False
    return "N:N", True


def compare_columns(cols_a: list[str], cols_b: list[str]) -> dict:
    """Pure: column-set diff between two sources (scenario S3) — what they share,
    and what's unique to each. Used to tell the user whether two datasets line up
    and can be linked."""
    sa, sb = set(cols_a), set(cols_b)
    return {
        "common": sorted(sa & sb),
        "only_a": sorted(sa - sb),
        "only_b": sorted(sb - sa),
    }


def render_compare_panel(report_sources: "dict | None" = None) -> None:
    """Side-by-side column comparison of two sources (S3) — metadata only, so it's
    free even for large data. Flags a candidate join key when one exists."""
    sources = dict(report_sources or {})
    if len(sources) < 2:
        return
    names = {bid: (getattr(c, "description", None) or bid) for bid, c in sources.items()}
    with st.expander("🔍 比較兩份資料（看欄位差異、能不能對得起來）", expanded=False):
        ids = list(sources.keys())
        c1, c2 = st.columns(2)
        with c1:
            a = st.selectbox("資料 A", ids, format_func=lambda b: names[b], key="cmp_a")
        with c2:
            b_opts = [x for x in ids if x != a] or ids
            b = st.selectbox("資料 B", b_opts, format_func=lambda b: names[b], key="cmp_b")
        ca, cb = sources[a], sources[b]
        diff = compare_columns([c.name for c in ca.columns], [c.name for c in cb.columns])
        st.caption(f"**共同欄位（{len(diff['common'])}）**：" +
                   ("、".join(f"`{c}`" for c in diff["common"]) or "（無）"))
        d1, d2 = st.columns(2)
        with d1:
            st.caption(f"只在「{names[a]}」（{len(diff['only_a'])}）")
            st.caption("、".join(f"`{c}`" for c in diff["only_a"]) or "—")
        with d2:
            st.caption(f"只在「{names[b]}」（{len(diff['only_b'])}）")
            st.caption("、".join(f"`{c}`" for c in diff["only_b"]) or "—")
        cand = _auto_detect_join_cols(ca, cb)
        if cand:
            st.success(f"✅ 這兩份可用 `{cand[0][0]}` ↔ `{cand[0][1]}` 關聯 — 到「🔗 關聯」建立。")
        else:
            st.info("找不到明顯的共同鍵，可能無法直接關聯。")


def _combo_unique(contract, cols: list[str], *, sample_n: int = 2000) -> "bool | None":
    """Round 182: is the COMBINATION of ``cols`` unique within a sample? (composite
    key support). None when the sample/columns can't be read. Resource-safe."""
    from ai4bi.blocks.datastore import sample_dataframe
    try:
        df = sample_dataframe(contract, sample_n)
    except Exception:  # noqa: BLE001 — detection must never break the page
        return None
    if df is None or not cols or any(c not in getattr(df, "columns", []) for c in cols):
        return None
    sub = df[cols].dropna()
    if len(sub) == 0:
        return None
    return not bool(sub.duplicated().any())


def detect_cardinality(from_contract, from_col: str, to_contract, to_col: str,
                       *, sample_n: int = 2000) -> tuple[str, bool]:
    """Infer join cardinality from SAMPLES only (resource-safe — never loads a
    full table). Returns (label, is_risky). See cardinality_from_keys."""
    return cardinality_from_keys(
        _combo_unique(from_contract, [from_col], sample_n=sample_n),
        _combo_unique(to_contract, [to_col], sample_n=sample_n))


def detect_cardinality_multi(from_contract, from_cols: list[str],
                             to_contract, to_cols: list[str],
                             *, sample_n: int = 2000) -> tuple[str, bool]:
    """Round 182: cardinality for a COMPOSITE key — uniqueness is judged on the
    whole column COMBINATION per side, so "(廠別, 機台)" can be unique even when
    neither column is unique alone. Returns (label, is_risky)."""
    return cardinality_from_keys(
        _combo_unique(from_contract, list(from_cols), sample_n=sample_n),
        _combo_unique(to_contract, list(to_cols), sample_n=sample_n))


# ---------------------------------------------------------------------------
# Round 037: Join Builder UI
# ---------------------------------------------------------------------------

def render_join_builder(report_blocks: "dict | None" = None, expanded: bool = False) -> None:
    """Render the '資料關聯設定' expander — Round 037.

    Round 148: ``expanded`` lets the caller open it by default when it is the
    primary panel of the 模型 view (so the headline feature isn't one click away).
    Round 178: operates on the CURRENT REPORT's blocks (built-in/demo + user
    uploads) when ``report_blocks`` is passed — so you can join the demo's own
    tables (e.g. tool_dim ↔ process_move_fact on tool_id), not only files you
    uploaded yourself. report_block_contracts only includes blocks the report
    actually references, so other demos' seeds don't leak in.
    """
    user_blocks: dict[str, DataBlockContract] = (
        dict(report_blocks) if report_blocks is not None else _user_loaded_blocks())

    with st.expander("🔗 資料關聯設定（把兩份資料用共同欄位連結）", expanded=expanded):
        st.caption(
            "將兩份資料用共同欄位連結起來，就能在同一張圖表中顯示不同來源的數字。"
        )

        # Round 183: inline manual — a plain-language guide the user can open when
        # the terms feel unfamiliar (requested alongside auto-correct).
        with st.expander("📖 怎麼設定關聯？（看不懂時點這）", expanded=False):
            st.markdown(
                "**一句話**：把「你要看的數字」那份（主要資料），用一個共同欄位接上"
                "「拿來分類／補欄位」那份（補充資料）。\n\n"
                "**主要資料 vs 補充資料**\n"
                "- 📊 **主要資料**＝你要看的數字（例：生產紀錄、銷售明細）——通常筆數很多。\n"
                "- 🏷️ **補充資料**＝拿來分類或補欄位（例：機台基本資料、門市清單）——通常一個對象一筆。\n\n"
                "**為什麼方向很重要？**\n"
                "- ✅ **很多筆數字 → 對到一筆基本資料**：安全，加總、平均都算對。\n"
                "- ⚠️ **接反了**（一筆基本資料被複製到很多筆）：加總時數字會被**重複灌大**。"
                "別擔心——偵測到接反時，系統會**自動幫你對調修正**。\n\n"
                "**一個欄位還是會重複？用「複合鍵」**\n"
                "- 例：同一個機台編號在不同廠都有，只用「機台」會對到別廠。改用"
                "「**廠別＋機台**」一起對（按 ➕ 再加一組對應欄位）就準了。\n\n"
                "**建立關聯後**：到「🔍 探索」用兩份資料的欄位畫一張圖（例：依機台看平均等待時間），"
                "或用下方「🔗 跨資料表計算」算跨表數字（人均、轉換率…）。"
            )

        if len(user_blocks) < 2:
            st.info(
                "上傳至少 **2 份資料** 後，才能設定資料關聯。\n\n"
                "範例：銷售明細 + 門市基本資料，用 `store_id` 連結後，\n"
                "即可在同一張圖表裡顯示各門市的「銷售額」和「門市坪數」。",
                icon="💡",
            )
            return

        block_ids = list(user_blocks.keys())

        def _nm(bid: str) -> str:
            c = user_blocks.get(bid)
            return getattr(c, "description", None) or bid

        # Round 183: after a relationship is created, show a "what's next" card so
        # the user isn't stranded ("建立 link 後不知道要做什麼").
        _jc = st.session_state.pop("_just_created_rel", None)
        if _jc is not None:
            st.success(
                f"關聯建好了！🎉　「{_jc['from']}」和「{_jc['to']}」現在可以一起分析了。"
            )
            st.caption("接下來你可以——")
            nb1, nb2 = st.columns(2)
            with nb1:
                if st.button("💬 用這個關聯問問題", key="join_next_ask", type="primary",
                             help="例如「依機台比較平均等待時間」「每個機台的生產筆數」"):
                    st.session_state["_pending_nav_mode"] = "🔍 探索"
                    st.rerun()
            with nb2:
                st.caption("或往下捲到 **🔗 跨資料表計算**，做一個跨表數字（人均、轉換率…）。")
            st.markdown("---")

        st.caption("**建立新的關聯**")
        # Round 176: a 1:N detection means main/sub are likely swapped; the swap
        # button sets this flag, drained BEFORE the selectboxes re-instantiate.
        if st.session_state.pop("_join_swap_request", False):
            _fb, _tb = st.session_state.get("join_from_block"), st.session_state.get("join_to_block")
            if _fb and _tb:
                st.session_state["join_from_block"] = _tb
                st.session_state["join_to_block"] = _fb
        st.caption("📊 主要資料 = 你要看的數字　🏷️ 補充資料 = 拿來分類／補欄位的")
        col_l, col_r = st.columns(2)
        with col_l:
            from_bid = st.selectbox(
                "要分析的主要資料", block_ids, key="join_from_block",
                format_func=_nm,
                help="你最想看數字的那份，例如「生產紀錄」「銷售明細」（技術上＝事實表）")
        with col_r:
            to_options = [b for b in block_ids if b != from_bid]
            if not to_options:
                st.warning("需要至少兩份不同的資料才能建立關聯。")
                return
            to_bid = st.selectbox(
                "補充說明用的資料", to_options, key="join_to_block",
                format_func=_nm,
                help="拿來補欄位／分類的那份，例如「機台基本資料」「門市清單」（技術上＝維度表）")

        from_contract = user_blocks.get(from_bid)
        to_contract = user_blocks.get(to_bid)
        if from_contract is None or to_contract is None:
            return
        from_name, to_name = _nm(from_bid), _nm(to_bid)

        # Auto-detect common columns (top match per row default)
        candidates = _auto_detect_join_cols(from_contract, to_contract)
        if candidates:
            top_a, top_b, confidence = candidates[0]
            conf_pct = int(confidence * 100)
            (st.success if confidence >= 0.9 else st.info)(
                f"{'✅ AI 偵測到最佳連接欄位' if confidence >= 0.9 else '💡 建議連接欄位'}："
                f"`{top_a}` ↔ `{top_b}`（信心度 {conf_pct}%）")

        from_col_options = [c.name for c in from_contract.columns]
        to_col_options = [c.name for c in to_contract.columns]

        # Round 182: COMPOSITE keys — a list of column pairs that must ALL be equal
        # for two rows to count as "the same". Reset the rows when the chosen
        # blocks change (their columns differ, so stale widget values are invalid).
        ctx = (from_bid, to_bid)
        if st.session_state.get("_join_pairs_ctx") != ctx:
            st.session_state["_join_pairs_ctx"] = ctx
            st.session_state["_join_n_pairs"] = 1
            for _k in [k for k in list(st.session_state.keys())
                       if str(k).startswith(("jk_from_", "jk_to_"))]:
                del st.session_state[_k]
        n_pairs = int(st.session_state.get("_join_n_pairs", 1))

        key_pairs: list[tuple[str, str]] = []
        for i in range(n_pairs):
            st.caption("用哪個欄位把兩份資料對起來？" if i == 0
                       else "⋯ 而且這個欄位也要同時相等（兩個都相等才算同一筆）：")
            dft = candidates[i][0] if i < len(candidates) else from_col_options[0]
            dtt = candidates[i][1] if i < len(candidates) else to_col_options[0]
            cc1, cc2 = st.columns(2)
            with cc1:
                fc = st.selectbox(
                    f"「{from_name}」的欄位", from_col_options,
                    index=from_col_options.index(dft) if dft in from_col_options else 0,
                    key=f"jk_from_{i}")
            with cc2:
                tc = st.selectbox(
                    f"「{to_name}」的欄位", to_col_options,
                    index=to_col_options.index(dtt) if dtt in to_col_options else 0,
                    key=f"jk_to_{i}")
            key_pairs.append((fc, tc))

        addc, rmc = st.columns(2)
        with addc:
            if st.button(
                    "➕ 再加一組對應欄位", key="join_add_pair",
                    help="一個欄位還是對到重複的資料時，多用一個欄位一起比對"
                         "（例如「廠別＋機台」一起對，才不會混到別廠的同號機台）"):
                st.session_state["_join_n_pairs"] = n_pairs + 1
                st.rerun()
        with rmc:
            if n_pairs > 1 and st.button("➖ 移除最後一組", key="join_rm_pair"):
                for _sfx in (f"jk_from_{n_pairs - 1}", f"jk_to_{n_pairs - 1}"):
                    st.session_state.pop(_sfx, None)
                st.session_state["_join_n_pairs"] = n_pairs - 1
                st.rerun()

        from_cols = [f for f, _ in key_pairs]
        to_cols = [t for _, t in key_pairs]

        # Detect cardinality from samples (resource-safe) over the WHOLE key combo.
        card_label, risky = detect_cardinality_multi(
            from_contract, from_cols, to_contract, to_cols)

        # Round 183: AUTO-CORRECT a backwards (1:N) pick — flip main/sub so it
        # becomes the safe N:1, instead of asking the user to understand "主從" and
        # click. One swap always converges (1:N→N:1); N:N is never swapped (it
        # wouldn't help). The user can still opt out per data pair.
        pair_fs = frozenset({from_bid, to_bid})
        _no_ac: set = st.session_state.setdefault("_join_no_autocorrect", set())
        if card_label == "1:N" and pair_fs not in _no_ac:
            st.session_state["_join_swap_request"] = True
            st.session_state["_join_autocorrect_pair"] = pair_fs
            st.rerun()
        _ac_pair = st.session_state.get("_join_autocorrect_pair")

        if card_label in ("1:1", "N:1"):
            if _ac_pair == pair_fs:
                st.info(
                    "✅ 已自動幫你把「主要／補充」對調好（你原本接反了）——"
                    "這樣加總才不會被重複灌大。")
                if st.button("其實我要用原本的方向", key="join_undo_autocorrect"):
                    _no_ac.add(pair_fs)
                    st.session_state.pop("_join_autocorrect_pair", None)
                    st.session_state["_join_swap_request"] = True
                    st.rerun()
            else:
                st.success(
                    f"✅ 對得起來了：很多筆「{from_name}」對到一筆「{to_name}」，"
                    "這樣加總、平均都會算對。")
            st.caption(f"（技術型態：{card_label}，安全）")
        elif card_label == "1:N":  # only when the user opted out of auto-correct
            st.warning(
                "⚠️ 主從接反了，數字會被灌大：你把「很多筆 → 一筆」反過來接了，"
                "加總時同一個數字會被重複算好幾次。👉 按下面的按鈕就修好。")
            st.caption("（技術型態：1:N）")
            if st.button("🔄 一鍵對調，修正它", key="join_swap_btn"):
                _no_ac.discard(pair_fs)  # re-enable auto-correct for this pair
                st.session_state["_join_swap_request"] = True
                st.rerun()
        elif card_label == "N:N":
            st.error(
                "🚨 這兩份對不太起來，數字會爆量：兩邊的對應欄位都有重複值，"
                "硬接會讓每筆資料互相相乘、總數被灌得很誇張。")
            st.info(
                "💡 通常是「對應欄位選錯」，或「需要再加一組欄位才能對準」——"
                "試試上面的「➕ 再加一組對應欄位」（例如「廠別＋機台」一起對）。")
        else:  # 未知
            st.warning(
                "❔ 還沒辦法確認對不對得起來（資料太少或欄位取樣不到）。"
                "可先到「📋 來源與預覽」看看這些欄位的內容。")
            st.caption(f"（技術型態：{card_label}）")
        st.caption("（型態由前幾列取樣估計，非全表掃描；若加總後數字異常偏大，可能仍有重複。）")

        confirm_ok = True
        if risky:
            confirm_ok = st.checkbox("我了解風險，仍要建立此關聯", key="join_confirm_risky")

        if st.button("✅ 建立關聯", key="join_create_btn", type="primary",
                     disabled=not confirm_ok):
            _add_relationship(from_bid, to_bid, key_pairs,
                              cardinality=_CARD_TO_SEMANTIC.get(card_label, "many_to_one"))
            st.session_state["_just_created_rel"] = {
                "from": from_name, "to": to_name, "card": card_label}
            st.rerun()

        # Show existing relationships (composite keys shown joined with ＋)
        sm = get_user_semantic_model()
        existing_rels = [
            r for r in sm.get("relationships", [])
            if r.get("from_block") in user_blocks or r.get("to_block") in user_blocks
        ]
        if existing_rels:
            st.markdown("---")
            st.caption("**已建立的關聯**")
            for rel in existing_rels:
                keys = rel.get("keys", []) or []
                from_k = "＋".join(str(k.get("from", "?")) for k in keys) or "?"
                to_k = "＋".join(str(k.get("to", "?")) for k in keys) or "?"
                card = _SEMANTIC_TO_CARD.get(rel.get("cardinality", ""), "")
                rel_col, del_col = st.columns([5, 1])
                with rel_col:
                    st.markdown(
                        f"`{rel['from_block']}`.({from_k}) **─{card}→** "
                        f"`{rel['to_block']}`.({to_k})"
                    )
                with del_col:
                    if st.button("刪除", key=f"del_rel_{rel['relationship_id']}"):
                        _remove_relationship(rel["relationship_id"])
                        st.rerun()


# ---------------------------------------------------------------------------
# Round 038: Data Model View
# ---------------------------------------------------------------------------

_BLOCK_TYPE_ICON = {
    "fact": "📊", "snapshot_fact": "📸", "target_fact": "🎯",
    "dimension": "🏷️", "date_dimension": "📅",
    "metric_set": "🔢", "derived_block": "🔄",
}
_DATA_TYPE_ICON = {
    "date": "📅", "timestamp": "📅", "float": "🔢", "integer": "🔢",
    "string": "🏷️", "boolean": "✓",
}


def render_data_model_view(report_blocks: "dict | None" = None) -> None:
    """Render the '資料模型' expander — Round 038.

    Round 178: shows the CURRENT REPORT's blocks (built-in/demo + uploads) when
    ``report_blocks`` is passed, matching the join builder."""
    user_blocks: dict[str, DataBlockContract] = (
        dict(report_blocks) if report_blocks is not None else _user_loaded_blocks())
    sm = get_user_semantic_model()

    with st.expander("🗂️ 資料模型", expanded=False):
        if not user_blocks:
            st.info("上傳資料後，這裡會顯示你的資料結構和關聯圖。", icon="🗂️")
            return

        st.caption(f"**{len(user_blocks)} 個資料集，{len(sm.get('relationships', []))} 個關聯**")

        for bid, contract in user_blocks.items():
            icon = _BLOCK_TYPE_ICON.get(contract.block_type.value, "📦")
            n_metrics = len(contract.metrics)
            n_dims = len([c for c in contract.columns if c.data_type in ("string", "str")])
            n_dates = len([c for c in contract.columns if c.data_type in ("date", "timestamp")])

            with st.expander(f"{icon} **{bid}** — {len(contract.columns)} 欄位", expanded=False):
                sum_m = [m for m in contract.metrics if m.disaggregation_method.value == "sum"]
                avg_m = [m for m in contract.metrics if m.disaggregation_method.value == "average"]
                # Use caption instead of st.metric() to avoid polluting AppTest metric collection
                st.caption(
                    f"📊 加總指標 **{len(sum_m)}** 個　"
                    f"⚠️ 比率指標 **{len(avg_m)}** 個　"
                    f"🏷️ 分類 **{n_dims}** 欄　"
                    f"📅 日期 **{n_dates}** 欄"
                )

                # Column list
                st.caption("**欄位清單**")
                for col in contract.columns:
                    dtype_icon = _DATA_TYPE_ICON.get(col.data_type, "▪️")
                    is_metric = any(m.name == col.name for m in contract.metrics)
                    metric_tag = " _(指標)_" if is_metric else ""
                    st.caption(f"{dtype_icon} `{col.name}` — {col.data_type}{metric_tag}")

        # Relationships diagram (textual) — Round 176: real cardinality + orphans.
        rels = sm.get("relationships", [])
        st.markdown("---")
        st.caption("**資料關聯圖**")
        if rels:
            for rel in rels:
                keys = rel.get("keys", [{}])
                from_k = keys[0].get("from", "?") if keys else "?"
                to_k = keys[0].get("to", "?") if keys else "?"
                status_icon = "✅" if rel.get("status") == "certified" else "⚠️"
                card = _SEMANTIC_TO_CARD.get(rel.get("cardinality", ""), "?")
                st.markdown(
                    f"{status_icon} `{rel['from_block']}`.`{from_k}` **─ {card} ─→** "
                    f"`{rel['to_block']}`.`{to_k}`"
                )
        else:
            st.caption("尚未建立任何關聯。")
        # Orphan tables: loaded blocks no relationship references — they can't be
        # combined with the others until linked. Flag them so the user notices.
        linked = {b for rel in rels for b in (rel.get("from_block"), rel.get("to_block"))}
        orphans = [bid for bid in user_blocks if bid not in linked]
        if orphans and len(user_blocks) >= 2:
            st.warning(
                "🔗 尚未關聯的資料：" + "、".join(f"`{b}`" for b in orphans)
                + "。建立關聯後才能和其他資料一起分析。"
            )
