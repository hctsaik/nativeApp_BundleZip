"""Retail demo report — Round 033.

Replaces the semiconductor demo as the default first-impression report.
Target: retail / e-commerce / chain-store operators.

Data: ~500 rows of synthetic store sales across 5 stores, 8 products, 3 months.
Metrics: revenue (SUM), order_count (SUM), quantity (SUM)
Ratio metric: return_rate (AVG — demo of Round 032 ratio guard)
Dimensions: order_date, store_name, city, product_name, category
"""

from __future__ import annotations

import os
import random

from ai4bi.blocks.contracts import (
    BlockType,
    ColumnSchema,
    DataBlockContract,
    DataClassification,
    DisaggregationMethod,
    InlineDataSource,
    LifecycleStatus,
    MetricDefinition,
    PolicySpec,
)
from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    SortDirection,
    SortSpec,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)
from ai4bi.report.models import (
    AuditMetadata,
    ExecutableReportSpec,
    ReportPageSpec,
    ReportVisualSpec,
)

_BLOCK_ID = "retail_sales"
_CACHED_BLOCK: "DataBlockContract | None" = None  # module-level cache — generated once per process


# ---------------------------------------------------------------------------
# Data generation (deterministic, seed=42)
# ---------------------------------------------------------------------------

def _generate_records() -> list[dict]:
    rng = random.Random(42)
    stores = [
        ("TPE-01", "台北信義店", "台北", 1.4),
        ("TPE-02", "台北西門店", "台北", 1.1),
        ("TCH-01", "台中中港店", "台中", 1.0),
        ("KHH-01", "高雄三多店", "高雄", 0.9),
        ("TNN-01", "台南成功店", "台南", 0.7),
    ]
    products = [
        ("SKU-A01", "經典T恤", "服飾", 490),
        ("SKU-A02", "牛仔長褲", "服飾", 1290),
        ("SKU-A03", "運動外套", "服飾", 1890),
        ("SKU-B01", "皮革手袋", "配件", 2490),
        ("SKU-B02", "棒球帽", "配件", 390),
        ("SKU-B03", "針織圍巾", "配件", 590),
        ("SKU-C01", "護膚乳液", "保養", 890),
        ("SKU-C02", "洗顏慕斯", "保養", 590),
    ]
    # 3 months: March–May 2026, sample ~every 3rd day per store/product combo
    import datetime
    base = datetime.date(2026, 3, 1)
    records: list[dict] = []
    for day_offset in range(91):
        d = base + datetime.timedelta(days=day_offset)
        date_str = d.isoformat()
        is_weekend = d.weekday() >= 5
        for store_id, store_name, city, mult in stores:
            for sku, prod_name, category, price in products:
                if rng.random() > 0.35:  # ~35% fill rate → ~500 rows
                    continue
                weekend_boost = 1.35 if is_weekend else 1.0
                qty = max(1, int(rng.gauss(3, 1.2) * mult * weekend_boost))
                # Round 062: customer_id from a recurring pool so cohort/retention
                # analysis has repeat customers across months (deterministic).
                customer_id = f"C{rng.randint(1, 80):03d}"
                records.append({
                    "order_date": date_str,
                    "store_id": store_id,
                    "store_name": store_name,
                    "city": city,
                    "customer_id": customer_id,
                    "product_sku": sku,
                    "product_name": prod_name,
                    "category": category,
                    "quantity": qty,
                    "revenue": qty * price,
                    "order_count": 1,
                    "return_rate": round(rng.uniform(0.01, 0.12), 3),
                })
    return records


