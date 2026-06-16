"""Content-addressed DataFrame store — Round 051.

Defuses the "InlineDataSource time bomb": uploading a 50K-row CSV used to embed
all rows as a list[dict] inside the DataBlockContract, which then lived in
st.session_state and was carried (and re-serialised) on every Streamlit rerun —
an OOM risk as soon as a user has a few datasets.

Instead, the rows live once in this process-global store keyed by a content
hash; the contract carries only the hash (CachedDataSource). Identical uploads
deduplicate automatically. The store is a module-level dict so it survives
reruns within a process and is trivially testable; in Streamlit one process
serves the session, and session_state + this store reset together.

materialize_dataframe() is the single accessor that resolves *any* data source
(inline or cached) to a DataFrame, so callers never branch on source_type.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from ai4bi.blocks.contracts import DataBlockContract

# hash → DataFrame (process-global, deduplicated by content)
_STORE: dict[str, pd.DataFrame] = {}


def _hash_dataframe(df: pd.DataFrame) -> str:
    """Stable content hash of a DataFrame (shape + column names + values)."""
    hasher = hashlib.sha256()
    hasher.update(",".join(map(str, df.columns)).encode())
    hasher.update(str(df.shape).encode())
    try:
        values = pd.util.hash_pandas_object(df, index=True).values
        hasher.update(values.tobytes())
    except Exception:  # noqa: BLE001 — fall back to a cheaper digest
        hasher.update(df.to_csv(index=True).encode("utf-8", errors="ignore"))
    return hasher.hexdigest()[:16]


def put_dataframe(df: pd.DataFrame) -> str:
    """Store a DataFrame and return its content hash (idempotent)."""
    key = _hash_dataframe(df)
    if key not in _STORE:
        _STORE[key] = df.copy()
    return key


def has(content_hash: str) -> bool:
    return content_hash in _STORE


def get_dataframe(content_hash: str) -> pd.DataFrame:
    """Return the stored DataFrame, or raise KeyError if it is gone."""
    if content_hash not in _STORE:
        raise KeyError(
            f"DataFrame for content_hash '{content_hash}' is not in the store "
            f"(process may have restarted). Re-upload the data."
        )
    return _STORE[content_hash]


def clear() -> None:
    """Drop all stored DataFrames (used by tests)."""
    _STORE.clear()


def source_row_count(contract: "DataBlockContract") -> "int | None":
    """Row count WITHOUT materializing the data (Round 167).

    Reads metadata only — CachedDataSource carries ``row_count``; an
    InlineDataSource knows ``len(records)``. Returns None when the count can't
    be known without loading (so callers can show "未知" instead of paying for
    a full scan). This is the cheap basis for the data-source inspector.
    """
    from ai4bi.blocks.contracts import CachedDataSource, InlineDataSource

    src = contract.data_source
    if isinstance(src, CachedDataSource):
        return int(src.row_count)
    if isinstance(src, InlineDataSource):
        return len(src.records)
    return None


def sample_dataframe(contract: "DataBlockContract", n: int = 20) -> pd.DataFrame:
    """Return at most ``n`` rows for a *resource-safe preview* (Round 167).

    Never renders or copies the whole dataset:
    - InlineDataSource → builds a DataFrame from only the first ``n`` records.
    - CachedDataSource → ``.head(n)`` of the in-store frame (a cheap view; the
      rows already live once in the store, so no extra materialization).

    Use this for previews/profiling instead of ``materialize_dataframe`` so a
    50K-row source doesn't get fully rendered into the browser or scanned for
    stats on every rerun.
    """
    from ai4bi.blocks.contracts import CachedDataSource, InlineDataSource

    n = max(0, int(n))
    src = contract.data_source
    if isinstance(src, InlineDataSource):
        return pd.DataFrame(src.records[:n])
    if isinstance(src, CachedDataSource):
        return get_dataframe(src.content_hash).head(n)
    raise TypeError(
        f"Cannot sample data source of type {type(src).__name__} "
        f"for block '{contract.block_id}'"
    )


def materialize_dataframe(contract: "DataBlockContract") -> pd.DataFrame:
    """Resolve any contract's data source to a DataFrame.

    - InlineDataSource → DataFrame from its records
    - CachedDataSource → DataFrame from the content store
    Other source types raise TypeError (no in-process rows available).
    """
    from ai4bi.blocks.contracts import CachedDataSource, InlineDataSource

    src = contract.data_source
    if isinstance(src, InlineDataSource):
        return pd.DataFrame(src.records)
    if isinstance(src, CachedDataSource):
        return get_dataframe(src.content_hash)
    raise TypeError(
        f"Cannot materialize data source of type "
        f"{type(src).__name__} for block '{contract.block_id}'"
    )
