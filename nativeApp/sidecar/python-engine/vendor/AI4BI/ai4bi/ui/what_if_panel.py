"""What-if parameters — Round 060.

Power BI's what-if parameter: a named numeric value bound to a slider that feeds
calculated measures, so an owner can ask "if I give a 15% discount, what happens
to revenue?" live. Parameters are referenced in a calc-measure formula as
``@name`` (e.g. ``SUM(revenue) * (1 - @discount)``) and the executor substitutes
the current slider value as a numeric literal (never SQL).

State:
    st.session_state["what_if_params"]      = {name: current_value}
    st.session_state["what_if_param_defs"]  = {name: {min, max, step, default}}
"""

from __future__ import annotations

import streamlit as st

_PARAMS_KEY = "what_if_params"
_DEFS_KEY = "what_if_param_defs"


def get_parameters() -> dict[str, float]:
    return dict(st.session_state.get(_PARAMS_KEY, {}))


def render_what_if_panel() -> None:
    """Render the what-if parameter manager (sidebar)."""
    defs: dict = st.session_state.setdefault(_DEFS_KEY, {})
    params: dict = st.session_state.setdefault(_PARAMS_KEY, {})

    with st.expander(f"🎚️ What-If 參數（{len(defs)}）", expanded=False):
        st.caption(
            "建立可調整的假設值，並在計算欄位裡用 @名稱 引用。"
            "例如：折後營收 = SUM(revenue) * (1 - @折扣率)。"
        )

        with st.form("what_if_add", clear_on_submit=True):
            st.caption("新增參數")
            name = st.text_input("名稱", placeholder="折扣率", key="wi_name")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                mn = st.number_input("最小", value=0.0, key="wi_min")
            with c2:
                mx = st.number_input("最大", value=1.0, key="wi_max")
            with c3:
                step = st.number_input("間隔", value=0.05, key="wi_step")
            with c4:
                default = st.number_input("預設", value=0.0, key="wi_default")
            if st.form_submit_button("➕ 新增") and name.strip():
                nm = name.strip()
                if mx <= mn:
                    st.error("最大值必須大於最小值。")
                else:
                    defs[nm] = {"min": float(mn), "max": float(mx),
                                "step": float(step or 0.01), "default": float(default)}
                    params[nm] = float(default)
                    st.rerun()

        # Sliders for existing parameters
        for nm, d in list(defs.items()):
            c1, c2 = st.columns([5, 1])
            with c1:
                val = st.slider(
                    nm, min_value=d["min"], max_value=d["max"],
                    value=float(params.get(nm, d["default"])), step=d["step"],
                    key=f"wi_slider_{nm}",
                )
                params[nm] = float(val)
            with c2:
                if st.button("刪除", key=f"wi_del_{nm}"):
                    defs.pop(nm, None)
                    params.pop(nm, None)
                    st.rerun()
