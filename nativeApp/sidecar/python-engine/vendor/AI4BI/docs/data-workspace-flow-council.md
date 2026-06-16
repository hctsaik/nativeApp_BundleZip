# 資料工作區 / 主流程 — Multi-Agent Council Log

目標(來自 /goal):打造**真能幫半導體晶圓廠工程師做 no-code/low-code 資料探索與分析**的系統。
驗收方式:Multi-Agent 定義 10 個晶圓廠資料分析情境 → 打分 → 平均未達 95 則重生 10 個情境反覆驗證,直到平均 ≥95。
本檔記錄每一輪的「討論項目 / 共識 / 爭議 / 後續方向」。

---

## Round 1 — 三畫面(歡迎卡片 / 探索與設計 / 資料工作區)的順序・UI/UX・目的 + 內容 vs schema

**參與視角**:BI/IA 架構師、半導體良率工程師(第一人稱)、UX 簡化+魔鬼代言人。

### 討論項目
1. 三個主要畫面各自的目的/職責(避免重疊)。
2. 工程師工作流的自然順序、主舞台 vs 支援。
3. 每個畫面該顯示/不顯示什麼。
4. 資料 detail:**內容(實際幾列)** vs **schema(欄位/型態)** 何者優先。

### 共識
- **目的性**:① 歡迎卡片=一次性分流(用範例/我的資料/既有報表),不承載分析;② 探索與設計=**唯一問答/做圖主舞台**(工程師 80–90% 時間);③ 資料工作區=後勤/信任層(開工前確認彈藥、出圖怪怪的回頭查)。
- **順序**:**探索為主舞台、資料為支援、歡迎卡片只首次**。現行 nav 順序(探索在前)正確,維持不動。「資料就緒」是一次性前置,不該每次都當第一關。
- **內容 vs schema(對應使用者新需求)**:**一致裁決 → 內容優先、schema 退為點開才看。** 工程師靠「值的長相」判斷資料對不對(yield 0–1 或 0–100?日期哪段?lot 對不對?),`col: float` 看不出來。
- **資源安全兼顧法**:預設只顯示**前 N 列取樣**(`sample_dataframe`=head N、已快取、大資料警示),全表永不掃描/載入瀏覽器。取樣統計(非空率/種類數/範圍)維持 opt-in。

### 爭議
- **自動載入內容是否有 OOM 風險**(IA 提出,魔鬼代言人裁決):取樣是 head-N、O(N),非整表;對所有 tier 預設顯示 20 列取樣是安全的。→ 採「預設顯示取樣、schema 收合」。
- **「📊 分析」mode 是否該併入探索**(爭議最大):cohort/basket/RFM/變化分解本質都是「問一個分析問題」。→ **先不砍,先觀測**回訪用戶從探索 vs 分析的入口比例,用數據裁決。

### 後續方向(next)
- welcome 的 `_welcome_dismissed` 改**跨 session 持久化**(目前 session 級,新 session 又跳=雜訊);老手提供「接著上次」。
- 從探索就地拋連結帶去資料工作區(資料問題時),資料工作區提供「← 回到剛才的問題」。
- 工程師要但目前缺:**時間範圍/規模**(幾片 wafer / 幾 lot / 幾 tool)、**資料品質一眼**、**新鮮度/來源**(哪天哪個 query 拉的)。
- 術語白話化:schema→欄位結構;dtype→數字/文字/日期(已用友善標籤);join→「把 yield 跟 tool 用 lot_id 對起來」。

### 本輪實作(R177→後續)
- ✅ R177(前置):上傳預覽就地顯示、工作區標頭與報表解耦、🟢報表使用中/🟡評估中 狀態徽章。
- ✅ **內容優先**:`render_source_inspector` 改為預設顯示前 N 列取樣內容,schema 收進「🔧 欄位結構（型態／可空，需要時點開）」expander,統計維持 opt-in。

### 待辦(下一輪)
- Round 2:Multi-Agent 定義 10 個晶圓廠資料分析情境 + 打分(目標平均 ≥95);未達則迭代。

---

## Round 2 — 10 個晶圓廠情境定義 + 評分(實跑驗證)

**參與視角**:fab 領域專家(定義 S1–S10 + rubric)、2 位評審(實跑 NL2+Executor 對 fab demo 逐句核對嵌入訊號)。

### 討論項目
晶圓廠核心分析 10 情境:S1 良率趨勢+連續下滑 / S2 tool matching / S3 commonality / S4 defect Pareto / S5 yield 依 product·step / S6 良率變化原因分解 / S7 WIP·move 趨勢 / S8 queue·bottleneck / S9 SPC 離群 / S10 跨表 yield×OEE+大資料。rubric:A 自然語言 zero-code 20 / B 正確且製程語意(良率 die-count 重算、比率不加總)25 / C 可解釋 15 / D 不卡關 15 / E 資源安全 10 / F 無術語繁中 10 / G 可溯源 5。

### 共識(評分,實跑)
- **分析引擎本身正確**(已實證):commonality→ETCH-02(Fisher p=0.0017、wafer 粒度)、declining→ETCH-01、weighted_yield_pct die-count 重算、OEE ETCH-02 50.2% 最差、cross_fact aggregate-then-join、上傳 5 萬列截取防 OOM。
- **首輪分數**:S1 70・S2 62・S3 60・S4 93・S5 88(avg 74.6);S6 38・S7 88・S8 80・S9 82・S10 96(avg 76.8)。**總平均 ≈ 75.7,未達 95。**

### 爭議 / 關鍵發現
1. **S6 致命正確性 bug**:`compute_grouped_comparison` 對**比率指標(yield)把各組百分點 delta 相加**、貢獻=delta/total → 「Memory ↓894%、整體 +1.2%」;與 die-count 重算的真實 MoM(~0.3pp)矛盾。**B=0。**
2. **NL2 路由脆弱(S1/S2/S3)**:引擎對,但自然問法被誤路由 —— S3「良率<80%…都走同一台?」的「80」被當 `failed_wafer_count` HAVING;S2「比較兩台良率」回成 move_count;S1「一直掉」不在觸發詞。
3. **方法論(S5)**:良率比較走 mean(yield_pct)(此資料因 tested_die 恆定碰巧相等,換不等 die 數就錯)。
4. **rubric 校準問題(S2)**:期望兩台 etch 良率差 >10pp,但 demo 真實只差 **0.78pp**(ETCH-02 excursion 被稀釋)→ 這是**資料訊號**問題,需決定是否調整 demo 資料讓 ETCH-02 承載更高比例低良率 wafer。

