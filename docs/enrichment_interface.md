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
