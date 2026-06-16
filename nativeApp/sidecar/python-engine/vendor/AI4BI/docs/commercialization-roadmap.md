# AI4BI 商用化需求深度討論報告

**日期：** 2026-05-29  
**討論規模：** 8 個 Agent，3 輪深度討論  
**角色組成：** 財務分析師、IT 採購主管、中小企業老闆、資料工程師、零售副總、商用化顧問、技術架構師、UX/Growth PM  
**核心問題：** 這個工具如何從 demo 工具走向真正商用化？Excel 更完整的問題怎麼解決？

---

## 執行摘要（給決策者看的版本）

### 現狀診斷

> **這個工具目前有「產品人格分裂症」。**  
> 技術架構像內部工具、UI 像 demo、安全設計是假的，但定位想打企業市場。三個市場都做不好。

### 商用化路徑的核心決策

| 決策 | 選擇 | 理由 |
|---|---|---|
| **目標市場** | 50-500 人零售/電商/連鎖品牌的老闆或營運副總 | 有預算、有痛點、沒有 IT 守門員 |
| **Go-to-market** | PLG（Product-Led Growth），信用卡訂閱 | 繞過企業採購流程，先活下去 |
| **定價** | NT$8,000/月，14 天免費試用 | 相當於半個兼職分析師，合理 ROI |
| **核心承諾** | 上傳 CSV → 5 分鐘內得到可信答案 | 解決所有角色共同的「信任赤字」問題 |
| **最大競爭者** | Excel + 人工整理 | 不是 Power BI，是老闆每週叫員工做的報表 |

### 最重要的一個洞見

> 用戶不是說不出問題，是他**不知道該從哪裡問起**。  
> 工具必須在用戶問問題之前，主動說：「你的資料有一個異常，你要看嗎？」  
> 從「問答工具」到「AI 分析師」，這是商用化成敗的分水嶺。

---

## Round 1：五個利害關係人的誠實評估

### 🧮 財務分析師（12 年 Excel 經驗）

**Excel 目前不可替代的 5 件事：**

1. **What-If 分析**：換一個假設值，整個模型即時更新。AI4BI 的 `DisaggregationMethod` 沒有「參數輸入→即時試算」的概念。

2. **公式可視性**：P&L 表格裡，能同時看到 EBITDA 數字和它背後的 DEPRECIATION 輸入值，並且直接修改。AI4BI 的數字在 `_build_metric_expr()` 生成後，外部完全不透明。

3. **Multi-sheet 相互引用**：原料單價 × BOM × P&L 三張表形成一個模型。AI4BI 的 Block join 被 `FanoutRisk.BLOCKED` 擋住，複雜的商業邏輯 join 做不了。

4. **手動標記 + 彈性**：Excel 允許在某個異常格子旁邊加紅色警示和文字批注，做稽核追蹤。AI4BI 沒有任何用戶標注機制。

5. **離線作業**：出差搭飛機可以做完整的季度報告。Streamlit 需要伺服器連線。

**AI4BI 真正贏過 Excel 的場景：**
> 主管在會議中說「換成 Vendor 視角看看」，Excel 要花 5 分鐘調整 Pivot Table，AI4BI 說一句話就完成，而且有 governance 保護不會出錯。**即時、受控的 ad-hoc 分析是真正的差異化**。

**最大的不信任點：**
> `upload.py` 的 `infer_block()` 把所有 numeric columns 用 `SUM`。上傳「毛利率（0.35）」和「退貨率（0.02）」，系統加總顯示「毛利率合計 = 47.3」。這種數字出現一次，財務分析師永遠不會再信任這個工具。

**能讓他每天使用的單一功能：**
> 點任何一個數字，彈出視窗顯示：原始行資料 + 套用的公式 + 篩選條件——類似 Excel 的「追蹤前導參照」。

---

### 🔒 IT 採購主管（企業 2000 人規模）

