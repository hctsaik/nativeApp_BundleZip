"""Calculated-measure authoring UI — Round 052.

The derived-metric *engine* (executor `_build_derived_formula_expr`, R045) can
already run safe composite formulas like `(revenue - cost) / revenue`, but there
was no way for a non-technical owner to create one without hand-editing JSON.
This panel adds a no-code form: pick a dataset, name the measure, type a formula,
see it validated live against the same allow-list sandbox the engine uses, save.

Saved measures are appended to the user block's contract (disaggregation_method
= none) so the executor, add-visual panel, alerts, and NL2 all see them.
"""

from __future__ import annotations

import re

import streamlit as st

from ai4bi.analysis.executor import QueryPlanningError, _build_derived_formula_expr
from ai4bi.blocks.contracts import DisaggregationMethod, MetricDefinition
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY


def _column_names(contract) -> list[str]:
    return [c.name for c in contract.columns]


def _insert_token(token: str) -> None:
    """Append a token to the formula box (on_click runs before the rerun, so the
    text_input keyed 'calc_formula' picks it up)."""
    cur = st.session_state.get("calc_formula", "")
    sep = "" if (not cur or cur.endswith((" ", "(", ",")) or token in (")", ",")) else " "
    st.session_state["calc_formula"] = f"{cur}{sep}{token}"


def formula_lineage(formula: str, contract) -> tuple[list[str], list[str]]:
    """Round 152: return (referenced_columns, referenced_metrics) so the user can
    see exactly what a calculated measure depends on."""
    cols = [c.name for c in contract.columns]
    metrics = [m.name for m in contract.metrics]
    used_cols = [c for c in cols if re.search(rf"(?<![\w]){re.escape(c)}(?![\w])", formula)]
    used_metrics = [m for m in metrics if re.search(rf"(?<![\w]){re.escape(m)}(?![\w])", formula)]
    return used_cols, used_metrics


# Round 152: display-format presets → the unit string the render layer already uses.
_UNIT_PRESETS = {
    "數字（無單位）": "", "百分比 %": "%", "金額 $": "$", "金額（元）": "元",
    "千": "千", "萬": "萬", "次數": "次",
}


def validate_formula(formula: str, contract, parameters: dict | None = None) -> tuple[bool, str]:
    """Validate a formula against the engine sandbox. Returns (ok, message).

    Round 060: ``parameters`` (what-if @names) are accepted so formulas that
    reference them validate instead of being rejected as unknown identifiers.
    """
    try:
        _build_derived_formula_expr(
            formula, contract.block_id, set(_column_names(contract)),
            parameters=parameters or {},
        )
        return True, "公式有效 ✅"
    except QueryPlanningError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"無法解析公式：{exc}"


def _existing_derived(contract) -> list[MetricDefinition]:
    return [m for m in contract.metrics if m.disaggregation_method == DisaggregationMethod.none]


