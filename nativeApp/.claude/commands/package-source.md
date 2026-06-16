# /package-source — 打包原始碼 zip

## 說明

將整個專案打包成可攜帶的原始碼 zip，用於換電腦或傳送給他人。
有兩種模式，執行前請先確認要哪一種。

---

> **注意（catalog 事實來源）**：`tools.sqlite` 是 **per-device 衍生快取**，
> 收件方首次 `start-dev.bat` 會自動由 `plugin.yaml + sheet YAML + config/seed.yaml`
> 重建，**不需要、也不應該**隨原始碼打包。詳見
> [docs/platform/catalog-source-of-truth-discussion.md](../../docs/platform/catalog-source-of-truth-discussion.md)。

## 模式 A：完整原始碼（換電腦用）

```powershell
python packages/source-code-packager/scripts/package_source_zip.py `
  --root . --include-all `
  --exclude-dir .venv-xanylabeling --exclude-dir .claude `
  --exclude-dir external_exe --exclude-dir release --exclude-dir _release --exclude-dir testData `
  --exclude-dir logs --exclude-dir tmp `
  --name ../nativeApp_source
```

**輸出**：`../nativeApp_source.zip`

> 若想連同**執行期啟停狀態**（在管理中心改過的 Module 啟停等，非目錄定義）一起帶走，
> 可額外加 `--include-file "apps/host-electron/logs/data/tools.sqlite"`；
> 一般情況不需要，目錄定義會在目標機首啟自動重建。

---

## 模式 B：Gmail 安全模式

附件大小符合 Gmail 限制。

```powershell
python packages/source-code-packager/scripts/package_source_zip.py `
  --root . --include-all `
  --exclude-dir .venv-xanylabeling --exclude-dir .claude `
  --exclude-dir external_exe --exclude-dir release --exclude-dir _release --exclude-dir testData `
  --gmail-safe --name ../nativeApp_source_gmail_safe
```

**輸出**：`../nativeApp_source_gmail_safe.zip`

---

## 收件方解壓後的首次設定

```powershell
# 僅 Gmail-safe zip 需要（還原被改名的檔案）
python restore_gmail_safe_filenames.py

npm install
pip install -r sidecar/python-engine/requirements.txt
start-dev.bat
```

---

## 注意事項

- 執行前確認工作目錄在 repo 根目錄
- 若要同時包含最新的 SQLite，先確認 app 已正常關閉（避免 WAL 鎖）
- Gmail 安全模式收件方**必須**先執行 `restore_gmail_safe_filenames.py`，否則部分檔案路徑會錯誤
