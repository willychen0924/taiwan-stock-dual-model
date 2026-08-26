from __future__ import annotations

import html
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar_sources import (  # noqa: E402
    ETF_SOURCES,
    parse_capital_html,
    parse_fuhwa_html,
    parse_fuhwa_xlsx,
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
