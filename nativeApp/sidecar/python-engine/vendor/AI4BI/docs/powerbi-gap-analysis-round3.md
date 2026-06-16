# AI4BI Power BI 對標差距分析（第三輪 · Multi-Agent）

**日期：** 2026-05-30
**方法：** 兩個獨立 Agent（Power BI 對標審計 + 複雜情境壓力測試），在 R041–067 已完成的大量功能基礎上,實地讀碼後回報。
**結論：** 大部分常見 + 進階分析已可做；**剩下的缺口集中在一個根因**——executor 是刻意的「單一 GROUP BY」引擎,無 window function / HAVING / 自我 join / 子查詢。凡是需要「逐維度的期間差異、自我 join、集合交集、或單一比率以外的跨表算術」都還做不到。

## 收斂的最高 ROI 下一階（兩個 agent 交集）

| 缺口 | 解鎖情境 | SMB | 難度 | 做法 |
|---|---|---|---|---|
| **跨表算術 diff / margin_pct**（非只有 ratio） | 成本在另一張表時的「貢獻毛利排名」 | 5 | 2 | cross_fact.compose_two_facts 加 op∈{ratio,diff,margin_pct},輸出 (A−B)/A、A−B,再排序 |
| **相對日期 slicer**（最近7/30天、本月、QTD） | 所有時間相對問題,且不會隨新資料過期 | 4 | 2 | report_slicer 加 relative_date 型別,get_slicer_filters 由 today() 算 lo/hi |
| **Top-N + 其他** | 排名圖總和可對帳 | 4 | 2 | postprocess 加 top_n,尾端彙總成「其他」列(同 pareto 模式) |
| **逐維度期間差異引擎** | 「上週營收為何下降」分解、同店 YoY、雙線 PoP 圖 | 5 | 3 | 把 compute_period_comparison 從回傳純量改為「對兩個窗各跑 grouped spec → 依維度 merge → 算 Δ 與 Δ占比」,重用現有 executor |
| **Matrix / 樞紐表**（列×欄+小計+展開） | Excel/PB 最常用物件 | 5 | 3 | render_pivot 用 pandas.pivot_table,註冊 VisualType.pivot(目前 enum 有但未註冊) |
| **客戶分群 builder**（新客vs回頭、高價值） | 新vs回頭客營收、複合分群 | 4 | 3 | materialize_dataframe → pandas customer_segments(同 cohort/funnel hatch) |
| **預測 / 外推**（rolling 12 週） | 簡單趨勢預測 | 4 | 3 | trend line 追加未來 x 點做 polyval 外推(目前只 in-sample) |
| **PDF 匯出**（董事會用報告） | 可分享成品 | 5 | 3 | 仿 build_report_excel 迴圈,visual→PNG→reportlab |
| **跨頁 drill-through** | 點值→詳情頁 | 4 | 4 | 把 _render_canvas 的 st.tabs 改成 state 驅動頁面選擇,點擊帶 filter 切頁 |
| 主題/行動版、地圖、small multiples | 包裝/特殊視覺 | 3 | 2-3 | 後續 |

## 實作佇列（依 ROI,每輪 test+commit+push）
R068 跨表 diff/margin_pct · R069 相對日期 slicer · R070 Top-N+其他 · R071 逐維度 PoP 差異(分解/同店YoY/雙線) · R072 Matrix 樞紐表 · R073 客戶分群 · R074 預測外推 · R075 PDF · R076 跨頁 drill-through · 之後 主題/行動版。

> 確認「不是缺口」(勿重做)：undo/redo(workspace 21 深)、multi-select drill、條件格式/RAG、histogram、what-if、外部連接器——皆已存在。
