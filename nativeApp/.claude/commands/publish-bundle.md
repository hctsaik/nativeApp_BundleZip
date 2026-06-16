# /publish-bundle — 打包「全家桶」原始碼並發布到 nativeApp_BundleZip

## 說明

把 **nativeApp + AI4BI + LV + Labeling** 攤平成**單一、可直接安裝**的原始碼 bundle,
並**自動 commit + push** 到產物 repo
[`hctsaik/nativeApp_BundleZip`](https://github.com/hctsaik/nativeApp_BundleZip)。

專給**只能下載 ZIP、不能 `git clone --recurse-submodules`** 的電腦使用:收件方解壓後
不需要 git / submodule / junction,照 bundle 內 `00-READ-ME-FIRST.md` 裝即可。

> 分工:**原始碼 + 打包腳本**留在 `nativeApp`;**產出的 zip**(大檔)只進 `nativeApp_BundleZip`,
> 不汙染主 repo 歷史。和 `/package-source`(打包整包平台原始碼換電腦用)不同 —— 本指令專做
> 「四合一、攤平、發布到固定下載點」。

## 前置

- 在 repo 根目錄執行,且 submodule 已 checkout、labeling junction 已掛載
  (`git submodule update --init --recursive` + `scripts\win\link-labeling.bat`;
  `make-source-bundle.ps1` 會自動檢查,缺了會擋下並提示)。
- 能 push 到 `nativeApp_BundleZip`(Git Credential Manager 已存帳密,或先 `gh auth login`)。

## 執行(一行)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\publish-bundle.ps1
```

會依序:
1. 跑 `make-source-bundle.ps1` 產生乾淨 bundle(排除 node_modules / venv / `.tool-venvs` /
   模型權重 / log / >50MB 檔)。
2. clone `nativeApp_BundleZip`,把 zip 以固定檔名 `nativeApp-family-bundle.zip` 放入
   (下載 URL 永遠不變),刷新 `README.md` 與 `VERSION.txt`(記錄來源 commit)。
3. `git add / commit / push`。**內容沒變就略過 commit**。

## 只想打包、先不發布?

```powershell
powershell -ExecutionPolicy Bypass -File scripts\win\make-source-bundle.ps1
```

輸出在 `release\nativeApp-family-bundle-<日期時間>.zip`(`release\` 已 gitignore,不會進版控)。

## 注意事項

- 產物 repo 用「固定檔名覆蓋」策略:下載點穩定,版本歷史靠該 repo 的 git log。
- bundle 是**原始碼**(仍需 Node.js + Python 3.11),不是免安裝 exe。
- 改完 `scripts\win\bundle-repo-readme.md` 後重跑本指令,產物 repo 的 README 會一起更新。