def build_retail_sales_block() -> DataBlockContract:
    """Return the retail_sales DataBlockContract with inline demo records.

    Result is module-level cached so the 500-row generation only happens once
    per Python process, avoiding AppTest timeout issues.
    """
    global _CACHED_BLOCK
    if _CACHED_BLOCK is not None:
        return _CACHED_BLOCK
    records = _generate_records()
    block = DataBlockContract(
        block_id=_BLOCK_ID,
        block_type=BlockType.fact,
        grain="one row per product sold per store per day",
        version="1.0.0",
        description="零售門市銷售示範資料（2026 年 3–5 月）",
        block_lifecycle=LifecycleStatus.draft,
        primary_keys=[],
        columns=[
            ColumnSchema(name="order_date",    data_type="date"),
            ColumnSchema(name="store_id",      data_type="string"),
            ColumnSchema(name="store_name",    data_type="string"),
            ColumnSchema(name="city",          data_type="string"),
            ColumnSchema(name="customer_id",   data_type="string"),
            ColumnSchema(name="product_sku",   data_type="string"),
            ColumnSchema(name="product_name",  data_type="string"),
            ColumnSchema(name="category",      data_type="string"),
            ColumnSchema(name="quantity",      data_type="integer"),
            ColumnSchema(name="revenue",       data_type="float"),
            ColumnSchema(name="order_count",   data_type="integer"),
            ColumnSchema(name="return_rate",   data_type="float"),
        ],
        metrics=[
            MetricDefinition(
                name="revenue",
                formula="SUM(revenue)",
                disaggregation_method=DisaggregationMethod.sum,
                unit="NT$",
                description="銷售金額",
            ),
            MetricDefinition(
                name="order_count",
                formula="SUM(order_count)",
                disaggregation_method=DisaggregationMethod.sum,
                description="訂單數",
            ),
            # Round 099: distinct customer count. Name != dedupe column, so it's a
            # derived metric — the formula sandbox already allows COUNT(DISTINCT …).
            MetricDefinition(
                name="unique_customers",
                formula="COUNT(DISTINCT customer_id)",
                disaggregation_method=DisaggregationMethod.none,
                description="不重複客戶數",
            ),
            MetricDefinition(
                name="quantity",
                formula="SUM(quantity)",
                disaggregation_method=DisaggregationMethod.sum,
                description="銷售數量",
            ),
            MetricDefinition(
                name="return_rate",
                formula="AVG(return_rate)",
                disaggregation_method=DisaggregationMethod.average,
                unit="%",
                description="退貨率（平均，不加總）",
            ),
            # Round 045: derived (composite) metric — average order value.
            # disaggregation_method=none → executor expands the validated formula.
            MetricDefinition(
                name="avg_order_value",
                formula="SUM(revenue) / NULLIF(SUM(order_count), 0)",
                disaggregation_method=DisaggregationMethod.none,
                unit="NT$",
                description="平均客單價（總營收 ÷ 訂單數，複合指標）",
            ),
        ],
        data_source=InlineDataSource(records=records),
        # Round 106: row-level-security demo — when the session identity carries a
        # "city", the executor scopes every query to that city. No identity = all.
        policy=PolicySpec(data_classification=DataClassification.internal,
                          row_filter_column="city", row_filter_identity_key="city"),
    )
    _CACHED_BLOCK = block
    return block


_STAFFING_BLOCK_ID = "store_staffing"
_CACHED_STAFFING: "DataBlockContract | None" = None


