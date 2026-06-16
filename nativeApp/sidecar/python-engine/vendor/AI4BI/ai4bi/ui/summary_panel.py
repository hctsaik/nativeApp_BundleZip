"""Business summary panel — Round 050.

Sidebar panel that generates the owner's "morning digest" on demand, offers it
as a download, and stores a delivery schedule preference.

Honest scope: the Streamlit MVP has no background mailer, so "schedule" saves a
preference and the digest is generated/downloaded in-app. generate_summary() is
pure, so a future backend job can produce and email the same digest.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.alerts import AlertRule
from ai4bi.analysis.summary import generate_summary
from ai4bi.blocks.contracts import DataBlockContract

_SCHEDULE_KEY = "summary_schedule"
_PERIOD_CHOICES = {"week": "週報（vs 上週）", "month": "月報（vs 上月）"}


def _current_report_block_id() -> str | None:
    """Primary block of the report currently on screen, so the digest matches it."""
    try:
        from ai4bi.ui import workspace
        report = workspace.current_report()
        for page in report.pages.values():
            for vid in page.visual_order:
                refs = page.visuals[vid].query.block_refs
                if refs:
                    return refs[0].block_id
    except Exception:  # noqa: BLE001
        pass
    return None


def render_summary_panel(
    contracts: dict[str, DataBlockContract],
    executor,
) -> None:
    """Render the summary generation + schedule panel (sidebar)."""
    with st.expander("📋 業務摘要", expanded=False):
        st.caption("一鍵產生業績摘要：期間業績、成長率、前三名、提醒。可下載分享。")

        period = st.selectbox(
            "摘要週期",
            list(_PERIOD_CHOICES.keys()),
            format_func=lambda p: _PERIOD_CHOICES[p],
            key="summary_period_sel",
        )

        if st.button("✨ 產生摘要", key="summary_gen_btn", type="primary"):
            rules: list[AlertRule] = st.session_state.get("alert_rules", [])
            preferred = _current_report_block_id()
            report = generate_summary(
                executor, contracts, period=period, alert_rules=rules,
                preferred_block_id=preferred,
            )
            st.session_state["_summary_md"] = report.to_markdown()

        if st.session_state.get("_summary_md"):
            st.caption("✅ 結果顯示在右側主畫面")

        # ── Schedule preference (saved, delivery is manual in the MVP) ─────────
        st.markdown("---")
        sched = st.session_state.get(_SCHEDULE_KEY, {"enabled": False, "freq": "daily"})
        enabled = st.checkbox("排程定期摘要", value=sched.get("enabled", False), key="summary_sched_on")
        freq = st.selectbox(
            "頻率", ["daily", "weekly"],
            index=["daily", "weekly"].index(sched.get("freq", "daily")),
            format_func=lambda f: {"daily": "每天", "weekly": "每週"}[f],
            key="summary_sched_freq",
            disabled=not enabled,
        )
        st.session_state[_SCHEDULE_KEY] = {"enabled": enabled, "freq": freq, "period": period}
        if enabled:
            st.caption(
                "✅ 已記錄排程偏好。目前版本請於此面板手動產生並下載；"
                "自動寄送將於連接後端後啟用。"
            )


def render_summary_results() -> bool:
    """Render the business-summary digest in the main canvas. Returns True if rendered."""
    md = st.session_state.get("_summary_md")
    if not md:
        return False
    st.markdown(md)
    st.download_button(
        "⬇️ 下載摘要 (.md)",
        data=md.encode("utf-8"),
        file_name="business_summary.md",
        mime="text/markdown",
        key="summary_dl_btn",
    )
    return True
