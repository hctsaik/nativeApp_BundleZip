"""RFM / churn-risk panel — Round 082.

"哪些客戶快流失了？誰是 VIP？" — per-customer Recency/Frequency/Monetary
scoring with a churn-risk flag. Reads rows from the content store (R051);
pure pandas, so it works where the single-GROUP-BY executor cannot.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.rfm import compute_rfm
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.blocks.datastore import materialize_dataframe
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_CUSTOMER_HINTS = ("customer", "member", "client", "user", "客戶", "顧客", "會員")
_DATE_HINTS = ("date", "_at", "time", "日期", "時間")
_MONEY_HINTS = ("revenue", "amount", "sales", "spend", "price", "total", "營收", "金額", "銷售", "消費")


def _fact_blocks(blocks: dict | None = None) -> dict[str, DataBlockContract]:
    blocks = blocks if blocks is not None else st.session_state.get(_USER_BLOCKS_KEY, {})
    return {b: c for b, c in blocks.items() if c.block_type == BlockType.fact}


def _guess(cols: list[str], hints: tuple[str, ...], default: int = 0) -> int:
    for i, c in enumerate(cols):
        if any(h in c.lower() for h in hints):
            return i
    return default


def _has(cols: list[str], hints: tuple[str, ...]) -> bool:
    return any(any(h in c.lower() for h in hints) for c in cols)


# Strong customer hints (exclude bare "_id" so lot_id/tool_id don't count).
_STRONG_CUSTOMER = ("customer", "member", "client", "user", "顧客", "會員", "客戶")


def _rfm_applicable(contract) -> bool:
    cols = [c.name for c in contract.columns]
    return _has(cols, _STRONG_CUSTOMER) and _has(cols, _DATE_HINTS) and _has(cols, _MONEY_HINTS)


def render_rfm_panel(blocks: dict | None = None) -> None:
    # Round 156: only offer RFM on data that actually has customer + date + money
    # columns (it's a retail/transaction analysis); driven by the CURRENT report.
    facts = {b: c for b, c in _fact_blocks(blocks).items() if _rfm_applicable(c)}
    if not facts:
        return
    with st.expander("🎯 客戶流失風險 / RFM 分群", expanded=False):
        st.caption("依最近購買(R)、購買頻率(F)、累計金額(M)為每位客戶評分，標出流失風險與 VIP。")
        bid = st.selectbox(
            "資料集", list(facts.keys()),
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="rfm_block",
        )
        contract = facts[bid]
        cols = [c.name for c in contract.columns]
        if len(cols) < 3:
            st.info("此資料集欄位不足以計算 RFM。")
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            customer_col = st.selectbox("客戶欄位", cols,
                                        index=_guess(cols, _CUSTOMER_HINTS), key="rfm_customer")
        with c2:
            date_col = st.selectbox("日期欄位", cols,
                                    index=_guess(cols, _DATE_HINTS), key="rfm_date")
        with c3:
            money_col = st.selectbox("金額欄位", cols,
                                     index=_guess(cols, _MONEY_HINTS), key="rfm_money")

        if st.button("🔍 計算 RFM", key="rfm_run", type="primary"):
            try:
                df = materialize_dataframe(contract)
                st.session_state["_rfm_result"] = compute_rfm(df, customer_col, date_col, money_col)
            except Exception as exc:  # noqa: BLE001
                st.error(f"無法計算：{exc}")

        if st.session_state.get("_rfm_result") is not None:
            st.caption("✅ 結果顯示在右側主畫面")


def render_rfm_results() -> bool:
    """Render RFM result in the main canvas. Returns True if rendered."""
    res = st.session_state.get("_rfm_result")
    if res is None:
        return False
    if res.empty:
        st.info("資料不足以計算 RFM（請確認客戶、日期、金額欄位）。")
    else:
        at_risk = int(res["流失風險"].sum())
        st.markdown(f"**{len(res)} 位客戶｜⚠️ {at_risk} 位有流失風險**")
        st.dataframe(res, width="stretch", hide_index=True)
        csv = res.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇ 下載流失風險名單 CSV", data=csv,
                           file_name="rfm_churn_risk.csv", key="rfm_csv")
    return True
