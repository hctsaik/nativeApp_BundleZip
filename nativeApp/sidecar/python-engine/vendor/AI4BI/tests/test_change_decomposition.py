"""Round 178: ratio-metric change decomposition must NOT sum group ratios
(scenario S6 was fatal: summing per-group yields gave "Memory ↓894%, +1.2%").
Plus decline-trigger phrasing coverage (S1).
"""

from __future__ import annotations

import math

from ai4bi.ai.nl2proposal import _metric_is_ratio, _DECLINE_TRIGGERS


def test_metric_is_ratio_name_heuristic():
    # no contract → fall back to name heuristic
    assert _metric_is_ratio({}, "wafer_yield_fact", "weighted_yield_pct") is True
    assert _metric_is_ratio({}, "wafer_yield_fact", "yield_pct") is True
    assert _metric_is_ratio({}, "f", "defect_rate") is True
    assert _metric_is_ratio({}, "f", "move_count") is False
    assert _metric_is_ratio({}, "f", "good_die") is False


def test_metric_is_ratio_uses_contract_disaggregation():
    from ai4bi.blocks.contracts import (
        BlockType, ColumnSchema, DataBlockContract, DataClassification,
        DisaggregationMethod, InlineDataSource, MetricDefinition, PolicySpec,
    )
    c = DataBlockContract(
        block_id="f", block_type=BlockType.fact, grain="row", version="1.0.0",
        description="f", primary_keys=[],
        columns=[ColumnSchema(name="amt", data_type="float")],
        metrics=[
            MetricDefinition(name="amt", formula="SUM(amt)",
                             disaggregation_method=DisaggregationMethod.sum),
            MetricDefinition(name="rate", formula="AVG(amt)",
                             disaggregation_method=DisaggregationMethod.average),
        ],
        data_source=InlineDataSource(records=[{"amt": 1.0}]),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    contracts = {"f": c}
    assert _metric_is_ratio(contracts, "f", "rate") is True   # average → ratio
    assert _metric_is_ratio(contracts, "f", "amt") is False   # sum → additive


def test_decline_triggers_cover_common_fab_phrasings():
    for phrase in ("一直掉", "一直跌", "逐週下滑", "一直在掉", "持續下滑"):
        assert any(t in phrase or phrase in t or t == phrase for t in _DECLINE_TRIGGERS) \
            or phrase in _DECLINE_TRIGGERS, f"{phrase} not covered"


def test_ratio_decomposition_returns_weighted_overall_not_summed_ratios():
    """End-to-end on the fab demo: the yield change decomposition must report a
    sane weighted overall (not a sum of group rates) and NaN contributions."""
    from ai4bi.report.fab_template import fab_contracts
    from ai4bi.analysis.executor import Executor
    from ai4bi.analysis.time_intelligence import compute_grouped_comparison
    from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec

    cs = fab_contracts()
    # locate a yield fact: a block with a ratio yield metric + a date + a category
    target = None
    for bid, c in cs.items():
        ratio_m = next((m for m in c.metrics
                        if getattr(getattr(m, "disaggregation_method", None), "value", None)
                        in ("average", "none") and "yield" in m.name.lower()), None)
        dates = [col.name for col in c.columns if col.data_type in ("date", "timestamp")]
        cats = [col.name for col in c.columns if col.data_type in ("string", "str")
                and not col.name.lower().endswith(("_id", "id"))
                and "event" not in col.name.lower()]
        if ratio_m and dates and cats:
            target = (bid, ratio_m.name, dates[0], cats[0])
            break
    if target is None:
        import pytest
        pytest.skip("no ratio-yield fact with date+category in fab demo")

    bid, metric, date_col, dim = target
    ex = Executor(extra_contracts=cs)
    base = VisualQuerySpec(f"x_{metric}", [BlockRef(bid)],
                           metrics=[MetricRef(bid, metric, metric)])
    df = compute_grouped_comparison(
        ex, base, date_block_id=bid, date_column=date_col,
        dimension_col=dim, period="month", metric_col=metric, is_ratio=True,
    )
    if df.empty:
        import pytest
        pytest.skip("decomposition window did not resolve on demo data")
    # contributions are undefined for a ratio → NaN (no fabricated 894%)
    assert df["contribution_pct"].isna().all()
    # weighted overall is carried + within a plausible yield range (not summed)
    ov_cur = df.attrs.get("overall_current")
    assert ov_cur is not None and not math.isnan(ov_cur)
    assert 0.0 <= ov_cur <= 100.0, f"overall yield {ov_cur} looks summed, not weighted"
