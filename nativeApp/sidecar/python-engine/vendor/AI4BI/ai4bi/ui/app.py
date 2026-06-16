"""Streamlit report canvas for editable semiconductor report drafts."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import streamlit as st

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.loader import BlockLoader
from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.report.builder import (
    build_add_visual_proposal,
    build_reorder_visual_proposal,
    build_visual_from_selection,
)
from ai4bi.report.catalog import build_catalog
from ai4bi.report.models import (
    DraftReportStore,
    ExecutableReportSpec,
    PublishedReportStore,
    ReportProposal,
    ReportChange,
)
from ai4bi.blocks.registry import FilesystemBlockRegistry, BlockNotFoundError, NoCertifiedVersionError
from ai4bi.report.proposals import build_page_delete_proposal, build_delete_visual_proposal, build_resize_visual_proposal, build_title_proposal, controls_to_proposal, pin_block_version_proposal, prompt_to_proposal, unpin_block_version_proposal
from ai4bi.report.publication import GateCheckResult, run_publication_gate
from ai4bi.report.templates import build_semiconductor_queue_time_report
from ai4bi.query_spec import AggFunction, BlockRef, FilterOperator, FilterSpec, MetricRef, VisualizationSpec, VisualQuerySpec, VisualType
from ai4bi.ui.cache import QueryCache
from ai4bi.ui.render_visual import get_metadata, humanize_metadata, render_visual
from ai4bi.ui import workspace
from ai4bi.ui.viewer import get_draft_path_from_params, is_readonly_mode, render_readonly_banner
from ai4bi.report.metric_catalog import MetricCatalogService, MetricZone
from ai4bi.report.block_library import build_block_library, LIFECYCLE_BADGE
from ai4bi.blocks.contracts import LifecycleStatus
from ai4bi.ui.upload import render_upload_panel, render_staged_upload_preview, _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY, _PENDING_NEW_BLOCK_KEY
from ai4bi.report.user_report import build_report_from_block
from ai4bi.ai.suggestions import generate_suggestions, detect_anomalies, AnomalyObservation, ChartSuggestion
from ai4bi.report.retail_template import (
    build_retail_demo_report, build_retail_sales_block, build_store_staffing_block,
)
from ai4bi.ui.data_model import render_join_builder, render_data_model_view, get_user_semantic_model, render_data_source_manager, render_compare_panel
from ai4bi.ui.create_data import render_create_data_panel  # Round 176
from ai4bi.ui.workspace_manager import render_workspace_panel  # Round 039
from ai4bi.ui.audit_trail import render_audit_trail, record_change  # Round 040
from ai4bi.ui.report_slicer import render_report_slicer, get_slicer_filters, SlicerDefinition  # Round 041
from ai4bi.ui.connector_panel import render_connector_panel  # Round 043
from ai4bi.ui.alert_panel import render_alert_manager, render_alert_banner  # Round 048
from ai4bi.ui.drilldown import (  # Round 049
    apply_drill, process_pending_drill, render_drill_controls, hierarchy_of,
)
from ai4bi.ui.summary_panel import render_summary_panel, render_summary_results  # Round 050
from ai4bi.ui.calc_metric_panel import render_calc_metric_panel  # Round 052
from ai4bi.ui.cross_fact_panel import render_cross_fact_panel, render_cross_fact_results  # Round 055
from ai4bi.ui.what_if_panel import render_what_if_panel, get_parameters  # Round 060
from ai4bi.ui.bookmark_panel import render_bookmark_panel  # Round 061
from ai4bi.ui.cohort_panel import (  # Round 062
    render_cohort_panel, render_cohort_results, _cohort_applicable, _fact_blocks,
)
from ai4bi.ui.change_panel import render_change_panel, render_change_results  # Round 071
from ai4bi.ui.basket_panel import render_basket_panel, render_basket_results, _basket_applicable  # Round 077
from ai4bi.ui.rfm_panel import render_rfm_panel, render_rfm_results, _rfm_applicable  # Round 082
from ai4bi.ui.trend_streak_panel import (  # Round 085
    render_trend_streak_panel, render_trend_streak_results, _streak_applicable,
)
from ai4bi.ui.format_controls import FORMAT_CONTROL_VTYPES as _FMT_VTYPES  # Round 135
from ai4bi.ui import theme as _theme  # Round 164: design-system / themes
from ai4bi.report.share_auth import hash_password, verify_password  # Round 064

_DEMO_ROOT = Path(__file__).parents[2] / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"
_SEMANTIC_MODEL = _DEMO_ROOT / "semantic_model.json"
_DRAFT_STORE = _DEMO_ROOT / "draft_reports"
_REGISTRY_DIR = _DEMO_ROOT / "registry"
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ASSISTANT_PLAN_KEY = "visual_assistant_analysis_plan"
_ASSISTANT_TRUST_KEY = "visual_assistant_trust_notes"
_ASSISTANT_ANSWER_KEY = "visual_assistant_direct_answer"  # Round 078
_ASSISTANT_TABLE_KEY = "visual_assistant_result_table"  # Round 086
_CHAT_HISTORY_KEY = "chat_history"


def _record_chat(prompt: str, visual_id: str, result) -> None:
    """Append a prompt + outcome to chat_history session state (spec 7.5)."""
    import time as _time
    if _CHAT_HISTORY_KEY not in st.session_state:
        st.session_state[_CHAT_HISTORY_KEY] = []
    icon_map = {
        "style": "🎨", "analysis": "📊", "plan": "🔍", "answer": "💡",
        "refused": "🚫", "mixed": "⚡", "unknown": "💬",
    }
    kind = getattr(result, "intent_kind", "unknown")
    st.session_state[_CHAT_HISTORY_KEY].append({
        "ts": _time.strftime("%H:%M:%S"),
        "prompt": prompt,
        "visual_id": visual_id,
        "kind": kind,
        "icon": icon_map.get(kind, "💬"),
        "message": result.message[:80],
        "ok": result.proposal is not None or getattr(result, "is_mixed", False)
        or result.analysis_plan is not None or getattr(result, "direct_answer", None) is not None
        or getattr(result, "result_table", None) is not None,
    })
    # Keep last 20 entries
    st.session_state[_CHAT_HISTORY_KEY] = st.session_state[_CHAT_HISTORY_KEY][-20:]


def _is_sandbox_visual(visual, contracts: dict[str, "DataBlockContract"]) -> bool:
    """Return True if any block_ref in this visual uses a non-certified contract."""
    for ref in visual.query.block_refs:
        contract = contracts.get(ref.block_id)
        if contract is None or contract.block_lifecycle != LifecycleStatus.certified:
            return True
    return False


def _has_sandbox_blocks(report: ExecutableReportSpec, contracts: dict) -> bool:
    """Return True if any visual in the report uses a non-certified block."""
    for page in report.pages.values():
        for visual in page.visuals.values():
            if _is_sandbox_visual(visual, contracts):
                return True
    return False


def _render_sandbox_banner() -> None:
    """Render the non-closeable amber sandbox banner (002-E consensus)."""
    st.markdown(
        '<div style="background:#fef3c7;border:2px solid #f59e0b;border-radius:6px;'
        'padding:8px 14px;margin-bottom:10px;">'
        '🔬 <strong>沙盒模式</strong> — 此報表含未認證積木，不可對外發布分享。'
        '</div>',
        unsafe_allow_html=True,
    )


_SANDBOX_BADGE_HTML = (
    '<span style="background:#fef3c7;color:#92400e;border:1px solid #f59e0b;'
    'border-radius:4px;padding:2px 6px;font-size:0.75rem;vertical-align:middle;">'
    '🔬 實驗中</span>'
)


def _active_cross_filter_for_page(page_id: str) -> dict | None:
    """Return the active cross-filter payload for one page, if any."""
    cross_filters = st.session_state.get("cross_filters") or {}
    if isinstance(cross_filters, dict):
        payload = cross_filters.get(page_id)
        if payload:
            return payload
    legacy = st.session_state.get("cross_filter")
    if isinstance(legacy, dict) and legacy.get("page_id", page_id) == page_id:
        return legacy
    return None


def _apply_cross_filter_to_query(
    query: VisualQuerySpec,
    cross_filter: dict | None,
    target_component_id: str,
    contracts: "dict | None" = None,
) -> VisualQuerySpec:
    """Inject a page-scoped cross-filter into compatible target visuals.

    Round 044: Enhanced cross-filter matching —
    1. Exact: source block is in target visual's block_refs (original behaviour)
    2. Semantic: source column name exists in the target visual's primary block
       (enables cross-table filtering when both tables share the same column name,
       e.g. store_name in sales_fact AND store_name in nps_fact)
    """
    if not cross_filter:
        return query
    if cross_filter.get("source_spec_id") == target_component_id:
        return query

    block_id = cross_filter.get("block_id")
    column_name = cross_filter.get("column_name")
    value = cross_filter.get("value")
    if not block_id or not column_name or value is None:
        return query

    values = value if isinstance(value, list) else [value]
    target_all_block_ids = query.all_block_ids

    # Exact match: source block is referenced by target visual
    effective_block = block_id if block_id in target_all_block_ids else None

    # Round 044: Semantic match — find the same column name in target's primary block
    if effective_block is None:
        # Use passed contracts or fall back to session_state cache
        _eff_contracts = contracts or st.session_state.get("_cached_all_contracts") or {}
        primary_id = query.primary_block_id
        primary_contract = _eff_contracts.get(primary_id)
        if primary_contract is not None:
            primary_col_names = {c.name for c in primary_contract.columns}
            if column_name in primary_col_names:
                effective_block = primary_id

    if effective_block is None:
        return query

    filters = [
        filter_spec
        for filter_spec in query.filters
        if not (
            filter_spec.block_id == effective_block
            and filter_spec.column_name == column_name
        )
    ]
    filters.append(
        FilterSpec(
            block_id=effective_block,
            column_name=column_name,
            operator=FilterOperator.in_,
            value=values,
            inherit_global_filter=False,
        )
    )
    version_token = f"{query.data_version}:xf:{effective_block}.{column_name}:{values}"
    return replace(query, filters=filters, data_version=version_token)


def _load_all_contracts() -> dict[str, DataBlockContract]:
    """Load all block contracts from the demo blocks directory plus user-uploaded blocks."""
    loader = BlockLoader()
    contracts: dict[str, DataBlockContract] = {}
    if _BLOCKS_DIR.exists():
        for path in _BLOCKS_DIR.glob("*.json"):
            try:
                contract = loader.load_json(str(path))
                contracts[contract.block_id] = contract
            except Exception:  # noqa: BLE001
                pass
    # Merge session-state user-uploaded blocks (Round 028)
    user_blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    contracts.update(user_blocks)
    return contracts


_DATE_DIMISH = ("date", "_at", "_on", "time", "日期", "時間", "month", "week", "day")


def _sample_metric_dim(report: ExecutableReportSpec) -> tuple[str, str]:
    """Round 157: a representative metric alias + categorical dimension from the
    CURRENT report, so NL example prompts match the actual data (semiconductor vs
    retail) instead of hardcoded retail copy."""
    metric_alias = dim_col = None
    for page in report.pages.values():
        for v in page.visuals.values():
            for m in v.query.metrics:
                metric_alias = metric_alias or (m.alias or m.metric_name)
            for d in v.query.dimensions:
                name = d.column_name
                is_date = getattr(d, "truncate_date_to", None) or \
                    any(h in name.lower() for h in _DATE_DIMISH)
                if not is_date and dim_col is None:
                    dim_col = name
            if metric_alias and dim_col:
                break
        if metric_alias and dim_col:
            break
    return (metric_alias or "數值"), (dim_col or "類別")


def _report_block_contracts(report: ExecutableReportSpec) -> dict[str, DataBlockContract]:
    """Round 155: the blocks the CURRENT report actually uses (resolved through
    _load_all_contracts), plus any genuinely user-loaded sources. This is what the
    calc-metric / cross-fact panels should offer — not the static retail seed that
    lingers in user_blocks after switching demos."""
    all_c = _load_all_contracts()
    ids: set[str] = set()
    for page in report.pages.values():
        for visual in page.visuals.values():
            for ref in visual.query.block_refs:
                ids.add(ref.block_id)
    # include user uploads/DB imports (tracked by a meta entry) so freshly added
    # data is editable even before it appears in a visual
    ids |= set(st.session_state.get(_USER_BLOCK_META_KEY, {}).keys())
    return {bid: all_c[bid] for bid in ids if bid in all_c}


def _applicable_analysis_tabs(report: ExecutableReportSpec) -> list[tuple[str, "callable"]]:
    """Round 174: the 分析-mode result tabs are data-driven, mirroring each
    panel's own applicability gate (R156). Retail/customer analyses (客戶留存 /
    常一起購買 / RFM) only appear when the report's data actually has those
    semantics — so a semiconductor/fab report (lots, tools, no customers) no
    longer shows irrelevant retail tabs. 連續下滑 / 變化分解 / 業務摘要 are
    general business analyses and apply to fab data too."""
    return _analysis_tabs_for_facts(_fact_blocks(_report_block_contracts(report)))


def _analysis_tabs_for_facts(facts: dict) -> list[tuple[str, "callable"]]:
    """Pure helper (testable without Streamlit): given the report's fact-block
    contracts, return [(label, results_renderer), ...] for the analyses that
    apply to that data. See _applicable_analysis_tabs for rationale (R174)."""
    def _any(pred) -> bool:
        return any(pred(c) for c in facts.values())

    tabs: list[tuple[str, callable]] = []
    if _any(_cohort_applicable):
        tabs.append(("客戶留存", render_cohort_results))
    if _any(_basket_applicable):
        tabs.append(("常一起購買", render_basket_results))
    if _any(_rfm_applicable):
        tabs.append(("RFM", render_rfm_results))
    if _any(_streak_applicable):
        tabs.append(("連續下滑", render_trend_streak_results))
    # change-decomposition + summary are general (not retail-specific) — always offered.
    tabs.append(("變化分解", render_change_results))
    tabs.append(("業務摘要", render_summary_results))
    return tabs


def _share_password_ok(report: ExecutableReportSpec) -> bool:
    """Round 064: gate a protected read-only share behind a password.

    Returns True once the viewer has entered the correct password (remembered
    per session). Renders a centred prompt and returns False until then.
    """
    authed_key = f"_share_authed_{report.audit.report_id}"
    if st.session_state.get(authed_key):
        return True
    st.title("🔒 受保護的報表")
    st.caption("這份分享報表需要密碼才能檢視。")
    pw = st.text_input("請輸入分享密碼", type="password", key="_share_pw_input")
    if st.button("開啟報表", key="_share_pw_submit", type="primary"):
        if verify_password(pw, report.share_password_hash):
            st.session_state[authed_key] = True
            st.rerun()
        else:
            st.error("密碼錯誤，請再試一次。")
    return False


def _gate_check_icon(check: GateCheckResult) -> str:
    if check.passed:
        return "✅"
    if check.blocking:
        return "❌"
    return "⚠️"


def _render_pin_versions_panel(report: ExecutableReportSpec) -> None:
    """Render the 'Pin versions' expander in the sidebar."""
    with st.expander("版本鎖定", expanded=False):
        if report.read_only:
            st.warning("Read-only mode — pinning is disabled.")
            return
        registry = FilesystemBlockRegistry(_REGISTRY_DIR)
        page = report.pages.get("main")
        if page is None:
            st.info("No 'main' page found in report.")
            return
        for visual_id in page.visual_order:
            visual = page.visuals[visual_id]
            for block_ref in visual.query.block_refs:
                block_id = block_ref.block_id
                if block_ref.pinned_version is None:
                    btn_key = f"pin_{visual_id}_{block_id}"
                    if st.button(f"Pin {block_id}", key=btn_key):
                        try:
                            certified_version = registry.get_certified_latest(block_id)
                        except (BlockNotFoundError, NoCertifiedVersionError):
                            st.warning(f"{block_id}: no certified version found")
                            continue
                        current_report = workspace.current_report()
                        proposal = pin_block_version_proposal(
                            current_report, "main", visual_id, block_id, certified_version
                        )
                        workspace.stage_proposal(proposal)
                        st.rerun()
                else:
                    st.markdown(
                        f"`{block_id}` pinned @ `{block_ref.pinned_version}`"
                    )
                    unpin_key = f"unpin_{visual_id}_{block_id}"
                    if st.button("Unpin", key=unpin_key):
                        current_report = workspace.current_report()
                        proposal = unpin_block_version_proposal(
                            current_report, "main", visual_id, block_id
                        )
                        workspace.stage_proposal(proposal)
                        st.rerun()


def _render_publication_readiness(report: ExecutableReportSpec) -> None:
    """Render the Publication Readiness expander in the sidebar."""
    with st.expander("發布前檢查", expanded=False):
        contracts = _load_all_contracts()
        semantic_model = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
        gate = run_publication_gate(report, contracts, semantic_model)

        if gate.can_publish:
            st.success("All blocking checks passed — report may be published.")
        else:
            st.error("One or more blocking checks failed — not ready to publish.")

        for check in gate.checks:
            icon = _gate_check_icon(check)
            label = check.check_name.replace("_", " ").title()
            st.markdown(f"{icon} **{label}**")
            st.caption(check.message)

        # Round 064: optional password gate for the read-only share
        st.markdown("---")
        st.markdown("**🔒 分享密碼（選填）**")
        if report.share_password_hash:
            st.caption("✅ 已設定密碼 — 開啟分享連結需輸入密碼。")
        else:
            st.caption("目前未設密碼 — 任何人拿到連結即可檢視。")
        _pw = st.text_input("設定分享密碼", type="password", key="set_share_pw")
        pc1, pc2 = st.columns(2)
        with pc1:
            if st.button("設定密碼", key="set_share_pw_btn", disabled=not _pw):
                workspace.replace_with_loaded(replace(report, share_password_hash=hash_password(_pw)))
                st.rerun()
        with pc2:
            if st.button("清除密碼", key="clear_share_pw_btn", disabled=not report.share_password_hash):
                workspace.replace_with_loaded(replace(report, share_password_hash=None))
                st.rerun()
        st.markdown("---")

        if gate.can_publish:
            if st.button("Publish & Share", type="primary", key="publish_share_btn"):
                # Re-run gate fail-closed before writing
                final_gate = run_publication_gate(report, contracts, semantic_model)
                pub_store = PublishedReportStore(_PROJECT_ROOT / "published")
                _, share_url = pub_store.publish(report, final_gate)
                st.success(f"Published! Share URL: {share_url}")
                st.session_state["last_share_url"] = share_url
        else:
            st.button(
                "Publish & Share",
                disabled=True,
                key="publish_share_btn",
                help="Fix failing checks before publishing",
            )


def _load_published_snapshot(path: Path) -> ExecutableReportSpec:
    """Load a published snapshot as a read-only report preview."""
    report = PublishedReportStore(_PROJECT_ROOT / "published").load(path)
    return replace(report, read_only=True)


def _render_block_library_panel(contracts: "dict | None" = None) -> None:
    """Render the Data Block View sidebar panel (Round 021, design-council 001-F).

    Round 156: defaults to the CURRENT report's blocks (+ user uploads) so the
    library is data-driven — it no longer lists every registry/demo block (which
    leaked retail blocks onto the semi demo and vice-versa)."""
    with st.expander("資料積木庫", expanded=False):
        if contracts is None:
            contracts = _load_all_contracts()
        if not contracts:
            st.info("No data blocks loaded.")
            return

        # Search input
        search = st.text_input(
            "Search blocks",
            placeholder="block name, type…",
            key="block_library_search",
        )

        cards = build_block_library(contracts, search_query=search)

        if not cards:
            st.info("No blocks match your search.")
            return

        st.caption(f"{len(cards)} block{'s' if len(cards) != 1 else ''} found")

        for card in cards:
            badge = card.lifecycle_badge
            header_md = (
                f"{card.type_icon} **`{card.block_id}`** "
                f"<span style='color:{badge['color']};font-size:0.8em;'>"
                f"{badge['emoji']} {badge['label']}</span>"
            )
            with st.expander(f"{card.type_icon} {card.block_id} · {badge['label']}", expanded=False):
                # Header row
                st.markdown(header_md, unsafe_allow_html=True)
                st.caption(card.summary_line)

                # Description + grain
                if card.description:
                    st.markdown(f"_{card.description}_")
                if card.grain:
                    st.caption(f"**Grain:** {card.grain[:120]}")

                # Metrics
                if card.metric_names:
                    st.markdown("**Metrics:**")
                    for mname in card.metric_names:
                        st.markdown(f"- `{mname}`")
                else:
                    st.caption("No metrics defined.")

                # Columns (first 8)
                if card.column_names:
                    visible_cols = card.column_names[:8]
                    extra = len(card.column_names) - 8
                    cols_text = "  ".join(f"`{c}`" for c in visible_cols)
                    if extra > 0:
                        cols_text += f"  _+{extra} more_"
                    st.markdown(f"**Columns:** {cols_text}")

                # Relationships
                if card.relationships:
                    st.markdown("**Relationships:**")
                    for rel in card.relationships:
                        st.caption(f"→ `{rel.target_block_id}` ({rel.status})")


def _render_create_report_from_loaded(cache: QueryCache) -> None:
    """Build a fresh report from a single user-loaded source. Round 176: moved
    out of the 資料 sidebar into the Data Workspace's ➕ 新增資料 tab."""
    _user_meta: dict = st.session_state.get(_USER_BLOCK_META_KEY, {})
    _all_blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    _user_blocks = {b: c for b, c in _all_blocks.items() if b in _user_meta}
    if not _user_blocks:
        return
    with st.expander("📊 從這份資料建立新報表", expanded=False):
        bid_choice = st.selectbox(
            "選擇已匯入的資料", list(_user_blocks.keys()),
            key="create_report_block_sel",
        )
        if st.button("建立新報表", key="create_report_from_upload", type="primary"):
            _meta = _user_meta.get(bid_choice, {})
            _contract = _user_blocks[bid_choice]
            _new_report = build_report_from_block(
                _contract, _meta.get("metric_names", []), _meta.get("dim_names", []),
            )
            workspace.replace_with_loaded(_new_report)
            cache.invalidate_all()
            st.rerun()


