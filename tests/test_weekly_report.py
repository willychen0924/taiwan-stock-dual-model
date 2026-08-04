from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.weekly_report import (  # noqa: E402
    build_weekly_html,
    completed_week_window,
    last_eligible_by_market_date,
    longest_version_segment,
    market_focus_block,
)


def record(model_id: str, market_date: str, *, version: str | None = "0.2.0", eligible: bool = True, rank: int = 1) -> dict:
    return {
        "model_id": model_id,
        "latest_market_date": market_date,
        "config_version": version,
        "eligible_for_backtest": eligible,
        "ineligible_reasons": [] if eligible else ["覆蓋率不足"],
        "rankings": [
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "rank": rank,
                "total_score": 80 - rank,
                "industry": "半導體業",
                "components": {"defense": 40, "valuation": 20, "momentum": 10}
                if model_id == "defensive_value"
                else {"operating_momentum": 50, "quality": 20, "valuation_liquidity": 10},
            }
        ],
    }


class WeeklyReportTests(unittest.TestCase):
    def test_market_focus_renders_sources_and_keeps_news_separate_from_model(self) -> None:
        context = {
            "market_environment": {
                "summary": "櫃買弱於加權，風險偏好下降。",
                "source": {"label": "市場資料", "url": "https://example.com/market"},
            },
            "industry_theme": {
                "summary": "晶片股由動能交易轉向風險檢驗。",
                "news": [{
                    "date": "2026-07-29",
                    "source": "測試來源",
                    "title": "晶片股新聞",
                    "url": "https://example.com/news",
                    "summary": "AI 資本支出成為焦點。",
                }],
            },
            "model_alignment": {"summary": "模型仍集中半導體，但不代表風險消失。"},
            "disclaimer": "新聞只供研究呈現，不進模型。",
        }
        block = market_focus_block(context)
        self.assertIn("本週市場焦點", block)
        self.assertIn("市場環境", block)
        self.assertIn('href="https://example.com/market"', block)
        self.assertIn("晶片股新聞", block)
        self.assertIn("AI 資本支出成為焦點", block)
        self.assertIn("模型仍集中半導體", block)
        self.assertIn("不進模型", block)

    def test_completed_week_uses_previous_week_on_monday(self) -> None:
        records = [record("defensive_value", "2026-07-31")]
        self.assertEqual(completed_week_window(records, as_of=date(2026, 8, 3)), (date(2026, 7, 27), date(2026, 7, 31)))

    def test_last_eligible_version_wins_on_same_market_date(self) -> None:
        records = [
            record("defensive_value", "2026-07-31", rank=5),
            record("defensive_value", "2026-07-31", eligible=False),
            record("defensive_value", "2026-07-31", rank=2),
        ]
        selected, invalid = last_eligible_by_market_date(
            records,
            model_id="defensive_value",
            week_start=date(2026, 7, 27),
            week_end=date(2026, 7, 31),
        )
        self.assertEqual(selected[0]["rankings"][0]["rank"], 2)
        self.assertEqual(invalid, [])

    def test_longest_segment_does_not_cross_model_version(self) -> None:
        records = [
            record("defensive_value", "2026-07-27", version="0.1.0"),
            record("defensive_value", "2026-07-28", version="0.1.0"),
            record("defensive_value", "2026-07-29", version="0.2.0"),
        ]
        longest, segments = longest_version_segment(records)
        self.assertEqual(len(segments), 2)
        self.assertEqual([item["latest_market_date"] for item in longest], ["2026-07-27", "2026-07-28"])

    def test_weekly_page_contains_quality_and_model_tabs(self) -> None:
        records = []
        for market_date in ["2026-07-27", "2026-07-28"]:
            records.extend([record("defensive_value", market_date), record("operating_momentum", market_date)])
        page = build_weekly_html(records, week_start=date(2026, 7, 27), week_end=date(2026, 7, 31))
        self.assertIn("資料品質", page)
        self.assertIn("雙模型交集", page)
        self.assertIn("本週摘要", page)
        self.assertIn(
            "期末精華20產業分布：防禦價值以半導體業 1 檔為主；"
            "營運動能以半導體業 1 檔為主。",
            page,
        )
        self.assertIn("較上週變化", page)
        self.assertIn("精華20產業分布", page)
        self.assertIn('class="industry-grid"', page)
        self.assertIn(".industry-grid .ibar{grid-template-columns:minmax(120px,150px)", page)
        self.assertIn(".industry-grid>div:last-child{padding-left:32px;border-left:1px", page)
        self.assertIn('<span class="icount">1 檔</span>', page)
        self.assertIn("人工複核進度", page)
        self.assertNotIn("分數組成變化", page)  # 週內幾乎只有估值區塊會動，三欄裡兩欄恆為 0
        self.assertIn("精華20名單變動", page)
        self.assertNotIn("週初 vs 週末", page)
        self.assertIn('<b class="in">新增</b>', page)
        self.assertIn('<b class="out">移出</b>', page)
        self.assertIn("在榜／連續", page)
        self.assertIn(">2／2</td>", page)
        self.assertIn("--stock-key:62px;--stock-code:66px;--stock-name:116px", page)
        self.assertIn("--stock-period:92px;--stock-detail:148px", page)
        self.assertIn(".stocktable tbody td{vertical-align:middle}", page)
        self.assertNotIn("部分天數", page)
        self.assertIn("2 個有效市場日的交集名單相同。", page)
        self.assertNotIn('<details class="intersection-days">', page)
        self.assertIn('▲ 上升最多', page)
        self.assertIn('▼ 下降最多', page)
        self.assertNotIn("期初至期末淨進出", page)
        self.assertIn("不是買進建議", page)
        self.assertIn('href="../../latest/index.html"', page)

    def test_version_warning_lists_only_unselected_segments_as_other(self) -> None:
        records = []
        for model_id in ["defensive_value", "operating_momentum"]:
            records.extend(
                [
                    record(model_id, "2026-07-27", version="0.1.0"),
                    record(model_id, "2026-07-28", version="0.1.0"),
                    record(model_id, "2026-07-29", version="0.2.0"),
                ]
            )
        page = build_weekly_html(records, week_start=date(2026, 7, 27), week_end=date(2026, 7, 31))
        # 區間說明自成一句：採用的區間與被排除的區間都寫在面板內
        self.assertIn("比較區間 <b>2026-07-27～2026-07-28</b>（0.1.0，2 個有效市場日）", page)
        self.assertIn("已排除 2026-07-29～2026-07-29（0.2.0，1 日）", page)
        # 被採用的區間不得同時被列為排除
        self.assertNotIn("已排除 2026-07-27", page)

    def test_version_notice_stays_inside_the_panel(self) -> None:
        """版本說明就在該模型面板內，不另闢頁尾區塊，也不用警示樣式。"""
        records = []
        for model_id in ["defensive_value", "operating_momentum"]:
            records.extend([
                record(model_id, "2026-07-27", version="0.1.0"),
                record(model_id, "2026-07-28", version="0.2.0"),
            ])
        page = build_weekly_html(records, week_start=date(2026, 7, 27), week_end=date(2026, 7, 31))
        body = page[page.index("</style>"):]
        self.assertNotIn("模型版本與比較區間", body)
        self.assertNotIn('class="weekly-warning"', body)
        self.assertIn("跨版本的名次差異", body)

    def test_tab_order_matches_the_daily_portal(self) -> None:
        """模型分頁在前、彙總在後，預設停在營運動能，與日報一致。"""
        records = [record(model_id, "2026-07-27") for model_id in ["defensive_value", "operating_momentum"]]
        page = build_weekly_html(records, week_start=date(2026, 7, 27), week_end=date(2026, 7, 31))
        self.assertIn('id="w-momentum" class="tabin" checked', page)
        labels = [page.index(f'<label for="w-{key}">') for key in ("momentum", "value", "overview")]
        self.assertEqual(labels, sorted(labels))
        panels = [page.index(f'id="weekly-{key}"') for key in
                  ("operating_momentum", "defensive_value", "overview")]
        self.assertEqual(panels, sorted(panels))


    def test_week_over_week_needs_same_model_version(self) -> None:
        """跨版本的週對週差異同時含市場與模型變動，不可歸因，因此不計算。"""
        from value_screener.weekly_report import week_over_week
        same = [record("defensive_value", "2026-07-20"), record("defensive_value", "2026-07-27")]
        result = week_over_week(same, model_id="defensive_value",
                                week_start=date(2026, 7, 27), week_end=date(2026, 7, 31))
        self.assertTrue(result["comparable"])
        self.assertEqual([item["stock_id"] for item in result["stayed"]], ["2330"])

        crossed = [record("defensive_value", "2026-07-20", version="0.1.0"),
                   record("defensive_value", "2026-07-27", version="0.2.0")]
        result = week_over_week(crossed, model_id="defensive_value",
                                week_start=date(2026, 7, 27), week_end=date(2026, 7, 31))
        self.assertFalse(result["comparable"])
        self.assertIn("跨版本不可比", result["reason"])

    def test_intersection_splits_full_week_from_partial(self) -> None:
        from value_screener.weekly_report import intersection_persistence
        def rec(stock_ids):
            return {"rankings": [{"stock_id": s, "stock_name": s, "rank": i + 1}
                                 for i, s in enumerate(stock_ids)]}
        value = {"2026-07-27": rec(["1111", "2222"]), "2026-07-28": rec(["1111", "3333"])}
        momentum = {"2026-07-27": rec(["1111", "2222"]), "2026-07-28": rec(["1111"])}
        always, partial, days = intersection_persistence(value, momentum)
        self.assertEqual(days, 2)
        self.assertEqual([item["stock_id"] for item in always], ["1111"])
        self.assertEqual([(item["stock_id"], n) for item, n in partial], [("2222", 1)])

    def test_intersection_daily_details_group_identical_periods(self) -> None:
        records = []
        for market_date, stock_id in [
            ("2026-07-27", "1111"),
            ("2026-07-28", "1111"),
            ("2026-07-29", "2222"),
        ]:
            for model_id in ["defensive_value", "operating_momentum"]:
                item = record(model_id, market_date)
                item["rankings"][0]["stock_id"] = stock_id
                item["rankings"][0]["stock_name"] = f"公司{stock_id}"
                records.append(item)
        page = build_weekly_html(
            records,
            week_start=date(2026, 7, 27),
            week_end=date(2026, 7, 31),
        )
        self.assertIn(
            '<details class="intersection-days"><summary>交集名單變化（3 個有效日／2 個區間）</summary>',
            page,
        )
        self.assertIn("2026-07-27～2026-07-28", page)
        self.assertIn("2026-07-29", page)
        self.assertIn(".intersection-days .tablewrap tbody td{padding-top:6px;padding-bottom:6px;vertical-align:middle}", page)
        self.assertIn(".intersection-days .weekly-chip{padding:2px 7px;margin:0 4px 0 0", page)

    def test_manual_review_progress_counts_only_decided_rows(self) -> None:
        from value_screener.weekly_report import manual_review_progress
        review = {
            "1111": {"governance_status": "通過"},
            "2222": {"governance_status": "待複核"},
            "3333": {"governance_status": ""},
        }
        progress = manual_review_progress(review, {"1111", "2222", "4444"})
        self.assertEqual(progress["filled"], 3)
        self.assertEqual(progress["reviewed"], 1)
        self.assertEqual(progress["focus_total"], 3)
        self.assertEqual(progress["focus_reviewed"], 1)


if __name__ == "__main__":
    unittest.main()