**合規審查結果（9 項）：**

| 合規項目 | 狀況 | 嚴重程度 |
|---|---|---|
| SSO/SAML/LDAP | ❌ 無（`created_by = "unknown"`） | 🔴 封鎖 |
| RBAC 角色權限 | ❌ 假的（`_check_policy()` 寫死 `passed=True`） | 🔴 封鎖 |
| TLS/HTTPS | ❌ Streamlit 預設 HTTP | 🔴 封鎖 |
| 資料儲存位置 | ❌ 本機 JSON 檔，無備份 | 🟠 嚴重 |
| 稽核日誌 | ⚠️ 可被覆寫的 JSON，非 immutable | 🟠 嚴重 |
| LLM API 資料外送 | ⚠️ 查詢送 Anthropic，無 DPA | 🟠 嚴重 |
| SOC 2 / ISO 27001 | ❌ v0.1.0 開源，完全無 | 🔴 封鎖 |
| Session 隔離 | ❌ 無 multi-tenancy | 🟠 嚴重 |
| 地理資料落地 | ❌ 無任何聲明 | 🟡 關注 |

**最直接的 Deal Breaker：**
> RBAC 是假的——`publication.py` 的 `_check_policy()` 明確寫著「Not yet enforced」並直接回傳 `passed=True`。這意味著 HR 資料、財務數字可以被任何有工具存取權的人發布和分享。**這一條我不用看其他的，直接否決。**

**結論：** IT 採購路線現在完全不可行。必須先打 PLG 路線，企業合規是 Series A 之後的事。

---

### 🏪 中小企業老闆（電商，15 人，非技術背景）

**第一次使用的真實旅程：**

1. 上傳 CSV：成功
2. 看到「Block ID（識別碼）」輸入框：不知道要打什麼
3. 看到指標/維度分類：不確定對不對，直接按「匯入」
4. 回到主畫面：顯示半導體 Demo 報表，**完全不知道下一步**
5. 結局：關掉視窗，繼續用 Google Sheets

**看不懂的術語（完整清單）：**
Block、Block ID、Block Library、DataBlockContract、grain、LifecycleStatus、Draft/Certified 狀態、semantic_model_ref、validate_upgrade、Publication Gate...

**願意付費的三個核心需求：**

| 需求 | 說明 | 月付金額 |
|---|---|---|
| NL 問答→圖表 | 打一句話，立刻出圖，不需要任何設定 | - |
| 每日 Email 摘要 | 早上自動寄：昨天業績 + 前三名商品 + 跟上週比 | - |
| Alert 功能 | 庫存低於 X、業績低於 Y 自動通知 | - |
| **以上三件事都做到** | - | **NT$2,000–3,000/月** |

**永不回來的條件：**
> 數字錯一次。我是老闆，我不 debug，數字一錯我可能還帶著錯誤數字做了錯誤決定，這不是工具的問題，這是我的責任問題。所以數字錯一次就永遠不信任。

---

### 🔧 Senior Data Engineer（dbt / Airflow / DuckDB 熟悉）

**生產部署清單（「只適合 demo」的設計）：**

| 問題 | 程式碼位置 | 生產需要什麼 |
|---|---|---|
| InlineDataSource 塞資料進 JSON | `contracts.py` | ExternalDataSource + S3 Parquet 路徑 |
| 每次 query 建新 `:memory:` DuckDB 連線 | `executor.py:344` | 持久化 connection，資料 register 一次 |
| `_DEFAULT_REGISTRY` 指向測試夾具 | `executor.py:31` | 環境變數 `AI4BI_REGISTRY_ROOT` |
| `row_filter_expr` + `allowed_roles` 定義了但 executor 完全忽略 | `executor.py` | 必須在 `_build_sql()` 注入，接 identity provider |
| 無 secrets 管理 | `pyproject.toml` | AWS Secrets Manager / Vault |
| 無 REST API，全是 Streamlit callback | 整個 app | FastAPI 層才能接 Airflow/dbt 觸發 |

