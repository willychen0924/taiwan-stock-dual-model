"""Official holdings adapters for the five ETFs tracked by ETF Radar.

The three issuers publish semantically similar data with different markup.  The
parsers intentionally validate the schema instead of silently returning an
empty portfolio: an issuer redesign must become a visible ``missing`` cell in
the report, never a false zero position.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.request import HTTPCookieProcessor, Request, build_opener
from xml.etree import ElementTree


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ETFSource:
    code: str
    name: str
    issuer: str
    adapter: str
    source_id: str
    url: str


ETF_SOURCES = (
    ETFSource(
        "00981A",
        "主動統一台股增長",
        "統一",
        "unified",
        "49YTW",
        "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW",
    ),
    ETFSource(
        "00403A",
        "主動統一升級50",
        "統一",
        "unified",
        "63YTW",
        "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=63YTW",
    ),
    ETFSource(
        "00991A",
        "主動復華未來50",
        "復華",
        "fuhwa",
        "ETF23",
        "https://www.fhtrust.com.tw/ETF/etf_detail/ETF23",
    ),
    ETFSource(
        "00982A",
        "主動群益台灣強棒",
        "群益",
        "capital",
        "399",
        "https://www.capitalfund.com.tw/etf/product/detail/399/buyback",
    ),
    ETFSource(
        "00992A",
        "主動群益科技創新",
        "群益",
        "capital",
        "500",
        "https://www.capitalfund.com.tw/etf/product/detail/500/buyback",
    ),
)


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    value = dict(attrs).get("class") or ""
    return set(value.split())


class _HoldingsHTMLParser(HTMLParser):
    """Collect ordinary HTML tables and Capital's div-based stock rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table_depth = 0

        self.capital_rows: list[list[str]] = []
        self.embedded_data: dict[str, str] = {}
        self._div_depth = 0
        self._capital_row: list[str] | None = None
        self._capital_row_depth = 0
        self._capital_cell: list[str] | None = None
        self._capital_cell_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id") or ""
        data_content = attributes.get("data-content")
        if element_id and data_content is not None:
            self.embedded_data[element_id] = data_content

        if tag == "table":
            self._table_depth += 1
            if self._table is None:
                self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

        if tag != "div":
            return
        self._div_depth += 1
        class_names = _classes(attrs)
        if self._capital_row is None and {"tr", "show-for-medium"} <= class_names:
            self._capital_row = []
            self._capital_row_depth = self._div_depth
        elif (
            self._capital_row is not None
            and self._capital_cell is None
            and self._div_depth == self._capital_row_depth + 1
            and class_names.intersection({"th", "td"})
        ):
            self._capital_cell = []
            self._capital_cell_depth = self._div_depth

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self._table_depth -= 1
            if self._table_depth == 0:
                if self._table:
                    self.tables.append(self._table)
                self._table = None

        if tag != "div":
            return
        if self._capital_cell is not None and self._div_depth == self._capital_cell_depth:
            if self._capital_row is not None:
                self._capital_row.append(" ".join(self._capital_cell).strip())
            self._capital_cell = None
        if self._capital_row is not None and self._div_depth == self._capital_row_depth:
            if any(self._capital_row):
                self.capital_rows.append(self._capital_row)
            self._capital_row = None
        self._div_depth -= 1

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if not clean:
            return
        self.text.append(clean)
        if self._cell is not None:
            self._cell.append(clean)
        if self._capital_cell is not None:
            self._capital_cell.append(clean)


def _flat_html(raw_html: str) -> _HoldingsHTMLParser:
    parser = _HoldingsHTMLParser()
    parser.feed(raw_html)
    parser.close()
    return parser


def _clean_header(value: str) -> str:
    return re.sub(r"[\s（）()％%]", "", value)


def _integer(value: str) -> int:
    cleaned = re.sub(r"[^\d-]", "", value)
    if not cleaned or cleaned == "-":
        raise ValueError(f"invalid integer: {value!r}")
    return int(cleaned)


def _weight(value: str) -> float:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", value)
    if not match:
        raise ValueError(f"invalid percentage: {value!r}")
    return float(match.group(1)) / 100.0


