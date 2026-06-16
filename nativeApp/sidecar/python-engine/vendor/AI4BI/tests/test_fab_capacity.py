"""Phase 3 move / capacity / OEE scenarios — regression lock-in.

Three themed rounds the multi-agent loop drove to >95 (R128):
  A = move / WIP, B = capacity / utilization / loading, C = OEE.
Each asserts the analytical method + the headline signal the fab dataset embeds
(ETCH-02 bottleneck/excursion, CVD idle headroom, THINFILM low plan attainment).
"""

from __future__ import annotations

import pytest

from ai4bi.analysis.capacity import compute_oee, plan_attainment, throughput_rate, utilization
from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


@pytest.fixture(scope="module")
def env():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def _ask(env, p):
    svc, report, c, ex = env
    return svc.propose(p, report, None, contracts=c, executor=ex)


# --- capacity analytics module (direct) ----------------------------------
def test_capacity_block_present():
    c = fab_contracts()
    assert "fab_tool_capacity" in c


def test_utilization_etch02_is_bottleneck():
    u = utilization(fab_contracts(), "tool_id")
    assert not u.empty and u.iloc[0]["tool_id"] == "ETCH-02"  # highest util first
    assert u.iloc[0]["利用率%"] >= 90


def test_plan_attainment_worst_area():
    p = plan_attainment(fab_contracts(), "area")
    assert not p.empty and "達成率%" in p.columns  # ascending: worst first


def test_throughput_has_rate_column():
    t = throughput_rate(fab_contracts(), "tool_id")
    assert not t.empty and "moves_per_hr" in t.columns


def test_oee_etch02_worst_dragged_by_availability():
    o = compute_oee(fab_contracts())
    assert not o.empty and o.iloc[0]["tool_id"] == "ETCH-02"  # worst OEE first
    row = o.iloc[0]
    assert row["可用率A"] == min(row["可用率A"], row["表現P"], row["良率Q"])  # A drags


# --- Round A: move / WIP --------------------------------------------------
def test_A1_tool_move_ranking(env):
    r = _ask(env, "每台機台的移動次數，哪一台最高？")
    assert r.result_table is not None and "tool_id" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_A3_step_queue_ranking(env):
    r = _ask(env, "各製程站的平均等待時間排名")
    assert r.result_table is not None and "step_id" in r.result_table.columns


def test_A6_product_move_share(env):
    r = _ask(env, "各產品別的移動次數佔總比")
    assert r.result_table is not None
    assert any("佔總" in c or "佔總比%" in c for c in r.result_table.columns)


def test_A10_etch02_anomaly_spc(env):
    r = _ask(env, "ETCH-02 的移動量與等待時間異常嗎？")
    assert r.result_table is not None  # SPC outlier table


# --- Round B: capacity / utilization -------------------------------------
def test_B1_utilization_ranking(env):
    r = _ask(env, "各機台的產能利用率排名")
    assert r.result_table is not None and "利用率%" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_B2_headroom(env):
    r = _ask(env, "哪些機台還有產能餘裕、可以多接單？")
    assert r.result_table is not None and "餘裕" in r.result_table.columns
    assert "CVD" in str(r.result_table.iloc[0]["tool_id"])  # idle CVD has most headroom


def test_B4_plan_attainment_worst_area(env):
    r = _ask(env, "計畫達成率最差的區是哪一區？")
    assert r.result_table is not None and "達成率%" in r.result_table.columns


