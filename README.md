# nativeApp_BundleZip

CIM 平台(**nativeApp + AI4BI + LV + Labeling**)的**已拼裝好、可直接安裝**的原始碼 bundle。
專給**只能下載 ZIP、不能 `git clone --recurse-submodules`** 的電腦使用。

> 這個 repo 只放「產物」(一顆 zip)。原始碼與打包腳本在主 repo
> [`hctsaik/nativeApp`](https://github.com/hctsaik/nativeApp)(`scripts/win/make-source-bundle.ps1`)。
> 本檔由打包流程自動產生,**請勿手動編輯**;要更新就重跑打包腳本重新發布。

## 內容

| 檔案 | 說明 |
|------|------|
| `nativeApp-family-bundle.zip` | 攤平好的單一原始碼 bundle。AI4BI / LV(原 submodule)與 Labeling(原 junction→ANnoTation)都已**實體放進** `vendor\AI4BI`、`vendor\LV`、`plugins\labeling`。已排除 node_modules / venv / 模型權重 / log。 |
| `VERSION.txt` | 這顆 bundle 對應的 nativeApp 來源 commit 與打包時間。 |

## 怎麼用(收到的電腦)

1. 下載 `nativeApp-family-bundle.zip`(點檔名 → Download,或本 repo 的 **Code → Download ZIP** 再解出裡面那顆)。
2. 解壓,會得到一個 `nativeApp\` 資料夾。
3. 打開裡面的 **`00-READ-ME-FIRST.md`**,照著三步裝:
   ```powershell
   $env:PYTHONUTF8 = "1"     # 繁中(CP950)機器必設
   npm install                # 卡 esbuild 就刪 node_modules 重跑
   py -3.11 -m pip install -r sidecar\python-engine\requirements.txt
   py -3.11 -m pip install -e "sidecar\python-engine\vendor\AI4BI[llm]"
   py -3.11 -m pip install -r sidecar\python-engine\plugins\labeling\requirements-labeling.txt
   powershell -ExecutionPolicy Bypass -File scripts\win\verify-setup.ps1   # 要 [OK] 全部通過
   start-dev.bat
   ```

**不需要** git、submodule、junction —— 全都拼好了。詳細踩雷見 bundle 內 `docs\INSTALL.md`。

## 注意
- 這是**原始碼** bundle,不是免安裝執行檔;仍需 Node.js 與 Python 3.11。
- bundle 內沒有 git,**不能 `git pull` 更新**;要更新請回來抓新的一顆。
- LV 的重相依(torch 等)與模型權重會在**首次啟動該工具**時自動安裝/下載,刻意不打包進來。
