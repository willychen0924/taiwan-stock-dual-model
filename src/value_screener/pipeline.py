from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import load_manual_review
from .dates import add_years, latest_complete_quarter, next_day, quarter_end, quarter_series, shift_month
from .finmind import FinMindClient
from .model import analyze


def _fetch_exact_dates(
    client: FinMindClient,
    dataset: str,
    dates: list[date],
    *,
    force: bool,
    max_age_hours: float | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in dates:
        rows.extend(
            client.fetch(
                dataset,
                start_date=value.isoformat(),
                end_date=next_day(value).isoformat(),
                force=force,
                max_age_hours=max_age_hours,
            )
        )
    return rows


def _select_recent_trading_dates(
    rows: list[dict[str, Any]],
    *,
    as_of: date,
    include_as_of: bool,
) -> list[date]:
    cutoff = as_of if include_as_of else as_of - timedelta(days=1)
    return sorted(
        date.fromisoformat(str(row["date"]))
        for row in rows
        if row.get("date") and date.fromisoformat(str(row["date"])) <= cutoff
    )[-20:]


def _require_latest_snapshots(
    datasets: dict[str, list[dict[str, Any]]],
    *,
    latest_market_date: date,
) -> None:
    required = {"市值": "market_value", "PER": "per"}
    missing = [label for label, key in required.items() if not datasets.get(key)]
    if missing:
        labels = "、".join(missing)
        raise ValueError(f"{latest_market_date.isoformat()} 的 {labels} 資料尚未更新")


def run_pipeline(
    root: Path,
    config: dict[str, Any],
    *,
    as_of: date,
    force: bool = False,
    include_as_of: bool = False,
) -> dict[str, Any]:
    import os

    token = os.environ.get("FINMIND_TOKEN", "")
    client = FinMindClient(token, root / "data" / "raw")
    latest_quarter = latest_complete_quarter(as_of)
    complete_year_end = latest_quarter.year - 1 if latest_quarter.month < 12 else latest_quarter.year
    annual_years = list(range(complete_year_end - 4, complete_year_end + 1))

    recent_start = as_of - timedelta(days=45)
    # Full-market datasets are single-date snapshots. TradingDate is the
    # exception and supplies the dates for incremental snapshot downloads.
    recent_end = next_day(as_of) if include_as_of else as_of
    old_anchor = add_years(as_of, -int(config["hard_gates"]["required_history_years"]))
    old_start = old_anchor - timedelta(days=30)
    old_end = old_anchor + timedelta(days=31)

    first_income_quarter = quarter_end(annual_years[0], 3)
    income_quarters = quarter_series(first_income_quarter, latest_quarter)
    cashflow_dates = [date(year, 12, 31) for year in annual_years]

    datasets: dict[str, list[dict[str, Any]]] = {}
    datasets["info"] = client.fetch(
        "TaiwanStockInfo",
        force=force,
        max_age_hours=18,
    )
    recent_calendar = client.fetch(
        "TaiwanStockTradingDate",
        start_date=recent_start.isoformat(),
        end_date=recent_end.isoformat(),
        force=force,
        max_age_hours=18,
    )
    recent_trading_dates = _select_recent_trading_dates(
        recent_calendar,
        as_of=as_of,
        include_as_of=include_as_of,
    )
    if not recent_trading_dates:
        raise ValueError("交易日曆未提供最近已完成交易日")
    datasets["price_recent"] = _fetch_exact_dates(
        client,
        "TaiwanStockPrice",
        recent_trading_dates,
        force=force,
    )

    old_calendar = client.fetch(
        "TaiwanStockTradingDate",
        start_date=old_start.isoformat(),
        end_date=old_end.isoformat(),
        force=force,
    )
    old_dates = sorted(date.fromisoformat(str(row["date"])) for row in old_calendar if row.get("date"))
    if not old_dates:
        raise ValueError("十年前交易日曆無資料")
    old_trade_date = min(old_dates, key=lambda value: abs((value - old_anchor).days))
    datasets["price_old"] = _fetch_exact_dates(
        client,
        "TaiwanStockPrice",
        [old_trade_date],
        force=force,
    )

    latest_market_date = recent_trading_dates[-1]
    datasets["market_value"] = _fetch_exact_dates(
        client,
        "TaiwanStockMarketValue",
        [latest_market_date],
        force=force,
        max_age_hours=0 if include_as_of else None,
    )
    datasets["per"] = _fetch_exact_dates(
        client,
        "TaiwanStockPER",
        [latest_market_date],
        force=force,
        max_age_hours=0 if include_as_of else None,
    )
    _require_latest_snapshots(datasets, latest_market_date=latest_market_date)
    datasets["balance"] = _fetch_exact_dates(
        client,
        "TaiwanStockBalanceSheet",
        [latest_quarter],
        force=force,
    )
    datasets["income"] = _fetch_exact_dates(
        client,
        "TaiwanStockFinancialStatements",
        income_quarters,
        force=force,
    )
    datasets["cashflow"] = _fetch_exact_dates(
        client,
        "TaiwanStockCashFlowsStatement",
        cashflow_dates,
        force=force,
    )
    revenue_dates = [
        date(*shift_month(as_of.year, as_of.month, offset), 1)
        for offset in range(-18, 1)
    ]
    datasets["revenue"] = []
    for revenue_date in revenue_dates:
        is_current_revenue_snapshot = revenue_date == revenue_dates[-1]
        snapshot_is_today = as_of == date.today()
        datasets["revenue"].extend(
            client.fetch(
                "TaiwanStockMonthRevenue",
                start_date=revenue_date.isoformat(),
                end_date=next_day(revenue_date).isoformat(),
                force=force,
                # The current filing month changes daily as issuers disclose.
                # Preserve one point-in-time snapshot per report date so a later
                # rerun cannot leak subsequently published revenue into history.
                max_age_hours=18 if is_current_revenue_snapshot and snapshot_is_today else None,
                cache_tag=f"asof_{as_of.isoformat()}" if is_current_revenue_snapshot else None,
            )
        )

    manual_review = load_manual_review(root / "config" / "manual_review.csv")
    return analyze(
        datasets,
        config,
        manual_review,
        as_of=as_of,
        latest_quarter=latest_quarter,
        annual_years=annual_years,
    )
