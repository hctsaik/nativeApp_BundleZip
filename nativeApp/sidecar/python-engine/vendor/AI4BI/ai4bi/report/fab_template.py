"""Semiconductor wafer-fab demo dataset + report — Round 112.

A richer, denormalized fab dataset (so the single-GROUP-BY executor + the NL
answer engine work without joins), with realistic embedded signal that
scenarios can actually find:

  * ETCH-02 is a bottleneck (high queue time) AND a yield detractor (commonality)
  * IMPLANT has occasional rework; a few lots go on HOLD
  * Memory products yield lower than Logic; yield trends slightly up over time

Two facts:
  process_move_fact  — one row per wafer per process step (WIP / move events)
  wafer_yield_fact   — one row per wafer at final test (electrical yield)

Mirrors retail_template's structure so the app can switch demos.
"""

from __future__ import annotations

import datetime as _dt
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

_MOVE_ID = "fab_process_move"
_YIELD_ID = "fab_wafer_yield"

# step_id, step_name, sequence, tool_group, base_queue_hr, base_proc_min
_STEPS = [
    ("PHOTO",   "Lithography",  10, "PHOTO",   2.0, 45),
    ("ETCH",    "Etch",         20, "ETCH",    3.5, 60),
    ("CVD",     "Deposition",   30, "CVD",     1.5, 50),
    ("IMPLANT", "Ion Implant",  40, "IMPLANT", 2.5, 35),
    ("CMP",     "Planarization",50, "CMP",     1.2, 30),
    ("METAL",   "Metallization",60, "METAL",   1.8, 55),
]
# tool_group -> list of (tool_id, vendor, reliability_factor, yield_factor)
_TOOLS = {
    "PHOTO":   [("PHOTO-01", "ASML",   1.0, 1.00), ("PHOTO-02", "Nikon",  1.05, 0.998)],
    # Round 178: ETCH-02 yield_factor lowered 0.96→0.86 so the tool-matching gap
    # vs ETCH-01 is a clear, realistic ~12pp (was diluted to <1pp). Still keeps
    # the excursion lots (0.72) as the <80% commonality signal on ETCH-02.
    "ETCH":    [("ETCH-01",  "LAM",    1.0, 1.00), ("ETCH-02",  "TEL",    1.9, 0.86)],   # bottleneck + low yield
    "CVD":     [("CVD-01",   "AMAT",   1.0, 1.00), ("CVD-02",   "AMAT",   1.0, 1.00)],
    "IMPLANT": [("IMP-01",   "AMAT",   1.0, 1.00), ("IMP-02",   "AIBT",   1.1, 0.99)],
    "CMP":     [("CMP-01",   "Ebara",  1.0, 1.00), ("CMP-02",   "AMAT",   1.0, 1.00)],
    "METAL":   [("METAL-01", "AMAT",   1.0, 1.00), ("METAL-02", "AMAT",   1.0, 1.00)],
}
_PRODUCTS = [
    ("Logic-A", "R28A", 1.00),
    ("Logic-B", "R28B", 0.995),
    ("Memory-X", "RMX", 0.97),
    ("Memory-Y", "RMY", 0.965),
    ("Analog-Z", "RAZ", 0.99),
]
_DEFECTS = ["Particle", "Scratch", "Pattern", "Contamination", "Edge"]

_AREA = {"PHOTO": "LITHO", "ETCH": "ETCH", "CVD": "THINFILM",
         "IMPLANT": "IMPLANT", "CMP": "CMP", "METAL": "THINFILM"}

_CACHE: dict[str, DataBlockContract] = {}