def _render_published_snapshot_browser(
    report: ExecutableReportSpec,
    cache: QueryCache,
) -> None:
    """Render a small browser for published snapshots of the current report."""
    with st.expander("已分享版本", expanded=False):
        store = PublishedReportStore(_PROJECT_ROOT / "published")
        snapshots = store.list_published(report.report_id)
        if not snapshots:
            st.info("No published snapshots found for this report.")
            return

        selected = st.selectbox(
            "Snapshot",
            snapshots,
            format_func=lambda path: path.stem,
            key="published_snapshot_select",
        )
        if st.button("Load Snapshot", key="published_snapshot_load", width="stretch"):
            try:
                workspace.replace_with_loaded(_load_published_snapshot(selected))
                cache.invalidate_all()
                st.session_state["cross_filters"] = {}
                st.session_state["cross_filter"] = None
                workspace.set_message(f"Loaded published snapshot: {selected.name}")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                workspace.set_message(f"Published snapshot load rejected: {exc}")
            st.rerun()


# ---------------------------------------------------------------------------
# Metric Catalog panel (003-E three-zone design)
# ---------------------------------------------------------------------------

def _render_metric_catalog_panel(report: ExecutableReportSpec, cache: QueryCache) -> None:
    """Render the three-zone Metric Catalog in the sidebar (design-council 003-E)."""
    # 可用指標清單（直接展示，不再 nested expander）
    if report.read_only:
        st.caption("唯讀模式 — 無法新增指標。")
        return

    contracts_cat = _load_all_contracts()
    try:
        semantic_model_cat = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        st.error(f"無法載入語意模型：{exc}")
        return

    catalog_result = MetricCatalogService().classify(semantic_model_cat, contracts_cat)
    if catalog_result.is_empty():
        st.caption("語意模型中沒有找到指標。")
        return

    if catalog_result.certified_ready:
        st.caption("🔵 **可直接使用**")
        for entry in catalog_result.certified_ready:
            st.caption(f"`{entry.metric_name}` [{entry.aggregation}] — {entry.block_id}")

    if catalog_result.needs_blocks:
        st.caption("⬜ **需補充積木**")
        for entry in catalog_result.needs_blocks:
            missing = ", ".join(f"`{b}`" for b in (entry.missing_blocks or []))
            st.caption(f"`{entry.metric_name}` — 缺少: {missing}")

    if catalog_result.sandbox:
        st.caption("🟡 **Sandbox（未認證）**")
        for entry in catalog_result.sandbox:
            st.caption(f"`{entry.metric_name}` [{entry.aggregation}] — {entry.block_id}")


# ---------------------------------------------------------------------------
# Add Visual panel
# ---------------------------------------------------------------------------

_VISUAL_TYPE_OPTIONS: list[str] = ["kpi_card", "line_chart", "bar_chart", "table"]
_VISUAL_TYPE_LABELS: dict[str, str] = {
    "kpi_card": "KPI Card",
    "line_chart": "Line Chart",
    "bar_chart": "Bar Chart",
    "table": "Table",
}


def _render_add_visual_panel(
    report: ExecutableReportSpec,
    cache: QueryCache,
) -> None:
    """Render the '+ Add Visual' expander in the sidebar.

    Steps
    -----
    1. Select block (primary fact block from semantic model).
    2. Select metrics (multiselect, max 2).
    3. Select dimensions (multiselect, max 2, optional).
    4. Select visual type.
    5. Preview VisualQuerySpec as JSON.
    6. 'Add to Report' → adds visual to current page and increments revision.
    """
    with st.expander("新增圖表設定", expanded=False):
        if report.read_only:
            st.warning("Read-only mode — adding visuals is disabled.")
            return

        # Load contracts and semantic model once (cached by Streamlit widget state
        # — reloaded on each rerun, acceptable for a demo draft tool).
        contracts = _load_all_contracts()
        try:
            semantic_model = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load semantic model: {exc}")
            return

        catalog = build_catalog(semantic_model, contracts)
        if not catalog:
            st.info("No fact blocks with metrics are available in the loaded contracts.")
            return

        # --- Step 1: Select block ---
        block_display_names = {bc.block_id: bc.display_name or bc.block_id for bc in catalog}
        selected_block_id = st.selectbox(
            "1. 選擇資料來源",
            list(block_display_names.keys()),
            format_func=lambda bid: block_display_names[bid],
            key="add_visual_block",
        )
        block_catalog = next((bc for bc in catalog if bc.block_id == selected_block_id), None)
        if block_catalog is None:
            return

        # --- Step 2: Select metrics (max 2) ---
        metric_options = [m.metric_name for m in block_catalog.metrics]
        metric_labels = {
            m.metric_name: f"{m.display_name} [{m.aggregation}]"
            for m in block_catalog.metrics
        }
        selected_metrics = st.multiselect(
            "2. 選擇指標（最多 2 個）",
            metric_options,
            format_func=lambda mn: metric_labels.get(mn, mn),
            max_selections=2,
            key="add_visual_metrics",
        )

        # --- Step 3: Select dimensions (max 2, optional) ---
        # Build dimension option keys as "block_id.column_name"
        dim_options: list[str] = []
        dim_labels: dict[str, str] = {}
        for de in block_catalog.dimensions:
            key = f"{de.block_id}.{de.column_name}"
            dim_options.append(key)
            dim_labels[key] = de.display_name

        selected_dims = st.multiselect(
            "3. 選擇分組維度（最多 2 個，可不選）",
            dim_options,
            format_func=lambda dk: dim_labels.get(dk, dk),
            max_selections=2,
            key="add_visual_dims",
        )

        # --- Step 4: Select visual type ---
        selected_vtype_str = st.selectbox(
            "4. 選擇圖表類型",
            _VISUAL_TYPE_OPTIONS,
            format_func=lambda vt: _VISUAL_TYPE_LABELS.get(vt, vt),
            key="add_visual_type",
        )
        visual_type = VisualType(selected_vtype_str)

        # --- Validate & show Step 5: preview ---
        validation_error: str | None = None
        query_spec = None
        viz_spec = None

        if selected_metrics:
            try:
                # Generate a candidate visual_id (not yet in the report).
                existing_ids = set(report.pages["main"].visuals.keys())
                base_id = f"user_{selected_block_id}_{selected_vtype_str}"
                visual_id = base_id
                counter = 1
                while visual_id in existing_ids:
                    visual_id = f"{base_id}_{counter}"
                    counter += 1

                query_spec, viz_spec = build_visual_from_selection(
                    visual_id=visual_id,
                    block_id=selected_block_id,
                    metric_names=selected_metrics,
                    dimension_names=selected_dims,
                    visual_type=visual_type,
                    contracts=contracts,
                    semantic_model=semantic_model,
                )
            except ValueError as exc:
                validation_error = str(exc)

        if validation_error:
            st.warning(f"Cannot add visual: {validation_error}")

        if query_spec is not None:
            with st.expander("5. Preview VisualQuerySpec (JSON)", expanded=False):
                from ai4bi.report.models import query_to_dict
                st.json(query_to_dict(query_spec))

        # --- Step 6: Add to Report button ---
        add_disabled = (
            not selected_metrics
            or validation_error is not None
            or query_spec is None
        )
        if st.button(
            "Add to Report",
            type="primary",
            disabled=add_disabled,
            key="add_visual_submit",
        ):
            if query_spec is not None and viz_spec is not None:
                # Carry matching active filters into the new visual's query spec.
                current_report = workspace.current_report()
                active = current_report.active_filters()
                from ai4bi.query_spec import FilterSpec, FilterOperator
                inherited_filters = []
                for filter_key, filter_value in active.items():
                    key_block_id = filter_key.split(".")[0] if "." in filter_key else ""
                    if key_block_id == selected_block_id:
                        col_name = filter_key.split(".", 1)[1] if "." in filter_key else filter_key
                        inherited_filters.append(
                            FilterSpec(
                                block_id=key_block_id,
                                column_name=col_name,
                                operator=FilterOperator.in_,
                                value=filter_value if isinstance(filter_value, list) else [filter_value],
                                inherit_global_filter=True,
                            )
                        )
                if inherited_filters:
                    from dataclasses import replace as _replace
                    query_spec = _replace(query_spec, filters=inherited_filters)

                proposal = build_add_visual_proposal(
                    page_id="main",
                    visual_id=visual_id,
                    query_spec=query_spec,
                    viz_spec=viz_spec,
                )
                workspace.stage_proposal(proposal)
                workspace.set_message(
                    f"Visual '{viz_spec.title or visual_id}' staged — confirm in the proposal panel."
                )
                st.rerun()


