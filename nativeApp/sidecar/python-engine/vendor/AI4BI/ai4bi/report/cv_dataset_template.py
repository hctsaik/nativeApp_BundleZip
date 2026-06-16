"""Computer-vision dataset-management demo dataset + report — Round 186.

A CV engineer can't manage *pixels* in a tabular BI tool, but they CAN manage the
**annotation / metadata / evaluation tables** their CV tooling (COCO eval, CVAT,
FiftyOne…) exports. This demo mirrors fab_template's "denormalized facts with
embedded, findable signal" design so the NL answer engine + scenarios work
without joins.

Three tables:
  cv_annotations    — one row per bounding box (the labelled dataset)
  cv_predictions    — one row per detection at eval time (model output vs GT)
  cv_eval_per_class — one row per class (already-computed precision/recall/AP)

Embedded signal the scenarios can actually find:
  * class imbalance: traffic_cone is rare (~order of magnitude fewer boxes)
  * split shift: person is over-represented in val vs train
  * version drift: bicycle boxes surge in v2 vs v1
  * annotator quality: ann_07 has systematically low IoU (agreement)
  * over-confident errors: wrong predictions still carry high confidence
  * errors concentrate on ann_07 + dataset_version v2 (commonality / Fisher)
  * confusion: car <-> truck is the dominant mix-up
  * bbox area is bimodal (a cluster of tiny objects + a cluster of large ones)
  * duplicates: a batch of repeated image_id (is_duplicate=1)
  * leakage: a few image_id appear in BOTH train and val
"""

from __future__ import annotations

import random

from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, LifecycleStatus, MetricDefinition, PolicySpec,
)
from ai4bi.query_spec import (
    BlockRef, DimensionRef, MetricRef, SortDirection, SortSpec,
    VisualizationSpec, VisualQuerySpec, VisualType,
)
from ai4bi.report.models import (
    AuditMetadata, ExecutableReportSpec, ReportPageSpec, ReportVisualSpec,
)

_ANN_ID = "cv_annotations"
_PRED_ID = "cv_predictions"
_EVAL_ID = "cv_eval_per_class"

_CACHE: dict[str, DataBlockContract] = {}

# class -> (v1 box count, v2 box count). bicycle surges in v2; traffic_cone rare.
_CLASS_COUNTS = {
    "car":          (70, 72),
    "truck":        (44, 46),
    "person":       (40, 52),
    "bicycle":      (8, 58),    # version drift: v2 surge
    "dog":          (18, 20),
    "traffic_cone": (3, 4),     # severe class imbalance
}
_ANNOTATORS = [f"ann_{i:02d}" for i in range(1, 9)]  # ann_01 .. ann_08
_LOW_IOU_ANNOTATOR = "ann_07"   # systematically poor agreement


def _size_bucket(area: int) -> str:
    """COCO-style object-size bucket (small < 32², medium < 96², else large) — the
    convention CV engineers use, so an 'area distribution' becomes a clean
    categorical breakdown that surfaces the bimodality."""
    if area < 32 * 32:
        return "小物件(<32²)"
    if area < 96 * 96:
        return "中物件(32²–96²)"
    return "大物件(≥96²)"


def _generate() -> tuple[list[dict], list[dict]]:
    rng = random.Random(7)
    anns: list[dict] = []
    preds: list[dict] = []
    img_seq = 0

    def _split_for(cls: str) -> str:
        # ~70/15/15, but person is over-represented in val (split shift),
        # and traffic_cone never lands in test (missing-class-in-split signal).
        r = rng.random()
        if cls == "person":
            return "train" if r < 0.55 else ("val" if r < 0.90 else "test")
        if cls == "traffic_cone":
            return "train" if r < 0.7 else "val"
        return "train" if r < 0.70 else ("val" if r < 0.85 else "test")

    def _area() -> tuple[int, int, int]:
        # bimodal: a cluster of tiny objects + a cluster of large ones
        if rng.random() < 0.45:
            w, h = rng.randint(12, 40), rng.randint(12, 40)      # tiny
        else:
            w, h = rng.randint(180, 460), rng.randint(160, 420)  # large
        return w, h, w * h

    for cls, (v1, v2) in _CLASS_COUNTS.items():
        for version, count in (("v1", v1), ("v2", v2)):
            for _ in range(count):
                img_seq += 1
                image_id = f"img_{img_seq:04d}"
                split = _split_for(cls)
                annotator = rng.choice(_ANNOTATORS)
                w, h, area = _area()
                # IoU (annotation agreement): most ~0.85-0.97, ann_07 ~0.55-0.75
                if annotator == _LOW_IOU_ANNOTATOR:
                    iou = round(rng.uniform(0.50, 0.74), 3)
                else:
                    iou = round(rng.uniform(0.84, 0.98), 3)
                bbox_id = f"bb_{img_seq:04d}_1"
                anns.append({
                    "image_id": image_id, "bbox_id": bbox_id, "class": cls,
                    "split": split, "dataset_version": version, "annotator": annotator,
                    "bbox_w": w, "bbox_h": h, "area": area,
                    "size_bucket": _size_bucket(area),
                    "img_width": 1280, "img_height": 720,
                    "is_duplicate": 0, "iou": iou, "n": 1,
                })
                # one prediction per box (model output vs GT)
                _make_prediction(rng, preds, image_id, cls, version, split, annotator)

    # ── duplicates: clone a batch of rows with is_duplicate=1 (same image_id) ──
    for src in anns[:14]:
        d = dict(src)
        d["bbox_id"] = src["bbox_id"].replace("_1", "_dup")
        d["is_duplicate"] = 1
        anns.append(d)

    # ── leakage: force a few train images to ALSO appear in val (same image_id) ─
    leaks = [a for a in anns if a["split"] == "train" and a["is_duplicate"] == 0][:6]
    for a in leaks:
        leaked = dict(a)
        leaked["split"] = "val"
        leaked["bbox_id"] = a["bbox_id"].replace("_1", "_leak")
        anns.append(leaked)

    return anns, preds


