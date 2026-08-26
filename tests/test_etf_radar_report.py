from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar import build_radar_result  # noqa: E402
from value_screener.etf_radar_report import build_etf_radar_html  # noqa: E402
from tests.test_etf_radar import CONFIG, WEIGHTS, _days  # noqa: E402


class ETFRadarReportTests(unittest.TestCase):
    def _page(self) -> str:
        result = build_radar_result(
            _days({"00981A": [0.001] * 6 + [0.0013]}, missing_last={"00992A"}),
            CONFIG,
            weights=WEIGHTS,
            weight_version="2026-08",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
            cross_reference={"4958": {"stock_name": "臻鼎-KY", "close": 108.5}},
        )
        return build_etf_radar_html(
            result,
            published_at=datetime.fromisoformat("2026-08-26T08:25:00+08:00"),
        )

    def _cold_page(self) -> str:
        result = build_radar_result(
            _days({"00981A": [0.001] * 7})[:1],
            CONFIG,
            weights=WEIGHTS,
            weight_version="2026-08",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        return build_etf_radar_html(
            result,
            published_at=datetime.fromisoformat("2026-08-26T08:25:00+08:00"),
        )

    def _many_candidates_page(self) -> str:
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
        result = build_radar_result(
            days,
            CONFIG,
            weights=WEIGHTS,
            weight_version="2026-08",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        return build_etf_radar_html(result)

    def test_report_keeps_existing_style_and_has_no_javascript(self) -> None:
        page = self._page()
        self.assertIn("--page:#faf6ef", page)
        self.assertIn('<h1>ETF 雷達</h1>', page)
        self.assertNotIn("<script", page)

    def test_navigation_places_etf_radar_left_of_daily(self) -> None:
        page = self._page()
        self.assertLess(page.index(">ETF雷達</"), page.index(">日報</"))
        self.assertIn('aria-current="page">ETF雷達</a>', page)

    def test_main_cells_show_lots_without_the_unit_or_percent(self) -> None:
        page = self._page()
        self.assertIn('<i class="mark">▲</i>1', page)
        self.assertNotIn('<i class="mark">▲</i>1張', page)
        header = page[page.index('class="lhead lgrid-etf"'):page.index('</div>', page.index('class="lhead lgrid-etf"'))]
        self.assertNotIn("32.0%", header)

    def test_cold_start_waiting_candidate_is_visible_with_low_marker(self) -> None:
        page = self._cold_page()
        self.assertIn('class="sigchip wait">待觀察</span>', page)
        self.assertIn('<i class="mark">●</i>1', page)
        self.assertNotIn('<i class="mark">▲</i>1', page)
        self.assertIn("尚無法完成連續減碼尾倉檢查", page)

    def test_page_shows_ten_and_keeps_only_fifteen_candidates(self) -> None:
        page = self._many_candidates_page()
        primary, extra = page.split('<details class="watchlist">', 1)
        self.assertEqual(primary.count('class="lrow '), 10)
        self.assertEqual(extra.count('class="lrow '), 5)
        self.assertIn("單日符合 16 檔，候選只取排名前 15 檔", page)

    def test_missing_uses_word_not_question_mark(self) -> None:
        page = self._page()
        self.assertIn('class="etfc miss" title="資料不足">缺</span>', page)
        self.assertNotIn(">?</span>", page)

    def test_radar_is_explicitly_separate_from_score_and_hard_gates(self) -> None:
        page = self._page()
        self.assertIn("不使用、也不影響雙模型的 100 分評分與硬門檻", page)
        self.assertNotIn("雷達總分", page)


if __name__ == "__main__":
    unittest.main()
