# 資料源檢視器 — 驗證紀錄(Round 167)

## 目標
使用者常載入多種資料(JSON / SQL / Service,最後正規化成表格),需要便宜地知道:
**目前載入了哪些資料源、各自有哪些資料/型態**;而且**大資料的預覽不能吃爆資源/時間**。
用 multi-agent 思考 UI/UX 與功能,跑 10 情境驗證到全部 ≥95。

## 設計原則:昂貴的路徑全部 opt-in
- **schema 與形狀免載入** — 讀 block contract(`columns` + `data_source.row_count`),不載入任何列。
- **預覽取樣且延遲** — 預設收合;勾選才載入,且只取前 N 列(`datastore.sample_dataframe`:
  inline 只切 `records[:n]`;cached 對已在記憶體 store 的 frame 做 `.head(n)` 廉價 view)。
- **統計只算在樣本上**,明確標示「取樣估計,非全表」,並用 **bounded `@st.cache_data`
  (max_entries=64, ttl=600)** 快取,reruns 不重算、記憶體有界。

## 交付
| 檔案 | 內容 |
|------|------|
| `ai4bi/blocks/datastore.py` | `source_row_count`(metadata 列數,零載入)、`sample_dataframe`(取樣,不物化整表) |
| `ai4bi/ui/data_inspector.py` | `schema_rows` / `profile_sample` / `source_shape` / `classify_cost`(純函式)+ `render_source_inspector`(schema 免載入 + opt-in 取樣預覽 + bounded cache) |
| `ai4bi/ui/data_model.py` | 資料源管理器:總來源數/關聯/約總列數(全 metadata);每來源接上檢視器;相對載入時間 |
| `ai4bi/ui/upload.py` | 上傳 meta 加 `uploaded_at` |
| `tests/test_data_inspector.py` | 9 個單元測試(metadata 零載入、取樣上限、profile 取樣統計) |

每個來源(內建/示範 + 你上傳)一個預設收合的檢視器:成本徽章 🟢/🟡/🔴/⚪、欄位結構表
(欄位 / 型態圖示+文字 / 可空)、schema CSV 匯出、寬表欄位搜尋、上傳來源顯示載入時間;
「🔍 載入取樣預覽與統計」勾選後顯示前 N 列 + 每欄統計(非空率含 ⚠️ 低完整度標記、種類數、
數值 min/max、類別最常見值+次數),並附白話說明。

## Multi-agent 驗證(3 persona:資料工程師 / 效能 / SMB 老闆 × 10 情境,每輪換新批)

| 輪次 | 資料工程師 | 效能 | SMB 老闆 | 動作 |
|-----:|----------:|-----:|--------:|------|
| 1 | 84.8 | 90.5 | 86.9 | 抓到:統計未快取(每次 rerun 重算)、缺欄位搜尋/匯出/Top-K、型態詞彙、資料品質不顯眼 |
| 2 | 93.9 | 91.7 | 88.8 | 修:bounded cache、schema CSV 匯出、欄位搜尋、最常見值+次數、預覽更明顯 |
| 3 | 96.7 | 97.4 | 94.5 | 修:⚠️ 低完整度標記、相異值→種類數、上傳時間 freshness |
| 4 | (96.7) | (97.4) | **97.3** | 修:⚠️/種類數 白話說明、相對時間(今天/昨天);**三者全部 ≥95、每情境 ≥95** |

最終每個 persona 平均皆 ≥95(96.7 / 97.4 / 97.3),所有情境 ≥95。

## 通則
- UI 任何「看資料」的動作,先用 metadata(contract/row_count)回答;真的要碰資料時只取樣、要 opt-in、要快取且有上限。
- 取樣統計一律標「取樣估計,非全表」,避免被誤當全表精算。