**可擴展性（1000 並發）：**
- Streamlit 是 per-session 單 thread model，1000 並發 = 1000 threads，OS context switch 爆炸
- DuckDB 掃 100M row Parquet 單機可行（3-30 秒），但 1000 並發同時掃不行
- 解法：Streamlit 只做 UI，加 FastAPI async backend + query queue

**DuckDB 接 dbt + S3 的改動：**
`BlockLoader.register_to_duckdb()` 加 `elif source_type == "data_ref"` 分支，呼叫 `duckdb.read_parquet("s3://...")` + DuckDB httpfs extension，約 30 行。Contract schema 已預留，只差實作。

---

### 🏬 零售連鎖副總（50 家門市，非技術背景）

**三個業務問題的回答：**

| 問題 | 能做嗎？ | 阻礙 |
|---|---|---|
| 每人工時銷售額 = POS ÷ HR | ❌ | `_build_metric_expr()` 強制 metric 只能來自 primary_block_id；兩個 fact block 相除被架構禁止 |
| 缺貨 vs NPS（只有 store_id 可對應）| ❌ | 兩個 fact block 無 join 鍵，`SafeJoinPlanner` 視為 BLOCKED fanout |
| 促銷轉換率（有購買/到訪）| ❌ | 「到訪」欄位不存在 POS 資料；且轉換率 = A/B 的除法指標架構無法處理 |

**三個問題都答不了的根本原因：**
工具的「安全語言」只懂同一個系統內的數字，不懂「把不同系統的數字放在一起看」的業務邏輯。

**最有價值的 AI 功能（不是你問它答）：**
> 「你的台中店上週四有個異常，缺貨次數突然暴增，同期 NPS 下滑 12 分，建議立即關注。」——**主動發現你還沒意識到的問題。**

**願意付的價格：**
> 三個問題全答得了，一個月 NT$5–15 萬。比現在的 BI 工具授權費 + 養一個分析師的總成本，其實差不多甚至更少。但是它主動告訴你，而不是等你去問。

---

## Round 2：交叉辯論的關鍵洞見

### 矛盾 1：IT 主管說「全是假的」vs 零售副總說「我願意付錢」

**解析：** 這兩個人根本不在同一條購買路徑上。

- IT 主管 = 守門員，工作是說不，走「合規審查→採購簽字」路線
- 零售副總 = 預算持有者，邏輯是「數字對就付錢」，走「試用→信用卡→訂閱」路線

**商業策略結論：** Phase 1 完全不打 IT 採購路線。PLG 直接到決策者，繞過 IT 部門。

### 矛盾 2：技術架構師說「多資料源現在就能做」vs 老闆說「不知道下一步」

**解析：** 架構師說的是後端技術可行性（每個 VisualQuerySpec 獨立執行），但他沒考慮 UX 流程。用戶建第二張來自不同資料源的圖時，沒有任何 UI 引導。

**結論：** "Technically possible, UX impossible" ——架構支援 ≠ 用戶能完成任務。

### 洞見 1：5 個人用不同語言說了同一件事

| 角色 | 說的話 | 共同指向 |
|---|---|---|
| 財務分析師 | 毛利率被加總成 347% | 數字不可信 |
| IT 主管 | RBAC 是假的 | 數字不可信 |
| 中小企業老闆 | 數字錯一次永遠不回來 | 數字不可信 |
| 資料工程師 | row_filter 定義了但沒執行 | 數字不可信 |
| 零售副總 | 三個問題都答不了 | 數字不可信 |

> **核心診斷：這個系統有信任赤字（Trust Deficit）。**  
> 商業 BI 工具賣的從來不是圖表，而是「這個數字可以拿去開董事會」的信心。

### 洞見 2：Date Grain 混排是最危險的靜默錯誤

