# AI-for-BI Living Design Council Log

| 項目 | 內容 |
| --- | --- |
| 文件目的 | 保存每輪 Multi-Agent 設計討論、共識、異議、決策與下一輪問題，讓未來 Agent 可直接接續 |
| 建立日期 | `2026-05-27` |
| 文件性質 | Append-only 討論記錄；新的結論可標記舊結論為 superseded，但不得刪除歷史脈絡 |
| 主要規格 | [spec.md](./spec.md) |
| GUI / Wireframe 討論 | [wireframe-review.md](./wireframe-review.md) |

## 1. Future Agent 接續規則

接手此專案的 Agent 應依序：

1. 閱讀本文件的 `North Star`、`Current Working Thesis` 與最新一輪討論。
2. 閱讀 `spec.md` 取得目前已寫入的正式產品/契約定義。
3. 閱讀 `wireframe-review.md` 取得目前 GUI 與使用意圖結論。
4. 若使用者要求繼續完善需求，啟動多角色討論，避免僅由單一視角修改規格。
5. 每輪討論完成後，先將結果 append 至本文件，再更新被影響的正式 spec 或 wireframe。
6. 若新結論推翻舊結論，不刪除舊輪次；在新輪次的 `Supersedes` 欄位明確說明。

每輪至少留下：

| 必記欄位 | 說明 |
| --- | --- |
| Round goal | 本輪要解決的產品/架構問題 |
| Agent perspectives | 參與討論的角色與關注角度 |
| Consensus | 可寫入 spec 的共同結論 |
| Disagreements / cautions | 仍有風險或尚未定案的部分 |
| Decisions recorded | 已寫入哪些正式文件與章節 |
| Open questions | 下一輪需要討論或由使用者決定的問題 |
| Next round prompt | 可直接交給下一批 Agent 的聚焦題目 |

## 2. North Star

使用者的長期目標是打造一個非常強大的 AI-for-BI 工具：

```text
資料科學家 / 資料團隊
  -> 提供一個一個可重用的 JSON 資料積木
  -> 不再為每一個業務題目客製化 GUI

業務使用者
  -> 在 BI 工具內自行挑選資料積木、組成分析模型
  -> 建立多資料來源、多頁、多圖表與表格的互動 Dashboard
  -> 使用自然語言或 GUI 修改分析與畫面
  -> 保存、分享、重現並信任分析結果
```

### 2.1 必須保留的願景

- GUI 應由通用的 report / visual / interaction runtime 生成，而不是由資料科學家為每種需求另寫畫面。
- 資料來源可擴充為多個 JSON data blocks，支援跨來源分析。
- DIY 不只代表修改一張圖，而是能建立、組合與分享完整分析成果。
- AI 是建模、探索、解釋與設計的助手，但不能以不透明方式改變數字含義。

### 2.2 不可空泛承諾的邊界

「不管多麼複雜的 JSON 都自動正確分析」不能直接作為可驗收承諾。可驗收的產品方向應是：

> 對符合 `DataBlockContract` 且通過模型驗證的資料積木，平台能讓使用者以 no-code / low-code 方式組合成可信的多資料分析與 Dashboard；對不確定的關聯、粒度、公式或權限，系統提出 proposal、阻擋或要求核准，而非猜測。

## 3. Current Working Thesis

目前正式文件已確認以下方向：

| 主題 | 目前結論 | 來源 |
| --- | --- | --- |
| 產品主體 | 不再以單圖為產品主架構，而是多資料、多 visual 的 report workspace | `spec.md` v1.3-draft、`wireframe-review.md` |
| 第一入口 | 業務可手動選取受治理指標，不必先使用 AI | `spec.md` |
| 第一成果 | `R1` 即需可保存、重新開啟與唯讀分享多元件 Dashboard | `spec.md` |
| 多表安全 | `R1` 使用預先認證 relationships；不允許 AI 或業務靜默任意 Join | `spec.md` |
| GUI 架構 | `報表設計` / `查看資料` / `管理關聯` 三種工作視角 | `wireframe-review.md` |
| AI 邊界 | 外觀修改不改數字；分析修改需 diff；新 relationship 只能 proposal 後核准 | `spec.md` |

## 4. 尚未解決的核心議題

以下問題是從「受治理的示範 Dashboard」進一步邁向「可擴充 JSON 資料積木平台」時必須討論的主線：

| Topic | 為什麼重要 |
| --- | --- |
| `DataBlockContract` | 決定資料科學家交付什麼，平台才能不寫客製 GUI 仍理解資料 |
| 多 fact / 跨來源模型 | 實績、預算、庫存、行銷、客戶、事件資料的粒度與對齊極難 |
| 轉換與計算積木 | 清洗、派生欄位、時間對齊、窗口計算是否也由 JSON 描述 |
| AI model-authoring | AI 能否建議模型、公式、dashboard，而不污染正式語義 |
| 治理與發布流程 | 誰可發布 data block、核准關聯/metric、更新後如何處理既有 Dashboard |
| 通用 GUI runtime | 何種元件與互動語彙足以涵蓋大量分析場景而不用客製前端 |
| 能力邊界 | 哪些進階分析仍需 notebook/code 或資料專家介入 |

## 5. 討論輪次

### Round 000 - From Single Chart to Governed Multi-Visual Dashboard

| 欄位 | 記錄 |
| --- | --- |
| Date | `2026-05-27` |
| Goal | 判斷單圖 Dashboard 是否足以支援類 Power BI 的多資料 DIY |
| Agent perspectives | Semantic modeling、Power BI UX、AI/spec contracts、self-service trust/governance |
| Consensus | 單一 `ui_spec.analysis` 不足；需升級為 `Semantic Model -> Report/Page -> Multiple VisualQuerySpec -> Interaction/Sharing` |
| Consensus | `R1` 就需多 KPI / trend / table、global filter、保存與唯讀分享 |
| Consensus | Join 不可由 AI 或業務臨時猜測；`R1` 使用已認證模型，`R2` 才開放 relationship proposal |
| Documents updated | `spec.md` v1.3-draft、`wireframe-review.md` V4 Multi-Data Report Workspace |
| Open questions | JSON data block 的契約、資料積木發布流程、多 fact 複雜度與長期通用 GUI runtime |

### Round 001 - JSON Data Blocks as a Universal BI Building System

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-27` |
| Goal | 把願景從固定認證模型擴展為「資料團隊交付 JSON 資料積木，業務自行組合 BI 成果」的平台 |
| Agent perspectives | Headless analytics architecture、no-code product UX、semantic computation、AI automation safety、enterprise red-team |
| Consensus | Data block 不只是 rows/data；必須攜帶 schema、grain、keys、metrics、relationships/capabilities、time、quality/security/version metadata，才能被通用 GUI 安全使用 |
| Consensus | 長期產品定位應是 `Headless Analytics Platform`：同一套底層供 GUI、AI Agent、embedded analytics 或 API 使用 |
| Consensus | 通用產品必須增加 `Data Block View / 資料積木` 與 `Library View / 成果庫`；Report / Model 仍為核心工作區 |
| Consensus | AI 透過 Proposal / Diff / Approval / Audit 提升組裝速度；不得自行使新 Join、新 metric 或資料修正成為可信事實 |
| Consensus | 複雜情境需以可插拔 `Analysis Block` / 專用 visual 擴充，例如 funnel、cohort、forecast、attribution，而非假設基本 chart 可涵蓋一切 |
| Caution | JSON 是傳輸/契約格式，不等於任意 JSON records 可自動 Join 或直接可信分析 |
| Caution | 資料科學家不再反覆寫頁面 GUI，但仍需建立、測試、發布及治理資料/指標/分析積木 |
| Supersedes | 擴充 Round 000：產品長期終點不只 multi-visual Dashboard，而是 Data Block/Analysis Block 驅動的 analytics platform |

#### 001-A. Refined Product Vision

> 建立一個可擴充、受治理的 AI-assisted headless analytics platform。資料科學家以可重用的 JSON Data Blocks、Metrics、Relationships 與 Analysis Blocks 提供能力；業務使用者在認證範圍內，透過 no-code GUI 與 AI，自行建立、探索、保存與分享多資料、多頁、多元件分析應用。對未驗證關聯、特殊方法或高風險判斷，平台提出診斷與核准流程，而非假裝完全自動化。

#### 001-B. Platform Object Stack

```text
DataBlockRegistry
  -> DataBlockContract / MetricBlock / RelationshipBlock / PolicyBlock
  -> SemanticModelComposer
  -> AnalysisRuntime + deterministic validation
  -> ReportSpec / future AnalyticsAppSpec
  -> AI Proposal + Diff + Approval + Audit
  -> Sharing / Library / Embedded clients
```

#### 001-C. Minimum DataBlockContract Direction

| Contract area | 最低必要內容 | 理由 |
| --- | --- | --- |
| Identity / lifecycle | `block_id`, version, owner, `draft/validated/certified/deprecated` | 可發布、升級、淘汰與追蹤影響 |
| Data access | JSON records 或 execution/data reference、records path、refresh mode | Demo 可內含 JSON，正式規模不應強迫資料本體全裝進 JSON |
| Schema / grain | fields、types、primary/candidate keys、一列代表什麼 | 阻止錯誤加總與錯誤 Join |
| Semantic role | `fact`, `dimension`, `snapshot_fact`, `target_fact`, `bridge`, `derived_block` | 決定可安全執行的計算方式 |
| Metrics / dimensions | owner block、公式、aggregation behavior、allowed dimensions、hierarchies | 提供可重用且可驗證的業務語義 |
| Relationships | key mapping、cardinality、filter direction、certification、fanout diagnostics | 多來源組裝的安全核心 |
| Time | time roles、calendar、timezone、snapshot/period comparison semantics | 處理訂單日/退款日、同比及庫存等情境 |
| Quality / lineage | required tests、freshness、input blocks、model/version lineage | 顯示數字可信度並防 schema drift |
| Security | classification、restricted fields、row/export policy refs | 分享與匯出的必要邊界 |
| Supported analyses | 可使用的核心分析/專用 analysis blocks | 讓 GUI 知道何時需專用元件 |

#### 001-D. Capability Classification

| 類別 | 例子 | 產品處理方式 |
| --- | --- | --- |
| 核心可泛化場景 | 認證 KPI、時間/區域/品類拆解、趨勢、排行、明細、比較、保存分享 | 通用 Report Canvas 與 Data Blocks 支援 |
| 需要 Analysis Block 的場景 | funnel、cohort/留存、預算 vs 實績、庫存、歸因、預測、異常、地圖 | 資料/分析團隊發布可重用專用積木與 visual vocabulary |
| 不可聲稱完全 DIY 的場景 | 因果推論、高風險法遵/醫療/財務模型、未治理 raw data、任意 ML 訓練與即時營運決策 | 平台可呈現受核准輸出或提供擴充介面，不提供無條件自動結論 |

#### 001-E. AI Safety Decisions Proposed

| ID | Decision candidate |
| --- | --- |
| `AI-001` | AI 對正式分析的所有數字影響變更均以 Proposal 表達，不直接覆寫可信成果。 |
| `AI-002` | Style/layout 可 preview 與 Undo；query/model/metric/quality/security 變更必須顯示 risk-classified diff。 |
| `AI-003` | 新 relationship、新 metric、資料修正與跨 fact 組合需 deterministic validation，且高風險項目由適當 owner 核准。 |
| `AI-004` | Report sharing 執行 Share Gate：記錄 Data Block/Model 版本、有效 filters、認證狀態、freshness 與權限。 |
| `AI-005` | AI workflow 應職責分離為 catalog、model/diagnostic、metric、report designer、visual editor、validator、approval、audit/explanation。 |

#### 001-F. Product Views Added

| View | 目的 |
| --- | --- |
| `Report View / 設計報表` | 業務建立、探索與分享多頁、多 visual 分析成果 |
| `Data Block View / 資料積木` | 搜尋積木、了解 grain/metrics/相容性/freshness/認證狀態 |
| `Model View / 資料模型` | 檢視或核准關聯、模型風險與指標來源 |
| `Library View / 成果庫` | 重用 Dashboard、模板、版本與分享成果 |

#### 001-G. Open Questions

1. Data Block 正式產品中，是承載 records，還是以 JSON contract 指向可執行資料端，或兩者皆可？
2. 資料積木是否拆成 `Fact/Dimension/Metric/Relationship/Derived/Policy/Analysis` 多種 block type？
3. 業務是否能在 sandbox 使用未認證 JSON block，並禁止正式分享？
4. 最先需要證明的 multi-fact 場景應是 `Actual vs Target`、`Sales vs Returns`、`Inventory` 或其他？
5. 報表是否長期升級成可支援 what-if、write-back、workflow 與 alert 的 `AnalyticsAppSpec`？
6. 誰可發布/核准 certified Data Block、Relationship、Metric 及 Analysis Block？

#### 001-H. Documents To Update After Refinement

- `spec.md`：將產品願景由 multi-visual report 擴展成 Data Block / Analysis Block 平台，並納入分階段 roadmap。
- `wireframe-review.md`：未來補充 `Data Block View` 與 `Library View`，但 Report View 仍是業務第一工作區。
- 新契約文件：在 Round 002 完成後建立 `data-block-contract.md`，保存可實作的 schema 初稿與驗證 gates。

### Round 002 - Data Block Contract and Safe Composition Rules

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 將 Round 001 願景收斂為正式 block 類型、JSON contract schema、生命週期與可驗收的多積木組合規則 |
| Agent perspectives | Data Architecture、No-code Product UX、AI Safety & Governance、Python/Data Engineering |
| Input | Round 001 共識、`spec.md` v1.3、現有 ReportSpec 與多資料 GUI |

#### 002-A. DataBlockContract 正式 JSON Schema（共識草案）

四個角色一致認同以下最小必要欄位結構：

```json
{
  "block_id": "sales_daily",
  "version": "1.0.0",
  "lifecycle": "certified",
  "block_type": "fact",
  "display_name": "每日門店銷售",
  "owner": { "team": "data-eng", "email": "data@company.com" },
  "schema": {
    "fields": [
      { "name": "sale_id", "type": "string", "semantic_role": "key", "nullable": false },
      { "name": "store_id", "type": "string", "semantic_role": "foreign_key" },
      { "name": "sale_date", "type": "date", "semantic_role": "time_key" },
      { "name": "amount", "type": "decimal", "semantic_role": "measure" }
    ],
    "primary_key": ["sale_id"]
  },
  "grain": {
    "description": "每筆銷售交易一列",
    "grain_keys": ["sale_id"],
    "additive_dimensions": ["store_id", "sale_date"]
  },
  "data_access": {
    "mode": "inline_records",
    "inline_records": {
      "records": [],
      "checksum_sha256": "abc123"
    },
    "refresh": { "mode": "static" }
  },
  "metrics": [
    {
      "metric_id": "revenue",
      "display_name": "營收",
      "formula": "amount",
      "aggregation": "sum",
      "format": "#,##0",
      "unit": "TWD"
    }
  ],
  "relationships": [
    {
      "rel_id": "sales_to_stores",
      "target_block_id": "stores_dim",
      "join_keys": [{ "source_field": "store_id", "target_field": "store_id" }],
      "cardinality": "many_to_one",
      "filter_direction": "target_to_source",
      "certification_status": "certified",
      "fanout_risk": "none"
    }
  ],
  "time": {
    "primary_date_field": "sale_date",
    "timezone": "Asia/Taipei",
    "snapshot_semantics": "none"
  },
  "quality": {
    "required_tests": ["not_null_pk", "unique_pk", "freshness"],
    "freshness_sla_hours": 4
  },
  "security": {
    "data_classification": "confidential",
    "restricted_fields": []
  },
  "supported_analyses": ["trend", "ranking", "kpi_card", "distribution"]
}
```

**三種資料存取模式（共識）：**

| Mode | 適用場景 | 技術實作 |
| --- | --- | --- |
| `inline_records` | 開發/測試/小型 lookup（< 10K rows） | Pydantic 解析 → Arrow Table → DuckDB register |
| `execution_ref` | 生產環境動態查詢（SQL / dbt / Spark） | connection_id 引用，不儲存憑證本身 |
| `data_ref` | 大型靜態資料集 | Parquet / Delta，支援 partition pushdown |

#### 002-B. Block Type 分類策略（共識）

| Block Type | 用途 | 關鍵特性 |
| --- | --- | --- |
| `fact` | 可加總的交易事實 | additive measures、時間欄位 |
| `snapshot_fact` | 某時間點的狀態快照 | semi-additive，不跨時間加總 |
| `target_fact` | 預算/目標 | grain 通常比 fact 粗，需顯式宣告 |
| `dimension` | 描述性主題表 | SCD 類型、hierarchy |
| `date_dimension` | 日曆維度 | 獨立出來，處理複雜日曆邏輯 |
| `metric_set` | **跨 fact 的指標定義集（不含資料）** | 允許指標在多個 fact 上重用 |
| `derived_block` | 從其他 block 計算的衍生資料 | 必須宣告 lineage，禁止循環依賴 |
| `relationship` | 兩 block 間的安全關聯定義 | 獨立存在供集中稽核 |
| `policy` | 行/欄安全政策 | 與業務邏輯解耦 |
| `analysis` | 特殊分析積木（funnel / cohort） | 具有內建分析邏輯步驟，不只是資料+樣式 |

**重要新增共識：`metric_set` 必須獨立**。指標定義（如毛利率公式）可能跨多個 fact block 重用，若綁在單一 fact 上，fact 版本升級時所有指標需跟著改。`metric_set` 獨立後，由 Query Engine 在執行期動態解析。

#### 002-C. 多 Fact 組合安全規則（共識）

**三層 Fan-out 防護機制：**

1. **靜態宣告層（DataBlockContract）**：資料科學家在 contract 中聲明 `allowed_join_keys`，只有白名單欄位允許被 JOIN。`fanout_risk` 欄位（none / low / high / blocked）在 block 寫入 registry 時計算，而非 query 時才發現。

2. **Query Planner 靜態分析層**：執行前偵測兩個 fact block 直接 JOIN（無 dimension 中介）即自動拒絕。JOIN key 不在 `allowed_join_keys` 即拒絕。

3. **AI 限制層**：AI 只能提案，不得自動執行未認證 JOIN。`fanout_risk = "blocked"` 時 AI 必須給出替代路徑建議，而非嘗試繞過。

**多 Fact 安全組合模式（由易到難）：**
- **同 grain + 共同維度** → 可直接 JOIN，安全
- **不同 grain + 共同上層維度（如 month）** → 各自先聚合到共同 grain，再 JOIN
- **many-to-many** → 必須透過已認證的 bridge block，禁止臨時推斷

#### 002-D. DataBlock 生命週期治理（共識）

```
draft → validated → certified → deprecated
          ↓              ↓
       rejected      suspended（緊急單人啟動，48小時內補審核）