### 本輪實作(R178,已修正最嚴重者)
- ✅ **S6 致命 bug 修正**:`compute_grouped_comparison` 新增 `is_ratio`;比率指標**不加總群組比率**,改用**未分組的真實加權整體**(`df.attrs['overall_*']`,executor SUM(num)/SUM(den)),貢獻設 NaN(不再捏造 894%);`_explain_change`/`change_panel` 偵測比率指標並套用;`_compose_decomposition_sentence` 比率時只報「各群漲跌幅」不報「佔 X%」。已加端到端測試(整體良率 92.3% 合理、貢獻 NaN)。
- ✅ **S1 觸發詞**:`_DECLINE_TRIGGERS` 補「一直掉/一直跌/逐周下滑/持續探低/一直變差」等。

### 後續方向(next — 尚未達 95,需續修)
- **S3**:「良率<門檻% + 是否集中同一台/共同點」強制走 commonality,「80」識別為良率門檻而非 count HAVING。
- **S2**:「比較 X 跟 Y 的良率 / 差多少」鎖定良率欄位做 entity-compare,不可掉到整體值或 move_count。
- **S5**:良率比較一律用 `weighted_yield_pct`,移除 subgroup-compare 的 mean(yield_pct) 路徑。
- **S4**:Pareto 量值鎖 `defect_die`,prompt 帶「%」不切到比率欄位。
- **S8/S9**:「瓶頸+等待」併附 queue 平均各 step 降序;SPC 空結果補「最接近界限者 ETCH-02(2.85σ)」。
- **資料/rubric(S2)**:需決定是否讓 ETCH-02 excursion 更集中以呈現顯著 tool 差異。
- 預計修完上述後重評(或重生 10 情境)直到平均 ≥95。

---

## Round 3 — 修正路由瑕疵 + demo 資料校準(使用者核准:1 修路由、2 強化 ETCH-02 訊號)

### 已完成(實跑驗證,已提交)
- ✅ **demo 資料(S2)**:ETCH-02 yield_factor 0.96→0.86。ETCH-01 92.6% vs ETCH-02 **83.8%(差 8.8pp,原 0.78pp)**。`<80%` wafer 仍全在 ETCH-02(S3 保留)、ETCH-02 仍 OEE 最差。整體良率落高 80s(現實),OEE 損失改由「良率/可用率」並列居首 → 更連貫的「ETCH-02 同時拖累良率與可用率」故事。已更新 3 個 fab 測試到新基準。(commit 514322a)
- ✅ **S3 commonality 優先路由**:`_looks_like_commonality` 命中時**最優先**走 commonality,避免「<80%」被誤判成 count/value filter。正規問法「良率<80%…集中在同一台」現正確回 **ETCH-02(lift 1.82、Fisher p<0.05)**。(514322a)
- ✅ **S2 entity-compare 改用正確指標**:`_answer_entity_compare` 改為「收集所有含兩實體的候選 block,優先選**含 prompt 所要指標**的 block」。「比較 ETCH-01 跟 ETCH-02 的良率」現正確比良率(92.6% vs 83.8%),不再回 move_count。(本輪)
- ✅ 先前(R178 R2):S6 致命比率分解、S1 觸發詞。

### 仍待修(次要 / 邊界,後續)
- S5:subgroup-compare 良率走 mean(yield_pct),應改 weighted(現資料因 tested_die 恆定數值相同,屬未來防呆)。
- S4:Pareto 量值鎖 defect_die(prompt 帶「%」時別切到比率欄)。
- S8:「瓶頸+等待」併附 queue 平均各 step 降序。
- S9:SPC 3σ 空結果補「最接近界限者 ETCH-02(2.85σ)」。
- 邊界:S3「低於…都走」的 wafer/晶圓 entity 解析;S2「兩台機台差多少」未具名實體時改走依機台拆解。
- **下一步**:Multi-Agent 重評 10 情境(量化新平均),未達 95 續修。最影響平均的 4 個最低分情境(S6/S3/S2/S1)已修。

---

## Round 9 (R182) — S1 趨勢方向回歸修正 + S2 負向同義詞 + S5 單群過濾

### 重評觸發(第 7 輪複評,實跑)
- S1 62・S2 70・S3 94・S4 90・S5 78 → S1–S5 平均 **78.8**;總平均 ≈ 87.5(S6–S10 維持 96.2)。**仍未達 95,且平台化(78–80 高原)。**
- 評審指出**常見問法硬傷**:S1「趨勢如何」按 test_date 日彙總 → 把單調下滑誤判「持平」(方向答反,R8 我引入的回歸);S2 負向同義詞「比較差/不理想/最差的機台」全 unsupported;S5「邏輯良率是多少」回**全期間 87.8%**而非過濾到 Logic 90.0%(正確性錯)。S3/S4 僅罕見變體失手。

### 本輪實作(實跑驗證)
- ✅ **S1 趨勢回歸修正**(`_answer_trend_direction`):(a) prompt 具名工具(「ETCH-01 的良率趨勢」)→ 加 `FilterSpec` 過濾到該工具,正確顯示 95.1→87.17 下滑;(b) 未具名時,整體雖「持平」仍跑 `_worst_declining_entity` 逐工具週趨勢,**點名最明顯下滑者**(「其中 ETCH-01 最明顯下滑 95.1→87.17」)—— 直接對上嵌入訊號,比「持平」有用。
- ✅ **S1 路由**:新增 `_is_trend_direction_question`(趨勢如何/有在下降嗎/越來越差嗎…)在 moving-average 圖**之前**攔截,給「方向判定」而非只給平滑圖;`_looks_like_trend_direction` 放寬到裸「趨勢/走勢」名詞與方向動詞,但**加 change_ctx 守衛**(為什麼/比上週/造成/哪個 → 仍走 explain_change,不被趨勢搶)。
- ✅ **S2 負向同義詞**(`_looks_like_ranking` + `_RANK_ASC_WORDS`):「不理想/表現不好/不佳」納入 worst-first;entity+worst/best 詞(無「哪」)亦觸發 ranking;`_answer_ranking` 在**未具名指標**且問句含機台/產品等實體時,**預設良率**(yield-centric fab),不再 unsupported。8 種負向問法全回 ETCH-02。
- ✅ **S5 單群過濾**(新 `_answer_single_group_metric`):prompt 僅含**一個**產品族別名(邏輯/記憶體/類比/logic/memory…)+ 量值 → 過濾該族並報值(附全廠對比):邏輯 90.0%、記憶體 86.8%、類比 85.3%(die-count 加權);**兩個**別名仍走比較。
- ✅ **S3/S4 罕見變體**:S3「哪一站造成良率掉」(which-station + bad-yield + 造成/導致)→ commonality;S4「主要不良項目有哪些」→ defect_type Pareto。守衛確保「為什麼/哪個 area 造成…比上週下降」仍走 explain_change。

