在新的開發對話開始時，執行以下步驟，讓開發者可以立刻知道工作進度並無縫繼續。

## Step 1 — 讀取上次斷點

讀取 `C:\Users\hctsa\.claude\projects\c--code-claude-nativeApp\memory\current_focus.md`。
若檔案不存在，跳到 Step 2 直接掃描 tasks.md。

## Step 2 — 掃描所有 tasks.md 找出未完成項目

讀取以下檔案，列出所有 `- [ ]` 項目：
- `openspec/changes/hybrid-edge-microfrontend-platform/tasks.md`
- `openspec/changes/opencv-image-processing-tool/tasks.md`
- `openspec/changes/cv-modular-tool-framework/tasks.md`

若有其他 `openspec/changes/*/tasks.md`，一併讀取。

## Step 3 — 向使用者輸出開發簡報

用以下格式輸出，**不要省略任何一段**：

```
── 開發進度摘要 ──────────────────────────────

上次完成：
  [從 current_focus.md 的「本次完成」取出，若無則寫「無記錄」]

下一步（最優先）：
  [從 current_focus.md 的「下一步」取出；若無，取 tasks.md 第一個未完成項目]

待辦清單（未完成）：
  [spec名稱]
    • [未完成項目1]
    • [未完成項目2]
    ...

相關檔案：
  [從 current_focus.md 的「相關檔案」取出；若無，列出與下一步相關的路徑]

注意事項：
  [從 current_focus.md 的「重要決策 / 注意事項」取出；若無則省略此段]

──────────────────────────────────────────────
準備好從「[下一步]」繼續了，要開始嗎？
```

## Step 4 — 等待使用者確認後開始工作

使用者回覆確認後，直接開始執行下一步，不需要再問其他問題。
