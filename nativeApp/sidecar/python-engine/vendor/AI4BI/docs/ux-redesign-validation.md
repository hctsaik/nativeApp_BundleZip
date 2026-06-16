# AI4BI GUI — UI/UX 改善 Multi-Agent 驗證日誌

> 目標（2026-05-31 使用者設定）：用 Multi-Agent + 10 情境法檢視 GUI 的 UI/UX 手順是否方便。
> 具體痛點：(1) 左側 AI4BI toolbar 階層感不好；(2) Data source 管理不清；(3) 想要 Data source join 功能；(4) 整體更像 Power BI（使用者認為 Power BI 設計很好）。

## 起點現況
左側 sidebar 是 **~25 個面板平鋪一列**（只有 `---` 分隔、無分組標題），絕大多數是預設收合的 expander。**join builder（資料關聯設定）與資料模型檢視其實早已存在**（Round 037/038），但埋在第 13/14 位 → 使用者找不到（正好印證階層問題）。Data source 有兩個入口（上傳、DB 連接器）寫到同一個 user_blocks，但沒有統一的「資料來源管理」。

## 第 1 輪 — Multi-Agent UX 評估（3 lens × 10 情境）
3 個 persona agent：①Power BI 分析師 ②非技術 SMB 老闆（目標用戶）③IA/互動設計師。10 情境＝首次開啟、上傳看圖、上傳第二份並 join、管理資料來源、改圖維度/指標、自然語言問答、新增計算指標、整份篩選、分享發布、找 join 功能。

| Lens | 現況分數 | 最差情境 |
|---|---|---|
| Power BI 分析師 | **47** | 找 join 15、資料來源管理 20、onboarding 25 |
| SMB 老闆 | **33** | join 15、計算指標 20、找 join 20 |
| IA 設計師 | **34/100** | 平鋪 25 項、資料生命週期散落、揭露文法不一致 |

**一致結論**：用 **Power BI 式 view-mode** 取代平鋪列；把 join 升為一級入口；做統一資料來源管理。

## 開發（每輪 test+commit+push，非 e2e 1044 passed）
**Round 147**：sidebar 改為 **view-mode 選擇器**「🔍探索 / 🗂️資料 / 🔗模型 / 📊分析 / 📤分享」，每個 mode 只顯示相關面板（~4-6 項 vs 25）。新增 `render_data_source_manager`（統一列出所有來源＋來源徽章/列數/移除）。join builder 升為 🔗模型 mode 第 1 個面板。持久保留：title、demo 切換、復原/重做/快取 ribbon、篩選 pane、identity（View-as）。**全部既有功能，純重排**。
**Round 148**：把自然語言 ask box 從 sidebar 收合 expander **移到主畫布頂端**（Power BI Copilot 位置，常駐）；join builder 在 🔗模型 mode 預設展開、標籤改白話「把兩份資料用共同欄位連結」。
**Round 148b**：每張圖表下方新增 **per-visual field-well「✏️ 編輯這張圖」**——圖表類型 + 分組（group by）下拉，直接改圖不需打字（走治理 builder）。
**Round 149**：field-well 對「選取中」的視覺**預設展開**（Power BI 行為）。

## 第 2 輪 — Multi-Agent 重新打分
| Lens | 起點 | R147 | R148+b |
|---|---|---|---|
| Power BI 分析師 | 47 | 74.6 | **81.3** |
| SMB 老闆 | 33 | 69.5 | **80.4** |
| IA 設計師 | 34 | 79（預測82） | — |

關鍵情境：找 join 15→**85-90**、資料來源管理 20→**84-90**、onboarding 25→**82-88**、改圖 45→**72-76**、問答 → **85**。

**兩位 agent 最終 VERDICT**：手順已「genuinely convenient and Power-BI-like」「genuinely usable… a clear jump」。使用者四項痛點全部解決：階層感（view-modes）、資料來源管理（統一 manager）、join（升為一級＋預設展開＋AI 偵測 key）、Power BI 感（ribbon／view-modes／Copilot ask box／field-well／filters pane）。