def _iso_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%Y/%m/%d").date().isoformat()


def _match_date(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S)
        if match:
            return _iso_date(match.group(1))
    raise ValueError("portfolio date not found")


def _match_amount(text: str, patterns: tuple[str, ...]) -> float:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S)
        if match:
            return float(match.group(1).replace(",", ""))
    raise ValueError("fund net assets not found")


def _positions_from_tables(tables: list[list[list[str]]]) -> list[dict[str, Any]]:
    for table in tables:
        header_index = None
        indexes: dict[str, int] = {}
        for row_index, row in enumerate(table):
            headers = [_clean_header(cell) for cell in row]
            for index, header in enumerate(headers):
                if header in {"股票代號", "證券代號"}:
                    indexes["stock_id"] = index
                elif header in {"股票名稱", "證券名稱"}:
                    indexes["stock_name"] = index
                elif header == "股數":
                    indexes["shares"] = index
                elif "持股權重" in header or header == "權重":
                    indexes["weight"] = index
            if set(indexes) == {"stock_id", "stock_name", "shares", "weight"}:
                header_index = row_index
                break
            indexes = {}
        if header_index is None:
            continue

        positions: list[dict[str, Any]] = []
        for row in table[header_index + 1 :]:
            if max(indexes.values()) >= len(row):
                continue
            stock_id = row[indexes["stock_id"]].strip()
            if not re.fullmatch(r"\d{4}", stock_id):
                continue
            try:
                positions.append(
                    {
                        "stock_id": stock_id,
                        "stock_name": row[indexes["stock_name"]].strip(),
                        "shares": _integer(row[indexes["shares"]]),
                        "weight": _weight(row[indexes["weight"]]),
                    }
                )
            except ValueError:
                continue
        if positions:
            return positions
    return []


def _validate_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for position in positions:
        deduplicated[position["stock_id"]] = position
    positions = list(deduplicated.values())
    if len(positions) < 5:
        raise ValueError(f"portfolio schema mismatch: only {len(positions)} stock rows")
    if any(item["shares"] < 0 or item["weight"] < 0 for item in positions):
        raise ValueError("portfolio contains a negative stock position")
    return positions


def parse_unified_html(source: ETFSource, raw_html: str) -> dict[str, Any]:
    parsed = _flat_html(raw_html)
    text = " ".join(parsed.text)
    embedded = parsed.embedded_data.get("DataAsset")
    if embedded:
        assets = json.loads(embedded)
        nav = next(
            (item for item in assets if str(item.get("AssetCode") or "").upper() == "NAV"),
            None,
        )
        stocks = next(
            (item for item in assets if str(item.get("AssetCode") or "").upper() == "ST"),
            None,
        )
        if not nav or not stocks:
            raise ValueError("embedded portfolio is missing NAV or stock assets")
        aum = float(nav.get("Value") or 0.0)
        details = stocks.get("Details") or []
        positions = _validate_positions(
            [
                {
                    "stock_id": str(item.get("DetailCode") or "").strip(),
                    "stock_name": str(item.get("DetailName") or "").strip(),
                    "shares": int(float(item.get("Share") or 0)),
                    # NavRate is rounded to two decimals and turns genuine tiny
                    # holdings into 0.00%.  Amount / NAV retains the official
                    # data while recovering the precision needed by the radar.
                    "weight": (
                        float(item.get("Amount") or 0.0) / aum
                        if aum > 0 and float(item.get("Amount") or 0.0) > 0
                        else float(item.get("NavRate") or 0.0) / 100.0
                    ),
                }
                for item in details
                if re.fullmatch(r"\d{4}", str(item.get("DetailCode") or "").strip())
            ]
        )
        raw_date = str((details[0] if details else {}).get("TranDate") or nav.get("EditDate") or "")
        match = re.match(r"(\d{4}-\d{2}-\d{2})", raw_date)
        if not match:
            raise ValueError("embedded portfolio date not found")
        return _snapshot(
            source,
            raw_html,
            data_date=match.group(1),
            aum=aum,
            positions=positions,
        )

    positions = _validate_positions(_positions_from_tables(parsed.tables))
    return _snapshot(
        source,
        raw_html,
        data_date=_match_date(
            text,
            (r"基金投資組合\s*資料日期\s*[:：]?\s*(\d{4}/\d{1,2}/\d{1,2})",),
        ),
        aum=_match_amount(
            text,
            (r"基金資產\s*淨資產\s*NTD\s*([\d,]+)",),
        ),
        positions=positions,
    )