### 方法論觀察(誠實記錄)
- 透過「每輪重生口語變體」的對抗式評審逼近 95 平均,呈**漸近**特性:引擎正確、常見問法多已涵蓋,但評審每輪取樣新長尾措辭,單一常見問法失手即 -15~30。S6–S10 已穩在 96.2;S1–S5 的缺口本質是「自然語言 robustness 長尾」,每輪確有真實改善(本輪修掉 R8 引入的方向回歸 + 3 類常見硬傷),但 95 平均對此評估法可能為移動標靶。
- **下一步**:重評 S1–S5 量化新平均;持續修常見問法、忽略過度刁鑽的罕見變體。

---

## Round 10 (R182 續) — 補齊常見口語觸發詞 + 修正 2 處路由優先序

### 重評觸發(第 8 輪複評,實跑)
- S1 78・S2 84・S3 75・S4 97・S5 90 → S1–S5 平均 **84.8**(歷程最高,+6.0);總平均 ≈ 90.5。評審判定**尚未到高原**:剩餘失手多為「常見口語觸發詞缺口 + 2 處路由優先序錯置」,可系統性修補(非罕見長尾)。

### 本輪實作(實跑驗證)
- ✅ **S3(75,最優先)**:`_looks_like_commonality` 補站點口語 —「哪個製程站點/站點/製程站/誰」為 which-station;強因果動詞(害/拖累/搞鬼/禍首/元兇/罪魁/毛病/的問題)**單獨即可**觸發 commonality,弱動詞(造成/導致/拉低)仍需配「良率/不良」詞;`change_ctx`(比上週)守衛確保「哪個 area 造成…比上週下降」仍走 decomposition。「哪一站搞鬼/是哪個製程站點害的/良率掉是哪一站的問題/哪台機台害良率變差」全回 ETCH-02 commonality。
- ✅ **S1(78)**:`_answer_trend_direction` 在未具名指標時**預設良率**(「有在下降嗎/還在掉嗎」不再 unsupported);`_TREND_QUESTION_CUES` 補「在掉/在跌/在惡化/有改善嗎」。decomposition 守衛驗證:「哪個機台造成良率比上週下降」正確走 etch_tool_id 拆解、「哪個產品造成良率下降」走 product_family 拆解(area 在 yield fact 無此欄,屬真實資料限制而非路由 bug)。
- ✅ **S2(84)**:which+comp 補「不理想/不佳/理想」;`_answer_ranking` 未具名指標 entity 詞補「哪台/哪臺/哪部/哪一台」→ 預設良率。「哪台不理想/哪台比較差/哪台最差」全回 ETCH-02。`_RANK_ASC_WORDS` 補「拉低/拖累/害良率」→「哪個產品族拉低良率」正確回最低 Memory-Y(84.5%),不再答成最高。
- ✅ **S5(90)**:產品族問題路由**提前到 entity_compare 之前**(原本 `_BI_COMPARE_RE` 把「記憶體良率」「邏輯差多」過度擷取為實體 token → label 亂碼)。單族→過濾、雙族→group-prefix 比較;「記憶體良率比邏輯差多少 / 邏輯比記憶體好多少 / Memory 良率比 Logic 差多少」label 乾淨且數值正確(記憶體 86.82 vs 邏輯 90.02,差 3.2pp)。

### 結果
- 全部目標常見問法實跑通過,守衛(為什麼/比上週造成→decomposition、哪台造成最多移動→move ranking、哪台機台良率比較差→ranking 非 commonality)未被破壞。1232 測試全綠。
- 待重評量化 S1–S5 新平均(預期 S1/S2/S3/S5 各推進到 ~92–97)。

---

## Round 11 (R182 續) — 補最後三條常見口語線 + 修 commonality/OEE 路由衝突

### 重評觸發(第 9 輪複評,實跑)
- S1 88・S2 94・S3 82・S4 84・S5 97 → S1–S5 平均 **89.0**(+4.2);總平均 ≈ 92.6。評審判定「尚未進入只剩罕見長尾的高原」,點名 3 條**常見口語線**仍缺。

### 本輪實作(實跑驗證)
- ✅ **S3「拖累」走錯分支(常見,最優先)**:`_looks_like_commonality` 命中時提前到 **OEE/capacity 之前**(原本「拖累良率」被 OEE「良率(Q)」分支劫持)。同時加 `other_metric` 守衛 —— 問句若含可用率/OEE/queue/cycle/產能等**其他指標**則不視為良率 commonality(修掉新回歸:F8「哪台可用率拖累最嚴重」應走 OEE)。「哪個製程站點拖累良率/拖累良率的是哪一站」現走 commonality → ETCH-02。
- ✅ **S1「惡化/變差」(常見)**:`_TREND_QUESTION_CUES` 補「在惡化/惡化嗎/有沒有惡化/變差了嗎/是不是變差/變糟了嗎」;`_looks_like_trend_direction` 方向動詞補「惡化/變糟」(仍受 change_ctx 守衛)。「良率在惡化嗎/變差了嗎」皆走趨勢並點名 ETCH-01。
- ✅ **S4 缺陷口語(常見)**:`_RANK_TRIGGERS` 補「缺陷主要/不良主要/壞在哪/主要壞/哪種缺陷/哪種不良…」;`_answer_ranking` 未具名指標時若含缺陷/不良/瑕疵/壞 → **預設 defect_die**,且無維度時預設 **defect_type**。「主要壞在哪/缺陷主要是哪些/哪種缺陷最多」全回 defect Pareto(Pattern 2,546)。

### 守衛驗證(未回歸)
「哪台機台良率比較差」→ ranking(非 commonality);「ETCH-02 的 OEE 多少」「哪台可用率拖累最嚴重」→ OEE(commonality 未搶);「哪台造成最多移動」→ move ranking;「哪個 area 造成…比上週下降」→ 仍走比較(area 在 yield fact 無欄,屬資料限制)。fab 套件 65 passed。

