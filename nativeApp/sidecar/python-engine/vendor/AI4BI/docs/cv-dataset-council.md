# CV 資料集管理 /goal — Multi-Agent Council Log

目標（來自 /goal）：用 multi-agent 思考「怎樣的系統能真正幫**電腦視覺(CV)工程師更好管理資料集**」，定義 10 種情境、評分，平均 <95 不停（必要時重生 10），每輪記錄項目/共識/爭議/後續，**先有共識再開發**。

## Round 1 — 定義 10 情境 + 可行性評估（三視角：MLOps/資料工程、CV 訓練工程師、標註團隊負責人）

### 關鍵現實（共識起點）
AI4BI 是**表格型** BI（Streamlit+DuckDB）：上傳 CSV/JSON/REST/DB → 預覽 → 關聯/複合鍵 → NL 問答（ranking/Pareto/breakdown/trend/commonality(Fisher)/spc/比較/insights/what-if）→ 圖表/報表。**不能讀影像像素、不能 from-image 算 mAP/IoU、不能標註、不能感知去重**。
→ CV 資料集管理只能以「CV 工具匯出的**標註/中繼資料表**」為操作對象；像素級的「為什麼」靠人去看圖，AI4BI 負責「指出哪裡值得看」。

### 10（+1 邊界）情境
- S1 類別不平衡（各 class count 排序）✅
- S2 split 平衡/分布偏移（train vs val 各類占比）✅(完整每類×split 矩陣 ⚠️ 單維限制)
- S3 每類 precision/recall（ranking recall 最低類）⚠️(需先匯入/建比率欄)
- S4 信心分布（confidence histogram + 答對vs答錯 subgroup_compare）✅
- S5 標註者產能（各 annotator count）✅
- S6 標註者一致性（各 annotator 平均 IoU 排序）✅
- S7 重複/洩漏（重複 image_id；跨 split 同 image join）⚠️(需建關聯;非感知去重)
- S8 版本標籤漂移（v1 vs v2 各類占比/趨勢）✅
- S9 錯誤分析/混淆（filter is_correct=0 後 ranking 主要誤判對；commonality 找錯誤是否系統性集中某 annotator/split）⚠️(完整 NxN 熱圖需 pivot/新意圖)
- S10 bbox 尺寸雙峰（area histogram）✅
- **S11（純誠實邊界）影像品質/看圖** ❌ → 正解＝婉拒+說明「給我 blur_score/qc_flag/iou 欄位我能排序找出該複檢的」

### 共識
1. **資料治理層是 AI4BI 甜蜜點**（不平衡/split偏移/重複洩漏/版本漂移/標註者產能·一致性），本質是 group-by/distinct/join，現成能力覆蓋 ~70%。
2. **指標必須上游已算好匯出**（precision/recall/IoU/is_correct），AI4BI 只彙總不重算——界線講清楚。
3. **commonality(Fisher+lift) 引擎可直接遷移** 到「錯誤是否系統性共用某 annotator/source」(S9)，零改碼、高價值。

### 爭議
1. **「看起來能幫但價值有限」**：訓練工程師核心迴圈是看錯誤樣本的圖；AI4BI 能精準縮小到「該看哪 200 張」，但最後一哩仍要離開工具看圖（vs FiftyOne 能點開看圖）。未解。
2. **混淆矩陣**：單維 filter+ranking 給主要誤判對 vs 完整 NxN 熱圖（需 pivot/新意圖）。
3. **重複/洩漏真假**：只能靠 image_id/hash/is_duplicate，做不到感知近似重複。

### 後續方向（先共識後開發 — 共識已達成）
1. **阻斷性前置：新增 `cv_dataset_template.py` CV demo dataset**（仿 fab_template，InlineDataSource+contract+metrics+內嵌可被找到的訊號），否則評分代理無資料可跑。3 表：
   - `cv_annotations`（每 bbox 一列：image_id/bbox_id/class/split/dataset_version/annotator/bbox_w/h/area/img_w/h/is_duplicate/iou）
   - `cv_predictions`（image_id/true_class/pred_class/confidence/is_correct/iou_pred）
   - `cv_eval_per_class`（class/gt_count/tp/fp/fn/precision/recall/ap）
   - 內嵌訊號：某類嚴重不平衡、person 在 val 占比偏高、bicycle 在 v2 暴增、ann_07 avg_iou 系統性低、錯誤樣本過度自信且集中 ann_07+v2、car↔truck 主要混淆對、area 雙峰、一批重複 image_id + 跨 train/val 洩漏。
2. NL 引擎現有意圖已覆蓋 S1/S2/S4/S5/S6/S8/S10；S3/S7 需操作前置（建比率欄/關聯）；S9/S2 完整交叉表 ⚠️ 單維限制（可接受「分次單維+filter」等價答案）；S11 需加「看圖類問句→婉拒守門」。
3. 建完 demo → multi-agent 評分 10 情境 → 平均 <95 續修。

### 誠實總評
AI4BI 對 CV 工程師是強力的**「資料集治理 + 錯誤分流」儀表板**，覆蓋日常痛點 ~60-70%（把「該先看哪批」精準縮小），但**碰不到像素**（看圖/from-image 指標/感知去重/完整混淆熱圖要嘛本質做不到要嘛需小改），指標須上游算好。取代不了真正去看圖那一哩。
