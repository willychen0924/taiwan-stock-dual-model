from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.history import append_history_records, build_history_record  # noqa: E402


HISTORY_KWARGS = {
    "min_revenue_coverage": 0.8,
    "financial_industries": {"金融業"},
}


def payload(*, as_of: str, status: str = "OK", complete_revenue: bool = True, ranked: bool = True) -> dict:
    row = {
        "stock_id": "1234",
        "stock_name": "測試公司",
        "industry": "半導體業",
        "close": 100,
        "hard_pass": ranked,
        "rank": 1 if ranked else None,
        "total_score": 70,
        "funnel_stage": "精華20" if ranked else "基礎觀察",
        "revenue_3m_yoy": 0.1 if complete_revenue else None,
    }
    return {
        "metadata": {
            "as_of": as_of,
            "latest_market_date": "2026-07-31",
            "latest_revenue_period": "2026-06" if complete_revenue else "2026-07",
            "latest_financial_quarter": "2026-03-31",
            "model_status": status,
            "hard_pass_count": 1 if ranked else 0,
            "model_id": "test_model",
            "model_name": "測試模型",
        },
        "config": {"version": "test"},
        "checks": [],
        "results": [row],
    }


class RankingHistoryTests(unittest.TestCase):
    def write_report(self, root: Path, name: str, value: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def test_history_record_keeps_zero_rank_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = self.write_report(root, "report.json", payload(as_of="2026-08-01", status="WARN", ranked=False))
            record = build_history_record(json.loads(path.read_text()), path, root=root, **HISTORY_KWARGS)
            self.assertEqual(record["rankings"], [])
            self.assertFalse(record["eligible_for_backtest"])
            self.assertIn("來源模型狀態為 WARN", record["ineligible_reasons"])

    def test_incomplete_revenue_is_not_eligible_even_when_status_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = self.write_report(root, "report.json", payload(as_of="2026-08-01", complete_revenue=False))
            record = build_history_record(json.loads(path.read_text()), path, root=root, **HISTORY_KWARGS)
            self.assertFalse(record["eligible_for_backtest"])
            self.assertEqual(record["ranked_revenue_coverage"], 0)
            self.assertEqual(record["source_model_status"], "OK")
            self.assertEqual(record["effective_model_status"], "WARN")

    def test_repeated_append_is_idempotent_and_does_not_truncate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self.write_report(root, "first.json", payload(as_of="2026-08-01"))
            second = self.write_report(root, "second.json", payload(as_of="2026-08-03"))
            history = root / "rankings_history.jsonl"

            self.assertEqual(len(append_history_records(history, [first], root=root, **HISTORY_KWARGS)), 1)
            self.assertEqual(len(append_history_records(history, [first], root=root, **HISTORY_KWARGS)), 0)
            self.assertEqual(
                len(append_history_records(history, [first, second], root=root, **HISTORY_KWARGS)),
                1,
            )

            records = [json.loads(line) for line in history.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertEqual({record["as_of"] for record in records}, {"2026-08-01", "2026-08-03"})
            self.assertEqual({record["latest_market_date"] for record in records}, {"2026-07-31"})

    def test_volatile_timestamp_does_not_create_duplicate_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = payload(as_of="2026-08-03")
            report["metadata"]["generated_at"] = "2026-08-03T08:00:00+08:00"
            path = self.write_report(root, "report.json", report)
            history = root / "rankings_history.jsonl"
            self.assertEqual(len(append_history_records(history, [path], root=root, **HISTORY_KWARGS)), 1)

            report["metadata"]["generated_at"] = "2026-08-03T09:00:00+08:00"
            self.write_report(root, "report.json", report)
            self.assertEqual(len(append_history_records(history, [path], root=root, **HISTORY_KWARGS)), 0)


if __name__ == "__main__":
    unittest.main()