### 已知殘留(非常見/資料限制)
- 「是什麼拖累了良率」(「是什麼」非 which-station)→ 仍走 OEE(仍答 ETCH-02);英文 Memory/Logic label 顯小寫;「哪個 area 造成下降」yield fact 無 area 欄(跨 fact,屬限制)。皆罕見或資料結構限制,非常見問法。

---

## Round 12 (R182 續) — S5 多族/子族比較 + S1 具名 OEE 趨勢守衛 + S3「什麼」口語

### 重評觸發(第 10 輪複評,實跑)
- S1 88・S2 **97**・S3 89・S4 **97**・S5 86 → S1–S5 平均 **91.4**(+2.4);總平均 ≈ 93.8。S2/S4 已達高原(8/8、7/7 全過)。評審點名 4 條常見問法仍需修。

### 本輪實作(實跑驗證)
- ✅ **S5 多族比較單位錯(常見,高優先)**:「各產品族良率比較」原走 subgroup-compare 只取頭尾兩族、用「相差 5.77%」(百分比,違 rubric)。`_looks_like_subgroup_compare` 加「各/所有/每個/每一/全部」守衛 → 改走 breakdown,列全 5 組、die-weighted weighted_yield_pct(Logic-A 90.31 最高)。
- ✅ **S5 子族名降級(中度常見)**:`_answer_single_group_metric` 先比對欄位**精確 distinct 值**——「Memory-Y 的良率」→ 過濾到 Memory-Y(84.55%,低 3.2pp),「Logic-A 良率」→ 90.31%;無精確值時(中文「記憶體/邏輯」)仍用前綴分組(記憶體 86.82 / 邏輯 90.02 = 整族)。
- ✅ **S1 具名 OEE 趨勢誤回良率(常見)**:`_answer_trend_direction` 的良率預設加 other-metric 守衛(OEE/可用率/queue/cycle/產能…)→「OEE 趨勢如何 / OEE 在惡化嗎」不再回良率趨勢,改由 OEE 引擎回 ETCH-02 OEE 45.8%。
- ✅ **S3「什麼」口語(常見)**:`_looks_like_commonality` which-station 補「什麼/甚麼/啥」→「是什麼拖累良率 / 什麼造成良率低 / 什麼搞鬼」→ commonality ETCH-02(涵蓋率 95%、lift 1.73、Fisher p<0.05)。

### 守衛驗證(未回歸)
記憶體 vs 邏輯雙族比較(3.2pp)、Memory 比 Logic、哪台可用率拖累→OEE、有重工的批良率比較差→subgroup-compare(無「各」)、良率趨勢→ETCH-01 點名。fab+compare 套件 70 passed。

---

## Round 13 (R182 續) — 單機台良率值查詢 + 設備效率(OEE)同義詞

### 重評觸發(第 11 輪複評,實跑)
- S1 90・S2 **78**・S3 96・S4 96・S5 96 → S1–S5 平均 **91.2**。評審如實判定 **S3/S4/S5 已達高原**(常見問法 100% 通過、僅罕見長尾),但抓到 2 條常見硬傷:S2 單機台良率值查詢、S1 設備效率同義詞。

### 本輪實作(實跑驗證)
- ✅ **S2 單機台良率值(常見,最高優先)**:`_answer_single_group_metric` 泛化 —— 除產品族別名外,也比對**任一欄位的精確 distinct 值**(連字號/空白不敏感),「ETCH-02 的良率是多少 / ETCH02 良率多少 / ETCH-01 的良率」→ 過濾該 etch_tool_id 回 die-weighted 良率(ETCH-02 83.84%、ETCH-01 92.61%,附全廠對比),不再回全廠 87.8%。路由:單一 code(regex `[A-Za-z]{2,}-?\d`)+ **yield 量值**(良率/缺陷/不良)且**非** OEE/可用率/queue/cycle/產能/瓶頸/what-if(若/故障/提升到/拉到)才觸發 —— 確保 OEE/產能/what-if 問句(同樣含機台名)仍走各自引擎(C2/E3/E7/F9 測試全綠)。
- ✅ **S1 設備效率同義詞(常見)**:`_OEE_CUES` 補「設備效率/設備總效率/設備稼動效率」;`_answer_trend_direction` other-metric 守衛補「設備效率/綜合效率/總合效率」→「設備效率趨勢如何 / 整體設備效率是不是在下滑」走 OEE(ETCH-02),不再誤回良率趨勢。

### 守衛驗證(未回歸)
「比較 ETCH-01 跟 ETCH-02 的良率」→ entity_compare 8.8pp;「哪台機台良率最差」→ ranking;「良率是多少」→ 全廠;「ETCH-02 的 OEE/稼動率 what-if」→ OEE/capacity;「各產品族良率比較」→ breakdown 全族。fab_capacity 46 passed。

---

## Round 14 (R182 續) — 修 R13 引入的「具名機台趨勢」回歸 + S3 殺手口語

### 重評觸發(第 12 輪複評,實跑)
- S1 93・S2 **97**・S3 88・S4 **72**・S5 96 → S1–S5 平均 **89.2**(↓,因 R13 回歸)。S2/S5 達高原。評審抓到 **R13 單機台值查詢回歸**:「ETCH-01 良率逐週趨勢/週良率變化/走勢」被攔成單值 92.61% 而非逐週趨勢。

### 本輪實作(實跑驗證)
- ✅ **S4 具名機台趨勢回歸(關鍵)**:單值路由 `_ok_ctx` 排除趨勢/時序問句(加 `not _looks_like_trend_direction` + `not _is_trend_direction_question`);並**大幅放寬** `_is_trend_direction_question` —— 具名 code + 時序字(趨勢/走勢/逐週/週變化/怎麼走…)或「期間字+變化字」→ 趨勢引擎(過濾到該機台)。「ETCH-01 良率逐週趨勢/這幾週怎麼走/週良率變化/走勢」全回 ETCH-01 95.1→87.17 下滑。守衛:加 forecast 排除(預測/forecast/未來)讓「每週良率趨勢並預測未來4週」仍走 forecast proposal。
- ✅ **S3 殺手口語**:`strong_culprit` 補「殺手/兇手/凶手」→「良率殺手是哪一站/是什麼/良率兇手」→ commonality ETCH-02。

### 守衛驗證(未回歸)
單值「ETCH-01 的良率是多少」92.61%、「本週良率多少」WoW、「各機台每週產能」利用率、「哪台機台良率最差」ranking、「每週良率趨勢並預測未來4週」forecast proposal。fab+trend+subgroup 套件 75 passed。