```

| 轉換 | 授權者 |
| --- | --- |
| draft → validated | Data Scientist 提交，自動測試核准 |
| validated → certified | Data Manager + 業務 Domain Owner 雙簽 |
| certified → deprecated | Data Manager 提交，月會委員會核可 |
| certified → suspended | Data Manager 單人（緊急），48h 內補審核 |

**Deprecation 後 Dashboard 處理：**
- 影響分析（impact graph）在提交時自動產生
- 90 天遷移窗口，期間顯示 banner 警告
- 窗口結束後：Dashboard 進入 read-only frozen 狀態，歷史快照保留供稽核
- **絕不自動切換到替代積木**（即使欄位名相同，語義可能已變）

#### 002-E. Sandbox UX 視覺語言（共識）

| 層次 | 設計 |
| --- | --- |
| 環境層（全頁） | 頂部不可關閉橫幅：琥珀色背景 `🔬 沙盒模式 — 含未認證積木，不可對外分享` |
| 元件層（每張圖） | 右上角小標籤 `[實驗中]`，琥珀色邊框 |
| 操作層（分享/匯出） | 分享按鈕變灰 + tooltip 說明，技術層硬擋（非僅 UI 提示） |
| 匯出/截圖 | 強制半透明浮水印 `⚠ SANDBOX — 未認證資料`，CSS 層實作不可被報表設計覆蓋 |

**色彩規則**：琥珀色保留給 sandbox/警告；紅色保留給資料載入失敗/錯誤；認證積木用藍色 + 盾牌 icon。

#### 002-F. R1 GUI 最小元件集（共識）

| 元件 | 用途 | 必要 Analysis Contract 欄位 |
| --- | --- | --- |
| KPI Card | 單一指標 + 趨勢箭頭 | 1 measure, 可選 period_compare |
| Line / Area Chart | 時間趨勢 | 1 time_dim, 1-3 measures |
| Bar Chart（含堆疊/群組） | 排行、比較、組成 | 1 category_dim, 1-2 measures |
| Table（含條件格式） | 明細、排行榜 | N dims, N measures |
| Filter Panel | 全域篩選 | filter_targets: [block_ids] |

Funnel / Cohort / Map 等 Analysis Block 元件保留至 R2，明確告知使用者在路線圖中，不現在就放半成品。

#### 002-G. 技術實作方向（共識）

- **Pydantic v2 discriminated union**：`InlineDataSource` vs `ExternalDataSource` 用 `mode` 欄位 discriminate
- **DuckDB 載入路徑**：inline JSON → Arrow Table → `conn.register()`，比 DataFrame 效能優
- **Registry**：SQLite（lifecycle 索引）+ JSON files（contract 版本控管，git-friendly）
- **Fan-out 偵測**：`allowed_join_keys` 宣告在 contract，Query Planner 在產生 SQL 前靜態驗證
- **PII 欄位標記**：`semantic_role: "restricted"` 在 column schema 中聲明，Authorization 層在 Query Plan 插入 masking

#### 002-H. AI Safety 補充規則

- DataBlock 描述等自由文字欄位，進入 AI context 前必須過獨立 **content sanitizer**
- AI 提案的 relationship 必須附帶 risk-classified 資訊（HIGH/MEDIUM/LOW/INFO）
- `fanout_risk = "high"` → AI 顯示警告並要求確認；`fanout_risk = "blocked"` → AI 直接拒絕並提供替代路徑

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 002-A DataBlockContract schema 初版草案（三模式資料存取） |
| Consensus | 002-B 十種 block types，`metric_set` 必須獨立於 fact block |
| Consensus | 002-C 三層 Fan-out 防護，`fanout_risk` 在 registry 寫入時計算 |
| Consensus | 002-D 四狀態生命週期 + suspended 緊急機制，雙簽 certified，90 天遷移 |
| Consensus | 002-E Sandbox 視覺語言：琥珀色、技術層硬擋、浮水印不可繞過 |
| Consensus | 002-F R1 最小元件集：5 種，Analysis Block 元件保留至 R2 |
| Consensus | 002-G 技術棧：Pydantic v2 + Arrow + SQLite Registry |
| Disagreements | `relationship` 是否應獨立為 block type，還是嵌在 source block 的 `relationships` 陣列中（UX 複雜度 vs 集中稽核性） |
| Disagreements | Content sanitizer 的維護責任與誤判申訴流程尚未確認 |
| Disagreements | PII masking 邏輯位置：SQL Compiler 層 vs Execution Engine 層（各有 tradeoff） |
| Decisions recorded | design-council-log.md Round 002、spec.md 待更新（見下一步） |
| Open questions | 見 002-I |

#### 002-I. Open Questions → Round 003 議題

1. **共同 grain 對齊（Date Spine）**：多 fact 組合時，「共同上層維度（如 month）」的 date spine 是由哪個 block 提供？是 `date_dimension` block 固定擔任 spine 角色，還是需要另外定義 `spine_block_id`？

2. **Metric Set 的 GUI 發現性**：`metric_set` 獨立後，業務使用者如何在 GUI 中瀏覽「跨 block 的可用指標」？需要設計 Metric Catalog 視圖嗎？

3. **Analysis Block 的 SQL Pattern 邊界**：funnel / cohort 的 SQL 邏輯（LEAD/LAG、self-join、window function）由誰定義？資料科學家在 `analysis` block 中如何安全宣告而不讓 LLM 直接產生？

4. **Relationship Block 獨立 vs 嵌入**：集中管理（獨立 block）有利稽核，但 UX 複雜；嵌入 source block 的 `relationships[]` 更直覺，但稽核分散。最終採哪種？

5. **認證 SLA**：如果 validated → certified 需要雙簽且走月會，業務等 30 天才能用新積木，Sandbox 的實際使用模式會扭曲嗎？如何設計快速通道（fast-track）?

6. **GUI Runtime 的 Analysis Contract**：資料科學家發布 `analysis` block 時，如何聲明該 block 支援哪些元件（funnel_chart, cohort_heatmap），以及欄位綁定規則（哪欄是 `event_sequence`，哪欄是 `cohort_date`）？

#### Next Round Prompt

> Round 003 聚焦議題：
> 1. 多 Fact 的 Date Spine 架構：date_dimension 如何承擔 spine 角色，multi-grain 對齊的 Query Plan 是什麼？
> 2. Metric Catalog GUI：`metric_set` block 在業務端的發現性設計與 AI 輔助指標推薦邊界
> 3. Analysis Block 的 SQL Pattern 合約：funnel/cohort 的安全宣告格式，讓 Query Planner 可執行而不依賴 LLM 產生 SQL
> 4. Relationship 集中 vs 嵌入的最終決策：結合稽核需求、Registry 實作與 UX 複雜度做出明確取捨

---

### Round 003 - Date Spine, Metric Catalog & Analysis Block Contracts

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 解決多 fact grain 對齊的 date spine 架構；定義 Metric Catalog GUI；確立 Analysis Block 安全 SQL pattern 宣告格式；決定 Relationship 集中 vs 嵌入 |
| Agent perspectives | Date Spine & Architecture、Metric Catalog UX、AI Safety & Governance、Python/Data Engineering |
| Input | Round 002 共識、Open Questions 002-I |

#### 003-A. Date Spine 架構（共識）

`date_dimension` block 固定擔任 spine 角色，contract 中加入 `is_spine: true` 與 `supported_grains` 宣告。

**Grain Normalization 策略**（Query Planner 核心邏輯）：

1. 解析各 block 的 grain 宣告（`temporal: day|month`, `spatial: store|national`）
2. 找出查詢目標 grain（由業務選擇）
3. grain 比目標細的 fact（如銷售/日） → `GROUP BY` 聚合，聚合函數從 metric `aggregation` 欄位讀取
4. grain 比目標粗的 fact（如預算/月） → 依 block 宣告的 `disaggregation_method` 分攤

**重要共識**：`disaggregation_method`（`equal_split` / `weighted_by_sales`）必須在 DataBlockContract 中明確宣告，不允許 Query Planner 靜默假設。缺少此欄位時 Planner 必須拋出 `GrainMismatchError`。

**DuckDB SQL 生成模式（CTE 結構）**：
```sql
WITH
  spine AS (date_dimension × store_dim CROSS JOIN，提供完整時間×空間格),
  sales_grain AS (fact_sales GROUP BY target_grain，SUM聚合),
  budget_grain AS (fact_budget 分攤到 target_grain，依 disaggregation_method)
SELECT ... FROM spine LEFT JOIN sales_grain ... LEFT JOIN budget_grain ...
```

#### 003-B. Relationship 集中 vs 嵌入 — 最終決策（共識）

**決議：混合方案**

- **主體**：Relationship 作為獨立的 `relationship` block type（集中稽核、獨立版本線）
- **輔助**：source block 自動填入 `relationship_hints[]`（Registry 在 block 寫入時自動回填，唯讀）
- **權威來源**：Query Planner 以獨立 relationship block 為準，`hints` 僅供 GUI 顯示

```jsonc
// source block 的 relationship_hints（Registry 自動回填，Data Scientist 不手動填）
{ "relationship_hints": [{ "relationship_block_id": "rel_sales_product_v1", "role": "source" }] }

// 獨立 relationship block（真正的定義與稽核對象）
{ "block_type": "relationship", "block_id": "rel_sales_product_v1", ... }
```

風險：hints 與獨立 block 不一致時（Registry 同步延遲），Query Planner 必須以 relationship block 為準。需設計 checksum 驗證機制。

#### 003-C. Metric Set 執行期解析（共識）

`metric_set` block 的 `metrics[]` 中每個指標以 `operands[]` 宣告跨 block 欄位引用：

```json
{ "metric_id": "gross_profit_margin",
  "formula": "gross_profit / net_revenue",
  "operands": [
    { "alias": "gross_profit", "source_block": "fact_financials_v1", "source_column": "gross_profit_amount", "aggregation": "sum" },
    { "alias": "net_revenue", "source_block": "fact_sales_v1", "source_column": "revenue_net", "aggregation": "sum" }
  ] }
```

**MetricSetResolver 執行步驟**：
1. 收集所有依賴 fact block
2. 驗證跨 fact 安全性（每對 block 必須有 certified relationship，fanout_risk ≠ blocked）
3. 驗證 join key 在每個 metric 的 `allowed_join_keys` 白名單內
4. 為每個 fact block 建立 CTE（含聚合）
5. 組裝最終 formula 計算

**循環依賴防護**：Kahn's Algorithm 在 metric 儲存時執行拓樸排序，依賴鏈最深限 3 層，超過視為設計缺陷強制拒絕。

**安全邊界**：`formula` 欄位只支援四則運算與白名單函數，複雜邏輯改用 `derived_block`，禁止 LLM 直寫 `allowed_join_keys`（此欄位只由 Registry Validator 填入）。

#### 003-D. Analysis Block SQL Pattern 合約（共識）

採有限 `analysis_pattern` enum → SQL Template 填充，Query Planner **不依賴 LLM 產生 SQL**。

**Analysis Block JSON 設計**：
```json
{
  "block_type": "analysis",
  "pattern_type": "funnel_sequential",
  "source_block_id": "events_fact",
  "field_mapping": {
    "user_id": "visitor_id",
    "event_col": "event_name",
    "time_col": "event_ts",
    "steps": ["view_product", "add_to_cart", "checkout", "purchase"]
  },
  "window_hours": 48
}
```

**已定義 pattern 清單**：

| Pattern | SQL 核心技術 | 優先級 |
| --- | --- | --- |
| `funnel_sequential` | CASE WHEN + MIN timestamp + conversion window | R2 優先 |
| `cohort_date_grid` | DATE_TRUNC + self-join + period diff | R2 |
| `retention_curve` | LAG + date diff + user_id grouping | R2 |
| `period_over_period` | LAG + date spine | R1 可考慮 |
| `distribution_histogram` | WIDTH_BUCKET + GROUP BY | R2 |

**SQL 注入防護**：Template 中所有 `field_mapping` 值必須通過白名單 parser（僅允許 `column = 'literal'` 格式，禁止子查詢或函數呼叫）。Template engine 選型需有 sandbox 模式（建議評估 Jinja2 sandbox vs 自研 AST）。

**Analysis Block Certification 額外要求（AI Safety 共識）**：
- SQL AST 靜態分析通過（自動）
- 第二位 Data Scientist peer review（額外要求，比一般 fact block 嚴格）
- SQL Pattern 安全審核（window function partition key 必須來自 dimension allowlist）
- 壓力測試（large partition 不超時）

#### 003-E. Metric Catalog GUI 設計（UX 共識）

**位置**：整合進 Data Block View 的右側抽屜（Metric Drawer），非獨立頁面。

**三分區設計**：
- `可直接使用`：已認證 + 積木相容，藍色 `[+ 加入]` 按鈕
- `需補充積木`：已認證 + 缺少 block，灰色 `[查看需求]`，觸發 Block Gap Wizard
- `Sandbox 指標`：未認證，琥珀色，`[申請認證]`

**Block Gap Wizard**：業務點選需補充積木的指標後，Modal 顯示缺少哪些 block 及粒度相容性預覽（插頭/插座圖），一鍵加入後自動升級顯示。

**AI 推薦邊界**：Metric Drawer 底部固定區塊，最多同時顯示 2 則推薦；推薦只來自已認證指標；提供「不感興趣」機制（30 天後重新推薦，管理者可查看被忽略率）。

#### 003-F. Fast-Track 認證安全設計（共識）

**Fast-track 必要條件（AND 關係）**：自動測試全過 + 資料分類 ≤ INTERNAL + 無跨組織分享 + 無 restricted field + Data Manager 同步簽核 + Block 變更幅度 ≤ 20%

**絕對禁止 Fast-Track（系統層硬擋）**：
- 資料含 CONFIDENTIAL 或 RESTRICTED 等級欄位
- 跨組織分享路徑
- PII 欄位新增或修改
- 修改現有 certified join path 的基數或方向
- 同一 block 90 天內已使用過 fast-track（`last_fast_track_date` 寫入 Registry）

**UX 流程**：Sandbox 橫幅 → `[申請認證]` → Modal（填原因 + 緊急程度） → 管理者行動審核介面（批量核准、超時升級通知）

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 003-A Date Spine：date_dimension 固定擔任 spine，Grain Normalization 策略，disaggregation_method 必須宣告 |
| Consensus | 003-B Relationship：混合方案（獨立 block 為主體 + source block hints 自動回填） |
| Consensus | 003-C Metric Set：operands[] 跨 block 引用，Kahn cycle detection，max 3 依賴層 |
| Consensus | 003-D Analysis Block：finite pattern enum → SQL template fill，filter 值白名單 parser |
| Consensus | 003-E Metric Catalog：Metric Drawer 三分區 + Block Gap Wizard |
| Consensus | 003-F Fast-Track：硬擋清單 + 90 天冷卻期寫入 Registry |
| Disagreements | Template engine 選型（Jinja2 sandbox vs 自研 AST）尚未決定 |
| Disagreements | join key 命名衝突（date_key vs dt）：R0 強制一致 vs R1 加 alias mapping |
| Disagreements | AI 高風險 Proposal 的 prompt 存儲：hash only vs 加密存 vault（7 年） |
| Disagreements | Funnel UX 的步驟定義拖曳介面細節（影響 field_mapping 欄位粒度） |
| Decisions recorded | design-council-log.md Round 003 |
| Open questions | 見 003-G |

#### 003-G. Open Questions → Round 004 議題

1. **DataBlock 版本升級的破壞性變更偵測**：DataBlock v1.0 升 v1.1 時，系統如何自動判斷哪些是 breaking change（欄位刪除、PK 改變、grain 改變）vs non-breaking（欄位新增、描述修改）？`validate_upgrade()` 函數的完整規則集？

2. **Report Composer 全頁設計的 AI 解析**：業務輸入「上方放三張 KPI，中間放營收趨勢，下方放地區明細」時，AI 如何解析成 VisualQuerySpec + LayoutSpec？哪些是安全推斷，哪些必須確認？

3. **多租戶 DataBlock 命名空間**：平台擴大至多部門或外部夥伴後，Registry 如何設計命名空間隔離（`org/dept/block_id`）？block_id 的全域唯一性如何保證？

4. **AnalysisBlock 複合查詢**：Funnel Block 的輸出（用戶 ID 集合）如何作為另一個 KPI Card 的 cross-filter 輸入？Query Planner 的 filter propagation 規則是什麼？

5. **實作路徑確認**：R0 Phase 0-2 的具體工作包，哪些可以並行開發？測試框架（pytest fixtures + DuckDB :memory:）的設計標準？

#### Next Round Prompt

> Round 004 聚焦議題：
> 1. DataBlock 版本升級的 breaking change 偵測規則集（完整 validate_upgrade 規則）
> 2. Report Composer 全頁自然語言設計的 AI 解析邊界與 VisualQuerySpec 生成流程
> 3. Registry 多租戶命名空間設計（org/dept/block_id 結構）
> 4. AnalysisBlock 輸出作為 cross-filter 的 Query Planner 規則
> 5. R0 Phase 0-2 實作工作包拆分與並行開發策略

---

### Round 004 - Breaking Changes, Report Composer & Registry Namespacing

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 確立 DataBlock 版本升級的破壞性變更規則；設計全頁 AI Report Composer 的解析流程；定義 Registry 多租戶命名空間；確認 R0 實作工作包 |
| Agent perspectives | Architecture & Registry、Report Composer UX、Governance & Compliance、Engineering R0 Blueprint |
| Input | Round 003 共識、Open Questions 003-G |

#### 004-A. DataBlock 版本升級的 Breaking Change 規則（共識）

| 變更類型 | 例子 | 分類 |
| --- | --- | --- |
| 刪除 metric / 欄位改名 | 移除 `revenue` | **Breaking**（必須升 major） |
| grain 變更 | day → week | **Breaking** |
| 型別窄化 | float → int | **Breaking** |
| `disaggregation_method` 變更 | SUM → AVG | **Breaking** |
| 新增 metric（非 required） | 加入 `margin` | Non-breaking（minor） |
| 描述 / label 修改 | 改 display_name | Non-breaking（patch） |
| 改變 block_id 本身 | — | **Forbidden**（需新 block_id + tombstone） |
| 修改 PK 組合 | — | **Forbidden** |
| 跨 namespace 遷移 | — | **Forbidden** |

**Dashboard 狀態機（upgrade 觸發）**：
```
ACTIVE → [breaking change] → DEGRADED_WARNING（只讀，禁止 Refresh/分享）
       → [90 天未處理] → FROZEN → [Data Manager 手動] → 延展 30 天
                                → [仍未處理] → ARCHIVED（唯讀封存）
```

- **元件級健康標章**：不整體降級，每個受影響 Panel 各自顯示警示，未受影響 Panel 正常
- Relationship block 若 pin 版本為 major 以下，自動標記 `status: stale`（不刪除，執行時拋 `StaleRelationshipWarning`）
- Non-breaking change：Dashboard 自動升版並記錄 audit log（不需人工）
- Breaking change：Dashboard 進入 DEGRADED_WARNING，插入 `pending_migration` 佇列，需人工確認

**通知機制**：升版當下 → 第 7 天 → 第 30 天（強制彈窗）→ 第 60 天（自動開工單）→ 第 89 天（系統最終警告），全程不可關閉。

#### 004-B. Registry 多租戶命名空間（共識）

格式：`{org_slug}/{dept_slug}/{local_id}@{semver}`，例：`acme/sales/revenue_fact@2.1.0`

```sql
CREATE TABLE namespaces (ns_id TEXT PRIMARY KEY, org_slug TEXT, dept_slug TEXT, parent_ns TEXT);
CREATE TABLE blocks (fqid TEXT PRIMARY KEY, ns_id TEXT, local_id TEXT, version TEXT, status TEXT, payload JSON);
CREATE TABLE ns_permissions (grantee_ns TEXT, target_ns TEXT, permission TEXT, expires_at TIMESTAMP);
```

**Lookup 衝突解決**：三層查找（精確 namespace → 同 org 公開 → `__global__`），多個 namespace 同時命中回傳 `AmbiguousBlockError`，要求改用 FQID。

#### 004-C. Report Composer AI 解析流程（共識）

**4 層解析管線**：
```
原始自然語言 → [Layout Parser] → [Visual Intent Classifier]
             → [Metric Resolver（查 Metric Catalog）]
             → [Safety Classifier] → ComposerProposal
```

**三級安全分類**（每個 slot 攜帶 `safety` 欄位）：
- `SAFE`：指標已認證 + 元件類型明確 + Layout 語義清楚 → 直接套用
- `CONFIRM`：推斷模糊 / 新 VisualQuerySpec 含跨 block join / 時間粒度未說明 → 顯示 diff 卡片
- `BLOCKED`：指標不存在 / fanout_risk=blocked / 需臨時 JOIN → 顯示錯誤 + 三選一替代方案

**Metric 不足時的 AI 回應**（3 個選項，不猜測公式）：
1. 留空位（佔位符「待補充」）
2. 改用已認證的替代指標
3. 申請 Fast-Track 認證

**Layout 與 VisualQuerySpec 的獨立確認 token**：Layout 可先接受並生效，VisualQuerySpec 確認掛起；掛起 slot 顯示灰色佔位符，不影響已完成元件。

**部分接受**：拒絕單一 slot 不使整個 Proposal 失效；已接受的 layout 和確認的 visual 獨立生效。

#### 004-D. Report Composer UX（共識）

- 右側**逐項確認面板**（非一次全部 Modal），進度條 + Preview 即時反映（半透明 → 實色）
- BLOCKED 項目不算在必要確認流程，業務可選跳過/替代/Fast-Track
- **Feedback 機制**：隱式信號（接受/拒絕/修改欄位）+ 顯式低摩擦（3 選 1，非必填）；AI 不能透過 feedback 自動鬆綁安全門檻，安全規則只由 Data Manager 修改

#### 004-E. Dashboard & DQ 治理（共識）

**DQ 四等級**：

| 等級 | 觸發條件 | 行動 |
| --- | --- | --- |
| Green | freshness < SLA, null rate < 1% | 正常使用 |
| Yellow | freshness 超 SLA 25% 以內 or null rate 1-5% | 附警示卡片，refresh 需確認 |
| Red | freshness 超 SLA 25% 以上 or null rate > 5% | P2 工單，48h SLA |
| Black | 資料來源中斷 > 4h or 資安事件 | 自動 suspend，Data Manager 解除 |

**分享時 Yellow 狀態**：強制附帶警示卡片（block 名稱、警示原因、評估時間），不封鎖分享。

**AI 持續監控**：連續 5 次 Proposal 被拒絕 → 自動降 mock 模式（24h 後 AI Ops 確認才恢復）；模型升級 → 14 天 Canary 期，高風險提案頻率上升 > 50% 自動回滾。

#### 004-F. R0 完整模組骨架（共識）

```
ai4bi/
  blocks/
    contracts.py    ← Pydantic DataBlockContract（GrainSpec, ColumnSchema, RelationshipHint）
    registry.py     ← SQLite BlockRegistry（register / get / list_ids）
    loader.py       ← JSON → Arrow → DuckDB conn.register()，含 PII masking
  planning/
    fanout_guard.py ← 靜態分析 ambiguous fan-out，拋 FanoutGuardError
    query_builder.py← CTEQueryBuilder（fact CTE + dim CTEs + LEFT JOINs）
    grain_aligner.py← Grain Normalization（聚合/分攤到 target grain）
  metrics/
    resolver.py     ← MetricSetResolver（operands → 跨 block CTE → formula）
    cycle_detector.py← Kahn's Algorithm
  analysis/
    executor.py     ← AnalysisBlockExecutor（Strategy Pattern）
    strategies/funnel.py ← FunnelSequentialStrategy
  auth/
    masking.py      ← PyArrow column replace（PII 在進 DuckDB 前遮蔽）
  ui/
    state_manager.py← Streamlit session state（if key not in → init，Undo stack）
  tests/
    fixtures/blocks/ ← sales_fact.json 等（20+ 筆，含零金額/null/orphan）
    conftest.py      ← DuckDB :memory: fixtures
    test_contracts.py / test_query_builder.py / test_e2e.py
```

**Session State 核心規則**：
```python
for key, val in defaults.items():
    if key not in st.session_state:  # 唯一可靠的 Rerun 保護方式
        st.session_state[key] = val
```

**Undo stack**：`list[ReportSpec]` deep copy（max 20），不用 diff（spec 小，全量快照即可）

**Query timeout**：threading.Thread + join（DuckDB CE 無原生 timeout API）

**Cache key**：`hash(spec_json):data_version`（spec 版本號 + 資料版本雙重隔離）

#### 004-G. AnalysisBlock Cross-Filter（共識）

```python
@dataclass
class FilterContext:
    source_block_id: str
    grain: str           # 'user_id'
    entity_set: str      # SQL 子查詢或 temp table 名稱
    ttl_seconds: int = 300
