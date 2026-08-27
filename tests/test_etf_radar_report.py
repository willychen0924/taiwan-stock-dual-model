from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar import build_radar_result  # noqa: E402
from value_screener.etf_radar_report import (  # noqa: E402
    _daily_watch_rows,
    build_etf_radar_html,
)
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
            cross_reference={
                "4958": {
                    "stock_name": "臻鼎-KY",
                    "close": 108.5,
                    "value_rank": 70,
                    "momentum_rank": 40,
                    "revenue_period": "2026-07",
                    "latest_revenue_yoy": 0.565,
                    "revenue_3m_yoy": 0.486,
                }
            },
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

    def test_daily_watch_uses_consensus_cross_model_and_revenue_context(self) -> None:
        page = self._page()
        self.assertIn("<h2>每日觀察</h2>", page)
        self.assertIn("觀察理由", page)
        self.assertIn("等待訊號", page)
        self.assertIn("防禦價值第 70、營運動能第 40", page)
        self.assertIn("2026-07 單月營收年增 +56.5%、近三月年增 +48.6%", page)
        self.assertIn("不是進場訊號或買進建議", page)

    def test_daily_watch_prioritizes_consensus_then_best_cross_model(self) -> None:
        rows = [
            {
                "stock_id": "5347",
                "signal": "低部位觀察",
                "etf_count": 3,
                "issuer_count": 2,
                "value_rank": 169,
                "momentum_rank": 208,
            },
            {
                "stock_id": "2382",
                "signal": "低部位觀察",
                "etf_count": 2,
                "issuer_count": 2,
                "value_rank": None,
                "momentum_rank": None,
            },
            {
                "stock_id": "3044",
                "signal": "低部位觀察",
                "etf_count": 1,
                "issuer_count": 1,
                "value_rank": 70,
                "momentum_rank": 40,
            },
        ]
        selected = _daily_watch_rows(rows)
        self.assertEqual([row["stock_id"] for row in selected], ["5347", "3044", "2382"])

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

    def test_detail_table_shows_lots_before_stock_weight(self) -> None:
        page = self._page()
        self.assertIn(
            "<th>雷達權重（√AUM）</th><th>持有張數</th><th>個股權重</th>",
            page,
        )
        self.assertIn("<td>32.0%</td><td>1</td><td>0.13%</td>", page)

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

    def test_unheld_position_does_not_claim_history_is_missing(self) -> None:
        page = self._page()
        self.assertIn('<td class="neu">—</td><td>未持有</td>', page)
        self.assertNotIn('>資料不足</td><td>未持有</td>', page)

    def test_etf_issuer_count_includes_history_short_low_holdings(self) -> None:
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
            weight_version="2026-08",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        page = build_etf_radar_html(result)
        self.assertIn('<span class="split">3<s>/</s>2</span>', page)
        self.assertIn("歷史不足的少量持有", page)

    def test_radar_is_explicitly_separate_from_score_and_hard_gates(self) -> None:
        page = self._page()
        self.assertIn("不使用、也不影響雙模型的 100 分評分與硬門檻", page)
        self.assertNotIn("雷達總分", page)

    def test_exclusions_are_compact_categories_without_stock_rows(self) -> None:
        days = _days({})[:1]
        days[0]["snapshots"]["00981A"]["positions"] = [
            {
                "stock_id": "1111",
                "stock_name": "配股測試",
                "shares": 1500,
                "weight": 0.001,
            },
            {
                "stock_id": "2222",
                "stock_name": "重倉測試",
                "shares": 1000,
                "weight": 0.02,
            },
        ]
        result = build_radar_result(
            days,
            CONFIG,
            weights=WEIGHTS,
            weight_version="2026-08",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        page = build_etf_radar_html(result)
        self.assertIn("排除分類", page)
        self.assertIn("配股殘留", page)
        self.assertIn("非低部位", page)
        self.assertNotIn('class="exrow"', page)
        self.assertNotIn("配股測試", page)
        self.assertNotIn("重倉測試", page)

    def test_header_shows_history_per_etf_when_only_capital_is_backfilled(self) -> None:
        result = build_radar_result(
            _days({}),
            CONFIG,
            weights=WEIGHTS,
            weight_version="2026-08",
            aum_medians={code: 1.0 for code in WEIGHTS},
            provisional_weights=True,
        )
        result["metadata"]["history_days_by_etf"] = {
            "00981A": 1,
            "00403A": 1,
            "00991A": 1,
            "00982A": 20,
            "00992A": 20,
        }
        page = build_etf_radar_html(result)
        self.assertIn("981A/403A/991A 1 日", page)
        self.assertIn("982A/992A 20 日", page)


if __name__ == "__main__":
    unittest.main()
