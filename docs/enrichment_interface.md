# 技術面與籌碼面外部資料接口

報表可選擇性讀取：

`data/processed/enrichment/{as_of}/technical_chip_summary.json`

最小格式：

```json
{
  "as_of": "2026-08-03",
  "stocks": {
    "2330": {
      "technical": {"status": "中性", "summary": "日線與週線摘要"},
      "chip": {"status": "待觀察", "summary": "持股與籌碼摘要"},
      "source_date": "2026-08-03"
    }
  }
}
```

`technical` 與 `chip` 也可直接使用字串。檔案不存在、JSON 無效或個股欄位缺漏時，報表顯示 `—`，掃描流程仍繼續。

此接口只有呈現用途：

- 允許出現在 HTML 候選表與 Excel「人工複核」頁。
- 禁止進入 `total_score`、`hard_pass`、`funnel_stage` 或任何影響 `model_status` 的檢核。
- 禁止寫入 `rankings_history.jsonl` 的 `rankings`，以保留模型基準線與前瞻報酬檢定的可比性。

每日流程會執行：

```bash
python3 scripts/build_technical_chip_enrichment.py --as-of YYYY-MM-DD --top-n 5
```

它取兩模型各自前5名並去重，使用與 `FinMind抓取器.app` 相同的價格、法人、外資持股、融資券及集保持股級距資料集。每檔另保留：

- `data/processed/enrichment/{as_of}/{stock_id}/日主表.csv`
- `data/processed/enrichment/{as_of}/{stock_id}/週持股表.csv`

短評由固定規則和可稽核數字產生，不交由語言模型猜測；資料不足時明確顯示「資料不足」。產出保留30天。
