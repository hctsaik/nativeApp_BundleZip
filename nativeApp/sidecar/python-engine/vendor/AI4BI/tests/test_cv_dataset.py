"""Round 186: computer-vision dataset-management scenarios — regression lock-in.

The CV demo (cv_dataset_template) exports the annotation / prediction / eval
TABLES a CV team's tooling produces. AI4BI manages those tables — it never sees
pixels. Each test asserts the analytical route + the headline signal the demo
embeds (class imbalance, version drift, annotator agreement, over-confident
errors, car↔truck confusion, size bimodality), plus the honest pixel boundary.
"""

from __future__ import annotations

import pytest

from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.analysis.executor import Executor
from ai4bi.report.cv_dataset_template import build_cv_demo_report, cv_contracts


@pytest.fixture(scope="module")
def env():
    c = cv_contracts()
    return NL2ProposalService(), build_cv_demo_report(), c, Executor(extra_contracts=c)


def _ask(env, p):
    svc, report, c, ex = env
    return svc.propose(p, report, None, contracts=c, executor=ex)


# --- dataset shape --------------------------------------------------------
def test_cv_contracts_three_blocks():
    c = cv_contracts()
    assert {"cv_annotations", "cv_predictions", "cv_eval_per_class"} <= set(c)


def test_demo_report_builds():
    rep = build_cv_demo_report()
    assert rep.pages and "main" in rep.pages


# --- S1 class imbalance ---------------------------------------------------
def test_S1_class_count_ranking(env):
    r = _ask(env, "各類別標註數由多到少")
    t = r.result_table
    assert t is not None and "class" in t.columns
    assert t.iloc[0]["class"] == "car"  # most-annotated class first


def test_S1_rarest_class_is_traffic_cone(env):
    r = _ask(env, "哪個類別樣本最少")
    t = r.result_table
    assert t is not None and t.iloc[0]["class"] == "traffic_cone"  # severe imbalance


# --- S3 per-class recall --------------------------------------------------
def test_S3_lowest_recall_classes(env):
    r = _ask(env, "哪些類別召回率最差")
    t = r.result_table
    assert t is not None
    assert set(t.iloc[:2]["class"]) == {"traffic_cone", "bicycle"}  # weakest recall


# --- S4 over-confident errors ---------------------------------------------
def test_S4_errors_are_overconfident(env):
    r = _ask(env, "答對與答錯的平均信心比較")
    t = r.result_table
    assert t is not None
    conf = {row["outcome"]: row[[c for c in t.columns if c != "outcome"][0]]
            for _, row in t.iterrows()}
    assert conf["答錯"] > conf["答對"]  # wrong predictions carry HIGHER confidence


# --- S6 annotator agreement -----------------------------------------------
def test_S6_worst_annotator_is_ann07(env):
    r = _ask(env, "哪個標註員一致性最低")
    t = r.result_table
    assert t is not None and t.iloc[0]["annotator"] == "ann_07"  # systematically low IoU


# --- S8 version label drift -----------------------------------------------
def test_S8_bicycle_drift_v1_to_v2(env):
    r = _ask(env, "各類別在不同 dataset_version 的標註數")
    t = r.result_table
    assert t is not None
    # pivot: a dataset_version column + per-class columns; bicycle surges v1→v2
    by_ver = {str(row.get("dataset_version")): row for _, row in t.iterrows()}
    assert by_ver["v2"]["bicycle"] > by_ver["v1"]["bicycle"] * 3


# --- S9 confusion ---------------------------------------------------------
def test_S9_confusion_car_truck(env):
    r = _ask(env, "最常被誤判成哪一類")
    assert r.result_table is not None
    # headline names the dominant off-diagonal confusion pair (car × truck)
    assert "car" in (r.message or "") and "truck" in (r.message or "")


# --- S10 size bimodality --------------------------------------------------
def test_S10_size_distribution(env):
    r = _ask(env, "各尺寸的標註數")
    t = r.result_table
    assert t is not None and "size_bucket" in t.columns
    assert len(t) >= 2  # multiple size buckets (bimodal)


# --- S11 honest pixel boundary --------------------------------------------
def test_S11_pixel_request_refused_with_guidance(env):
    r = _ask(env, "幫我把模糊的影像挑出來看")
    msg = r.message or ""
    assert "blur_score" in msg  # declines pixel work, points to a quantifiable column
    assert r.result_table is None
