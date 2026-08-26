# 台股防禦價值與營運動能篩選器

這個專案把「重視下檔安全、絕對／相對便宜、老公司新動能」轉成可稽核的全市場篩選流程。程式只產生研究候選名單，不會下單，也不把量化分數當成投資保證。

## 模型邏輯

- 全市場：上市、上櫃、四位數普通股；排除 ETF、存託憑證。
- 分開處理：金融保險業不套用一般公司的流動比率與清算價值模型。
- 防禦分 50：淨現金、流動比率、負債比率、五年獲利、自由現金流。
- 估值分 30：保守清算價值、同業 PER/PBR 分位、絕對 PER。
- 動能分 20：各公司截至報表日最新完整三個月營收年增、單月營收年增、同業營益率分位、TTM 淨利成長。月初申報期間允許個股期別不同，報表會逐檔標示截止月份。
- 質化否決：治理誠信、新技術催化與商業護城河保留在 `config/manual_review.csv` 人工維護。

商譽的清算折價預設為 0；「30% 最大損失」不作保證。完整門檻位於 `config/screening.json`。

專案另提供獨立的營運動能模型：營運動能 60 分、動能品質 25 分、估值與流動性 15 分；完整設定位於 `config/momentum_screening.json`。兩個模型共用市場與財報資料，但門檻、分數及排名互不混用。

另有獨立的「ETF 雷達」，每日追蹤 00981A、00403A、00991A、00982A、00992A 的完整投資組合，觀察低部位轉向與跨投信共振。ETF 雷達只以個股在基金中的權重判定，不使用股數判定加碼，也不進入雙模型的 100 分評分、硬門檻或排名歷史。完整規格位於 `docs/etf_radar_spec.md`。

## 執行

先在專案根目錄建立 `.env`：

```text
FINMIND_TOKEN=你的實際_token
```

執行資料掃描：

```bash
python3 scripts/run_screen.py
```

掃描會在 `reports/latest/` 產生防禦價值 JSON 與 CSV，並在 `reports/momentum/latest/` 產生營運動能版本。網頁只有一個入口 `reports/latest/index.html`（雙模型監控台），週報在 `reports/weekly/latest/index.html`；兩個模型不再各自輸出單頁 HTML，內容已由入口頁的分頁涵蓋。Excel 報表由 OpenAI artifact runtime 產生。

```bash
node scripts/build_report.mjs reports/latest/screening_results.json outputs/latest/台股防禦價值篩選.xlsx
node scripts/build_momentum_report.mjs reports/momentum/latest/screening_results.json outputs/latest/台股營運動能篩選.xlsx
```

或一次執行全部流程：

```bash
zsh scripts/run_all.sh
```

建議排程於交易日上午執行；模型使用前一個已完成交易日，避免盤中未完整資料。當月營收會按報表日保存不可變快照；當天可定期刷新，日後重跑舊日期不會混入後來才公布的營收。流動性硬門檻使用 20 日均成交額，Excel 主排名則以 20 日均量（張）方便閱讀。

每日完整流程會同時產出 `台股防禦價值篩選_日期.xlsx` 與 `台股營運動能篩選_日期.xlsx`，兩份 Excel 都包含「模型說明」工作表。

完整流程也會為兩模型各自前5名抓取 FinMind 價格與籌碼資料（重複股票只抓一次），產生個股 `日主表.csv`、`週持股表.csv` 及規則式短評。資料固定截止於模型的已完成市場日，避免混入盤中行情；技術面與籌碼面只供入口頁及 Excel 人工複核呈現，不影響分數、硬門檻或排名。

日報入口為 `reports/latest/index.html`；週報入口為 `reports/weekly/latest/index.html`。週報只使用排名歷史中的有效觀測，並自動切開模型版本。月報需先通過 `scripts/check_monthly_readiness.py` 的資料量與同版本門檻，目前不會以不足資料產生。

完整流程完成後會把最新 ETF 雷達與雙模型日報 HTML 推送到遠端 `gh-pages` 分支，再由 GitHub Pages 發布；若已有週報也會一併更新。只發布自包含 HTML，不上傳 `.env`、投信或 FinMind 原始資料、JSON、CSV、Excel、QA 或技術籌碼快取。若只想更新本機，可執行：

```bash
PUBLISH_GITHUB_PAGES=0 zsh scripts/run_all.sh
```

發布失敗只會顯示警告，不會讓模型、排名歷史或本機報表失敗。

重新下載歷史快取可加上 `--force`。日常執行不需要重抓已封存季度資料。

## 人工複核

每日報表會依量化欄位自動產生 50 至 70 字的「模型短評（自動）」，同步寫入 JSON、CSV、入口頁的展開明細與 Excel「人工複核」工作表。短評只摘要硬門檻、財務優勢與量化風險，不取代治理或催化的人工查證，也不構成買進建議。

`config/manual_review.csv` 可填：

- `governance_status`：`待複核`、`通過`、`否決`
- `catalyst`：AI、機器人、矽光子等經查證後的催化說明
- `exclude`：填 `true` 可人工排除
- `notes`：法說、年報或治理風險摘要

即使量化排名進入前 20，仍須完成質化複核後才可能成為集中研究標的。