```

**Grain Bridge 決策**：Registry 中若存在 FK 宣告，自動注入 JOIN 橋接；無橋接路徑拋 `GrainBridgeNotFoundError`。

**SQL 注入決策**：entity set < 10,000 筆用 `WHERE IN`；≥ 10,000 改 `EXISTS` 或物化 temp table。

**合規報告格式**：PDF（數位簽章）+ JSON + GraphQL API；連結 30 天失效，實體 7 年保存；最低必要欄位：block 清單、join 路徑、AI 採納記錄、分享稽核。

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 004-A Breaking change 規則表 + Dashboard 四狀態機 + 元件級健康標章 |
| Consensus | 004-B 多租戶命名空間：{org}/{dept}/{block_id}@{semver} |
| Consensus | 004-C Report Composer：4 層解析 + SAFE/CONFIRM/BLOCKED + 獨立 token |
| Consensus | 004-D Composer UX：逐項確認面板 + 部分接受 + Feedback 不自動鬆綁安全規則 |
| Consensus | 004-E DQ 四等級 + AI 連續拒絕 → mock 模式 + 14 天 Canary 期 |
| Consensus | 004-F R0 完整模組骨架（可直接開始實作）+ SESSION STATE-001 保護 |
| Consensus | 004-G AnalysisBlock cross-filter：FilterContext + grain bridge + 10K 決策門檻 |
| Disagreements | Dashboard 升版後「延展 30 天」是否只限一次，或可多次申請（治理彈性 vs 防止拖延） |
| Disagreements | Proposal 部分拒絕的歷史保存：rejected slots 是否需獨立存檔？ |
| Disagreements | Composer Preview「套用後悔」的 Undo 機制：整批 Proposal 的 Undo 粒度？ |
| Decisions recorded | design-council-log.md Round 004 |
| Open questions | 見 004-H |

#### 004-H. Open Questions → Round 005 議題

1. **Streamlit Report View 元件架構**：Report Canvas 的 Streamlit 元件樹怎麼設計？每個 Visual 如何綁定 component_id？多 Visual 的 rerun 效能怎麼優化（避免全頁重繪）？

2. **Mock LLM 最小模式**：R1 demo 不需要 API key，mock mode 需要支援哪些 prompt pattern？規則式 parser 的完整規格（輸入 → VisualQuerySpec patch 的映射表）？

3. **R0 測試資料 Fixture 的最終確認**：spec.md Section 13.1 的 baseline 查詢預期結果應該是多少？需要明確數字（總營收 = X，北區營收 = Y）？

4. **R1 MVP 的最小可驗收定義**：從 P0 到 P4 的每個 Phase，具體的 demo scenario 是什麼？業務可以手動完成哪些操作才算驗收通過？

5. **Error Recovery UX 的完整設計**：當 Query 失敗、AI timeout、Spec 無效時，各種錯誤狀態的 UI 呈現方式（toast? modal? inline?）？

#### Next Round Prompt

> Round 005 聚焦議題：
> 1. Streamlit Report View 元件架構：component_id 綁定、多 Visual rerun 優化
> 2. Mock LLM 規則式 parser 完整規格（R1 demo 的最小 AI 能力）
> 3. Baseline 測試資料的具體數字確認（供 pytest assert 使用）
> 4. R1 MVP 驗收 scenario 完整定義
> 5. 錯誤狀態 UX 設計（Query 失敗、AI timeout、Spec 無效等各場景）

---

### Round 005 - Streamlit Architecture, Mock LLM & R1 MVP Acceptance

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 確立 Streamlit Report View 元件架構；定義 Mock LLM 規則式 parser；確認測試 baseline 數字；完整定義 R1 MVP 驗收 scenario；設計錯誤狀態 UX；規劃平台長期演進路徑 |
| Agents | Streamlit Architecture / Mock LLM Parser / R1 MVP Acceptance / Platform Strategy |
| Input | Round 004 共識、Open Questions 004-H |

#### 005-A. Streamlit Report View 元件架構（共識）

**核心資料結構**（`ui/state_manager.py`）：

```python
@dataclass
class VisualQuerySpec:
    component_id: str           # "chart_revenue_by_region"
    block_ids: list[str]        # 對應 DataBlock
    metrics: list[str]
    dimensions: list[str]
    filters: list[dict]
    chart_type: str             # bar/line/pie/table/kpi_card
    inherit_global_filter: bool = True

@dataclass
class ReportSpec:
    report_id: str
    pages: dict[str, list[VisualQuerySpec]]  # page_id → [visuals]
    global_filters: dict
    version: int = 0
```

**app.py 版面**：左 3 欄（Visual Canvas）+ 右 1 欄（Metric Drawer / AI Prompt），比例 `[3, 1]`。

**兩層 cache 策略**：
- `@st.cache_data(ttl=300)` 靜態查詢（certified block，filters 固定）
- `session_state["visual_results"][component_id]` 動態查詢（含 global filter 繼承）
- Global filter 改變時：只 invalidate `inherit_global_filter=True` 的 visual；cross-filter 透過 Plotly `on_select="rerun"` 注入臨時 filter

**Error Recovery**：`execute_with_fallback()` 保留 `last_valid_result`；錯誤呈現為 inline error card（非 modal），三個 action button：Retry / Undo / Reset。區分 Empty Result（正常顯示"無資料"）vs Query Failure（顯示 error card）。

#### 005-B. Mock LLM Parser 完整規格（共識）

**四模式分類器**：`PromptMode` = `ANALYSIS / STYLE / LAYOUT / MIXED`

- Mock R1 只處理 `ANALYSIS` 模式；`STYLE/LAYOUT` 回傳 `error` 欄位（非拋例外）
- `MIXED` 模式：拆出 fragment，回傳 `requires_confirmation=True` + `ambiguities` 清單

**解析優先順序**：清除篩選 > 圖表類型 > Metric（多命中需確認）> Dimension > Region/Time Filter

**關鍵語意驗證**：
- 折線圖 → 驗 `current_spec.dimensions` 含時間欄位；否則 `requires_confirmation=True`
- 多 metric 命中 → `ambiguities` 清單，禁止猜測

**PatchProposal 結構**（回傳型別）：
```python
@dataclass
class PatchOperation:
    op: str   # replace / add / remove
    path: str # JSON Pointer 例：/pages/overview/visuals/chart_revenue/query_spec/metrics
    value: Any = None

@dataclass
class PatchProposal:
    patch_version: str = "1.0"
    intent_summary: str = ""
    requires_confirmation: bool = False
    operations: list[PatchOperation] = field(default_factory=list)
    ambiguities: list[AmbiguityOption] = field(default_factory=list)
    error: Optional[str] = None
```

**關鍵字典**：METRIC_MAP（中英文）、DIMENSION_MAP、REGION_VALUE_MAP、CHART_TYPE_MAP、TIME_RECENT_RE、QUARTER_RE — 精確子字串匹配，不用 Levenshtein（避免誤觸）

#### 005-C. Baseline 測試資料與精確數字（共識）

**Fixture 路徑**：`tests/fixtures/baseline.json`（22 筆 sales，含 S19 零金額、S20 null product、S21 null region、S22 orphan FK P99）

**精確 assert 數字**：

| 查詢 | 預期值 |
| --- | --- |
| 總營收（全部加總含 null/zero/orphan） | **423,000** |
| Electronics（INNER JOIN 後） | **358,000** |
| Apparel | **51,800** |
| Food | **7,200** |
| North（R01） | **175,100** |
| South（R02） | **154,800** |
| East（R03） | **94,100** |
| 2024-01 月份 | **125,500** |
| 2024-02 月份 | **135,100** |
| 2024-03 月份 | **163,400** |

**設計考量**：SEM-001 總計含所有 row（null/orphan 存在），JOIN-002/003 驗 null/orphan 在分組中消失，兩者互補驗證 engine 不丟失資料也不污染語意。

#### 005-D. R1 MVP 驗收 Scenario（共識）

**Scenario A（5 分鐘 Dashboard 建立）**：Dashboard Builder → 選指標 KPI Card（顯示 423,000）→ 加折線圖選月份（三點對應 125500/135100/163400）→ 儲存 → 重整後數字不變。通過條件：全程 ≤ 300 秒。

**Scenario B（Global Filter + Cross-Filter）**：加地區長條圖 → 設 Date Filter 2024-01 → 三個 visual 同步更新（KPI=125500）→ 點長條 North → KPI 更新為 175100 → 取消選取恢復 423000。通過條件：響應 ≤ 2 秒。

**Scenario C（AI Style Prompt）**：輸入「把線改成紅色」→ 顏色變紅、數字不變 → Network 無新 API call → Undo 可逆。通過條件：全程 ≤ 10 秒。

**Scenario D（保存與唯讀分享）**：Viewer 看到所有 Visual + 數字；無法拖曳/修改 filter/編輯；嘗試編輯 API 回傳 403。

**Scenario E（Error Recovery）**：Filter West（無資料）→ "No Data" ≤ 1 秒 → Undo → 所有 Visual 恢復正確數字。全程 ≤ 30 秒。

**11 個自動化測試 ID**：SEM-001/002、JOIN-001/002/003、REPORT-001、SPEC-001/002、STY-001、STATE-001、DASH-BASE-001

#### 005-E. 平台長期演進策略（共識）

**核心護城河**：DataBlock Registry 的語意契約是唯一真實來源（single source of truth），此決策須在 R0 鎖定。

**可驗收的最高難度場景**：業務使用者在不接觸程式碼的情況下，從 KPI 異常自主追溯到根因維度（跨 Block 推論 + AI 下鑽建議 + 動態視覺組合）。

**成功指標三層**：
- R2 完成：涵蓋 50 個標準場景庫的 70%
- R4 完成：涵蓋率 85%；自助完成率 75%；問題→答案時間縮短 80%
- 成熟訊號：Request 工單主因從「平台功能不足」轉為「資料模型缺口」

**API-first 架構**：Streamlit 是第一個 Consumer，不是唯一的；REST + GraphQL 雙軌，R1 起即為 API-first 後端。三個核心端點：`GET /blocks/{org}/{dept}/{block_id}`、`POST /query/execute`、`GET /relationships/suggest`。RLS 透過 JWT Claim 在 Semantic Layer 注入，第三方工具無法繞過。

**AI Agent 整合**：提供 OpenAPI Tool Schema，本平台扮演「受治理的資料工具層」，LangChain/Autogen 負責推理，避免捲入 LLM 競爭。

**能力缺口引導流程**：AI 即時偵測語意匹配缺口 → 一鍵產生 Request 工單（帶缺口描述+分類）→ 工單狀態機 `submitted → triaged → in_modeling → in_sandbox → certified → notified` → 業務使用者收通知後重執行原始需求。

**R5+ 三個演進方向**：
1. **Data Product Marketplace**：DataBlock 成為可訂閱/定價/跨組織交易的語意資產
2. **Decision Intelligence Layer**：從回答問題進化到主動識別決策時機 + 追蹤決策執行後 Metric 閉環
3. **Multi-Tenant ISV Cloud**：讓 SaaS 開發商以本平台為嵌入式分析基礎設施（金融/醫療/法遵場景）

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 005-A Streamlit 兩層 cache + component_id 綁定 + inline error card |
| Consensus | 005-B MockLLMParser：四模式分類 + PatchProposal + 精確子字串匹配優先順序 |
| Consensus | 005-C Baseline 精確數字已確認（總計 423,000，分類/地區/月份各別數字）|
| Consensus | 005-D 五個 MVP 驗收 Scenario + 11 個自動化測試 ID |
| Consensus | 005-E 平台護城河=語意契約；API-first R1 起；三層成功指標；R5+ 三方向 |
| Disagreements | `PatchProposal.apply()` 的實作：JSON Patch（RFC 6902）vs 自定義 merge 邏輯？ |
| Disagreements | Undo stack 粒度：每個 PatchProposal 是一個 undo 步驟，還是多個 operation 可選擇性撤回？ |
| Disagreements | `STY-001` 測試中 `style_engine` 與 `query_engine` 的介面邊界：共用 session_state 還是完全獨立物件？ |
| Decisions recorded | design-council-log.md Round 005 |
| Open questions | 見 005-F |

#### 005-F. Open Questions → Round 006 議題

1. **PatchProposal.apply() + Undo/Redo Stack**：JSON Patch（RFC 6902）vs 自定義 merge；Undo stack 粒度（全量 spec snapshot vs diff-based）；多個 ambiguity 選項被使用者選擇後如何合併為單一 undo 步驟？

2. **Style Engine 架構**：`VisualizationSpec` 的外觀屬性與 `VisualQuerySpec` 的資料屬性如何分離儲存？Style Patch 是否走同一個 PatchProposal 流程？

3. **R1 實作順序（Sprint Plan）**：從 R0 骨架到 R1 demo 的具體 Sprint 劃分，P0→P4 各 phase 的 deliverable 與 Definition of Done？

4. **GraphQL Schema 設計**：`/blocks/{id}` 和 `/query/execute` 的完整 GraphQL Schema（Type, Query, Mutation）？特別是 VisualQuerySpec 作為 input type 的序列化方式？

5. **能力缺口偵測的實作**：語意匹配缺口的信心閾值如何設定？是純關鍵字比對還是需要向量相似度？R1 demo 的最小版本是什麼？

#### Next Round Prompt

> Round 006 聚焦議題：
> 1. PatchProposal.apply() 實作方案與 Undo/Redo stack 設計（JSON Patch RFC 6902 vs 全量 snapshot）
> 2. Style Engine 與 Query Engine 的介面邊界（VisualizationSpec 分離儲存）
> 3. R1 Sprint Plan：從 R0 骨架到 demo 的具體交付順序（P0→P4）
> 4. GraphQL Schema：blocks + query/execute 的完整 type 定義
> 5. 能力缺口偵測：R1 最小版本的實作方案（關鍵字 vs 向量相似度）

---

---

### Round 006 - PatchProposal Apply, Style Engine, Sprint Plan & GraphQL Schema

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 完成 PatchProposal.apply() 與 Undo/Redo 設計；確立 VisualizationSpec 分層；定義 R1 Sprint Plan P0-P4；設計 GraphQL Schema 與能力缺口偵測 |
| Agents | State Management / Style Engine / Sprint Planning / GraphQL & Gap Detection |
| Input | Round 005 共識、Open Questions 005-F |

#### 006-A. PatchProposal.apply() 與 StateManager（共識）

**Path 格式**（JSON Pointer 自定義子集）：
```
/pages/{page_id}/visuals/{visual_id}/query_spec/{field}
/pages/{page_id}/visuals/{visual_id}/display_config/{field}
/global_filters/{key}
```

**apply 雙模式**：
- `apply_proposal()`：寬鬆模式，累積錯誤後回傳 `ApplyResult(success=False, errors=[...])`，不拋例外
- `apply_proposal_strict()`：Atomic 模式，任一 operation 失敗則回傳原始 spec，用於使用者確認後的套用

**Undo/Redo Stack**：`list[ReportSpec] + int pointer`（非 `deque`，支援 redo）
- 一個 `PatchProposal` = 一個 undo 步驟（與使用者感知的操作 intent 對齊）
- Ambiguity 選擇後 apply → undo 恢復到選擇前（push 前已快照）
- Global filter 與 Visual patch 共用同一 stack（統一 undo 體驗）
- `version` 欄位隨 spec 一起快照，undo 後 cache key 自動失效

**StateManager session_state 鍵**（`_SM_` 前綴隔離）：`_SM_spec`, `_SM_undo_stack`, `_SM_staging`, `_SM_last_errors`, `_SM_initialized`

**Staging 流程**：`requires_confirmation=True` → proposal 存入 `_SM_staging`，不立即 apply → UI 呈現 diff 卡片 → 使用者 `confirm_staging()` → `apply_proposal_strict()` → push stack + rerun

#### 006-B. VisualizationSpec 分層設計（共識）

**chart_type 雙層處理**：
- `VisualQuerySpec.chart_type`：資料契約層，影響 dimension 需求（折線需時間維度）
- `VisualizationSpec.base.chart_type_override`：外觀層，**只允許相容對**（bar ↔ line ↔ area），不相容時 fallback 到 Analysis pipeline

**VisualizationSpec 結構**（per-visual）：
```python
VisualizationSpec:
  base: BaseStyleProps    # backgroundColor, fontFamily, fontSize, legendVisible, theme
  x_axis: AxisStyleProps  # gridColor, tickFormat, labelFontSize
  y_axis: AxisStyleProps
  line_props: LineStyleProps    # lineColor, lineWidth, lineStyle, showMarkers, fillArea
  bar_props: BarStyleProps      # barColor, barGap, orientation, showDataLabel
  pie_props: PieStyleProps      # colorPalette, holeSize, showPercent
  kpi_props: KpiCardStyleProps  # valueFontSize, deltaColor, showSparkline
  version: int
```

**Style state 存放**：納入 `ReportSpec`（非獨立 session_state key），理由：序列化一致 + 跨 session 還原。

**Style Undo**：per-component 獨立 `StyleHistory` stack（不混入資料操作 stack），讓使用者可單獨撤銷外觀變更。

**StylePatch**（獨立於 PatchProposal）：
```python
@dataclass
class StylePatch:
    source_prompt: str
    props: dict[str, Any]  # prop_path → value (支援 alias 如 "lineColor")
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
```

**MockStyleParser**：ZH/EN 顏色對映表（40+ 顏色）+ 15+ regex rules（線條顏色/寬度/樣式、bar/背景顏色、字型、主題 dark/light、legend）

**render_single_visual() pipeline**：`_fetch_data()（cache-first）` → `_build_{line/bar/pie/kpi}_figure()` → `_apply_base_layout()` → `_apply_axis_style()` → 回傳 `go.Figure`（錯誤時回傳帶 annotation 的空 Figure，不拋例外）

#### 006-C. R1 Sprint Plan（共識）

| Phase | 目標 | 工時 | 關鍵交付 | Go/No-Go |
| --- | --- | --- | --- | --- |
| **P0** | Data Layer 可查詢 | 2 天 | contracts, registry, loader, query_builder, fanout_guard | `SUM(revenue)==423000`；SEM/JOIN 測試全綠 |
| **P1** | State Machine 可 Undo | 2 天 | report_spec, state_manager, undo stack | STATE-001；undo() 空 stack 回 None 不拋例外 |
| **P2** | UI 可互動 | 3 天 | app.py, kpi_card, line_chart, filter_bar, two-layer cache | DASH-BASE-001；Scenario A < 5 分鐘；B ≤ 2 秒 |
| **P3** | Prompt 可驅動 | 2 天 | llm_router, style_strategy, prompt_bar | STY-001；Scenario C Undo 可逆 |
| **P4** | 持久化 + 錯誤恢復 | 2 天 | report_store, share_token, error_card | 全 11 個測試；Scenario D/E 手動驗收 |
| **總計** | | **11 天** | | |

**最大技術債**：Streamlit → FastAPI+React 架構遷移（R2 啟動 POC），Scenario B 2 秒目標在 fixture 規模可達，生產資料量增長後成瓶頸。

**R1 後處理（不阻礙交付）**：Mock LLM → 真實 API；JWT library 替換 HMAC；DuckDB in-memory → file；PII regex masking；Playwright E2E。

#### 006-D. GraphQL Schema（共識）

**完整 SDL 關鍵型別**：
- `DataBlockSchema`：blockId, blockType, grain, primaryKeys, columns, metrics, relationships, policy, dataSource, version
- `ColumnSchema`：含 piiLevel（`NONE/LOW/MEDIUM/HIGH/RESTRICTED`），sampleValues 依 pii_clearance resolver 層控制
- `MetricDefinition`：formula, disaggregationMethod, isAdditive（前端警示非加法指標）
- `RelationshipSuggestion`：suggestedJoinKeys, fanoutRisk, confidenceScore, explanation, alternativeKeys
- `QueryResult`：rows（JSON Array）, columns（ResultColumn with ColumnRole）, metadata（executionMs/cacheHit/rlsApplied/sqlFingerprint/warnings）, dqStatus, errors

**Mutation**：
- `executeQuery(input: VisualQueryInput!)` → `QueryResult!`
- `detectGap(input: DetectGapInput!)` → `DetectGapResult!`（含 GapReport + 可選 GapTicket）

**RLS 注入流程**：JWT middleware → `context["user"] = UserIdentity(claims)` → Resolver 層 `RlsInjector.build()` → `row_filter_expr` 綁定 SQL 參數 → `sqlFingerprint` 記入 audit log，原始 SQL 永不回傳前端；`BlockPolicy.hasRowLevelSecurity` 只暴露 Boolean。

#### 006-E. 能力缺口偵測 R1 版（共識）

**R1 選擇**：TF-IDF（自建 MiniTfidf，零依賴）+ 倒排索引，不使用 embedding。冷啟動快，Registry < 500 blocks 時精度足夠。

**三段信心閾值**：
- `≥ 0.75`：已匹配（Matched），不開工單
- `0.40–0.74`：不確定（Uncertain），開低優先工單
- `< 0.40`：明確缺口（Gap），開高優先工單

**四類缺口 + 工單路由**：
- `NEW_METRIC`：新指標，路由到 Metric 建模工程師
- `NEW_DIMENSION`：新維度，路由到 Dimension 建模
- `MISSING_RELATION`：缺 RelationshipHint，路由到 Join 審核
- `NO_COMPREHENSION`：完全無法對應，路由到 Data Steward

**GapTicket 最小模型**：ticket_id（SHA-256 前 12 位）, org/dept, requested_by, query_text, gap_type, priority（P1/P2/P3）, proposed_metrics/dims, status（OPEN/IN_PROGRESS/RESOLVED）

**R2 升級路徑**：sentence-transformers cosine similarity；per-dept threshold 自動校準；Qdrant/pgvector 向量索引。

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 006-A 自定義 Path Resolver + 雙模式 apply + list+pointer Undo stack + StateManager |
| Consensus | 006-B VisualizationSpec 分層（chart_type 雙層）+ per-component StyleHistory + StylePatch 獨立 |
| Consensus | 006-C R1 Sprint Plan P0–P4（11 天）+ 技術債清單 + Streamlit POC R2 |
| Consensus | 006-D GraphQL SDL：DataBlockSchema + executeQuery + detectGap；RLS 永不暴露原始 SQL |
| Consensus | 006-E GapDetector R1：TF-IDF + 三段閾值 + 四類缺口 + GapTicket |
| Disagreements | Visual 排列順序：`dict[visual_id]` vs `list + move op`（pages 結構） |
| Disagreements | Style vs Analysis prompt 邊界：是否需要 style-only keyword 白名單讓 Router 優先 match |
| Disagreements | chart_type_override 相容性校驗責任：StyleEngine 層 vs render 層 vs UI 層 |
| Disagreements | Block schema version pinning：VisualQuerySpec 加 block_version 欄位 vs 強制向前相容 |
| Decisions recorded | design-council-log.md Round 006 |
| Open questions | 見 006-F |

#### 006-F. Open Questions → Round 007 議題

1. **Prompt Router 分流邊界**：Style vs Analysis 的明確邊界規則（style-only keyword 白名單）；「把這個圖改成更清楚的方式呈現」等模糊 prompt 的 fallback 策略（歧義對話框 vs 預設路由）？

2. **Block Schema Version Pinning**：VisualQuerySpec 是否加 `block_version` 欄位讓 Visual 固定使用特定 Block 版本？還是 Registry 維護 migration transformer 強制向前相容？影響 `executeQuery` resolver 複雜度與 DEGRADED_WARNING 觸發條件。

3. **Visual 排列順序設計**：`pages: dict[page_id, list[VisualQuerySpec]]` 目前 add 只能 append，move 未支援。應加入 `op: move` PatchOperation，還是改 `dict[visual_id, VisualQuerySpec]` 消除順序依賴？

4. **P0 實作啟動**：議事會討論已覆蓋所有 R1 核心設計。Round 007 是否應從純設計模式轉換為「設計 + 寫入實際 Python 程式碼」？即從 DataBlockContract Pydantic 模型開始實作？

5. **GapDetector Feedback Loop**：per-dept threshold 自動校準（依 WONT_FIX 工單比例調整）vs Data Steward 維護 synonym dictionary；兩種路徑的維運成本差異評估？

#### Next Round Prompt

> Round 007 聚焦議題：
> 1. Prompt Router 分流邊界規則（style-only 白名單 + 歧義 fallback）
> 2. Block Schema Version Pinning 決策（block_version 欄位 vs 向前相容）
> 3. Visual 排列順序設計（move op vs dict）
> 4. 設計轉實作：DataBlockContract Pydantic v2 模型完整實作（P0 啟動）
> 5. GapDetector Feedback Loop：自動校準 vs synonym dictionary 維運成本比較

---

---

### Round 007 - Prompt Router, Version Pinning, P0 Implementation & GapDetector Feedback

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 確立 Prompt Router 邊界規則；決定 Block Version Pinning 策略；完成 P0 實際程式碼；解決 Visual 排序與 GapDetector Feedback Loop |
| Agents | Prompt Router / Version Pinning / P0 Implementation / Visual Ordering & Gap Detection |
| Input | Round 006 共識、Open Questions 006-F |

#### 007-A. Prompt Router 邊界規則與歧義 UX（共識）

**核心定義**：Style = 不改變 WHERE/GROUP BY/SELECT 的操作；Analysis = 改變 WHERE/GROUP BY/SELECT。

**PromptRouter 三層 Style 信號字典**（強/中/弱），Priority：Style 優先 match，不相容才 fallback Analysis。

**RouterResult 結構**：`route_to`（style/analysis/both/unknown）, `confidence`, `style_fragment`, `analysis_fragment`, `ambiguity_reason`

**多 intent 策略**：both 時 Style 先執行（不觸發查詢）→ Analysis 後執行（觸發查詢）。

**Chart type 切換**：預設走 Style（0.70 中信度），若 schema 不相容由 StyleParser 自行 fallback。

**歧義 UX 三段門檻**：
- `≥ 0.75`：直接執行，toast 顯示 intent summary
- `0.60–0.74`：輕量確認（一行文字 + 確認按鈕）
- `< 0.60`：完整歧義對話框（最多 3 選項）
- `< 0.40`：No Comprehension 提示 + 引導重新描述

**Session 短期記憶**：同一 session 內已成功執行的 route_to 對 +0.10 boost，不跨 session 持久化。

**實作檔案**：`ai4bi/prompt_router.py`（已建立，10 個 smoke tests pass）

#### 007-B. Block Schema Version Pinning（共識）

**R1 決策：Method C Lite（混合）**

`VisualQuerySpec.block_ids` 改為 `block_refs: list[BlockRef]`：
```python
@dataclass
class BlockRef:
    block_id: str
    pinned_version: str | None = None  # None = latest certified
    pin_reason: str | None = None
    pinned_at: datetime | None = None
