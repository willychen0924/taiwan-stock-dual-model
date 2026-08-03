from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.report import (  # noqa: E402
    SUMMARY_MAX_CHARS,
    SUMMARY_MIN_CHARS,
    _build_html,
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

    def test_html_has_score_bars_collapsed_watchlist_and_sorting(self) -> None:
        results = []
        for rank in range(1, 22):
            results.append(
                {
                    "rank": rank,
                    "stock_id": f"{rank:04d}",
                    "stock_name": f"公司{rank}",
                    "industry": "測試業",
                    "hard_pass": True,
                    "total_score": 70.0,
                    "defense_score": 40.0,
                    "valuation_score": 20.0,
                    "momentum_score": 10.0,
                    "per": 12.0,
                    "pbr": 1.2,
                    "avg_daily_turnover": 80_000_000,
                    "net_cash_ratio": 0.2,
                    "liquidation_coverage": 0.3,
                    "revenue_3m_yoy": 0.1,
                    "model_summary": "僅供研究篩選，仍須公開資訊查證。",
                    "governance_status": "待複核",
                }
            )
        payload = {
            "metadata": {
                "model_status": "OK",
                "as_of": "2026-08-03",
                "latest_market_date": "2026-07-31",
                "latest_financial_quarter": "2026-03-31",
                "latest_revenue_period": "2026-06",
                "universe_count": 21,
                "operating_company_count": 21,
                "hard_pass_count": 21,
                "watchlist_count": 21,
                "focus_count": 20,
                "revenue_signal_coverage": {
                    "signal_key": "revenue_3m_yoy",
                    "signal_label": "3M月營收年增率",
                    "ranked": 1.0,
                    "universe": 1.0,
                    "threshold": 0.8,
                },
            },
            "config": {"report": {"focus_size": 20, "watchlist_size": 100}},
            "checks": [],
            "results": results,
        }
        page = _build_html(
            payload,
            enrichment={"0001": {"technical": "中性", "chip": "待觀察"}},
        )
        self.assertIn("scorebar", page)
        self.assertIn("展開自選100第 21–100 名（1 檔）", page)
        self.assertIn("data-sort", page)
        self.assertIn("中性", page)
        self.assertIn("台股防禦型價值監控台", page)
        self.assertIn("本益比", page)
        self.assertIn("本淨比", page)
        self.assertIn("技術面、籌碼面與模型短評", page)
        self.assertNotIn("<th data-type=\"text\">治理</th>", page)
        self.assertNotIn("cdn", page.lower())


if __name__ == "__main__":
    unittest.main()