def _sync_widget_values(report: ExecutableReportSpec, *, force: bool = False) -> None:
    if not all(k in report.controls for k in ("process_step", "product_family", "breakdown")):
        return
    mappings = {
        "widget_process_step": report.controls["process_step"].value,
        "widget_product_family": report.controls["product_family"].value,
        "widget_breakdown": report.controls["breakdown"].value,
    }
    for key, value in mappings.items():
        if force or key not in st.session_state:
            st.session_state[key] = value


def _request_widget_sync() -> None:
    st.session_state["_sync_widgets_from_report"] = True


_SUGGESTION_ICONS: dict = {
    "kpi_card": "🔢", "line_chart": "📈", "bar_chart": "📊",
    "pie_chart": "🥧", "scatter": "⚡", "table": "📋",
}


def _render_ai_suggestions(report: ExecutableReportSpec, cache: QueryCache) -> None:
    """Power BI Copilot-style proactive chart suggestions + anomaly detection (Round 031/034)."""
    contracts = _load_all_contracts()
    if not contracts:
        return
    try:
        sm = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        sm = {}

    # Round 034: proactive anomaly observations
    anomalies = detect_anomalies(contracts, max_observations=3)
    if anomalies:
        with st.expander("🔍 AI 主動發現", expanded=True):
            st.caption("AI 掃描你的資料後，發現以下值得注意的地方：")
            for obs in anomalies:
                sev_color = "#dc2626" if obs.severity == "high" else "#d97706"
                st.markdown(
                    f"**{obs.icon} {obs.headline}**  \n"
                    f"<span style='color:{sev_color};font-size:0.85rem'>{obs.detail}</span>",
                    unsafe_allow_html=True,
                )
            st.markdown("---")

    suggestions = generate_suggestions(contracts, sm)
    if not suggestions:
        return

    # Filter out visuals that are already on the canvas
    existing_titles = {
        v.visualization.title
        for page in report.pages.values()
        for v in page.visuals.values()
    }
    suggestions = [s for s in suggestions if s.title not in existing_titles]
    if not suggestions:
        return

    with st.expander("💡 AI 建議圖表", expanded=False):
        st.caption("根據你的資料自動產生，點擊「建立」即可加入畫布。")
        if report.read_only:
            st.caption("唯讀模式")
            return

        existing_ids = set(report.pages.get("main", type("_", (), {"visuals": {}})()).visuals.keys())
        for si, sg in enumerate(suggestions[:8]):  # Round 185: surface more (was 5)
            icon = _SUGGESTION_ICONS.get(sg.visual_type.value, "📊")
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f"{icon} **{sg.title}**")
                st.caption(sg.reason)
            with cols[1]:
                # Round 185: include si + extra/second-dim in the key so two
                # suggestions on the same block+metric+type (e.g. trend vs moving-avg)
                # get distinct buttons.
                btn_key = f"sg_create_{si}_{sg.block_id}_{sg.metric_name}_{sg.visual_type.value}"
                if st.button("建立", key=btn_key):
                    dim_names = [d for d in (sg.dimension_name, sg.second_dimension_name) if d]
                    vid = f"sg_{sg.visual_type.value}_{sg.metric_name}_{si}"
                    c = 1
                    while vid in existing_ids:
                        vid = f"sg_{sg.visual_type.value}_{sg.metric_name}_{si}_{c}"; c += 1
                    try:
                        from ai4bi.report.builder import build_add_visual_proposal, build_visual_from_selection
                        q, v = build_visual_from_selection(
                            visual_id=vid,
                            block_id=sg.block_id,
                            metric_names=[sg.metric_name],
                            dimension_names=dim_names,
                            visual_type=sg.visual_type,
                            contracts=contracts,
                            semantic_model=sm,
                        )
                        # Round 185: apply the suggestion's analytics config (Pareto /
                        # moving-average / forecast) onto the built visualization.
                        if sg.extra:
                            v.extra = {**(v.extra or {}), **sg.extra}
                        workspace.stage_proposal(build_add_visual_proposal("main", vid, q, v))
                        workspace.accept_pending()
                        existing_ids.add(vid)
                        cache.invalidate_all()
                        workspace.set_message(f"已加入「{sg.title}」。")
                    except Exception as exc:  # noqa: BLE001
                        workspace.set_message(f"無法建立圖表：{exc}")
                    st.rerun()


def _report_badge(report) -> str:
    """A short 'which report am I in' badge for the breadcrumb / hub."""
    rid = report.audit.report_id
    if getattr(report, "read_only", False):
        return "🔒 唯讀分享"
    if rid == "retail_demo_v1":
        return "🛍️ 零售示範（範例）"
    if rid == "semiconductor_queue_time_v1":
        return "🔬 半導體示範（範例）"
    if rid.startswith(("upload_", "blank_")):
        return "📄 你的報表"
    return "📊 報表"


def _new_blank_report() -> ExecutableReportSpec:
    from ai4bi.report.models import AuditMetadata, ReportPageSpec
    import os
    import uuid
    return ExecutableReportSpec(
        audit=AuditMetadata(report_id=f"blank_{uuid.uuid4().hex[:6]}",
                            created_by=os.environ.get("ANALYST_NAME", "user")),
        title="新報表", semantic_model_ref="user@1.0.0", status="user_draft",
        pages={"main": ReportPageSpec("main", "Overview", {}, [], "概覽")}, controls={},
    )


def _relative_time(ts: float) -> str:
    """Human 'how long ago' label for a draft's last-modified time."""
    import time
    delta = time.time() - ts
    if delta < 90:
        return "剛剛"
    if delta < 3600:
        return f"{int(delta // 60)} 分鐘前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小時前"
    if delta < 7 * 86400:
        return f"{int(delta // 86400)} 天前"
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _hub_is_dirty(report: ExecutableReportSpec) -> bool:
    """True when the current report has edits since it was loaded/saved.
    Baseline revision is recorded in _render_draft_controls and reset on save."""
    if getattr(report, "read_only", False):
        return False
    if st.session_state.get("_baseline_for") != report.report_id:
        return False
    base = st.session_state.get("_baseline_rev")
    return base is not None and report.revision != base


def _do_switch(intent: str, store: DraftReportStore, cache: QueryCache) -> None:
    """Load the report identified by a switch intent (used by the hub guard)."""
    if intent == "retail":
        workspace.replace_with_loaded(build_retail_demo_report())
    elif intent == "semi":
        workspace.replace_with_loaded(build_semiconductor_queue_time_report())
    elif intent == "blank":
        workspace.replace_with_loaded(_new_blank_report())
    elif intent.startswith("open:"):
        stem = intent[len("open:"):]
        for p in store.list_paths():
            if p.stem == stem:
                workspace.replace_with_loaded(store.load(p))
                break
    cache.invalidate_all()


