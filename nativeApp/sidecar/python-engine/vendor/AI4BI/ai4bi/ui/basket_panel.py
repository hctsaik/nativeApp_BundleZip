"""Market-basket panel — Round 077.

"常一起購買的商品" — derives baskets from customer+date+store (no order id
needed) and shows the top product pairs by lift. Reads rows from the content
store (R051); pure pandas.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.basket import basket_affinity
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.blocks.datastore import materialize_dataframe
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_PRODUCT_HINTS = ("product", "item", "sku", "商品", "品項")
_BASKET_HINTS = ("customer", "member", "date", "_at", "store", "客戶", "門市", "日期")
_ID_HINTS = ("id", "code", "sku")


def _fact_blocks(blocks: dict | None = None) -> dict[str, DataBlockContract]:
    blocks = blocks if blocks is not None else st.session_state.get(_USER_BLOCKS_KEY, {})
    return {b: c for b, c in blocks.items() if c.block_type == BlockType.fact}


# A real "basket" needs a product column AND a transaction grouping (a customer/
# order/store) — not merely a date — so fab data (product_family but no customers)
# doesn't wrongly qualify.
_BASKET_KEY_STRONG = ("customer", "member", "order", "訂單", "會員", "顧客", "store", "門市", "客戶")


def _basket_applicable(contract) -> bool:
    cols = [c.name.lower() for c in contract.columns]
    has_product = any(any(h in c for h in _PRODUCT_HINTS) for c in cols)
    has_basket_key = any(any(h in c for h in _BASKET_KEY_STRONG) for c in cols)
    return has_product and has_basket_key


def render_basket_panel(blocks: dict | None = None) -> None:
    # Round 156: only on data with products AND a transaction grouping; CURRENT-report driven.
    facts = {b: c for b, c in _fact_blocks(blocks).items() if _basket_applicable(c)}
    if not facts:
        return
    with st.expander("🧺 常一起購買（商品關聯）", expanded=False):
        st.caption("找出常被一起購買的商品組合（依同一顧客同日同店視為一籃）。")
        bid = st.selectbox(
            "資料集", list(facts.keys()),
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="basket_block",
        )
        contract = facts[bid]
        cols = [c.name for c in contract.columns]

        # product column
        prod_default = next((i for i, c in enumerate(cols)
                             if any(h in c.lower() for h in _PRODUCT_HINTS)
                             and not c.lower().endswith(("_id", "_sku", "_code"))), 0)
        product_col = st.selectbox("商品欄位", cols, index=prod_default, key="basket_product")
        # basket key columns
        basket_default = [c for c in cols
                          if any(h in c.lower() for h in _BASKET_HINTS) and c != product_col]
        basket_cols = st.multiselect("一籃的定義（這些相同視為同一次購買）", cols,
                                     default=basket_default[:3], key="basket_keys")

        if st.button("🔍 找出商品關聯", key="basket_run", type="primary", disabled=not basket_cols):
            try:
                df = materialize_dataframe(contract)
                st.session_state["_basket_result"] = basket_affinity(df, product_col, basket_cols)
            except Exception as exc:  # noqa: BLE001
                st.error(f"無法計算：{exc}")

        if st.session_state.get("_basket_result") is not None:
            st.caption("✅ 結果顯示在右側主畫面")


def render_basket_results() -> bool:
    """Render market-basket result in the main canvas. Returns True if rendered."""
    res = st.session_state.get("_basket_result")
    if res is None:
        return False
    if res.empty:
        st.info("找不到明顯的商品關聯（可能每籃只有單一商品）。")
    else:
        st.caption("提升度 > 1 表示兩商品正相關（常一起買）。")
        st.dataframe(res, width="stretch", hide_index=True)
    return True