def parse_capital_html(source: ETFSource, raw_html: str) -> dict[str, Any]:
    parsed = _flat_html(raw_html)
    text = " ".join(parsed.text)
    positions: list[dict[str, Any]] = []
    for row in parsed.capital_rows:
        if len(row) < 4 or not re.fullmatch(r"\d{4}", row[0].strip()):
            continue
        try:
            positions.append(
                {
                    "stock_id": row[0].strip(),
                    "stock_name": row[1].strip(),
                    "weight": _weight(row[2]),
                    "shares": _integer(row[3]),
                }
            )
        except ValueError:
            continue
    return _snapshot(
        source,
        raw_html,
        data_date=_match_date(
            text,
            (
                r"申購買回清單公告.*?\((\d{4}/\d{1,2}/\d{1,2})\).*?股票",
                r"\((\d{4}/\d{1,2}/\d{1,2})\)\s*股票",
            ),
        ),
        aum=_match_amount(
            text,
            (r"基金淨資產價值\(元\)\s*TWD\s*([\d,]+)",),
        ),
        positions=_validate_positions(positions),
    )


def parse_fuhwa_html(source: ETFSource, raw_html: str) -> dict[str, Any]:
    parsed = _flat_html(raw_html)
    text = " ".join(parsed.text)
    positions = _validate_positions(_positions_from_tables(parsed.tables))
    return _snapshot(
        source,
        raw_html,
        data_date=_match_date(
            text,
            (
                r"\(日期\s*[:：]\s*(\d{4}/\d{1,2}/\d{1,2})\)",
                r"基金資產.*?資料日期\s*[:：]\s*(\d{4}/\d{1,2}/\d{1,2})",
            ),
        ),
        aum=_match_amount(
            text,
            (r"基金資產淨值\s*NTD\s*([\d,]+)",),
        ),
        positions=positions,
    )


