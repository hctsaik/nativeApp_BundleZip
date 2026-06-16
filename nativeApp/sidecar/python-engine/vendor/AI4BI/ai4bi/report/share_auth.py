"""Share password gate — Round 064 (first RLS step).

Read-only share links were previously open to anyone with the URL. This adds an
optional password gate: the publisher sets a password; the read-only viewer must
enter it before the report renders. The report stores only a salted SHA-256
hash, never the plaintext.

This is deliberately a *gate*, not row-level security — it controls who can open
a shared report, a pragmatic first step before a real identity provider / RLS.
"""

from __future__ import annotations

import hashlib
import hmac

_SALT = "ai4bi-share-v1$"


def hash_password(password: str) -> str:
    """Return the salted SHA-256 hex digest of a share password."""
    return hashlib.sha256((_SALT + (password or "")).encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str | None) -> bool:
    """True if ``password`` matches ``stored_hash`` (constant-ish comparison)."""
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_password(password), stored_hash)