def _make_prediction(rng, preds, image_id, true_cls, version, split, annotator) -> None:
    # base error rate ~12%; errors concentrate on ann_07 and v2 (commonality),
    # and are OVER-confident (high confidence despite being wrong).
    err_p = 0.12
    if annotator == _LOW_IOU_ANNOTATOR:
        err_p += 0.30
    if version == "v2":
        err_p += 0.10
    is_error = rng.random() < err_p
    if is_error:
        # dominant confusion: car <-> truck; otherwise a random other class
        if true_cls == "car":
            pred_cls = "truck"
        elif true_cls == "truck":
            pred_cls = "car"
        else:
            pred_cls = rng.choice([c for c in _CLASS_COUNTS if c != true_cls])
        confidence = round(rng.uniform(0.80, 0.97), 3)   # over-confident error
        iou_pred = round(rng.uniform(0.20, 0.45), 3)
        is_correct = 0
    else:
        pred_cls = true_cls
        confidence = round(rng.uniform(0.55, 0.99), 3)
        iou_pred = round(rng.uniform(0.62, 0.95), 3)
        is_correct = 1
    preds.append({
        "image_id": image_id, "true_class": true_cls, "pred_class": pred_cls,
        "confidence": confidence, "is_correct": is_correct, "is_error": 1 - is_correct,
        # a STRING outcome label so the generic breakdown/ranking/compare handlers
        # can split by 答對/答錯 (the 0/1 ints aren't treated as a categorical axis).
        "outcome": "答對" if is_correct else "答錯",
        "iou_pred": iou_pred, "annotator": annotator, "split": split,
        "dataset_version": version, "n": 1,
    })


