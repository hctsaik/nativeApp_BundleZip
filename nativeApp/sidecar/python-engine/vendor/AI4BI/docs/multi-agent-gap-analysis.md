# AI4BI 多 Agent 需求討論：Power BI 對標差距分析

**日期：** 2026-05-29  
**參與者：** Product Manager Agent、Data Analyst Agent（8 年經驗）、Technical Architect Agent  
**討論輪次：** 2 輪  
**目標：** 識別此工具與 Power BI 的核心差距，以及實際使用場景中無法處理的問題

---

## 背景脈絡

目前 AI4BI 已完成 Round 028–031：
- 自助 CSV/Excel 上傳（028）
- 圓餅圖 + 散點圖（029）
- 格線畫布（030）
- AI 建議圖表 + CSV 匯出（031）

用戶提問核心：**「Power BI 同一畫面可以有不同主題/來源的資料，但目前工具比較像整個畫面都是同一個目的——還有哪些真實使用場景無法處理？」**

---

## Round 1：各角色初步評估

### 🎯 Product Manager 的觀點

#### 多資料源同一畫面（Multi-subject Dashboard）

架構上技術可行，但有三個實際阻礙：

| 問題 | 說明 |
|---|---|
| `semantic_model_ref` 是 report 層級 | 整份 report 綁死一個 semantic model，無法讓「銷售圖」和「供應鏈圖」各自引用獨立 schema |
| Block Library 只有單一主題 | 沒有機制讓不同主題的 blocks 共存且清楚標示 |
| Controls（全域篩選）是 report 共用 | 無法做「這個 filter 只影響銷售圖，不影響財務圖」 |

#### 真實使用場景 Gap（8 個）

1. **同期比較（MoM/YoY）**：用戶想看「本月 vs 去年同月」，但系統無 time-intelligence 函數，filter 只能做靜態值篩選
2. **下鑽分析（Drill-down）**：點「Asia」看各國明細——無階層維度，無 drill context 概念
3. **Cross-filtering**：點一張圖，全頁其他圖同步過濾——*schema 有佔位符但功能不存在*
4. **分享（Read-only）無身份驗證**：任何人拿到連結都能切換 mode
5. **Alert / 閾值通知**：「queue time 超過 48 小時通知我」——NL2 intent list 中完全沒有
6. **條件格式（RAG 狀態）**：KPI card 沒有紅/橙/綠狀態邏輯
7. **排程匯出 / Email**：完全沒有訂閱機制
8. **NL2 只能修改現有圖，不能從空白建圖**：應該能說「建一張銷售趨勢折線圖」就完成

#### Power BI 殺手級功能——此工具完全缺席

- **Cross-filtering**（點圖→全頁過濾）——BI 最核心互動
- **DAX / Calculated Measures**——在工具內定義 `毛利率 = (revenue-cost)/revenue`
- **Row-level Security（RLS）**——企業採購的底線需求
- **Bookmark / Storytelling**——儲存特定狀態製作簡報式流程

---

### 📊 Data Analyst 的觀點

#### 日常任務 vs 現有能力

| 任務 | 能做嗎？ | 阻礙 |
|---|---|---|
| MoM/YoY 成長率 | ❌ | `executor.py` 不支援 LAG()、window function |
| 下鑽（Drill-down） | ⚠️ 部分 | 只能切換粒度，無「選點→下一層」的 drill context |
| Alert / 閾值通知 | ❌ | NL2 intent list 中無此類型 |
| 匯出 PDF/Excel/PPT | ❌ | 無 export handler |
| Calculated Measures（yield = passed/tested） | ❌ | `_build_metric_expr()` 強制只允許 5 種聚合，複合公式直接 raise error |

#### 多資料源深層問題

**具體場景**：同一頁顯示「每日訂單數（CRM）+ 庫存水位（ERP）」，X 軸都是日期但兩個資料集沒有 join 鍵。

三個架構阻礙：
1. `_build_metric_expr()` 強制所有 metric 必須來自 `spec.primary_block_id`
2. `SafeJoinPlanner` 只允許 fact→dimension，fact-to-fact 被視為 BLOCKED fanout risk
3. `_add_metric` 的 governance check 若新指標的 `owner_block` 不在 `block_refs`，直接拒絕

→ Power BI 用 **Composite Model** 解這個問題，此工具無對應概念

#### 語意層限制

| 限制 | 說明 |
|---|---|
| `_CATEGORICAL_DIM_MAP` 是靜態 hardcoded | 鎖死在半導體 demo，零售分析師輸入「按地區分析」→ 直接 unsupported |
| 每個 visual 最多 3 個 metric | 無業務依據的保守設計，多指標 OEE 儀表板做不了 |
| `grain` 是純 string | 無法機器可讀，系統無法自動偵測 double-counting 風險 |
| 日期篩選無法跨 visual 同步 | 沒有 report-level slicer 概念 |

---

### 🏗️ Technical Architect 的觀點

#### 關鍵澄清：獨立圖表「現在就能做」