def _render_saved_drafts(store: DraftReportStore, cache: QueryCache, dirty: bool) -> None:
    """List saved drafts (recent-first) with 開啟 (guarded if dirty) + delete."""
    current = workspace.current_report()
    current_id = current.report_id if current else None
    saved_paths = store.list_paths()
    if not saved_paths:
        st.caption("（尚無已儲存的草稿）")
        return
    try:  # most-recently-modified first so frequent reports are on top
        saved_paths = sorted(saved_paths, key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:  # noqa: BLE001
        pass
    st.caption(f"已儲存的草稿（{len(saved_paths)} 份，最近在前）")
    pending = st.session_state.get("_hub_del_pending")
    for path in saved_paths:
        try:
            rep = store.load(path)
        except Exception:  # noqa: BLE001
            st.caption(f"⚠️ {path.name} 讀取失敗")
            continue
        is_cur = rep.report_id == current_id
        if pending == path.stem:  # two-step delete confirmation
            st.warning(f"確定刪除「{rep.title}」？此動作無法復原。")
            cc = st.columns(2)
            with cc[0]:
                if st.button("確定刪除", key=f"hub_delyes_{path.stem}", width="stretch"):
                    path.unlink(missing_ok=True)
                    st.session_state.pop("_hub_del_pending", None)
                    st.rerun()
            with cc[1]:
                if st.button("取消", key=f"hub_delno_{path.stem}", width="stretch"):
                    st.session_state.pop("_hub_del_pending", None)
                    st.rerun()
            continue
        try:
            mtime = _relative_time(path.stat().st_mtime)
        except Exception:  # noqa: BLE001
            mtime = ""
        row = st.columns([4, 1, 1])
        with row[0]:
            st.markdown(("🟢 " if is_cur else "") + f"**{rep.title}**")
            if mtime:
                st.caption(f"上次修改 {mtime}")
        with row[1]:
            if not is_cur and st.button("開啟", key=f"hub_open_{path.stem}"):
                if dirty:
                    st.session_state["_pending_switch"] = f"open:{path.stem}"
                else:
                    _do_switch(f"open:{path.stem}", store, cache)
                st.rerun()
        with row[2]:
            if st.button("🗑", key=f"hub_del_{path.stem}", help="刪除此草稿"):
                st.session_state["_hub_del_pending"] = path.stem
                st.rerun()


def _render_report_hub(report: ExecutableReportSpec, cache: QueryCache,
                       store: DraftReportStore) -> None:
    """Round 168: ONE clear report entry — open-existing vs create-new + save.

    Replaces the scattered demo-switcher + 📤分享-mode workspace panel + 🗂️資料
    build button so the "how do I start" steps are obvious:
      ① 使用既有報表（示範 / 已存草稿）   ② 全新建立（用我的資料 / 空白）
    plus file-lifecycle actions (儲存 / 另存新版 / 重新命名) that don't belong
    under 分享. Switching away from a report with unsaved edits is guarded.
    """
    st.markdown(f"**📋 {report.title}**")
    st.caption(_report_badge(report))
    dirty = _hub_is_dirty(report)

    # Unsaved-changes guard: confirm before discarding edits on a switch.
    pend = st.session_state.get("_pending_switch")
    if pend:
        st.warning("⚠️ 目前報表有未儲存變更，切換後會遺失。")
        c = st.columns(3)
        with c[0]:
            if st.button("💾 先儲存再切", key="psw_save", width="stretch"):
                store.save(workspace.current_report())
                _do_switch(pend, store, cache)
                st.session_state.pop("_pending_switch", None)
                st.rerun()
        with c[1]:
            if st.button("直接切換", key="psw_go", width="stretch", help="丟棄未儲存的變更"):
                _do_switch(pend, store, cache)
                st.session_state.pop("_pending_switch", None)
                st.rerun()
        with c[2]:
            if st.button("取消", key="psw_cancel", width="stretch"):
                st.session_state.pop("_pending_switch", None)
                st.rerun()
        return

    def _switch(intent: str) -> None:
        if dirty:
            st.session_state["_pending_switch"] = intent
        else:
            _do_switch(intent, store, cache)
        st.rerun()

    first = not st.session_state.get("_hub_seen")
    with st.expander("📋 報表：開啟 ／ 新建 ／ 儲存", expanded=first):
        st.session_state["_hub_seen"] = True

        st.markdown("**① 使用既有報表**")
        d = st.columns(2)
        with d[0]:
            if st.button("🛍️ 零售示範", key="hub_retail", width="stretch"):
                _switch("retail")
        with d[1]:
            if st.button("🔬 半導體示範", key="hub_semi", width="stretch"):
                _switch("semi")
        _render_saved_drafts(store, cache, dirty)

        st.markdown("**② 全新建立報表**")
        n = st.columns(2)
        with n[0]:
            if st.button("✨ 用我的資料", key="hub_new_data", width="stretch", type="primary",
                         help="上傳檔案或連接資料庫,自動建立新報表"):
                # not a report switch — stays on this report, just changes mode.
                st.session_state["_nav_mode"] = "🗂️ 資料"
                st.rerun()
        with n[1]:
            if st.button("📄 空白報表", key="hub_blank", width="stretch"):
                _switch("blank")

        # File-lifecycle actions — promoted out of 📤分享 (save ≠ share).
        if report and not report.read_only:
            st.markdown("**③ 儲存目前報表**" + ("　🟠 有未儲存變更" if dirty else ""))
            if st.button("💾 儲存", key="hub_save", width="stretch"):
                store.save(workspace.current_report())
                st.session_state["_baseline_rev"] = workspace.current_report().revision
                workspace.set_message("已儲存目前報表")
                st.rerun()
            # Rename and Save-as have SEPARATE inputs — unambiguous which a name feeds.
            rn = st.text_input("✏️ 重新命名為", value="", key="hub_rename_name",
                               placeholder=report.title)
            if st.button("✏️ 重新命名", key="hub_rename", width="stretch",
                         disabled=not rn.strip(), help="改目前這份報表的名稱"):
                workspace.replace_with_loaded(
                    replace(workspace.current_report(), title=rn.strip()))
                st.rerun()
            sa = st.text_input("💾 另存新版，命名為", value="", key="hub_saveas_name",
                               placeholder=f"{report.title} 複本")
            if st.button("💾 另存新版", key="hub_saveas", width="stretch",
                         disabled=not sa.strip(), help="複製成一份新報表，不動原檔"):
                import uuid
                cur = workspace.current_report()
                forked = replace(
                    cur, title=sa.strip(),
                    audit=replace(cur.audit, report_id=f"blank_{uuid.uuid4().hex[:6]}"))
                workspace.replace_with_loaded(forked)
                saved = store.save(workspace.current_report())
                workspace.set_message(f"已另存並切換到新版：{saved.name}")
                st.rerun()


def _render_draft_controls(
    report: ExecutableReportSpec,
    cache: QueryCache,
    store: DraftReportStore,
    executor: "Executor | None" = None,
) -> dict[str, object]:
    with st.sidebar:
        st.title("AI for BI")

        # Round 168: record the dirty-tracking baseline when the current report
        # identity changes (a switch/load), so edits-since-load can be detected.
        if st.session_state.get("_baseline_for") != report.report_id:
            st.session_state["_baseline_for"] = report.report_id
            st.session_state["_baseline_rev"] = report.revision

        # single clear report entry (open existing / create new / save)
        # — replaces the scattered demo-switcher + 分享-mode workspace panel.
        _render_report_hub(report, cache, store)

        # ── Ribbon: always-on actions (undo / redo / clear cache) ──────────
        # Round 147: promoted out of the buried 報表設定 expander so editing
        # actions are always reachable, like Power BI's ribbon.
        _rb = st.columns(3)
        with _rb[0]:
            if st.button("復原", disabled=not workspace.can_undo(), width="stretch"):
                _rev_before = report.revision
                workspace.undo()
                record_change("Undo", "Undid last proposal", report.report_id, _rev_before, workspace.current_report().revision)
                _clear_visual_assistant_context()
                _request_widget_sync()
                cache.invalidate_all()
                st.rerun()
        with _rb[1]:
            if st.button("重做", disabled=not workspace.can_redo(), width="stretch"):
                _rev_before = report.revision
                workspace.redo()
                record_change("Redo", "Redid last proposal", report.report_id, _rev_before, workspace.current_report().revision)
                _clear_visual_assistant_context()
                _request_widget_sync()
                cache.invalidate_all()
                st.rerun()
        with _rb[2]:
            if st.button("🗑 快取", disabled=report.read_only, width="stretch"):
                cache.invalidate_all()
                st.rerun()

        # Round 164: global appearance / theme picker (always visible).
        _render_theme_picker()

        # ── View-mode selector (Round 147 — Power BI-style view modes) ─────
        # Replaces the old flat ~25-panel scroll. Each mode shows only its
        # relevant panes, so the join/data-model/data-source features are
        # first-class destinations instead of buried expanders.
        # Round 168: drain a pending mode jump (e.g. welcome card → 資料) BEFORE
        # the radio instantiates, since its widget value can't be set afterwards.
        _pending_mode = st.session_state.pop("_pending_nav_mode", None)
        if _pending_mode is not None:
            st.session_state["_nav_mode"] = _pending_mode
        mode = st.radio(
            "模式",
            # Round 176: 🔗 模型 merged into 🗂️ 資料 (now a unified Data Workspace
            # whose 🔗 關聯 sub-tab owns relationships) — 4 top-level modes.
            ["🔍 探索", "🗂️ 資料", "📊 分析", "📤 分享"],
            horizontal=True, label_visibility="collapsed", key="_nav_mode",
        )
        st.markdown("---")

        if "探索" in mode:
            # Ask / read the report: suggestions, metric-first entry, bookmarks.
            # (The primary NL ask box now lives at the top of the canvas.)
            st.caption("💬 用自然語言提問的對話框已移到上方畫布頂端，隨時可用。")
            _render_ai_suggestions(report, cache)
            _render_metric_first_entry(report, cache)
            render_bookmark_panel(cache)

        elif "資料" in mode:
            # Round 176: all data management lives in the wide main-canvas Data
            # Workspace (來源與預覽 / 關聯 / 新增資料), so it gets full width. The
            # sidebar just signposts it (absorbs the old 🔗 模型 mode too).
            st.subheader("🗂️ 資料工作區")
            st.caption("資料的管理都在右側主畫布：")
            st.markdown(
                "📋 **來源與預覽** — 看每份資料的欄位與內容　\n"
                "🔗 **關聯** — 把多份資料用共同欄位連起來　\n"
                "➕ **新增資料** — 上傳／連接資料庫／新產生資料"
            )

        elif "分析" in mode:
            st.subheader("進階分析")
            _rblocks = _report_block_contracts(report)
            render_cohort_panel(_rblocks)
            render_basket_panel(_rblocks)
            render_rfm_panel(_rblocks)
            render_trend_streak_panel(_rblocks)
            if executor is not None:
                render_change_panel(_load_all_contracts(), executor)
                render_summary_panel(_load_all_contracts(), executor)

        elif "分享" in mode:
            st.subheader("分享與管理")
            st.caption("💡 開啟／新建／儲存報表已移到左上角的「📋 報表」入口；這裡專注於對外分享與發布。")
            with st.expander("📤 分享與發布", expanded=False):
                st.caption("檢查報表是否符合發布條件，建立唯讀分享連結，或載入已發布版本。")
                _render_publication_readiness(report)
                st.markdown("---")
                _render_published_snapshot_browser(report, cache)
            _render_digest_scheduler(report, executor)
            render_alert_manager(_load_all_contracts())
            with st.expander("⚙️ 報表設定", expanded=False):
                st.caption(f"版本 {report.revision}")
                if not report.read_only:
                    new_title = st.text_input("報表標題", value=report.title, key="widget_report_title")
                    if new_title != report.title:
                        title_proposal = build_title_proposal(report.title, new_title)
                        workspace.stage_proposal(title_proposal)
                        st.rerun()
                if not report.read_only and len(report.pages) > 1:
                    delete_page_id = st.selectbox(
                        "刪除頁面",
                        list(report.pages.keys()),
                        format_func=lambda page_id: report.pages[page_id].display_name or page_id,
                        key="widget_delete_page",
                    )
                    if st.button("Stage Page Delete", width="stretch"):
                        workspace.stage_proposal(
                            build_page_delete_proposal(workspace.current_report(), delete_page_id)
                        )
                        workspace.set_message(f"Page '{delete_page_id}' deletion staged.")
                        st.rerun()
            render_audit_trail()
            with st.expander("🔧 系統工具", expanded=False):
                st.caption("資料積木資訊與版本鎖定（進階使用者）。")
                _render_pin_versions_panel(report)
                st.markdown("---")
                _render_block_library_panel(_report_block_contracts(report))

        # ── Persistent Filters pane (every mode, like Power BI's Filters) ──
        st.markdown("---")
        _has_demo_controls = all(
            k in report.controls for k in ("process_step", "product_family", "breakdown")
        )
        if _has_demo_controls:
            st.subheader("篩選條件")
            steps = st.multiselect(
                report.controls["process_step"].label,
                report.controls["process_step"].options,
                key="widget_process_step",
                disabled=report.read_only,
            )
            products = st.multiselect(
                report.controls["product_family"].label,
                report.controls["product_family"].options,
                key="widget_product_family",
                disabled=report.read_only,
            )
            breakdown = st.selectbox(
                report.controls["breakdown"].label,
                report.controls["breakdown"].options,
                key="widget_breakdown",
                disabled=report.read_only,
            )
            proposal = controls_to_proposal(
                report,
                steps=steps,
                products=products,
                breakdown=breakdown,
            )
            if proposal and not report.read_only:
                if workspace.apply_immediately(proposal):
                    cache.invalidate_all()
                    st.rerun()
        else:
            st.subheader("篩選條件")
            _active_slicers = render_report_slicer(_load_all_contracts(), cache)
            st.session_state["_active_slicers"] = _active_slicers

        # ── Row-level security demo (Round 106) — persistent (View as) ─────
        _render_identity_selector(report, cache, executor)

        # ── Footer: status ───────────────────────────────────────────────
        st.markdown("---")
        try:
            from ai4bi.ai.llm_adapter import LLMAdapter
            _is_llm = LLMAdapter().active_mode == "llm"
        except Exception:  # noqa: BLE001
            _is_llm = False
        _dot = "🟢" if _is_llm else "⚫"
        _status = "AI 輔助中" if _is_llm else "規則模式"
        st.caption(f"{_dot} {_status}　|　草稿模式，尚未認證發布")

    return report.merged_filters() if report.controls else {}


def _render_digest_scheduler(report: ExecutableReportSpec, executor=None) -> None:
    """Round 111: configure a scheduled digest + deliver to the local outbox.

    The cron + SMTP transport is the external piece; here you set the schedule
    and 'send now' drops the digest into a local outbox folder (FileOutbox
    transport) that such a job would pick up — a working delivery demo.
    """
    if executor is None:
        return
    with st.expander("📧 排程摘要寄送（示範）", expanded=False):
        st.caption("設定寄送頻率與收件人。實際的定時與 SMTP 由外部 cron 接手；"
                   "「立即寄送」會把摘要寫入本機 outbox 資料夾（可由該排程程式撿走寄出）。")
        cols = st.columns(2)
        freq = cols[0].selectbox("頻率", ["daily", "weekly", "monthly"], index=1, key="_digest_freq")
        period = cols[1].selectbox("摘要範圍", ["week", "month"], index=0, key="_digest_period")
        recipients_raw = st.text_input("收件人（逗號分隔）", key="_digest_to",
                                       placeholder="boss@example.com, ops@example.com")
        if st.button("📤 立即產生並寄到 outbox", key="_digest_send"):
            from ai4bi.report.scheduler import DigestSchedule, FileOutboxTransport, run_digest
            recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
            schedule = DigestSchedule(recipients=recipients, frequency=freq, period=period)
            transport = FileOutboxTransport(_PROJECT_ROOT / "outbox")
            try:
                record = run_digest(executor, _load_all_contracts(), schedule, transport)
            except Exception as exc:  # noqa: BLE001
                st.error(f"產生失敗：{exc}")
                return
            if record.get("sent"):
                st.success(f"已寫入 outbox：{record['ref']}（收件人：{', '.join(record['recipients'])}）")
            else:
                st.warning(f"未寄送：{record.get('reason')}")


def _proposal_rows(proposal: ReportProposal) -> list[dict[str, str]]:
    return [
        {
            "Change": change.label,
            "Before": str(change.before),
            "After": str(change.after),
            "Data impact": "Re-query after approval" if change.affects_data else "Display only",
        }
        for change in proposal.changes
    ]


def _format_answer_value(answer) -> str:
    """Format a DirectAnswer value for st.metric (reuses the NL2 formatter)."""
    from ai4bi.ai.nl2proposal import _format_metric_value
    return _format_metric_value(answer.value, answer.unit)


def _clear_visual_assistant_context() -> None:
    st.session_state[_ASSISTANT_PLAN_KEY] = None
    st.session_state[_ASSISTANT_TRUST_KEY] = ()
    st.session_state[_ASSISTANT_ANSWER_KEY] = None
    st.session_state[_ASSISTANT_TABLE_KEY] = None


def _store_visual_assistant_context(result) -> None:
    # Use getattr for robustness against Streamlit hot-reload module cache mismatches.
    st.session_state[_ASSISTANT_PLAN_KEY] = getattr(result, "analysis_plan", None)
    st.session_state[_ASSISTANT_ANSWER_KEY] = getattr(result, "direct_answer", None)
    st.session_state[_ASSISTANT_TABLE_KEY] = getattr(result, "result_table", None)
    st.session_state[_ASSISTANT_TRUST_KEY] = tuple(getattr(result, "trust_notes", ()))


def _render_visual_assistant_context() -> None:
    # Round 086: a tabular analytics answer (churn / decline / basket).
    table = st.session_state.get(_ASSISTANT_TABLE_KEY)
    if table is not None:
        try:
            import pandas as _pd
            if isinstance(table, _pd.DataFrame) and not table.empty:
                st.dataframe(table, width="stretch", hide_index=True)
                csv = table.to_csv(index=False).encode("utf-8-sig")
                st.download_button("⬇ 下載名單 CSV", data=csv,
                                   file_name="answer_list.csv", key="answer_table_csv")
        except Exception:  # noqa: BLE001 — table render must never break the page
            pass

    # Round 078: a direct computed answer is shown most prominently.
    answer = st.session_state.get(_ASSISTANT_ANSWER_KEY)
    if answer is not None:
        delta = None
        if answer.delta_pct is not None:
            delta = f"{answer.delta_pct:+.1f}% vs {answer.previous_label}"
        st.metric(label=answer.metric_alias, value=_format_answer_value(answer), delta=delta)
        st.success(answer.sentence, icon="💡")

    plan = st.session_state.get(_ASSISTANT_PLAN_KEY)
    trust_notes = tuple(st.session_state.get(_ASSISTANT_TRUST_KEY) or ())
    if plan is not None:
        st.markdown("**Analysis Plan**")
        st.write(plan.question)
        for step in plan.steps:
            st.markdown(f"- {step}")
        if plan.suggested_visuals:
            st.caption(f"Suggested visuals: {', '.join(plan.suggested_visuals)}")
    if trust_notes:
        with st.expander("Why this response is trusted", expanded=False):
            for note in trust_notes:
                st.markdown(f"- {note}")


def _render_explanation_panel(component_id: str, visual) -> None:
    """Per-visual Explanation Panel (spec 8.1 — Explain before trust)."""
    meta = get_metadata(component_id)
    with st.expander("ℹ️ 資料來源與說明", expanded=False):
        if meta is None:
            st.caption("尚未執行查詢，請等待圖表載入後再開啟。")
            return

        # Metrics
        if meta.metrics_used:
            st.markdown("**指標定義**")
            for m in meta.metrics_used:
                agg = getattr(m.get("agg"), "value", None) or m.get("agg", "")
                st.caption(f"`{m['name']}` — {m['metric_id']} ({agg}) from `{m['block_id']}`")

        # Dimensions
        if meta.dimensions_used:
            st.markdown("**分組維度**")
            st.caption("  ".join(f"`{d}`" for d in meta.dimensions_used))

        # Filters
        if meta.filters_applied:
            st.markdown("**套用篩選**")
            for f in meta.filters_applied:
                st.caption(f"`{f}`")

        # Blocks & Relationships
        if meta.blocks_used:
            st.markdown("**資料來源**")
            st.caption("來源：" + "、".join(meta.blocks_used))
        if meta.relationships_used:
            for r in meta.relationships_used:
                cert = "✅ 已認證" if "certified" in r else "⚠️ 未認證"
                st.caption(f"→ {r}  {cert}")

        # Data freshness
        if meta.data_freshness:
            st.markdown("**資料更新時間**")
            for block_id, ts in meta.data_freshness.items():
                st.caption(f"`{block_id}`: {ts[:19].replace('T', ' ')} UTC")

        # Row count & execution time
        st.caption(
            f"回傳 **{meta.row_count}** 列 ｜ "
            f"查詢時間: {meta.executed_at[:19].replace('T', ' ')} UTC"
        )

        # Quality warnings
        if meta.quality_warnings:
            for w in meta.quality_warnings:
                st.warning(w, icon="⚠️")

        # CSV export — Round 031
        _last_valid = st.session_state.get("visual_last_valid", {}).get(component_id)
        if _last_valid is not None and not _last_valid.empty:
            csv_bytes = _last_valid.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇ 下載 CSV",
                data=csv_bytes,
                file_name=f"{component_id}.csv",
                mime="text/csv",
                key=f"csv_dl_{component_id}",
            )

        # SQL preview (for transparency / debug)
        if meta.sql_preview:
            with st.expander("SQL 預覽", expanded=False):
                st.code(meta.sql_preview, language="sql")