def build_annotations_block() -> DataBlockContract:
    if _ANN_ID in _CACHE:
        return _CACHE[_ANN_ID]
    anns, _ = _generate()
    block = DataBlockContract(
        block_id=_ANN_ID, block_type=BlockType.fact,
        grain="one row per bounding-box annotation",
        version="1.0.0", description="影像標註（每個框一列）",
        block_lifecycle=LifecycleStatus.draft, primary_keys=[],
        columns=[
            ColumnSchema(name="image_id", data_type="string", description="影像 圖片"),
            ColumnSchema(name="bbox_id", data_type="string"),  # row identifier — not a grouping axis
            ColumnSchema(name="class", data_type="string", description="類別 種類"),
            ColumnSchema(name="split", data_type="string", description="資料集切分 切分 train val test"),
            ColumnSchema(name="dataset_version", data_type="string", description="資料集版本 版本"),
            ColumnSchema(name="annotator", data_type="string", description="標註員 標記員 標註者"),
            ColumnSchema(name="bbox_w", data_type="integer"),
            ColumnSchema(name="bbox_h", data_type="integer"),
            ColumnSchema(name="area", data_type="integer", description="框面積 大小"),
            ColumnSchema(name="size_bucket", data_type="string",
                         description="尺寸 大小 size 物件大小 框大小 面積 框面積 面積分布 面積區間 尺寸分布 大中小"),
            ColumnSchema(name="img_width", data_type="integer"),
            ColumnSchema(name="img_height", data_type="integer"),
            ColumnSchema(name="is_duplicate", data_type="integer", description="重複 重覆"),
            ColumnSchema(name="iou", data_type="float", description="標註一致性 重疊度"),
            ColumnSchema(name="n", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="bbox_count", formula="SUM(n)",
                             disaggregation_method=DisaggregationMethod.none,
                             description="標註框數 標註數量 標註數 框數 標註量 物件數 樣本 樣本數 資料量 幾個框 標了幾個"),
            MetricDefinition(name="unique_images", formula="COUNT(DISTINCT image_id)",
                             disaggregation_method=DisaggregationMethod.none, description="不重複影像數"),
            MetricDefinition(name="avg_iou", formula="AVG(iou)",
                             disaggregation_method=DisaggregationMethod.none,
                             description="平均標註一致性(IoU)"),
            MetricDefinition(name="avg_area", formula="AVG(area)",
                             disaggregation_method=DisaggregationMethod.none, description="平均框面積"),
            MetricDefinition(name="dup_rate", formula="SUM(is_duplicate) / NULLIF(SUM(n),0) * 100",
                             disaggregation_method=DisaggregationMethod.none, unit="%",
                             description="重複率(重複框÷總框)"),
        ],
        data_source=InlineDataSource(records=anns),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHE[_ANN_ID] = block
    return block


def build_predictions_block() -> DataBlockContract:
    if _PRED_ID in _CACHE:
        return _CACHE[_PRED_ID]
    _, preds = _generate()
    block = DataBlockContract(
        block_id=_PRED_ID, block_type=BlockType.fact,
        grain="one row per detection at evaluation",
        version="1.0.0", description="模型預測 vs 真實標註（每個偵測一列）",
        block_lifecycle=LifecycleStatus.draft, primary_keys=[],
        columns=[
            ColumnSchema(name="image_id", data_type="string", description="影像 圖片"),
            ColumnSchema(name="true_class", data_type="string", description="真實類別 正解類別"),
            ColumnSchema(name="pred_class", data_type="string", description="預測類別 誤判類別"),
            ColumnSchema(name="confidence", data_type="float", description="信心 信賴度 置信度"),
            ColumnSchema(name="is_correct", data_type="integer", description="是否正確 答對"),
            ColumnSchema(name="is_error", data_type="integer", description="是否錯誤 答錯 誤判"),
            ColumnSchema(name="outcome", data_type="string", description="結果 對錯 答對 答錯 正確 錯誤"),
            ColumnSchema(name="iou_pred", data_type="float", description="預測重疊度"),
            ColumnSchema(name="annotator", data_type="string", description="標註員 標記員"),
            ColumnSchema(name="split", data_type="string", description="資料集切分 切分 train val test"),
            ColumnSchema(name="dataset_version", data_type="string", description="資料集版本 版本"),
            ColumnSchema(name="n", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="pred_count", formula="SUM(n)",
                             disaggregation_method=DisaggregationMethod.none,
                             description="預測數 偵測數 預測數量 偵測數量 樣本數 幾個預測"),
            MetricDefinition(name="accuracy", formula="SUM(is_correct) / NULLIF(SUM(n),0) * 100",
                             disaggregation_method=DisaggregationMethod.none, unit="%",
                             description="正確率(答對÷總數)"),
            MetricDefinition(name="error_count", formula="SUM(is_error)",
                             disaggregation_method=DisaggregationMethod.none, description="錯誤數"),
            MetricDefinition(name="avg_confidence", formula="AVG(confidence)",
                             disaggregation_method=DisaggregationMethod.none, description="平均信心"),
            MetricDefinition(name="avg_iou_pred", formula="AVG(iou_pred)",
                             disaggregation_method=DisaggregationMethod.none,
                             description="平均預測IoU"),
        ],
        data_source=InlineDataSource(records=preds),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHE[_PRED_ID] = block
    return block


def build_eval_per_class_block() -> DataBlockContract:
    """One row per class with ALREADY-COMPUTED metrics (AI4BI aggregates, does not
    re-compute mAP/IoU from images). bicycle + traffic_cone have low recall."""
    if _EVAL_ID in _CACHE:
        return _CACHE[_EVAL_ID]
    # gt_count, tp, fp, fn → precision/recall/ap. Low recall on rare/drifted classes.
    rows_raw = [
        # class,        gt,  tp,  fp,  fn
        ("car",         142, 120, 14, 22),
        ("truck",        90,  74, 18, 16),
        ("person",       92,  80,  9, 12),
        ("bicycle",      66,  34,  8, 32),   # low recall (0.52) — drifted/new
        ("dog",          38,  33,  4,  5),
        ("traffic_cone",  7,   3,  1,  4),   # low recall (0.43) — rare class
    ]
    rows = []
    for cls, gt, tp, fp, fn in rows_raw:
        precision = round(tp / (tp + fp), 3) if (tp + fp) else 0.0
        recall = round(tp / (tp + fn), 3) if (tp + fn) else 0.0
        ap = round(max(0.0, precision * recall * rng_ap(cls)), 3)
        rows.append({
            "class": cls, "gt_count": gt, "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "ap": ap,
        })
    block = DataBlockContract(
        block_id=_EVAL_ID, block_type=BlockType.fact,
        grain="one row per class (computed eval metrics)",
        version="1.0.0", description="每類別評估指標（已算好的 precision/recall/AP）",
        block_lifecycle=LifecycleStatus.draft, primary_keys=["class"],
        columns=[
            ColumnSchema(name="class", data_type="string", description="類別 種類"),
            ColumnSchema(name="gt_count", data_type="integer", description="真實框數"),
            ColumnSchema(name="tp", data_type="integer"),
            ColumnSchema(name="fp", data_type="integer"),
            ColumnSchema(name="fn", data_type="integer"),
            ColumnSchema(name="precision", data_type="float", description="精確率 精準率 查準率"),
            ColumnSchema(name="recall", data_type="float", description="召回率 查全率"),
            ColumnSchema(name="ap", data_type="float", description="平均精度 AP"),
        ],
        metrics=[
            MetricDefinition(name="gt_count", formula="SUM(gt_count)",
                             disaggregation_method=DisaggregationMethod.sum, description="真實框數"),
            MetricDefinition(name="precision", formula="AVG(precision)",
                             disaggregation_method=DisaggregationMethod.none, description="精確率 精準率 查準率"),
            MetricDefinition(name="recall", formula="AVG(recall)",
                             disaggregation_method=DisaggregationMethod.none, description="召回率 查全率"),
            MetricDefinition(name="ap", formula="AVG(ap)",
                             disaggregation_method=DisaggregationMethod.none, description="平均精度 AP mAP"),
        ],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHE[_EVAL_ID] = block
    return block


def rng_ap(cls: str) -> float:
    # deterministic small spread so AP isn't a trivial product
    return {"car": 0.95, "truck": 0.9, "person": 0.96, "bicycle": 0.8,
            "dog": 0.93, "traffic_cone": 0.7}.get(cls, 0.9)


def cv_contracts() -> dict[str, DataBlockContract]:
    return {_ANN_ID: build_annotations_block(),
            _PRED_ID: build_predictions_block(),
            _EVAL_ID: build_eval_per_class_block()}


def build_cv_demo_report() -> ExecutableReportSpec:
    """A starter CV dataset-health dashboard (class balance, IoU, recall, confidence)."""
    a, e, p = BlockRef(_ANN_ID), BlockRef(_EVAL_ID), BlockRef(_PRED_ID)

    def _v(vid, block, metrics, vt, title, dims=None, sort=None, extra=None):
        q = VisualQuerySpec(spec_id=vid, block_refs=[block], metrics=metrics,
                            dimensions=dims or [], sort=sort or [], inherit_global_filter=True)
        return ReportVisualSpec(vid, q, VisualizationSpec(vt, title=title, extra=extra or {}))

    kpi_boxes = _v("kpi_boxes", a, [MetricRef(_ANN_ID, "bbox_count", "標註框數")],
                   VisualType.kpi_card, "標註框總數")
    kpi_imgs = _v("kpi_imgs", a, [MetricRef(_ANN_ID, "unique_images", "影像數")],
                  VisualType.kpi_card, "不重複影像數")
    bar_class = _v("bar_class", a, [MetricRef(_ANN_ID, "bbox_count", "標註框數")],
                   VisualType.bar_chart, "各類別標註數（看不平衡）",
                   dims=[DimensionRef(_ANN_ID, "class", "類別")],
                   sort=[SortSpec("標註框數", SortDirection.desc)])
    bar_recall = _v("bar_recall", e, [MetricRef(_EVAL_ID, "recall", "召回率")],
                    VisualType.bar_chart, "各類別召回率（看模型弱項）",
                    dims=[DimensionRef(_EVAL_ID, "class", "類別")],
                    sort=[SortSpec("召回率", SortDirection.asc)])
    bar_iou = _v("bar_iou", a, [MetricRef(_ANN_ID, "avg_iou", "平均IoU")],
                 VisualType.bar_chart, "各標註員一致性（IoU）",
                 dims=[DimensionRef(_ANN_ID, "annotator", "標註員")],
                 sort=[SortSpec("平均IoU", SortDirection.asc)])

    visuals = {v.component_id: v for v in [kpi_boxes, kpi_imgs, bar_class, bar_recall, bar_iou]}
    page = ReportPageSpec(page_id="main", title="CV 資料集健檢儀表板",
                          visuals=visuals, visual_order=list(visuals.keys()),
                          display_name="CV Dataset")
    return ExecutableReportSpec(
        audit=AuditMetadata(report_id="cv_dataset_demo_v1", revision=1),
        title="CV 資料集健檢儀表板", semantic_model_ref="cv_dataset_demo",
        status="validated_demo_draft", pages={"main": page}, controls={})