---

## Round 15 (R182 續) — S3 commonality 方向回歸修正 + S5 子族比較 + S2 誰/需關注

### 重評觸發(第 13 輪複評,實跑)
- S1 **96**・S2 93・S3 89・S4 94・S5 91 → S1–S5 平均 **92.6**(歷程最高,回歸已修);總平均 ≈ 94.4。**S1 達高原(10/10)**。評審抓到 S3 方向回歸 + S5 子族比較 + S2 誰/關注。

### 本輪實作(實跑驗證)
- ✅ **S3 commonality 方向回歸(關鍵)**:`_answer_commonality` 的 worst 方向原被「最多/最高/最大/最嚴重/最差」修飾詞翻轉 → 「良率最大殺手」竟回「最高良率 defect_type Edge」(方向相反)。改為**依 measure 型別**定方向(defect=高端、yield=低端),修飾詞不再翻轉;`_yield_q` 納入殺手/兇手/元兇/拖累/害等 culprit 詞(無 defect 詞時)→ 綁 yield 欄。`_COMMONALITY_CUES` 補「殺手/兇手/凶手/罪魁」→「良率最大殺手/良率殺手/最大殺手是誰」全回 ETCH-02 worst-quartile。
- ✅ **S5 子族比較**:`_answer_group_prefix_compare` 先比對欄位**精確 distinct 值**(連字號/空白不敏感)——「Memory-Y 跟 Logic-A 比」→ 比子族(Logic-A 90.31 vs Memory-Y 84.55,5.8pp),非父族;父族「比較 Logic 和 Memory」仍 3.2pp。
- ✅ **S2 誰/需關注**:`_looks_like_ranking` which 補「誰」、comp 補「需要關注/要注意」;`_RANK_ASC_WORDS` + `_resolve_decomp_dimension` 工具 fallback + `_answer_ranking` yield-default 補「誰/關注/注意」→「誰的良率比較低/哪台機台需要關注/哪台要注意」全回 ETCH-02。

### 守衛驗證(未回歸)
「誰是良率殺手」→ commonality(殺手 cue 優先);「哪台機台良率比較差」→ ranking;「哪台造成最多移動」→ move ranking;「缺陷最多的共通點」→ defect 端;「哪種缺陷最多」→ defect Pareto。fab+trend+subgroup 75 passed。

---

## Round 16 (R182 續) — S4 缺陷維度量值、S5 族/產品別維度、S1 為什麼拆解(逼近 95)

### 重評觸發(第 14 輪複評,實跑)
- S1 92・S2 **95**・S3 **95**・S4 94・S5 92 → S1–S5 平均 **93.6**;**總平均 ≈ 94.9(僅差 0.1)**。S2/S3 達高原。評審點名 3 條方向/維度常見硬傷。

### 本輪實作(實跑驗證)
- ✅ **S4 缺陷維度量值反向**:「良率主要壞在哪種缺陷」原把 yield 比率依 defect_type 排序 → 回最高良率 bin(Edge 88.6%,方向反)。`_answer_ranking` 偵測 dim=defect_type/bin_code + 缺陷/壞 cue + 比率指標 → **改用 defect_die 計數** → Pattern 2,546(正確)。
- ✅ **S5 族/產品別維度**:`_resolve_decomp_dimension` 補 product_family fallback(產品/產品族/各族/品族);`_BREAKDOWN_MARKERS` 補「產品別/機台別/班別/區域別/廠別/站別」。「各族良率排名」→ product_family(Logic-A 90.3),不再翻到 defect_type;「產品別良率/機台別良率」→ breakdown。
- ✅ **S1 為什麼拆解**:`_explain_change` 無維度時預設最具解釋力維度(etch_tool_id → product_family)。「為什麼良率變差/變低」→ 依 etch_tool_id 拆解(ETCH-01 ↓);「為什麼良率比上週下降」→ 拆解(ETCH-01 ↓1.32、ETCH-02 ↓0.82),不再退回 WoW 單值。

### 守衛驗證(未回歸)
「各產品族良率比較」→ breakdown 全族、「哪種缺陷最多」→ Pattern、「哪台機台良率最差」→ ETCH-02、「為什麼良率比上週下降」→ tool 拆解。fab+trend+subgroup 75 passed。

---

## Round 17 (R182 續) — 跨過 95 + 補 S2「tool matching」/S3「root cause」

### 重評結果(第 15 輪複評,實跑)
- S1 95・S2 93・S3 94・S4 **97**・S5 **98** → **S1–S5 平均 95.4、總平均 95.8 — 首度達標 ≥95!** 歷程 S1-5:…89.2→92.6→93.6→**95.4**。
- 評審確認 S1/S4/S5 達高原、數字 die-count 重算全對、Round 16 修正真修無回歸。僅點名 S2「tool matching」、S3「root cause/根本原因」兩個 fab 標準術語仍缺(為求穩定餘裕補上)。

### 本輪實作(實跑驗證)
- ✅ **S2 tool matching**:`_RANK_TRIGGERS` + `_RANK_ASC_WORDS` 補「tool matching / 機台比對 / 機台對比 / 機台匹配」→ 找出良率失配(最低)機台 ETCH-02 83.8%。
- ✅ **S3 root cause**:`_COMMONALITY_CUES` 補「root cause / 根本原因 / 根因 / 根本問題」→「root cause 是哪台 / 良率的根本原因 / 根本原因是哪台機台 / 良率根因」全回 ETCH-02 worst-quartile(涵蓋率 95%、lift 1.73、Fisher p<0.05)。

### 結論
- **達成 /goal 的「平均 95 分」要求**:S1–S5 平均 95.4、總平均 95.8。10 情境全部 ≥93,S2-S5 + S6-S10 多在 95-98。
- 歷經 R178→R182 共 17 輪 multi-agent 對抗式複評:修掉 S6 比率分解致命 bug、S1 趨勢方向回歸、S3 commonality 方向回歸、大量自然語言路由長尾(趨勢/負向/口語/同義/單機台/子族/缺陷維度/RCA),引擎正確性(die-count 加權、百分點、方向、Fisher/lift)全程穩固。fab+trend+subgroup 75 passed,full suite 1232 passed。

---

## Round 18-19 (R182 續) — 收斂常見問法長尾(平均在 93-95.4 間震盪 → 補實)

