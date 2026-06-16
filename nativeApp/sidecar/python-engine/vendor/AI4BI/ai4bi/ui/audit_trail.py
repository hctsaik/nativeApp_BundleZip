"""Audit Trail — Round 040.

Every change applied to a report is logged to an immutable session-scoped
audit trail. This satisfies the enterprise requirement for change accountability
and supports rollback / compliance review.

Structure:
    st.session_state["audit_trail"] = [
        {
            "ts": "14:23:55",
            "date": "2026-05-29",
            "user": "analyst_name",
            "action": "Apply Proposal",
            "description": "Style: line_revenue_trend → red",
            "report_id": "retail_demo_v1",
            "revision_before": 3,
            "revision_after": 4,
        },
        ...
    ]

Max 200 entries (rolling).
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import Any

import streamlit as st

_AUDIT_KEY = "audit_trail"
_MAX_ENTRIES = 200


def record_change(
    action: str,
    description: str,
    report_id: str,
    revision_before: int,
    revision_after: int,
    user: str = "user",
) -> None:
    """Append a change event to the audit trail."""
    if _AUDIT_KEY not in st.session_state:
        st.session_state[_AUDIT_KEY] = []
    now = datetime.now(timezone.utc)
    st.session_state[_AUDIT_KEY].append({
        "ts": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "user": user,
        "action": action,
        "description": description[:120],
        "report_id": report_id,
        "revision_before": revision_before,
        "revision_after": revision_after,
    })
    # Rolling window
    st.session_state[_AUDIT_KEY] = st.session_state[_AUDIT_KEY][-_MAX_ENTRIES:]


def render_audit_trail() -> None:
    """Render the Audit Trail expander — Round 040."""
    trail: list[dict] = st.session_state.get(_AUDIT_KEY, [])

    with st.expander(f"📋 變更記錄（{len(trail)} 筆）", expanded=False):
        if not trail:
            st.caption("尚無變更記錄。每次套用提案都會在此留下記錄。")
            return

        # Export as CSV
        import io
        import csv
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["date", "ts", "user", "action", "description", "report_id", "revision_before", "revision_after"])
        writer.writeheader()
        writer.writerows(trail)
        st.download_button(
            "⬇ 匯出變更記錄 (CSV)",
            data=buf.getvalue().encode("utf-8-sig"),
            file_name="audit_trail.csv",
            mime="text/csv",
            key="audit_export_btn",
        )

        st.markdown("---")
        # Show most recent first
        for entry in reversed(trail[-50:]):  # show last 50
            action_icon = {
                "Apply Proposal": "✅",
                "Undo": "↩️",
                "Redo": "↪️",
                "Load Report": "📂",
                "New Report": "📄",
                "Save Draft": "💾",
            }.get(entry.get("action", ""), "📝")

            rev_change = ""
            if entry.get("revision_after") is not None:
                rev_change = f" (r{entry['revision_before']} → r{entry['revision_after']})"

            st.markdown(
                f"{action_icon} `{entry['date']} {entry['ts']}` "
                f"**{entry.get('action', '?')}**{rev_change}  \n"
                f"<span style='color:#374151'>{entry.get('description', '')}</span>",
                unsafe_allow_html=True,
            )
