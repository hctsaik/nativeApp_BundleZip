# 圖表常用功能 — E2E 多情境驗證（multi-agent）

> 目標（使用者）：用 E2E 測試方式，產生 10 組「使用圖表時常用的功能/情境」，逐一在真實瀏覽器試用；每組都要完美無缺（multi-agent 打分 ≥95），否則重出 10 組重來。

## 方法
- **情境產生**：multi-agent（BI/data-viz UX 專家）生成 10 個最常用的圖表操作情境 + 可觀察的通過標準。
- **E2E**：`tests/e2e/run_chart_usage_e2e.py` — 真實 Chromium + 真實 Streamlit server（free port、`LLM_MODE=mock` 確保確定性）。每個情境**讀取 Plotly 的 live `.data`/`.layout`/`.calcdata`**（渲染後的真實狀態，非控制項狀態），各情境獨立（每題開新分頁＋重載半導體 demo）。
- **打分**：兩個 multi-agent lens（QA 測試架構師 / Power BI 重度使用者）各自對 10 題打分。

## 10 情境（皆對半導體 demo 的「Queue Time by Tool ID」長條圖）
S1 換圖表類型（長條→折線）／S2 換值（measure）／S3 換分組維度／S4 排序（高↘低 與 低↗高）／S5 Y 軸範圍（min/max）／S6 Y 軸對數刻度／S7 資料標籤開關／S8 圖例位置（底部）／S9 刪除圖＋復原／S10 自然語言新增圖表。

## 過程中修掉的真 bug（E2E 驗出，非調參）
1. **換 measure 後殘留舊排序** → `Sort column ... is not a projected output` → 圖表壞掉消失。修：換值時同步 remap query/sort（`_sort_remap_change`）。
2. **單邊 Y 軸範圍被靜默忽略**（只設 min 或只設 max 無效）。修：用 plotly `autorangeoptions.minallowed/maxallowed` 夾住單邊。
3. **field-well 分組下拉**預設選到錯欄位（排除了結尾 `_id` 的當前維度），且走 NL 治理而**誤拒同表欄位**（"not certified"）。修：改成直接 block-scoped 的 query/dimensions patch，並含當前維度。
4. **格式控制被埋在收合的 fallback expander**（拖放元件存在時）→ 使用者看不到 Y軸/排序/標籤/圖例。修：格式區塊永遠可見。

## 結果
- **E2E：10/10 PASS**（強化驗證：S3 驗類別真的變、S4 驗雙向重排、S9 驗復原還原、S10 驗真的新增一個長條 trace）。
- **multi-agent 打分：每一題 ≥95**。QA lens 平均 **97.3**、Power BI lens 平均 **96.1**，兩者皆「ALL ≥95 = yes」。
- 非 e2e 測試 **1059 passed**。全程 test+commit+push（Round 160–162）。

達標：10 組圖表常用情境全部 ≥95，無需重出新 10 組。