def build_store_staffing_block() -> DataBlockContract:
    """A second retail fact (one row per store) to demo cross-fact composition.

    Round 055: enables "revenue per employee" — sales (retail_sales) ÷ headcount
    (this block), joined on store_name — which single-fact GROUP BY cannot do.
    """
    global _CACHED_STAFFING
    if _CACHED_STAFFING is not None:
        return _CACHED_STAFFING
    # store_name must match retail_sales for the join key
    rows = [
        {"store_id": "TPE-01", "store_name": "台北信義店", "headcount": 14, "labor_hours": 2240},
        {"store_id": "TPE-02", "store_name": "台北西門店", "headcount": 11, "labor_hours": 1760},
        {"store_id": "TCH-01", "store_name": "台中中港店", "headcount": 9,  "labor_hours": 1440},
        {"store_id": "KHH-01", "store_name": "高雄三多店", "headcount": 8,  "labor_hours": 1280},
        {"store_id": "TNN-01", "store_name": "台南成功店", "headcount": 6,  "labor_hours": 960},
    ]
    block = DataBlockContract(
        block_id=_STAFFING_BLOCK_ID,
        block_type=BlockType.fact,
        grain="one row per store",
        version="1.0.0",
        description="門市人力配置（員工數、工時）",
        block_lifecycle=LifecycleStatus.draft,
        primary_keys=["store_id"],
        columns=[
            ColumnSchema(name="store_id",    data_type="string"),
            ColumnSchema(name="store_name",  data_type="string"),
            ColumnSchema(name="headcount",   data_type="integer"),
            ColumnSchema(name="labor_hours", data_type="integer"),
        ],
        metrics=[
            MetricDefinition(name="headcount", formula="SUM(headcount)",
                             disaggregation_method=DisaggregationMethod.sum, description="員工數"),
            MetricDefinition(name="labor_hours", formula="SUM(labor_hours)",
                             disaggregation_method=DisaggregationMethod.sum, description="工時"),
        ],
        data_source=InlineDataSource(records=rows),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    _CACHED_STAFFING = block
    return block


# ---------------------------------------------------------------------------
# Report template
# ---------------------------------------------------------------------------

def build_retail_demo_report() -> ExecutableReportSpec:
    """Return a starter retail dashboard report."""
    b = BlockRef(_BLOCK_ID)

    def _q(vid: str, metrics, dimensions=None, sort=None, limit=None, filters=None):
        return VisualQuerySpec(
            spec_id=vid,
            block_refs=[b],
            metrics=metrics,
            dimensions=dimensions or [],
            sort=sort or [],
            limit=limit,
            filters=filters or [],
            inherit_global_filter=True,
        )

    # ── KPI row ──────────────────────────────────────────────────────────────
    # Round 047: revenue KPI shows trailing-30-day value with MoM delta
    kpi_revenue = ReportVisualSpec(
        "kpi_revenue",
        _q("kpi_revenue", [MetricRef(_BLOCK_ID, "revenue", "營收")]),
        VisualizationSpec(
            VisualType.kpi_card,
            title="營收",
            extra={
                "unit": "NT$",
                "compare_period": "month",
                "compare_date_column": "order_date",
            },
        ),
    )
    kpi_orders = ReportVisualSpec(
        "kpi_orders",
        _q("kpi_orders", [MetricRef(_BLOCK_ID, "order_count", "訂單數")]),
        VisualizationSpec(VisualType.kpi_card, title="訂單數"),
    )
    kpi_return = ReportVisualSpec(
        "kpi_return_rate",
        _q("kpi_return_rate", [MetricRef(_BLOCK_ID, "return_rate", "平均退貨率", AggFunction.avg)]),
        # Round 053: RAG — return rate is "lower is better"
        VisualizationSpec(
            VisualType.kpi_card, title="平均退貨率",
            extra={"unit": "%", "rag": {"good_if": "lte", "target": 0.06, "warn": 0.10}},
        ),
    )
    # Round 045: derived metric KPI — average order value (AOV)
    kpi_aov = ReportVisualSpec(
        "kpi_avg_order_value",
        _q("kpi_avg_order_value", [MetricRef(_BLOCK_ID, "avg_order_value", "平均客單價")]),
        VisualizationSpec(VisualType.kpi_card, title="平均客單價", extra={"unit": "NT$"}),
    )

    # ── Revenue trend (line) ─────────────────────────────────────────────────
    line_trend = ReportVisualSpec(
        "line_revenue_trend",
        _q(
            "line_revenue_trend",
            metrics=[MetricRef(_BLOCK_ID, "revenue", "營收")],
            dimensions=[DimensionRef(_BLOCK_ID, "order_date", "日期", truncate_date_to="week")],
            sort=[SortSpec("日期", SortDirection.asc)],
        ),
        VisualizationSpec(
            VisualType.line_chart,
            title="每週營收趨勢",
            x_axis_label="日期",
            y_axis_label="營收（NT$）",
            height_px=320,
            # Round 074: weekly revenue trend + 4-week linear forecast
            extra={"line_color": None,
                   "trend_line": {"method": "linear", "forecast_periods": 4}},
        ),
        col_span=12,
    )

    # ── Revenue drill-down: 地區 › 門市 › 商品 (bar) ───────────────────────────
    bar_store = ReportVisualSpec(
        "bar_revenue_by_store",
        _q(
            "bar_revenue_by_store",
            metrics=[MetricRef(_BLOCK_ID, "revenue", "營收")],
            dimensions=[DimensionRef(_BLOCK_ID, "city", "地區")],
            sort=[SortSpec("營收", SortDirection.desc)],
        ),
        VisualizationSpec(
            VisualType.bar_chart,
            title="營收下鑽（地區 › 門市 › 商品）",
            x_axis_label="地區",
            y_axis_label="營收（NT$）",
            height_px=300,
            # Round 049: click a bar to drill into the next level
            # Round 058: show value labels on bars
            extra={
                "drill_hierarchy": ["city", "store_name", "product_name"],
                "data_labels": True,
            },
        ),
        col_span=6,
    )

    # ── Revenue by category (pie) ─────────────────────────────────────────────
    pie_category = ReportVisualSpec(
        "pie_revenue_by_category",
        _q(
            "pie_revenue_by_category",
            metrics=[MetricRef(_BLOCK_ID, "revenue", "營收")],
            dimensions=[DimensionRef(_BLOCK_ID, "category", "品類")],
        ),
        VisualizationSpec(
            VisualType.pie_chart,
            title="品類營收佔比",
            height_px=300,
            extra={"hole": 0.4, "show_percent": True},
        ),
        col_span=6,
    )

    # ── Top products table ────────────────────────────────────────────────────
    table_products = ReportVisualSpec(
        "table_top_products",
        _q(
            "table_top_products",
            metrics=[
                MetricRef(_BLOCK_ID, "revenue",      "營收"),
                MetricRef(_BLOCK_ID, "order_count",  "訂單數"),
                MetricRef(_BLOCK_ID, "return_rate",  "退貨率", AggFunction.avg),
            ],
            dimensions=[
                DimensionRef(_BLOCK_ID, "product_name", "商品"),
                DimensionRef(_BLOCK_ID, "category",     "品類"),
            ],
            sort=[SortSpec("營收", SortDirection.desc)],
            limit=10,
        ),
        VisualizationSpec(
            VisualType.table, title="商品銷售明細（Top 10）", height_px=320,
            # Round 053: flag products whose return rate exceeds 8%
            extra={"conditional_formats": [
                {"column": "退貨率", "method": "threshold", "operator": "gt",
                 "value": 0.08, "color": "#FF4444"},
            ]},
        ),
        col_span=12,
    )

    # ── Product ABC / Pareto analysis (Round 054) ─────────────────────────────
    table_abc = ReportVisualSpec(
        "table_product_abc",
        _q(
            "table_product_abc",
            metrics=[MetricRef(_BLOCK_ID, "revenue", "營收")],
            dimensions=[DimensionRef(_BLOCK_ID, "product_name", "商品")],
            sort=[SortSpec("營收", SortDirection.desc)],
        ),
        VisualizationSpec(
            VisualType.table,
            title="商品 ABC 分析（哪些商品貢獻 80% 營收）",
            height_px=320,
            # Round 054: post-process into a Pareto table (cumulative % + ABC class)
            extra={"postprocess": "pareto", "postprocess_column": "營收"},
        ),
        col_span=12,
    )

    # ── Transaction-size distribution (Round 059 histogram) ───────────────────
    hist_revenue = ReportVisualSpec(
        "hist_revenue",
        _q(
            "hist_revenue",
            metrics=[],
            dimensions=[DimensionRef(_BLOCK_ID, "revenue", "revenue")],
        ),
        VisualizationSpec(
            VisualType.bar_chart,           # intercepted by render_visual as histogram
            title="單筆銷售金額分布",
            x_axis_label="單筆金額（NT$）",
            y_axis_label="筆數",
            height_px=300,
            extra={"chart_mode": "histogram", "bins": 25},
        ),
        col_span=6,
    )

    # ── Store × Category pivot/matrix (Round 072) ─────────────────────────────
    pivot_store_cat = ReportVisualSpec(
        "pivot_store_category",
        _q(
            "pivot_store_category",
            metrics=[MetricRef(_BLOCK_ID, "revenue", "營收")],
            dimensions=[DimensionRef(_BLOCK_ID, "store_name", "門市"),
                        DimensionRef(_BLOCK_ID, "category", "品類")],
        ),
        VisualizationSpec(
            VisualType.pivot, title="門市 × 品類 營收矩陣", height_px=300,
            extra={"show_totals": True},
        ),
        col_span=12,
    )

    visuals = {
        "kpi_revenue":           kpi_revenue,
        "kpi_orders":            kpi_orders,
        "kpi_avg_order_value":   kpi_aov,
        "kpi_return_rate":       kpi_return,
        "line_revenue_trend":    line_trend,
        "bar_revenue_by_store":  bar_store,
        "pie_revenue_by_category": pie_category,
        "hist_revenue":          hist_revenue,
        "table_top_products":    table_products,
        "table_product_abc":     table_abc,
        "pivot_store_category":  pivot_store_cat,
    }
    visual_order = list(visuals.keys())

    page = ReportPageSpec(
        "main", "門市銷售總覽",
        visuals, visual_order,
        display_name="門市銷售總覽",
    )

    return ExecutableReportSpec(
        audit=AuditMetadata(
            report_id="retail_demo_v1",
            created_by=os.environ.get("ANALYST_NAME", "demo"),
        ),
        title="零售門市銷售儀表板",
        semantic_model_ref="retail_demo@1.0.0",
        status="user_draft",
        pages={"main": page},
        controls={},
    )
