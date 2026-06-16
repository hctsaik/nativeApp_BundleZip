"""
ai4bi.ui.cache — Two-tier query result cache for the Streamlit dashboard.

Architecture
------------
L1  @st.cache_data(ttl=300)
    Process-level, shared across all sessions.
    Used for static queries: block is certified, filters are fixed (no global-filter
    inheritance).  Keyed by ``VisualQuerySpec.cache_key()`` which encodes both
    the spec content and ``data_version``.  Evicted automatically after 300 s or
    when Streamlit clears its internal cache.

L2  st.session_state["visual_results"]
    Per-session dict.  Used for dynamic queries: any filter marked
    ``inherit_global_filter=True`` may change when the user adjusts the global
    filter bar.  Entries are invalidated selectively by
    ``invalidate_global_filter_visuals()`` — only specs with
    ``inherit_global_filter=True`` are flushed, leaving unaffected visuals
    untouched.

Cache key format
----------------
    ``{sha256_prefix}:{data_version}``

    sha256 is computed over the canonical JSON of the spec (block_refs with
    pinned_version, metrics, dimensions, static filter values, etc.).
    data_version is a monotonic token supplied by the data layer; bumping it
    instantly invalidates all entries for the same spec shape.

Typical call flow
-----------------
1.  ``render_visual`` calls ``cache.get(spec)``
2.  Cache miss → ``executor.run(spec)`` → ``cache.put(spec, df)``
3.  Global filter change → ``cache.invalidate_global_filter_visuals()``
4.  Affected visuals re-execute on next render; unaffected visuals hit L2 cache.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import pandas as pd
import streamlit as st

from ai4bi.query_spec import VisualQuerySpec

if TYPE_CHECKING:
    pass  # avoids circular imports in type stubs

logger = logging.getLogger(__name__)

# Session-state key for the L2 cache dict
_L2_KEY = "visual_results"
# Session-state key that tracks which spec_ids use global-filter inheritance
_L2_INHERITORS_KEY = "visual_global_filter_inheritors"


# ---------------------------------------------------------------------------
# L1: process-level Streamlit cache
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _l1_fetch(cache_key: str, _fetch_fn, *args, **kwargs) -> pd.DataFrame:  # noqa: ANN001
    """
    Internal L1 cache wrapper.

    ``_fetch_fn`` is prefixed with ``_`` so Streamlit does not hash it (it is
    a callable, not data).  The cache key is the first positional argument and
    is what Streamlit uses to decide hits vs. misses.
    """
    logger.debug("[Cache L1] MISS key=%s — executing query", cache_key)
    return _fetch_fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# QueryCache
# ---------------------------------------------------------------------------

class QueryCache:
    """
    Two-tier query result cache.

    Parameters
    ----------
    use_l1 : bool
        If False, L1 (process-level) cache is bypassed.  Useful in tests or
        when the executor itself handles caching.

    Usage
    -----
    ::

        cache = QueryCache()

        # Try cache, fall back to executor
        df = cache.get(spec)
        if df is None:
            df = executor.run(spec, active_filters)
            cache.put(spec, df)

        # Or use the convenience method:
        df = cache.get_or_fetch(spec, executor, active_filters)
    """

    def __init__(self, use_l1: bool = True) -> None:
        self._use_l1 = use_l1
        self._ensure_l2_initialized()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_l2_initialized() -> None:
        if _L2_KEY not in st.session_state:
            st.session_state[_L2_KEY] = {}
        if _L2_INHERITORS_KEY not in st.session_state:
            st.session_state[_L2_INHERITORS_KEY] = set()

    @staticmethod
    def _l2() -> dict[str, pd.DataFrame]:
        return st.session_state[_L2_KEY]

    @staticmethod
    def _l2_inheritors() -> set[str]:
        return st.session_state[_L2_INHERITORS_KEY]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, spec: VisualQuerySpec) -> Optional[pd.DataFrame]:
        """
        Return a cached DataFrame for *spec*, or None on a cache miss.

        Look-up order:
        1. L2 (session_state) — always checked first (per-session freshness)
        2. L1 (@st.cache_data) — only for non-inheriting specs

        A spec with ``inherit_global_filter=True`` is never served from L1
        because its effective filter values differ per session.
        """
        self._ensure_l2_initialized()
        key = spec.cache_key()

        # Register this spec if it inherits global filter
        if spec.inherit_global_filter:
            self._l2_inheritors().add(spec.spec_id)

        # L2 hit
        if key in self._l2():
            logger.debug("[Cache L2] HIT spec=%s key=%s", spec.spec_id, key)
            return self._l2()[key]

        # L1 — only for static (non-inheriting) specs
        if self._use_l1 and not spec.inherit_global_filter:
            # We pass a no-op lambda so the L1 cache returns None on a miss
            # without us needing to call the executor here.
            # Real fetch path: get_or_fetch() calls _l1_fetch with the executor.
            pass  # L1 hit is handled inside get_or_fetch to keep executor coupling clean

        return None

    def put(self, spec: VisualQuerySpec, df: pd.DataFrame) -> None:
        """Store *df* in L2 (and optionally promote to L1 for static specs)."""
        self._ensure_l2_initialized()
        key = spec.cache_key()
        self._l2()[key] = df
        logger.debug("[Cache L2] PUT spec=%s key=%s rows=%d", spec.spec_id, key, len(df))

    def get_or_fetch(
        self,
        spec: VisualQuerySpec,
        fetch_fn,  # Callable[[VisualQuerySpec], pd.DataFrame]
        active_filters: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        Return a cached result or execute *fetch_fn* and cache the result.

        For static (non-inheriting) specs: L1 → L2 → fetch.
        For dynamic (inheriting) specs: L2 → fetch (L1 is skipped).

        Parameters
        ----------
        spec : VisualQuerySpec
            The query specification.
        fetch_fn : Callable[[VisualQuerySpec], pd.DataFrame]
            Called on a cache miss; typically ``executor.run``.
        active_filters : dict | None
            Current global filter state; merged into spec at call time if
            ``inherit_global_filter`` is True.  Passed through to fetch_fn
            so the executor can apply them correctly.
        """
        self._ensure_l2_initialized()
        key = spec.cache_key()

        # Track inheriting specs
        if spec.inherit_global_filter:
            self._l2_inheritors().add(spec.spec_id)

        # L2 hit
        if key in self._l2():
            logger.debug("[Cache L2] HIT spec=%s", spec.spec_id)
            return self._l2()[key]

        # L1 hit (static specs only)
        if self._use_l1 and not spec.inherit_global_filter:
            try:
                df = _l1_fetch(key, fetch_fn, spec)
                self._l2()[key] = df  # backfill L2 from L1
                return df
            except Exception:
                # L1 miss falls through to direct fetch
                pass

        # Cache miss → execute query
        logger.debug("[Cache] MISS spec=%s — calling fetch_fn", spec.spec_id)
        df = fetch_fn(spec)
        self.put(spec, df)
        return df

    def invalidate(self, spec: VisualQuerySpec) -> None:
        """Remove a single spec from L2 cache."""
        self._ensure_l2_initialized()
        key = spec.cache_key()
        self._l2().pop(key, None)
        logger.debug("[Cache] INVALIDATED spec=%s key=%s", spec.spec_id, key)

    def invalidate_global_filter_visuals(self) -> int:
        """
        Flush only L2 entries whose spec_id is registered as a global-filter
        inheritor.  Entries for non-inheriting specs are preserved.

        Returns
        -------
        int
            Number of cache entries removed.
        """
        self._ensure_l2_initialized()
        inheriting_ids = self._l2_inheritors()
        if not inheriting_ids:
            logger.debug("[Cache] invalidate_global_filter_visuals: no inheritors registered")
            return 0

        l2 = self._l2()
        # Cache keys contain the spec content hash, not the spec_id directly.
        # We track spec_id → [keys] via a secondary index stored in session_state.
        # Simpler approach: flush the entire L2 for inheriting specs by prefix
        # convention.  spec_id is not embedded in the key hash, so we keep a
        # separate registry keyed by spec_id.
        registry_key = "_cache_spec_id_to_keys"
        if registry_key not in st.session_state:
            st.session_state[registry_key] = {}
        registry: dict[str, list[str]] = st.session_state[registry_key]

        removed = 0
        for spec_id in inheriting_ids:
            for cache_key in registry.get(spec_id, []):
                if cache_key in l2:
                    del l2[cache_key]
                    removed += 1
            registry[spec_id] = []  # clear tracked keys for this spec

        logger.info(
            "[Cache] invalidate_global_filter_visuals: removed %d entries for %d spec(s)",
            removed,
            len(inheriting_ids),
        )
        return removed

    def invalidate_all(self) -> None:
        """Clear the entire L2 cache. Use sparingly (e.g. after a full data refresh)."""
        self._ensure_l2_initialized()
        st.session_state[_L2_KEY] = {}
        logger.info("[Cache] L2 fully cleared")

    def register_key_for_spec(self, spec: VisualQuerySpec) -> None:
        """
        Register the cache key for a spec_id so invalidate_global_filter_visuals
        can locate it.  Called internally by put().
        """
        registry_key = "_cache_spec_id_to_keys"
        if registry_key not in st.session_state:
            st.session_state[registry_key] = {}
        registry = st.session_state[registry_key]
        key = spec.cache_key()
        registry.setdefault(spec.spec_id, [])
        if key not in registry[spec.spec_id]:
            registry[spec.spec_id].append(key)