def _render_llm_mode_badge() -> None:
    """Render a prominent LLM mode status badge (spec 9.4 mode indicator)."""
    try:
        from ai4bi.ai.llm_adapter import get_llm_mode_label, LLMAdapter
        label = get_llm_mode_label()
        adapter = LLMAdapter()
        is_llm = adapter.active_mode == "llm"
        model_full = adapter._model if is_llm else ""
    except Exception:  # noqa: BLE001
        label, is_llm, model_full = "Mock NL2", False, ""

    if is_llm:
        bg, border, text_color, icon = "#d1fae5", "#10b981", "#065f46", "🤖"
        mode_label = "AI 模式"
        sub_label = model_full.replace("claude-", "").replace("-20251001", "")
    else:
        bg, border, text_color, icon = "#f3f4f6", "#9ca3af", "#374151", "⚙️"
        mode_label = "規則模式"
        sub_label = "keyword routing"

    st.markdown(
        f"""<div style="
            display:inline-flex; align-items:center; gap:8px;
            background:{bg}; border:1.5px solid {border};
            border-radius:8px; padding:6px 12px; margin-bottom:4px;
        ">
            <span style="font-size:1.2rem;">{icon}</span>
            <div>
                <div style="font-weight:700; font-size:0.85rem; color:{text_color}; line-height:1.2;">{mode_label}</div>
                <div style="font-size:0.72rem; color:{text_color}; opacity:0.75;">{sub_label}</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def _render_metric_first_entry(report: ExecutableReportSpec, cache: QueryCache) -> None:
    """Primary entry point: '想觀察的數字' (spec 8.1).

    Shows certified metrics from the semantic model.  Clicking '+' on any metric
    immediately stages a KPI card + line chart pair as a proposal — no 5-step
    manual workflow needed.
    """
    st.subheader("想觀察的數字")
    st.caption("選擇你想追蹤的指標，畫布自動產生 KPI 與趨勢圖。")

    if report.read_only:
        st.caption("唯讀模式")
        return

    contracts = _load_all_contracts()
    try:
        sm = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        sm = {"relationships": []}

    from ai4bi.report.catalog import build_catalog
    from ai4bi.report.builder import build_add_visual_proposal, build_visual_from_selection
    catalog = build_catalog(sm, contracts)
    if not catalog:
        st.caption("目前沒有可用的指標。")
        return

    existing_ids = set(report.pages.get("main", type("_", (), {"visuals": {}})()).visuals.keys())

    # Show user-uploaded block metrics directly (not in semantic model catalog)
    _user_contracts: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    _user_meta: dict = st.session_state.get(_USER_BLOCK_META_KEY, {})
    for _ubid, _uc in _user_contracts.items():
        if not _uc.metrics:
            continue
        st.caption(f"**{_ubid}** _(上傳資料)_")
        for _m in _uc.metrics[:4]:
            _col_info, _col_btn = st.columns([5, 1])
            with _col_info:
                st.caption(f"**{_m.name}** `[SUM]`")
            with _col_btn:
                _btn_key = f"metric_add_user_{_ubid}_{_m.name}"
                if st.button("＋", key=_btn_key, help=f"加入 {_m.name}"):
                    _kpi_id = f"kpi_{_m.name}"
                    _c = 1
                    while _kpi_id in existing_ids:
                        _kpi_id = f"kpi_{_m.name}_{_c}"; _c += 1
                    _kpi_q = VisualQuerySpec(
                        _kpi_id,
                        [BlockRef(_ubid)],
                        metrics=[MetricRef(_ubid, _m.name, _m.name, AggFunction.sum)],
                    )
                    _kpi_v = VisualizationSpec(VisualType.kpi_card, title=f"Total {_m.name}")
                    workspace.stage_proposal(build_add_visual_proposal("main", _kpi_id, _kpi_q, _kpi_v))
                    workspace.accept_pending()
                    existing_ids.add(_kpi_id)
                    cache.invalidate_all()
                    workspace.set_message(f"已加入「{_m.name}」KPI。")
                    st.rerun()

    for block_catalog in catalog:
        for metric_entry in block_catalog.metrics[:4]:  # show top 4 per block
            m_name = metric_entry.metric_name
            m_display = metric_entry.display_name or m_name
            m_agg = metric_entry.aggregation or ""

            col_info, col_btn = st.columns([5, 1])
            with col_info:
                st.caption(f"**{m_display}** `[{m_agg}]`")
            with col_btn:
                btn_key = f"metric_add_{block_catalog.block_id}_{m_name}"
                if st.button("＋", key=btn_key, help=f"加入 {m_display}"):
                    # Stage KPI card
                    kpi_id = f"kpi_{m_name}"
                    counter = 1
                    while kpi_id in existing_ids:
                        kpi_id = f"kpi_{m_name}_{counter}"; counter += 1

                    try:
                        kpi_q, kpi_v = build_visual_from_selection(
                            visual_id=kpi_id,
                            block_id=block_catalog.block_id,
                            metric_names=[m_name],
                            dimension_names=[],
                            visual_type=VisualType.kpi_card,
                            contracts=contracts,
                            semantic_model=sm,
                        )
                        proposal_kpi = build_add_visual_proposal("main", kpi_id, kpi_q, kpi_v)
                        workspace.stage_proposal(proposal_kpi)
                        workspace.accept_pending()
                        existing_ids.add(kpi_id)
                    except Exception as exc:  # noqa: BLE001
                        workspace.set_message(f"無法新增 KPI：{exc}")
                        st.rerun()
                        return

                    # Stage line chart if time dimension available
                    time_dims = [
                        d for d in block_catalog.dimensions
                        if any(t in d.column_name for t in ("date", "time", "event"))
                    ]
                    if time_dims:
                        trend_id = f"trend_{m_name}"
                        counter = 1
                        while trend_id in existing_ids:
                            trend_id = f"trend_{m_name}_{counter}"; counter += 1
                        try:
                            td = time_dims[0]
                            trend_q, trend_v = build_visual_from_selection(
                                visual_id=trend_id,
                                block_id=block_catalog.block_id,
                                metric_names=[m_name],
                                dimension_names=[f"{td.block_id}.{td.column_name}"],
                                visual_type=VisualType.line_chart,
                                contracts=contracts,
                                semantic_model=sm,
                            )
                            proposal_trend = build_add_visual_proposal("main", trend_id, trend_q, trend_v)
                            workspace.stage_proposal(proposal_trend)
                            workspace.accept_pending()
                            existing_ids.add(trend_id)
                        except Exception:  # noqa: BLE001
                            pass

                    cache.invalidate_all()
                    workspace.set_message(f"已加入「{m_display}」的 KPI 與趨勢圖。")
                    st.rerun()


def _render_chat_history() -> None:
    """Render the prompt history panel (spec 7.5 chat_history)."""
    history = st.session_state.get(_CHAT_HISTORY_KEY, [])
    if not history:
        return
    with st.expander(f"歷史記錄 ({len(history)})", expanded=False):
        for entry in reversed(history):
            status = "✅" if entry["ok"] else "❌"
            st.markdown(
                f"{status} {entry['icon']} `{entry['ts']}` **{entry['visual_id']}**  \n"
                f"_{entry['prompt'][:60]}_  \n"
                f"<span style='color:#6b7280;font-size:0.8em'>{entry['message']}</span>",
                unsafe_allow_html=True,
            )
        if st.button("清除歷史", key="clear_chat_history"):
            st.session_state[_CHAT_HISTORY_KEY] = []
            st.rerun()


def _render_identity_selector(report: ExecutableReportSpec, cache: QueryCache, executor=None) -> None:
    """Round 106: a lightweight identity/scope selector to activate R103 RLS.

    Only shown for the retail demo (whose policy scopes by city). Selecting a
    city sets the session identity so the executor restricts every query to that
    city — a live row-level-security demo without an external IdP.
    """
    if report.audit.report_id != "retail_demo_v1":
        return
    from ai4bi.report.auth import authenticate, demo_users
    with st.expander("🔐 檢視身分 / 登入（資料權限示範）", expanded=False):
        logged_in = st.session_state.get("_auth_user")
        if logged_in:
            ident = st.session_state.get("_identity") or {}
            scope = ident.get("city", "全部（管理者）")
            st.success(f"已登入：{logged_in}（{ident.get('role','viewer')}）｜資料範圍：{scope}")
            if st.button("登出", key="_auth_logout"):
                st.session_state["_auth_user"] = None
                st.session_state["_identity"] = None
                if executor is not None:
                    executor._identity = {}
                cache.invalidate_all()
                st.rerun()
            return

        st.caption("登入後依角色套用列級安全（RLS）：店長只看自己城市，管理者看全部。"
                   "示範帳號：admin / taipei / taichung（密碼=帳號+123）。")
        u = st.text_input("帳號", key="_auth_u")
        p = st.text_input("密碼", type="password", key="_auth_p")
        if st.button("登入", key="_auth_login"):
            ident = authenticate(u, p, demo_users())
            if ident is None:
                st.error("帳號或密碼錯誤。")
            else:
                # admin's empty city scope → no row restriction
                st.session_state["_auth_user"] = ident["username"]
                st.session_state["_identity"] = (
                    {"city": ident["city"]} if ident.get("city") else None)
                if executor is not None:
                    executor._identity = st.session_state["_identity"] or {}
                cache.invalidate_all()
                st.rerun()

        st.markdown("—— 或快速切換（免登入示範）——")
        cities = ["全部（管理者）", "台北", "台中", "高雄", "台南"]
        choice = st.selectbox("以此身分檢視", cities, key="_rls_choice")
        new_identity = None if choice.startswith("全部") else {"city": choice}
        if new_identity != st.session_state.get("_identity"):
            st.session_state["_identity"] = new_identity
            if executor is not None:
                executor._identity = new_identity or {}
            cache.invalidate_all()


def _render_visual_assistant(report: ExecutableReportSpec, cache: QueryCache, executor=None) -> None:
    with st.expander("🧠 探索與設計", expanded=True):
        st.caption("用自然語言新增圖表、調整分析、改變外觀。輸入後產生草稿提案，確認後才套用。")
        display_names = {
            component_id: visual.visualization.title or component_id
            for component_id, visual in report.pages["main"].visuals.items()
        }
        display_names_with_none = {"": "（不指定，對整個報表）"} | display_names
        selected_raw = st.selectbox(
            "① 選擇圖表（可選）",
            list(display_names_with_none),
            format_func=lambda cid: display_names_with_none[cid],
            key="selected_component_id",
            disabled=report.read_only,
        )
        selected = selected_raw or None
        # Round 102: a short, drag-resizable text_area — roomier than a single line
        # while typing a longer NL request, but it doesn't permanently occupy the
        # sidebar (user-reported sizing feedback). height≈3 lines; drag to grow.
        # Round 157: data-driven example prompts — use THIS report's metric +
        # dimension so the hints match the actual data (no hardcoded retail copy).
        _m, _d = _sample_metric_dim(report)
        prompt = st.text_area(
            "② 告訴我你想做什麼，或直接問問題",
            placeholder=f"例：{_m}最高的 5 個{_d}／各{_d}的{_m}／為什麼{_m}有變化？依{_d}拆解／加一張趨勢圖",
            height=80,
            disabled=report.read_only,
            help="輸入較長的句子時可拖曳右下角放大；按「送出請求」執行。",
        )
        with st.expander("💡 你可以這樣問（不只是改圖，也能直接得到答案）", expanded=False):
            st.markdown(
                f"- **直接問數字**：「{_m}總共多少？」→ 立即算出答案＋來源\n"
                f"- **排名**：「{_m}最高的 5 個{_d}」「每個{_d}的{_m}」→ 排行表\n"
                f"- **問原因**：「為什麼{_m}有變化？依{_d}拆解」→ 找出貢獻最多增減的維度\n"
                f"- **趨勢**：「{_m}這幾週的趨勢」「哪個{_d}連續下滑」\n"
                f"- **目標**：「{_m}有沒有達到目標？」\n"
                "- **改圖／分析**：「加一張趨勢圖」「改成依其他維度」「把離群值標紅色」"
            )
        if st.button("送出請求", type="primary", disabled=report.read_only, width="stretch"):
            # Load semantic model — merge demo SM with user-defined relationships (Round 037)
            try:
                _sm = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _sm = {"relationships": [], "metrics": []}
            _user_sm = get_user_semantic_model()
            _sm["relationships"] = _sm.get("relationships", []) + _user_sm.get("relationships", [])
            _contracts = _load_all_contracts()
            # Round 136: per-session conversation memory so a follow-up like
            # "只看 ETCH" inherits the prior turn's metric + dimension scope.
            _convo = st.session_state.setdefault("_convo_state", {})
            result = prompt_to_proposal(prompt, report, selected, semantic_model=_sm,
                                        contracts=_contracts, executor=executor,
                                        conversation_state=_convo)
            _store_visual_assistant_context(result)
            _record_chat(prompt, selected, result)
            st.session_state["_disambiguation"] = getattr(result, "disambiguation", None)
            if result.is_mixed:
                workspace.cancel_pending()
                st.session_state["split_proposals"] = result.split_proposals
                workspace.set_message(result.message)
            elif result.proposal is not None:
                st.session_state["split_proposals"] = None
                workspace.stage_proposal(result.proposal)
                workspace.set_message(result.message)
            else:
                st.session_state["split_proposals"] = None
                workspace.cancel_pending()
                workspace.set_message(result.message)
            st.rerun()

        _render_visual_assistant_context()

        # Disambiguation question from LLM (spec 9.3)
        disam = st.session_state.get("_disambiguation")
        if disam:
            st.info(f"🤔 {disam}", icon="❓")

        _render_chat_history()

        pending = workspace.pending_proposal()
        if pending is not None:
            st.markdown("**Pending Proposal**")
            st.dataframe(_proposal_rows(pending), hide_index=True, width="stretch")
            if pending.affects_data:
                st.warning("This change affects filters or grouping. Numbers update only after Apply.")
            else:
                st.success("Presentation-only change: query semantics and numbers stay unchanged.")
            actions = st.columns(2)
            with actions[0]:
                if st.button("Apply Proposal", type="primary", width="stretch"):
                    _rev_before = workspace.current_report().revision
                    _pending = workspace.pending_proposal()
                    if workspace.accept_pending():
                        _rev_after = workspace.current_report().revision
                        _desc = _pending.description if _pending else "提案已套用"
                        record_change("Apply Proposal", _desc, workspace.current_report().report_id, _rev_before, _rev_after)
                        _request_widget_sync()
                        cache.invalidate_all()
                    _clear_visual_assistant_context()
                    st.rerun()
            with actions[1]:
                if st.button("Cancel Proposal", width="stretch"):
                    workspace.cancel_pending()
                    _clear_visual_assistant_context()
                    st.rerun()

        # Mixed-prompt split proposals (style + analysis shown separately)
        split = st.session_state.get("split_proposals")
        if split:
            st.markdown("---")
            labels = ["🎨 Style (display only)", "📊 Analysis (re-queries data)"]
            for i, (prop, label) in enumerate(zip(split, labels)):
                st.markdown(f"**{label}**")
                st.dataframe(_proposal_rows(prop), hide_index=True, width="stretch")
                cols = st.columns(2)
                with cols[0]:
                    if st.button(f"Apply {label.split()[0]}", key=f"split_apply_{i}", type="primary", width="stretch"):
                        workspace.stage_proposal(prop)
                        if workspace.accept_pending():
                            _request_widget_sync()
                            cache.invalidate_all()
                        _clear_visual_assistant_context()
                        st.session_state["split_proposals"] = None
                        st.rerun()
            all_cols = st.columns(2)
            with all_cols[0]:
                if st.button("Apply Both", key="split_apply_all", width="stretch"):
                    for prop in split:
                        workspace.stage_proposal(prop)
                        workspace.accept_pending()
                    _request_widget_sync()
                    cache.invalidate_all()
                    _clear_visual_assistant_context()
                    st.session_state["split_proposals"] = None
                    st.rerun()
            with all_cols[1]:
                if st.button("Cancel All", key="split_cancel", width="stretch"):
                    st.session_state["split_proposals"] = None
                    _clear_visual_assistant_context()
                    st.rerun()


_SPAN_LABELS: dict[int, str] = {12: "100%", 6: "50%", 4: "33%", 3: "25%"}
_SPAN_OPTIONS: list[int] = [12, 6, 4, 3]


def _pack_grid_rows(
    visual_order: list[str],
    visuals: dict,
) -> list[list[str]]:
    """Pack visuals into grid rows of 12 columns total.

    Adjacent KPI cards with default col_span=12 are automatically paired
    into col_span=6 rows so they render side-by-side (legacy behaviour).
    """
    # Auto-pair adjacent KPI cards that haven't been manually resized
    order = list(visual_order)
    effective_spans: dict[str, int] = {}
    i = 0
    while i < len(order):
        vid = order[i]
        visual = visuals[vid]
        span = visual.col_span
        # Auto-pair: two adjacent full-width KPI cards → render as 6+6
        if (
            span == 12
            and visual.visualization.visual_type == VisualType.kpi_card
            and i + 1 < len(order)
            and visuals[order[i + 1]].visualization.visual_type == VisualType.kpi_card
            and visuals[order[i + 1]].col_span == 12
        ):
            effective_spans[vid] = 6
            effective_spans[order[i + 1]] = 6
            i += 2
        else:
            effective_spans[vid] = span
            i += 1

    rows: list[list[str]] = []
    current_row: list[str] = []
    current_total = 0
    for vid in order:
        span = effective_spans[vid]
        if current_total + span > 12 and current_row:
            rows.append(current_row)
            current_row = [vid]
            current_total = span
        else:
            current_row.append(vid)
            current_total += span
    if current_row:
        rows.append(current_row)
    return rows, effective_spans


def _render_visual_cell(
    report: ExecutableReportSpec,
    page_id: str,
    component_id: str,
    idx: int,
    order_len: int,
    contracts: dict,
    cache: QueryCache,
    executor: "Executor",
    active_filters: dict,
) -> None:
    """Render one visual cell (header + chart + explanation)."""
    page = report.pages[page_id]
    visual = page.visuals[component_id]
    title = visual.visualization.title or component_id

    # Header row: title | ✏️ | ↑ | ↓ | 🗑 | width selector
    if not report.read_only:
        h_cols = st.columns([4, 1, 1, 1, 1, 2])
    else:
        h_cols = st.columns([8, 1, 1])

    with h_cols[0]:
        # Round 165: dropped the per-visual "🔬 實驗中" sandbox badge (friction
        # for SMB self-serve; certification is advisory-only now).
        st.markdown(f"**{title}**")

    if not report.read_only:
        _is_selected = st.session_state.get("selected_component_id") == component_id
        with h_cols[1]:
            # Round 136: pick this chart for editing in the right 🎨 pane without the
            # dropdown. Writes a non-widget request key drained at the top of main()
            # (selected_component_id is a widget key — can't be set after instantiation).
            if st.button("✅" if _is_selected else "✏️",
                         key=f"edit_{page_id}_{component_id}",
                         help="在右側「視覺化」面板編輯這張圖"):
                st.session_state["_edit_target_request"] = component_id
                # Round 175: the right 🎨 視覺化 pane lives only in 探索 mode. When
                # ✏️ is clicked from a full-width mode (分析/模型/資料) the chart was
                # selected but no pane appeared ("右側不見了"). Jump to 探索 so the
                # editor is always where the button promises it will be.
                if "探索" not in st.session_state.get("_nav_mode", "🔍 探索"):
                    st.session_state["_pending_nav_mode"] = "🔍 探索"
                st.rerun()
        with h_cols[2]:
            if st.button("↑", key=f"up_{page_id}_{component_id}", disabled=(idx == 0), help="上移"):
                workspace.stage_proposal(build_reorder_visual_proposal(
                    page_id, component_id, "up", list(page.visual_order)
                ))
                st.rerun()
        with h_cols[3]:
            if st.button("↓", key=f"dn_{page_id}_{component_id}", disabled=(idx == order_len - 1), help="下移"):
                workspace.stage_proposal(build_reorder_visual_proposal(
                    page_id, component_id, "down", list(page.visual_order)
                ))
                st.rerun()
        with h_cols[4]:
            # Round 158: delete this visual (undoable via the 復原 ribbon button).
            if st.button("🗑", key=f"del_{page_id}_{component_id}",
                         help="刪除這張圖（可用上方「復原」還原）"):
                workspace.stage_proposal(
                    build_delete_visual_proposal(workspace.current_report(), page_id, component_id))
                workspace.accept_pending()
                _clear_visual_assistant_context()
                cache.invalidate_all()
                st.rerun()
        with h_cols[5]:
            current_span = visual.col_span
            new_label = st.selectbox(
                "寬度",
                options=list(_SPAN_LABELS.values()),
                index=list(_SPAN_OPTIONS).index(current_span) if current_span in _SPAN_OPTIONS else 0,
                key=f"span_sel_{page_id}_{component_id}",
                label_visibility="collapsed",
            )
            new_span = _SPAN_OPTIONS[list(_SPAN_LABELS.values()).index(new_label)]
            if new_span != current_span:
                workspace.stage_proposal(
                    build_resize_visual_proposal(page_id, component_id, new_span, current_span)
                )
                workspace.accept_pending()
                cache.invalidate_all()
                st.rerun()
    else:
        with h_cols[1]:
            if st.button("↑", key=f"up_{page_id}_{component_id}", disabled=(idx == 0), help="上移"):
                workspace.stage_proposal(build_reorder_visual_proposal(
                    page_id, component_id, "up", list(page.visual_order)
                ))
                st.rerun()
        with h_cols[2]:
            if st.button("↓", key=f"dn_{page_id}_{component_id}", disabled=(idx == order_len - 1), help="下移"):
                workspace.stage_proposal(build_reorder_visual_proposal(
                    page_id, component_id, "down", list(page.visual_order)
                ))
                st.rerun()

    st.session_state["_current_render_page_id"] = page_id
    query = replace(visual.query, data_version=f"draft-r{report.revision}")
    # Round 049: drill-down breadcrumb + per-level query rewrite (if drillable)
    if hierarchy_of(visual.visualization):
        render_drill_controls(component_id, visual.visualization)
        query = apply_drill(query, component_id, visual.visualization)
    query = _apply_cross_filter_to_query(query, _active_cross_filter_for_page(page_id), component_id, contracts)
    # Round 041: inject report-level slicer filters
    _slicers = st.session_state.get("_active_slicers", [])
    if _slicers:
        _slicer_filters = get_slicer_filters(_slicers)
        # Only inject filters for columns that exist in this visual's block refs
        _visual_blocks = {ref.block_id for ref in query.block_refs}
        _applicable = [f for f in _slicer_filters if f.block_id in _visual_blocks]
        if _applicable:
            query = replace(query, filters=list(query.filters) + _applicable)
    render_visual(query, visual.visualization, cache, executor, active_filters)
    # Round 032: show human-readable data source summary below visual
    _meta = get_metadata(component_id)
    _summary = humanize_metadata(_meta)
    if _summary:
        st.caption(f"🔍 {_summary}")
    # Round 153: the field-well now lives in the right-hand 🎨 視覺化 pane (Power BI
    # placement). Mark the selected visual on the canvas so it's clear which one
    # the pane is editing.
    if not report.read_only and st.session_state.get("selected_component_id") == component_id:
        st.caption("🎨 已選取 — 在右側「視覺化」面板編輯這張圖")
    _render_explanation_panel(component_id, visual)


_CHART_TYPE_LABELS = {
    "bar_chart": "長條圖", "line_chart": "折線圖",
    "pie_chart": "圓餅圖", "scatter": "散佈圖",
    "table": "表格", "pivot": "樞紐分析",
}


def _render_visual_field_well(component_id, visual, report, cache, contracts, in_pane: bool = False) -> None:
    """Round 148/153: a direct field-well for the selected visual — change value,
    group-by dimension, or chart type with dropdowns (no NL needed). Re-uses the
    governed NL2 structured-dispatch builders so all safety checks still apply.
    ``in_pane`` renders inline (no expander) for the right-hand Visualizations pane."""
    import contextlib  # noqa: PLC0415
    vtype = visual.visualization.visual_type.value
    if vtype not in _CHART_TYPE_LABELS:
        if in_pane:
            st.caption("這個視覺（KPI 卡）沒有可調整的值/分組/圖表類型。")
        return  # kpi_card has no chart-type/dimension well
    from ai4bi.ai import NL2ProposalService  # noqa: PLC0415
    svc = NL2ProposalService()

    _ctx = (contextlib.nullcontext() if in_pane
            else st.expander("✏️ 編輯這張圖（值 / 分組 / 圖表類型）", expanded=True))
    with _ctx:
        # ── measure (值) swap — the primary field, like Power BI's Values well ──
        if visual.query.metrics:
            fact_block = visual.query.metrics[0].block_id
            cur_metric = visual.query.metrics[0].metric_name
            fc = (contracts or {}).get(fact_block)
            metric_names = [m.name for m in getattr(fc, "metrics", []) or []]
            if len(metric_names) >= 2 and cur_metric in metric_names:
                picked_m = st.selectbox(
                    "值（要看的數字）", metric_names,
                    index=metric_names.index(cur_metric),
                    key=f"fw_measure_{component_id}",
                    help="換成另一個指標，例如從「營收」改成「數量」或「退貨率」。",
                )
                if picked_m != cur_metric:
                    page_id = next((pid for pid, p in report.pages.items()
                                    if component_id in p.visuals), None)
                    if page_id is not None:
                        before_m = [{"block_id": m.block_id, "metric_name": m.metric_name,
                                     "alias": m.alias, "agg_override": (m.agg_override.value if m.agg_override else None)}
                                    for m in visual.query.metrics]
                        after_m = [{"block_id": fact_block, "metric_name": picked_m,
                                    "alias": picked_m, "agg_override": None}]
                        changes = [ReportChange(
                            path=f"pages/{page_id}/visuals/{component_id}/query/metrics",
                            label=f"值 → {picked_m}", before=before_m, after=after_m,
                            affects_data=True)]
                        # Round 161: a sort referencing the OLD measure alias would
                        # become an invalid (non-projected) sort → re-point it.
                        sc = _sort_remap_change(visual, page_id, component_id, [picked_m])
                        if sc is not None:
                            changes.append(sc)
                        workspace.stage_proposal(ReportProposal(
                            description=f"值改為 {picked_m}", changes=changes,
                            target_component_id=component_id))
                        workspace.accept_pending()
                        cache.invalidate_all()
                        st.rerun()

        # ── chart-type switch ──
        # Round 151: pivot only offered when the visual has ≥2 dimensions.
        type_keys = [k for k in _CHART_TYPE_LABELS
                     if k != "pivot" or len(visual.query.dimensions) >= 2]
        if vtype not in type_keys:
            type_keys.append(vtype)  # always include the current type
        cur_idx = type_keys.index(vtype)
        new_label = st.selectbox(
            "圖表類型",
            [_CHART_TYPE_LABELS.get(k, k) for k in type_keys],
            index=cur_idx,
            key=f"fw_type_{component_id}",
        )
        new_type = type_keys[[_CHART_TYPE_LABELS.get(k, k) for k in type_keys].index(new_label)]
        if new_type != vtype:
            res = svc._build_single_proposal(
                "chart_type_change", {"target_type": new_type}, "",
                report, component_id, None, contracts)
            if res is not None and res.proposal is not None:
                workspace.stage_proposal(res.proposal)
                workspace.accept_pending()
                cache.invalidate_all()
                st.rerun()

        # ── group-by dimension switch — categorical columns of the visual's own
        # block, applied as a DIRECT block-scoped patch (Round 162). Going via the
        # NL categorical_dimension_change handler wrongly rejected same-block
        # columns as "not certified", and excluding *_id hid the current dimension.
        cur_dims = [d.column_name for d in visual.query.dimensions]
        cur_dim = cur_dims[0] if cur_dims else None
        fact_b = visual.query.metrics[0].block_id if visual.query.metrics else None
        dim_block = {}  # column -> block_id (only the metric's block, so it's joinable)
        if fact_b is not None:
            c = (contracts or {}).get(fact_b)
            for col in getattr(c, "columns", []) or []:
                low = col.name.lower()
                is_cat = getattr(col, "data_type", "") in ("string", "str", "object", "text", "varchar")
                # keep categorical cols; allow the CURRENT dim even if it ends in _id
                if (is_cat and not low.endswith("_code")) or col.name == cur_dim:
                    dim_block[col.name] = fact_b
        if dim_block:
            options = sorted(dim_block)
            idx = options.index(cur_dim) if cur_dim in options else 0
            picked = st.selectbox(
                "分組依據（group by）", options, index=idx,
                key=f"fw_dim_{component_id}",
                help="改變這張圖的分組維度，例如從「機台」改成「產品」。",
            )
            if picked != cur_dim:
                page_id2 = next((pid for pid, p in report.pages.items()
                                 if component_id in p.visuals), None)
                if page_id2 is not None:
                    before_d = [{"block_id": d.block_id, "column_name": d.column_name,
                                 "alias": d.alias, "truncate_date_to": d.truncate_date_to}
                                for d in visual.query.dimensions]
                    after_d = [{"block_id": dim_block[picked], "column_name": picked,
                                "alias": picked, "truncate_date_to": None}]
                    workspace.stage_proposal(ReportProposal(
                        description=f"分組改為 {picked}",
                        changes=[ReportChange(
                            path=f"pages/{page_id2}/visuals/{component_id}/query/dimensions",
                            label=f"分組 → {picked}", before=before_d, after=after_d,
                            affects_data=True)],
                        target_component_id=component_id))
                    workspace.accept_pending()
                    cache.invalidate_all()
                    st.rerun()


def _patch_visual_extra(page_id, vid, key, before, after) -> None:
    """Stage+apply a patch to a visual's visualization.extra[key]."""
    workspace.stage_proposal(ReportProposal(
        description=f"格式：{key}={after}",
        changes=[ReportChange(
            path=f"pages/{page_id}/visuals/{vid}/visualization/extra/{key}",
            label=f"格式 {key}", before=before, after=after, affects_data=False)],
        target_component_id=vid))
    workspace.accept_pending()


def _render_format_controls(component_id, visual, report, cache) -> None:
    """Round 160: Power BI-style Format controls for a chart visual — Y-axis
    range/scale, sort order, data labels, legend position. All via governed patches."""
    vtype = visual.visualization.visual_type.value
    page_id = next((pid for pid, p in report.pages.items() if component_id in p.visuals), None)
    if page_id is None:
        return
    extra = dict(visual.visualization.extra or {})
    st.markdown("**🎛️ 格式**")

    # ── sort order (value-based) — for bar/pie/table, not time series ──
    if vtype in _FMT_VTYPES["sort"] and visual.query.metrics:
        alias = visual.query.metrics[0].alias or visual.query.metrics[0].metric_name
        cur = visual.query.sort[0].direction.value if visual.query.sort else "desc"
        sort_label = {"desc": "由高到低", "asc": "由低到高"}
        pick = st.selectbox("排序", ["由高到低", "由低到高"],
                            index=0 if cur == "desc" else 1, key=f"fmt_sort_{component_id}")
        new_dir = "desc" if pick == "由高到低" else "asc"
        if new_dir != cur:
            before = [{"column_name": s.column_name, "direction": s.direction.value}
                      for s in visual.query.sort]
            after = [{"column_name": alias, "direction": new_dir}]
            workspace.stage_proposal(ReportProposal(
                description=f"排序 {pick}",
                changes=[ReportChange(path=f"pages/{page_id}/visuals/{component_id}/query/sort",
                                      label="排序", before=before, after=after, affects_data=True)],
                target_component_id=component_id))
            workspace.accept_pending(); cache.invalidate_all(); st.rerun()

    # ── Y-axis range + scale (line/bar) ──
    if vtype in _FMT_VTYPES["y_axis"]:
        c1, c2, c3 = st.columns(3)
        ymin = c1.text_input("Y 最小", value=("" if extra.get("y_min") is None else str(extra.get("y_min"))),
                             key=f"fmt_ymin_{component_id}", placeholder="自動")
        ymax = c2.text_input("Y 最大", value=("" if extra.get("y_max") is None else str(extra.get("y_max"))),
                             key=f"fmt_ymax_{component_id}", placeholder="自動")
        scale = c3.selectbox("刻度", ["線性", "對數"],
                             index=0 if extra.get("y_scale") != "log" else 1, key=f"fmt_scale_{component_id}")
        if st.button("套用 Y 軸", key=f"fmt_yaxis_apply_{component_id}"):
            def _num(s):
                try:
                    return float(s) if s.strip() != "" else None
                except ValueError:
                    return None
            for key, val in (("y_min", _num(ymin)), ("y_max", _num(ymax)),
                             ("y_scale", "log" if scale == "對數" else "linear")):
                _patch_visual_extra(page_id, component_id, key, extra.get(key), val)
            cache.invalidate_all(); st.rerun()

    # ── data labels toggle (bar/line/pie) ──
    if vtype in _FMT_VTYPES["data_labels"]:
        cur_dl = bool(extra.get("data_labels"))
        new_dl = st.checkbox("顯示資料標籤", value=cur_dl, key=f"fmt_dl_{component_id}")
        if new_dl != cur_dl:
            _patch_visual_extra(page_id, component_id, "data_labels", extra.get("data_labels"), new_dl)
            cache.invalidate_all(); st.rerun()

    # ── legend position ──
    if vtype in _FMT_VTYPES["legend_position"]:
        _LEG = {"預設": "top", "底部": "bottom", "右側": "right", "隱藏": "hide"}
        cur_leg = extra.get("legend_position") or "top"
        inv = {v: k for k, v in _LEG.items()}
        pick = st.selectbox("圖例位置", list(_LEG.keys()),
                            index=list(_LEG.keys()).index(inv.get(cur_leg, "預設")),
                            key=f"fmt_leg_{component_id}")
        new_leg = _LEG[pick]
        if new_leg != cur_leg:
            _patch_visual_extra(page_id, component_id, "legend_position", extra.get("legend_position"), new_leg)
            cache.invalidate_all(); st.rerun()

    # ── baseline / reference line (line/bar) — a horizontal line to read points against ──
    if vtype in _FMT_VTYPES["baseline"]:
        _BASE = {"無": None, "平均值": "mean", "自訂值": "custom"}
        cur_base = extra.get("baseline")
        inv = {v: k for k, v in _BASE.items()}
        b1, b2 = st.columns([2, 2])
        pick = b1.selectbox("基準線", list(_BASE.keys()),
                            index=list(_BASE.keys()).index(inv.get(cur_base, "無")),
                            key=f"fmt_base_{component_id}",
                            help="畫一條水平線當基準（平均值或自訂數值），方便看哪些點高於/低於它")
        new_base = _BASE[pick]
        cur_val = extra.get("baseline_value")
        new_val = cur_val
        if new_base == "custom":
            raw = b2.text_input("基準值", value=("" if cur_val is None else str(cur_val)),
                                key=f"fmt_baseval_{component_id}", placeholder="輸入數值")
            try:
                new_val = float(raw) if raw.strip() != "" else None
            except ValueError:
                new_val = None
        elif new_base != "custom":
            new_val = None
        if new_base != cur_base or new_val != cur_val:
            _patch_visual_extra(page_id, component_id, "baseline", extra.get("baseline"), new_base)
            _patch_visual_extra(page_id, component_id, "baseline_value", extra.get("baseline_value"), new_val)
            cache.invalidate_all(); st.rerun()


_GRAIN_LABELS = {
    "day": "日", "week": "週", "month": "月", "quarter": "季", "year": "年",
}


def _detect_grain_mismatch(page) -> dict[str, list[str]]:
    """Return {date_grain: [visual titles]} for time-bucketed visuals on a page.

    Pure helper (no Streamlit calls) so it can be unit-tested. A result with
    more than one key means the page mixes date grains.
    """
    grains: dict[str, list[str]] = {}
    for vid, visual in page.visuals.items():
        query = getattr(visual, "query", None)
        if query is None:
            continue
        for dim in query.dimensions:
            grain = getattr(dim, "truncate_date_to", None)
            if grain:
                title = getattr(visual.visualization, "title", None) or vid
                grains.setdefault(grain.lower(), []).append(title)
    return grains


def _render_grain_mismatch_warning(page) -> None:
    """Round 046: warn when visuals on the same page use different date grains.

    Mixing e.g. a weekly trend with a monthly trend on one page is the most
    dangerous *silent* data error (per the gap analysis): the numbers look
    comparable but are aggregated over different time buckets. We surface an
    orange warning rather than silently letting users mis-compare.
    """
    grains = _detect_grain_mismatch(page)
    if len(grains) <= 1:
        return
    parts = [
        f"「{_GRAIN_LABELS.get(g, g)}」（{'、'.join(titles)}）"
        for g, titles in grains.items()
    ]
    st.warning(
        "⚠️ 這個頁面有圖表使用不同的時間粒度："
        + "；".join(parts)
        + "。不同粒度的數字不可直接比較，請確認這是你要的。"
    )


def _render_drillthrough_controls(report: ExecutableReportSpec, page_id: str, contracts: dict) -> None:
    """Round 093: cross-page drill-through driven by the active cross-filter.

    On a normal page, an active cross-filter (a clicked dimension value) offers a
    button to open a focused detail page for that value. On a detail page, a
    button navigates back to the main page.
    """
    if page_id.startswith("detail_"):
        if st.button("← 返回主頁", key=f"back_{page_id}"):
            mains = [p for p in report.pages if not p.startswith("detail_")]
            st.session_state[_ACTIVE_PAGE_KEY] = mains[0] if mains else list(report.pages)[0]
            st.rerun()
        return

    cf = _active_cross_filter_for_page(page_id)
    if not cf:
        return
    block_id, column, value = cf.get("block_id"), cf.get("column_name"), cf.get("value")
    if not block_id or not column or value is None or isinstance(value, list):
        return
    contract = (contracts or {}).get(block_id)
    if contract is None:
        return
    if st.button(f"🔎 查看「{value}」的詳情頁", key=f"drill_{page_id}", width="stretch"):
        from ai4bi.report.drillthrough import build_detail_page
        from ai4bi.report.models import ReportChange, ReportProposal
        detail = build_detail_page(contract, block_id, column, value)
        if detail.page_id not in report.pages:
            proposal = ReportProposal(
                description=f"Drill-through 詳情頁：{value}",
                changes=[ReportChange(path=f"pages/{detail.page_id}/delete",
                                      label="新增詳情頁", before=None,
                                      after=detail.to_dict(), affects_data=True)],
            )
            workspace.apply_immediately(proposal)
        st.session_state[_ACTIVE_PAGE_KEY] = detail.page_id
        st.rerun()


def _render_page(
    report: ExecutableReportSpec,
    page_id: str,
    cache: QueryCache,
    executor: Executor,
    active_filters: dict[str, object],
) -> None:
    """Render all visuals for a single page using a 12-column grid layout."""
    page = report.pages[page_id]
    # Round 049: consume any pending drill-down click before visuals render,
    # so it doesn't leak to neighbours as a cross-filter.
    if process_pending_drill(report, page_id):
        st.rerun()
    _render_grain_mismatch_warning(page)
    visuals = page.visuals
    contracts = _load_all_contracts()
    _render_drillthrough_controls(report, page_id, contracts)
    # Cache contracts for _apply_cross_filter_to_query semantic matching
    st.session_state["_cached_all_contracts"] = contracts
    order = page.visual_order
    order_len = len(order)

    rows, effective_spans = _pack_grid_rows(order, visuals)

    for row in rows:
        if len(row) == 1:
            vid = row[0]
            idx = order.index(vid)
            _render_visual_cell(
                report, page_id, vid, idx, order_len,
                contracts, cache, executor, active_filters,
            )
        else:
            spans = [effective_spans[vid] for vid in row]
            cols = st.columns(spans)
            for col, vid in zip(cols, row):
                idx = order.index(vid)
                with col:
                    _render_visual_cell(
                        report, page_id, vid, idx, order_len,
                        contracts, cache, executor, active_filters,
                    )


def _resolve_active_page(page_ids: list[str], requested: str | None) -> str:
    """Round 076: pick the active page — the requested one if valid, else the first."""
    if requested in page_ids:
        return requested
    return page_ids[0]


_ACTIVE_PAGE_KEY = "_active_page"


def _render_canvas(
    report: ExecutableReportSpec,
    cache: QueryCache,
    executor: Executor,
    active_filters: dict[str, object],
) -> None:
    page_ids = list(report.pages.keys())
    if len(page_ids) == 1:
        _render_page(report, page_ids[0], cache, executor, active_filters)
        return

    # Round 076: state-driven page navigation (replaces st.tabs) so a page can be
    # switched programmatically — the prerequisite for cross-page drill-through.
    labels = {pid: (report.pages[pid].display_name or pid) for pid in page_ids}
    active = _resolve_active_page(page_ids, st.session_state.get(_ACTIVE_PAGE_KEY))
    # No widget key: `index` is honoured every run, so a programmatic change to
    # _active_page (e.g. a drill-through) is reflected immediately.
    chosen = st.radio(
        "頁面", page_ids, index=page_ids.index(active),
        format_func=lambda p: labels[p], horizontal=True,
    )
    st.session_state[_ACTIVE_PAGE_KEY] = chosen
    _render_page(report, chosen, cache, executor, active_filters)


def _render_theme_picker() -> None:
    """Round 164: live theme switcher (sidebar). Re-skins chrome + charts
    without an app restart. The five saved presets (top-5 from the UI/UX
    review) lead the list; the dark 'midnight' theme is offered last for
    low-light / control-room screens."""
    # presets first (recommended default leads), then any extra themes (dark).
    preset_keys = list(_theme.PRESET_ORDER)
    extra_keys = [k for k in _theme.all_themes() if k not in preset_keys]
    keys = preset_keys + extra_keys
    current = st.session_state.get(_theme._SESSION_KEY, _theme.DEFAULT_THEME_KEY)
    if current not in keys:
        current = keys[0]

    def _fmt(k: str) -> str:
        label = _theme.get_theme(k).label
        if k == _theme.DEFAULT_THEME_KEY:
            return f"{label}（推薦）"
        if k not in preset_keys:
            return f"{label}（深色監控）"
        return label

    with st.expander("🎨 外觀主題", expanded=False):
        chosen = st.selectbox(
            "選擇配色主題",
            keys,
            index=keys.index(current),
            format_func=_fmt,
            key="_theme_picker",
            label_visibility="collapsed",
        )
        st.caption(_theme.get_theme(chosen).description)
        if chosen != current:
            _theme.set_active_theme(chosen)
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="AI for BI", page_icon="📊", layout="wide")
    # Round 164: re-skin the Streamlit chrome to the active theme on every run
    # (config.toml only sets the startup look; this enables live switching).
    st.markdown(_theme.app_css(), unsafe_allow_html=True)

    # Determine read-only mode from URL query parameters (?mode=readonly&draft=<path>)
    readonly = is_readonly_mode()
    draft_path_param = get_draft_path_from_params()

    # Round 033: default to retail demo (better first impression for non-technical users)
    workspace.init_report(build_retail_demo_report())

    # Pre-register the retail demo block so the executor can query it
    if _USER_BLOCKS_KEY not in st.session_state:
        st.session_state[_USER_BLOCKS_KEY] = {}
    if "retail_sales" not in st.session_state[_USER_BLOCKS_KEY]:
        st.session_state[_USER_BLOCKS_KEY]["retail_sales"] = build_retail_sales_block()
    # Round 055: second retail fact for cross-fact composition demo (revenue per employee)
    if "store_staffing" not in st.session_state[_USER_BLOCKS_KEY]:
        st.session_state[_USER_BLOCKS_KEY]["store_staffing"] = build_store_staffing_block()

    # Round 033: auto-build report when user just imported a new block
    _pending_block = st.session_state.pop(_PENDING_NEW_BLOCK_KEY, None)
    if _pending_block and _pending_block in st.session_state.get(_USER_BLOCKS_KEY, {}):
        _ub = st.session_state[_USER_BLOCKS_KEY][_pending_block]
        _um = st.session_state.get("user_block_meta", {}).get(_pending_block, {})
        _new_report = build_report_from_block(
            _ub,
            _um.get("metric_names", []),
            _um.get("dim_names", []),
        )
        workspace.replace_with_loaded(_new_report)

    # If a draft path is provided via URL, load it once per session
    if draft_path_param and "readonly_draft_loaded" not in st.session_state:
        _store = DraftReportStore(_DRAFT_STORE)
        try:
            candidate = Path(draft_path_param)
            try:
                loaded = _store.load(candidate)
            except ValueError:
                loaded = PublishedReportStore(_PROJECT_ROOT / "published").load(candidate)
            workspace.replace_with_loaded(loaded)
            st.session_state["readonly_draft_loaded"] = True
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    report = workspace.current_report()

    # Enforce read_only flag when URL mode=readonly
    if readonly and not report.read_only:
        report = replace(report, read_only=True)
        workspace.replace_with_loaded(report)
        report = workspace.current_report()

    # Round 064: password gate for protected read-only shares — block render
    # until the correct password is entered.
    if readonly and getattr(report, "share_password_hash", None):
        if not _share_password_ok(report):
            return

    force_sync = st.session_state.pop("_sync_widgets_from_report", False)
    _sync_widget_values(report, force=force_sync)
    # Round 136: drain a pending "edit this chart" request into the selectbox's
    # widget key BEFORE the selectbox instantiates (writing it later would raise
    # "cannot be modified after widget instantiated"). Set by the canvas ✏️ button.
    _edit_req = st.session_state.pop("_edit_target_request", None)
    if _edit_req is not None:
        st.session_state["selected_component_id"] = _edit_req
    cache = QueryCache(use_l1=False)
    store = DraftReportStore(_DRAFT_STORE)
    # Include all user-uploaded blocks (retail demo + any CSV uploads)
    _user_blocks_exec: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    # Round 183: feed user-defined relationships (🔗 關聯 UI) into the CHART
    # executor so joins on uploaded data actually resolve (was NL2-only before).
    _user_rels = get_user_semantic_model().get("relationships") or None
    executor = Executor(
        registry_root=_BLOCKS_DIR,
        semantic_model_path=_SEMANTIC_MODEL,
        extra_contracts=_user_blocks_exec or None,
        extra_relationships=_user_rels,
        parameters=get_parameters(),  # Round 060: what-if parameters
        identity=st.session_state.get("_identity") or None,  # Round 103: row-level security
    )

    active_filters = _render_draft_controls(report, cache, store, executor)
    report = workspace.current_report()
    # Round 060: pick up any what-if slider changes made during sidebar render,
    # so the canvas (rendered next) reflects the latest parameter values.
    executor._parameters = get_parameters()

    # Round 176: in the Data Workspace the page header is the WORKSPACE, not the
    # report — otherwise the big report title looms over data management and the
    # two feel "mixed". Other modes keep the report title + breadcrumb.
    _mode = st.session_state.get("_nav_mode", "🔍 探索")
    _in_data_ws = (not readonly) and ("資料" in _mode)
    st.title("🗂️ 資料工作區" if _in_data_ws else report.title)

    # Show read-only banner or normal caption
    if readonly:
        render_readonly_banner()
    elif _in_data_ws:
        _dirty_tag = "　·　🟠 有未儲存變更" if _hub_is_dirty(report) else ""
        st.caption(
            f"整理資料來源、關聯與新增資料。　目前報表：{_report_badge(report)}"
            f"　·　看報表請切到「🔍 探索」。{_dirty_tag}")
    else:
        # Round 168: breadcrumb — which report am I in, and which mode (markdown,
        # not caption, so "which report" is prominent enough to always notice).
        _dirty_tag = "　·　🟠 有未儲存變更" if _hub_is_dirty(report) else ""
        st.markdown(
            f"📋 **{_report_badge(report)}**　·　目前在「{_mode}」"
            f"　·　切換／新建在左上「📋 報表」{_dirty_tag}")
        _rid = report.audit.report_id
        if _rid == "retail_demo_v1":
            st.caption("📊 零售示範資料（2026 年 3–5 月合成數據）｜左側上傳你的資料，或直接用自然語言探索。")
        elif _rid == "semiconductor_queue_time_v1":
            st.caption("🔬 半導體製程示範 — process movement facts, certified tool_dim join")
        elif _rid.startswith("upload_"):
            st.caption("📁 你的資料 — AI 自動建立的起始報表，可用自然語言繼續探索。")
        else:
            st.caption(f"報表 ID: `{_rid}`")

    # Round 168: first-run welcome — make the (otherwise invisible) starting
    # point explicit and offer the two paths. Dismissible; shown once per session.
    if not readonly and not st.session_state.get("_welcome_dismissed"):
        with st.container(border=True):
            st.markdown("#### 👋 歡迎使用 AI for BI — 你想怎麼開始？")
            st.caption("目前畫面是一份**範例報表**,可直接看或用自然語言編輯。或選一條路開始：")
            wc = st.columns([1, 1, 1])
            with wc[0]:
                st.markdown("**① 用這份範例**  \n直接在下方輸入框用自然語言提問或改圖。")
                if st.button("✅ 就用這份範例", key="welcome_use_demo", width="stretch"):
                    st.session_state["_welcome_dismissed"] = True
                    st.rerun()
            with wc[1]:
                st.markdown("**② 用我的資料**  \n上傳檔案／連資料庫,自動建新報表。")
                if st.button("✨ 開始建立", key="welcome_new", type="primary", width="stretch"):
                    st.session_state["_pending_nav_mode"] = "🗂️ 資料"
                    st.session_state["_welcome_dismissed"] = True
                    st.rerun()
            with wc[2]:
                st.markdown("**③ 開啟既有報表**  \n左上「📋 報表」開示範或你存過的草稿。")
                st.caption("（在左側「📋 報表：開啟／新建／儲存」）")

    # Round 148: primary NL ask box at the TOP of the canvas (Power BI Copilot
    # placement) — the most common action lives where the user is looking, not
    # buried in a sidebar expander. Read-only shares omit it.
    if not readonly:
        _render_visual_assistant(report, cache, executor)

    # Round 165: the always-on "sandbox / uncertified blocks" banner was removed —
    # for SMB self-serve use it was friction (uploaded + demo data is never
    # "certified"). Certification status is still reported in the publish flow as
    # a non-blocking advisory; nothing blocks everyday exploration or sharing.

    # Round 048: threshold alert banner (shown when a rule's condition is true)
    render_alert_banner(executor)

    if workspace.message():
        st.info(workspace.message())

    # Round 056/075: Excel + PDF export — generated lazily on click (the PDF
    # render is heavy, so we don't rebuild it on every rerun).
    if not readonly:
        if st.button("📤 準備匯出檔案 (Excel / PDF)", key="prep_exports"):
            try:
                from ai4bi.analysis.excel_export import build_report_excel
                from ai4bi.analysis.pdf_export import build_report_pdf
                st.session_state["_export_xlsx"] = build_report_excel(report, executor, active_filters)
                st.session_state["_export_pdf"] = build_report_pdf(report, executor, active_filters)
            except Exception as _exc:  # noqa: BLE001 — export must never break the page
                st.warning(f"匯出產生失敗：{_exc}")
        _xlsx, _pdf = st.session_state.get("_export_xlsx"), st.session_state.get("_export_pdf")
        if _xlsx or _pdf:
            _ecols = st.columns(2)
            if _xlsx:
                _ecols[0].download_button(
                    "⬇ 下載 Excel", data=_xlsx, file_name=f"{report.audit.report_id}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="report_xlsx_dl")
            if _pdf:
                _ecols[1].download_button(
                    "⬇ 下載 PDF 報告", data=_pdf, file_name=f"{report.audit.report_id}.pdf",
                    mime="application/pdf", key="report_pdf_dl")

    _trusted_markdown = (
        "- 示範資料：合成數據，非真實業務資料。\n"
        "- 退貨率（return_rate）以平均值計算，不加總，避免錯誤數字。\n"
        "- 所有計算均可點擊「ℹ️ 資料來源與說明」查看原始數字與計算方式。"
    )

    if readonly:
        # Read-only layout: full-width canvas, Visual Assistant panel hidden
        _render_canvas(report, cache, executor, active_filters)
        with st.expander("Why this result is trusted"):
            st.markdown(_trusted_markdown)
    else:
        _nav_mode = st.session_state.get("_nav_mode", "")
        if "分析" in _nav_mode:
            # Round 134: 分析 mode — full-width canvas, then analysis RESULTS in the
            # wide main area (controls stay in the sidebar). No right pane.
            _render_canvas(report, cache, executor, active_filters)
            with st.expander("Why this result is trusted"):
                st.markdown(_trusted_markdown)
            st.markdown("---")
            st.subheader("分析結果")
            _hint = "在左側「分析」面板選好選項並執行，結果會顯示在這裡。"
            # Round 174: data-driven tabs — retail-only analyses (cohort/basket/
            # RFM) are hidden when the report's data has no customer/product
            # semantics (e.g. semiconductor), matching the sidebar panels' gate.
            _analysis_tabs = _applicable_analysis_tabs(report)
            _tab_objs = st.tabs([_lbl for _lbl, _ in _analysis_tabs])
            for _to, (_lbl, _fn) in zip(_tab_objs, _analysis_tabs):
                with _to:
                    if not _fn():
                        st.caption(_hint)
        elif "資料" in _nav_mode:
            # Round 176: unified Data Workspace — sources/preview, relationships
            # and "create new data" in one place (absorbs the old 🔗 模型 mode).
            # Wide sub-tabs; the report's own charts stay in 探索, so this view is
            # dedicated to data management.
            # (page title is already "🗂️ 資料工作區" — no duplicate subheader)
            _ws_src, _ws_rel, _ws_new = st.tabs(["📋 來源與預覽", "🔗 關聯", "➕ 新增資料"])
            with _ws_src:
                if render_staged_upload_preview():  # just-uploaded file (pre-import)
                    st.markdown("---")
                # block_ids the report's visuals actually reference → 🟢 報表使用中
                # (vs 🟡 評估中 for loaded-but-unused sources).
                _in_use_ids = {
                    ref.block_id for page in report.pages.values()
                    for v in page.visuals.values() for ref in v.query.block_refs
                }
                render_data_source_manager(_report_block_contracts(report), in_use_ids=_in_use_ids)
                render_compare_panel(_report_block_contracts(report))
            with _ws_rel:
                st.caption("把多份資料用共同欄位關聯起來（類似 Power BI 的關係檢視）。")
                _rel_blocks = _report_block_contracts(report)
                render_join_builder(_rel_blocks, expanded=True)
                render_data_model_view(_rel_blocks)
                render_cross_fact_panel(_report_block_contracts(report))
                if (st.session_state.get("_xf_result") is not None
                        and not st.session_state["_xf_result"].empty):
                    st.subheader("跨資料表計算結果")
                    render_cross_fact_results()
            with _ws_new:
                st.caption("上傳檔案、連接資料庫／服務，或從既有資料新產生欄位／資料表。")
                render_upload_panel()
                # Round 176: show the just-uploaded preview RIGHT HERE (where the
                # user uploaded) instead of only on the 來源與預覽 tab — they were
                # losing it across tabs and the "右側主畫布" hint was stale.
                render_staged_upload_preview()
                render_connector_panel()
                render_calc_metric_panel(_report_block_contracts(report))
                render_create_data_panel(_report_block_contracts(report))
                _render_create_report_from_loaded(cache)
                with st.expander("⚙️ 進階：情境參數（What-if）與手動新增圖表", expanded=False):
                    render_what_if_panel()
                    _render_add_visual_panel(report, cache)
        else:
            # Round 153: Power BI-style layout — report canvas on the left, a
            # persistent 🎨 視覺化 (Visualizations) pane on the right that edits the
            # currently-selected visual (chosen via the ask box's chart selector).
            canvas_col, pane_col = st.columns([4, 1.4], gap="medium")
            with canvas_col:
                _render_canvas(report, cache, executor, active_filters)
                with st.expander("Why this result is trusted"):
                    st.markdown(_trusted_markdown)
            with pane_col:
                # Round 136: pin the pane to the viewport while the (often long)
                # canvas scrolls, so you can see the chart AND its edit controls at
                # once. Scoped to this branch only — 分析/模型 full-width modes and
                # read-only layout are untouched.
                st.markdown('<div id="viz-pane-anchor"></div>', unsafe_allow_html=True)
                st.markdown(
                    """<style>
                    div[data-testid="stVerticalBlock"]:has(> div #viz-pane-anchor){
                        position: sticky; top: 3.5rem; align-self: flex-start;
                        max-height: calc(100vh - 4.5rem); overflow-y: auto;
                    }
                    </style>""",
                    unsafe_allow_html=True,
                )
                _render_visualizations_pane(report, cache, _load_all_contracts())


def _render_visualizations_pane(report: ExecutableReportSpec, cache: QueryCache, contracts) -> None:
    """Round 153/154: right-hand Visualizations pane (Power BI placement). Edits the
    selected visual via a real drag-and-drop field-well (custom React component),
    with the dropdown field-well kept as a fallback."""
    st.markdown("#### 🎨 視覺化")
    sel = st.session_state.get("selected_component_id")
    visual = page_id = None
    if sel:
        for pid, page in report.pages.items():
            if sel in page.visuals:
                visual, page_id = page.visuals[sel], pid
                break
    if visual is None:
        st.caption("在上方「① 選擇圖表」挑一張圖，這裡就會出現它的編輯選項"
                   "（拖放欄位 / 圖表類型）。")
        return
    st.caption(f"正在編輯：**{visual.visualization.title or sel}**")

    from ai4bi.ui.components.field_well import field_well, is_available  # noqa: PLC0415
    used_dnd = False
    if is_available() and visual.query.metrics:
        fact_block = visual.query.metrics[0].block_id
        fc = (contracts or {}).get(fact_block)
        if fc is not None:
            measures = [{"name": m.name, "label": m.name, "kind": "measure"}
                        for m in getattr(fc, "metrics", []) or []]
            dims = [{"name": c.name, "label": c.name, "kind": "dimension"}
                    for c in getattr(fc, "columns", []) or []
                    if getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar")
                    and not c.name.lower().endswith(("_id", "_code"))]
            cur_dims = [d.column_name for d in visual.query.dimensions]
            wells = {
                "values": [m.metric_name for m in visual.query.metrics],
                "axis": cur_dims[:1],
                "legend": cur_dims[1:2],
            }
            result = field_well(
                available=measures + dims, wells=wells,
                chart_type=visual.visualization.visual_type.value,
                key=f"fw_dnd_{sel}",
            )
            used_dnd = True
            if isinstance(result, dict) and result.get("nonce"):
                if st.session_state.get(f"_fw_nonce_{sel}") != result["nonce"]:
                    st.session_state[f"_fw_nonce_{sel}"] = result["nonce"]
                    if _apply_field_well_result(report, page_id, sel, visual, fact_block, result):
                        cache.invalidate_all()
                        st.rerun()

    # Dropdown fallback for value/dimension/type (also covers no-build / AppTest).
    label = "或用下拉選單編輯（值 / 分組 / 圖表類型）" if used_dnd else "編輯選項"
    with st.expander(label, expanded=not used_dnd):
        _render_visual_field_well(sel, visual, report, cache, contracts, in_pane=True)
    # Format controls are ALWAYS visible (not buried in the fallback expander),
    # since the drag-drop component doesn't cover axis/sort/labels/legend.
    if visual.visualization.visual_type.value in _CHART_TYPE_LABELS:
        _render_format_controls(sel, visual, report, cache)


def _sort_remap_change(visual, page_id, vid, new_aliases):
    """Round 161: when the measure(s) change, rewrite any sort that referenced an
    old metric alias (now removed) to a current alias — else the query has a sort
    on a non-projected column and errors. Returns a ReportChange or None."""
    cur = [{"column_name": s.column_name, "direction": s.direction.value}
           for s in visual.query.sort]
    if not cur or not new_aliases:
        return None
    new_set = set(new_aliases)
    old_metric_aliases = {m.alias or m.metric_name for m in visual.query.metrics}
    after, changed = [], False
    for s in cur:
        if s["column_name"] not in new_set and s["column_name"] in old_metric_aliases:
            after.append({"column_name": new_aliases[0], "direction": s["direction"]})
            changed = True
        else:
            after.append(s)
    if not changed:
        return None
    return ReportChange(path=f"pages/{page_id}/visuals/{vid}/query/sort",
                        label="排序欄位更新", before=cur, after=after, affects_data=True)


def _apply_field_well_result(report, page_id, sel, visual, fact_block, result) -> bool:
    """Round 154: turn a drag-drop field-well result into a governed query patch
    (metrics + dimensions + chart type). Returns True if anything changed."""
    from ai4bi.query_spec import VisualType  # noqa: PLC0415
    values = [v for v in (result.get("values") or []) if v]
    dims = [d for d in (result.get("axis") or []) + (result.get("legend") or []) if d]
    new_type = result.get("chart_type")
    if not values:
        return False  # a visual needs at least one measure

    changes = []
    cur_metrics = [m.metric_name for m in visual.query.metrics]
    if values != cur_metrics:
        before_m = [{"block_id": m.block_id, "metric_name": m.metric_name, "alias": m.alias,
                     "agg_override": (m.agg_override.value if m.agg_override else None)}
                    for m in visual.query.metrics]
        after_m = [{"block_id": fact_block, "metric_name": v, "alias": v, "agg_override": None}
                   for v in values]
        changes.append(ReportChange(
            path=f"pages/{page_id}/visuals/{sel}/query/metrics",
            label="值", before=before_m, after=after_m, affects_data=True))
        sc = _sort_remap_change(visual, page_id, sel, values)  # keep sort valid
        if sc is not None:
            changes.append(sc)

    cur_dims = [d.column_name for d in visual.query.dimensions]
    if dims != cur_dims:
        before_d = [{"block_id": d.block_id, "column_name": d.column_name, "alias": d.alias,
                     "truncate_date_to": d.truncate_date_to} for d in visual.query.dimensions]
        after_d = [{"block_id": fact_block, "column_name": d, "alias": d, "truncate_date_to": None}
                   for d in dims]
        changes.append(ReportChange(
            path=f"pages/{page_id}/visuals/{sel}/query/dimensions",
            label="分組", before=before_d, after=after_d, affects_data=True))

    cur_type = visual.visualization.visual_type.value
    if new_type and new_type != cur_type:
        try:
            VisualType(new_type)
            if not (new_type == "pivot" and len(dims) < 2):
                changes.append(ReportChange(
                    path=f"pages/{page_id}/visuals/{sel}/visualization/visual_type",
                    label="圖表類型", before=cur_type, after=new_type, affects_data=False))
        except ValueError:
            pass

    if not changes:
        return False
    workspace.stage_proposal(ReportProposal(
        description="拖放編輯視覺", changes=changes, target_component_id=sel))
    workspace.accept_pending()
    return True


if __name__ == "__main__":
    main()
