from __future__ import annotations

import calendar
from datetime import date, timedelta


QUARTER_MONTHS = (3, 6, 9, 12)


def quarter_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def previous_quarter(value: date) -> date:
    index = QUARTER_MONTHS.index(value.month)
    if index == 0:
        return quarter_end(value.year - 1, 12)
    return quarter_end(value.year, QUARTER_MONTHS[index - 1])


def latest_complete_quarter(as_of: date) -> date:
    """Return a conservative quarter with broad market filing coverage.

    Non-year-end quarters use a 60-day lag. Year-end uses 105 days to avoid
    mixing complete and incomplete annual filings.
    """

    candidates: list[date] = []
    for year in range(as_of.year - 2, as_of.year + 1):
        for month in QUARTER_MONTHS:
            value = quarter_end(year, month)
            lag = 105 if month == 12 else 60
            if value + timedelta(days=lag) <= as_of:
                candidates.append(value)
    if not candidates:
        raise ValueError("找不到已完整申報的季度")
    return max(candidates)


def quarter_series(start: date, end: date) -> list[date]:
    if start.month not in QUARTER_MONTHS or end.month not in QUARTER_MONTHS:
        raise ValueError("季度日期必須為 3/6/9/12 月底")
    values: list[date] = []
    current = start
    while current <= end:
        values.append(current)
        if current.month == 12:
            current = quarter_end(current.year + 1, 3)
        else:
            current = quarter_end(current.year, current.month + 3)
    return values


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def next_day(value: date) -> date:
    return value + timedelta(days=1)


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1
