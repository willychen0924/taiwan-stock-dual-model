from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.momentum import (  # noqa: E402
    SUMMARY_MAX_CHARS,
    SUMMARY_MIN_CHARS,
    build_momentum_result,
    load_momentum_config,
)


class MomentumModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_momentum_config(ROOT / "config" / "momentum_screening.json")

    def test_config_weights_and_components_are_consistent(self) -> None:
        self.assertEqual(sum(self.config["weights"].values()), 100)

    def test_qualifying_company_gets_rank_and_short_summary(self) -> None:
        row = {
            "stock_id": "1234",
            "stock_name": "範例公司",
            "industry": "半導體業",
            "market": "twse",
            "rank": 1,
            "hard_pass": True,
            "total_score": 70,
            "close": 50,
            "market_value": 10_000_000_000,
            "avg_daily_turnover": 80_000_000,
            "per": 18,
            "pbr": 2,
            "revenue_3m_yoy": 0.25,
            "latest_revenue_yoy": 0.3,
            "revenue_acceleration": 0.08,
            "ttm_net_income": 1_000_000_000,
            "prior_ttm_net_income": 700_000_000,
            "ttm_net_income_growth": 0.4286,
            "ttm_operating_margin": 0.18,
            "ttm_operating_margin_change": 0.03,
            "profitable_years": 5,
            "complete_profit_years": 5,
            "positive_fcf_years": 4,
            "cash_conversion": 1.1,
            "liabilities_ratio": 0.35,
            "net_cash_ratio": 0.1,
            "sector_per_percentile": 0.4,
            "sector_pbr_percentile": 0.5,
            "sector_margin_percentile": 0.8,
            "governance_status": "待複核",
            "manual_exclude": False,
            "catalyst": "",
        }
        base = {
            "metadata": {
                "as_of": "2026-07-17",
                "latest_market_date": "2026-07-16",
                "latest_financial_quarter": "2026-03-31",
                "latest_revenue_period": "2026-06",
                "universe_count": 1,
                "model_status": "OK",
            },
            "config": {"universe": {"financial_industries": ["金融保險業"]}},
            "results": [row],
        }
        result = build_momentum_result(base, self.config)
        output = result["results"][0]
        self.assertTrue(output["hard_pass"])
        self.assertEqual(output["rank"], 1)
        self.assertGreater(output["operating_momentum_score"], output["quality_score"])
        self.assertGreaterEqual(len(output["model_summary"]), SUMMARY_MIN_CHARS)
        self.assertLessEqual(len(output["model_summary"]), SUMMARY_MAX_CHARS)
        self.assertNotIn("買進", output["model_summary"])


if __name__ == "__main__":
    unittest.main()
