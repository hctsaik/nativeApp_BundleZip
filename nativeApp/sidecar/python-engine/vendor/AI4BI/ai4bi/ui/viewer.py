"""Read-only draft viewer utilities for AI4BI Streamlit app."""

from __future__ import annotations

import streamlit as st


def is_readonly_mode() -> bool:
    """Return True when the app is launched with ?mode=readonly in the URL."""
    params = st.query_params
    return params.get("mode", "") == "readonly"


def get_draft_path_from_params() -> str | None:
    """Return the draft path from ?draft=<path> query parameter, or None."""
    params = st.query_params
    return params.get("draft") or None


def render_readonly_banner() -> None:
    """Render an orange warning banner indicating read-only validated_demo_draft status."""
    st.warning(
        "Read-only view — 此報表為 validated_demo_draft，未正式發布",
        icon="🔒",
    )
