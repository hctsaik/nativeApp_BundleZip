"""Round 113-114: semiconductor fab NL scenarios route + answer correctly.

These are the scored scenarios from the fab validation rounds, locked in as
regression tests (they use the real fab dataset + executor).
"""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


@pytest.fixture(scope="module")
def env():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def _ask(env, prompt):
    svc, report, c, ex = env
    return svc.propose(prompt, report, None, contracts=c, executor=ex)


def test_overall_yield_answer(env):
    r = _ask(env, "整體良率多少？")
    assert r.direct_answer is not None
    # Round 178: ETCH-02 yield detractor → fab-wide yield in the high-80s.
    assert 80 < r.direct_answer.value < 95


def test_bottleneck_step_ranking(env):
    r = _ask(env, "哪個製程站等待時間最長？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["step_id"] == "ETCH"  # embedded bottleneck


def test_yield_commonality_by_etch_tool(env):
    r = _ask(env, "哪台 ETCH 機台良率最低？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["etch_tool_id"] == "ETCH-02"  # embedded detractor


def test_worst_product_yield(env):
    r = _ask(env, "哪個產品良率最低？")
    assert r.result_table is not None
    # the ranking must be ascending (lowest first) and the worst must be a real
    # low-yield family (Memory or Analog-Z carry the embedded excursion/drift).
    df = r.result_table
    ycol = [c for c in df.columns if c != "product_family"][-1]
    assert list(df[ycol]) == sorted(df[ycol])  # ascending
    assert df.iloc[0]["product_family"] in {"Memory-X", "Memory-Y", "Analog-Z"}


def test_defect_pareto(env):
    r = _ask(env, "哪種缺陷最多？")
    assert r.result_table is not None
    assert "defect_type" in r.result_table.columns


def test_moves_by_step_breakdown(env):
    r = _ask(env, "各製程站的移動次數")
    assert r.result_table is not None
    assert "step_id" in r.result_table.columns
    assert len(r.result_table) == 6  # 6 process steps


def test_unique_wafers_answer(env):
    r = _ask(env, "不重複晶圓數有多少？")
    assert r.direct_answer is not None
    assert r.direct_answer.value == 100


def test_yield_forecast_proposal(env):
    r = _ask(env, "每週良率趨勢並預測未來4週")
    assert r.proposal is not None
    added = next((ch.after for ch in r.proposal.changes if ch.path.endswith("/add_visual")), None)
    assert added is not None
    assert "trend_line" in added["visual"]["visualization"]["extra"]


def test_duration_columns_not_treated_as_dates(env):
    # regression: queue_time_hr / process_time_min must NOT register as date dims
    from ai4bi.ai.schema_index import SchemaIndex
    idx = SchemaIndex.build(fab_contracts())
    d = idx.find_dim("等待時間")
    assert d is None or d.column_name != "queue_time_hr"