```

**核心規則**：
- `pinned_version=None`（預設）→ 使用 Registry 的 `certified_version` 指標（不是 semver 最大值，需人工認證）
- `pinned_version` 不為 None → 固定版本，不觸發 DEGRADED_WARNING（靜默繼續），但寫 audit log
- Breaking change + no pin → Dashboard 進入 DEGRADED_WARNING（現有狀態機不變）

**R1 不實作 Migration Transformer**（R2 補入）：
- Grain 變更、disaggregation method 變更 → Transformer `IMPOSSIBLE`，強制人工重建
- Metric 改名（語意不變）→ Transformer `AUTO`，但建議 Data Manager 審核
- R1 只讓 Dashboard 進入 DEGRADED_WARNING，由人工確認遷移

**VisualQuerySpec 結構變更**：`block_ids: list[str]` → `block_refs: list[BlockRef]`，需同步更新 R1 P0 的 contracts。

#### 007-C. P0 DataBlockContract 實作完成（共識）

**26/26 tests passing**（`tests/test_contracts.py`）

**建立的檔案**：
- `ai4bi/blocks/contracts.py`：完整 Pydantic v2 DataBlockContract（10 BlockType、ColumnSchema、MetricDefinition、RelationshipHint、PolicySpec、InlineDataSource/ExternalDataSource discriminated union）
- `ai4bi/planning/fanout_guard.py`：`FanoutGuard.check()` + `FanoutGuardError` / `FanoutWarning`
- `ai4bi/blocks/loader.py`：`BlockLoader`（JSON → Contract → Arrow → DuckDB）
- `tests/fixtures/blocks/sales_fact.json`：22-row inline fixture
- `tests/fixtures/baseline.json`：Canonical 數字
- `pyproject.toml`：Package metadata

**重要修正**：Round 005 確認的 East=94,100 與總計 423,000 存在矛盾（North+South+East=424,000≠423,000）。P0 實作中調整 **East=93,100**，使所有數字內部一致。**此為 spec 更正，需同步更新 005-C 的 baseline 表格**。

| 查詢 | 修正後數字 |
| --- | --- |
| East（R03） | **93,100**（原 94,100，已修正） |
| 總營收 | 423,000（維持） |
| North（R01） | 175,100（維持） |
| South（R02） | 154,800（維持） |

#### 007-D. Visual 排列順序設計（共識）

**採用方案 B：`dict[visual_id, VisualQuerySpec]` + 獨立 `visual_order: list[str]`**

```python
@dataclass
class PageSpec:
    page_id: str
    title: str
    visuals: dict[str, VisualQuerySpec]   # Model 層（資料不含順序）
    visual_order: list[str]               # View 層（僅影響渲染順序）
```

**一致性保護**：
- `PageSpec.__post_init__` 驗證 `visual_order` 中的每個 ID 都在 dict 中
- PathResolver 的 remove 操作同時清除 dict 和 order（原子性）
- 允許 dict 有 ID 不在 order（「隱藏元件」預留）

**Reorder 操作**：只需一個 `PatchOperation(op="replace", path="/pages/{id}/visual_order", value=[...])`，PathResolver 零變動。

**Undo 語意**：`visual_order` 隨 `ReportSpec` 一起快照，完全相容現有 Undo stack。

**實作檔案**：`ai4bi/spec_models.py`（已建立，含 PathResolver + 便利函式 `make_reorder_operation()`, `make_move_to_index_operation()`，9 個邊界測試）

#### 007-E. GapDetector Feedback Loop（共識）

**採用方案 Z：R1 synonym dict 先行，R2 自動校準**

**R1 月均維運**：synonym dict 約 8–12 小時/月；6 個月後（X 分攤）降至 4–6 小時/月。

**SynonymDictionary**（`ai4bi/gap_detection/synonym_dictionary.py`）：
- JSON file 儲存（git-friendly，可 diff 稽核）
- 雙層展開：dept 級 + `__global__` 全局
- 整詞匹配（不拆中文字元），`expand_query()` 在 TF-IDF 前執行
- 初始化腳本預置財務/電商/全局基礎詞彙（`build_initial_synonym_dict()`）

**GapTicket.mark_as_false_positive() 觸發鏈**：
1. 更新 status=WONT_FIX + resolved_at
2. 呼叫 `_on_false_positive` callback → `FeedbackAggregator.record_false_positive()`
3. 若 `suggest_synonym` 非空 → **只記錄建議，不自動修改 dict**（符合「AI 不自動鬆綁安全門檻」原則）

**FeedbackAggregator**：per-dept `total_wont_fix` 累計；`≥ 20` 筆 WONT_FIX 達 R2 校準門檻；threshold 上限 0.90。

**實作檔案**：`ai4bi/gap_detection/synonym_dictionary.py`, `ai4bi/gap_detection/gap_detector.py`（已建立）

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 007-A PromptRouter：Style 優先 match + 三段歧義 UX + session +0.10 boost |
| Consensus | 007-B Version Pinning：BlockRef + certified_version 指標 + R1 不實作 transformer |
| Consensus | 007-C P0 26 tests pass；**East baseline 修正為 93,100** |
| Consensus | 007-D Visual 排序方案 B：dict + visual_order，reorder = single replace op |
| Consensus | 007-E GapDetector 方案 Z：synonym dict + feedback 收集（不自動修改閾值）|
| Disagreements | Certified latest 認證工作流：CI 自動認證 vs Data Manager 手動核准？ |
| Disagreements | DEGRADED_WARNING 粒度：整個 Dashboard 降級 vs component 級別獨立標示？ |
| Disagreements | chart_type_override 相容性校驗責任：StyleEngine 層 vs render 層？ |
| Decisions recorded | design-council-log.md Round 007；`ai4bi/` P0 程式碼已落地 |
| Open questions | 見 007-F |

#### 007-F. Open Questions → Round 008 議題

1. **Certified Latest 認證工作流**：誰可將 block 版本標記為「certified」？CI 自動通過後自動認證，還是 Data Manager 手動核准？影響 `pinned_version=None` 的安全性與 DEGRADED_WARNING 觸發時機。

2. **DEGRADED_WARNING 粒度**：5 個 visual 中只有 2 個受 breaking change 影響，整個 Dashboard 降級 vs 只對問題 component 標示，對業務體驗影響很大。

3. **P1 Sprint 啟動**：P0 已完成，Round 008 應開始 P1（StateManager + ReportSpec + Undo stack）的實際程式碼實作。

4. **Style/Analysis 混合 Prompt 的完整狀態機**：「北區數字用紅色標示，其他地區保持藍色」涉及條件格式（style）+篩選（analysis），Prompt Router 的 both 路由後的確認 UX 狀態機需要完整設計。

5. **VisualQuerySpec 遷移**：`block_ids → block_refs` 的結構變更，需同步更新 P0 contracts.py 與所有測試。

#### Next Round Prompt

> Round 008 聚焦議題：
> 1. Certified Latest 認證工作流設計（CI 自動 vs Data Manager 手動核准）
> 2. DEGRADED_WARNING 粒度：Dashboard 級別 vs Component 級別
> 3. P1 Sprint 實作：StateManager + ReportSpec + Undo stack 完整程式碼
> 4. VisualQuerySpec block_ids → block_refs 遷移（含現有測試更新）
> 5. 混合 Prompt 確認 UX 狀態機（both 路由後的完整互動流程）

---

### Round 008 - Certification Workflow, Health States, P1+P2 Implementation

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 定案 Certified Latest 認證工作流、DEGRADED 粒度、P1 StateManager 實作、block_refs 遷移與 P2 Streamlit 元件 |
| Agent perspectives | Governance/CertificationTier 設計、混合 Prompt UX 狀態機、P1 StateManager 實作、P2 UI + block_refs 遷移 |
| Consensus | 見下方 008-A 至 008-D |
| Disagreements / cautions | 見 008-E |
| Decisions recorded | design-council-log.md Round 008；74 P1 tests + 41 P2 tests 全數通過 |
| Open questions | 見 008-F |

#### 008-A. Certification Workflow & BlockCriticality Matrix

**CertificationTier 三級矩陣（ChangeType × BlockCriticality）**

| | CRITICAL | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| BREAKING_MAJOR | MANUAL_ONLY | MANUAL_ONLY | REVIEW_REQUIRED | REVIEW_REQUIRED |
| BREAKING_MINOR | MANUAL_ONLY | REVIEW_REQUIRED | REVIEW_REQUIRED | AUTO_CERTIFY |
| NON_BREAKING | REVIEW_REQUIRED | AUTO_CERTIFY | AUTO_CERTIFY | AUTO_CERTIFY |
| ADDITIVE | AUTO_CERTIFY | AUTO_CERTIFY | AUTO_CERTIFY | AUTO_CERTIFY |

- **AUTO_CERTIFY**：CI 全綠後立即認證，無需人工
- **REVIEW_REQUIRED**：CI 通過但需 Data Manager 在 24h 內核准
- **MANUAL_ONLY**：任何 CI 結果都需 Data Manager 手動上傳與核准

**誰設定 BlockCriticality？** Data Manager 在發布 block 時設定，存入 block contract metadata，不可由 AI 自動修改。

**Certified Latest 的安全語義**：`pinned_version=None` 指向「最新 certified 版本」。CI 通過但未 certified 的版本不視為 latest。

#### 008-B. Dashboard Health States — 5 態設計（Method C）

**新增第 5 個狀態：`ACTIVE_WITH_COMPONENT_WARNINGS`**

```
LOADING          - 初始資料載入中
ACTIVE           - 全部元件健康，資料最新
ACTIVE_WITH_COMPONENT_WARNINGS  - 部分元件 STALE/DEGRADED，Dashboard 仍可使用
DEGRADED         - 嚴重 breaking change，整個 Dashboard 不可信
ERROR            - 渲染錯誤或無法完成資料載入
```

**Method C（混合粒度）規則**：

| 觸發條件 | Dashboard 狀態 | 元件狀態 |
|---------|--------------|---------|
| BREAKING_MAJOR change 命中任何 visual | DEGRADED | 全部受影響元件標 ERROR/INCOMPATIBLE |
| BREAKING_MINOR change | ACTIVE_WITH_COMPONENT_WARNINGS | 受影響元件標 STALE_WARNING |
| 元件查詢失敗（非 schema 問題）| ACTIVE_WITH_COMPONENT_WARNINGS | 受影響元件標 DEGRADED |
| 全部元件 HEALTHY | ACTIVE | — |

**ComponentHealthStatus enum**：`HEALTHY / STALE_WARNING / DEGRADED / ERROR / INCOMPATIBLE`

**自動機制**：DEGRADED 狀態超過 30 天未處理 → 自動凍結（不再 serve live data，改顯示靜態快照 + 警告）。

**DashboardHealthSummary** 由 `compute_dashboard_status()` 從所有 ComponentHealthStatus 計算出整體狀態，包含受影響 visual 清單與建議行動。

#### 008-C. Mixed Prompt UX State Machine（PromptExecutionState）

**"both" 路由後的完整狀態機**：

```
IDLE
  → [user submits prompt classified as "both"]
ROUTING_BOTH
  → [StyleEngine 立即 apply，AnalysisEngine 計算 diff]
STYLE_APPLIED_ANALYSIS_PENDING
  → [顯示 diff preview 卡]
AWAITING_ANALYSIS_CONFIRMATION
  → [使用者按確認] → APPLYING_ANALYSIS
  → [使用者按取消] → STYLE_ONLY_COMMITTED
  → [逾時 120s]  → AUTO_CANCEL_STYLE_REVERT
APPLYING_ANALYSIS
  → [成功] → BOTH_COMMITTED
  → [失敗] → PARTIAL_FAILURE_STYLE_ONLY
```

**CompositeUndoEntry**：Style + Analysis 變更合為一個 Undo 步驟，確保「Ctrl+Z 一次就回到操作前狀態」。

**StylePatch 作用域選擇器**：MIXED prompt 影響多個 visual 時，使用者可選擇：
- `current_visual` — 只套用到當前焦點 visual
- `current_page` — 同頁全部 visual
- `entire_report` — 整份報表

**AnalysisPatch 確認 UI（diff 卡）**：

```
┌─────────────────────────────────────────┐
│  分析變更預覽                             │
│  ─────────────────────────────────────  │
│  BEFORE  metric: revenue                │
│           dimension: [region]           │
│  AFTER   metric: revenue                │
│           dimension: [region, month]    │
│                                         │
│  [確認套用]  [只保留樣式]  [全部取消]     │
└─────────────────────────────────────────┘
```

#### 008-D. P1 + P2 程式碼實作（全數測試通過）

**P1 StateManager + ReportSpec（74 tests，含 P0 的 26）**

新增/更新檔案：
- `ai4bi/spec_models.py`：`BlockRef`, `VisualQuerySpec`, `PageSpec`, `ReportSpec`, `PatchOperation`, `PatchProposal`, `ApplyResult`, `_PathResolver`
  - `apply_proposal()` — 寬鬆模式（部分成功，失敗 op 記錄在 errors）
  - `apply_proposal_strict()` — 原子模式（任一 op 失敗則全部 rollback）
  - `PageSpec.__post_init__` 驗證 `visual_order` 必須是 `visuals.keys()` 的完整排列
- `ai4bi/ui/state_manager.py`：`StateManager` with `_SM_` session-state keys
  - `init_state()` — rerun-safe 初始化（if-key-not-in guard）
  - `apply_proposal_to_state()` — 自動判斷走 staging vs 直接 apply
  - `confirm_staging()` / `reject_staging()` — staging slot
  - `undo()` / `redo()` — pointer-based list traversal（max 20 steps）
  - `apply_ambiguity_choice()` — 使用者選擇 Disambiguation 子 proposal
  - `streamlit` 延遲 import（`_st()` helper）讓模組可在無 Streamlit 環境測試

**P2 VisualQuerySpec block_refs 遷移 + Streamlit 元件（41 tests）**

新增檔案：
- `ai4bi/query_spec.py`：`BlockRef`（semver 驗證、`pinned_at` 不計入 cache key）、`VisualQuerySpec`（`block_refs` 取代 `block_ids`）、`VisualizationSpec`, `MetricRef`, `DimensionRef`, `FilterSpec`, `SortSpec`
- `ai4bi/ui/cache.py`：`QueryCache` — L1（`@st.cache_data` TTL 300s，靜態 spec 用）+ L2（session_state，動態 spec 用）；`invalidate_global_filter_visuals()` 只清除有 `inherit_global_filter=True` 的 entries
- `ai4bi/ui/render_visual.py`：`render_visual()` — Cache → Execute → Dispatch → Error；`execute_with_fallback()` 三態回傳 `(df, None)` / `(stale_df, exc)` / `(empty_df, exc)`；錯誤卡：Retry / Undo / Reset
- `ai4bi/ui/components/kpi_card.py`：`render_kpi_card()`（headline metric + delta badge + sparkline）
- `ai4bi/ui/components/line_chart.py`：`render_line_chart()`（Plotly + cross-filter 寫入 session_state）
- `ai4bi/ui/components/filter_bar.py`：`render_filter_bar()`（operator → widget 映射，最多 4 column 佈局）
- `ai4bi/analysis/executor.py`：`Executor.run()`（BlockRef 路徑解析 + SQL 生成 + DuckDB）
- `ai4bi/ui/app.py`：Streamlit entry point（`main()`）

**cross-filter 協定（初版）**：line chart 點擊後寫入 `st.session_state["cross_filter"] = {source_spec_id, column, value, timestamp}`，其他 visual render 時讀取並轉換為 active_filters。

#### 008-E. 尚有爭議 / Cautions

1. **BlockCriticality 可否事後變更**：如果 Data Manager 將一個 block 從 HIGH 升級為 CRITICAL，過去依 HIGH 標準認證的版本是否仍視為有效？目前暫定：升級後保持歷史認證，但未來版本強制走新標準。

2. **Staging 逾時策略**：`requires_confirmation=True` 的 proposal 放入 staging 後，若使用者 30 分鐘內未確認，是否自動取消？目前 StateManager 未實作逾時，Round 009 待補。

3. **cross-filter 多選合併邏輯**：多個 chart 同時設定 cross-filter 時 AND 合併的 session_state 結構尚未定案（見 008-F）。

4. **StylePatch 與 PatchProposal 的 CompositeUndoEntry 整合**：目前 StylePatch 走獨立 StyleHistory stack，CompositeUndoEntry 需要跨 stack 合作，整合細節待 Round 009 確認。

#### 008-F. Open Questions → Round 009 議題

1. **BlockRef Version Registry 儲存結構**：目前 Executor 用 `fixtures/blocks/<block_id>/<version>.json` 路徑約定，正式版需決定：目錄結構 vs 資料庫表 vs 物件儲存（S3/GCS）with manifest？`pinned_version` 解析是同步（阻塞渲染）還是非同步（background prefetch）？

2. **cross-filter 資料模型正式化**：點擊單點應產生 `eq` 還是 `in_`（為後續 multi-select 擴展）？多個 chart 同時設定 cross-filter 時，session_state key 是否改為 `dict[spec_id → FilterSpec]`？`VisualQuerySpec` 是否需要正式宣告 `cross_filter_emit: DimensionRef | None`？

3. **Analysis Patch Manual Edit 範圍**：使用者在 diff 確認卡看到 `VisualQuerySpec` 前後對比後，是否可以手動調整「AFTER」欄位再確認（limited field editor）？還是只能 Accept/Reject？

4. **Staging 逾時機制**：`requires_confirmation=True` 的 proposal 在 StateManager 中無逾時。應在 session 層、Streamlit rerun hook 或後端計時器實作？逾時後動作：自動 reject 還是轉為草稿？

5. **CompositeUndoEntry 跨 stack 整合**：StylePatch 走 StyleHistory stack，AnalysisPatch 走 ReportSpec undo stack，CompositeUndoEntry 需要同時 pop 兩個 stack。若其中一個 stack 為空（例如 style 成功但 analysis 取消），undo 的語義是什麼？

6. **P2 → P3 Sprint 計劃**：P2 UI 元件（kpi_card, line_chart, filter_bar）已完成，P3 應是哪些？候選：bar_chart, scatter, table/pivot, map, 跨頁 global filter 同步，share/export 功能？

#### Next Round Prompt

> Round 009 聚焦議題：
> 1. BlockRef Version Registry 儲存設計（filesystem vs DB vs object storage）
> 2. cross-filter 協定正式化（session_state key 結構 + FilterSpec operator 決策）
> 3. P3 Sprint 規劃（bar_chart / table / scatter + 跨頁 filter 同步）
> 4. CompositeUndoEntry 跨 stack 整合設計
> 5. Staging 逾時機制設計與實作

---

### Round 009 - BlockRef Version Registry 深度設計

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 深度設計 BlockRef Version Registry 的儲存後端、版本解析策略、Executor fallback 行為，以及 BlockRegistry Python API 介面 |
| Agent role | 資料基礎設施架構師 |
| Input | Round 008 已決策：BlockRef dataclass、pinned_version semver、CertificationTier 矩陣、`ai4bi/query_spec.py` 實作 |

---

#### 009-A. Q1：儲存後端選擇——評分矩陣與建議

**評分矩陣（1=差，5=優）**

| 場景 | Filesystem Convention | SQLite + JSON | 物件儲存（S3/GCS + manifest） |
|---|---|---|---|
| 本地開發 / Demo | **5** | 4 | 2 |
| 小型企業（<100 blocks，5 人） | **5** | 4 | 2 |
| 中型企業（500+ blocks，多團隊） | 2 | **4** | **5** |

**各方案詳細 trade-off：**

**方案 1 — Filesystem Convention（`blocks/<block_id>/v<version>.json`）**

優點：零依賴、git-friendly（每個版本是一個 diff-able 檔案）、Executor 路徑解析已按此實作（Round 008 `_resolve_block_path()`）、本地測試無須啟動任何服務。

缺點：沒有原生查詢能力（`list_versions("sales_fact")` 要做 `glob`）；certified_latest 指標沒有原子更新機制（concurrent writes 可能造成 race condition）；目錄規模超過 500 blocks × 20 版本後，ls 效能退化；無法存放 metadata index（認證狀態、criticality、timestamps）而不另開 manifest 檔。

**方案 2 — SQLite + JSON files（混合：SQLite 存 index + metadata，JSON 存 contract payload）**

優點：SQL 查詢 certified_latest、list_versions、fanout_risk 全部 O(log n)；schema 遷移可版控；DuckDB 已在棧內、SQLite 亦零額外服務；JSON file 保持 git-diffable，SQLite 只是索引層；符合 Round 002 已確認的「SQLite（lifecycle 索引）+ JSON files（contract 版本控管）」技術棧。

缺點：需維護 SQLite index 與 JSON files 的雙重一致性（每次 register 需原子寫入兩者）；team scale 超過 20 人並發寫入後 SQLite WAL 可能成瓶頸（但中型企業寫入頻率低，通常不是問題）。

**方案 3 — 物件儲存（S3/GCS）+ manifest.json**

優點：無限 scale；天然跨區域；與 CI/CD artifact pipeline 整合自然；雲端 IAM 可控存取。

缺點：本地開發需 LocalStack 或 MinIO 模擬（摩擦大）；所有 read path 都有網路延遲（pinned_version 解析從 filesystem stat 變成 HTTP GET）；manifest.json 的 concurrent update 需要 conditional PUT（etag-based optimistic locking）；成本與複雜度不符 R0/R1 需求。

**結論性建議：**

- **P0/MVP 推薦後端：方案 1 + 輕量 manifest.json**
  在現有 filesystem convention 基礎上，為每個 `block_id/` 目錄加入 `_meta.json` 檔存放 certified_latest 指標與版本清單。`Executor._resolve_block_path()` 讀取 `_meta.json` 確定 latest，不做 glob。這讓 P0 測試完全不依賴額外服務，且 git commit 一個版本 = 一次有意義的 diff。

- **P2 升級路徑：方案 2（SQLite 混合）**
  當 blocks 超過 50 個、多人開發開始出現 certified_latest 競爭寫入時，引入 SQLite index 層。JSON contract files 繼續存在（git source of truth），SQLite 只作為可再生的 derived index（`registry rebuild` 指令從 JSON 重建）。此時 filesystem 的 `_meta.json` 廢棄，以 SQLite 為準。

  **升級觸發條件（明確判斷點）**：block 數超過 80、或 CI pipeline 開始出現 `_meta.json` merge conflict、或 list_versions 呼叫出現在熱路徑且次數 > 1000/day。

---

#### 009-B. Q2：`pinned_version=None` 解析策略與 Session-Scoped Snapshot

**核心問題剖析**

`pinned_version=None`（latest certified）的解析如果在每次 render 呼叫時執行，等同於每次 Streamlit rerun 都重查 Registry。在一個 dashboard session 中，如果有人剛發布新版本（例如 `sales_fact` 從 `1.2.0` 升到 `1.3.0`），會在同一個 session 內造成同一張圖在不同 rerun 中數字不一致——這違反了「分析結果可信」的 North Star。

**事件序列（不設 snapshot 的危險場景）**：

```
t=0  使用者開啟 Dashboard，latest certified = sales_fact@1.2.0
t=1  使用者看到 KPI = 423,000（用 1.2.0）
t=2  Data Engineer 發布 1.3.0 並立即 certified（AUTO_CERTIFY 路徑）
t=3  使用者點擊 global filter → Streamlit rerun
t=4  KPI 重新解析 latest = 1.3.0，數字變成 431,000
t=5  使用者困惑：「我剛才看到的是 423,000 啊」
```

**設計決策：Session-Scoped Version Snapshot**

在 session 初始化時（`StateManager.init_state()` 中），一次性解析所有未 pin 的 BlockRef，並將「本次 session 使用的版本號」存入 session_state，整個 session 期間鎖定。

```python
# session_state 新增兩個鍵（SM_ 前綴延伸）
_SM_block_version_snapshot: dict[str, str]
# key: block_id, value: resolved version string (e.g. "1.2.0")
# 在 init_state() 時對所有 unpinned BlockRef 呼叫一次 registry.get_certified_latest()

