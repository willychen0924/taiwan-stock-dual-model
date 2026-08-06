from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.combined_report import (  # noqa: E402
    build_combined_html,
    write_combined_report,
)


def _result(model_id: str, *, status: str = "OK") -> dict:
    momentum = model_id == "operating_momentum"
    row = {
        "rank": 1,
        "stock_id": "2330",
        "stock_name": "台積電",
        "industry": "半導體業",
        "hard_pass": True,
        "total_score": 70.0,
        "defense_score": 40.0,
        "valuation_score": 20.0,
        "momentum_score": 10.0,
        "operating_momentum_score": 40.0,
        "quality_score": 20.0,
        "valuation_liquidity_score": 10.0,
    }
    return {
        "metadata": {
            "model_id": model_id,
            "model_status": status,
            "as_of": "2026-08-03",
            "latest_market_date": "2026-07-31",
            "latest_revenue_period": "2026-06",
            "revenue_signal_coverage": {
                "signal_key": "revenue_acceleration" if momentum else "revenue_3m_yoy",
                "signal_label": "營收加速度" if momentum else "3M月營收年增率",
                "ranked": 1.0,
                "universe": 0.95,
                "threshold": 0.8,
            },
        },
        "config": {"report": {"focus_size": 20}},
        "results": [row],
    }


def _result_with_ranked_rows(model_id: str, count: int = 20) -> dict:
    result = _result(model_id)
    source = result["results"][0]
    result["results"] = [
        {
            **source,
            "rank": rank,
            "stock_id": str(1000 + rank),
            "stock_name": f"公司{rank}",
            "model_summary": f"模型短評{rank}",
        }
        for rank in range(1, count + 1)
    ]
    return result


