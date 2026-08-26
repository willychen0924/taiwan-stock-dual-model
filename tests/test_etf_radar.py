from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar import (  # noqa: E402
    backfill_capital_history,
    build_radar_result,
    load_snapshot_days,
    merge_snapshot_day,
    normalize_snapshot_day,
    save_snapshot_day,
)
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

    def test_history_short_low_holdings_are_included_in_etf_and_issuer_counts(self) -> None:
        days = _days({"00991A": [0.001] * 7})
        for day in days[:-1]:
            for code in ("00981A", "00403A"):
                day["snapshots"][code]["status"] = "missing"
                day["snapshots"][code]["positions"] = []
        for code in ("00981A", "00403A"):
            days[-1]["snapshots"][code]["positions"] = [
                {
                    "stock_id": "4958",
                    "stock_name": "臻鼎-KY",
                    "shares": 1000,
                    "weight": 0.001,
                }
            ]
        result = build_radar_result(
            days,
            CONFIG,
            weights=WEIGHTS,
            weight_version="test",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        row = result["rows"][0]
        self.assertEqual(row["contributors"], ["00991A"])
        self.assertEqual(row["signal_etf_count"], 1)
        self.assertEqual(row["signal_issuer_count"], 1)
        self.assertEqual(row["etf_count"], 3)
        self.assertEqual(row["issuer_count"], 2)


class ETFRadarBackfillTests(unittest.TestCase):
    @staticmethod
    def _capital_snapshot(code: str, data_date: date) -> dict:
        source = next(item for item in ETF_SOURCES if item.code == code)
        return {
            "etf_code": source.code,
            "etf_name": source.name,
            "issuer": source.issuer,
            "adapter": source.adapter,
            "source_id": source.source_id,
            "source_url": source.url,
            "data_date": data_date.isoformat(),
            "aum": 10_000_000_000,
            "positions": [],
            "position_count": 0,
            "source_html_sha256": "fixture",
            "status": "healthy",
            "error": "",
        }

    def test_capital_backfill_skips_weekend_and_reaches_target(self) -> None:
        through = date(2026, 8, 25)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            latest = normalize_snapshot_day(
                [self._capital_snapshot(code, through) for code in ("00982A", "00992A")],
                requested_as_of=through,
            )
            save_snapshot_day(root, latest)
            requested: list[date] = []

            def fake_fetcher(
                *, requested_date: date, sources: tuple | None = None
            ) -> list[dict]:
                requested.append(requested_date)
                return [
                    self._capital_snapshot(code, requested_date)
                    for code in [source.code for source in sources or ()]
                ]

            counts = backfill_capital_history(
                root,
                through_date=through,
                target_trading_days=3,
                fetcher=fake_fetcher,
            )
            self.assertEqual(counts, {"00982A": 3, "00992A": 3})
            self.assertEqual(requested, [date(2026, 8, 24), date(2026, 8, 21)])
            self.assertEqual(
                [day["data_date"] for day in load_snapshot_days(root)],
                ["2026-08-21", "2026-08-24", "2026-08-25"],
            )

    def test_official_snapshot_replaces_third_party_for_the_same_date(self) -> None:
        data_date = date(2026, 8, 25)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            third_party = self._capital_snapshot("00982A", data_date)
            third_party["provenance"] = "third_party"
            third_party["aum"] = 9_000_000_000
            save_snapshot_day(
                root,
                normalize_snapshot_day([third_party], requested_as_of=data_date),
            )
            official = self._capital_snapshot("00982A", data_date)
            official["provenance"] = "official"
            merge_snapshot_day(
                root,
                normalize_snapshot_day([official], requested_as_of=data_date),
            )
            snapshot = load_snapshot_days(root)[0]["snapshots"]["00982A"]
            self.assertEqual(snapshot["provenance"], "official")
            self.assertEqual(snapshot["aum"], 10_000_000_000)
            raw = root / "data" / "raw" / "etf_pcf" / "00982A"
            self.assertTrue((raw / "2026-08-25.third_party.json").exists())
            self.assertTrue((raw / "2026-08-25.json").exists())


if __name__ == "__main__":
    unittest.main()
