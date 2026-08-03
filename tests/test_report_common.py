from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.report_common import (  # noqa: E402
    build_checks_panel,
    build_freshness_banner,
    build_monitor_status,
    format_rank_change,
    load_rank_comparison,
)


def _result(*, market_date: str = "2026-07-31", status: str = "OK") -> dict:
    return {
        "metadata": {
            "model_id": "defensive_value",
            "model_status": status,
            "latest_market_date": market_date,
            "latest_revenue_period": "2026-07",
            "revenue_signal_coverage": {
                "signal_key": "revenue_3m_yoy",
                "signal_label": "3M月營收年增率",
                "ranked": 1.0,
                "universe": 0.95,
                "threshold": 0.8,
            },
        }
    }


class ReportCommonTests(unittest.TestCase):
    def test_comparison_uses_latest_earlier_eligible_market_observation(self) -> None:
        records = [
            {
                "model_id": "defensive_value",
                "as_of": "2026-07-30",
                "latest_market_date": "2026-07-29",
                "eligible_for_backtest": True,
                "rankings": [{"stock_id": "1111", "rank": 4}],
            },
            {
                "model_id": "defensive_value",
                "as_of": "2026-08-01",
                "latest_market_date": "2026-07-31",
                "eligible_for_backtest": False,
                "rankings": [{"stock_id": "1111", "rank": 1}],
            },
            {
                "model_id": "operating_momentum",
                "as_of": "2026-07-31",
                "latest_market_date": "2026-07-30",
                "eligible_for_backtest": True,
                "rankings": [{"stock_id": "1111", "rank": 9}],
            },
            {
                "model_id": "defensive_value",
                "as_of": "2026-07-31",
                "latest_market_date": "2026-07-30",
                "eligible_for_backtest": True,
                "rankings": [{"stock_id": "1111", "rank": 3}],
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
            comparison = load_rank_comparison(_result(), path)
        self.assertEqual(comparison["prior_market_date"], "2026-07-30")
        self.assertEqual(format_rank_change({"stock_id": "1111", "rank": 1}, comparison), "↑2")
        self.assertEqual(format_rank_change({"stock_id": "2222", "rank": 2}, comparison), "NEW")

    def test_invalid_current_observation_is_never_compared(self) -> None:
        result = _result(status="WARN")
        comparison = load_rank_comparison(result, None)
        self.assertFalse(comparison["comparable"])
        self.assertEqual(format_rank_change({"stock_id": "1111", "rank": 1}, comparison), "資料不可比")

    def test_comparison_uses_last_record_for_same_prior_market_date(self) -> None:
        records = [
            {
                "model_id": "defensive_value",
                "as_of": "2026-07-30",
                "latest_market_date": "2026-07-30",
                "eligible_for_backtest": True,
                "rankings": [{"stock_id": "1111", "rank": 8}],
            },
            {
                "model_id": "defensive_value",
                "as_of": "2026-07-31",
                "latest_market_date": "2026-07-30",
                "eligible_for_backtest": True,
                "rankings": [{"stock_id": "1111", "rank": 3}],
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
            comparison = load_rank_comparison(_result(), path)
        self.assertEqual(comparison["prior_as_of"], "2026-07-31")
        self.assertEqual(format_rank_change({"stock_id": "1111", "rank": 1}, comparison), "↑2")

    def test_panels_show_signal_freshness_and_all_check_states(self) -> None:
        metadata = _result()["metadata"]
        metadata["revenue_signal_coverage"]["universe"] = 0.002
        banner = build_freshness_banner(metadata)
        panel = build_checks_panel(
            [{"check": "一般公司營收覆蓋率", "actual": 0.002, "expected": 0.8, "status": "FAIL", "notes": "測試"}]
        )
        self.assertIn("動能分數本日不可用", banner)
        self.assertIn("0.2%", banner)
        self.assertIn("status fail", panel)
        self.assertIn("80.0%", panel)

    def test_monitor_status_is_collapsed_for_ok_and_open_for_abnormal(self) -> None:
        ok = build_monitor_status(
            _result()["metadata"],
            [{"check": "測試", "actual": 1, "expected": 1, "status": "OK", "notes": ""}],
            stats=[("硬門檻通過", 20)],
        )
        self.assertIn('class="statusbox ok"', ok)
        self.assertNotIn('class="statusbox ok" open', ok)
        warned_metadata = _result(status="WARN")["metadata"]
        warned = build_monitor_status(
            warned_metadata,
            [{"check": "測試", "actual": 0, "expected": 1, "status": "WARN", "notes": ""}],
            stats=[("硬門檻通過", 0)],
        )
        self.assertIn('class="statusbox warn" open', warned)
        self.assertIn("檢核 0/1 通過", warned)


if __name__ == "__main__":
    unittest.main()