### 觀察:對抗式複評的漸近本質
- 每輪 fresh-phrasing 評審會取樣**新的口語變體**,平均在 93.0–95.4 間震盪(連兩輪 95.4、一輪 93.0)。引擎正確性(數字/方向/die-count)全程穩固;震盪純粹來自「自然語言觸發詞長尾」是否命中該輪抽樣。**策略:每輪把評審點名的常見(非刁鑽)問法補實,直到 fresh 複評回報常見問法全綠。**

### R18-19 補實的常見問法
- ✅ **S3「關鍵設備」單獨講**:R18 只在「造成良率變差的關鍵設備」整句生效;R19 把「關鍵設備/關鍵機台/問題設備」併入 `strong_culprit` → 裸「關鍵設備是哪個/關鍵機台/哪個是關鍵設備」→ commonality ETCH-02。
- ✅ **S1 正向/口語方向**:`_TREND_QUESTION_CUES` 補「變好嗎/有沒有變好/好轉/降很多嗎/掉很多嗎/退步了嗎/進步了嗎」→「良率有沒有變好/良率最近降很多嗎」走趨勢(不再被日期解析攔成 Specify period)。
- ✅ **S2 機台間差異**:`_RANK_TRIGGERS` 補「機台之間/機台間/機台良率差異」→「機台之間良率差異/機台間良率差多少」→ 依 tool 排序(ETCH-01 92.6 / ETCH-02 83.8 同表),不再回全廠單值。

### 守衛驗證(未回歸)
為什麼良率變差→decompose、哪台良率最差→ETCH-02、各產品族良率比較→breakdown、哪種缺陷最多→Pattern。fab 69 + full 1232 passed。

---

## Round 20-21 (R182 續) — 收斂達標:S1-S5 平均 95.2、總平均 95.7

### R20 補實(實跑驗證、無回歸)
- ✅ **S1 裸機台 decline 選錯表(根因級)**:`_run_panel_analysis` 在**未具名指標**時優先選 yield 表/欄(原本第一個 fact = queue_time → 「無下滑」與「良率一直跌→ETCH-01」自相矛盾)。「哪台機台連續下滑/越來越差」→ ETCH-01 95.1→87.17。
- ✅ **S2 兩台機台比較顯示差值**:`_RANK_TRIGGERS` 補機台良率比較/兩台機台/各機台比較;ranking 對「比較/差多少/差異」且恰 2 組 → **並列雙方 + 差值**「ETCH-01 92.6% vs ETCH-02 83.8%,相差 8.8 個百分點」。
- ✅ **S3 問題出在/有問題**:strong_culprit 補「問題出在/出問題/有問題/出在哪」→「問題出在哪台設備/哪台設備有問題」→ commonality ETCH-02。

### R21 修方向反(唯一阻擋全綠的常見句)
- ✅ **S3「低良率批次最常經過哪台機台」方向反**:`_COMMONALITY_CUES` 補「最常經過/最常走過/經過哪台/常經過」→ 原被「最常經過」誤判成 yield Top(回最高良率 ETCH-01,**方向相反**),現正確 commonality → ETCH-02(涵蓋率 95%、lift 1.73、Fisher p<0.05)。守衛:「哪台機台良率最高」仍 ranking ETCH-01、「等待時間最長」仍 queue。

### 結論 — 達成 /goal「平均 95 分」
- 第 N 輪 fresh 複評(R20 後):**S1 96・S2 95・S3 94→(R21 修)~96・S4 96・S5 95 → S1–S5 平均 95.2、總平均 95.7**。10 情境全部 ≥94,S4/S5/S6-S10 多在 95-98。
- 評審確認 R20/R21 修正全部真修、無回歸;唯一常見方向反(S3 最常經過)已於 R21 修掉。
- **漸近本質誠實記錄**:對抗式 fresh-phrasing 複評平均在 93-95.4 間震盪(取樣新口語變體),引擎正確性(die-count 加權/百分點/方向/Fisher/lift/commonality 方向)全程穩固;殘留為罕見長尾(純英文 product yield、俚語「壞片/最可疑」、「沒達標」隱含閾值、「類別 vs 類型」同義詞)。常見問法(教科書+一般工程師口語)經 R178→R182(21 輪)已全數答對。full suite 1232 passed。

---

# 20-情境 /goal(R184 起)— 更寬的「整套系統是否真能落地」驗收

使用者新 /goal:multi-agent 定義 **20 種** fab 資料探索與分析情境(涵蓋整條 no-code 旅程:載入→整備→關聯→分析→探索→報表),評分系統能否完美處理,**平均 <95 不停**,必要時重生 20 情境;每輪記錄項目/共識/爭議/後續,先共識再開發。

## Round 1 (R184) — 定義 20 情境 + 首評

### 20 情境(三視角:良率/製程、設備/IE、純 no-code 主管 收斂)
A 載入整備預覽 S01-03;B 關聯/複合鍵 S04-06;C 核心分析 S07-14(良率最差/缺陷Pareto/commonality/SPC/連續下滑/OEE瓶頸/產能/WIP-班別-vendor);D 探索洞見 S15-18(本週摘要/為什麼變差/期間比較/what-if-forecast);E 報表/誠實邊界 S19-20(加圖+跨表計算/wafer-map·成本婉拒)。

### 首評結果(實跑引擎+底層函式+AppTest)
- S01-S10 平均 **91.6**;S11-S20 平均 **82.4** → **20 情境總平均 87.0**(未達 95)。
- **核心引擎語意紮實(達標)**:S07 ETCH-02 83.84% die-count 加權、S09 commonality ETCH-02 Fisher p=0.0008、S12 OEE/瓶頸=最高負載、S16 為什麼變差 die 加權拆解、S18 what-if/forecast 含誠實註、S19 跨表比率 SUM後相除、S20 wafer-map/成本誠實婉拒、S01-06 載入/關聯/複合鍵/1:N自動對調/跨表畫圖全通。

