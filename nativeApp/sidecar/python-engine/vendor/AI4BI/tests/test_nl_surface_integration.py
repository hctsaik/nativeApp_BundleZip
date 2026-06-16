"""Round 092: end-to-end integration guard for the NL answer surface.

Runs representative prompts through the full prompt_to_proposal path on the
retail demo with a real executor, asserting each routes to the right kind of
outcome. Locks in the R078-R091 conversational capabilities against regression.
"""

from __future__ import annotations

import pytest

from ai4bi.analysis.executor import Executor
from ai4bi.report.proposals import prompt_to_proposal
from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block


@pytest.fixture
def env():
    report = build_retail_demo_report()
    contracts = {"retail_sales": build_retail_sales_block()}
    executor = Executor(extra_contracts=contracts)
    return report, contracts, executor


def _ask(env, prompt, selected=None):
    report, contracts, executor = env
    return prompt_to_proposal(prompt, report, selected, semantic_model={},
                              contracts=contracts, executor=executor)


def test_direct_answer_number(env):
    res = _ask(env, "總共營收多少？")
    assert res.intent_kind == "answer"
    assert res.direct_answer is not None
    assert res.direct_answer.value is not None


def test_ranking_returns_table(env):
    res = _ask(env, "營收最高的 3 個地區")
    assert res.result_table is not None
    assert len(res.result_table) == 3


def test_grouped_topn_returns_table(env):
    res = _ask(env, "每個地區營收最高的 2 個商品")
    assert res.result_table is not None
    assert (res.result_table.groupby("city").size() <= 2).all()


def test_decomposition_answer(env):
    res = _ask(env, "為什麼營收變化 依地區拆解")
    assert res.direct_answer is not None
    assert "拆解" in res.direct_answer.sentence


def test_churn_routes_to_rfm_table(env):
    res = _ask(env, "哪些客戶快流失")
    assert res.result_table is not None
    assert "流失風險" in res.result_table.columns


def test_measure_filter_on_visual(env):
    res = _ask(env, "營收超過 100000 的地區", selected="bar_revenue_by_store")
    assert res.proposal is not None
    assert any("/query/having" in c.path for c in res.proposal.changes)


def test_set_target_proposal(env):
    res = _ask(env, "把訂單數目標設為 5000", selected="kpi_orders")
    assert res.proposal is not None
    assert any(c.path.endswith("/extra/target") for c in res.proposal.changes)


def test_add_map_visual(env):
    res = _ask(env, "加一張地圖")
    assert res.proposal is not None
    added = next((c.after for c in res.proposal.changes if c.path.endswith("/add_visual")), None)
    assert added is not None
    assert added["visual"]["visualization"]["visual_type"] == "map"


def test_plain_edit_still_works(env):
    # a non-question imperative must still edit, not become an answer
    res = _ask(env, "加一張長條圖")
    assert res.proposal is not None
    assert res.direct_answer is None
    assert res.result_table is None


def test_unsupported_is_graceful(env):
    res = _ask(env, "幫我訂便當")
    # no crash; returns a (non-answer) result
    assert res.direct_answer is None
    assert res.result_table is None
