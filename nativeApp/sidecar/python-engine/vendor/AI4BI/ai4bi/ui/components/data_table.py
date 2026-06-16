"""
ai4bi.ui.components.data_table — Sortable data table visual component.

Uses ``st.dataframe()`` (not ``st.table()``) to support column sorting,
column resizing, and Streamlit's built-in row selection.

Features
--------
- Column aliases: MetricRef.alias / DimensionRef.alias rename the displayed header.
- Numeric formatting: metric columns rendered with thousand-separator commas via
  Streamlit's ``column_config.NumberColumn`` (format string ",.2f").
- Pagination hint: if the DataFrame exceeds 50 rows, the component trims to 50
  and shows "Showing 50 of N rows".  Full server-side pagination is deferred to P5.
- Height: driven by ``style.height_px`` (default 300 px).
- Empty state: renders a "No Data" card without raising.

Column resolution order
-----------------------
1. DimensionRef columns (in spec order) — treated as category / string.
2. MetricRef columns (in spec order) — treated as numeric and formatted.

Any DataFrame columns not covered by the spec are still displayed but receive
no special formatting.  This allows pass-through of columns added by joins.

Dispatch compatibility
----------------------
Signature: render_data_table(query_spec, df, style)
matches the convention used by render_visual._dispatch() for all components.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import streamlit as st
from streamlit.column_config import NumberColumn, TextColumn

from ai4bi.query_spec import DimensionRef, MetricRef, VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)

_MAX_ROWS = 50


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_col(ref: DimensionRef | MetricRef, df: pd.DataFrame) -> Optional[str]:
    """
    Resolve the effective column name present in the DataFrame.

    Tries alias first, then the raw column/metric name.
    Returns None if neither is present.
    """
    alias = getattr(ref, "alias", None)
    raw = getattr(ref, "column_name", None) or getattr(ref, "metric_name", None)
    for candidate in filter(None, [alias, raw]):
        if candidate in df.columns:
            return candidate
    return None


def _build_column_config(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
) -> dict[str, NumberColumn | TextColumn]:
    """
    Build a Streamlit column_config dict from the query spec.

    - DimensionRef columns → TextColumn with alias as header.
    - MetricRef columns → NumberColumn with alias as header and comma format.
    """
    config: dict = {}

    # Dimension columns — string/category treatment
    for dim in query_spec.dimensions:
        col = _resolve_col(dim, df)
        if col is None:
            continue
        header = dim.alias or dim.column_name
        config[col] = TextColumn(label=header)

    # Metric columns — numeric with thousand-separator formatting
    for metric in query_spec.metrics:
        col = _resolve_col(metric, df)
        if col is None:
            continue
        header = metric.alias or metric.metric_name
        config[col] = NumberColumn(
            label=header,
            # Round 159: Streamlit NumberColumn wants a printf/preset format, not a
            # Python spec — ",d" rendered literally as ",d". "localized" gives
            # locale thousands separators and keeps decimals for floats.
            format="localized",
        )

    return config


def _select_display_columns(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
) -> list[str]:
    """
    Return an ordered list of column names to display.

    Order: dimensions first, then metrics, then any remaining DataFrame columns
    not referenced in the spec.  This keeps the table layout consistent with
    how the query was defined.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for dim in query_spec.dimensions:
        col = _resolve_col(dim, df)
        if col and col not in seen:
            ordered.append(col)
            seen.add(col)

    for metric in query_spec.metrics:
        col = _resolve_col(metric, df)
        if col and col not in seen:
            ordered.append(col)
            seen.add(col)

    # Append any remaining columns not in the spec
    for col in df.columns:
        if col not in seen:
            ordered.append(col)

    return ordered


# ---------------------------------------------------------------------------
# Public component
# ---------------------------------------------------------------------------

