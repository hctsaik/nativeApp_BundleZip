"""Round 110: local login/role auth that provisions the RLS identity."""

from __future__ import annotations

from ai4bi.analysis.executor import Executor
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec
from ai4bi.report.auth import User, authenticate, demo_users
from ai4bi.report.retail_template import build_retail_sales_block


def test_password_is_hashed_not_stored_plaintext():
    u = User.create("bob", "secret", role="manager", identity={"city": "台北"})
    assert u.password_hash != "secret"
    assert "secret" not in u.password_hash


def test_authenticate_success_returns_identity():
    users = demo_users()
    ident = authenticate("taipei", "taipei123", users)
    assert ident is not None
    assert ident["city"] == "台北"
    assert ident["role"] == "manager"
    assert ident["username"] == "taipei"


def test_authenticate_wrong_password():
    assert authenticate("taipei", "wrong", demo_users()) is None


def test_authenticate_unknown_user():
    assert authenticate("nobody", "x", demo_users()) is None


def test_admin_has_no_row_scope():
    ident = authenticate("admin", "admin123", demo_users())
    assert ident["role"] == "admin"
    assert "city" not in ident  # admin sees everything


def test_login_identity_drives_rls_end_to_end():
    # a logged-in city manager's identity scopes the executor's rows
    ident = authenticate("taipei", "taipei123", demo_users())
    scope = {"city": ident["city"]}  # how the app maps it
    ex = Executor(extra_contracts={"retail_sales": build_retail_sales_block()}, identity=scope)
    spec = VisualQuerySpec("t", [BlockRef("retail_sales")],
                           metrics=[MetricRef("retail_sales", "revenue", "營收")])
    scoped = ex.run(spec)["營收"].iloc[0]

    ex_all = Executor(extra_contracts={"retail_sales": build_retail_sales_block()})
    full = ex_all.run(spec)["營收"].iloc[0]
    assert 0 < scoped < full
