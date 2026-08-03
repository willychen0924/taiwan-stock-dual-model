from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.combined_report import build_combined_html  # noqa: E402


def _result(model_id: str, *, status: str = "OK") -> dict:
    momentum = model_id == "operating_momentum"
    row = {
        "rank": 1,
        "stock_id": "2330",
        "stock_name": "台積電",
        "industry": "半導體業",
        "hard_pass": True,
        "total_score": 70.0,
        "defense_score": 40.0,
        "valuation_score": 20.0,
        "momentum_score": 10.0,
        "operating_momentum_score": 40.0,
        "quality_score": 20.0,
        "valuation_liquidity_score": 10.0,
    }
    return {
        "metadata": {
            "model_id": model_id,
            "model_status": status,
            "as_of": "2026-08-03",
            "latest_market_date": "2026-07-31",
            "latest_revenue_period": "2026-06",
            "revenue_signal_coverage": {
                "signal_key": "revenue_acceleration" if momentum else "revenue_3m_yoy",
                "signal_label": "營收加速度" if momentum else "3M月營收年增率",
                "ranked": 1.0,
                "universe": 0.95,
                "threshold": 0.8,
            },
        },
        "config": {"report": {"focus_size": 20}},
        "results": [row],
    }


class CombinedReportTests(unittest.TestCase):
    def test_valid_models_show_intersection(self) -> None:
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        self.assertIn("雙模型交集", page)
        self.assertIn("共 1 檔", page)
        self.assertIn("2330", page)
        self.assertIn("sortable-table", page)
        self.assertIn('role="tablist"', page)
        self.assertIn('id="status-value"', page)
        self.assertIn('id="status-momentum"', page)
        self.assertIn("量化排序不是買進建議", page)

    def test_invalid_model_suppresses_intersection(self) -> None:
        page = build_combined_html(
            _result("defensive_value"),
            _result("operating_momentum", status="WARN"),
        )
        self.assertIn("本次不產生雙模型交集", page)
        self.assertIn("資料不可比", page)

    def test_weekly_navigation_is_enabled_only_when_available(self) -> None:
        disabled = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        enabled = build_combined_html(
            _result("defensive_value"),
            _result("operating_momentum"),
            weekly_available=True,
        )
        self.assertNotIn('href="../weekly/latest/index.html"', disabled)
        self.assertIn('href="../weekly/latest/index.html"', enabled)


if __name__ == "__main__":
    unittest.main()
