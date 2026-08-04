# 日／週／月報政策

## 日報

- 入口：`reports/latest/index.html`
- 同時呈現雙模型交集、防禦價值及營運動能。
- 雙模型交集只有在兩模型資料皆有效且市場日一致時才產生。
- 排名變動取同模型、同設定版本、較早市場日的最後一份有效記錄。

## 週報

- 入口：`reports/weekly/latest/index.html`
- 模型排名區塊由 `data/processed/rankings_history.jsonl` 產生；「本週市場焦點」可另讀取同週的 `data/processed/weekly_context/` 脈絡檔。
- 缺少市場脈絡檔時退回純量化摘要，不影響週報產生；新聞與宏觀內容不進入模型分數或排名歷史。
- 每個市場日取檔案中最後一份有效版本。
- 失效日不進入交集、進出榜、穩定度或名次比較。
- 同一週若出現多個模型版本，分段後只比較最長同版本區間，不做跨版本歸因。
- 「精華20名單變動」比較同版本最長區間第一日與最後一日的名單，只顯示新增與移出，不代表研究或交易建議。

## GitHub Pages

- `scripts/run_all.sh` 完成本機報表後，呼叫 `scripts/publish_github_pages.sh`。
- 發布分支固定為 `gh-pages`，內容只有根目錄導向頁、最新日報及最新週報 HTML。
- `.env`、FinMind 原始資料、JSON、CSV、Excel、QA 與技術籌碼快取禁止進入發布分支。
- 網路或 GitHub 發布失敗只警告，不回滾本機模型、排名歷史或報表。
- 設定 `PUBLISH_GITHUB_PAGES=0` 可停用遠端發布。

## 月報啟用條件

月報導覽目前停用。`config/reporting_policy.json` 規定前一個完整月份必須同時符合：

- 每個模型至少 18 個有效市場日。
- 每個模型最長的同版本區間至少 15 個市場日。
- 仍須排除失效日及跨版本比較。

以 `python3 scripts/check_monthly_readiness.py --as-of YYYY-MM-DD` 檢查；未達門檻時不得產生看似完整的月報。

## 前瞻報酬

5／20／60 日前瞻報酬目前停用。啟用前必須具備完整持有期間，並使用還原價格或明確處理除權息及公司行動。排名只作研究排序，不得描述為買進建議。