分析師改了一張圖從月份→週，其他圖還停在月份。同一個 dashboard 出現月 vs 週混排，沒有任何警示。分析師比對數字得出錯誤結論而不自知。

> 這比 cross-filtering 缺失更隱蔽、更危險。成本低（加一個 page-level grain 一致性警示），CP 值極高。

### 洞見 3：Cross-filter 的真正難點

`cross_filter_emit` schema 存在只解決了「誰發出訊號」。真正的難點是：

> 如果目標 chart 的 x 軸來自跨 join 的 derived column（例如 `region` 來自 dim_table），filter 要往哪個 table 打、用哪個 key join？這需要**執行時動態重建 query plan**，不是 session state 的問題。

還有三個 Round 1 沒說清楚的複雜度：
1. **Filter state reconciliation**：兩個 chart 同時 emit 不同 filter 值，需要 last-write-wins 策略
2. **Multi-page isolation**：cross-page filter 穿透邊界未定義
3. **Circular filter 防止**：A filter→B，B 又 emit 回 A，需要 DAG cycle detection

---

## Round 3：商用化路線圖

### 完整的 0→1 用戶旅程（解決所有 Agent 提出的問題）

```
Step 1：歡迎畫面（0:00）
━━━━━━━━━━━━━━━━━━━━━━
用戶看到：畫面中央「把你的銷售表丟進來吧」
         大型橙色拖曳區域（或「先看 Demo 版」小字連結）
         Sidebar 完全收起不干擾
AI 做什麼：等待。什麼都不做。
───────────────────────────────

Step 2：數字健康檢查（上傳後，0:30–1:00）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用戶看到：「AI 讀懂了這些」卡片
         大字：「你有 12 週的銷售資料，涵蓋 5 家門市。」
         ⚠️ 黃色標注：「毛利率、退貨率：我把它們當比率處理，
           不會直接加總。如果不對，點這裡修正。」
         ✅ 其他欄位：「銷售金額、訂單數 → 加總計算」
         → 按鈕：「這樣對，繼續」
AI 做什麼：pandas profiler 掃描 + 欄名 regex 偵測比率欄位
           + grain 推斷（日期+門市+SKU 組合）
           + 主動跑一次標準差偵測，找異常（背景執行）
技術需要：upload.py 加 _detect_ratio_columns()（~25 行）
───────────────────────────────

Step 3：AI 主動給你三個觀察（1:00–2:00）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用戶看到：三張藍色卡片，例：
  📊「台中店上週缺貨次數比平常高 3 倍」
  📈「整體業績本月比上月成長 12%」  
  ⚠️「退貨率異常：某 SKU 退貨率是平均的 4 倍」
  → 按鈕「看這張圖」旁邊有「問 AI 更多」
AI 做什麼：自動執行異常偵測（DuckDB 標準差查詢）
           + generate_suggestions() 生成建議圖表
技術需要：suggestions.py 加異常偵測路徑（~40 行）
  關鍵：這一步讓用戶在還沒問問題之前就有 aha moment
───────────────────────────────

Step 4：用戶的第一個問題（2:00–4:00）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用戶看到：文字輸入框：「問我任何問題」
         下方有 3 個建議按鈕（由資料內容動態生成）：
         「哪個門市本月業績最差？」
         「哪個商品退貨率最高？」
         「本季 vs 上季整體業績？」
AI 做什麼：NL2Proposal → 執行前顯示摘要：
           「我會計算：各門市本月銷售額加總（排除比率欄位）」
           → 用戶確認後才執行
技術需要：NL2 加「執行前確認」步驟（~20 行）
───────────────────────────────

Step 5：可信的答案（4:00–5:00）
━━━━━━━━━━━━━━━━━━━━━━━━━━━
用戶看到：圖表 + 一句話摘要：
          「台北信義店本月業績 $3.2M，比第二名高 28%」
          圖表下方：「↓ 這個數字怎麼算的」（展開後顯示：
            「843 筆訂單的銷售金額加總，計算時間 14:23，
             已排除退貨金額」—— 不出現 SQL，只有白話說明）
          右下角：「⬇ 下載 CSV」
技術需要：ResultMetadata 轉人話 _humanize_metadata()（~25 行）
```

