from __future__ import annotations

import pandas as pd

from ai4bi.query_spec import BlockRef, VisualQuerySpec
from ai4bi.ui import render_visual


class _Cache:
    def __init__(self) -> None:
        self.invalidated = []
        self.put_args = None
        self.registered = []

    def invalidate(self, spec):
        self.invalidated.append(spec.spec_id)

    def get(self, spec):
        return None

    def put(self, spec, df):
        self.put_args = (spec.spec_id, df.copy())

    def register_key_for_spec(self, spec):
        self.registered.append(spec.spec_id)


class _Executor:
    def __init__(self) -> None:
        self.received_filters = None

    def run(self, spec, active_filters=None):
        self.received_filters = active_filters
        return pd.DataFrame({"value": [1]})


def test_execute_with_fallback_passes_active_filters_and_caches_dataframe(monkeypatch):
    store = {}
    monkeypatch.setattr(render_visual, "_last_valid_store", lambda: store)
    spec = VisualQuerySpec(
        spec_id="dynamic_visual",
        block_refs=[BlockRef("process_move_fact")],
        inherit_global_filter=True,
    )
    filters = {"process_move_fact.step_id": ["ETCH"]}
    cache = _Cache()
    executor = _Executor()

    result, error = render_visual.execute_with_fallback(spec, executor, cache, filters)

    assert error is None
    assert executor.received_filters == filters
    assert cache.invalidated == ["dynamic_visual"]
    assert cache.put_args[0] == "dynamic_visual"
    assert cache.put_args[1].equals(result)
    assert store["dynamic_visual"].equals(result)
