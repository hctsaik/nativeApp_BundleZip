"""
ai4bi.ui.components.map_chart — Geographic bubble map.

Round 083: fills the previously-dead VisualType.map enum (it had no renderer,
so any map visual silently hit "not yet implemented"). Plots a bubble per
resolvable location (size = first metric) on an OpenStreetMap basemap — no
mapbox token required.

Dispatch signature: render_map(query_spec, df, style)
- First dimension → location name (resolved to lat/lon via analysis.geo).
- First metric    → bubble size + colour.
Unmappable locations are dropped, with a caption noting how many.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from ai4bi.analysis.geo import attach_coords
from ai4bi.query_spec import VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)


def _resolve_col(ref, df: pd.DataFrame) -> Optional[str]:
    alias = getattr(ref, "alias", None)
    raw = getattr(ref, "column_name", None) or getattr(ref, "metric_name", None)
    for c in filter(None, [alias, raw]):
        if c in df.columns:
            return c
    return None


def render_map(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Render a geographic bubble map (OpenStreetMap basemap)."""
    title = style.title or query_spec.spec_id

    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        return
    if not query_spec.dimensions:
        st.warning(f"[{query_spec.spec_id}] 地圖需要一個地點維度（例如 城市 / 縣市）。")
        return

    loc_col = _resolve_col(query_spec.dimensions[0], df)
    if loc_col is None:
        st.error(f"[{query_spec.spec_id}] 找不到地點欄位。")
        return

    geo = attach_coords(df, loc_col)
    if geo.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("無法將地點對應到座標（目前支援台灣縣市與部分城市）。", icon="🗺️")
        return

    size_col = _resolve_col(query_spec.metrics[0], df) if query_spec.metrics else None
    dropped = len(df) - len(geo)

    from ai4bi.ui.theme import get_active_theme
    _theme = get_active_theme()
    fig = px.scatter_map(
        geo,
        lat="_lat",
        lon="_lon",
        size=size_col if size_col else None,
        color=size_col if size_col else None,
        hover_name=loc_col,
        size_max=40,
        zoom=6,
        height=style.height_px,
        color_continuous_scale=_theme.sequential,  # Round 164: themed ramp
    )
    fig.update_layout(
        map_style="carto-darkmatter" if _theme.base == "dark" else "carto-positron",
        margin=dict(l=0, r=0, t=40, b=0),
        title=style.title or "",
        font=dict(family=_theme.font_family, color=_theme.text_color),
        paper_bgcolor=_theme.paper_bg,
    )
    st.plotly_chart(fig, width="stretch", key=f"map_{query_spec.spec_id}")
    if dropped:
        st.caption(f"※ {dropped} 個地點無法對應座標，已略過。")

    logger.debug("[map_chart] spec=%s mapped=%d dropped=%d",
                 query_spec.spec_id, len(geo), dropped)
