"""Local username/password auth that provisions the RLS identity — Round 110.

A pragmatic, functional auth layer (not enterprise SSO): users authenticate
against a registry of salted-SHA-256 password hashes; a successful login yields
an *identity context* (role + row-scope) that the executor uses for row-level
security (Round 103). This closes the loop "who is logged in → which rows they
see" without an external IdP — the registry can later be swapped for one.

A User stores only a password hash (never plaintext) plus the identity dict to
attach on login (e.g. {"city": "台北"} scopes a store manager to their city;
an admin gets {} = full access).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ai4bi.report.share_auth import hash_password, verify_password


@dataclass(frozen=True)
class User:
    username: str
    password_hash: str
    role: str = "viewer"          # "admin" | "manager" | "viewer"
    identity: dict = field(default_factory=dict)  # row-scope, e.g. {"city": "台北"}

    @classmethod
    def create(cls, username: str, password: str, role: str = "viewer",
               identity: Optional[dict] = None) -> "User":
        return cls(username=username, password_hash=hash_password(password),
                   role=role, identity=dict(identity or {}))


def authenticate(username: str, password: str, users: dict[str, User]) -> Optional[dict]:
    """Return the resolved identity context on success, else None.

    The returned dict merges the user's row-scope with a 'role' and 'username'
    key, ready to hand to Executor(identity=...). An admin's empty scope means
    no row restriction.
    """
    user = users.get((username or "").strip())
    if user is None or not verify_password(password, user.password_hash):
        return None
    return {**user.identity, "role": user.role, "username": user.username}


def demo_users() -> dict[str, User]:
    """A small demo registry: an admin (sees all) + per-city store managers."""
    return {
        "admin": User.create("admin", "admin123", role="admin"),
        "taipei": User.create("taipei", "taipei123", role="manager", identity={"city": "台北"}),
        "taichung": User.create("taichung", "taichung123", role="manager", identity={"city": "台中"}),
    }
