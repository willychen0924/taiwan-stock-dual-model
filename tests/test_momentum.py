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
    momentum_bucket,
)


class MomentumModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_momentum_config(ROOT / "config" / "momentum_screening.json")

    def test_config_weights_and_components_are_consistent(self) -> None:
        self.assertEqual(sum(self.config["weights"].values()), 100)

    def test_qualifying_company_gets_rank_and_short_summary(self) -> None:
        row = self._base_row()
        base = self._base_result(row)
        result = build_momentum_result(base, self.config)
        output = result["results"][0]
        self.assertTrue(output["hard_pass"])
        self.assertEqual(output["rank"], 1)
        self.assertGreater(output["operating_momentum_score"], output["quality_score"])
        self.assertGreaterEqual(len(output["model_summary"]), SUMMARY_MIN_CHARS)
        self.assertLessEqual(len(output["model_summary"]), SUMMARY_MAX_CHARS)
        self.assertNotIn("買進", output["model_summary"])
        self.assertEqual(output["value_defense_score"], 30)
        self.assertEqual(output["value_valuation_score"], 20)
        self.assertEqual(output["value_momentum_score"], 20)
        self.assertNotIn("momentum_score", output)
        self.assertNotIn("valuation_score", output)
        self.assertNotIn("defense_score", output)

    def test_missing_prior_income_is_data_history_not_turnaround(self) -> None:
        self.assertEqual(momentum_bucket(10, None), "前期資料不足")
        self.assertEqual(momentum_bucket(10, -1), "轉機觀察")
        self.assertEqual(momentum_bucket(10, 1), "一般成長")
        self.assertEqual(momentum_bucket(None, None), "一般成長")

    def test_warn_data_status_is_propagated(self) -> None:
        row = self._base_row()
        base = self._base_result(row, data_status="WARN")
        result = build_momentum_result(base, self.config)
        shared = next(item for item in result["checks"] if item["check"] == "共用資料模型狀態")
        self.assertEqual(shared["status"], "WARN")
        self.assertEqual(result["metadata"]["data_status"], "WARN")
        self.assertEqual(result["metadata"]["model_status"], "WARN")

    def test_missing_critical_revenue_data_fails_model_without_changing_score(self) -> None:
        row = self._base_row()
        row["revenue_acceleration"] = None
        base = self._base_result(row)
        result = build_momentum_result(base, self.config)
        output = result["results"][0]
        acceleration = next(item for item in result["checks"] if item["check"] == "營收加速度覆蓋率")
        self.assertEqual(acceleration["status"], "FAIL")
        self.assertEqual(result["metadata"]["model_status"], "FAIL")
        self.assertFalse(output["hard_pass"])

    def test_missing_prior_income_is_labeled_without_becoming_turnaround(self) -> None:
        row = self._base_row()
        row["prior_ttm_net_income"] = None
        base = self._base_result(row)
        result = build_momentum_result(base, self.config)
        output = result["results"][0]
        self.assertEqual(output["momentum_bucket"], "前期資料不足")
        self.assertEqual(output["funnel_stage"], "前期資料不足")
        self.assertIn("前期TTM淨利資料不足", output["exclusion_reasons"])
        self.assertIn("前期TTM淨利", output["missing_flags"])
        self.assertEqual(result["metadata"]["turnaround_count"], 0)
        self.assertEqual(result["metadata"]["insufficient_history_count"], 1)

    def _base_row(self) -> dict:
        row = {
            "stock_id": "1234",
            "stock_name": "範例公司",
            "industry": "半導體業",
            "market": "twse",
            "rank": 1,
            "hard_pass": True,
            "total_score": 70,
            "defense_score": 30,
            "valuation_score": 20,
            "momentum_score": 20,
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
        return row

    def _base_result(self, row: dict, *, data_status: str = "OK") -> dict:
        return {
            "metadata": {
                "as_of": "2026-07-17",
                "latest_market_date": "2026-07-16",
                "latest_financial_quarter": "2026-03-31",
                "latest_revenue_period": "2026-06",
                "universe_count": 1,
                "model_status": data_status,
                "data_status": data_status,
            },
            "config": {"universe": {"financial_industries": ["金融保險業"]}},
            "results": [row],
        }


if __name__ == "__main__":
    unittest.main()