def render_data_table(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """
    Render an interactive sortable data table using st.dataframe().

    Parameters
    ----------
    query_spec : VisualQuerySpec
        Query spec used to resolve column aliases and formatting rules.
        - dimensions: rendered as text columns (in order).
        - metrics: rendered as formatted numeric columns (in order).
    df : pd.DataFrame
        Result DataFrame from the executor.
    style : VisualizationSpec
        Presentation hints:
          - style.title:     table header caption.
          - style.height_px: table height in pixels (default 300).

    Pagination
    ----------
    If ``len(df) > 50``, only the first 50 rows are displayed.
    A caption "Showing 50 of N rows" is shown below the table.
    Full server-side pagination is planned for P5.

    Sorting
    -------
    Streamlit's st.dataframe() natively supports column-header click-to-sort.
    No additional configuration is required.
    """
    title = style.title or query_spec.spec_id
    height = style.height_px or 300

    # ------------------------------------------------------------------ #
    # Guard: empty DataFrame
    # ------------------------------------------------------------------ #
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        logger.debug("[data_table] spec=%s empty DataFrame", query_spec.spec_id)
        return

    # ------------------------------------------------------------------ #
    # Pagination: cap at MAX_ROWS
    # ------------------------------------------------------------------ #
    total_rows = len(df)
    truncated = total_rows > _MAX_ROWS
    display_df = df.head(_MAX_ROWS) if truncated else df

    # ------------------------------------------------------------------ #
    # Column ordering and config
    # ------------------------------------------------------------------ #
    display_cols = _select_display_columns(query_spec, display_df)
    # Filter to columns that actually exist (safety guard)
    display_cols = [c for c in display_cols if c in display_df.columns]
    display_df = display_df[display_cols]

    column_config = _build_column_config(query_spec, display_df)

    # ------------------------------------------------------------------ #
    # Conditional formatting — highlight_outliers (Round 027)
    # ------------------------------------------------------------------ #
    conditional_formats = style.extra.get("conditional_formats", [])
    styled_df = None
    if conditional_formats and not display_df.empty:
        try:
            import numpy as np
            styler = display_df.style
            for fmt in conditional_formats:
                col = fmt.get("column")
                method = fmt.get("method", "iqr")
                color = fmt.get("color", "#FF4444")
                # Determine numeric columns to check
                if col and col in display_df.columns:
                    num_cols = [col]
                else:
                    num_cols = [c for c in display_df.columns if pd.api.types.is_numeric_dtype(display_df[c])]
                for nc in num_cols:
                    s = display_df[nc].dropna()
                    if method == "threshold":
                        # Round 053: user RAG rule — colour cells crossing a value
                        thr = fmt.get("value", 0)
                        op = fmt.get("operator", "lt")
                        series = display_df[nc]
                        mask = {
                            "lt": series < thr,
                            "lte": series <= thr,
                            "gt": series > thr,
                            "gte": series >= thr,
                            "eq": series == thr,
                        }.get(op, series < thr)
                    elif len(s) < 4:
                        continue
                    elif method == "zscore":
                        mean, std = s.mean(), s.std()
                        mask = (display_df[nc] - mean).abs() > 2.5 * std
                    else:  # iqr
                        q1, q3 = s.quantile(0.25), s.quantile(0.75)
                        iqr = q3 - q1
                        mask = (display_df[nc] < q1 - 1.5 * iqr) | (display_df[nc] > q3 + 1.5 * iqr)
                    # Round 169r: contrast-checked text on the highlight color
                    # (a user-chosen light color would make white invisible).
                    from ai4bi.ui.theme import on_color as _on_color
                    _fg = _on_color(color)
                    styler = styler.apply(
                        lambda col_data, m=mask, c=color, fg=_fg: [
                            f"background-color:{c};color:{fg}" if v else "" for v in m
                        ],
                        subset=[nc],
                    )
            styled_df = styler
        except Exception:  # noqa: BLE001
            styled_df = None

    # ------------------------------------------------------------------ #
    # Render
    # ------------------------------------------------------------------ #
    # Round 172: the visual frame (_render_visual_cell) already renders the
    # title in bold — don't render it again here (it produced a duplicate /
    # inconsistent second title vs other visual types).

    if styled_df is not None:
        st.dataframe(
            styled_df,
            width="stretch",
            height=height,
            hide_index=True,
        )
    else:
        st.dataframe(
            display_df,
            width="stretch",
            height=height,
            column_config=column_config,
            hide_index=True,
        )

    if truncated:
        st.caption(f"Showing {_MAX_ROWS:,} of {total_rows:,} rows")

    logger.debug(
        "[data_table] spec=%s rendered rows=%d (total=%d) cols=%d truncated=%s",
        query_spec.spec_id, len(display_df), total_rows, len(display_cols), truncated,
    )
