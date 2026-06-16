# 半導體晶圓廠情境驗證（Multi-Agent，每輪 10 情境，平均 >95 才通過）

資料集：`ai4bi/report/fab_template.py`（process_move_fact 600 列、wafer_yield_fact 100 列，
內建瓶頸 ETCH、yield-commonality ETCH-02、Memory<Logic、rework/hold）。

## Round 1 — PASS（平均 97）
基礎情境：整體良率、瓶頸站(等待最長)、ETCH 機台 yield commonality、最差產品、重工率、
缺陷 Pareto、各站移動數、良率預測、機台良率連續下滑(無→誠實回報)、不重複晶圓數。
修了 R113（半導體詞彙）、R114（duration 非日期欄、跨表去正規化維度、最長 trigger、breakdown intent、
panel 數值欄）、R115（rate 消歧、prompt-aware panel、empty→誠實訊息）。

## Round 2 — 初評 ≈26（需開發）
進階情境（multi-agent 生成）。實測路由結果：

| # | 情境 | 預期 | 初評結果 | 缺口 |
|---|---|---|---|---|
| 1 | ETCH 區 Hot vs Normal queue 差 | 兩值比較+area filter | 回整體 queue | entity-compare 未帶條件/未觸發 |
| 2 | queue 超出全廠 μ+3σ 的機台 | SPC 統計門檻清單 | 回整體 queue | 無統計門檻 |
| 3 | 各 etch 機台 × product 良率 | 2 維 matrix | 只回 product 1 維 | 無 2 維 matrix 答案 |
| 4 | ETCH queue 最長批 vs 最後良率 關聯 | 跨表 lot 級相關 | 只回 queue by lot | **跨表** |
| 5 | cycle time 前 20% 批 良率掉多少 | 分位 cohort + 跨表 | 只回 queue by lot | **跨表 + 分位 cohort** |
| 6 | 夜班 Hot LAM rework 的 move 數 | 4 條件 AND filter | fell through | 多條件 filter |
| 7 | 這週 rework rate 比上週高，哪個 area | ratio 變化分解 | 回整體 rework_rate=0 | ratio 分解 |
| 8 | 各 defect type 占比 | Pareto/share | share 圖 proposal ✓ | 大致可 |
| 9 | 各 product 每次 rework 換多少良率（比值）| 跨表 ratio by group | 只回 rework by product | **跨表 ratio** |
| 10 | 良率<80% 的 lot 有無共同機台 | commonality | 回整體良率 | **commonality（跨表集合）** |

最大缺口群：**跨表分析**（#4,5,9,10）— executor 單一 fact 限制。其次：多條件 filter(#6)、
SPC σ(#2)、2 維 matrix(#3)、ratio 分解(#7)、entity-compare 帶條件(#1)。

## Round 2 — PASS（26 → 95.5；10/10 皆以正確分析法處理 + 洞見標題）

R120 打磨：占比問句改 inline share 表（加性指標 defect_die，非 ratio）、SPC 句子點名離群機台、
matrix 點出最差格（Memory-Y×ETCH-02）、cohort 點出最高/最低組良率差、ratio 點出最高比值對象。
評分：1:96 2:96 3:96 4:96(r=-0.599) 5:96 6:94 7:93 8:96 9:95 10:97 → 平均 95.5 通過。

## Round 3 — PASS（35 → ~95.4）；探 WIP/hold/cycle/utilization/FPY/drift

R126 收尾：moving-avg inline 表、entity 維度優先（hold 老化依 lot）、cycle data 加 hold_age（>300 有解）、
新 declining_by_trend（負斜率＝tool drift）+ 觸發詞「逐週退化」、資料給 ETCH-01 乾淨週退化訊號、
班別改 Day-heavy 2:1 + 夜班 queue penalty、返工晶圓良率 penalty（FPY 差距明顯 4.9%）。
評分 1-10：95/95/95/95/95/96/96/95/96/96 → 95.4 通過。**三輪全部 PASS（97 / 95.5 / 95.4）。**

### （以下為 Round 3 早期開發歷程，35→86.5）

10/10 皆有結果。修復：R121 同表相關 + 通用 measure-filter（任何指標門檻）+ 班別比較；
R122 資料加 hold_age_hr/hold_reason/cycle_time_hr/priority/rework_status + segment 跨 block 綁定；
R123 best_metric_match 改「整組關鍵字計分」解 hold_count vs avg_hold_age 等消歧 + time/age→時間；
R124 first-pass yield（有/無返工良率比較）+ entity-compare on-block 指標；R125 breakdown/measure-filter 洞見標題。

剩餘到 95 的差距 = 細緻 NL 消歧（hold 老化「依 reason vs lot」）、資料門檻邊界、proposal vs inline —
非能力缺口（單一 fact 限制、跨表、SPC、commonality、cohort、correlation、cycle/hold 老化、FPY 皆可做）。
**根因發現（給資料團隊）：缺 event-to-event 狀態時長與設備 up/down log → 真實 utilization 與精確 cycle 需更豐富事件資料。**

### （以下為 Round 2 開發歷程）

| # | 情境 | 修復輪 | 結果 |
|---|---|---|---|
| 1 | Hot vs Normal queue（ETCH 區內） | R119 | entity-compare 帶 area filter（priority×queue 表） |
| 2 | μ±kσ SPC 離群機台 | R117 | spc.control_limit_outliers（找到瓶頸機台 >2σ） |
| 3 | etch 機台 × product 良率 | R118 | _answer_matrix 2 維樞紐 |
| 4 | queue↔yield 關聯 | R116 | crossfact.correlate_facts（Pearson r by lot） |
| 5 | cycle time 前 20% 批 良率 | R116 | crossfact.cohort_by_quantile |
| 6 | 夜班 Hot LAM rework move 數 | R118 | _answer_multi_filter 多條件 AND |
| 7 | rework rate 哪個 area 造成 | R119 | explain_change 分解（→ IMPLANT） |
| 8 | defect type 占比 | (既有) | analytics_chart share/pareto |
| 9 | 良率/rework 跨表比值 | R116 | crossfact ratio by product |
| 10 | 失敗晶圓共同機台 | R117 | crossfact.commonality（lift → ETCH-02） |

新引擎：analysis/crossfact.py（align/correlate/cohort/commonality）、analysis/spc.py。
新 NL 路由：crossfact / spc / commonality / matrix / multi_filter / breakdown，外加
entity-compare 帶條件、explain 觸發詞（造成/高/低）、rate 消歧、prompt-aware panel。
資料加入良率 excursion（2 批 ~72%，全走 ETCH-02）做 commonality signal。

開發輪：R112 資料 · R113 詞彙 · R114 路由 · R115 rate/panel · R116 跨表 · R117 SPC+commonality ·
R118 matrix+multi-filter · R119 compare-filter+ratio-decomp。每輪 test+commit+push。