> 三張來自不同 fact table 的圖湊在 dashboard，各自 `VisualQuerySpec` 獨立執行，完全沒有問題。
> **阻礙只在「同一張圖」想同時顯示來自不同 fact 的指標。**

#### 三個最高 ROI 的架構改動

| 優先 | 改動 | 程式量 | 解鎖功能 |
|---|---|---|---|
| 1 | Derived Metric Formula Execution | ~50 行（executor.py） | 毛利率、轉換率、YoY 等所有複合指標 |
| 2 | ExternalDataSource 執行路徑 | ~100 行 + ConnectionRegistry | 連接真實 DB（PostgreSQL/BigQuery） |
| 3 | Block-agnostic Global Filter | ~80 行 | 多 fact 圖共享同一個 filter（如日期 slicer） |

**安全注意**：Formula 直接插入 SQL 需要 allow-list 校驗，否則是 SQL injection 向量。

---

## Round 2：交叉辯論

### 🎯 PM 挑戰技術架構師：「能做 ≠ 用戶能完成」

> **架構師的「現在就能做」是後端視角，前端 UX 根本不夠。**

用戶建立第二張來自不同資料源的圖時：
- 沒有「選擇資料源」的明確入口
- 用戶不知道圖一用的是哪個 fact table
- Canvas 層沒有「這個 dashboard 共有哪些資料源」的管理視圖

這是典型的 **"technically possible, UX impossible"** 陷阱。

### 🎯 PM 挑戰優先序：Cross-filter 應排第一

> 技術架構師的排序是工程師視角（什麼容易寫），而非用戶使用頻率視角。

- **Derived Metric** = 建立時的一次性操作
- **Cross-filter** = 每次看 dashboard 時都會用的互動

用戶打開 dashboard 點一張圖什麼都沒反應 → 他們會認為工具「壞掉了」，直接棄用。

### 🎯 PM 補充：RLS 是企業採購 Blocker

> 企業 BI 合規需求：銷售 A 只看自己的 region，財務只看自己的 BU。  
> 不支援 RLS → IT 部門直接否決，連 POC 都進不去。

---

### 📊 Analyst 揭示：Cross-filter 真正的難關不是 Schema

> Schema 有 `cross_filter_emit` 只解決「誰發出訊號」。

**真正的難點是接收端的 filter propagation across join paths：**

```
用戶點擊 Bar Chart 的「北區」→
session_state["cross_filters"] 被寫入 →
Streamlit 整頁 rerun →
其他 visual 各自重跑 SQL

問題：如果目標 chart 的 x 軸是跨 join 的 derived column
（region 來自 dim_table，不是 fact_table），
filter 要往哪個 table 打、用哪個 key join？
```

這需要**執行時動態重建 query plan**，不是 session state 問題。

### 📊 Analyst：Allow-list 如果太嚴，3 個真實計算會被擋

1. `PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY revenue)` — P90 業績分析
2. `SUM(revenue) / NULLIF(SUM(last_year_revenue), 0)` — YoY ratio（`NULLIF` 防除零）
3. `CASE WHEN category = 'A' THEN revenue ELSE 0 END` — 條件加總

### 📊 Analyst 補充：Date Grain 混排是「靜默資料錯誤」

> 分析師最常見：先看月，發現異常，下鑽看週。  
> 改了一個 chart 的粒度，其他 chart 還停在月份。  
> **同一頁出現月 vs 週混排卻沒有任何提示，分析師比對數字時得出錯誤結論而不自知。**

這比 cross-filtering 缺失更隱蔽、更危險。

---

### 🏗️ Architect 迴應：動態 Dim Mapping 可行性

> `_CATEGORICAL_DIM_MAP` 的問題是 hardcode 了 schema knowledge（block_id + column_name）。

修法：掃所有 dim blocks 建立倒排索引，估計 40-60 行替換現有靜態 dict。  
但前提是 `ColumnDef` 需加 `aliases: list[str]` 欄位（+半個 sprint）。

### 🏗️ Architect 揭示：Cross-filter 比想像中複雜

三個在 Round 1 沒說清楚的困難：

| 問題 | 說明 |
|---|---|
| Filter state reconciliation | 兩個 chart 同時 emit 不同 filter 值，誰優先？需要 last-write-wins 或 merge 策略 |
| Multi-page isolation | Cross-page filter 穿透邊界沒有定義 |
| Circular filter 防止 | A filter→B scope，B 又 emit 回 A 的 dimension → 需要 DAG cycle detection |

### 🏗️ Architect 識別根本瓶頸

> **所有問題的共同瓶頸是：`VisualQuerySpec` 是 query-time artifact，沒有 live semantic layer。**

Multi-fact、Derived Metrics、Cross-filter、Real Data Source 這四個問題都需要：
> 在 query 執行前做 **semantic resolution** 的中間層

如果插入一個 `SemanticPlanner`（在 executor 前）：
- 知道哪些 blocks 可以 join
- filter scope 如何傳播
- grain 是否相容
- derived formula 如何安全展開

→ 其他問題都變成它的 plugin，這是最值得優先投資的架構改動。

---

