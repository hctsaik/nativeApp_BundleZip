# 媒體素材 (Demo 影片等)

大型媒體檔（螢幕錄影、demo 影片）**不放進 git 歷史**，改以 **GitHub Release 附件**
形式存放，避免 clone 被大檔拖累、也避開 GitHub 的單檔大小限制。`.gitignore` 已忽略
`*.mp4` / `*.mov` / `*.webm`。

本檔只保存指向這些素材的連結。

## Demo 錄影

| 日期 | 說明 | 連結 |
|---|---|---|
| 2026-05-31 | AI4BI 操作示範錄影（約 85 MB） | [demo-2026-05-31.mp4](https://github.com/hctsaik/AI4BI/releases/download/demo-2026-05-31/demo-2026-05-31.mp4) ・ [Release 頁面](https://github.com/hctsaik/AI4BI/releases/tag/demo-2026-05-31) |

## 如何新增一支影片

```bash
# 1) 用去空白的描述性檔名（例：demo-YYYY-MM-DD.mp4）
# 2) 建立 / 上傳到 Release（gh 需登入或沿用 git 既有 credential）
gh release create demo-YYYY-MM-DD "demo-YYYY-MM-DD.mp4" \
    --title "AI4BI Demo 錄影 YYYY-MM-DD" \
    --notes "操作示範錄影。"
# 3) 把連結加到上面的表格
```
