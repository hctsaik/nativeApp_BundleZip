"""Dynamic schema index for NL2 — Round 035.

Builds keyword → (block_id, column, alias, truncate) mappings at runtime from
loaded DataBlockContracts, so NL2 works on any user-uploaded CSV, not just the
hardcoded semiconductor demo.

The index merges:
1. Dynamic entries inferred from column names and metric names in loaded contracts.
2. Common Chinese ↔ English word synonyms for business columns.
3. Static semiconductor-demo entries (kept as fallback, lower priority).

Usage
-----
    from ai4bi.ai.schema_index import SchemaIndex
    idx = SchemaIndex.build(contracts)
    entry = idx.find_dim("門市")    # → {"block_id": "retail_sales", "column_name": "store_name", ...}
    entry = idx.find_metric("收入")  # → {"block_id": "retail_sales", "metric_name": "revenue"}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ai4bi.blocks.contracts import BlockType, DataBlockContract

# ---------------------------------------------------------------------------
# Common business column synonym table (EN stem → list of ZH aliases)
# ---------------------------------------------------------------------------

_EN_TO_ZH: dict[str, list[str]] = {
    "store":      ["門市", "店", "商店", "分店", "門店"],
    "shop":       ["門市", "商店"],
    "city":       ["城市", "縣市", "地區", "地點"],
    "region":     ["地區", "區域", "地點", "城市"],
    "category":   ["品類", "分類", "類別", "類型"],
    "product":    ["商品", "產品", "品項"],
    "item":       ["品項", "商品"],
    "channel":    ["通路", "渠道", "銷售管道"],
    "brand":      ["品牌"],
    "vendor":     ["供應商", "廠商"],
    "customer":   ["客戶", "顧客"],
    "date":       ["日期", "時間"],
    "month":      ["月份", "月"],
    "week":       ["週", "星期"],
    "day":        ["日", "天"],
    "revenue":    ["收入", "營收", "銷售額", "業績"],
    "sales":      ["銷售額", "業績", "銷售"],
    "amount":     ["金額", "總額"],
    "quantity":   ["數量", "件數"],
    "count":      ["數量", "次數", "筆數"],
    "order":      ["訂單", "訂購"],
    "profit":     ["利潤", "獲利"],
    "margin":     ["利潤率", "毛利率"],
    "cost":       ["成本", "費用"],
    "return":     ["退貨", "退回"],
    "rate":       ["比率", "比例", "率"],
    "score":      ["分數", "評分"],
    "name":       ["名稱", "名字"],
    # --- Round 113: semiconductor wafer-fab vocabulary ---------------------
    "yield":      ["良率", "良品率", "產率", "良率百分比"],
    "queue":      ["等待", "排隊", "等候", "佇列", "等待時間", "q-time", "qtime"],
    "defect":     ["缺陷", "不良", "瑕疵", "缺點", "壞點"],
    "die":        ["晶粒", "顆粒", "die"],
    "wafer":      ["晶圓", "晶片", "片"],
    "lot":        ["批號", "批", "批次", "工單"],
    "tool":       ["機台", "設備", "機器", "機臺"],
    "step":       ["製程", "站", "製程站", "工序", "步驟", "關卡", "站點"],
    "move":       ["移動", "動作", "移動量", "走動"],
    "moves":      ["移動次數", "移動量"],
    "rework":     ["重工", "重做", "返工", "重新加工"],
    "hold":       ["保留", "暫停", "卡關", "扣留", "hold"],
    "process":    ["製程", "加工", "處理"],
    "test":       ["測試", "電測", "量測", "檢測"],
    "good":       ["良品", "好品", "合格"],
    "tested":     ["受測", "已測"],
    "density":    ["密度"],
    "unique":     ["不重複", "獨立", "相異"],
    "area":       ["區域", "區", "廠區", "面積", "大小", "尺寸"],
    "priority":   ["優先", "優先級", "優先序", "急件"],
    "route":      ["路線", "製程路線", "途程"],
    "shift":      ["班別", "班次", "輪班"],
    "etch":       ["蝕刻"],
    "implant":    ["離子植入", "植入"],
    "photo":      ["微影", "曝光", "黃光"],
    "cmp":        ["研磨", "平坦化"],
    "metal":      ["金屬", "金屬層"],
    "cvd":        ["沉積", "薄膜沉積"],
    "fail":       ["失敗", "失效"],
    "failed":     ["失敗", "失效"],
    "cycle":      ["週期", "循環"],
    "throughput": ["產出", "吞吐", "產能"],
    "time":       ["時間", "時長"],
    "age":        ["時間", "時長", "老化", "年齡"],
    "duration":   ["時間", "時長", "持續時間"],
    # --- Round 186: computer-vision dataset-management vocabulary ----------
    "class":      ["類別", "種類", "物件類別", "標籤類別"],
    "annotator":  ["標註員", "標記員", "標註者", "標註人員"],
    "confidence": ["信心", "信賴度", "置信度", "信心分數"],
    "recall":     ["召回率", "查全率"],
    "precision":  ["精確率", "精準率", "查準率"],
    "accuracy":   ["正確率", "準確率", "準確度"],
    "prediction": ["預測"],
    "pred":       ["預測"],
    "image":      ["影像", "圖片", "圖像"],
    # NOTE: 'bbox' intentionally has NO synonym — "標註框" must resolve the
    # bbox_COUNT metric (via its description), never the bbox_id row identifier.
    "iou":        ["一致性", "重疊度", "交並比"],
    "duplicate":  ["重複", "重覆", "副本"],
    "split":      ["切分", "資料集切分", "資料切分"],
    "version":    ["版本", "資料集版本"],
    "annotation": ["標註", "標記"],
    "correct":    ["正確", "答對"],
    "error":      ["錯誤", "答錯", "誤判"],
    "ap":         ["平均精度", "mAP", "ap"],
}

_ZH_TO_EN: dict[str, str] = {}  # built lazily below

# Columns that indicate date granularity dimension
_DATE_COL_HINTS = frozenset({
    "date", "time", "timestamp", "dt", "ts",
    "order_date", "created_at", "event_date", "sale_date",
    "transaction_date", "report_date",
})

_DATE_TRUNCATE_KEYWORDS: dict[str, str] = {
    "month": "month", "月份": "month", "月": "month",
    "week": "week", "週": "week",
    "day": "day", "daily": "day", "日": "day",
    "year": "year", "年": "year",
    "quarter": "quarter", "季": "quarter",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _col_tokens(col_name: str) -> list[str]:
    """Split snake_case or camelCase into lowercase tokens."""
    # split on _ and spaces first
    parts = re.split(r"[_\s]+", col_name.lower())
    return [p for p in parts if p]


_DESC_SPLIT_RE = re.compile(r"[\s/÷×・,，、:：;；()（）「」【】\[\]+\-]+")


def _desc_tokens(description: Optional[str]) -> list[str]:
    """Round 186: derive keywords from a column/metric ``description``.

    Many uploaded contracts name columns in English ("recall", "confidence") but
    describe them in the analyst's language ("召回率", "平均信心"). The name-token
    synonym table can't cover every domain, so we also index description words.
    Descriptions are written as space/punctuation-separated synonym lists, so a
    simple split yields each term. Tokens shorter than 2 chars are dropped (they
    fuzzy-match unrelated words and produce confidently-wrong answers).
    """
    if not description:
        return []
    out: list[str] = []
    for chunk in _DESC_SPLIT_RE.split(description):
        c = chunk.strip().lower()
        if len(c) >= 2:
            out.append(c)
    return out


def _is_date_col(col_name: str, data_type: str) -> bool:
    if data_type in ("date", "timestamp", "datetime"):
        return True
    # Round 114: a NUMERIC column is a measure, never a date dimension — even if
    # its name contains "time" (e.g. queue_time_hr, process_time_min, cycle_time).
    if data_type in ("integer", "int", "float", "number", "numeric", "double", "bigint"):
        return False
    tokens = set(_col_tokens(col_name))
    return bool(tokens & {"date", "time", "ts", "dt", "day", "month", "year",
                          "week", "period", "timestamp", "at", "on", "created", "updated"})


def _build_zh_to_en() -> dict[str, str]:
    zh2en: dict[str, str] = {}
    for en, zhs in _EN_TO_ZH.items():
        for zh in zhs:
            if zh not in zh2en:
                zh2en[zh] = en
    return zh2en


# ---------------------------------------------------------------------------
# Entry types
# ---------------------------------------------------------------------------

@dataclass
class DimEntry:
    block_id: str
    column_name: str
    alias: str
    truncate: Optional[str] = None  # 'month' | 'week' | 'day' | None


@dataclass
class MetricEntry:
    block_id: str
    metric_name: str
    alias: str


# ---------------------------------------------------------------------------
# SchemaIndex
# ---------------------------------------------------------------------------

@dataclass
class SchemaIndex:
    """Runtime keyword index built from loaded DataBlockContracts."""
    _dims: dict[str, DimEntry] = field(default_factory=dict)    # keyword → DimEntry
    _metrics: dict[str, MetricEntry] = field(default_factory=dict)  # keyword → MetricEntry
    # Round 122: (MetricEntry, full keyword set) per metric — uncollapsed.
    _metric_keywords: list = field(default_factory=list)

    @classmethod
    def build(cls, contracts: dict[str, DataBlockContract]) -> "SchemaIndex":
        idx = cls()
        zh2en = _build_zh_to_en()

        for block_id, contract in contracts.items():
            if contract.block_type not in (
                BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact,
                BlockType.dimension, BlockType.date_dimension,
            ):
                continue

            for col in contract.columns:
                col_name = col.name
                is_date = _is_date_col(col_name, col.data_type)
                is_string = col.data_type in ("string", "str", "object", "text", "varchar")

                if not (is_date or is_string):
                    continue

                alias = col_name.replace("_", " ").title()
                entry = DimEntry(
                    block_id=block_id,
                    column_name=col_name,
                    alias=alias,
                    truncate="month" if is_date else None,
                )

                # Register the raw column name and its underscore-split tokens
                keywords: list[str] = [col_name.lower(), col_name.replace("_", " ").lower()]
                for tok in _col_tokens(col_name):
                    keywords.append(tok)
                    # EN token → ZH aliases
                    for zh in _EN_TO_ZH.get(tok, []):
                        keywords.append(zh)
                # Round 186: description-derived keywords (e.g. 類別/召回率/標註員)
                keywords.extend(_desc_tokens(col.description))

                # For date cols, also register granularity keywords
                if is_date:
                    for gran_kw in _DATE_TRUNCATE_KEYWORDS:
                        gran_entry = DimEntry(
                            block_id=block_id,
                            column_name=col_name,
                            alias=gran_kw.title(),
                            truncate=_DATE_TRUNCATE_KEYWORDS[gran_kw],
                        )
                        idx._dims.setdefault(gran_kw, gran_entry)

                for kw in keywords:
                    idx._dims.setdefault(kw, entry)

            # Register metrics
            for metric in contract.metrics:
                m_name = metric.name
                m_alias = m_name.replace("_", " ").title()
                m_entry = MetricEntry(block_id=block_id, metric_name=m_name, alias=m_alias)

                m_keywords: list[str] = [m_name.lower(), m_name.replace("_", " ").lower()]
                for tok in _col_tokens(m_name):
                    m_keywords.append(tok)
                    for zh in _EN_TO_ZH.get(tok, []):
                        m_keywords.append(zh)
                # Round 186: description-derived keywords (e.g. 召回率/平均信心/正確率)
                m_keywords.extend(_desc_tokens(metric.description))
                for kw in m_keywords:
                    idx._metrics.setdefault(kw, m_entry)
                # Round 122: keep the FULL keyword set per metric (not collapsed by
                # setdefault) so best_metric_match can score every metric — needed
                # to tell apart hold_count vs avg_hold_age_hr etc.
                idx._metric_keywords.append((m_entry, {k for k in m_keywords if len(k) >= 2}))

        return idx

    def find_dim(self, keyword: str) -> Optional[DimEntry]:
        """Look up a dimension by keyword (case-insensitive)."""
        return self._dims.get(keyword.lower()) or self._dims.get(keyword)

    def find_metric(self, keyword: str) -> Optional[MetricEntry]:
        """Look up a metric by keyword (case-insensitive)."""
        return self._metrics.get(keyword.lower()) or self._metrics.get(keyword)

    def best_dim_match(self, prompt: str, normalized: str) -> Optional[DimEntry]:
        """Find the longest-matching dimension keyword in a prompt."""
        best: Optional[DimEntry] = None
        best_len = 0
        for kw, entry in self._dims.items():
            if (kw in normalized or kw in prompt) and len(kw) > best_len:
                best = entry
                best_len = len(kw)
        return best

    def best_metric_match(self, prompt: str, normalized: str) -> Optional[MetricEntry]:
        """Find the longest-matching metric keyword in a prompt.

        Single-character keywords (e.g. the synonym '率' for *rate*) are ignored:
        they fuzzy-match unrelated words ('毛利率' → return_rate) and produce
        confident WRONG answers. Requiring length >= 2 makes the engine decline
        (return None) when the asked-for metric isn't really present, which the
        answer handlers turn into a graceful "not found" rather than a wrong rank.

        Round 114: when the prompt signals a *rate* (率/rate/%/比率), break ties
        toward a rate/pct/ratio-named metric — so '重工率' resolves rework_rate,
        not rework_count.
        """
        hay = f"{prompt.lower()} {normalized}"
        wants_rate = any(s in hay for s in ("率", "rate", "%", "比率", "比例", "percent", "佔比", "占比"))
        # Round 184 (S19): "不良率" CONTAINS the substring "良率", so a yield metric
        # falsely ties a defect metric. When the prompt signals a DEFECT, break the
        # tie toward a defect-named metric (不良率 → defect_density_pct, not yield).
        wants_defect = any(s in hay for s in ("不良", "缺陷", "瑕疵", "defect", "壞點", "缺點"))

        def _is_rate(e: "MetricEntry") -> bool:
            return any(t in e.metric_name.lower()
                       for t in ("rate", "pct", "ratio", "percent", "density"))

        def _is_defect(e: "MetricEntry") -> bool:
            return any(t in e.metric_name.lower()
                       for t in ("defect", "scrap", "fail", "reject", "ng"))

        # Round 122: score EVERY metric by its full keyword set — number of
        # distinct keywords matched (so avg_hold_age_hr matching '保留'+'時間' beats
        # hold_count matching only '保留'), tie-broken by longest keyword + a small
        # rate bonus. Falls back to the collapsed dict if the uncollapsed set is
        # unavailable (older indexes).
        best: Optional[MetricEntry] = None
        if self._metric_keywords:
            best_key = (0, 0, 0.0)
            for entry, kws in self._metric_keywords:
                matched = [k for k in kws if k in hay]
                if not matched:
                    continue
                longest = max(len(k) for k in matched)
                rate_bonus = 1.0 if (wants_rate and _is_rate(entry)) else 0.0
                defect_bonus = 1.0 if (wants_defect and _is_defect(entry)) else 0.0
                key = (len(matched), longest, rate_bonus + defect_bonus)
                if key > best_key:
                    best_key, best = key, entry
            return best

        best_score = 0.0
        for kw, entry in self._metrics.items():
            if len(kw) < 2:
                continue
            if kw in normalized or kw in prompt:
                score = len(kw) + (0.5 if (wants_rate and _is_rate(entry)) else 0.0)
                if score > best_score:
                    best, best_score = entry, score
        return best
