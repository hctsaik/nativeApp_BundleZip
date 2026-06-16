# AI4BI Power BI 對標差距分析（第二輪 · Multi-Agent）

**日期：** 2026-05-29
**方法：** 起兩個獨立 Agent（資深 BI 分析師視角 + Power BI 功能對標審計視角），各自實地閱讀程式碼後回報，以 file:function 為證。
**前提：** Round 041–051 已完成（全域篩選器、連接器、cross-filter、derived metrics、time intelligence、alerts、drill-down、summary、datastore）。本輪找「還缺什麼才更像 Power BI」。

---

## 收斂結論：最高 ROI 缺口（scaffolding 已存在，屬接線/擴充）

| 排序 | 缺口 | 現況證據 | 影響 | 難度 |
|---|---|---|---|---|
| 1 | **計算欄位 UI** | 引擎 `executor.py:_build_derived_formula_expr`（R045，含 allow-list 沙箱）已可安全執行 `(revenue-cost)/revenue`，但 `app.py` 無任何「新增計算欄位」表單，formula 只能從 JSON 或自動推斷進入 | 5 | 2 |
| 2 | **條件格式 / RAG** | `data_table.py` 的 `conditional_formats` 只支援 IQR/z-score 離群值；`kpi_card.py` 無門檻著色（只有 delta 顏色）；門檻邏輯只存在於 `alerts.py` 的橫幅 | 4 | 2 |
| 3 | **累計 / 移動平均 / Pareto** | `executor.py:_build_sql` 只發單一 GROUP BY，無 window function（`time_intelligence.py:21` 註明）；`line_chart.py` 的 rolling 只是視覺疊加 | 5 | 2 |
| 4 | **跨 fact 複合指標接線** | `composition_executor.py` / `composition_plan.py` 引擎已建好且通過安全審查，但 `ai4bi/ui/` 無任何呼叫，唯一 factory 是半導體範例 → 零售用戶到不了 | 5 | 3 |
| 5 | **Excel / PDF 匯出** | 只有 CSV（`app.py` download_button）；無 to_excel/reportlab/pptx | 4 | 2 |

## 跨切面架構阻礙（根因）

1. **executor 無 window function** → 擋住累計、Pareto、cohort、retention。
2. **單 fact、僅 fact→dim join** → 擋住跨 fact 單圖、cohort、market-basket；強迫走未接線的 composition。
3. **composition 引擎是孤兒** → 缺口 #4 是「最大能力躍升、最少新引擎程式碼」。
4. **NL2 仍半導體 hardcode**（`nl2proposal.py:_DIM_KEYWORD_MAP`），`SchemaIndex`（R035）已是動態 fallback 但主表錯領域。

## 被點名的負債（非 SMB 優先但須誠實）

- `report/publication.py:_check_policy` 永遠回傳 `passed=True`（「Not yet enforced」卻聲明通過）— 應降級為 `not_enforced`，停止錯誤聲明。
- 唯讀分享 `?mode=readonly&draft=<path>` 無 token，任何人可改 URL。
- `PolicySpec.row_filter_expr` / `allowed_roles` 定義了但 executor 從未注入（RLS 假的）。

## 實作佇列（依 ROI，每輪 test+commit+push）

- **R052**：計算欄位 UI（缺口 #1）
- **R053**：條件格式 + KPI RAG（缺口 #2）
- **R054**：累計/移動平均/Pareto（缺口 #3）
- **R055**：跨 fact 複合指標接線（缺口 #4）
- **R056**：Excel 匯出（缺口 #5）
- **R057**：誠實化安全聲明（`_check_policy` → not_enforced）

> 已延後（SMB 非優先 / 需更深架構）：cohort、funnel、market-basket（需 window function 或 analysis-block 通道）、完整 RLS（需身分系統）。