## 綜合結論

### 問題嚴重度矩陣

| 問題 | 用戶影響 | 技術難度 | 企業採購影響 | 優先建議 |
|---|---|---|---|---|
| **Cross-filter 完整實作** | 🔴 極高（每次使用都感受到） | 🟡 中（schema 有，但 query plan 需改） | 🟡 中 | P1 |
| **Date Grain 混排警示** | 🔴 極高（靜默資料錯誤） | 🟢 低（UI warning 即可） | 🟢 低 | P1 |
| **Derived Metric 執行** | 🟠 高（分析師核心需求） | 🟢 低（executor ~50 行）| 🟡 中 | P1 |
| **多資料源 UX 流程** | 🟠 高（架構已支援，UI 不夠） | 🟢 低（純 UI 改動） | 🟡 中 | P1 |
| **Dynamic Dim Mapping（NL2 泛化）** | 🟠 高（現在 NL2 只懂半導體） | 🟢 低（40-60 行） | 🟡 中 | P2 |
| **Real Data Source Connection** | 🟠 高（從 demo → production） | 🟡 中（DuckDB connector） | 🔴 高 | P2 |
| **Row-level Security（RLS）** | 🟡 中（企業才需要） | 🔴 高（需要身份系統） | 🔴 極高（採購 blocker） | P3 |
| **SemanticPlanner 中間層** | 🔴 高（解鎖所有問題） | 🔴 高（架構重構） | 🔴 高 | P3（基礎設施）|
| **Drill-down / Hierarchy** | 🟡 中 | 🔴 高 | 🟡 中 | P3 |
| **Time Intelligence（YoY/MoM）** | 🟠 高 | 🟡 中 | 🟡 中 | P2 |

---

### 關鍵洞見摘要

1. **「多資料源」問題的真相**：架構已支援（每個 visual 獨立 VisualQuerySpec），但 UX 流程沒有提供「管理多來源」的介面——這是 UX 問題，不是架構問題。Priority: 補 UI 流程。

2. **Cross-filter 不是「有沒有」的問題，是「完不完整」**：schema 有 emit，但接收端的 filter propagation across join paths 才是真正的工程挑戰。

3. **Date Grain 混排是目前最危險的靜默 bug**：不需大改架構，加一個 page-level grain 一致性警示即可解決，CP 值極高。

4. **Derived Metric 是投報率最高的單一功能**：~50 行解鎖分析師最高頻需求（毛利率、轉換率），且 formula 欄位已存在只是沒被 executor 信任。

5. **長期架構方向**：`SemanticPlanner`（query 執行前的語意解析層）是解鎖 multi-fact、cross-filter、derived metrics 的共同基礎設施。

---

## 下一輪討論方向建議

### 方向 A：深度討論 Cross-filter 設計（技術 × 產品）

> 如果要在 2 個 sprint 內做出「可用的」cross-filter，最小可行版本是什麼？  
> 如何處理 filter propagation across join paths？是否需要 SemanticPlanner 作前置條件？

### 方向 B：Derived Metric 的安全模型設計（技術 × 分析師）

> Allow-list 要怎麼設計才能放行合理公式（NULLIF、CASE WHEN、PERCENTILE_CONT）但阻擋 SQL injection？  
> 是否需要一個「公式沙盒」編輯器 UI 讓用戶驗證公式？

### 方向 C：從 Demo → Production 路線圖（產品 × 技術）

> 要讓這個工具能連接真實 PostgreSQL/BigQuery，最小的改動步驟是什麼？  
> ConnectionRegistry 的安全設計（憑證存放）如何不成為安全弱點？

### 方向 D：企業採購路線（產品 × 分析師）

> 如果要讓這個工具能進入企業 IT 採購名單，除了 RLS，還需要哪些合規功能？  
> SOC 2 Type II、GDPR Data Residency、Audit Log 等，哪個優先？

---

## 附錄：目前功能狀態（Round 031 後）

```
✅ 自助 CSV/Excel/Parquet 上傳
✅ 格線畫布（per-visual 寬度調整）
✅ 4 種圖表（bar, line, KPI, table）+ pie + scatter
✅ NL2 自然語言改圖（14 種 intent）
✅ AI 建議圖表（Copilot 風格）
✅ CSV 資料匯出
✅ Multi-page report
✅ Publication gate + Read-only sharing
✅ Block version pinning
✅ Chat history

⚠️ Cross-filter（schema 存在，功能不完整）
⚠️ NL2 add_visual（可用，但 dim mapping 只懂半導體 demo）
⚠️ Sandbox 模式（標示存在，邊界不清晰）

❌ Cross-filter（完整的 filter propagation）
❌ Derived Metrics（複合公式執行）
❌ Date grain 混排警示
❌ 多資料源 UX 管理流程
❌ Time Intelligence（YoY/MoM）
❌ Real data source connection（PostgreSQL/BigQuery）
❌ Row-level Security
❌ Drill-down / Hierarchy
❌ Bookmark / Storytelling
❌ Alert / Threshold notification
❌ SemanticPlanner 中間層
```
