在這次開發對話結束前，執行以下步驟把工作狀態完整保存下來，讓下一次開發可以無縫接續。

## Step 1 — 掃描本次對話的完成項目

回顧這次對話中實際完成的工作，整理成清單。

## Step 2 — 更新 tasks.md

找出所有 `openspec/changes/*/tasks.md` 檔案，把本次已完成的項目從 `- [ ]` 改為 `- [x]`。只改確實完成的，未完成的保持原狀。

## Step 3 — 寫入 current_focus.md

將以下內容寫入（覆蓋）`C:\Users\hctsa\.claude\projects\c--code-claude-nativeApp\memory\current_focus.md`：

```markdown
---
name: Current Development Focus
description: 最近一次開發的斷點記錄，下次開發從這裡繼續
type: project
---

## 本次完成

[條列本次實際完成的事項]

## 下一步（最優先）

[從 tasks.md 找出第一個未打勾的項目，寫清楚檔案位置與具體行動]

## 相關檔案

[列出與下一步直接相關的檔案路徑]

## 重要決策 / 注意事項

[本次做了哪些重要決定，或有哪些坑需要下次注意]

## 記錄時間

[當前日期時間]
```

## Step 4 — 更新 MEMORY.md index

確認 `C:\Users\hctsa\.claude\projects\c--code-claude-nativeApp\memory\MEMORY.md` 有 current_focus.md 的條目。若沒有，加上：

```
- [Current Focus](current_focus.md) — 最近斷點：[一句話說明下一步]
```

若已有，更新那一行的說明文字。

## Step 5 — 向使用者確認

輸出以下摘要讓使用者確認記錄正確：

```
✓ Checkpoint 已儲存

本次完成：
  • [項目1]
  • [項目2]

下次繼續：
  [具體的下一步行動]

相關檔案：
  [路徑]
```
