from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.config import validate_config  # noqa: E402
from value_screener.model import (  # noqa: E402
    descending_score,
    latest_complete_revenue_period,
    linear_score,
    parse_balance,
    parse_cashflow,
    revenue_window_yoy,
)
from value_screener.quality import revenue_coverage_checks, revenue_signal_coverage_metrics  # noqa: E402
from value_screener.dates import latest_complete_quarter  # noqa: E402
from value_screener.pipeline import _require_latest_snapshots, _select_recent_trading_dates  # noqa: E402
from datetime import date


class ScoreTests(unittest.TestCase):
    def test_linear_score_bounds(self) -> None:
        self.assertEqual(linear_score(-1, 0, 1, 10), 0)
        self.assertEqual(linear_score(2, 0, 1, 10), 10)
        self.assertAlmostEqual(linear_score(0.25, 0, 1, 10), 2.5)

    def test_descending_score_bounds(self) -> None:
        self.assertEqual(descending_score(5, 10, 40, 4), 4)
        self.assertEqual(descending_score(50, 10, 40, 4), 0)
        self.assertAlmostEqual(descending_score(25, 10, 40, 4), 2)

    def test_revenue_coverage_uses_only_hard_pass_rows(self) -> None:
        rows = [
            {"hard_pass": True, "close": 10, "industry": "半導體業", "revenue_3m_yoy": 0.1},
            {"hard_pass": True, "close": 10, "industry": "半導體業", "revenue_3m_yoy": None},
            {"hard_pass": False, "close": 10, "industry": "半導體業", "revenue_3m_yoy": 0.2},
        ]
        checks, metrics = revenue_coverage_checks(
            rows,
            threshold=0.8,
            financial_industries={"金融業"},
        )
        self.assertEqual(metrics["ranked_revenue_coverage"], 0.5)
        self.assertEqual(metrics["universe_revenue_coverage"], 2 / 3)
        self.assertEqual([item["status"] for item in checks], ["WARN", "WARN"])

        acceleration = revenue_signal_coverage_metrics(
            [
                {"hard_pass": True, "close": 10, "industry": "半導體業", "revenue_acceleration": 0.1},
                {"hard_pass": False, "close": 10, "industry": "半導體業", "revenue_acceleration": None},
            ],
            signal_key="revenue_acceleration",
            financial_industries={"金融業"},
        )
        self.assertEqual(acceleration["ranked_revenue_coverage"], 1)
        self.assertEqual(acceleration["universe_revenue_coverage"], 0.5)


class FinancialParsingTests(unittest.TestCase):
    def test_balance_and_debt_do_not_use_percentage_rows(self) -> None:
        rows = [
            {"type": "CashAndCashEquivalents", "value": 100, "origin_name": "現金及約當現金"},
            {"type": "CashAndCashEquivalents_per", "value": 10, "origin_name": "現金及約當現金"},
            {"type": "ShorttermBorrowings", "value": 20, "origin_name": "短期借款"},
            {"type": "LongtermBorrowings", "value": 30, "origin_name": "長期借款"},
            {"type": "Liabilities", "value": 80, "origin_name": "負債總額"},
            {"type": "TotalAssets", "value": 200, "origin_name": "資產總額"},
        ]
        metrics, _ = parse_balance(rows)
        self.assertEqual(metrics["cash"], 100)
        self.assertEqual(metrics["debt"], 50)

    def test_free_cash_flow_normalizes_capex_sign(self) -> None:
        rows = [
            {"type": "CashFlowsFromOperatingActivities", "value": 100, "origin_name": "營業現金流"},
            {"type": "PropertyAndPlantAndEquipment", "value": -35, "origin_name": "取得不動產廠房設備"},
        ]
        self.assertEqual(parse_cashflow(rows)["fcf"], 65)

    def test_revenue_window_yoy_compares_matching_months(self) -> None:
        revenues = {
            (2025, 1): 100,
            (2025, 2): 100,
            (2025, 3): 100,
            (2026, 1): 110,
            (2026, 2): 120,
            (2026, 3): 130,
        }
        self.assertAlmostEqual(revenue_window_yoy(revenues, [(2026, 1), (2026, 2), (2026, 3)]), 0.2)

    def test_latest_complete_revenue_period_is_stock_specific(self) -> None:
        early_reporter = {
            **{(2025, month): 100 for month in (5, 6, 7)},
            **{(2026, month): 110 for month in (5, 6, 7)},
        }
        pending_reporter = {
            **{(2025, month): 100 for month in (4, 5, 6)},
            **{(2026, month): 110 for month in (4, 5, 6)},
        }
        self.assertEqual(latest_complete_revenue_period(early_reporter), (2026, 7))
        self.assertEqual(latest_complete_revenue_period(pending_reporter), (2026, 6))


class ConfigTests(unittest.TestCase):
    def test_project_config_is_valid(self) -> None:
        config = json.loads((ROOT / "config" / "screening.json").read_text(encoding="utf-8"))
        validate_config(config)

    def test_latest_complete_quarter_uses_filing_lag(self) -> None:
        self.assertEqual(latest_complete_quarter(date(2026, 7, 15)), date(2026, 3, 31))

    def test_recent_trading_dates_exclude_as_of_by_default(self) -> None:
        rows = [{"date": "2026-07-16"}, {"date": "2026-07-17"}]
        self.assertEqual(
            _select_recent_trading_dates(rows, as_of=date(2026, 7, 17), include_as_of=False),
            [date(2026, 7, 16)],
        )

    def test_recent_trading_dates_can_include_as_of_after_close(self) -> None:
        rows = [{"date": "2026-07-16"}, {"date": "2026-07-17"}]
        self.assertEqual(
            _select_recent_trading_dates(rows, as_of=date(2026, 7, 17), include_as_of=True),
            [date(2026, 7, 16), date(2026, 7, 17)],
        )

    def test_required_latest_snapshots_reject_missing_data(self) -> None:
        with self.assertRaisesRegex(ValueError, "2026-07-17 的 市值、PER 資料尚未更新"):
            _require_latest_snapshots(
                {"market_value": [], "per": []},
                latest_market_date=date(2026, 7, 17),
            )


if __name__ == "__main__":
    unittest.main()