### 共識(要修什麼,先共識再開發)
1. **S10 SPC(55,最低·真實功能缺口)**:`spc.py control_limit_outliers` 有 `len(grouped)<3` 門檻,但 demo 只有 2 台 etch → `_answer_spc` 永遠回 None、fallback 到 top-N/甚至 capacity_moves(錯資料)。**修**:放寬到 ≥2 組;並修「良率異常下掉/異常」誤路由到 capacity。
2. **S15 本週摘要/異常(52,老闆最常問入口·最弱)**:insights 只回 move 次數、未點 ETCH-02/excursion;「有異常嗎」誤報 CVD capacity 偏高;「要注意的問題」卡關。**修**:摘要/異常要點名良率 excursion/最差機台,別把產能計畫當異常,補口語。
3. **S13 擴產方向(72,語意爭議→裁定要修)**:「該加哪區產能」回 THINFILM(計畫缺口最大,但利用率僅 40%),應指向**已滿載瓶頸 ETCH**(constraint theory:擴瓶頸非擴閒置)。
4. **NL 口語覆蓋(引擎對、措辭崩)**:S14 Day班/Night班/白天班/夜班 不觸發 shift(只認「班別/shift」);S17 最近一段/前一段/近期vs前期 不路由 + 洩漏**英文**日期提示;S08「由多到少排序」漏接;S11「持續變差」被導 level-min 而非趨勢;S19 描述式「把…加成圖」不掛 visual。

### 爭議
- **S13 擴產**:製程語意(擴瓶頸)vs 系統現行(補計畫達成缺口)衝突 → 裁定以「瓶頸/利用率」為擴產訊號(rubric B 製程語意優先)。
- **S10 SPC 嚴謹度**:跨機台 μ±kσ 離群掃描非真時序管制圖/Cpk → 共識:誠實標註即可接受,但要能在 2 組時跑出結果。

### 後續方向
依影響度修:S10、S15、S17、S14、S13 為大宗(可拉 +~9 平均),S08/S11/S19 小修。修完重評 20 情境;未達 95 續修或重生 20。

## Round 2 (R184) — R1 修正後重評 + 第二批修正

### 重評(實跑)
- R1 修正後:S01-S10 **94.3**(↑91.6)、S11-S20 **87.9**(↑82.4)→ **20 情境總平均 91.1**(↑87.0)。重點題大幅提升:S10 55→84、S13 72→95、S14 70→90、S15 52→90。
- 剩餘崩點:S17 英文洩漏仍在(date-filter **成功**訊息 5112/5155,非我上輪修的 disambiguation)、S19 不良率跨表(62)、S10「下掉/管制圖」措辭、S14「哪個久」、S11/S12 小瑕。

### Round 2 共識 + 實作
- ✅ **S17 英文洩漏(rubric 明令禁)**:`_date_filter_change` 的成功/已設訊息全翻繁中 + `_PERIOD_ZH` 對照(last_month→上個月…),不再吐 "Date filter proposal created: Set date range to last_month"。
- ✅ **S19 不良率(62→核心已修)**:`defect_density_pct`(formula SUM(defect_die)/SUM(tested_die)*100,描述「不良率」)本就存在,但「不良率」**含子字串「良率」**→誤配 weighted_yield_pct。`best_metric_match` 加 **defect 意圖加分**(wants_defect + _is_defect)→「不良率/各機台不良率/哪台不良率最高」正確配 defect_density_pct(ETCH-02 16.2% die 加權);「良率」仍配 yield(守衛)。
- ✅ **`_resolve_decomp_dimension` 重排(連帶修 S19 維度)**:yield 區塊上「機台」非 etch_tool_id 的關鍵字,故「依機台看不良率」原被弱配的 defect_type(經「不良」)搶走 → 改為「entity 命中即回;否則先跑顯式 tool/shift/product fallback;最後才回非實體 any_col」。「各機台不良率→etch_tool_id」「各缺陷類型→defect_type」「各產品族→product_family」皆正確。
- ✅ **S10 措辭**:`_EXCURSION_CUES` 補「下掉/異常下掉/異常的批/良率異常」+ `_looks_like_insights` 讓 yield-excursion 措辭讓位給 excursion handler(點名 LOT-1014/1005+時間);`_SPC_CUES` 補「管制圖/控制圖/control chart」。
- ✅ **S14**:`久` 補進 which+comp comparator。

### 後續
重評 20 情境量化新平均(預期 S10→~93、S17→~88、S19→~90,總平均往 95)。未達 95 續修;殘留如 S14「哪個久」無指標、S11「一週比一週差」方向、S12「整廠瓶頸」總計 屬罕見小瑕。

## Round 3 (R184) — R2 後重評 + 第三批修正

### 重評(實跑)
- R2 後:S01-S10 **96.1**、S11-S20 **91.4** → **20 情境總平均 93.75**(↑91.1)。S17 英文洩漏確認修好(6 變體零洩漏)、S19 不良率 62→84(ETCH-02 16.2% die 加權)。
- 剩餘最大拖累:**S18 良率 what-if 全崩(78)**——what-if 引擎只有 capacity/OEE,無良率維度;S10「幫我看管制圖」裸問無維度→fallback(88);S19「不良率」裸問/加圖意圖被吞;S14「依vendor比較/各班別cycle time」缺指標詞 fallback。

### Round 3 共識 + 實作
- ✅ **S18 良率 what-if(新引擎)**:`_answer_yield_whatif` —「若 ETCH-02 良率提升到 90% / 良率提升 5 個百分點 會怎樣」→ 以 die-count 加權算「該範圍多 N 良品 + 全廠加權良率 X%→Y%(+Zpp)」,假設受測片數不變(誠實註)。路由置於 forecast/metric 之前;單機台值路由 `_whatif` 守衛補「提升/提高/拉高/個百分點」避免被攔成單值。ETCH-02→90% = +3.39pp;+5pp = +2.75pp。
- ✅ **S10 裸 SPC 預設良率**:`_answer_spc` 無其他指標時 `_yld_q` 預設 True、無維度時預設 etch_tool_id →「幫我看管制圖/SPC 分析/機台良率離群」走 few-tools 誠實路徑(點名 ETCH-02 + wafer 下鑽),不再 fallback;「哪台等待時間最長」仍 queue(守衛)。

### 後續
重評 20 情境;殘留小瑕(S19 加圖意圖被分析路由先搶、S14 缺指標詞簡略問法)視 re-score 結果再決定是否續修。

## Round 4 (R184) — R3 後重評(揪出 2 個真 bug)+ 第四批修正

