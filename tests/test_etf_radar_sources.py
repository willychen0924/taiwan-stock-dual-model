from __future__ import annotations

import html
import io
import json
import sys
import unittest
import zipfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar_sources import (  # noqa: E402
    ETF_SOURCES,
    parse_capital_api_json,
    parse_capital_html,
    parse_fuhwa_html,
    parse_fuhwa_xlsx,
    parse_goal_star_json,
    parse_unified_html,
)


FIXTURES = ROOT / "tests" / "fixtures" / "etf_radar"


def _fuhwa_workbook() -> bytes:
    rows = [
        ["日期: 2026/08/25"],
        ["基金資產淨值"],
        ["6,000,000,000"],
        ["證券代號", "證券名稱", "股數", "金額", "權重(%)"],
        ["2330", "台積電", "1,000,000", "600,000,000", "10.000%"],
        ["2383", "台光電", "500,000", "300,000,000", "5.000%"],
        ["4958", "臻鼎-KY", "1,000", "7,200,000", "0.120%"],
        ["2454", "聯發科", "200,000", "240,000,000", "4.000%"],
        ["2308", "台達電", "300,000", "180,000,000", "3.000%"],
    ]
    shared = [value for row in rows for value in row]
    offsets: list[int] = []
    cursor = 0
    for row in rows:
        offsets.append(cursor)
        cursor += len(row)
    shared_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{html.escape(value)}</t></si>" for value in shared)
        + "</sst>"
    )
    row_xml = []
    for row_number, (row, offset) in enumerate(zip(rows, offsets), 1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{row_number}" t="s"><v>{offset + column}</v></c>'
            for column in range(len(row))
        )
        row_xml.append(f'<row r="{row_number}">{cells}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


class ETFRadarSourceTests(unittest.TestCase):
    def test_unified_parser_reads_date_aum_weight_and_shares(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00981A")
        result = parse_unified_html(source, (FIXTURES / "unified.html").read_text())
        self.assertEqual(result["data_date"], "2026-08-25")
        self.assertEqual(result["aum"], 10_000_000_000)
        low = next(item for item in result["positions"] if item["stock_id"] == "4958")
        self.assertEqual(low["shares"], 1000)
        self.assertAlmostEqual(low["weight"], 0.001)

    def test_unified_parser_reads_live_embedded_asset_json(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00981A")
        assets = [
            {
                "AssetCode": "NAV",
                "Value": 10_000_000_000,
                "EditDate": "2026-08-25T16:29:09",
            },
            {
                "AssetCode": "ST",
                "Details": [
                    {
                        "TranDate": "2026-08-25T00:00:00",
                        "DetailCode": code,
                        "DetailName": name,
                        "Share": shares,
                        "NavRate": weight,
                    }
                    for code, name, shares, weight in [
                        ("2330", "台積電", 1_000_000, 10.0),
                        ("2383", "台光電", 500_000, 5.0),
                        ("4958", "臻鼎-KY", 1_000, 0.1),
                        ("2454", "聯發科", 200_000, 4.0),
                        ("2308", "台達電", 300_000, 3.0),
                    ]
                ],
            },
        ]
        # The live page rounds NavRate to 0.00 for genuine tiny holdings.
        assets[1]["Details"][2]["NavRate"] = 0.0
        assets[1]["Details"][2]["Amount"] = 10_000_000
        raw_html = (
            '<div id="DataAsset" data-content="'
            + html.escape(json.dumps(assets, ensure_ascii=False), quote=True)
            + '"></div>'
        )
        result = parse_unified_html(source, raw_html)
        self.assertEqual(result["data_date"], "2026-08-25")
        self.assertEqual(result["position_count"], 5)
        self.assertAlmostEqual(result["positions"][2]["weight"], 0.001)

    def test_capital_div_rows_are_not_duplicated_by_mobile_markup(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00982A")
        result = parse_capital_html(source, (FIXTURES / "capital.html").read_text())
        self.assertEqual(result["issuer"], "群益")
        self.assertEqual(result["position_count"], 5)
        self.assertEqual(result["data_date"], "2026-08-25")

    def test_capital_archive_api_parser_preserves_weight_precision(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00982A")
        stocks = [
            {
                "stocNo": code,
                "stocName": name,
                "weight": weight,
                "share": shares,
            }
            for code, name, weight, shares in [
                ("2330", "台積電", 8.5449, 1_794_000),
                ("2454", "聯發科", 6.7956, 872_000),
                ("4958", "臻鼎-KY", 0.1191, 42_000),
                ("3443", "創意", 0.0107, 1_000),
                ("8046", "南電", 0.0023, 1_000),
            ]
        ]
        raw_json = json.dumps(
            {
                "code": 200,
                "data": {
                    "pcf": {"date1": "2026-08-20", "nav": 49_337_861_148},
                    "stocks": stocks,
                },
            }
        )
        result = parse_capital_api_json(source, raw_json)
        self.assertEqual(result["data_date"], "2026-08-20")
        self.assertEqual(result["position_count"], 5)
        low = next(item for item in result["positions"] if item["stock_id"] == "8046")
        self.assertEqual(low["shares"], 1000)
        self.assertAlmostEqual(low["weight"], 0.000023)

    def test_goal_star_archive_reconstructs_tiny_weight_and_marks_provenance(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00981A")
        items = [
            {
                "date": "2026-08-20",
                "stock_symbol": str(2300 + index),
                "stock_name": f"主要持股{index}",
                "shares": 1_000_000,
                "ratio": "1.000000",
                "close": "100.0000",
            }
            for index in range(5)
        ]
        items.append(
            {
                "date": "2026-08-20",
                "stock_symbol": "4958",
                "stock_name": "臻鼎-KY",
                "shares": 1_000,
                "ratio": "0.000000",
                "close": "100.0000",
            }
        )
        result = parse_goal_star_json(
            source,
            json.dumps({"items": items, "total": len(items)}),
            requested_date=date(2026, 8, 20),
        )
        low = next(item for item in result["positions"] if item["stock_id"] == "4958")
        self.assertAlmostEqual(result["aum"], 10_000_000_000)
        self.assertAlmostEqual(low["weight"], 0.00001)
        self.assertEqual(result["provenance"], "third_party")
        self.assertTrue(result["aum_estimated"])

    def test_fuhwa_parser_uses_asset_table_not_pcf_cash_table(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00991A")
        result = parse_fuhwa_html(source, (FIXTURES / "fuhwa.html").read_text())
        self.assertEqual(result["aum"], 6_000_000_000)
        self.assertEqual(result["positions"][2]["stock_id"], "4958")
        self.assertAlmostEqual(result["positions"][2]["weight"], 0.0012)

    def test_fuhwa_archive_workbook_parser(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00991A")
        result = parse_fuhwa_xlsx(source, _fuhwa_workbook())
        self.assertEqual(result["data_date"], "2026-08-25")
        self.assertEqual(result["aum"], 6_000_000_000)
        self.assertEqual(result["positions"][2]["shares"], 1000)
        self.assertAlmostEqual(result["positions"][2]["weight"], 0.0012)

    def test_schema_mismatch_raises_instead_of_returning_false_zero(self) -> None:
        source = next(item for item in ETF_SOURCES if item.code == "00981A")
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            parse_unified_html(source, "<html>基金投資組合資料日期:2026/08/25</html>")


if __name__ == "__main__":
    unittest.main()
