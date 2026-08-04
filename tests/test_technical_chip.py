from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.technical_chip import (  # noqa: E402
    analyze_chip,
    analyze_technical,
    rows_through,
    top_stock_universe,
)


def result(model_id: str, stock_ids: list[str]) -> dict:
    return {
        "metadata": {"model_id": model_id},
        "results": [
            {"stock_id": stock_id, "stock_name": f"公司{stock_id}", "rank": rank, "hard_pass": True}
            for rank, stock_id in enumerate(stock_ids, start=1)
        ],
    }


class TechnicalChipTests(unittest.TestCase):
    def test_top_stocks_are_per_model_and_deduplicated(self) -> None:
        stock_ids, selection = top_stock_universe(
            result("defensive_value", ["1101", "1102", "1103"]),
            result("operating_momentum", ["1102", "2201", "2202"]),
            top_n=2,
        )
        self.assertEqual(stock_ids, ["1101", "1102", "2201"])
        self.assertEqual(selection["1102"]["models"], {"defensive_value": 2, "operating_momentum": 1})

    def test_rising_price_series_is_marked_strong(self) -> None:
        start = date(2026, 1, 1)
        rows = [
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "close": 50 + index,
                "Trading_Volume": 1_000_000 + index * 1_000,
            }
            for index in range(80)
        ]
        block = analyze_technical(rows)
        self.assertEqual(block["status"], "趨勢偏強")
        self.assertEqual(block["tone"], "up")
        self.assertIn("站上20／60日線", block["summary"])

    def test_short_price_series_is_explicitly_incomplete(self) -> None:
        block = analyze_technical([{"date": "2026-08-03", "close": 10}])
        self.assertEqual(block["status"], "資料不足")
        self.assertEqual(block["metrics"]["valid_days"], 1)

    def test_rows_after_completed_market_date_are_excluded(self) -> None:
        rows = [{"date": "2026-08-03"}, {"date": "2026-08-04"}]
        self.assertEqual(rows_through(rows, "2026-08-03"), [{"date": "2026-08-03"}])

    def test_improving_chip_signals_use_source_tone(self) -> None:
        institutional = []
        for day in range(1, 6):
            institutional.extend(
                [
                    {"date": f"2026-08-0{day}", "name": "Foreign_Investor", "buy": 200_000, "sell": 0},
                    {"date": f"2026-08-0{day}", "name": "Investment_Trust", "buy": 100_000, "sell": 0},
                ]
            )
        holding = [
            {"date": "2026-07-24", "HoldingSharesLevel": "more than 1,000,001", "percent": 40.0},
            {"date": "2026-07-31", "HoldingSharesLevel": "more than 1,000,001", "percent": 40.5},
        ]
        margin = [
            {"date": f"2026-07-{day:02d}", "MarginPurchaseTodayBalance": 1_000 - day * 20}
            for day in range(21, 28)
        ]
        block = analyze_chip(institutional, [], margin, holding)
        self.assertEqual(block["status"], "籌碼改善")
        self.assertEqual(block["tone"], "up")
        self.assertIn("外資近5日買超", block["summary"])


if __name__ == "__main__":
    unittest.main()