def render_calc_metric_panel(blocks: dict | None = None) -> None:
    """Render the '新增計算欄位' panel.

    Round 155: ``blocks`` is the CURRENT report's blocks (so the dataset/column
    options match what you're actually looking at — semiconductor vs retail).
    Falls back to all user blocks when not supplied (tests / older callers)."""
    user_blocks: dict = blocks if blocks is not None else st.session_state.get(_USER_BLOCKS_KEY, {})
    if not user_blocks:
        return

    with st.expander("➗ 新增計算欄位", expanded=False):
        st.caption(
            "用現有欄位組合出新指標，例如：毛利率 = (revenue - cost) / revenue。"
            "支援 + - * / 、SUM/AVG/COUNT、NULLIF、CASE WHEN。"
        )

        block_ids = list(user_blocks.keys())
        block_id = st.selectbox(
            "資料集", block_ids,
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="calc_block_sel",
        )
        contract = user_blocks[block_id]

        name = st.text_input("指標名稱", placeholder="毛利率", key="calc_name")

        # ── Guided authoring: click a column or function to insert it ──────────
        st.caption("點欄位或函式即可插入公式（不用自己打）：")
        _cols = _column_names(contract)
        _grid = st.columns(3)
        for i, col in enumerate(_cols[:12]):
            _grid[i % 3].button(
                col, key=f"calc_ins_col_{block_id}_{col}", width="stretch",
                on_click=_insert_token, args=(col,),
            )
        _fn_grid = st.columns(4)
        for i, tok in enumerate(["+", "-", "*", "/", "(", ")", "NULLIF(", "SUM(",
                                 "AVG(", "COUNT(", "CASE WHEN", "END"]):
            _fn_grid[i % 4].button(
                tok, key=f"calc_ins_fn_{block_id}_{tok}", width="stretch",
                on_click=_insert_token, args=(tok,),
            )

        formula = st.text_input(
            "公式",
            placeholder="(revenue - cost) / NULLIF(revenue, 0)",
            key="calc_formula",
        )
        if st.button("🧹 清空公式", key="calc_clear_formula"):
            st.session_state["calc_formula"] = ""
            st.rerun()

        col1, col2 = st.columns(2)
        with col1:
            unit_label = st.selectbox("顯示格式", list(_UNIT_PRESETS.keys()), key="calc_unit_preset")
            unit = _UNIT_PRESETS[unit_label]
        with col2:
            desc = st.text_input("說明（選填）", key="calc_desc")

        from ai4bi.ui.what_if_panel import get_parameters
        _params = get_parameters()

        # Live validation + lineage (what this measure depends on)
        if formula.strip():
            ok, msg = validate_formula(formula, contract, _params)
            (st.success if ok else st.error)(msg)
            used_cols, used_metrics = formula_lineage(formula, contract)
            if used_cols or used_metrics:
                dep = "、".join(f"`{c}`" for c in used_cols + used_metrics)
                st.caption(f"🔗 依賴欄位／指標：{dep}")
        else:
            ok = False

        if st.button("➕ 建立計算欄位", key="calc_add_btn", type="primary",
                     disabled=not (name.strip() and formula.strip())):
            # Derived-metric names become a quoted SQL alias, so Unicode is fine —
            # keep the user's name verbatim instead of slugifying it to "col".
            metric_name = name.strip()
            existing_names = {m.name for m in contract.metrics}
            if metric_name in existing_names:
                st.error(f"指標名稱「{metric_name}」已存在。")
            else:
                ok, msg = validate_formula(formula, contract, _params)
                if not ok:
                    st.error(f"公式無效：{msg}")
                else:
                    new_metric = MetricDefinition(
                        name=metric_name,
                        formula=formula.strip(),
                        disaggregation_method=DisaggregationMethod.none,
                        unit=unit.strip() or None,
                        description=desc.strip() or name.strip(),
                    )
                    updated = contract.model_copy(
                        update={"metrics": list(contract.metrics) + [new_metric]}
                    )
                    st.session_state[_USER_BLOCKS_KEY][block_id] = updated
                    meta = st.session_state.setdefault(_USER_BLOCK_META_KEY, {})
                    block_meta = meta.setdefault(block_id, {})
                    block_meta.setdefault("metric_names", [])
                    if metric_name not in block_meta["metric_names"]:
                        block_meta["metric_names"].append(metric_name)
                    st.success(f"✅ 已建立計算欄位「{name}」，可在新增圖表、提醒、摘要中使用。")
                    st.rerun()

        # Existing calculated measures
        derived = _existing_derived(contract)
        if derived:
            st.markdown("---")
            st.caption("此資料集的計算欄位：")
            for m in derived:
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.write(f"• **{m.description or m.name}** = `{m.formula}`")
                with c2:
                    if st.button("刪除", key=f"calc_del_{block_id}_{m.name}"):
                        kept = [x for x in contract.metrics if x.name != m.name]
                        st.session_state[_USER_BLOCKS_KEY][block_id] = contract.model_copy(
                            update={"metrics": kept}
                        )
                        st.rerun()
