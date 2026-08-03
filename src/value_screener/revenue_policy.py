from __future__ import annotations

from collections.abc import Iterable


Period = tuple[int, int]


def shift_period(period: Period, offset: int) -> Period:
    year, month = period
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def has_revenue_signal(
    revenues: dict[Period, float],
    period: Period,
    *,
    signal: str,
) -> bool:
    current = [shift_period(period, offset) for offset in (-2, -1, 0)]
    prior_year = [(year - 1, month) for year, month in current]
    required = current + prior_year
    if signal == "latest_revenue_yoy":
        required = [period, (period[0] - 1, period[1])]
    elif signal == "revenue_acceleration":
        previous = [shift_period(period, offset) for offset in (-5, -4, -3)]
        required += previous + [(year - 1, month) for year, month in previous]
    elif signal != "revenue_3m_yoy":
        raise ValueError(f"unsupported revenue signal: {signal}")
    return all(item in revenues for item in required)


def signal_coverage(
    revenue_by_stock: dict[str, dict[Period, float]],
    stock_ids: Iterable[str],
    period: Period,
    *,
    signal: str,
) -> float:
    ids = list(stock_ids)
    if not ids:
        return 0.0
    covered = sum(
        has_revenue_signal(revenue_by_stock.get(stock_id, {}), period, signal=signal)
        for stock_id in ids
    )
    return covered / len(ids)


def select_latest_covered_period(
    revenue_by_stock: dict[str, dict[Period, float]],
    stock_ids: Iterable[str],
    periods: Iterable[Period],
    *,
    signal: str,
    threshold: float,
) -> tuple[Period | None, float]:
    ids = list(stock_ids)
    for period in sorted(set(periods), reverse=True):
        coverage = signal_coverage(revenue_by_stock, ids, period, signal=signal)
        if coverage >= threshold:
            return period, coverage
    return None, 0.0