> **核心設計原則：** 用戶在整個旅程中，不需要理解 Block、grain、VisualQuerySpec 任何一個術語。

---

### v1.0 商用必要功能清單

#### 🔴 Must-Have（沒有這個，第一個付費用戶就會退款）

| 功能 | 說明 | 技術工時估計 |
|---|---|---|
| 比率欄位自動偵測 + 警示 | 避免「毛利率加總 = 347%」 | 2-3 天 |
| 答案溯源白話說明 | 每個數字能展開看「怎麼算的」（非 SQL，是白話） | 3-4 天 |
| 上傳後 5 分鐘出第一張有意義的圖 | 自動呼叫 `build_report_from_block()` | 1 天 |
| AI 主動給三個觀察（資料上傳後立即）| 異常偵測 + 摘要推送 | 4-5 天 |
| 術語完全從 UI 消失 | Block、grain 等只存在程式碼，不出現在 UI | 3-5 天（翻譯層）|
| Date Grain 混排警示 | 同頁多圖使用不同時間粒度時，顯示橙色警告 | 1-2 天 |
| 行動版基本可讀 | 老闆在手機上看報告 | 2-3 天（Streamlit CSS）|

#### 🟡 Should-Have（影響 80% 續約率）

| 功能 | 說明 |
|---|---|
| 週期對比（本週 vs 上週）一鍵切換 | 用戶最常問的問題類型 |
| 每日/每週 Email 摘要排程 | 中小企業老闆的核心需求 |
| Alert 閾值設定 | 「業績低於 X 時通知我」 |
| 問題歷史記錄（Chat History）| 讓用戶感覺 AI 認識他 |
| 多 CSV 自動對應（有 store_id 就連起來） | 解鎖部分 cross-fact 場景 |
| 動態 NL2 維度關鍵字（從 schema 自動推導）| 讓 NL2 能理解任意 CSV 的欄位名稱 |

#### 🟢 Nice-to-Have（口碑傳播）

| 功能 | 說明 |
|---|---|
| 一鍵分享圖表到 Line 群組 | 零售業老闆分享給門市主管 |
| What-If 模擬（參數滑桿）| 「如果折扣率改成 20%，利潤變多少」 |
| 語音輸入問問題 | 老闆開車時問問題 |
| AI 自動寫報告摘要（PDF 格式）| 月底彙報用 |

---

### 現有架構的評估：保留 / 擴充 / 拆掉重做

#### ✅ 保留（已是正確方向）

| 模組 | 理由 |
|---|---|
| `ResultMetadata`（blocks_used、row_count、executed_at）| 溯源設計正確，只差前端渲染成白話 |
| `DisaggregationMethod` + `_APPROVED_AGGREGATIONS` | 聚合守門機制是對的，是信任赤字的核心防線 |
| `GovernanceRefusal` 結構 | 拒絕不安全查詢的設計方向正確 |
| `DataBlockContract` schema | Pydantic v2 + discriminated union 設計清晰 |
| `ExternalDataSource` 欄位（`path`、`connection_id`、`query`）| 擴展點已預留，只差實作 |

#### 🔧 擴充（方向對，需要更多）

| 模組 | 需要什麼擴充 |
|---|---|
| `NL2ProposalService` | 加「執行前確認摘要」層；動態 dim 關鍵字從 schema 推導（~150 行）|
| `executor.py` quality_warnings | 真正執行欄位類型守門，填滿 `quality_warnings`（~30 行）|
| `suggestions.py` | 改成「根據上傳資料動態生成」 + 加異常偵測路徑（~40 行）|
| `upload.py` | 加比率欄位偵測 + 上傳後自動建報表的流程（~60 行）|
| `render_visual.py` | 把 ResultMetadata 渲染成用戶看得懂的白話句子（~25 行）|

