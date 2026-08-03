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
                "components": {"defense": 40, "valuation": 20, "momentum": 10}
                if model_id == "defensive_value"
                else {"operating_momentum": 50, "quality": 20, "valuation_liquidity": 10},
            }
        ],
    }


class WeeklyReportTests(unittest.TestCase):
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
        self.assertIn("雙模型交集逐日變化", page)
        self.assertIn("分數組成變化", page)
        self.assertIn("精華20名單變動", page)
        self.assertNotIn("週初 vs 週末", page)
        self.assertIn('<b class="in">新增</b>', page)
        self.assertIn('<b class="out">移出</b>', page)
        self.assertIn("在榜日／最長連續", page)
        self.assertIn(">2／2</td>", page)
        self.assertNotIn('<th class="number">在榜日</th>', page)
        self.assertNotIn("期初至期末淨進出", page)
        self.assertIn("不是買進建議", page)
        self.assertIn('href="../../latest/index.html"', page)


if __name__ == "__main__":
    unittest.main()
