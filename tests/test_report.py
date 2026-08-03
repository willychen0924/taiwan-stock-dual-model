from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.report import (  # noqa: E402
    SUMMARY_MAX_CHARS,
    SUMMARY_MIN_CHARS,
    build_model_summary,
)


class ModelSummaryTests(unittest.TestCase):
    def test_passing_summary_is_short_and_auditable(self) -> None:
        row = {
            "stock_name": "南帝",
            "hard_pass": True,
            "current_ratio": 7.712,
            "positive_fcf_years": 5,
            "profitable_years": 5,
            "revenue_3m_yoy": 0.3138,
            "ttm_net_income_growth": -0.1928,
            "per": 32.82,
            "avg_daily_turnover": 34_913_472,
            "total_score": 79.0185,
            "governance_status": "待複核",
        }
        summary = build_model_summary(row)
        self.assertGreaterEqual(len(summary), SUMMARY_MIN_CHARS)
        self.assertLessEqual(len(summary), SUMMARY_MAX_CHARS)
        self.assertIn("通過硬門檻", summary)
        self.assertIn("TTM淨利年減19%", summary)
        self.assertIn("公開資訊查證", summary)

    def test_failed_summary_states_reason_without_recommendation(self) -> None:
        row = {
            "stock_name": "範例公司",
            "hard_pass": False,
            "exclusion_reasons": "20日均成交金額不足；TTM淨利非正或缺漏",
            "avg_daily_turnover": 5_000_000,
            "total_score": 42.5,
            "governance_status": "待複核",
        }
        summary = build_model_summary(row)
        self.assertGreaterEqual(len(summary), SUMMARY_MIN_CHARS)
        self.assertLessEqual(len(summary), SUMMARY_MAX_CHARS)
        self.assertIn("未通過硬門檻", summary)
        self.assertIn("成交金額不足", summary)
        self.assertNotIn("買進", summary)


if __name__ == "__main__":
    unittest.main()
