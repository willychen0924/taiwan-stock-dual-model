from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


DAILY_FIELDS = [
    "date",
    "stock_id",
    "Trading_Volume",
    "Trading_money",
    "open",
    "max",
    "min",
    "close",
    "spread",
    "Trading_turnover",
    "Foreign_Investor",
    "Investment_Trust",
    "Dealer_self",
    "Dealer_Hedging",
    "ForeignInvestmentSharesRatio",
    "MarginPurchaseTodayBalance",
    "MarginPurchaseYesterdayBalance",
    "ShortSaleTodayBalance",
    "ShortSaleYesterdayBalance",
]

WEEKLY_FIELDS = ["date", "stock_id", "HoldingSharesLevel", "people", "percent", "unit"]
INSTITUTION_NAMES = ("Foreign_Investor", "Investment_Trust", "Dealer_self", "Dealer_Hedging")
LARGE_HOLDER_LEVEL = "more than 1,000,001"


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Iterable[float]) -> float | None:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else None


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def _signed_percent(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:+.{digits}%}"


def _signed_pp(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}個百分點"


def _net_phrase(label: str, value: float | None) -> str:
    if value is None:
        return f"{label}資料不足"
    if value == 0:
        return f"{label}近5日買賣超0張"
    action = "買超" if value >= 0 else "賣超"
    return f"{label}近5日{action}{abs(value) / 1_000:,.0f}張"


def rows_through(rows: Iterable[dict[str, Any]], max_date: str) -> list[dict[str, Any]]:
    """Exclude current-day/future rows beyond the model's completed market date."""
    return [row for row in rows if str(row.get("date") or "") <= max_date]


