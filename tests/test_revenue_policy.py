from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.revenue_policy import (  # noqa: E402
    has_revenue_signal,
    select_latest_covered_period,
    shift_period,
)


class RevenuePolicyTests(unittest.TestCase):
    def test_shift_period_crosses_year_boundary(self) -> None:
        self.assertEqual(shift_period((2026, 1), -2), (2025, 11))

    def test_acceleration_requires_six_current_and_prior_year_months(self) -> None:
        revenues = {}
        for offset in range(-5, 1):
            period = shift_period((2026, 6), offset)
            revenues[period] = 1.0
            revenues[(period[0] - 1, period[1])] = 1.0
        self.assertTrue(has_revenue_signal(revenues, (2026, 6), signal="revenue_acceleration"))
        del revenues[(2025, 1)]
        self.assertFalse(has_revenue_signal(revenues, (2026, 6), signal="revenue_acceleration"))

    def test_selects_latest_period_meeting_coverage(self) -> None:
        complete = {}
        for stock_id in ("1111", "2222"):
            complete[stock_id] = {}
            for offset in range(-5, 1):
                period = shift_period((2026, 6), offset)
                complete[stock_id][period] = 1.0
                complete[stock_id][(period[0] - 1, period[1])] = 1.0
        complete["1111"][(2026, 7)] = 1.0
        complete["1111"][(2025, 7)] = 1.0
        selected, coverage = select_latest_covered_period(
            complete,
            ["1111", "2222"],
            [(2026, 6), (2026, 7)],
            signal="revenue_3m_yoy",
            threshold=0.8,
        )
        self.assertEqual(selected, (2026, 6))
        self.assertEqual(coverage, 1.0)


if __name__ == "__main__":
    unittest.main()