#### 🗑️ 拆掉重做（繼續下去是技術債）

| 設計問題 | 影響 | 正確方案 |
|---|---|---|
| `_DEMO_ROOT` 硬寫死在 `app.py` | 用戶 CSV 是事後補丁，demo 是第一公民；必須反過來 | CSV 上傳是第一公民，demo 是「示範資料集」選項之一 |
| `InlineDataSource` 把 records 塞進 Pydantic model | 50,000 行 × N columns 在每次 rerender 都帶著走，v2.0 多個 CSV 就 OOM | records 改為 content-hash 指向 `st.cache_data` 的 DataFrame，DataBlockContract 只存 schema |
| `_CATEGORICAL_DIM_MAP` / `_DIM_KEYWORD_MAP` hardcode | NL2 只懂半導體 demo，用戶的 CSV 完全無法用 NL | 從 user blocks 動態生成倒排索引（~60 行替換現有靜態 dict）|
| 技術術語直接外露到 UI | Block、grain 滲透用戶界面，非技術用戶直接放棄 | UI 語意翻譯層，把所有內部術語在渲染前轉成業務語言 |
| `_check_policy()` 回傳 `passed=True` | 這不是「未實作」，這是積極的錯誤聲明（actively wrong） | Phase 1 PLG 可以先限制功能而非假裝有安全；至少改成 `not_enforced` 而非 `passed` |

---

### 技術立即 Fix 清單（< 1 sprint，不 fix 第一個客戶就出事）

```python
# Fix 1: 比率欄位偵測 (upload.py, ~25 行)
_RATIO_PATTERNS = re.compile(
    r"\b(rate|ratio|pct|percent|margin|yield|utiliz|efficiency|coverage)\b", re.I
)
def _detect_col_type(col_name, dtype):
    if _RATIO_PATTERNS.search(col_name):
        return DisaggregationMethod.average  # 不加總
    ...

# Fix 2: 持久化 DuckDB 連線 (executor.py, ~10 行)
def __init__(self, ...):
    self._conn = duckdb.connect(database=":memory:")
    # register once, query many times
    
# Fix 3: 上傳後自動建報表 (upload.py, ~30 行)
if st.button("匯入"):
    st.session_state[_USER_BLOCKS_KEY][block_id] = contract
    new_report = build_report_from_block(contract, metric_names, dim_names)
    workspace.replace_with_loaded(new_report)  # 直接跳到報表
    st.rerun()

# Fix 4: LLM 例外 logging (llm_adapter.py, 1 行)
except Exception as exc:
    logger.warning("[llm_adapter] LLM call failed, falling back to mock: %s", exc)
```

---

### UX 革命：讓非技術用戶 5 分鐘成功的設計原則

**原則 1：先給價值，後要求行動（Canva / Airtable 模式）**
> 預載一份「零售業示範資料」，讓用戶不需要上傳任何東西就能體驗完整功能。  
> 當用戶問出第一個問題並看到圖表後，才輕輕問：「換成你自己的數字？」

**原則 2：主動摘要（Notion AI 模式）**
> 圖表生成後，AI 自動在上方寫一句話洞察，用戶不用自己解讀數字。

**原則 3：建議下一步（ChatGPT 模式）**
> 每次回答後顯示 2-3 個後續問題建議，讓用戶感覺「AI 在帶著我走」。

**原則 4：記憶回放（黏著感）**
> 用戶回來繼續使用時：「上次你問過：哪個門市業績最好。要繼續嗎？」

**最反直覺但最重要的設計：讓第一次不需要上傳任何東西。**

---

## 被低估的根本風險

### 風險 1：「正確但無感」（最可能導致失敗）

