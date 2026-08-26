from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar import build_radar_result  # noqa: E402
from value_screener.etf_radar_sources import ETF_SOURCES  # noqa: E402


CONFIG = {
    "version": "test",
    "low_position_max_weight": 0.0015,
    "require_round_lot": True,
    "exclude_decline_days": {"window": 4, "min_declines": 3},
    "exclude_drop_5d": 0.30,
    "boost_min_increase": 0.20,
    "confirm_consecutive_days": 2,
    "resonance_window_days": 3,
    "resonance_min_issuers": 2,
    "warmup_trading_days": 6,
    "low_observation_limit": 10,
    "observation_candidate_limit": 15,
}
WEIGHTS = {"00981A": 0.32, "00403A": 0.247, "00991A": 0.175, "00982A": 0.134, "00992A": 0.124}


def _days(series: dict[str, list[float]], *, missing_last: set[str] | None = None) -> list[dict]:
    missing_last = missing_last or set()
    start = date(2026, 8, 17)
    output = []
    for index in range(7):
        snapshots = {}
        for source in ETF_SOURCES:
            missing = index == 6 and source.code in missing_last
            weight = series.get(source.code, [0.0] * 7)[index]
            snapshots[source.code] = {
                "status": "missing" if missing else "healthy",
                "error": "fixture missing" if missing else "",
                "aum": 10_000_000_000 * WEIGHTS[source.code],
                "positions": []
                if missing or weight == 0
                else [{"stock_id": "4958", "stock_name": "臻鼎-KY", "shares": 1000, "weight": weight}],
            }
        output.append(
            {
                "data_date": (start + timedelta(days=index)).isoformat(),
                "requested_as_of": (start + timedelta(days=index + 1)).isoformat(),
                "coverage": {"healthy": 5 - len(missing_last) if index == 6 else 5, "total": 5},
                "snapshots": snapshots,
            }
        )
    return output


def _build(series: dict[str, list[float]], *, missing_last: set[str] | None = None) -> dict:
    days = _days(series, missing_last=missing_last)
    return build_radar_result(
        days,
        CONFIG,
        weights=WEIGHTS,
        weight_version="test",
        aum_medians={code: 1.0 for code in WEIGHTS},
        provisional_weights=True,
        cross_reference={"4958": {"stock_name": "臻鼎-KY", "close": 108.5}},
    )


class ETFRadarSignalTests(unittest.TestCase):
    def test_waiting_candidates_are_ranked_by_etf_count_and_capped_at_fifteen(self) -> None:
        days = _days({})[:1]
        for index in range(16):
            days[0]["snapshots"]["00981A"]["positions"].append(
                {
                    "stock_id": f"{1000 + index}",
                    "stock_name": f"候選{index}",
                    "shares": 1000,
                    "weight": 0.001,
                }
            )
        for code in ("00982A", "00992A"):
            days[0]["snapshots"][code]["positions"].append(
                {
                    "stock_id": "9000",
                    "stock_name": "雙ETF候選",
                    "shares": 1000,
                    "weight": 0.001,
                }
            )
        result = build_radar_result(
            days,
            CONFIG,
            weights=WEIGHTS,
            weight_version="test",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        self.assertEqual(len(result["rows"]), 15)
        self.assertEqual(result["rows"][0]["stock_id"], "9000")
        self.assertEqual(result["rows"][0]["etf_count"], 2)
        self.assertEqual(result["metadata"]["observation_pool_count"], 17)
        self.assertEqual(result["metadata"]["observation_omitted_count"], 2)

    def test_cold_start_shows_low_position_as_waiting_without_event(self) -> None:
        days = _days({"00981A": [0.001] * 7})[:1]
        result = build_radar_result(
            days,
            CONFIG,
            weights=WEIGHTS,
            weight_version="test",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        row = result["rows"][0]
        self.assertEqual(row["signal"], "待觀察")
        self.assertEqual(row["contributors"], ["00981A"])
        self.assertEqual(row["cells"]["00981A"]["kind"], "low")
        self.assertEqual(row["last_turn"], "")

    def test_zero_rounded_weight_with_shares_is_not_treated_as_unheld(self) -> None:
        days = _days({"00981A": [0.001] * 7})[:1]
        position = days[0]["snapshots"]["00981A"]["positions"][0]
        position["weight"] = 0.0
        result = build_radar_result(
            days,
            CONFIG,
            weights=WEIGHTS,
            weight_version="test",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        row = result["rows"][0]
        self.assertEqual(row["signal"], "待觀察")
        detail = next(item for item in row["details"] if item["etf_code"] == "00981A")
        self.assertTrue(detail["below_precision"])

    def test_first_signal_can_only_appear_on_day_seven(self) -> None:
        result = _build({"00981A": [0.001] * 6 + [0.0013]})
        row = result["rows"][0]
        self.assertEqual(row["signal"], "開始加碼")
        self.assertEqual(row["contributors"], ["00981A"])

    def test_share_flow_with_unchanged_weight_is_not_an_add_signal(self) -> None:
        result = _build({"00981A": [0.001] * 7})
        self.assertEqual(result["rows"][0]["signal"], "低部位觀察")

    def test_continuous_selling_tail_is_excluded(self) -> None:
        result = _build({"00981A": [0.0015, 0.0014, 0.0013, 0.0012, 0.0011, 0.0010, 0.0009]})
        self.assertEqual(result["rows"], [])
        excluded = next(item for item in result["excluded"] if item["stock_id"] == "4958")
        self.assertIn("減碼尾倉", excluded["reasons"])

    def test_two_etfs_from_unified_are_only_one_issuer(self) -> None:
        result = _build(
            {
                "00981A": [0.001] * 6 + [0.0013],
                "00403A": [0.001] * 6 + [0.0013],
            }
        )
        row = result["rows"][0]
        self.assertEqual(row["signal"], "開始加碼")
        self.assertEqual(row["etf_count"], 2)
        self.assertEqual(row["issuer_count"], 1)

    def test_cross_issuer_events_form_resonance(self) -> None:
        result = _build(
            {
                "00981A": [0.001] * 6 + [0.0013],
                "00991A": [0.001] * 6 + [0.0013],
            }
        )
        row = result["rows"][0]
        self.assertEqual(row["signal"], "跨投信共振")
        self.assertEqual(row["issuer_count"], 2)

    def test_missing_etf_is_shown_as_missing_and_not_counted(self) -> None:
        result = _build({"00981A": [0.001] * 7, "00992A": [0.001] * 7}, missing_last={"00992A"})
        row = result["rows"][0]
        self.assertEqual(row["cells"]["00992A"]["text"], "缺")
        self.assertNotIn("00992A", row["contributors"])


if __name__ == "__main__":
    unittest.main()