def test_B5_bottleneck_is_max_util(env):
    r = _ask(env, "整條線的瓶頸在哪？哪台機台利用率最高、餘裕最少？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"  # NOT headroom-sorted


def test_B6_cvd_family_filter(env):
    r = _ask(env, "CVD 機台的利用率是不是偏低？")
    assert r.result_table is not None
    assert all(str(t).startswith("CVD-") for t in r.result_table["tool_id"])


def test_B7_etch_area_headroom(env):
    r = _ask(env, "ETCH 區的產能餘裕還有多少？")
    assert r.result_table is not None
    assert set(r.result_table["area"]) == {"ETCH"}


def test_B9_lowest_availability(env):
    r = _ask(env, "可用率最低（停機最多）的機台是哪一台？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_B10_utilization_by_vendor(env):
    r = _ask(env, "各 vendor 機台群的平均利用率")
    assert r.result_table is not None and "vendor" in r.result_table.columns


# --- Round C: OEE ---------------------------------------------------------
def test_C1_oee_ranking_worst(env):
    r = _ask(env, "各機台的 OEE 排名，最低的是哪一台？")
    assert r.result_table is not None and "OEE" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_C2_oee_drag_factor_is_availability(env):
    r = _ask(env, "ETCH-02 的 OEE 為什麼這麼低？是可用率、表現還是良率拖累？")
    assert r.result_table is not None
    assert "可用率" in r.message  # names availability as the actual drag, not 表現


def test_C3_fab_average_oee(env):
    r = _ask(env, "全廠平均 OEE 大概多少？")
    assert r.result_table is not None and "範圍" in r.result_table.columns


def test_C4_oee_by_vendor(env):
    r = _ask(env, "各 vendor 機台群的 OEE 對比")
    assert r.result_table is not None and "vendor" in r.result_table.columns


def test_C8_oee_by_area(env):
    r = _ask(env, "各區（area）的 OEE 平均")
    assert r.result_table is not None and "area" in r.result_table.columns


def test_C9_oee_below_threshold(env):
    r = _ask(env, "OEE 低於 60% 的機台有哪些？")
    assert r.result_table is not None
    assert all(v < 60 for v in r.result_table["OEE"])


def test_C10_which_tool_to_fix_first(env):
    r = _ask(env, "如果要提升整廠 OEE，最該先處理哪一台？")
    assert r.result_table is not None and "tool_id" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"  # worst, not fab-average


# --- Round D: WIP / queue dynamics (R129) --------------------------------
def test_D2_wip_move_by_step(env):
    r = _ask(env, "各製程站的在製品（WIP）移動量分布")
    assert r.result_table is not None and "step_id" in r.result_table.columns


def test_D3_priority_compare(env):
    r = _ask(env, "Hot（高優先）lot 的等待時間有比一般 lot 短嗎？")
    assert r.result_table is not None and "priority" in r.result_table.columns
    assert set(r.result_table["priority"]) >= {"Hot", "Normal"}  # 2-group compare


def test_D4_queue_share_by_step(env):
    r = _ask(env, "等待時間最長的前五站，各佔總等待多少比重？")
    assert r.result_table is not None
    assert "佔總比%" in r.result_table.columns  # share, not a Top-N cut
    assert r.result_table.iloc[0]["step_id"] == "ETCH"


def test_D5_etch_queue_share(env):
    r = _ask(env, "瓶頸站 ETCH 的等待時間佔全廠等待的多少？")
    assert r.result_table is not None and "佔總比%" in r.result_table.columns
    assert r.result_table.iloc[0]["step_id"] == "ETCH"  # ETCH dominates total wait


def test_D7_cycle_vs_move_degenerate(env):
    # move_count per lot is uniform → correlation undefined; must say so honestly,
    # aligning cycle (yield) and move (move) cross-fact, not silently fall through.
    r = _ask(env, "cycle time 跟移動次數有沒有相關性？")
    assert r.result_table is not None
    assert "move_count" in r.result_table.columns and "cycle_time_hr" in r.result_table.columns


def test_D9_rework_compare(env):
    r = _ask(env, "重工 vs 非重工的移動量差異")
    assert r.result_table is not None and "rework_flag" in r.result_table.columns
    assert len(r.result_table) == 2  # rework vs non-rework


def test_D10_hold_age_hours_threshold(env):
    r = _ask(env, "卡關超過 4 小時的 lot 有哪些？")
    assert r.result_table is not None and "lot_id" in r.result_table.columns
    # hour-unit measure, not a count: every qualifying lot exceeds 4 hours
    hrcol = next(c for c in r.result_table.columns if "Hold Age" in c or "hold_age" in c.lower())
    assert all(v > 4 for v in r.result_table[hrcol])


def test_D_same_fact_cohort(env):
    r = _ask(env, "cycle time 最久的前 20% 批號的良率掉多少？")
    assert r.result_table is not None
    assert any("平均" in c for c in r.result_table.columns)  # cohort outcome column


# --- Round E: capacity planning / what-if (R130) -------------------------
def test_E1_capacity_shortfall(env):
    r = _ask(env, "要達成計畫，哪一區的產能缺口最大？")
    assert r.result_table is not None and "缺口" in r.result_table.columns
    assert r.result_table.iloc[0]["area"] == "THINFILM"  # biggest plan shortfall


def test_E2_expansion_routes(env):
    # Round 184 (S13): expansion follows constraint theory — add capacity at the
    # BOTTLENECK (highest utilization = ETCH), not wherever the plan gap is biggest
    # (an under-utilised station isn't a capacity problem).
    r = _ask(env, "如果要擴產，最該先加哪一區的機台？")
    assert r.result_table is not None and "利用率%" in r.result_table.columns
    assert r.result_table.iloc[0]["area"] == "ETCH"


def test_E3_whatif_uptime_uplift(env):
    r = _ask(env, "ETCH-02 的稼動率若從 70% 提升到 85%，產能可多多少？")
    assert r.result_table is not None and "增量 moves" in r.result_table.columns
    assert r.result_table.iloc[0]["增量 moves"] > 0


def test_E5_line_balance_bottleneck(env):
    r = _ask(env, "各區的產能是否平衡？哪一區拖累整線？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["area"] == "ETCH"  # 拖累 = highest util, not headroom


def test_E7_whatif_tool_failure(env):
    r = _ask(env, "若 ETCH-02 故障，產能會掉多少？")
    assert r.result_table is not None and "損失 moves" in r.result_table.columns


def test_E8_gap_to_target_loading(env):
    r = _ask(env, "各機台距離滿載（90%）還差多少 move？")
    assert r.result_table is not None
    assert any("90%" in c for c in r.result_table.columns)  # gap-to-target column


def test_E9_overall_utilization(env):
    r = _ask(env, "全廠整體產能利用率是多少？")
    assert r.result_table is not None and len(r.result_table) == 1
    assert r.result_table.iloc[0]["範圍"] == "全廠"


def test_E10_overall_plan_attainment(env):
    r = _ask(env, "計畫 vs 實際的總體達成率？")
    assert r.result_table is not None and "達成率%" in r.result_table.columns
    assert len(r.result_table) == 1


# --- Round F: OEE losses (R131) ------------------------------------------
def test_F1_loss_decomposition(env):
    r = _ask(env, "OEE 的三大損失（可用率、表現、良率）各損失多少百分點？")
    assert r.result_table is not None and "損失百分點" in r.result_table.columns
    assert len(r.result_table) == 3
    # Round 178: ETCH-02 is now a strong yield detractor, so 良率(Q) loss rivals/
    # leads 可用率(A) — the two dominant fab-wide OEE losses. Table is sorted
    # worst-first; assert the top loss is one of those two (not 表現P) and the
    # losses are in descending order.
    factors = list(r.result_table["因子"])
    losses = list(r.result_table["損失百分點"])
    assert factors[0].startswith(("可用率", "良率"))
    assert losses == sorted(losses, reverse=True)


def test_F3_performance_loss_tool(env):
    r = _ask(env, "表現損失（速度/小停機）最大的機台？")
    assert r.result_table is not None and "表現P" in r.result_table.columns
    assert "表現" in r.message  # routed to OEE P, not the plain availability table


def test_F4_quality_loss_tool(env):
    r = _ask(env, "良率損失（重工/報廢）最大的機台？")
    assert r.result_table is not None and "良率Q" in r.result_table.columns
    assert "良率" in r.message


def test_F6_loss_pareto(env):
    r = _ask(env, "OEE 損失的 Pareto，最該優先改善哪一項？")
    assert r.result_table is not None and "損失百分點" in r.result_table.columns


def test_F8_availability_drag_worst(env):
    r = _ask(env, "哪一台機台的可用率拖累最嚴重？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"  # lowest A, not highest


def test_F9_oee_uplift_whatif(env):
    r = _ask(env, "若把 ETCH-02 的 OEE 拉到全廠平均，產能可多多少？")
    assert r.result_table is not None and "增量 moves" in r.result_table.columns
    assert r.result_table.iloc[0]["增量 moves"] > 0