def top_stock_universe(
    value_result: dict[str, Any],
    momentum_result: dict[str, Any],
    *,
    top_n: int,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    selection: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for model_id, payload in (
        ("defensive_value", value_result),
        ("operating_momentum", momentum_result),
    ):
        ranked = sorted(
            (row for row in payload.get("results", []) if row.get("hard_pass") and row.get("rank") is not None),
            key=lambda row: int(row["rank"]),
        )[:top_n]
        for row in ranked:
            stock_id = str(row["stock_id"])
            if stock_id not in selection:
                ordered.append(stock_id)
                selection[stock_id] = {
                    "stock_name": str(row.get("stock_name") or ""),
                    "models": {},
                }
            selection[stock_id]["models"][model_id] = int(row["rank"])
    return ordered, selection


def analyze_technical(price_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(
        (row for row in price_rows if _number(row.get("close")) is not None),
        key=lambda row: str(row.get("date") or ""),
    )
    closes = [_number(row.get("close")) for row in rows]
    volumes = [_number(row.get("Trading_Volume")) or 0.0 for row in rows]
    if len(rows) < 60:
        return {
            "status": "資料不足",
            "summary": f"只有{len(rows)}個有效交易日，至少需要60日才能判讀20／60日趨勢。",
            "tone": "mid",
            "data_date": str(rows[-1].get("date") or "") if rows else "",
            "metrics": {"valid_days": len(rows)},
        }

    close = float(closes[-1])
    ma5 = float(_mean(float(value) for value in closes[-5:] if value is not None) or close)
    ma20 = float(_mean(float(value) for value in closes[-20:] if value is not None) or close)
    ma60 = float(_mean(float(value) for value in closes[-60:] if value is not None) or close)
    prior_ma20 = float(_mean(float(value) for value in closes[-25:-5] if value is not None) or ma20)
    ma20_change_5d = _change(ma20, prior_ma20)
    return_5d = _change(close, closes[-6]) if len(closes) >= 6 else None
    return_20d = _change(close, closes[-21]) if len(closes) >= 21 else None
    distance_ma20 = _change(close, ma20)
    volume_5 = _mean(volumes[-5:])
    volume_20 = _mean(volumes[-20:])
    volume_ratio = volume_5 / volume_20 if volume_5 is not None and volume_20 not in (None, 0) else None

    score = 0
    score += 2 if close > ma20 else -2
    score += 1 if ma20 > ma60 else -1
    score += 1 if (ma20_change_5d or 0) > 0 else -1
    score += 1 if (return_20d or 0) > 0 else -1
    if score >= 3:
        status, tone = "趨勢偏強", "up"
    elif score <= -3:
        status, tone = "趨勢偏弱", "down"
    else:
        status, tone = "區間整理", "mid"

    if close > ma20 and close > ma60:
        position = "股價站上20／60日線"
    elif close < ma20 and close < ma60:
        position = "股價跌破20／60日線"
    else:
        position = "股價位於20日與60日線之間"
    slope = "上揚" if (ma20_change_5d or 0) > 0.002 else "下彎" if (ma20_change_5d or 0) < -0.002 else "持平"
    volume_text = "量能資料不足" if volume_ratio is None else f"近5日均量為20日均量{volume_ratio:.1f}倍"
    summary = f"{position}，20日線近5日{slope}；{volume_text}，距20日線{_signed_percent(distance_ma20)}。"
    return {
        "status": status,
        "summary": summary,
        "tone": tone,
        "data_date": str(rows[-1].get("date") or ""),
        "metrics": {
            "close": close,
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "ma20_change_5d": ma20_change_5d,
            "return_5d": return_5d,
            "return_20d": return_20d,
            "distance_ma20": distance_ma20,
            "volume_ratio_5_20": volume_ratio,
            "valid_days": len(rows),
        },
    }


def _institution_net(rows: list[dict[str, Any]], name: str, days: int = 5) -> float | None:
    matching = [row for row in rows if str(row.get("name") or "") == name]
    if not matching:
        return None
    dates = sorted({str(row.get("date") or "") for row in matching if row.get("date")})[-days:]
    selected = [row for row in matching if str(row.get("date") or "") in dates]
    return sum((_number(row.get("buy")) or 0.0) - (_number(row.get("sell")) or 0.0) for row in selected)


def _series_change(rows: list[dict[str, Any]], key: str, lookback: int = 5) -> tuple[float | None, float | None, str]:
    usable = sorted(
        (row for row in rows if _number(row.get(key)) is not None),
        key=lambda row: str(row.get("date") or ""),
    )
    if not usable:
        return None, None, ""
    latest = _number(usable[-1].get(key))
    previous = _number(usable[-min(len(usable), lookback + 1)].get(key))
    return latest, _change(latest, previous), str(usable[-1].get("date") or "")


def _large_holder_change(rows: list[dict[str, Any]]) -> tuple[float | None, float | None, str]:
    usable = sorted(
        (row for row in rows if row.get("HoldingSharesLevel") == LARGE_HOLDER_LEVEL and _number(row.get("percent")) is not None),
        key=lambda row: str(row.get("date") or ""),
    )
    if not usable:
        return None, None, ""
    latest = _number(usable[-1].get("percent"))
    previous = _number(usable[-2].get("percent")) if len(usable) >= 2 else None
    delta_pp = latest - previous if latest is not None and previous is not None else None
    return latest, delta_pp, str(usable[-1].get("date") or "")


def analyze_chip(
    institutional_rows: list[dict[str, Any]],
    shareholding_rows: list[dict[str, Any]],
    margin_rows: list[dict[str, Any]],
    holding_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    foreign_5d = _institution_net(institutional_rows, "Foreign_Investor")
    trust_5d = _institution_net(institutional_rows, "Investment_Trust")
    dealer_5d = sum(
        value or 0.0
        for value in (
            _institution_net(institutional_rows, "Dealer_self"),
            _institution_net(institutional_rows, "Dealer_Hedging"),
        )
    )
    foreign_ratio, foreign_ratio_change, foreign_date = _series_change(
        shareholding_rows, "ForeignInvestmentSharesRatio", lookback=5
    )
    margin_balance, margin_change, margin_date = _series_change(
        margin_rows, "MarginPurchaseTodayBalance", lookback=5
    )
    large_ratio, large_change_pp, holding_date = _large_holder_change(holding_rows)

    score = 0
    for value in (foreign_5d, trust_5d):
        if value is not None:
            score += 1 if value > 0 else -1 if value < 0 else 0
    if large_change_pp is not None:
        score += 1 if large_change_pp > 0.1 else -1 if large_change_pp < -0.1 else 0
    if margin_change is not None:
        score += -1 if margin_change > 0.1 else 1 if margin_change < -0.1 else 0
    if score >= 2:
        status, tone = "籌碼改善", "up"
    elif score <= -2:
        status, tone = "籌碼轉弱", "down"
    else:
        status, tone = "籌碼中性", "mid"

    institutional_text = f"{_net_phrase('外資', foreign_5d)}、{_net_phrase('投信', trust_5d)}"
    large_text = "千張以上持股資料不足" if large_change_pp is None else f"千張以上持股比週變動{_signed_pp(large_change_pp)}"
    margin_text = "融資資料不足" if margin_change is None else f"融資餘額5日變動{_signed_percent(margin_change)}"
    source_dates = [date for date in (foreign_date, margin_date, holding_date) if date]
    return {
        "status": status,
        "summary": f"{institutional_text}；{large_text}，{margin_text}。",
        "tone": tone,
        "data_date": max(source_dates) if source_dates else "",
        "metrics": {
            "foreign_net_5d_shares": foreign_5d,
            "investment_trust_net_5d_shares": trust_5d,
            "dealer_net_5d_shares": dealer_5d,
            "foreign_holding_ratio": foreign_ratio,
            "foreign_holding_ratio_change_5d": foreign_ratio_change,
            "margin_balance": margin_balance,
            "margin_balance_change_5d": margin_change,
            "large_holder_1000_ratio": large_ratio,
            "large_holder_1000_change_pp": large_change_pp,
        },
    }


def build_daily_master(
    price_rows: list[dict[str, Any]],
    institutional_rows: list[dict[str, Any]],
    shareholding_rows: list[dict[str, Any]],
    margin_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    institutions: dict[str, dict[str, float]] = defaultdict(dict)
    for row in institutional_rows:
        date_label = str(row.get("date") or "")
        name = str(row.get("name") or "")
        if name in INSTITUTION_NAMES:
            institutions[date_label][name] = institutions[date_label].get(name, 0.0) + (
                (_number(row.get("buy")) or 0.0) - (_number(row.get("sell")) or 0.0)
            )
    share_by_date = {str(row.get("date") or ""): row for row in shareholding_rows}
    margin_by_date = {str(row.get("date") or ""): row for row in margin_rows}
    output: list[dict[str, Any]] = []
    for price in sorted(price_rows, key=lambda row: str(row.get("date") or "")):
        date_label = str(price.get("date") or "")
        share = share_by_date.get(date_label, {})
        margin = margin_by_date.get(date_label, {})
        row = {field: "" for field in DAILY_FIELDS}
        for field in (
            "date", "stock_id", "Trading_Volume", "Trading_money", "open", "max", "min", "close",
            "spread", "Trading_turnover",
        ):
            row[field] = price.get(field, "")
        for name in INSTITUTION_NAMES:
            row[name] = institutions.get(date_label, {}).get(name, "")
        row["ForeignInvestmentSharesRatio"] = share.get("ForeignInvestmentSharesRatio", "")
        for field in (
            "MarginPurchaseTodayBalance", "MarginPurchaseYesterdayBalance",
            "ShortSaleTodayBalance", "ShortSaleYesterdayBalance",
        ):
            row[field] = margin.get(field, "")
        output.append(row)
    return output


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