def _generate():
    rng = random.Random(7)
    d0 = _dt.date(2026, 3, 2)
    moves: list[dict] = []
    yields: list[dict] = []
    mid = yid = 0
    lot_num = 1000

    # ~20 lots, 5 wafers each, started across ~9 weeks.
    for li in range(20):
        lot_num += 1
        lot_id = f"LOT-{lot_num}"
        prod, route, prod_yf = _PRODUCTS[li % len(_PRODUCTS)]
        priority = "Hot" if li % 7 == 0 else "Normal"
        start = d0 + _dt.timedelta(days=li * 3)
        on_hold = 1 if li % 9 == 4 else 0
        hold_reason = rng.choice(["等待工程確認", "設備異常", "缺料", "待品質判定"]) if on_hold else ""
        hold_age = round(rng.uniform(8, 96), 1) if on_hold else 0.0  # Round 122: hold aging hr
        # Two lots have a real yield excursion (~72%), both routed through ETCH-02
        # — embeds a commonality signal (failing lots share a tool).
        excursion = li in (4, 13)
        for wno in range(1, 6):
            wafer_id = f"W{lot_num}-{wno:02d}"
            cur = start
            etch_tool_used = None
            wafer_had_rework = 0  # Round 122: track for first-pass yield
            for (step_id, step_name, seq, tg, bq, bp) in _STEPS:
                tools = _TOOLS[tg]
                tool_id, vendor, rel, tyf = tools[(li + wno) % len(tools)]
                if step_id == "ETCH":
                    if excursion:  # force the excursion lots through ETCH-02
                        tool_id, vendor, rel, tyf = _TOOLS["ETCH"][1]
                    etch_tool_used = tool_id
                # Day-heavy staffing (~2:1) and a night-shift queue penalty —
                # so Day vs Night comparisons reveal a real difference. (Round 126)
                shift = "Day" if (mid % 3 != 0) else "Night"
                night_pen = 1.18 if shift == "Night" else 1.0
                # queue time scales with the tool's reliability factor + noise
                qt = round(bq * rel * night_pen * rng.uniform(0.8, 1.3), 2)
                pt = round(bp * rng.uniform(0.9, 1.1), 1)
                rework = 1 if (step_id == "IMPLANT" and rng.random() < 0.12) else 0
                if rework:
                    wafer_had_rework = 1
                cur = cur + _dt.timedelta(days=rng.choice([1, 1, 2]))
                mid += 1
                moves.append({
                    "move_id": f"M{mid:05d}",
                    "event_date": cur.isoformat(),
                    "week": cur.isocalendar()[1],
                    "shift": shift,
                    "lot_id": lot_id,
                    "product_family": prod,
                    "route_id": route,
                    "priority": priority,
                    "wafer_id": wafer_id,
                    "step_id": step_id,
                    "step_name": step_name,
                    "tool_id": tool_id,
                    "tool_group": tg,
                    "area": _AREA[tg],
                    "vendor": vendor,
                    "queue_time_hr": qt,
                    "process_time_min": pt,
                    "move_count": 1,
                    "rework_flag": rework,
                    "hold_flag": on_hold if step_id == "IMPLANT" else 0,
                    "hold_age_hr": hold_age if (on_hold and step_id == "IMPLANT") else 0.0,
                    "hold_reason": hold_reason if (on_hold and step_id == "IMPLANT") else "",
                })
            # final yield per wafer — driven by product, the ETCH tool used, time trend
            test_date = cur + _dt.timedelta(days=2)
            # cycle time = lot dwell; held lots carry their hold time, so some
            # lots clearly exceed a 300hr SLA (Round 126).
            cycle_time_hr = round((test_date - start).days * 24
                                  + (hold_age if on_hold else 0.0)
                                  + rng.uniform(-12, 40), 1)
            tyf = next(t[3] for t in _TOOLS["ETCH"] if t[0] == etch_tool_used)
            trend = 1.0 + (li / 200.0)  # slight improvement over time
            base = 0.985 * prod_yf * tyf * trend
            # ETCH-01 chamber drift: a clean week-over-week yield decline so
            # '哪台機台良率逐週退化' surfaces a real declining tool. (ETCH-01 has
            # no excursion, so the trend is clean; ETCH-02 stays the commonality
            # / lowest-yield tool via its excursion.)
            if etch_tool_used == "ETCH-01" and not excursion:
                week_rank = max((test_date - d0).days // 7, 0)
                base = 0.99 - week_rank * 0.011
            if wafer_had_rework:
                base *= 0.95  # reworked wafers finish at lower yield (first-pass gap)
            if excursion:
                base = 0.72  # contamination excursion
            base = min(base, 0.999)
            tested = 1000
            good = int(round(tested * base * rng.uniform(0.99, 1.005)))
            good = min(good, tested)
            defect = tested - good
            yid += 1
            yields.append({
                "yield_event_id": f"Y{yid:05d}",
                "test_date": test_date.isoformat(),
                "week": test_date.isocalendar()[1],
                "lot_id": lot_id,
                "product_family": prod,
                "priority": priority,
                "wafer_id": wafer_id,
                "etch_tool_id": etch_tool_used,
                "cycle_time_hr": cycle_time_hr,
                "rework_status": "有返工" if wafer_had_rework else "無返工",
                "tested_die": tested,
                "good_die": good,
                "defect_die": defect,
                "yield_pct": round(good / tested * 100, 2),
                "defect_type": _DEFECTS[(yid + li) % len(_DEFECTS)],
                "bin_code": f"BIN{(yid % 4) + 1}",
                "failed_wafer_count": 1 if good / tested < 0.95 else 0,
            })
    return moves, yields


def build_process_move_block() -> DataBlockContract:
    if _MOVE_ID in _CACHE:
        return _CACHE[_MOVE_ID]
    moves, _ = _generate()
    block = DataBlockContract(
        block_id=_MOVE_ID, block_type=BlockType.fact,
        grain="one row per wafer per process step (move event)",
        version="1.0.0", description="晶圓製程移動事件（WIP / Q-time）",
        block_lifecycle=LifecycleStatus.draft, primary_keys=[],
        columns=[
            ColumnSchema(name="move_id", data_type="string"),
            ColumnSchema(name="event_date", data_type="date"),
            ColumnSchema(name="week", data_type="integer"),
            ColumnSchema(name="shift", data_type="string"),
            ColumnSchema(name="lot_id", data_type="string"),
            ColumnSchema(name="product_family", data_type="string"),
            ColumnSchema(name="route_id", data_type="string"),
            ColumnSchema(name="priority", data_type="string"),
            ColumnSchema(name="wafer_id", data_type="string"),
            ColumnSchema(name="step_id", data_type="string"),
            ColumnSchema(name="step_name", data_type="string"),
            ColumnSchema(name="tool_id", data_type="string"),
            ColumnSchema(name="tool_group", data_type="string"),
            ColumnSchema(name="area", data_type="string"),
            ColumnSchema(name="vendor", data_type="string"),
            ColumnSchema(name="queue_time_hr", data_type="float"),
            ColumnSchema(name="process_time_min", data_type="float"),
            ColumnSchema(name="move_count", data_type="integer"),
            ColumnSchema(name="rework_flag", data_type="integer"),
            ColumnSchema(name="hold_flag", data_type="integer"),
            ColumnSchema(name="hold_age_hr", data_type="float"),
            ColumnSchema(name="hold_reason", data_type="string"),
        ],
        metrics=[
            MetricDefinition(name="move_count", formula="SUM(move_count)",
                             disaggregation_method=DisaggregationMethod.sum, description="移動次數"),
            # name != column → derived (the formula sandbox allows AVG/SUM on a column)
            MetricDefinition(name="avg_queue_time_hr", formula="AVG(queue_time_hr)",
                             disaggregation_method=DisaggregationMethod.none, unit="hr",
                             description="平均等待時間"),
            MetricDefinition(name="avg_process_time_min", formula="AVG(process_time_min)",
                             disaggregation_method=DisaggregationMethod.none, unit="min",
                             description="平均製程時間"),
            # additive totals → enable share-of-total ("ETCH 等待佔全廠多少%").
            # disagg=none (derived) so the planner evaluates the SUM() formula rather
            # than treating the metric name as a native column.
            MetricDefinition(name="total_queue_hr", formula="SUM(queue_time_hr)",
                             disaggregation_method=DisaggregationMethod.none, unit="hr",
                             description="總等待時間"),
            MetricDefinition(name="total_process_min", formula="SUM(process_time_min)",
                             disaggregation_method=DisaggregationMethod.none, unit="min",
                             description="總製程時間"),
            MetricDefinition(name="rework_count", formula="SUM(rework_flag)",
                             disaggregation_method=DisaggregationMethod.none, description="重工次數"),
            MetricDefinition(name="hold_count", formula="SUM(hold_flag)",
                             disaggregation_method=DisaggregationMethod.none, description="保留(hold)次數"),
            MetricDefinition(name="avg_hold_age_hr", formula="AVG(hold_age_hr)",
                             disaggregation_method=DisaggregationMethod.none, unit="hr",
                             description="平均保留(hold)時間"),
            MetricDefinition(name="max_hold_age_hr", formula="MAX(hold_age_hr)",
                             disaggregation_method=DisaggregationMethod.none, unit="hr",
                             description="最長保留(hold)時間"),
            MetricDefinition(name="rework_rate", formula="SUM(rework_flag) / NULLIF(SUM(move_count),0) * 100",
                             disaggregation_method=DisaggregationMethod.none, unit="%",
                             description="重工率（重工÷移動）"),
            MetricDefinition(name="unique_wafers", formula="COUNT(DISTINCT wafer_id)",
                             disaggregation_method=DisaggregationMethod.none, description="不重複晶圓數"),
            MetricDefinition(name="unique_lots", formula="COUNT(DISTINCT lot_id)",
                             disaggregation_method=DisaggregationMethod.none, description="不重複批號數"),
        ],
        data_source=InlineDataSource(records=moves),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHE[_MOVE_ID] = block
    return block


def build_wafer_yield_block() -> DataBlockContract:
    if _YIELD_ID in _CACHE:
        return _CACHE[_YIELD_ID]
    _, yields = _generate()
    block = DataBlockContract(
        block_id=_YIELD_ID, block_type=BlockType.fact,
        grain="one row per wafer at final test",
        version="1.0.0", description="晶圓最終電測良率",
        block_lifecycle=LifecycleStatus.draft, primary_keys=[],
        columns=[
            ColumnSchema(name="yield_event_id", data_type="string"),
            ColumnSchema(name="test_date", data_type="date"),
            ColumnSchema(name="week", data_type="integer"),
            ColumnSchema(name="lot_id", data_type="string"),
            ColumnSchema(name="product_family", data_type="string"),
            ColumnSchema(name="priority", data_type="string"),
            ColumnSchema(name="wafer_id", data_type="string"),
            ColumnSchema(name="etch_tool_id", data_type="string"),
            ColumnSchema(name="cycle_time_hr", data_type="float"),
            ColumnSchema(name="rework_status", data_type="string"),
            ColumnSchema(name="tested_die", data_type="integer"),
            ColumnSchema(name="good_die", data_type="integer"),
            ColumnSchema(name="defect_die", data_type="integer"),
            ColumnSchema(name="yield_pct", data_type="float"),
            ColumnSchema(name="defect_type", data_type="string"),
            ColumnSchema(name="bin_code", data_type="string"),
            ColumnSchema(name="failed_wafer_count", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="tested_die", formula="SUM(tested_die)",
                             disaggregation_method=DisaggregationMethod.sum, description="受測晶粒"),
            MetricDefinition(name="good_die", formula="SUM(good_die)",
                             disaggregation_method=DisaggregationMethod.sum, description="良品晶粒"),
            MetricDefinition(name="defect_die", formula="SUM(defect_die)",
                             disaggregation_method=DisaggregationMethod.sum, description="不良晶粒"),
            MetricDefinition(name="weighted_yield_pct",
                             formula="SUM(good_die) / NULLIF(SUM(tested_die),0) * 100",
                             disaggregation_method=DisaggregationMethod.none, unit="%",
                             description="加權良率（良品÷受測）"),
            MetricDefinition(name="defect_density_pct",
                             formula="SUM(defect_die) / NULLIF(SUM(tested_die),0) * 100",
                             disaggregation_method=DisaggregationMethod.none, unit="%",
                             description="不良率（不良÷受測）"),
            MetricDefinition(name="failed_wafer_count", formula="SUM(failed_wafer_count)",
                             disaggregation_method=DisaggregationMethod.sum, description="失敗晶圓數"),
            MetricDefinition(name="tested_wafers", formula="COUNT(DISTINCT wafer_id)",
                             disaggregation_method=DisaggregationMethod.none, description="受測晶圓數"),
            MetricDefinition(name="avg_cycle_time_hr", formula="AVG(cycle_time_hr)",
                             disaggregation_method=DisaggregationMethod.none, unit="hr",
                             description="平均生產週期時間"),
        ],
        data_source=InlineDataSource(records=yields),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHE[_YIELD_ID] = block
    return block


_CAPACITY_ID = "fab_tool_capacity"

# Embedded utilization / availability / performance signal per tool (Round 128):
#   (util, uptime/availability, ideal_move_min, performance)
#   util = actual ÷ capacity (ETCH-02 ~constraint; CVD idle headroom)
#   uptime = availability; performance = speed efficiency
#   ETCH-02: high util but LOW availability (0.70) AND low performance (0.78) →
#   worst OEE despite being the bottleneck.
_TOOL_CAP = {
    "PHOTO-01": (0.78, 0.92, 42, 0.93), "PHOTO-02": (0.70, 0.90, 42, 0.90),
    "ETCH-01":  (0.86, 0.88, 60, 0.90), "ETCH-02":  (0.94, 0.70, 60, 0.78),
    "CVD-01":   (0.46, 0.95, 50, 0.92), "CVD-02":   (0.40, 0.95, 50, 0.92),
    "IMP-01":   (0.66, 0.86, 35, 0.90), "IMP-02":   (0.60, 0.84, 35, 0.88),
    "CMP-01":   (0.52, 0.90, 30, 0.91), "CMP-02":   (0.55, 0.90, 30, 0.91),
    "METAL-01": (0.62, 0.89, 55, 0.90), "METAL-02": (0.58, 0.89, 55, 0.89),
}
_TOOL_META = {tid: (tg, _AREA[tg], v) for tg, tools in _TOOLS.items()
              for (tid, v, _r, _y) in tools}


def build_tool_capacity_block() -> DataBlockContract:
    """Round 128: per-tool capacity / availability reference (one row per tool).

    capacity = actual moves ÷ embedded utilisation; available/run hours give
    availability (uptime); planned_moves a target; ideal_move_min the ideal
    process time — together enabling utilisation, loading, headroom, plan
    attainment, OEE (availability × performance × quality)."""
    if _CAPACITY_ID in _CACHE:
        return _CACHE[_CAPACITY_ID]
    moves, _ = _generate()
    actual = {}
    for m in moves:
        actual[m["tool_id"]] = actual.get(m["tool_id"], 0) + m["move_count"]
    rows = []
    for tid, (util, uptime, ideal_min, perf) in _TOOL_CAP.items():
        tg, area, vendor = _TOOL_META.get(tid, ("", "", ""))
        act = actual.get(tid, 0)
        capacity = max(int(round(act / util)), act) if util else act
        # Derive hours from the actual ideal work so OEE Performance is realistic:
        #   ideal_h = act × ideal_min/60 ; run_h = ideal_h/perf ; avail_h = run_h/uptime
        ideal_h = act * ideal_min / 60.0
        run_hours = round(ideal_h / perf, 1) if perf else ideal_h
        available_hours = round(run_hours / uptime, 1) if uptime else run_hours
        planned = int(round(capacity * 0.90))  # plan = 90% of capacity
        rows.append({
            "tool_id": tid, "tool_group": tg, "area": area, "vendor": vendor,
            "capacity_moves": capacity, "actual_moves_ref": act,
            "available_hours": available_hours, "run_hours": run_hours,
            "uptime_pct": round(uptime * 100, 1), "ideal_move_min": ideal_min,
            "planned_moves": planned,
        })
    block = DataBlockContract(
        block_id=_CAPACITY_ID, block_type=BlockType.fact,
        grain="one row per tool (capacity reference)",
        version="1.0.0", description="機台產能 / 稼動參考",
        block_lifecycle=LifecycleStatus.draft, primary_keys=["tool_id"],
        columns=[
            ColumnSchema(name="tool_id", data_type="string"),
            ColumnSchema(name="tool_group", data_type="string"),
            ColumnSchema(name="area", data_type="string"),
            ColumnSchema(name="vendor", data_type="string"),
            ColumnSchema(name="capacity_moves", data_type="integer"),
            ColumnSchema(name="actual_moves_ref", data_type="integer"),
            ColumnSchema(name="available_hours", data_type="float"),
            ColumnSchema(name="run_hours", data_type="float"),
            ColumnSchema(name="uptime_pct", data_type="float"),
            ColumnSchema(name="ideal_move_min", data_type="integer"),
            ColumnSchema(name="planned_moves", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="capacity_moves", formula="SUM(capacity_moves)",
                             disaggregation_method=DisaggregationMethod.sum, description="產能(可做移動數)"),
            MetricDefinition(name="planned_moves", formula="SUM(planned_moves)",
                             disaggregation_method=DisaggregationMethod.sum, description="計畫移動數"),
            MetricDefinition(name="available_hours", formula="SUM(available_hours)",
                             disaggregation_method=DisaggregationMethod.sum, unit="hr", description="可用工時"),
            MetricDefinition(name="run_hours", formula="SUM(run_hours)",
                             disaggregation_method=DisaggregationMethod.sum, unit="hr", description="運轉工時"),
            MetricDefinition(name="availability_pct",
                             formula="SUM(run_hours) / NULLIF(SUM(available_hours),0) * 100",
                             disaggregation_method=DisaggregationMethod.none, unit="%",
                             description="可用率(運轉÷可用工時)"),
            MetricDefinition(name="avg_uptime_pct", formula="AVG(uptime_pct)",
                             disaggregation_method=DisaggregationMethod.none, unit="%", description="平均稼動率"),
        ],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHE[_CAPACITY_ID] = block
    return block


def fab_contracts() -> dict[str, DataBlockContract]:
    return {_MOVE_ID: build_process_move_block(), _YIELD_ID: build_wafer_yield_block(),
            _CAPACITY_ID: build_tool_capacity_block()}


def build_fab_demo_report() -> ExecutableReportSpec:
    """A starter wafer-fab dashboard (yield, Q-time, WIP, defects)."""
    m, y = BlockRef(_MOVE_ID), BlockRef(_YIELD_ID)

    def _v(vid, block, metrics, vt, title, dims=None, sort=None, extra=None):
        q = VisualQuerySpec(spec_id=vid, block_refs=[block], metrics=metrics,
                            dimensions=dims or [], sort=sort or [], inherit_global_filter=True)
        return ReportVisualSpec(vid, q, VisualizationSpec(vt, title=title, extra=extra or {}))

    kpi_yield = _v("kpi_yield", y, [MetricRef(_YIELD_ID, "weighted_yield_pct", "加權良率")],
                   VisualType.kpi_card, "加權良率", extra={"unit": "%"})
    kpi_moves = _v("kpi_moves", m, [MetricRef(_MOVE_ID, "move_count", "移動次數")],
                   VisualType.kpi_card, "移動次數")
    kpi_qt = _v("kpi_qt", m, [MetricRef(_MOVE_ID, "avg_queue_time_hr", "平均等待")],
                VisualType.kpi_card, "平均等待(hr)", extra={"unit": "hr"})
    bar_qt_step = _v("bar_qt_step", m,
                     [MetricRef(_MOVE_ID, "avg_queue_time_hr", "平均等待")],
                     VisualType.bar_chart, "各製程站等待時間（找瓶頸）",
                     dims=[DimensionRef(_MOVE_ID, "step_name", "製程站")],
                     sort=[SortSpec("平均等待", SortDirection.desc)])
    bar_yield_prod = _v("bar_yield_prod", y,
                        [MetricRef(_YIELD_ID, "weighted_yield_pct", "加權良率")],
                        VisualType.bar_chart, "各產品良率",
                        dims=[DimensionRef(_YIELD_ID, "product_family", "產品")],
                        sort=[SortSpec("加權良率", SortDirection.desc)])

    visuals = {v.component_id: v for v in
               [kpi_yield, kpi_moves, kpi_qt, bar_qt_step, bar_yield_prod]}
    page = ReportPageSpec(page_id="main", title="晶圓廠營運儀表板",
                          visuals=visuals, visual_order=list(visuals.keys()),
                          display_name="Fab Ops")
    return ExecutableReportSpec(
        audit=AuditMetadata(report_id="fab_demo_v1", revision=1),
        title="晶圓廠營運儀表板", semantic_model_ref="fab_demo",
        status="validated_demo_draft", pages={"main": page}, controls={})