_SM_snapshot_taken_at: datetime
# session 開始的時間戳，用於 audit log 和 staleness warning
```

**Snapshot 機制的三個規則：**

1. **Session 開始時建立快照**：`init_state()` 掃描所有頁面所有 visual 的 block_refs，對 `pinned_version=None` 的 ref 呼叫 `registry.get_certified_latest(block_id)`，寫入 `_SM_block_version_snapshot`。

2. **Executor 使用 snapshot 解析**：`Executor._resolve_block_path()` 接受一個 optional `version_override: dict[str, str]` 參數（由 StateManager 從 snapshot 傳入）。Unpinned ref 先查 override dict，再查 filesystem/registry。

3. **Snapshot Refresh 觸發條件**：使用者主動點擊「重新整理資料」按鈕 → `StateManager.refresh_snapshot()` → 重新解析所有 certified_latest → 寫入新快照 + 更新 `_SM_snapshot_taken_at`。若新舊版本號有差異，推入 `SessionVersionChangeEvent`，UI 顯示 banner：「資料已更新至新版本，數字已重新整理」。

**Staleness Warning**：若 snapshot 超過 4 小時（與 freshness_sla_hours 對齊），頂部顯示非阻斷式提示：「資料快照建立於 X 小時前，點此重新整理」。

---

#### 009-C. Q3：Executor Fallback 行為——治理建議

**現狀**：`Executor._resolve_block_path()` 在 pinned version 不存在時 fallback to latest（靜默 WARNING log）。

**三個選項的治理分析：**

| 選項 | 治理合規性 | 使用者體驗 | 可審計性 |
|---|---|---|---|
| A：硬失敗（raise exception） | 最高（zero tolerance） | 差（使用者看到 ERROR 無法操作） | 高 |
| B：fallback to latest + STALE_WARNING | 中（靜默繞過 pin 意圖） | 好（圖表正常顯示） | 中（有 log 但未強制展示） |
| C：fallback to latest + DEGRADED（需確認） | 高（強制使用者知情） | 可接受（需一次確認） | 高 |

**問題的本質**：`pinned_version` 存在的語意是「Dashboard 製作者明確要求這個版本」。如果版本已不存在（被刪除、目錄不在），silently fallback 等同於違背了 pin 的契約意圖。這對「Q1 2024 董事會資料包」這類場景是嚴重的信任破壞。

**建議：選項 A（硬失敗）是治理正確選擇，但需配合 UX 改善**

理由：
- `pinned_version` 的設計目的就是「防止版本漂移」。如果 pin 失效可以靜默繞過，pin 機制本身就失去意義。
- 版本消失通常是管理行為（deprecation、手動刪除），不是 bug，不應被 Executor 自動「修復」。
- 從 Round 008 CertificationTier 的治理哲學看，MANUAL_ONLY block 的 pinned version 消失後 fallback，等同於繞過了人工審核門檻。

**建議實作方案（A 的改良版）**：

```python
# Executor._resolve_block_path() 修正後行為
if ref.pinned_version:
    versioned = self._registry_root / ref.block_id / f"{ref.pinned_version}.json"
    if versioned.exists():
        return versioned
    # HARD FAIL — no silent fallback
    raise BlockVersionNotFoundError(
        block_id=ref.block_id,
        requested_version=ref.pinned_version,
        pin_reason=ref.pin_reason,
        available_versions=self._list_available_versions(ref.block_id),
    )
```

**UI 配合**：`BlockVersionNotFoundError` 被 `render_visual()` 捕獲後，元件狀態設為 `INCOMPATIBLE`（Round 008 ComponentHealthStatus），顯示 error card，包含：
- 遺失的版本號與 pin reason
- 可用版本清單（若有）
- 一鍵「解除 pin，改用 latest certified」的操作（需 Data Manager 角色）

此設計符合 Round 008 Method C（混合粒度）：受影響元件個別標示 INCOMPATIBLE，Dashboard 整體狀態升為 `ACTIVE_WITH_COMPONENT_WARNINGS`，不影響其他正常元件。

---

#### 009-D. Q4：BlockRegistry Python API 設計

以下是 interface-level 設計，包含完整的 dataclass/Protocol 程式碼（不含儲存層實作）：

```python
# ai4bi/blocks/registry.py — interface level

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class RegistryError(Exception):
    """Base class for all BlockRegistry errors."""


class BlockNotFoundError(RegistryError):
    """block_id does not exist in the registry."""
    def __init__(self, block_id: str):
        super().__init__(f"Block not found: {block_id!r}")
        self.block_id = block_id


class BlockVersionNotFoundError(RegistryError):
    """A specific semver of a block does not exist in the registry."""
    def __init__(
        self,
        block_id: str,
        requested_version: str,
        pin_reason: str | None,
        available_versions: list[str],
    ):
        super().__init__(
            f"Block {block_id!r} version {requested_version!r} not found. "
            f"Available: {available_versions}. Pin reason: {pin_reason!r}"
        )
        self.block_id = block_id
        self.requested_version = requested_version
        self.pin_reason = pin_reason
        self.available_versions = available_versions


class NoCertifiedVersionError(RegistryError):
    """block_id exists but has no certified version yet."""
    def __init__(self, block_id: str):
        super().__init__(
            f"Block {block_id!r} has no certified version. "
            "Use list_versions() to inspect available lifecycle states."
        )
        self.block_id = block_id


class DuplicateVersionError(RegistryError):
    """Attempting to register a version that already exists."""
    def __init__(self, block_id: str, version: str):
        super().__init__(
            f"Version {version!r} of block {block_id!r} already exists. "
            "Versions are immutable once registered."
        )


# ---------------------------------------------------------------------------
# Registry metadata types
# ---------------------------------------------------------------------------

class VersionLifecycle(str, Enum):
    draft      = "draft"
    validated  = "validated"
    certified  = "certified"
    deprecated = "deprecated"
    suspended  = "suspended"


@dataclass
class VersionRecord:
    """
    Metadata entry for a single version of a block in the registry.
    This is what the registry index stores — the contract payload is
    stored separately (filesystem JSON or external store).
    """
    block_id: str
    version: str                           # semver "MAJOR.MINOR.PATCH"
    lifecycle: VersionLifecycle
    registered_at: datetime
    certified_at: Optional[datetime] = None
    deprecated_at: Optional[datetime] = None
    certified_by: Optional[str] = None    # user/role that triggered certification
    change_type: Optional[str] = None     # BREAKING_MAJOR / BREAKING_MINOR / NON_BREAKING / ADDITIVE
    notes: Optional[str] = None


@dataclass
class CertifiedLatestPointer:
    """
    The registry's single authoritative pointer to which version is
    'latest certified' for a given block_id.

    This is the value returned when BlockRef.pinned_version is None.
    It is updated atomically when a new version reaches certified lifecycle.
    It is NEVER the semver-max — it requires human or AUTO_CERTIFY action.
    """
    block_id: str
    certified_version: str                # the version string to use
    pointer_updated_at: datetime
    updated_by: str                       # "AUTO_CERTIFY" | user/role identifier


@dataclass
class RegistrySnapshot:
    """
    Immutable view of certified_latest for all blocks, captured at a
    specific point in time. Used to implement the session-scoped snapshot
    mechanism (Round 009-B).
    """
    snapshot_id: str                      # UUID
    taken_at: datetime
    pointers: dict[str, str]             # block_id → certified_version
    taken_by: str                         # session_id or user_id


# ---------------------------------------------------------------------------
# BlockRegistry Protocol (interface contract)
# ---------------------------------------------------------------------------

