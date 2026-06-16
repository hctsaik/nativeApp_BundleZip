"""Workspace Manager — Round 039.

Provides a multi-report workspace UI similar to Power BI's report listing:
- List all saved draft reports
- Create new reports from templates
- Rename, delete, and switch between reports
- Shows report metadata (created, modified, visual count)

This moves the tool from "one report at a time" to a true workspace
where users manage a portfolio of analytical reports.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from ai4bi.report.models import DraftReportStore, ExecutableReportSpec
from ai4bi.ui import workspace

_TEMPLATES_KEY = "workspace_template_choice"


def _report_summary(report: ExecutableReportSpec) -> dict:
    total_visuals = sum(len(page.visuals) for page in report.pages.values())
    modified = report.audit.last_modified_at or report.audit.created_at or "—"
    if modified != "—" and len(modified) >= 19:
        modified = modified[:16].replace("T", " ")
    return {
        "title": report.title,
        "report_id": report.report_id,
        "pages": len(report.pages),
        "visuals": total_visuals,
        "status": report.status,
        "modified": modified,
    }


def render_workspace_panel(
    store: DraftReportStore,
    cache,
) -> None:
    """Render the Workspace Manager expander — Round 039."""
    with st.expander("📁 我的報表工作區", expanded=False):
        st.caption("管理你的所有報表草稿，快速切換或建立新報表。")

        current = workspace.current_report()
        current_id = current.report_id if current else None

        # ── Saved drafts ────────────────────────────────────────────────────
        saved_paths = store.list_paths()
        if saved_paths:
            st.caption(f"**已儲存的草稿（{len(saved_paths)} 份）**")
            for path in saved_paths:
                try:
                    report = store.load(path)
                    info = _report_summary(report)
                    is_current = info["report_id"] == current_id
                    row = st.columns([5, 1, 1])
                    with row[0]:
                        badge = "🟢 " if is_current else ""
                        st.markdown(
                            f"{badge}**{info['title']}** "
                            f"— {info['visuals']} 張圖 · {info['pages']} 頁\n\n"
                            f"<span style='color:#6b7280;font-size:0.8rem'>"
                            f"修改：{info['modified']}</span>",
                            unsafe_allow_html=True,
                        )
                    with row[1]:
                        if not is_current:
                            if st.button("開啟", key=f"ws_open_{path.stem}"):
                                workspace.replace_with_loaded(report)
                                cache.invalidate_all()
                                st.rerun()
                    with row[2]:
                        if st.button("🗑️", key=f"ws_del_{path.stem}", help="刪除此草稿"):
                            path.unlink(missing_ok=True)
                            st.rerun()
                except Exception:  # noqa: BLE001
                    st.caption(f"⚠️ `{path.name}` — 讀取失敗")

        # ── Save current report ──────────────────────────────────────────────
        if current and not current.read_only:
            st.markdown("---")
            if st.button("💾 儲存目前報表", key="ws_save_current", type="primary"):
                saved_path = store.save(current)
                workspace.set_message(f"已儲存：{saved_path.name}")
                st.rerun()

        # ── New report from template ─────────────────────────────────────────
        st.markdown("---")
        st.caption("**從範本建立新報表**")
        template_options = {
            "retail_demo": "🛍️ 零售門市銷售儀表板",
            "cv_demo": "🖼️ 電腦視覺資料集健檢",
            "blank": "📄 空白報表",
        }
        chosen_template = st.selectbox(
            "選擇範本",
            list(template_options.keys()),
            format_func=lambda k: template_options[k],
            key=_TEMPLATES_KEY,
            label_visibility="collapsed",
        )
        if st.button("建立新報表", key="ws_new_from_template"):
            if chosen_template == "retail_demo":
                from ai4bi.report.retail_template import build_retail_demo_report
                new_report = build_retail_demo_report()
            elif chosen_template == "cv_demo":
                # Round 186: CV dataset-health demo. Register its 3 blocks so the
                # executor / NL engine can query them (mirrors the retail pre-reg).
                from ai4bi.report.cv_dataset_template import build_cv_demo_report, cv_contracts
                st.session_state.setdefault("user_blocks", {}).update(cv_contracts())
                new_report = build_cv_demo_report()
            else:
                from ai4bi.report.models import AuditMetadata, ReportPageSpec
                import os, uuid
                new_report = ExecutableReportSpec(
                    audit=AuditMetadata(
                        report_id=f"blank_{uuid.uuid4().hex[:6]}",
                        created_by=os.environ.get("ANALYST_NAME", "user"),
                    ),
                    title="新報表",
                    semantic_model_ref="user@1.0.0",
                    status="user_draft",
                    pages={"main": ReportPageSpec("main", "Overview", {}, [], "概覽")},
                    controls={},
                )
            workspace.replace_with_loaded(new_report)
            cache.invalidate_all()
            st.rerun()