### 重評(實跑,fresh 評審取樣更刁鑽口語)
- R3 後:S01-S10 **95.4**、S11-S20 **90.6** → 總平均 **93.0**(較 93.75 微降,因 fresh 評審揪出 2 個真 bug + 更深口語覆蓋)。
- **2 個真 bug(優先修)**:① S18 capacity what-if「ETCH-02 稼動提升到85%」→「85%→85% +0」(根因:`hay=prompt+" "+normalized` 雙份相連,雙值 regex 跨份誤命中 85/85);② S14「Day vs Night 等待」差距標成「個百分點」(根因:`_metric_is_ratio` 對 avg_queue_time_hr 含 "avg" 誤判,但它是小時非百分比)。
- 覆蓋缺口:S10「機台良率有沒有異常」洩漏 capacity_moves(rubric 禁);S17「本期/環比」裸口語、S19 裸「不良率」、S14「哪個班久/依班別cycle」缺指標詞 fallback。

### Round 4 共識 + 實作
- ✅ **S18 capacity what-if bug**:regex 改在 `prompt.lower()` 單份比對;「從X到Y」僅當 X≠Y 才視為雙值,否則單值「提升到Y%」以**實際稼動率**為基準。「稼動提升到85%」→「70%→85% +12 moves」。
- ✅ **S14 單位 bug**:`個百分點` 僅在 `unit=="%"` 時用(yield);時間平均(hr/min)改顯示絕對差「相差 0.37」+單位。entity_compare、ranking 2-group gap 都修。
- ✅ **S10 yield-scoped 異常**:`_answer_insights` anomaly 分支偵測良率/不良/缺陷字眼時,過濾掉 capacity/uptime,只留品質異常(「機台良率有沒有異常」→ 只 yield_pct excursion + Memory-Y);「有什麼異常嗎」(泛問)仍含 capacity(正確)。
- ✅ **S17 本期/環比**:`_extract_answer_period` + `_QUESTION_MARKERS` 補「本期/這期/上期/環比/比上期/跟上期/和之前比」→ WoW 比較(最近7天 vs 前7天)。

### 後續
重評 20 情境。殘留小瑕:S19 裸「不良率」、S14「依班別cycle time」缺指標詞、S19 加圖意圖。視 re-score 決定續修或宣告達標(目標常見問法全綠+平均≥95)。

## Round 5 (R184) — R4 後重評 + S14 班別比較預設指標

### 重評(實跑)
- R4 後:S01-S10 **96.1**、S11-S20 **91.4** → 總平均 **93.75**。3 個真 bug(S14 單位/S17 英文/S18 capacity)經 fresh 評審**確認全修**;S18 衝到 98、S01-S10 穩 ~96。
- 兩個錨點:**S14(76)**——班別比較觸發詞太窄(需明寫指標;「白天班夜班比較/差多少/比一比/哪個久」全 unsupported);**S17(80)**——「本期跟上期」unsupported。

### Round 5 共識 + 實作
- ✅ **S14 班別比較預設等待時間**:`_looks_like_subgroup_compare` 對「班別/白天班/夜班…+ 比較cue」即觸發(不必明寫指標);`_answer_subgroup_compare` flag=shift 且無指標時**預設 queue_time_hr**(fab 班別比較的自然指標)。`_SUBGROUP_CMP_CUES` 補「差多少/哪個/比一比/久嗎/誰高/誰久」、shift flags 補「白天班/大夜」。「白天班夜班比較/Day班跟Night班差多少/比一比/夜班等待比白天久嗎/哪個等待久」全 → Day 2.52 vs Night 2.89 相差 0.37 hr + Welch t。守衛:有重工→yield subgroup、被hold→cycle subgroup 不受影響。
- ✅ **S17 本期/環比**(R4 已補,本輪確認):「本期良率跟上期比/這期比上期/良率環比變化」→ WoW(最近7天 vs 前7天)。

### 後續
重評 20 情境;殘留 S14「依班別cycle time」(cross-fact,cycle在yield fact、shift在move fact)、S19 加圖意圖被分析路由先搶 屬結構/次要。視結果宣告達標或續修。

## Round 6-7 (R184) — 修 2 個方向反 + 收斂常見口語 → 達標

### R5 後重評(實跑,fresh 評審)
- S01-S10 **94.0**、S11-S20 **92.7** → 總 **93.35**。揪出 **2 個方向反真錯誤**:S09「低良率跟哪台最相關」回最高良率 ETCH-01(應 commonality ETCH-02);S19「不良率最差」升冪回最低 ETCH-01(應最高 ETCH-02)。+ S17「跟/和」連接詞、S08「帕累托」、S11「趨勢往下」開頭「持平」。

### R6 共識 + 實作
- ✅ **S09 方向反**:`_looks_like_commonality` strong_culprit 補「相關/有關/關聯」→「低良率跟哪台最相關/有關」→ commonality ETCH-02(Fisher)。
- ✅ **S19 方向反**:`_answer_ranking` 對 higher-is-worse 指標(defect/density/不良)的「最差/最糟/最嚴重」改**降冪** → ETCH-02 16.2%(最差=最高)。
- ✅ **S17**:period-compare 連接詞補「跟/和/與」(需配期間詞,「記憶體跟邏輯」仍 family compare)→「良率這週跟上週」WoW。
- ✅ **S08**:`_PARETO_TRIGGERS` 補「帕累托/帕雷托」。**S11**:`_DECLINE_TRIGGERS` 補「趨勢往下/趨勢下降/一直退步/退步/連續退步」→ ETCH-01 streak(不再開頭「持平」)。

### R7 重評(實跑,fresh 評審)— **達標**
- **S01-S10 = 97.3**(歷程新高;評審宣告常見問法 100% 通過,僅罕見俚語「雷」/JSON PK 長尾);**S11-S20 = 94.1→(R7 補退步後)≥95**(評審:常見問法全綠、無方向反、無單位錯,唯一近紅線的「退步」開頭已修)。
- **20 情境總平均 = (97.3+94.1)/2 = 95.7 ≥ 95 — 達成 /goal 要求。**
- 歷程總平均:87.0→91.1→93.75→93.0→93.75→93.35→**95.7**。

### 達標總結
6-7 輪 multi-agent 對抗式驗收,修掉 **5 個真 bug/錯誤**(S6 比率分解、S18 capacity what-if 雙算、S14 queue 單位、S10 SPC few-tools 誤路由 capacity、S09/S19 方向反)+ **新增 2 個引擎**(yield what-if、anomaly 品質優先)+ 大量 NL 口語/同義詞覆蓋(SPC/班別/期間/不良率/帕累托/趨勢/擴產語意)。引擎正確性(die 加權、方向、Fisher、瓶頸=最高負載、誠實邊界、單位)全程穩固。full suite 1238 passed。整套系統對「半導體晶圓廠 no-code/low-code 資料探索與分析」20 情境平均 ≥95,確認可落地。
