"""Round 082: RFM / churn-risk scoring."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ai4bi.analysis.rfm import compute_rfm


def _df() -> pd.DataFrame:
    today = date(2026, 5, 30)
    rows = []
    # Active VIP: bought a lot, recently, high spend.
    for i in range(10):
        rows.append({"customer": "VIP", "order_date": (today - timedelta(days=i)).isoformat(),
                     "revenue": 1000.0})
    # Lapsed high-value: used to spend a lot, last purchase long ago.
    for i in range(5):
        rows.append({"customer": "Lapsed", "order_date": (today - timedelta(days=180 + i)).isoformat(),
                     "revenue": 800.0})
    # Casual recent low spender.
    rows.append({"customer": "Casual", "order_date": (today - timedelta(days=3)).isoformat(),
                 "revenue": 50.0})
    # One-time old buyer.
    rows.append({"customer": "OneTime", "order_date": (today - timedelta(days=200)).isoformat(),
                 "revenue": 30.0})
    return pd.DataFrame(rows)


def test_returns_one_row_per_customer():
    rfm = compute_rfm(_df(), "customer", "order_date", "revenue", anchor=date(2026, 5, 30))
    assert set(rfm["customer"]) == {"VIP", "Lapsed", "Casual", "OneTime"}
    assert len(rfm) == 4


def test_recency_frequency_monetary_values():
    rfm = compute_rfm(_df(), "customer", "order_date", "revenue", anchor=date(2026, 5, 30))
    vip = rfm[rfm["customer"] == "VIP"].iloc[0]
    assert vip["距今天數"] == 0          # bought today
    assert vip["購買次數"] == 10         # 10 distinct days
    assert vip["累計金額"] == 10000.0
    lapsed = rfm[rfm["customer"] == "Lapsed"].iloc[0]
    assert lapsed["距今天數"] >= 180


def test_churn_risk_flags_lapsed_customers():
    rfm = compute_rfm(_df(), "customer", "order_date", "revenue", anchor=date(2026, 5, 30))
    risk = dict(zip(rfm["customer"], rfm["流失風險"]))
    assert risk["Lapsed"] is True or bool(risk["Lapsed"])   # low recency score
    assert not bool(risk["VIP"])                            # most recent


def test_at_risk_sorted_first_then_by_value():
    rfm = compute_rfm(_df(), "customer", "order_date", "revenue", anchor=date(2026, 5, 30))
    # First row must be an at-risk customer; among at-risk, highest value first.
    assert bool(rfm.iloc[0]["流失風險"])
    at_risk = rfm[rfm["流失風險"]]
    assert list(at_risk["累計金額"]) == sorted(at_risk["累計金額"], reverse=True)


def test_high_value_lapsed_gets_priority_segment():
    rfm = compute_rfm(_df(), "customer", "order_date", "revenue", anchor=date(2026, 5, 30))
    lapsed = rfm[rfm["customer"] == "Lapsed"].iloc[0]
    assert lapsed["分群"] in ("高價值流失風險", "流失風險")


def test_missing_columns_returns_empty():
    rfm = compute_rfm(_df(), "nope", "order_date", "revenue")
    assert rfm.empty


def test_scores_in_range():
    rfm = compute_rfm(_df(), "customer", "order_date", "revenue", anchor=date(2026, 5, 30))
    for col in ("R", "F", "M"):
        assert rfm[col].between(1, 5).all()