剩餘屬**深度而非導航**：field-well 尚不能換 measure、無 drag-drop fields pane、計算指標非 DAX 公式列、篩選單層。

## 第 3 輪 — 深度增量（依使用者「按建議進行」）
**Round 150**：field-well 補上 **值（measure）切換**——下拉選該 block 的指標，換指標時重排 `query/metrics` 治理 patch；`agg_override=None` 讓每個指標保留其認證彙總法（rate/average 指標不會被誤加總，這點評審指出「Power BI 反而不強制」＝真實優勢）。AppTest 實測 revenue→order_count 0 例外。field-well 現為完整「值 / 分組 / 圖表類型」面板。

**Power BI 分析師 re-eval**：S5 76→**87**、S7 72→**78**（計算指標移到 🔗模型 mode 旁邊＋新指標可直接在 field-well 選用）、**整體 81.3→~83.7**。

剩餘到 95 的三項：①原生 drag-drop fields pane（**Streamlit 無原生拖放，須自訂 React 元件＝結構天花板**）②計算指標深度（lineage/格式/公式輔助，可做）③常駐右側 Visualizations pane 映射選取視覺（可做，最便宜的下一步）。導航/手順已到位，剩深度。

## 第 4 輪 — 深度增量（使用者指示：更多元件 + 做 #2、#3）
**Round 151 更多圖表類型**：渲染層本就支援 table/pivot/map；`chart_type_change` 解除對 table（通用）與 pivot（需 ≥2 維度）的封鎖。field-well 圖表類型下拉新增「表格」與「樞紐分析（≥2 維才出現）」。實測 bar→table 套用、bar→pivot 友善擋下並提示需兩維度。
**Round 152 計算指標深度**：guided authoring（點欄位/函式按鈕插入公式 + 清空）、lineage（「🔗 依賴欄位／指標」即時顯示）、顯示格式 preset（數字/百分比/金額/千/萬/次數→unit）。S7 友善度大升。
**Round 153 右側 Visualizations pane**：主畫布改「畫布(左) + 🎨視覺化 pane(右)」；pane 讀 selected_component_id，內嵌 field-well（值/分組/圖表類型）編輯選取的視覺；per-visual 重複面板移除避免 key 衝突；唯讀分享維持全寬。實測選取後 pane 出現 fw_measure/fw_type/fw_dim，0 例外。

非 e2e **1044 passed**，全部 commit+push。

## 第 5 輪 — #1 原生拖放：自訂 React/TS 元件（最高擬真度）
使用者選擇最高擬真度路線。**Round 154**：以 Streamlit Components API 做真正的雙向自訂元件（React 18 + TS + Vite）。
- `ai4bi/ui/components/field_well/`：`frontend/`（React/TS 原始碼 + Vite build，dist 已 commit 以免每台都要 build；node_modules gitignore）、`__init__.py`（`declare_component` 包裝 + `is_available()` graceful fallback）、README（重建步驟）。
- `FieldWell.tsx`：HTML5 drag-drop 把欄位 chip 在 **可用欄位 / 值 / 軸 / 圖例** 之間拖放、圖表類型按鈕、即時「👁 預覽」列、theme-aware；用 `Streamlit.setComponentValue` 回傳指派。
- 視覺化 pane 以拖放元件為主、下拉 field-well 為 fallback；`_apply_field_well_result` 把回傳 wells 轉成治理的 metrics+dimensions+visual_type patch（nonce 去重、需至少一個 measure、pivot 需 2 維）。
- **真實瀏覽器（Playwright）驗證**：選取視覺後 component iframe 內出現 11 個可拖曳 chip、值(Values) well、即時預覽；real server boot HTTP 200。新增 `tests/test_field_well_apply.py`（2）鎖住 server 端套用 round-trip。非 e2e **1046 passed**。
- 四條路線全數落地：sortables（未走）/ elements（未走）/ **自訂 React 元件（已做）**。原本標為「Streamlit 結構天花板」的原生拖放已突破。