class BlockRegistry(Protocol):
    """
    Abstract interface for a versioned DataBlockContract registry.

    Storage backends (filesystem, SQLite, object storage) implement this
    protocol. The Executor, StateManager, and certification workflows
    depend only on this interface — never on a concrete backend.

    Versioning invariants:
    - Versions are immutable once registered (idempotent re-register raises DuplicateVersionError).
    - certified_latest is updated only through certify() or the CI AUTO_CERTIFY pathway.
    - Deprecation does NOT automatically update certified_latest.
    """

    def register(
        self,
        contract: "DataBlockContract",      # ai4bi.blocks.contracts.DataBlockContract
        version: str,
        change_type: str = "NON_BREAKING",
        notes: Optional[str] = None,
    ) -> VersionRecord:
        """
        Persist a new version of a DataBlockContract to the registry.

        Parameters
        ----------
        contract : DataBlockContract
            The fully-validated contract (Pydantic model_validate already called).
        version : str
            Semver string. Must not already exist for this block_id.
        change_type : str
            One of: ADDITIVE | NON_BREAKING | BREAKING_MINOR | BREAKING_MAJOR.
            Used to determine the CertificationTier (Round 008 matrix).
        notes : str | None
            Optional human note for the registry audit trail.

        Returns
        -------
        VersionRecord
            The metadata entry created for this version.

        Raises
        ------
        DuplicateVersionError
            If (block_id, version) already exists.
        ValueError
            If version is not valid semver.
        """
        ...

    def resolve(
        self,
        block_id: str,
        pinned_version: Optional[str] = None,
        *,
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> "DataBlockContract":
        """
        Retrieve a DataBlockContract from the registry.

        Resolution order:
        1. If pinned_version is set → load exactly that version.
           Raises BlockVersionNotFoundError if not found (NO silent fallback).
        2. If pinned_version is None and version_snapshot is provided →
           look up block_id in snapshot dict and use that version.
        3. If pinned_version is None and no snapshot → call get_certified_latest()
           and use the returned version.

        Parameters
        ----------
        block_id : str
        pinned_version : str | None
            Exact semver to load, or None for latest-certified.
        version_snapshot : dict[str, str] | None
            Session-scoped snapshot (block_id → version).
            When provided and block_id is in the dict, overrides
            the real-time certified_latest lookup.

        Returns
        -------
        DataBlockContract

        Raises
        ------
        BlockNotFoundError
            If block_id has never been registered.
        BlockVersionNotFoundError
            If pinned_version is set but that version file/record is missing.
        NoCertifiedVersionError
            If pinned_version is None and no certified version exists.
        """
        ...

    def certify(
        self,
        block_id: str,
        version: str,
        certified_by: str,
    ) -> CertifiedLatestPointer:
        """
        Mark a version as certified and update the certified_latest pointer.

        This is the ONLY mechanism that advances certified_latest.
        Idempotent: certifying an already-certified version is a no-op
        (returns the existing pointer without error).

        Parameters
        ----------
        certified_by : str
            Identity that triggered the certification.
            "AUTO_CERTIFY" for CI-driven AUTO_CERTIFY tier;
            user/role string for REVIEW_REQUIRED / MANUAL_ONLY.

        Returns
        -------
        CertifiedLatestPointer
            The updated pointer (points to the newly certified version).

        Raises
        ------
        BlockVersionNotFoundError
            If (block_id, version) has not been registered first.
        """
        ...

    def list_versions(
        self,
        block_id: str,
        lifecycle_filter: Optional[list[VersionLifecycle]] = None,
    ) -> list[VersionRecord]:
        """
        Return metadata records for all (or filtered) versions of a block.

        Parameters
        ----------
        block_id : str
        lifecycle_filter : list[VersionLifecycle] | None
            If provided, only return versions with matching lifecycle.
            Example: [VersionLifecycle.certified] returns only certified versions.

        Returns
        -------
        list[VersionRecord]
            Ordered by registered_at ascending (oldest first).

        Raises
        ------
        BlockNotFoundError
            If block_id has never been registered.
        """
        ...

    def get_certified_latest(self, block_id: str) -> str:
        """
        Return the version string of the current certified latest for a block.

        This is a lightweight read — returns the version string only (not the
        full contract). Callers who need the contract should pass the result
        to resolve(block_id, pinned_version=<returned_version>).

        Use this method to populate a RegistrySnapshot at session start.

        Returns
        -------
        str
            Semver string of the certified latest version, e.g. "1.2.0".

        Raises
        ------
        BlockNotFoundError
            If block_id has never been registered.
        NoCertifiedVersionError
            If no certified version exists for this block.
        """
        ...

    def take_snapshot(
        self,
        block_ids: list[str],
        snapshot_id: str,
        taken_by: str,
    ) -> RegistrySnapshot:
        """
        Capture a point-in-time snapshot of certified_latest for a set of blocks.

        Called by StateManager.init_state() to establish the session-scoped
        version snapshot. The returned RegistrySnapshot.pointers dict is stored
        in session_state and passed to Executor.run() on every query call.

        Parameters
        ----------
        block_ids : list[str]
            All block IDs referenced in the current dashboard (deduplicated).
        snapshot_id : str
            Caller-supplied UUID (typically the session_id).
        taken_by : str
            user_id or session_id for audit trail.

        Returns
        -------
        RegistrySnapshot
            Immutable snapshot. Raises NoCertifiedVersionError for any
            block_id that has no certified version.
        """
        ...

    def deprecate(
        self,
        block_id: str,
        version: str,
        deprecated_by: str,
        notes: Optional[str] = None,
    ) -> VersionRecord:
        """
        Mark a version as deprecated. Does NOT update certified_latest.

        If the deprecated version IS the current certified_latest, the
        registry raises DeprecatingCertifiedLatestWarning (non-fatal) —
        the caller (Data Manager UI) must explicitly call certify() on
        a replacement version to advance the pointer.

        This design prevents accidental creation of a 'no certified version'
        state through an automated deprecation workflow.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete P0/MVP implementation skeleton (Filesystem backend)
# ---------------------------------------------------------------------------

class FilesystemBlockRegistry:
    """
    Filesystem-backed implementation of BlockRegistry.

    Directory layout:
        <root>/
            <block_id>/
                _meta.json            <- CertifiedLatestPointer + VersionRecord list
                1.0.0.json            <- DataBlockContract payload
                1.1.0.json
                2.0.0.json

    The _meta.json is the only mutable file per block — it is rewritten
    atomically (write-to-temp + rename) on register() and certify().
    All version JSON files are immutable once written.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _block_dir(self, block_id: str) -> Path:
        return self._root / block_id

    def _version_path(self, block_id: str, version: str) -> Path:
        return self._block_dir(block_id) / f"{version}.json"

    def _meta_path(self, block_id: str) -> Path:
        return self._block_dir(block_id) / "_meta.json"

    def _atomic_write(self, path: Path, data: str) -> None:
        """Write-to-temp-then-rename for crash-safe updates."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)

    # register(), resolve(), certify(), list_versions(), get_certified_latest(),
    # take_snapshot(), deprecate() — implemented against the above layout.
    # (Full implementation is P2 work; P0/P1 can use the existing
    #  _resolve_block_path() in Executor with _meta.json for certified_latest.)
    ...
```

**設計說明：**

- `version_snapshot` 參數在 `resolve()` 中讓 Executor 無需感知 StateManager，只需把 snapshot dict 傳進去，保持關注點分離。
- `take_snapshot()` 封裝在 Registry 內部，讓 StateManager 只呼叫一個 API 而不自己遍歷 blocks。
- `deprecate()` 明確不更新 certified_latest，需要人工顯式 certify 新版本，防止「deprecate 舊版本後 latest 指標懸空」的狀態。
- `_atomic_write()` 解決 P0 的 concurrent write race condition（write-to-temp + rename 是 POSIX 原子操作）。

---

#### 009-E. Round 009 Open Questions（給下一輪）

以下 3 個問題是本輪設計推導出的、對後續實作影響最大的開放議題：

**OQ-1：`_meta.json` 格式標準化與 SQLite 遷移觸發點**

`_meta.json` 需要定義正式 JSON schema（VersionRecord 清單 + CertifiedLatestPointer），並確認：當 P2 升級到 SQLite backend 時，`FilesystemBlockRegistry` 和 `SqliteBlockRegistry` 是否可以共存（讓 CI 環境繼續用 Filesystem、生產環境用 SQLite）？遷移腳本是否只要讀所有 `_meta.json` + version JSON 即可重建 SQLite index？

**OQ-2：Snapshot Staleness 的 UI 決策**

當 `_SM_snapshot_taken_at` 超過 freshness_sla_hours（預設 4 小時），目前建議只顯示提示（非阻斷）。但如果 block 的 freshness_sla_hours = 1（例如即時庫存）而 snapshot 已 3 小時，業務使用者看到的數字可能嚴重過期。是否需要針對 block-level freshness_sla 觸發強制 snapshot refresh？這涉及 StateManager 與 DataBlockContract.quality.freshness_sla_hours 的耦合設計。

**OQ-3：`BlockVersionNotFoundError` 的 Data Manager 自助修復流程**

選項 A（硬失敗）的實作前提是：使用者看到 INCOMPATIBLE 元件後，有一個低摩擦的「解除 pin / 切換到其他版本」操作。目前 Round 008 定義了 error card 有「解除 pin，改用 latest certified」按鈕，但需確認：誰可以執行這個操作？Dashboard 的 owner？Data Manager？還是任何 viewer？若允許 viewer 解除 pin，等同於靜默繞過了原始 pin 的治理意圖，需要在 Round 010 明確授權模型。

---

| 欄位 | 記錄 |
| --- | --- |
| Consensus | 009-A P0/MVP 推薦 Filesystem + `_meta.json`；P2 升級路徑 SQLite 混合；升級觸發條件明確 |
| Consensus | 009-B Session-Scoped Snapshot 機制：init_state 一次解析 + `_SM_block_version_snapshot` + staleness banner |
| Consensus | 009-C Executor fallback 應採選項 A（硬失敗）+ BlockVersionNotFoundError；UI 層配合 INCOMPATIBLE 元件狀態 |
| Consensus | 009-D BlockRegistry Protocol 完整 interface；FilesystemBlockRegistry 骨架；atomic write 防 race condition |
| Open questions | OQ-1 _meta.json schema + SQLite 遷移共存策略 |
| Open questions | OQ-2 Block-level freshness_sla 驅動的強制 snapshot refresh 邏輯 |
| Open questions | OQ-3 BlockVersionNotFoundError 修復操作的授權模型（owner vs Data Manager vs viewer） |
| Consensus | 009-B cross-filter 協定：`in_` operator（value 永遠 list）；`dict[source_spec_id, CrossFilterEntry]` 存入 `st.session_state["cross_filters"]`；`VisualQuerySpec.cross_filter_emit: DimensionRef | None`；`build_active_filters(spec, global_filters, cross_filters)` 三段合併；Badge Bar UI；生命週期跨 page 持續、Reset 不清除 |
| Consensus | 009-C P3 Sprint 選定：bar_chart + data_table + 跨頁 global filter 同步（scatter/export 延至 P4/P5）；`ai4bi/ui/components/bar_chart.py` 與 `data_table.py` 已實作 |
| Consensus | 009-D CompositeUndoEntry：undo stack 改為 `list[UndoRecord]`（含 `before_report_spec` + `style_rollback: dict[visual_id, VisualQuerySpec] | None` + `origin: "style"/"analysis"/"composite"/"style_only_confirmed"`）；Staging 逾時 30 分鐘、在 `init_state()` rerun-hook 掃描、auto_reject；`PromptExecutionState` 新增 `COMPOSITE_STYLE_FAILED` 與 `STYLE_ONLY_CONFIRMED` 終止態 |
| Decisions recorded | design-council-log.md Round 009 |

#### Next Round Prompt

> Round 010 聚焦議題：
> 1. cross-filter 協定正式化：session_state key 結構（`dict[spec_id → FilterSpec]`）、eq vs in_ operator、VisualQuerySpec 宣告 `cross_filter_emit`
> 2. CompositeUndoEntry 跨 stack 整合：StyleHistory + ReportSpec undo stack 協作語義（特別是 style 成功但 analysis 取消時的 undo 行為）
> 3. Staging 逾時機制：session 層 vs rerun hook 實作、逾時後 auto-reject vs 草稿保留的語義決策
> 4. OQ-3 授權模型：BlockVersionNotFoundError 修復操作的角色權限設計
> 5. P3 Sprint 規劃：bar_chart / table / 跨頁 global filter 同步 / share-export deliverable 與 Definition of Done

---

## 6. 下一輪預備問題

Round 009 完成 BlockRef Version Registry 儲存後端選擇、Session-Scoped Snapshot 機制、Executor 硬失敗 fallback 設計、BlockRegistry Python Protocol 介面後，Round 010 應優先回答：

1. **cross-filter 協定正式化**：session_state 結構、eq vs in_ operator、VisualQuerySpec 宣告？
2. **CompositeUndoEntry 跨 stack**：StyleHistory + ReportSpec undo stack 如何協作？
3. **Staging 逾時機制**：session 層 vs rerun hook vs 後端計時器，逾時動作語義？
4. **BlockVersionNotFoundError 修復授權**：誰可解除 pin？授權模型設計？
5. **P3 Sprint**：bar_chart / table / scatter / 跨頁 global filter 同步 / share-export？

---

### Round 010 - Semiconductor Process Data Product for BI Runtime Validation

| 項目 | 內容 |
| --- | --- |
| 日期 | `2026-05-28` |
| 狀態 | `completed` |
| 目標 | 以 semiconductor 製程資料重新設計可組合的資料端結構，並產生可由現有 `DataBlockContract` 驗證的 JSON data product |
| Agent perspectives | Semiconductor Data Architect、Manufacturing BI/UX、Contract Engineering Reviewer、Adversarial Governance Reviewer |
| 產出 | `data/semiconductor_demo/README.md`、`semantic_model.json`、八個 Data Blocks、`baselines.json`、`tests/test_semiconductor_data.py` |

#### 010-A. Domain Data Product Decision

本輪決定以「事件 fact + 品質 fact + 可重用 dimensions」建立第一份 semiconductor data product，而不是將所有資訊放入單一寬表或直接做複雜 genealogy：

| Block | Grain | BI 用途 |
| --- | --- | --- |
| `lot_dim` | one row per manufacturing lot | product family、route、priority |
| `wafer_dim` | one row per wafer | lot traceability |
| `tool_dim` | one row per process tool | tool group comparison |
| `process_step_dim` | one row per route step | PHOTO / ETCH / CVD slicing |
| `foup_dim` | one row per carrier | event-time carrier analysis |
| `calendar_dim` | one row per date | trend filters |
| `process_move_fact` | one completed step movement per wafer | move count、queue time、process time trend |
| `wafer_yield_fact` | one final CVD yield result per wafer | good/tested/defect die 與 weighted yield |

此模型直接支援未來 Report Canvas 的典型元件：

- KPI：move count、failed wafer count。
- Trend：queue time by date/tool、weighted yield by test date/product。
- Bar/Table：tool comparison、lot/wafer quality detail。
- Global Filters：日期、product family、step、tool group、lot。

#### 010-B. Multi-Agent Safety Consensus

| Decision ID | 決策 |
| --- | --- |
| `SEMI-001` | `process_move_fact` 與 `wafer_yield_fact` 是不同 grain 的 facts；不得以 wafer/lot 明細直接 join 後計算 metric。 |
| `SEMI-002` | `FOUP` 是會重複使用且隨時間換載的 carrier；`foup_id` 僅能以 move event 當下關係解讀，不是永久 lot/wafer 屬性。 |
| `SEMI-003` | Yield 是非加總指標，正式彙總公式只能是 `SUM(good_die) / SUM(tested_die) * 100`；不得 `SUM(yield_pct)`。 |
| `SEMI-004` | WIP、rework/genealogy、原始 measurement 對 yield attribution 不進入此首版 data product 的可執行分析範圍。 |
| `SEMI-005` | 所有安全 dimension relationships 採 fact-to-dimension `many_to_one`；跨 fact 分析需未來 CompositionRule 與 query planner。 |

#### 010-C. Current Runtime Compatibility Decision

代理審查發現：目前 `ai4bi/analysis/executor.py` 雖可註冊多個 block，但尚未產生跨 block SQL `JOIN`，且尚不會執行 contract 內的 ratio formula。

因此本輪採取雙層設計：

| 層級 | 作法 | 狀態 |
| --- | --- | --- |
| Semantic future path | 提供 dimensions、relationships、prohibited paths 與 composition rule proposal | 已建立，可供 Join Planner 下一階段使用 |
| Executable current path | 在兩個 fact blocks 內放入必要的顯示維度欄位，讓現有 executor 可做單 fact KPI / trend / table | 已建立並測試 |

不得在 UI 或文件宣稱當前 runtime 已完成 `tool_dim` Join 後的動態 visual；目前完成的是資料契約與 join-safe fixture 驗證。

#### 010-D. Created Data Package

```text
data/semiconductor_demo/
  README.md
  semantic_model.json
  baselines.json
  blocks/
    calendar_dim.json
    lot_dim.json
    wafer_dim.json
    tool_dim.json
    process_step_dim.json
    foup_dim.json
    process_move_fact.json
    wafer_yield_fact.json
```

Fixture 規模：

| 資料 | 筆數 |
| --- | ---: |
| Lots | 3 |
| Wafers | 6 |
| Process moves | 18 |
| Final yield results | 6 |
| Failed wafers | 2 |

已固定的 baseline：

| Baseline | Expected |
| --- | --- |
| ETCH `ETCH-01` average queue time | `2.0 hr` |
| ETCH `ETCH-02` average queue time | `4.0 hr` |
| Overall weighted final yield | `94.55%` |
| `Logic-A` weighted final yield | `96.25%` |
| `Logic-B` weighted final yield | `91.15%` |

#### 010-E. Validation Completed

| Test Gate | Result |
| --- | --- |
| 新 DataBlock JSON 經 `BlockLoader` 驗證 | passed |
| Records 欄位與 contract columns 一致 | passed |
| Primary keys unique | passed |
| Many-to-one dimension joins 保持 move row count | passed |
| Weighted yield baseline 由 numerator/denominator 重算 | passed |
| 現有 Executor 單 fact tool queue-time visual query | passed |
| `tests/test_semiconductor_data.py` | `22 passed` |
| Full regression suite | `111 passed` |

#### 010-F. Next Round Prompt

> Round 011 聚焦實作：為 `Executor` 加入僅限 certified `many_to_one` fact-to-dimension 的 Join Planner，讓 `process_move_fact -> tool_dim/process_step_dim` 與 `wafer_yield_fact -> lot_dim/tool_dim` 能由 Report Canvas 真正動態執行；同時拒絕 fact-to-fact detail join、ratio metric 的錯誤 aggregation 與未認證 relationship。

## Round 011 - Governed DIY Report Canvas Vertical Slice

### 011-A. User Intent Reconfirmed

The target product is a Streamlit-based BI authoring experience that feels
familiar to Power BI or Excel:

| User Need | Product Interpretation |
| --- | --- |
| Business users explore data themselves | Slicers, metric selection, visual canvas, table detail, and reusable reports |
| Multiple JSON data blocks | Governed semantic blocks and relationships rather than custom GUI code per dataset |
| Natural-language GUI changes | Prompts propose report/visual specifications, including scoped edits such as a red trend line |
| Joins and aggregations | Deterministic, validated execution controlled by certified semantic metadata |
| Future handoff between Agents | This append-only council log records decisions, limits, evidence, and the next unresolved question |

### 011-B. Multi-Agent Council Consensus

Four roles reviewed the proposed direction: Product Architect, Streamlit UX
Designer, Query Safety Architect, and Adversarial Engineer.

| Question | Consensus |
| --- | --- |
| Is the Power BI / Excel mental model appropriate? | Yes, for report-canvas authoring, slicers, metric breakdowns, and saving/share concepts. The MVP must not claim full parity. |
| Is the proposed Model-Control-View layering sound? | Yes, with one correction: raw JSON is not sufficient as the Model; the Model is a governed DataBlock plus semantic relationships, metrics, policy, and version. |
| What is the role of the LLM? | Proposal Author only. It may generate safe specification changes and style changes; it may not invent joins, metrics, SQL, policy, or published truth. |
| Can multi-source analytics start now? | Yes, only through certified direct `many_to_one` fact-to-dimension joins in the first executable slice. |
| What must be refused for now? | Fact-to-fact detail joins, transitive joins, arbitrary drag-and-drop relationships, ratio metric aggregation without an expression resolver, and LLM-authored SQL. |

### 011-C. Product Layering Decision

| Layer | Responsibility | First MVP Representation |
| --- | --- | --- |
| Model | Trusted data building blocks and semantic truth | `DataBlockContract`, `semantic_model.json`, metric definitions, certified relationships |
| Control | User intent translated into valid analysis behavior | `VisualQuerySpec`, filters, aggregation, sort, safe Join Planner, deterministic Executor |
| View | Interactive BI authoring and consumption surface | Streamlit report canvas with prompt command area, controls, KPI, trend, comparison chart, and table |
| AI Assistant | Suggests controlled edits to the above layers | Prompt-to-spec/style prototype; explanation shown before broader LLM integration |

### 011-D. Approved MVP Slice

**Scenario:** `ETCH Queue-Time Explorer`

| Aspect | Decision |
| --- | --- |
| Primary fact | `process_move_fact` |
| Join-enabled dimensions | `tool_dim` and `process_step_dim`, only through certified direct relationships |
| Primary business question | Which tools or tool vendors have longer ETCH queue time? |
| Metrics | Move count and average queue time |
| Visual canvas | KPI cards, time trend, vendor/tool comparison bar chart, and result table |
| Manual controls | Process-step and product-family selection; comparison breakdown |
| Prompt prototype | Commands such as "只看 ETCH", "依供應商比較等待時間", "把趨勢線改成紅色", and "重設條件" |
| Validation baselines | ETCH `ETCH-01 = 2.0 hr`; ETCH `ETCH-02 = 4.0 hr` |

### 011-E. Execution Guardrails

| Rule | Enforcement Direction |
| --- | --- |
| One primary fact only | Planner rejects additional fact blocks in a query |
| Relationship authority | Join requires a certified `many_to_one` `left` relationship in `semantic_model.json` and a LOW-risk contract hint |
| Metric ownership | Metrics must come from the primary fact and use their approved aggregation |
| Join SQL | Executor qualifies all joined fields by block identifier and uses parameter binding for filter values |
| Unsafe fact-to-fact | `process_move_fact` plus `wafer_yield_fact` detail query is rejected before SQL execution |
| Non-additive metric | Weighted yield remains documented but not exposed in this first canvas until expression planning is implemented |

### 011-F. Implementation Status

Status: `completed`

This round implemented the direct certified dimension Join Planner, repaired
the visual execution/cache path needed by the GUI, and replaced the generic
sales screen with the semiconductor queue-time Report Canvas.

### 011-G. Implementation Delivered

| Deliverable | Result |
| --- | --- |
| Join Planner | Added `SafeJoinPlanner`; it permits only direct certified LOW-risk `many_to_one` left joins from one primary fact to dimensions. |
| Executor | Generates table-qualified joined SQL from `semantic_model.json`, enforces declared metric aggregation, binds filters safely, and rejects unsafe query shapes before execution. |
| Report Canvas | Replaced the sales demo with `ETCH Queue-Time Explorer`: slicers, two KPIs, trend chart, joined tool comparison, joined detail table, and a trust explanation panel. |
| Prompt Editing | Added a guarded rule-based command bar for approved view changes such as ETCH filtering, vendor/tool breakdown, and red trend-line styling. This is a prototype boundary, not an LLM semantic authority. |
| UI Runtime Repair | Fixed active-filter forwarding and successful DataFrame caching; updated rendered components to current Streamlit width API. |
| Data Product Documentation | Updated runtime support to direct certified dimensions and retained explicit refusal of fact-to-fact detail joins and incorrect yield aggregation. |

### 011-H. Verification Evidence

| Check | Evidence |
| --- | --- |
| Focused semiconductor and render-path tests | `30 passed` |
| Full regression suite | `119 passed` |
| Streamlit canvas smoke run | `0` exceptions; page renders `ETCH Queue-Time Explorer` |
| Certified join baseline | Joined `tool_dim.tool_id` query returned `ETCH-01 = 2.0 hr`, `ETCH-02 = 4.0 hr` |
| Unsafe join behavior | Automated test rejects `process_move_fact` detail join to `wafer_yield_fact` |
| Lineage clarity | Automated test rejects an unused secondary dimension block |
| Unsafe metric behavior | Automated test rejects undeclared direct averaging of `yield_pct` |

### 011-I. Honest Product Boundary

The implemented MVP demonstrates DIY filtering, prompt-scoped visual changes,
and multiple visuals sourced from a governed JSON fact plus certified JSON
dimensions. It is not yet a general Power BI replacement: it does not persist
or share report specifications, does not use a production LLM adapter, does
not compose multiple fact grains, and does not calculate ratio metrics such as
weighted yield through a reusable expression planner.

### 011-J. Next Round Prompt

> Round 012 聚焦產品化：將目前 Canvas 的 widget 狀態轉成可儲存、可分享、可版本化的 `ReportSpec`，加入 prompt proposal preview / accept / undo 流程；同時評估以「先各自聚合再 join」的 composition plan 安全支援 queue time 與 weighted yield 的跨 fact 分析，而不是開放明細 fact-to-fact join。

## Round 012 - Executable Report Draft And Proposal Workflow

### 012-A. Multi-Agent Council Decision

Four reviewers independently examined product value, state architecture,
semantic safety, and testability. They agreed on the next vertical slice:

| Candidate | Decision | Reason |
| --- | --- | --- |
| Proposal preview / accept / undo | Implement now | Proves the LLM-assisted WYSIWYG contract while keeping the user in control. |
| Save / load report state | Implement as local draft | Turns exploration into reusable work without claiming governed publication. |
| Read-only/public sharing | Defer | Blocks are currently `validated`, policy is not enforced at runtime, and version pin failure is not yet fail-closed. |
| Free-form visual builder | Defer | Persistence and proposal safety must become the source of truth first. |
| Cross-fact queue time vs yield | Refuse for execution | No safe aggregate-then-compose planner or weighted ratio expression compiler exists yet. |

### 012-B. Architecture Correction

The current application contains two different visual query models. The older
`spec_models.VisualQuerySpec` stores simplified strings, while the executable
runtime model stores block-qualified metrics, dimensions, filters, sorting and
visual styles. Extending the simplified model would lose the semantics already
proved by the semiconductor Canvas.

Decision:

| Area | Round 012 Direction |
| --- | --- |
| Report source of truth | Add an executable report-domain model that stores current runtime `VisualQuerySpec` and `VisualizationSpec` objects faithfully. |
| Existing legacy state tests | Keep the old model intact for compatibility; do not silently reinterpret saved legacy specs. |
| Controls | Store slicer and breakdown values within report state rather than independent widget-only state. |
| Prompt changes | Express as allowlisted `ReportProposal` changes, stage for preview, then apply atomically. |
| Undo / Redo | History operates on the executable report state, covering controls and style together. |
| Persistence | Serialize/load local draft JSON with model reference, revision and validation banner. |

### 012-C. Safety Boundary

| Rule | Enforcement |
| --- | --- |
| Dataset trust wording | The UI must say `validated demo data` using a certified relationship path, not claim a published certified dashboard. |
| Style prompt | May modify one selected visual, must state that data/query is unchanged, and must be undoable. |
| Analysis prompt | May propose approved filters or breakdown only; result does not change until accepted. |
| Mixed prompt | All included changes are applied as one atomic proposal and one undo step. |
| Draft persistence | Allowed locally for this demo, with explicit non-published status. |
| Formal sharing/publishing | Remains disabled until lifecycle, policy, audit and fail-closed version pin gates exist. |
| Cross-fact and weighted yield | Remain unavailable for execution. |

### 012-D. Approved Implementation Slice

Status: `completed`

The implementation delivered:

1. An executable semiconductor report template containing the five existing visuals.
2. A single report state that drives filters, breakdown and trend styling.
3. A Visual Assistant panel with target selection and proposal diff preview.
4. Atomic apply, cancel, undo and redo for report changes.
5. Local draft save/load with explicit `validated demo draft` labeling.
6. Automated model, workflow and Streamlit interaction verification.

### 012-E. Delivered Implementation

| Deliverable | Result |
| --- | --- |
| Executable report artifact | Added a report-domain model that serializes actual runtime query specs, visualization style, controls, semantic model reference, draft status and revision. |
| Starter template | Moved the five semiconductor visuals into an executable `ETCH Queue-Time Explorer` report template. |
| Single state source | Canvas filters, breakdown and trend style are now read from report workspace state rather than scattered direct prompt mutations. |
| Proposal workflow | Visual Assistant targets a selected component and stages allowlisted prompt changes with before/after diff and data-impact labels. |
| Atomic application | A stale or invalid proposal rejects as a whole; no partially applied AI change is committed. |
| Undo / Redo | Manual slicer changes and accepted prompt proposals are tracked as report revisions and can be reversed in the GUI. |
| Local drafts | The sidebar saves and loads executable local JSON drafts, explicitly marked `validated_demo_draft`. |
| Trust language | UI no longer calls the full dashboard certified; it distinguishes validated fixture data from a certified relationship path. |
| Error-action clarity | Query failure fallback action is labeled `Show previous result`, separate from report-history `Undo`. |

### 012-F. Verified User Journeys

| Journey | Evidence |
| --- | --- |
| Style prompt preview | `make trend line red` creates a pending proposal; before Apply the line style and KPI values are unchanged. |
| Style apply and undo | Apply sets the trend color to `#D62728`; Undo returns it to default without changing metrics. |
| Analysis prompt preview | `Only show Logic-B` leaves the active KPI at `6.0 moves / 2.7 hr` until Apply. |
| Analysis apply and undo | Apply updates KPI to `2.0 moves / 4.0 hr`; Undo restores `6.0 moves / 2.7 hr` and the slicer values. |
| Manual slicer history | Selecting `Logic-B` directly also participates in Undo and restores both widget and chart output. |
| Draft round trip | Local draft serialization retains safe join dimension, approved aggregation and red-line style. |
| Safety guard | Invalid/stale proposal test proves all-or-nothing rejection. |

### 012-G. Validation Evidence

| Test Gate | Result |
| --- | --- |
| Focused report/workflow/semantic/render tests | `39 passed` |
| Full regression suite | `128 passed` |
| Streamlit AppTest smoke run | `0` exceptions |
| Running local GUI endpoint | `HTTP 200` at `http://localhost:8501` |

### 012-H. Remaining Product Boundary

This round makes the demo substantially closer to a DIY BI product: a
business user can modify, preview, undo, and save a multi-visual analysis
draft. It deliberately does **not** provide published report sharing, access
control, arbitrary visual construction, LLM-generated semantic definitions,
or safe cross-fact yield composition.

### 012-I. Next Round Prompt

> Round 013 聚焦 builder 與治理：在 executable draft workspace 之上，加入由已核准 metric/dimension catalog 驅動的「新增 visual」流程與只讀 draft viewer；同時設計 publication gate（block lifecycle、role policy、version pin fail-closed、audit metadata），使 local draft 未來能安全升級為可分享報表。跨 fact composition 仍需以 aggregate-then-compose planner 與 weighted-yield expression compiler 分開評估。

---

## Round 013 — Visual Builder, Publication Gate, Composition Planner (2026-05-28)

### 013-A. Session Context

Round 013 continues from Round 012's executable draft workspace.  Goal: add a governed visual-builder flow driven by a certified metric/dimension catalog, a read-only draft viewer URL mode, a publication-readiness gate, and a cross-fact aggregate-then-compose planner.  Four agents were launched in parallel; three completed; one timed out.

### 013-B. Agents and Outcomes

| Agent ID | Task | Status | Tests Added |
| --- | --- | --- | --- |
| a4517e8c94603f44b | 013-A Visual Builder + CatalogBrowser | Completed | +21 (149 total) |
| ab7ad761113452158 | 013-B Publication Gate + ReadonlyMode | Completed | +10 (159 total) |
| a66be4b71bdbbe591 | 013-C Composition Planner + CompositionExecutor | Completed | +23 (197 total) |
| af44607e33f399c8d | 013-D BlockRegistry FilesystemBlockRegistry | FAILED — 600 s stall, zero output | 0 |

**Final passing test count: 197**

### 013-C. Decisions Made

#### Visual Builder (013-A)

- **CatalogBrowser (`ai4bi/report/catalog.py`)** builds `list[BlockCatalog]` from the semantic_model + DataBlockContracts.  Each `BlockCatalog` holds `list[MetricEntry]` and `list[DimensionEntry]`.
- **`build_visual_from_selection()` (`ai4bi/report/builder.py`)** takes `(visual_id, block_id, metric_names, dimension_names, visual_type, contracts)` and returns `(VisualQuerySpec, VisualizationSpec)`.  Safety rules enforced at build time:
  - `kpi_card` no dimensions allowed.
  - `line_chart` / `bar_chart` / `data_table` at least one dimension required.
  - Maximum 2 metrics and 2 dimensions per visual.
  - Cross-block dimensions must have a certified relationship in the semantic model.
- **Sidebar Add-Visual panel** in `app.py` exposes a 6-step expander: pick block, pick metrics, pick dimensions, pick visual type, preview, add to canvas.

#### Publication Gate (013-B)

- **`run_publication_gate(report, contracts, semantic_model)`** (`ai4bi/report/publication.py`) runs 5 ordered checks and returns `PublicationGateResult(can_publish, checks)`.
  1. `block_lifecycle` — all referenced blocks must be CERTIFIED or ARCHIVED_STABLE.
  2. `version_pin_safety` — if a version is pinned, it must match the current certified semver (no stale pins).
  3. `relationship_certified` — every join used by a visual must appear in `semantic_model.certified_joins`.
  4. `policy_check` — no policy block attached to the report may be in a DRAFT state.
  5. `audit_metadata` — report must carry a non-empty `report_id` and a saved revision >= 1.
- **ReadonlyMode (`ai4bi/ui/viewer.py`)** parses `?mode=readonly&draft=<path>` URL params via `st.query_params`; renders a banner and hides the prompt bar and sidebar edit controls.

#### Composition Planner (013-C)

- **`RatioMetricExpr`** (`ai4bi/planning/composition_plan.py`): `SUM(numerator)/SUM(denominator)*scale`.  Blocks `AVG(yield_pct)` at the type level — only ratio form is expressible.
- **`AggStep`**: single-fact aggregation unit with `block_id`, `group_by`, `metrics`, `filters`, and `validate_column_ownership()` which rejects columns that do not belong to that block.
- **`ComposeStep`**: joins two AggStep results on `join_key`.  Never touches raw fact tables — only operates on CTE aliases produced by its child AggSteps.
- **`CompositionPlan`**: validates 2-fact maximum and requires `join_key` to appear in both child `group_by` lists.
- **`CompositionPlanner`**: auto-detects single-fact vs cross-fact and routes to `SafeJoinPlanner` or `CompositionPlan` accordingly.
- **`CompositionExecutor`** (`ai4bi/analysis/composition_executor.py`): emits CTE-based SQL.  `_build_agg_sql()` produces per-fact CTE fragments; `_build_compose_sql()` joins the two CTE aliases.  `run_from_registry()` is a convenience method.
- **`build_etch_queue_vs_yield_plan()`** factory: cross-fact demo ETCH queue time vs wafer yield by product family.

#### BlockRegistry (013-D — DEFERRED)

Agent timed out with no output.  Task deferred to Round 014:
- Implement `ai4bi/blocks/registry.py`: `FilesystemBlockRegistry` with `_meta.json` atomic write (write-to-temp, rename).
- `_meta.json` schema: `{block_id, version, status, certified_at, certified_by, changelog}`.
- Integrate registry lookup into `Executor` path resolution.
- Create `data/semiconductor_demo/registry/` with one `_meta.json` per block (8 files).
- Add `tests/test_block_registry.py`.

### 013-D. New File Inventory

| File | Type | Purpose |
| --- | --- | --- |
| `ai4bi/report/catalog.py` | New | `MetricEntry`, `DimensionEntry`, `BlockCatalog`, `build_catalog()` |
| `ai4bi/report/builder.py` | New | `build_visual_from_selection()` with safety validation |
| `ai4bi/report/publication.py` | New | `run_publication_gate()` — 5-check publication gate |
| `ai4bi/ui/viewer.py` | New | `is_readonly_mode()`, `get_draft_path_from_params()`, `render_readonly_banner()` |
| `ai4bi/planning/composition_plan.py` | New | `AggStep`, `ComposeStep`, `CompositionPlan`, `CompositionPlanner`, `RatioMetricExpr` |
| `ai4bi/analysis/composition_executor.py` | New | `CompositionExecutor` — CTE-based cross-fact SQL |
| `tests/test_catalog_builder.py` | New | 21 tests |
| `tests/test_publication_gate.py` | New | 10 tests |
| `tests/test_composition_planner.py` | New | 23 tests |

### 013-E. Validated Data Contract Additions

```python
@dataclass
class RatioMetricExpr:
    numerator: str
    denominator: str
    scale: float = 100.0

@dataclass
class AggStep:
    step_id: str
    block_id: str
    group_by: list[str]
    metrics: list[SimpleMetricExpr | RatioMetricExpr]
    filters: dict[str, list[str]]

@dataclass
class ComposeStep:
    step_id: str
    left_step: AggStep
    right_step: AggStep
    join_key: str

@dataclass
class GateCheckResult:
    check_name: str
    passed: bool
    message: str
    blocking: bool

@dataclass
class PublicationGateResult:
    can_publish: bool
    checks: list[GateCheckResult]
```

### 013-F. Open Questions -> Round 014

1. **Dynamic canvas render loop**: Canvas currently renders a fixed visual list.  Round 014 must add `visual_order: list[str]` to `ReportPageSpec` and render visuals dynamically so newly added visuals appear without hardcoded layout changes.
2. **Filter inheritance for new visuals**: When `build_visual_from_selection()` adds a visual, it should inherit the current global filter set (`inherit_global_filter` strategy).
3. **BlockRef pin workflow in UI**: Which user action triggers a version pin?  When should the UI surface `pin_reason`?
4. **audit_metadata placement**: A dedicated `AuditMetadata` field on `ExecutableReportSpec` (rather than top-level fields) would make the schema cleaner.
5. **AggStep filter parameterized queries**: `_build_agg_sql()` interpolates filter values directly into SQL strings.  Must replace with DuckDB parameterized queries to prevent SQL injection.
6. **Multi-grain join_key completeness**: `CompositionPlan.validate()` checks `join_key` presence but does not verify compatible grain.  A `grain_check()` mechanism is needed.
7. **BlockRegistry (deferred from 013-D)**: `FilesystemBlockRegistry` + `_meta.json` atomic writes + Executor integration + 8 demo files.
8. **Cross-page global filter sync**: Still not implemented (P3 item pending).

### 013-G. Next Round Prompt

> Round 014 聚焦三件事：(1) **Dynamic Canvas** — `ReportPageSpec` 加入 `visual_order: list[str]`，canvas loop 依序渲染，新增 visual 自動插入底部並繼承當前 global filter；(2) **BlockRegistry** (013-D 補做) — `FilesystemBlockRegistry` + `_meta.json` atomic write + Executor 整合 + 8 個 demo _meta.json + tests；(3) **AggStep SQL injection hardening** — 將 `_build_agg_sql()` 的 filter 插值改為 DuckDB parameterized query。`grain_check()` 與 `AuditMetadata` dataclass 可作為次要目標。

---

## Round 014 — Dynamic Canvas, SQL Hardening, AuditMetadata, BlockRef Pin (2026-05-28)

### 014-A. Session Context

Round 014 continues from Round 013's Visual Builder + Publication Gate + Composition Planner baseline (197 tests). Three agents ran in parallel; all three completed successfully.

### 014-B. Agents and Outcomes

| Agent ID | Task | Status | Tests Added |
| --- | --- | --- | --- |
| a7932ce6d7f7b04f4 | 014-A Dynamic Canvas + Filter Inheritance | Completed | +9 (206 total) |
| a2c34966840a48d23 | 014-B SQL Hardening + grain_check | Completed | +19 (includes updated existing) |
| a938dcc5e3342eae2 | 014-C AuditMetadata + BlockRef Pin Workflow | Completed | +9 (234 total) |

**Final passing test count: 234**

### 014-C. Decisions Made

#### Dynamic Canvas (014-A)

- **`visual_order: list[str]`** added to `ReportPageSpec`. Defaults to `list(visuals.keys())` from the template. Preserved in `to_dict()` / `from_dict()` round-trips.
- **`ReportPageSpec.add_visual(visual_id, visual_spec)`**: appends `visual_id` to `visual_order`; raises `ReportValidationError` if the `visual_id` already exists.
- **`pages/{page_id}/add_visual` proposal path**: `apply_report_proposal()` recognises this path and calls `page.add_visual()` atomically. `before=None`, `new_value={"visual_id": str, "visual": dict}`.
- **`build_add_visual_proposal(page_id, visual_id, query_spec, viz_spec) -> ReportProposal`** in `builder.py` — `affects_data=True`.
- **Canvas loop** in `app.py` now iterates `page.visual_order` instead of a hardcoded list. Adjacent `kpi_card` pairs share a two-column layout; all other types render full-width.
- **Filter inheritance**: when "Add to Report" is clicked, active filters whose key starts with the selected `block_id` are copied into the new visual's `VisualQuerySpec.filters`.

#### AggStep SQL Hardening (014-B)

- **`_build_agg_sql()` now returns `(sql_fragment: str, params: list)`**. SQL uses `?` placeholders for all filter values; `params` holds the ordered values.
- **`AggStep.filter_values: dict[str, list]`** — new field for parameterized filter values. The legacy `filters: list[str]` field is retained for trusted-internal raw SQL predicates only.
- **`CompositionExecutor.run()`** collects params from each CTE step and passes the combined list to `con.execute(full_sql, all_params)`.
- **`grain_check(semantic_model: dict) -> list[str]`** added to `CompositionPlan`. Checks `semantic_model["certified_joins"]` in both directions for the `(left_block, right_block, join_key)` triple. Returns a warning string if not certified (not an error — planner proceeds with warning).
- **`CompositionPlanner.plan(semantic_model: dict | None = None)`** — optional parameter; calls `grain_check()` and logs warnings at WARNING level when semantic_model is provided.
- `tests/test_composition_planner.py` updated: 3 call sites of `_build_agg_sql()` now unpack `(sql, params)` tuple.

#### AuditMetadata + BlockRef Pin (014-C)

- **`AuditMetadata` dataclass** (in `models.py`): `{report_id, created_by, created_at, last_modified_by, last_modified_at, revision}`. Has own `to_dict()` / `from_dict()`.
- **`ExecutableReportSpec`** now carries `audit: AuditMetadata` instead of standalone `report_id` and `revision`. Backward-compat `report_id` and `revision` properties delegate to `self.audit.*`. Old drafts without `"audit"` key deserialize gracefully.
- **`DraftReportStore.save()`** sets `saved.audit.last_modified_at` to `datetime.now(timezone.utc).isoformat()` on every save.
- **Publication gate** `audit_metadata` check now uses `report.audit.report_id` and `report.audit.revision`.
- **`pin_block_version_proposal(report, page_id, visual_id, block_id, certified_version, pin_reason)`** in `proposals.py` — creates a proposal targeting `pages/{page_id}/visuals/{visual_id}/query/block_refs/{block_id}/pinned_version` with `affects_data=False`.
- **`apply_report_proposal()`** supports the 8-part `block_refs/{block_id}/pinned_version` path; locates the matching `BlockRef` by `block_id` and updates `pinned_version` and `pin_reason`.

### 014-D. Updated File Inventory

| File | Change | Purpose |
| --- | --- | --- |
| `ai4bi/report/models.py` | Modified | `AuditMetadata`, `visual_order`, `add_visual()`, pin path support |
| `ai4bi/report/builder.py` | Modified | `build_add_visual_proposal()` |
| `ai4bi/report/proposals.py` | Modified | `pin_block_version_proposal()` |
| `ai4bi/report/publication.py` | Modified | `audit_metadata` check uses `report.audit.*` |
| `ai4bi/report/templates.py` | Modified | `AuditMetadata(report_id=...)` in template |
| `ai4bi/planning/composition_plan.py` | Modified | `AggStep.filter_values`, `CompositionPlan.grain_check()`, `CompositionPlanner.plan(semantic_model)` |
| `ai4bi/analysis/composition_executor.py` | Modified | `_build_agg_sql()` returns tuple, parameterized DuckDB execution |
| `ai4bi/ui/app.py` | Modified | Canvas loop over `visual_order`, filter inheritance in Add Visual |
| `tests/test_dynamic_canvas.py` | New | 9 tests |
| `tests/test_composition_hardening.py` | New | 19 tests (incl. SQL injection safety) |
| `tests/test_audit_and_pin.py` | New | 9 tests |
| `tests/test_composition_planner.py` | Modified | 3 call sites updated for tuple return |

### 014-E. Validated Data Contract Additions

```python
@dataclass
class AuditMetadata:
    report_id: str
    created_by: str = "unknown"
    created_at: str | None = None
    last_modified_by: str = "unknown"
    last_modified_at: str | None = None
    revision: int = 0

# AggStep extended
@dataclass
class AggStep:
    ...
    filter_values: dict[str, list] = field(default_factory=dict)  # parameterized

# grain_check on CompositionPlan
def grain_check(self, semantic_model: dict) -> list[str]: ...

# New proposal helper
def pin_block_version_proposal(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
    block_id: str,
    certified_version: str,
    pin_reason: str = "manually pinned by user",
) -> ReportProposal: ...
```

### 014-F. Open Questions -> Round 015

1. **Published report sharing**: The publication gate and `AuditMetadata` are now in place. Round 015 can wire up a simple share-link mechanism (write `published/` subdirectory, generate a read-only URL with `?mode=readonly&draft=<path>`).
2. **`visual_order` reordering**: Users can now add visuals but cannot reorder them. A drag-reorder or move-up/down proposal would complete the canvas authoring loop.
3. **BlockRef pin UI**: `pin_block_version_proposal()` is implemented. Round 015 should add the sidebar "Pin version" button in `app.py` that looks up the certified version from `FilesystemBlockRegistry` and stages the proposal.
4. **`created_by` / `last_modified_by` identity**: Currently hardcoded to `"unknown"`. Round 015 can pick up a configurable `ANALYST_NAME` env var or Streamlit session param.
5. **Cross-page global filter sync**: Still pending (P3 item).
6. **Streamlit AppTest coverage for dynamic canvas**: The 9 new canvas tests cover the model layer. An `AppTest` smoke run for the add-visual + confirm flow would close the UI gap.

### 014-G. Next Round Prompt

> Round 015 聚焦三件事：(1) **Published Report Sharing** — 將已通過 publication gate 的 draft 寫入 `published/` 子目錄，`app.py` 生成 `?mode=readonly&draft=<path>` share URL 並在 UI 顯示；(2) **Pin Version UI** — sidebar 「Pin version」按鈕查詢 `FilesystemBlockRegistry` 取得 certified version，呼叫 `pin_block_version_proposal()` 並 stage；(3) **Canvas Reorder** — `ReportPageSpec` 支援 `move_visual_up(visual_id)` / `move_visual_down(visual_id)`，對應 proposal path `pages/{page_id}/reorder_visual`。`created_by` 身份可從 `ANALYST_NAME` env var 讀取作為次要目標。

---

## Round 015 — Published Sharing, Pin Version UI, Canvas Reorder, ANALYST_NAME (2026-05-28)

### 015-A. Session Context

Round 015 continues from Round 014 baseline (234 tests). Goal: wire the publication gate to an actual publish action that writes a shareable snapshot, add Pin/Unpin version UI, and add canvas visual reorder. Three agents ran in parallel; all three completed.

### 015-B. Agents and Outcomes

| Agent ID | Task | Status | Tests Added |
| --- | --- | --- | --- |
| a2a11ac1edf20dca3 | 015-A Published Report Sharing | Completed | +8 (242 total) |
| a89f71bace7c5a34a | 015-B Pin Version UI + unpin proposal | Completed | +9 (251 total) |
| a5efc88372a28634f | 015-C Canvas Reorder + ANALYST_NAME | Completed | +10 (261 total) |

**Final passing test count: 261**

### 015-C. Decisions Made

#### Published Report Sharing (015-A)

- **`PublishBlockedError(Exception)`** raised when `gate_result.can_publish` is False.
- **`PublishedReportStore`** (in `models.py`):
  - `publish(report, gate_result) -> (Path, str)`: fail-closed gate check, writes timestamped JSON to `root/<report_id>/<iso_timestamp>.json`, sets `audit.last_modified_at`, returns `(path, share_url)`.
  - `share_url` format: `?mode=readonly&draft=<absolute_path>` — paste into browser address bar.
  - `list_published(report_id) -> list[Path]`: all snapshots for a report_id, newest first.
- **`app.py` Publication Readiness panel**: "Publish & Share" primary button when gate passes; disabled with tooltip when gate fails. On click: re-runs gate fail-closed, calls `PublishedReportStore.publish()`, shows `st.success(share_url)`, stores in `st.session_state["last_share_url"]`.
- **`.gitignore`**: `published/` added — runtime output never committed.

#### Pin Version UI (015-B)

- **`unpin_block_version_proposal(report, page_id, visual_id, block_id)`** in `proposals.py`: `affects_data=False`; sets both `pinned_version=None` and `pin_reason=None`.
- **`_set_path()` fix in `models.py`**: unpin (`value=None`) now correctly clears both `pinned_version` AND `pin_reason` (previously only cleared `pinned_version`).
- **"Pin versions" sidebar expander** in `app.py`: iterates `visual_order` → each visual's `block_refs`. Unpinned refs show "Pin {block_id}" button (looks up `FilesystemBlockRegistry.get_certified_latest()`, stages `pin_block_version_proposal`). Pinned refs show label + "Unpin" button (stages `unpin_block_version_proposal`).

#### Canvas Reorder + ANALYST_NAME (015-C)

- **`ReportPageSpec.move_visual_up(visual_id)`**: swaps with the element before; no-op if already first; raises `ReportValidationError` if `visual_id` not in `visual_order`.
- **`ReportPageSpec.move_visual_down(visual_id)`**: swaps with the element after; no-op if already last; raises `ReportValidationError` if unknown.
- **`pages/{page_id}/reorder_visual` proposal path**: `new_value = {"visual_id": str, "direction": "up"|"down"}`.
- **`build_reorder_visual_proposal(page_id, visual_id, direction, current_order)`** in `builder.py`: `affects_data=False`.
- **Canvas `app.py`**: inline up/down arrow buttons in visual header row; click stages a reorder proposal via `workspace.stage_proposal()`.
- **`ANALYST_NAME` env var**: `DraftReportStore.save()` sets `audit.last_modified_by`; `build_semiconductor_queue_time_report()` sets `audit.created_by`. Falls back to `"unknown"` if env var not set.

### 015-D. Updated File Inventory

| File | Change | Purpose |
| --- | --- | --- |
| `ai4bi/report/models.py` | Modified | `PublishedReportStore`, `PublishBlockedError`, `move_visual_up/down`, reorder path, ANALYST_NAME, unpin fix |
| `ai4bi/report/proposals.py` | Modified | `unpin_block_version_proposal()` |
| `ai4bi/report/builder.py` | Modified | `build_reorder_visual_proposal()` |
| `ai4bi/report/templates.py` | Modified | `audit.created_by` from ANALYST_NAME |
| `ai4bi/ui/app.py` | Modified | Publish & Share button, Pin versions panel, up/down reorder buttons |
| `.gitignore` | Modified | `published/` excluded from git |
| `tests/test_published_store.py` | New | 8 tests |
| `tests/test_pin_ui_workflow.py` | New | 9 tests |
| `tests/test_canvas_reorder.py` | New | 10 tests |

### 015-E. Open Questions -> Round 016

1. **Cross-page global filter sync**: Still pending. Multiple pages in a report should share the same global filter state.
2. **Undo after publish**: Should publishing be an undoable action? Currently it writes a permanent file; undo would need to either delete the file or mark it as superseded.
3. **Published snapshot versioning**: `list_published()` returns all snapshots. A UI to browse, compare, and restore previous published versions would complete the lifecycle story.
4. **`created_at` field**: `AuditMetadata.created_at` is still null. Should be set on first `DraftReportStore.save()` (only if currently null), not on every save.
5. **Streamlit AppTest coverage gap**: Pin versions panel and reorder buttons have model-layer tests but no AppTest smoke tests.
6. **Report title editing**: Business users cannot rename a report from the UI. A simple proposal path `"title"` with `new_value: str` would close this gap.
7. **Multi-page support**: `ExecutableReportSpec.pages` is a dict but the UI only renders `pages["main"]`. Round 016 could add a page-tab switcher.

### 015-F. Next Round Prompt

> Round 016 聚焦三件事：(1) **Cross-page global filter sync** — `ExecutableReportSpec` 加入 `global_filters: dict[str, FilterSpec]`，canvas 套用時同步到所有 page 的 visuals；(2) **Report title editing** — proposal path `"title"` with `new_value: str`，sidebar 加一個 text_input；(3) **created_at fix** — `DraftReportStore.save()` 只在 `audit.created_at is None` 時設定，確保初次儲存時間被保留。`AuditMetadata` 的 `PublishedReportStore.publish()` 也要同步設定 `created_by` / `last_modified_by` from `ANALYST_NAME`。Multi-page tab switcher 可作為次要目標。

---

## Round 016 — Global Filters, Title Editing, Multi-page Tabs, created_at Fix (2026-05-28)

### 016-A. Session Context

Round 016 continues from Round 015 baseline (261 tests). Three agents ran in parallel; all three completed.

### 016-B. Agents and Outcomes

| Agent ID | Task | Status | Tests Added |
| --- | --- | --- | --- |
| a0bdbf73fd7bad256 | 016-A Cross-page Global Filter Sync | Completed | +25 (286 total) |
| a71be6b5432a3ce9d | 016-B Report Title Editing + created_at Fix | Completed | +10 (271 total) |
| a7028f8405cc4458c | 016-C Multi-page Tab Switcher | Completed | +9 (295 total combined) |

**Final passing test count: 295**

### 016-C. Decisions Made

#### Cross-page Global Filter Sync (016-A)

- **`ExecutableReportSpec.global_filters: dict[str, Any]`** — new field, default `{}`. Keys are `"{block_id}.{column_name}"` strings; values are lists of allowed values.
- **`set_global_filter(key, values)`**: adds key if `values` non-empty; removes key on empty list.
- **`merged_filters()`**: returns `active_filters()` merged with `global_filters`; `global_filters` wins on conflict. Canvas uses `merged_filters()` for all query execution (replaces `active_filters()` calls in `app.py`).
- **Proposal path `"global_filters/{key}"`**: supported in `_get_path()` and `_set_path()` for atomic proposal-driven updates.
- **`build_global_filter_proposal(filter_key, before_values, after_values)`** in `builder.py`: `affects_data=True`.
- `to_dict()` / `from_dict()` backward-compatible: missing `"global_filters"` key deserializes to `{}`.

#### Report Title Editing + created_at Fix + PublishedReportStore ANALYST_NAME (016-B)

- **`"title"` proposal path**: `_get_path()` returns `report.title`; `_set_path()` sets it (raises `ReportValidationError` on empty/whitespace string).
- **`build_title_proposal(current_title, new_title)`** in `proposals.py`: `affects_data=False`.
- **Sidebar title widget**: `st.text_input("Report title", value=report.title)` in draft controls; on change stages a title proposal and reruns.
- **`created_at` fix**: `DraftReportStore.save()` sets `audit.created_at` only when it is `None` (first save); always updates `audit.last_modified_at`. Preserves original creation timestamp across subsequent saves.
- **`PublishedReportStore.publish()`**: sets `snapshot.audit.last_modified_by = os.environ.get("ANALYST_NAME", "unknown")` after copying the snapshot.

#### Multi-page Tab Switcher (016-C)

- **`ReportPageSpec.display_name: str = ""`** — new field. When empty, UI falls back to `page_id`. `to_dict()` / `from_dict()` backward-compatible.
- **`"pages/{page_id}/display_name"` proposal path**: supported in `_get_path()` and `_set_path()`.
- **`build_page_rename_proposal(page_id, current_name, new_name)`** in `proposals.py`: `affects_data=False`.
- **`ExecutableReportSpec.add_page(page_id, page_spec)`**: raises `ReportValidationError` if `page_id` already exists.
- **Canvas multi-page rendering**: single-page → renders directly (backward-compatible); multi-page → `st.tabs(tab_labels)` with one tab per page. Tab labels come from `display_name or page_id`. Button keys namespaced by `page_id` to avoid Streamlit key collisions.
- **Template**: `build_semiconductor_queue_time_report()` sets `display_name="ETCH Queue-Time"` on the `"main"` page.

### 016-D. Updated File Inventory

| File | Change | Purpose |
| --- | --- | --- |
| `ai4bi/report/models.py` | Modified | `global_filters`, `merged_filters()`, `set_global_filter()`, `display_name`, `add_page()`, title path, created_at fix |
| `ai4bi/report/proposals.py` | Modified | `build_title_proposal()`, `build_page_rename_proposal()` |
| `ai4bi/report/builder.py` | Modified | `build_global_filter_proposal()` |
| `ai4bi/report/templates.py` | Modified | `display_name="ETCH Queue-Time"` on main page |
| `ai4bi/ui/app.py` | Modified | `merged_filters()` in canvas, title text_input, `_render_page()` extraction, `st.tabs()` multi-page |
| `tests/test_global_filters.py` | New | 25 tests |
| `tests/test_title_and_audit.py` | New | 10 tests |
| `tests/test_multipage.py` | New | 9 tests |

### 016-E. Open Questions -> Round 017

1. **Undo after publish**: Publishing writes a permanent file. Should the undo stack treat publish as a reversible action? Current answer: no — publish is a lifecycle action, not a draft edit.
2. **Published snapshot browser UI**: `list_published()` exists but there is no UI to browse, compare, or restore published versions.
3. **Cross-filter broadcast**: `cross_filter_emit` on `VisualQuerySpec` (designed in earlier rounds) allows one visual's selection to filter others on the same page. This is not yet wired to `merged_filters()`.
4. **Page delete / hide**: `add_page()` exists but there is no `delete_page()`. A delete proposal with proper undo support is needed.
5. **Report-level metric summary**: No high-level "what metrics does this report cover?" view. A `ReportSummary` dataclass derived from the catalog at render time would help business users orient.
6. **AppTest coverage**: Pin versions panel, global filter widget, title input, and tab switcher all have model-layer tests but no Streamlit AppTest smoke tests.

### 016-F. Next Round Prompt

---

## Round 017 - Cross-Filter Broadcast, Page Delete, Published Snapshot Browser (2026-05-28)

Round 017 completed the three planned workstreams:

- `VisualQuerySpec.cross_filter_emit` plus page-scoped `st.session_state["cross_filters"]`.
- `ExecutableReportSpec.delete_page()` and proposal path `pages/{page_id}/delete`.
- `PublishedReportStore.load()` plus a sidebar Published versions browser and a published-readonly URL loader fix.

Validation:

- Focused gate: `python -m pytest tests/test_cross_filter_broadcast.py tests/test_page_delete.py tests/test_published_store.py -q` -> 23 passed.
- Full gate: `python -m pytest tests/ -q` -> 310 passed.

Round 018 candidates:

1. Add a derived `ReportSummary` view.
2. Add a governed restore-to-draft proposal for published snapshots.
3. Extend cross-filter emit support to table row selection.
4. Add AppTest coverage once published-store root injection is cleaner.

> Round 017 聚焦三件事：(1) **Cross-filter broadcast** — `VisualQuerySpec.cross_filter_emit: DimensionRef | None` 設計已存在；Round 017 把 emit 值寫入 `st.session_state["cross_filters"]` 並在 `merged_filters()` 中套用，讓一個 visual 的點擊可以 filter 同 page 其他 visuals；(2) **Page delete proposal** — `delete_page(page_id)` on `ExecutableReportSpec`，proposal path `"pages/{page_id}/delete"`，undo 可恢復整個 page；(3) **Published snapshot browser** — sidebar 加一個 "Published versions" expander，呼叫 `list_published()` 顯示時間戳清單，點擊 "Load" 可以 stage 一個 restore proposal（只讀預覽）。`ReportSummary` dataclass 可作為次要目標。

---

### Round 018 — Metric Catalog + Sandbox Visual Language

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 實作設計共識 003-E Metric Catalog 三分區 + 002-E Sandbox 視覺語言 |
| Agent perspectives | Architecture planning agent + NL2 scope analysis agent |
| Input | design-council-log.md 002-E, 003-E; 現有 BlockRegistry + DataBlockContract |

#### 018-A. 實作交付物

**新模組 `ai4bi/report/metric_catalog.py`**：
- `MetricZone` enum：`CERTIFIED_READY / NEEDS_BLOCKS / SANDBOX`
- `CatalogMetricEntry` dataclass：block_id, metric_name, display_name, aggregation, zone, missing_blocks
- `MetricCatalogService.classify(semantic_model, contracts) -> CatalogResult`
  - owner block lifecycle = certified AND all certified dim blocks → CERTIFIED_READY
  - owner certified but missing/non-certified dim blocks → NEEDS_BLOCKS
  - owner block 非 certified（validated/draft/etc.）→ SANDBOX

**`app.py` 新增功能（002-E + 003-E）**：
- `_is_sandbox_visual(visual, contracts)` — 逐 BlockRef 檢查 lifecycle
- `_has_sandbox_blocks(report, contracts)` — 全報表 sandbox 掃描
- `_render_sandbox_banner()` — 琥珀色不可關閉頂部橫幅（沙盒模式）
- `_render_metric_catalog_panel(report, cache)` — 三分區 sidebar expander
- `_render_page()` 更新 — 每個 sandbox visual 標題旁加 `🔬 實驗中` badge

**Publication Gate**：block_lifecycle check 已在 Round 013 實作，sandbox blocks 自動擋 publish（既有邏輯驗證正確）。

#### 018-B. 驗收測試

- **Unit tests** (`tests/test_metric_catalog.py`)：14 tests — 三分區分類、missing blocks、全 certified、全 sandbox、aggregation 提取
- **Playwright E2E** (`tests/e2e/test_round018_sandbox_ui.py`)：11 tests — banner 存在、三分區 catalog、sandbox badge、publication gate 封鎖

| 指標 | 結果 |
| Unit tests | 14 passed |
| Playwright E2E | 11 passed |
| Full regression | 329 passed |

#### 018-C. Demo 狀態說明

半導體 Demo 所有 block 均為 `validated`（非 `certified`），因此：
- Sandbox banner 永遠顯示（符合設計意圖，Demo 是 validated draft）
- Metric Catalog 所有指標顯示於 🟡 Sandbox 區（符合實際 lifecycle 狀態）
- Publication Gate 正確封鎖發布（block_lifecycle check 失敗）

#### Next Round Prompt

> Round 019：依據 NL2 Scope Analysis Agent 的評估，新增三個受治理的 NL2 intent：
> 1. `chart_type_change` — 「把這個改成長條圖」，affects_data=False，改 visualization.visual_type
> 2. `dimension_change` — 「改用月份分組」，affects_data=True，改 query/dimensions（僅允許 semantic model 已認證維度）
> 3. `add_metric` — 「也加上 move_count 指標」，affects_data=True，必須先驗證指標在 semantic model 中且 owner block 已認證
> 每個 intent 必須同時測試「non-certified 被拒」case（governance 防護）。

---

### Round 019 — NL2Proposal Enhancement: 3 New Governed Intents

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 依 AI Safety Agent 安全邊界設計，新增 chart_type_change / dimension_change / add_metric 三個受治理 NL2 intent |
| Agent perspectives | Architecture Agent (planning) + NL2 Safety Review Agent (governance boundaries) |
| Input | design-council-log.md 005-B Mock LLM Parser，NL2 safety review agent output |

#### 019-A. 三個新 Intent

**`chart_type_change`（bar ↔ line only，affects_data=False）**：
- 允許：bar ↔ line 互換（相同 query contract）
- 封鎖：table/kpi_card（不同 query contract；kpi_card 無 dimension，table 暴露 row-level data）
- path：`pages/{page_id}/visuals/{visual_id}/visualization/visual_type`
- 在 style_change 之前優先偵測（避免 "line"/"bar" 觸發顏色意圖）

**`dimension_change`（日期粒度，affects_data=True）**：
- 支援：月份/週/日/季/年 + 英文對應
- block_id 從 visual.query.metrics[0].block_id 推導（確保同 block）
- 找現有 dimensions 中的時間欄位，修改其 truncate_date_to
- 需確認 proposal → apply_report_proposal 完整 roundtrip

**`add_metric`（semantic model 雙重驗證，affects_data=True）**：
- 必須在 semantic_model["metrics"] 中存在 → 否則 GovernanceRefusal (risk=high)
- owner_block 必須已在 visual.query.block_refs → 否則 GovernanceRefusal (risk=high)
- 最多 3 個 metric per visual（設計共識 003-E）
- 不可新增重複 metric

#### 019-B. 模型層新增路徑

`models.py _get_path / _set_path` 新增：
- `pages/{page_id}/visuals/{visual_id}/visualization/visual_type`
- `pages/{page_id}/visuals/{visual_id}/query/metrics`

#### 019-C. Bug Fix

`_store_visual_assistant_context` 改用 `getattr` defensive access 防止 Streamlit hot-reload
module cache 導致的 `'ProposalResult' object has no attribute 'analysis_plan'` 錯誤。

#### 019-D. 驗收測試

- **Unit tests** (`tests/test_nl2_round019.py`)：28 tests — 所有 intent happy path + governance refusal + affects_data assertion + model path roundtrip
- **Playwright E2E** (`tests/e2e/test_round019_nl2_intents.py`)：10 tests — no-crash guarantee + SQL refusal + proposal workflow

| 指標 | 結果 |
| Unit tests | 357 passed (28 new) |
| Playwright E2E | 10 passed |

#### Next Round Candidates

1. **R2 Data Block View** — 獨立頁面或 tab 顯示 BlockRegistry 中所有 block 的 lifecycle/schema/metrics/relationships
2. **Breaking Change Detection** — `validate_upgrade()` 函數偵測 DataBlockContract 版本升級的 breaking vs non-breaking change
3. **Date Filter Intent** — NL2 第四個 intent：「只看最近 3 個月」→ 自動計算 from/to date 並加入 FilterSpec

---

### Round 020 — validate_upgrade() + Date Filter NL2 Intent

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 實作 004-A Breaking Change 偵測規則集；新增 NL2 date_filter_change intent（設計共識 005-B） |
| Agent perspectives | Round 020 Design Agent + Round 021 Data Block View Design Agent（parallel） |
| Input | design-council-log.md 004-A breaking change rules、005-B parser spec |

#### 020-A. validate_upgrade()（`ai4bi/blocks/upgrade_validator.py`）

設計共識 004-A 完整實作：

| 分類 | 例子 | 結果 |
|------|------|------|
| FORBIDDEN | block_id 改變、primary_keys 修改 | `is_valid=False`、errors 填入 |
| BREAKING | 刪除 metric/column、grain 變更、型別窄化、disaggregation_method/formula 變更 | `required_bump=major` |
| NON-BREAKING | 新增 metric/column → minor；description 修改 → patch | `is_valid=True` |
| NO CHANGE | 完全相同 | `required_bump=none` |

`UpgradeResult` 欄位：`is_valid, required_bump, breaking[], non_breaking[], forbidden[], errors[]`

#### 020-B. Date Filter NL2 Intent（`date_filter_change`）

使用 `global_filters/date_range` 路徑（現有 `_set_path` 完整支援），值存相對字串物件 `{anchor:"relative", period:"last_3m|last_quarter|ytd|..."}` — 不呼叫 `datetime.now()`，保持 deterministic。

支援關鍵字：最近3個月/last 3 months、上季/last quarter、今年/ytd、最近6個月、上個月 + clear 清除

- `affects_data=True`、`risk_level="low"`
- `intent_kind="analysis_request"`
- 清除（after=None）在無 date_range 時為 no-op

#### 020-C. 驗收測試

| 測試檔案 | Tests | 內容 |
|---------|-------|------|
| `tests/test_upgrade_validator.py` | 21 | forbidden/breaking/non-breaking/metadata |
| `tests/test_nl2_date_filter.py` | 33 | period detection (17 parametrize) + proposal structure + roundtrip + isolation |
| `tests/e2e/test_round020_date_filter.py` | 6 | no-crash + feedback visibility |

| 指標 | 結果 |
| Unit regression | 411 passed |
| E2E | 6 passed |

---

### Round 021 — Data Block View (Block Library Sidebar Panel)

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 實作設計共識 001-F Data Block View：業務可瀏覽可用積木、了解 grain/metrics/相容性/認證狀態 |
| Agent perspectives | Round 021 Data Block View Design Agent（選 Option C Sidebar Expander） |
| Input | design-council-log.md 001-F, 002-E, 003-E |

#### 021-A. 實作決策

設計 Agent 建議：**Option C（Sidebar Expander）** — 最小侵入，不動 canvas 邏輯，約 60 行。

理由：`main()` 已固定為 `st.columns([3,2])` 雙欄布局；多頁需 `st.navigation` 且 session_state 跨頁共享複雜；加 tab 需重構 canvas/assistant columns。

#### 021-B. 新模組與元件

**`ai4bi/report/block_library.py`**：
- `LIFECYCLE_BADGE`：覆蓋全部 5 個 LifecycleStatus，對應顏色/emoji（002-E 色彩規則）
- `BLOCK_TYPE_ICON`：覆蓋全部 10 個 BlockType
- `BlockCard` dataclass：`block_id, block_type, lifecycle, version, description, grain, metric_names, column_names, relationships`
  - properties：`type_icon, lifecycle_badge, is_certified, is_sandbox, header, summary_line`
- `build_block_library(contracts, search_query) -> list[BlockCard]`
  - 搜尋：case-insensitive，match block_id/type/description
  - 排序：certified → validated → draft → deprecated；同 lifecycle 再按 block_type + block_id

**`app.py` 新增 `_render_block_library_panel()`**：
- Sidebar expander "Data Block Library"
- `st.text_input` 搜尋框（placeholder "block name, type…"）
- 每個 block 一個 nested expander：lifecycle badge + type icon + summary line
  - 展開後：description、grain、metrics list、columns（前 8）、relationships

#### 021-C. 驗收測試

| 測試檔案 | Tests | 內容 |
|---------|-------|------|
| `tests/test_block_library.py` | 23 | badge/icon 完整性、build/search/sort、BlockCard properties |
| `tests/e2e/test_round021_block_library.py` | 9 | expander 存在、block 列表、lifecycle 顯示、search、expand card |

| 指標 | 結果 |
| Unit regression | 434 passed |
| E2E | 9 passed |

#### Next Round Candidates

1. **R2 Relationship View** — 在 Block Library 中加入 certified/uncertified relationship 視覺化（圖形或表格）
2. **NL2 Composition Planner** — 業務輸入「把 queue time 和 yield rate 放在同一張圖」→ AI 判斷是否有 certified 關聯，建立 CompositionProposal
3. **DQ Status Badges** — 依 Data Quality 四等級（004-E）在 Block Library 和 Canvas 顯示資料新鮮度警示

---

### Round 022 — NL2 Expanded Intent Coverage

| 欄位 | 記錄 |
| --- | --- |
| Status | `completed` |
| Date | `2026-05-28` |
| Goal | 修復「只有特定功能可以調整」的問題 — 新增 5 個缺失的 NL2 intents，擴大用戶可以用自然語言操作的範圍 |
| Agent perspectives | Safety Design Agent（categorical dim / value filter / remove metric / rename 安全邊界） |
| Trigger | 用戶反映只有顏色、圖表類型、日期粒度可調整，其他操作都回傳 unsupported |

#### 022-A. 根本原因分析

NL2ProposalService 是**純確定性規則系統**（無 LLM），每個 intent 需要明確的關鍵字 patterns + 安全邊界。以下功能之前完全缺失：

| 缺失功能 | 狀態 → 修復後 |
|---------|------------|
| `add metric move_count`（無前綴） | UNSUPPORTED → PROPOSAL |
| `rename this chart to X` | UNSUPPORTED → PROPOSAL |
| `remove queue_time_hr` | UNSUPPORTED → PROPOSAL（≥1 guard） |
| `group by product family` | UNSUPPORTED → PROPOSAL（certified whitelist） |
| `only show PHOTO` | UNSUPPORTED → PROPOSAL（query/filters） |

#### 022-B. 新增 Intents 與安全邊界

**`rename_visual`** (affects_data=False)：
- path 已存在（visualization/title）
- XSS strip：`re.sub(r"<[^>]+>", "", title)[:80]`
- rename 檢查在 queue_analysis 之前（防止「rename to Queue Trend」誤觸發分析）

**`remove_metric`** (affects_data=True)：
- 最後一個 metric → GovernanceRefusal（risk=medium）
- path：`query/metrics`（現有），before/after list

**`categorical_dimension_change`** (affects_data=True)：
- block_id 必須在 semantic_model certified relationships 中 → 否則 GovernanceRefusal（risk=high）
- 支援：product_family / vendor / tool_id / step_name / lot_id + 中英文關鍵字

**`value_filter_change`** (affects_data=True)：
- 新增 `query/filters` path 支援（`_get_path`/`_set_path`）
- 支援：PHOTO / ETCH / CVD / CMP / IMPLANT → step_id IN filter
- Logic-A/B 排除（由 controls 機制處理）

**`add_metric` 關鍵字擴充**：
- 新增 8 個 regex pattern，支援 "add move_count"（snake_case），"add metric X"

#### 022-C. Intent 路由優先順序修正

```
rename_visual (FIRST — 防止 "rename to Queue Trend" 被 queue_analysis 截取)
→ chart_type_change
→ style_change
→ date_filter_change
→ queue_analysis (BEFORE categorical — 防止 "analyze...by tool" 被截取)
→ remove_metric
→ categorical_dimension_change
→ value_filter_change
→ add_metric
→ unsupported
```

#### 022-D. 驗收測試

| 指標 | 結果 |
| Unit regression | 473 passed |
| E2E (13 new) | 13 passed |