def _xlsx_rows(raw_xlsx: bytes) -> list[list[str]]:
    """Read the small, single-sheet issuer workbook without a runtime dependency."""

    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw_xlsx)) as archive:
        shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(item.itertext()) for item in shared_root.findall("x:si", namespace)
        ]
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows: list[list[str]] = []
    for row in sheet.findall(".//x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            reference = str(cell.get("r") or "A1")
            letters = re.match(r"[A-Z]+", reference)
            if not letters:
                continue
            column = 0
            for letter in letters.group(0):
                column = column * 26 + ord(letter) - ord("A") + 1
            value_node = cell.find("x:v", namespace)
            raw_value = value_node.text if value_node is not None else ""
            if cell.get("t") == "s" and raw_value:
                value = shared[int(raw_value)]
            else:
                value = raw_value
            values[column - 1] = value
        if values:
            rows.append([values.get(index, "") for index in range(max(values) + 1)])
    return rows


def parse_fuhwa_xlsx(source: ETFSource, raw_xlsx: bytes) -> dict[str, Any]:
    rows = _xlsx_rows(raw_xlsx)
    data_date = ""
    aum: float | None = None
    header_index: int | None = None
    for index, row in enumerate(rows):
        first = row[0].strip() if row else ""
        date_match = re.search(r"日期\s*[:：]\s*(\d{4}/\d{1,2}/\d{1,2})", first)
        if date_match:
            data_date = _iso_date(date_match.group(1))
        if first == "基金資產淨值" and index + 1 < len(rows):
            aum = float(rows[index + 1][0].replace(",", ""))
        headers = [_clean_header(value) for value in row]
        if headers[:5] == ["證券代號", "證券名稱", "股數", "金額", "權重"]:
            header_index = index

    if not data_date:
        raise ValueError("portfolio date not found in workbook")
    if aum is None:
        raise ValueError("fund net assets not found in workbook")
    if header_index is None:
        raise ValueError("portfolio headers not found in workbook")

    positions: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        if len(row) < 5 or not re.fullmatch(r"\d{4}", row[0].strip()):
            continue
        try:
            positions.append(
                {
                    "stock_id": row[0].strip(),
                    "stock_name": row[1].strip(),
                    "shares": _integer(row[2]),
                    "weight": (
                        float(row[3].replace(",", "")) / aum
                        if aum > 0 and row[3].replace(",", "").strip()
                        else _weight(row[4])
                    ),
                }
            )
        except ValueError:
            continue
    return _snapshot(
        source,
        raw_xlsx,
        data_date=data_date,
        aum=aum,
        positions=_validate_positions(positions),
    )


def _snapshot(
    source: ETFSource,
    raw_content: str | bytes,
    *,
    data_date: str,
    aum: float,
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    if aum <= 0:
        raise ValueError("fund net assets must be positive")
    return {
        "etf_code": source.code,
        "etf_name": source.name,
        "issuer": source.issuer,
        "adapter": source.adapter,
        "source_id": source.source_id,
        "source_url": source.url,
        "data_date": data_date,
        "aum": aum,
        "positions": positions,
        "position_count": len(positions),
        "source_html_sha256": hashlib.sha256(
            raw_content.encode("utf-8") if isinstance(raw_content, str) else raw_content
        ).hexdigest(),
        "status": "healthy",
        "error": "",
    }


PARSERS: dict[str, Callable[[ETFSource, str], dict[str, Any]]] = {
    "unified": parse_unified_html,
    "capital": parse_capital_html,
    "fuhwa": parse_fuhwa_html,
}


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        },
    )


def fetch_official_snapshots(
    *,
    requested_as_of: date,
    timeout: int = 30,
    sources: tuple[ETFSource, ...] = ETF_SOURCES,
) -> list[dict[str, Any]]:
    """Fetch every source independently; one broken issuer never hides the rest."""

    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    unified_seeded = False
    snapshots: list[dict[str, Any]] = []
    for source in sources:
        try:
            if source.adapter == "unified" and not unified_seeded:
                with opener.open(_request("https://www.ezmoney.com.tw/"), timeout=timeout):
                    pass
                unified_seeded = True
            request = _request(source.url)
            if source.adapter == "unified":
                request.add_header("Referer", "https://www.ezmoney.com.tw/")
            with opener.open(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                raw_html = response.read().decode(charset, errors="replace")
            snapshot = PARSERS[source.adapter](source, raw_html)
            if source.adapter == "fuhwa":
                candidate = requested_as_of - timedelta(days=1)
                while candidate.weekday() >= 5:
                    candidate -= timedelta(days=1)
                if snapshot["data_date"] < candidate.isoformat():
                    archive_url = (
                        f"https://www.fhtrust.com.tw/api/assetsExcel/{source.source_id}/"
                        f"{candidate.strftime('%Y%m%d')}"
                    )
                    with opener.open(_request(archive_url), timeout=timeout) as response:
                        archive = response.read()
                    archive_snapshot = parse_fuhwa_xlsx(source, archive)
                    if archive_snapshot["data_date"] > snapshot["data_date"]:
                        snapshot = archive_snapshot
            if snapshot["data_date"] > requested_as_of.isoformat():
                raise ValueError(
                    f"source date {snapshot['data_date']} is after requested date {requested_as_of}"
                )
            snapshots.append(snapshot)
        except Exception as exc:  # Source errors are report data, not a pipeline crash.
            snapshots.append(
                {
                    "etf_code": source.code,
                    "etf_name": source.name,
                    "issuer": source.issuer,
                    "adapter": source.adapter,
                    "source_id": source.source_id,
                    "source_url": source.url,
                    "data_date": None,
                    "aum": None,
                    "positions": [],
                    "position_count": 0,
                    "source_html_sha256": "",
                    "status": "missing",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return snapshots
