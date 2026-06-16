# AI4BI Power BI 對標差距分析（第四輪 · Multi-Agent）

**日期：** 2026-05-30
**方法：** 兩個獨立 Agent 實地讀碼（Power BI 功能對標審計 + 複雜情境壓力測試），以 file:function 為證。前提：R041–R077 已完成（slicer、連接器、cross-filter、derived/cross-fact metrics、time intelligence、變化分解、預測、alerts、條件格式/RAG、summary、drill-down、datastore、undo/redo、書籤、what-if、histogram、Pareto、Top-N、matrix/pivot、segments、cohort、funnel、basket、NL2 加視覺、Excel/PDF 匯出、密碼分享、state-driven 頁面）。

## 兩個 Agent 的收斂結論

| Lens | 最高 ROI 缺口 | 理由 |
|---|---|---|
| **A · Power BI 對標** | **NL「直接回答」引擎**（`answer_metric` intent） | 整個 NL2 介面今天只能「改畫布」，使用者問「上個月營收多少？」得到的是圖表提案而非數字 — 直接違背 MEMORY 的「5 分鐘可信答案」承諾。難度低、依賴全都已存在（SchemaIndex.best_metric_match + compute_period_comparison + ResultMetadata 溯源）。 |
| **B · 複雜情境壓力** | **executor 的 HAVING（聚合後篩選）** | 「買超過 N 次的客戶」「低於門檻的滯銷品」churn/VIP/slow-mover 名單**今天完全無法表達**，`_build_filter_clause` 只能 pre-aggregation 篩 raw row，且**無 pandas 替代方案**。改動面最小（`_build_sql` 加 HAVING 段），spec 的 FilterSpec 已具備所有運算子。 |

## 共同發現（兩 agent 交集）

1. **進階分析已實作但 NL 到不了**：cohort/funnel/basket/segments/grouped-comparison（變化分解）皆能運算，但只埋在 sidebar 面板，`nl2proposal` 的 intent router 無任一路由到它們，打字問會落入 `_unsupported`。純接線、compute 已存在 = 高 ROI glue。
2. **誠實 check（half-wired）**：
   - `VisualType.map` 是死 enum：`render_visual._COMPONENT_REGISTRY` 無 `map` renderer，任何 map 視覺靜默落入 "not yet implemented"。
   - `suggestions.detect_anomalies` 只在 `InlineDataSource/CachedDataSource` 跑，外部 DB 連接器路徑**零洞察**。
   - 快取命中時 `ResultMetadata` 退化（agg="—"、formula=metric_name），溯源面板顯示劣化資訊。

## 複雜情境壓力測試（Lens B 13 題摘要）

可做：why-did-it-change 變化分解(#4，但僅面板)、basket(#10)、cohort(#11)、median/percentile(若預先定義)。
**不可做**：3 個月連續下滑(#1，需 lag/streak window)、同店 YoY 排除今年新開店(#3，需子查詢)、庫存周轉(#5，無庫存模型)、churn 名單(#6，需 recency+HAVING)、買>3次且花<$500(#7，HAVING)、各店 Top-10 商品(#8，PARTITION window)、子群內佔比(#9b，partition window)。

## 缺口排序（綜合 SMB 價值 × 解鎖情境數 / 難度）

| 排序 | 缺口 | 解鎖 | SMB | 難度 | 做法 |
|---|---|---|---|---|---|
| 1 | **NL 直接回答引擎** `answer_metric` | 「5 分鐘可信答案」核心承諾 | 5 | 2 | nl2 新增 answer intent → SchemaIndex 解析指標 + compute_period_comparison 跑 1 query → 回傳句子 + KPI 提案 + 溯源 footnote |
| 2 | **executor HAVING（聚合後篩選）** | churn/VIP/slow-mover 名單(#6,#7)、#3 排除邏輯 | 5 | 2 | QuerySpec 加 `having: list[FilterSpec]`，`_build_sql` GROUP BY 後輸出 HAVING |
| 3 | **NL 路由到既有進階分析** | cohort/funnel/basket/segments/變化分解對使用者可達(#4,#10,#11) | 4 | 2 | nl2 intent router 加 analysis 關鍵字 → 對應面板/分析 |
| 4 | **RFM / recency-churn 模組** | churn 名單(#6) | 4 | 3 | 仿 cohort 的 pandas 面板：per-customer MAX(date) vs 錨點 + 分層 |
| 5 | **window functions（lag/row_number/partition）** | 連續下滑(#1)、各店 Top-N(#8)、子群佔比(#9b) | 4 | 5 | executor 重架（最大 blast radius，多數需求已有 pandas workaround，後置） |
| 6 | **map / geo 視覺**（retail demo 已有 city） | 地理分布 | 3 | 3 | render_map 用 plotly scatter_geo/choropleth，註冊進 _COMPONENT_REGISTRY |
| 7 | **anomaly 支援外部 DB 連接器** | 連接器路徑的主動洞察 | 4 | 2 | detect_anomalies 改走 executor 小型 aggregate 而非 materialize |
| 8 | **目標/實際 pacing（gauge/進度條）** | 「達標了嗎」 | 4 | 2 | what-if target + kpi_card 進度條 |

## UI/UX 後續討論清單（非功能缺口，但影響可用性）

> 此區收集使用者實際操作中回報的 UI/UX 摩擦，留待專門的 UI/UX 輪次集中處理（避免散在功能輪中分心）。

1. **✅ 已處理（R102）左側 NL 輸入框太小（2026-05-30 使用者回報）** — 原為單行 `st.text_input`。R102 改為 `st.text_area(height=80)`：約 3 行高、可拖曳右下角放大，比單行寬鬆但不常態佔據大量側欄高度。採用候選做法 (a)。`app.py:_render_visual_assistant`。
   - 候選做法（待討論）：(a) 改 `st.text_area` 但 `height` 設小（~68px）並可手動拖拉；(b) 維持單行，聚焦時才展開（需自訂 component / CSS，Streamlit 原生不支援 focus-grow）；(c) 把 NL 助理從側欄移到主畫面頂部的寬輸入列（更接近 Power BI Copilot 的位置），側欄只留快捷；(d) 增加「展開輸入」小按鈕切換 text_input↔text_area。
   - 傾向：(c) 長期最對標 Power BI；(a) 最低成本可先上。

## 實作佇列（依 ROI，每輪 test+commit+push）
**R078 NL 直接回答引擎** · R079 executor HAVING · R080 NL 路由到進階分析 · R081 RFM/churn 模組 · R082 anomaly 支援連接器 · R083 目標 pacing · R084 map/geo · (之後) window functions 重架 · 主題/行動版 · scheduled email backend · 真 RLS。

> 確認「不是缺口」（勿重做）：cross-fact ratio/diff/margin_pct、變化分解運算、Pareto/Top-N、書籤、what-if、外部連接器、Excel/PDF — 皆已存在。
