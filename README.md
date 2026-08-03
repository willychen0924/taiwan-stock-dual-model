# 台股價值與營運動能篩選器

這個專案把「重視下檔安全、絕對／相對便宜、老公司新動能」轉成可稽核的全市場篩選流程。程式只產生研究候選名單，不會下單，也不把量化分數當成投資保證。

## 模型邏輯

- 全市場：上市、上櫃、四位數普通股；排除 ETF、存託憑證。
- 分開處理：金融保險業不套用一般公司的流動比率與清算價值模型。
- 防禦分 50：淨現金、流動比率、負債比率、五年獲利、自由現金流。
- 估值分 30：保守清算價值、同業 PER/PBR 分位、絕對 PER。
- 動能分 20：各公司截至報表日最新完整三個月營收年增、單月營收年增、同業營益率分位、TTM 淨利成長。月初申報期間允許個股期別不同，報表會逐檔標示截止月份。
- 質化否決：治理誠信、新技術催化與商業護城河保留在 `config/manual_review.csv` 人工維護。

商譽的清算折價預設為 0；「30% 最大損失」不作保證。完整門檻位於 `config/screening.json`。

專案另提供獨立的高品質營運動能模型：營運動能 60 分、動能品質 25 分、估值與流動性 15 分；完整設定位於 `config/momentum_screening.json`。兩個模型共用市場與財報資料，但門檻、分數及排名互不混用。

## 執行

先在專案根目錄建立 `.env`：

```text
FINMIND_TOKEN=你的實際_token
```

執行資料掃描：

```bash
python3 scripts/run_screen.py
```

掃描會在 `reports/latest/` 產生防禦型價值 JSON、CSV 與 HTML，並在 `reports/momentum/latest/` 產生營運動能版本。Excel 報表由 OpenAI artifact runtime 產生。

```bash
node scripts/build_report.mjs reports/latest/screening_results.json outputs/latest/台股價值篩選.xlsx
node scripts/build_momentum_report.mjs reports/momentum/latest/screening_results.json outputs/latest/台股營運動能.xlsx
```

或一次執行全部流程：

```bash
zsh scripts/run_all.sh
```

建議排程於交易日上午執行；模型使用前一個已完成交易日，避免盤中未完整資料。當月營收會按報表日保存不可變快照；當天可定期刷新，日後重跑舊日期不會混入後來才公布的營收。流動性硬門檻使用 20 日均成交額，HTML 與 Excel 主排名則以 20 日均量（張）方便閱讀。

每日完整流程會同時產出 `台股價值篩選_日期.xlsx` 與 `台股營運動能_日期.xlsx`，兩份 Excel 都包含「模型說明」工作表。

重新下載歷史快取可加上 `--force`。日常執行不需要重抓已封存季度資料。

## 人工複核

每日報表會依量化欄位自動產生 50 至 70 字的「模型短評（自動）」，同步寫入 JSON、CSV、HTML 與 Excel「人工複核」工作表。短評只摘要硬門檻、財務優勢與量化風險，不取代治理或催化的人工查證，也不構成買進建議。

`config/manual_review.csv` 可填：

- `governance_status`：`待複核`、`通過`、`否決`
- `catalyst`：AI、機器人、矽光子等經查證後的催化說明
- `exclude`：填 `true` 可人工排除
- `notes`：法說、年報或治理風險摘要

即使量化排名進入前 20，仍須完成質化複核後才可能成為集中研究標的。