> 功能全做對了，用戶在 14 天試用結束時仍然不續約。  
> 原因：用戶從來沒有感受到「AI 幫我發現了一件我不知道的事」。

現有架構是「回答用戶問的問題」，但零售老闆第一次用時不知道要問什麼。  
**他們需要的第一個時刻不是「我問、它答」，而是「它主動說：你有一個異常，要看嗎？」**

解法：資料上傳後立刻跑異常偵測，主動給三條觀察。成本：DuckDB 標準差查詢 ~40 行。

### 風險 2：`InlineDataSource` 的時間炸彈

`DataBlockContract` 把 50,000 rows 的 dict list 存在 Pydantic model 裡，每次 rerender 都帶著走。v1.0 可能 OK，v2.0 多個 CSV + 定期刷新就 OOM。

**在 v1.0 前改掉代價：~40 行。在 v2.0 後改代價：3-5x，影響 executor + loader + upload + session_state 全部。**

### 風險 3：產品定位的「慣性漂移」

> 如果繼續增加功能而不確立「誰是我的唯一目標用戶」，這個工具會繼續在工程師欽佩架構、IT 主管通過合規審查、老闆第一次使用成功三個目標之間搖擺，最終三個都做不到。

**解法：砍掉一切，只服務一個人，讓那個人的第一個問題得到一個可信的答案。**

---

## 商用化路線圖建議

### Phase 1：信任建立（0→10 個付費用戶，1-2 個月）

**目標：** 讓第一個零售業老闆用 14 天試用，並在試用結束後續約。

**必做清單：**
1. ✅ 比率欄位偵測（25 行）
2. ✅ 上傳後自動建報表（30 行）
3. ✅ 主動異常偵測（40 行）
4. ✅ 答案白話溯源句（25 行）
5. ✅ 移除所有技術術語出現在 UI 的地方
6. ✅ Demo 資料改成零售業格式（不再是半導體）
7. ✅ 預載 Demo 模式（不需要上傳就能體驗）

### Phase 2：黏著度（10→100 用戶，3-4 個月）

**目標：** 週使用率 > 3 次，Net Revenue Retention > 100%

**必做清單：**
1. 週期對比（本週 vs 上週）
2. Email 摘要排程
3. Alert 功能
4. 動態 NL2（從用戶 schema 推導關鍵字）
5. InlineDataSource → cache_data 重構

### Phase 3：平台化（100→1000 用戶，6-12 個月）

**目標：** 能服務有 IT 部門的中型企業

**必做清單：**
1. SSO/SAML（最基本的企業入場券）
2. ExternalDataSource 連接器（PostgreSQL 優先）
3. 真正的 RBAC（不是 `passed=True`）
4. SemanticPlanner 中間層（解鎖 cross-fact 計算）
5. REST API（接 dbt / Airflow 生態）
6. Multi-tenancy

---

## 附錄：與 Excel 的定位對比

| 場景 | Excel 更好 | AI4BI 更好（達到商用後）|
|---|---|---|
| 複雜財務模型（What-If 分析）| ✅ | |
| 多 sheet 相互引用公式 | ✅ | |
| 離線作業 | ✅ | |
| 手動調整個別數值 | ✅ | |
| 小於 50 行的資料集 | ✅ | |
| 主動發現資料異常 | | ✅ |
| 非技術用戶自助分析 | | ✅（Phase 1 目標）|
| 多人同時看同一份 dashboard | | ✅ |
| 追蹤數字的治理紀錄（誰查過什麼）| | ✅ |
| 會議中即時調整分析視角 | | ✅ |
| 連接多個 CSV 並自動對齊 | | ✅（Phase 2）|

> **結論：** AI4BI 不需要贏過 Excel，只需要在「老闆想了解業務數字但不想手動做報表」這個場景裡，成為 Excel 的替代品。這個場景，每間公司每個月都在發生，而且願意付錢。