class CombinedReportTests(unittest.TestCase):
    def test_valid_models_show_intersection(self) -> None:
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        self.assertIn("雙模型交集", page)
        self.assertIn("共 1 檔", page)
        self.assertIn("2330", page)
        self.assertIn('id="status-value"', page)
        self.assertIn('id="status-momentum"', page)
        self.assertIn("量化排序不是買進建議", page)

    def test_header_shows_taipei_publication_time_to_minute(self) -> None:
        page = build_combined_html(
            _result("defensive_value"),
            _result("operating_momentum"),
            published_at=datetime.fromisoformat("2026-08-05T08:26:59+08:00"),
        )
        self.assertIn("資料發佈 2026-08-05 08:26", page)

    def test_tabs_and_row_expansion_work_without_javascript(self) -> None:
        """分頁與逐列展開必須是原生行為：禁用 script 的環境仍要能用。"""
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        self.assertNotIn("<script", page)
        self.assertIn('<label for="t-inter">總覽</label>', page)
        self.assertNotIn('<label for="t-inter">雙模型交集</label>', page)
        for key in ("t-momentum", "t-value", "t-inter"):
            self.assertIn(f'id="{key}" class="tabin"', page)
        # 預設停在營運動能
        self.assertIn('id="t-momentum" class="tabin" checked', page)
        for key in ("p-momentum", "p-value", "p-inter"):
            self.assertIn(f'#t-{key.split("-")[1]}:checked', page)
        self.assertIn('<details class="lrow lgrid-', page)

    def test_expanded_rows_have_separation_and_keyboard_focus(self) -> None:
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        self.assertIn("details.lrow[open]{border-bottom:6px solid var(--page)", page)
        self.assertIn(".lrow[open]>summary{background:var(--surface)}", page)
        self.assertIn(".dwrap{margin:0;padding:3px 16px 7px", page)
        self.assertIn(".lrow>summary:focus:not(:focus-visible){outline:none}", page)
        self.assertIn(".lrow>summary:focus-visible{outline:2px solid var(--link)", page)

    def test_mobile_typography_does_not_expand_inside_wide_tables(self) -> None:
        """iOS 不得自動放大展開短評；明細須依手機可視寬度換行。"""
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        self.assertIn("html{-webkit-text-size-adjust:100%;text-size-adjust:100%}", page)
        self.assertIn(
            ".dwrap{position:sticky;left:0;width:calc(100vw - 26px);"
            "max-width:calc(100vw - 26px)",
            page,
        )
        self.assertIn(
            ".drow{grid-template-columns:58px minmax(0,1fr);gap:10px;"
            "align-items:start",
            page,
        )
        self.assertIn(
            ".drow dd{font-size:12px;line-height:1.65;overflow-wrap:anywhere;"
            "word-break:break-word}",
            page,
        )
        self.assertIn(".statusbox .checks{overflow-x:auto;-webkit-overflow-scrolling:touch}", page)

    def test_rows_six_to_twenty_expand_to_model_summary_only(self) -> None:
        page = build_combined_html(
            _result_with_ranked_rows("defensive_value"),
            _result_with_ranked_rows("operating_momentum"),
        )
        self.assertEqual(page.count('class="panel model-panel"'), 2)
        for panel_id, next_anchor in (("p-momentum", "p-value"), ("p-value", "p-inter")):
            panel = page[page.index(f'id="{panel_id}"'):page.index(f'id="{next_anchor}"')]
            self.assertEqual(panel.count('<details class="lrow lgrid-model">'), 20)
            self.assertEqual(panel.count("<dt>模型短評</dt>"), 20)
            self.assertEqual(panel.count("<dt>技術面</dt>"), 5)
            self.assertEqual(panel.count("<dt>籌碼面</dt>"), 5)
            self.assertIn('<div class="groupsep lgrid-model">第 6–20 名</div>', panel)

    def test_model_panels_align_intro_height_and_group_separator_width(self) -> None:
        page = build_combined_html(
            _result_with_ranked_rows("defensive_value"),
            _result_with_ranked_rows("operating_momentum"),
        )
        self.assertIn(".model-panel>.note,.model-panel>.legend{white-space:nowrap;overflow-x:auto", page)
        self.assertIn(".model-panel>.legend{flex-wrap:nowrap}", page)
        self.assertIn(".groupsep{padding:7px 16px 7px 29px", page)
        self.assertIn("min-width:var(--minw,1200px);width:100%;box-sizing:border-box", page)

    def test_signal_columns_are_omitted_from_table_headers(self) -> None:
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        self.assertNotIn('<span class="">技術</span>', page)
        self.assertNotIn('<span class="">籌碼</span>', page)
        self.assertIn("技術面與籌碼面僅為前 5 名的外部展開明細", page)

    def test_radio_inputs_precede_every_element_they_control(self) -> None:
        """純 CSS 分頁靠 ~ 兄弟選擇器；radio 若被包進卡片，面板會全部隱藏。"""
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        last_radio = page.rindex('class="tabin"')
        for anchor in ('<header class="head">', 'id="p-momentum"', 'id="p-value"',
                       'id="p-inter"', 'class="audit"'):
            self.assertLess(last_radio, page.index(anchor), anchor)
        self.assertLess(page.index('<header class="head">'), page.index("</header>"))
        self.assertLess(page.index("</header>"), page.index('id="p-momentum"'))

    def test_intersection_omits_score_bars(self) -> None:
        """兩個模型的三段色代表不同區塊，並排會被誤讀成可比。"""
        page = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        panel = page[page.index('id="p-inter"'):page.index('class="audit"')]
        self.assertNotIn('class="bar"', panel)
        self.assertIn("總分尺度不同，不可直接互相比較", panel)

    def test_invalid_model_suppresses_intersection(self) -> None:
        page = build_combined_html(
            _result("defensive_value"),
            _result("operating_momentum", status="WARN"),
        )
        self.assertIn("本次不產生雙模型交集", page)
        self.assertIn("資料不可比", page)

    def test_header_shows_the_revenue_basis_not_just_the_newest_month(self) -> None:
        """只印最新月份會讓人以為全市場都換月了；實際上多數公司還在前一個月。"""
        value = _result("defensive_value")
        value["metadata"]["revenue_period_distribution"] = {"2026-07": 149, "2026-06": 1704}
        page = build_combined_html(value, _result("operating_momentum"))
        self.assertIn("營收基準 2026-06（1,704 家）", page)
        self.assertIn("149 家已採 2026-07", page)
        self.assertNotIn("營收期 2026-07", page)

    def test_header_omits_the_ahead_clause_when_the_basis_is_uniform(self) -> None:
        value = _result("defensive_value")
        value["metadata"]["revenue_period_distribution"] = {"2026-06": 1853}
        page = build_combined_html(value, _result("operating_momentum"))
        self.assertIn("營收基準 2026-06（1,853 家）", page)
        self.assertNotIn("家已採", page)

    def test_portal_is_written_only_as_index_html(self) -> None:
        """入口頁只有一個路徑：同內容再存一份 combined_report.html 沒有人連。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = write_combined_report(
                _result("defensive_value"), _result("operating_momentum"), root
            )
            self.assertEqual(set(paths), {"index_html", "latest_index_html"})
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*.html")),
                ["2026-08-03/index.html", "latest/index.html"],
            )

    def test_weekly_navigation_is_enabled_only_when_available(self) -> None:
        disabled = build_combined_html(_result("defensive_value"), _result("operating_momentum"))
        enabled = build_combined_html(
            _result("defensive_value"),
            _result("operating_momentum"),
            weekly_available=True,
        )
        self.assertNotIn('href="../weekly/latest/index.html"', disabled)
        self.assertIn('href="../weekly/latest/index.html"', enabled)


if __name__ == "__main__":
    unittest.main()
