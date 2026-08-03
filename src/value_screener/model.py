from __future__ import annotations

import bisect
import math
import re
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from .dates import previous_quarter
from .quality import aggregate_check_status, revenue_coverage_checks


def as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def linear_score(value: float | None, floor: float, target: float, points: float) -> float:
    if value is None or target == floor:
        return 0.0
    return points * clamp((value - floor) / (target - floor))


def descending_score(value: float | None, best: float, worst: float, points: float) -> float:
    if value is None or worst == best:
        return 0.0
    return points * clamp((worst - value) / (worst - best))


def last_quarters(end: date, count: int) -> list[date]:
    values = [end]
    while len(values) < count:
        values.append(previous_quarter(values[-1]))
    return list(reversed(values))


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def _row_map(rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows:
        metric_type = str(row.get("type") or "")
        if not metric_type or metric_type.endswith("_per"):
            continue
        value = as_number(row.get("value"))
        if value is not None:
            values[metric_type] = value
    return values


def _first(values: dict[str, float], names: Iterable[str]) -> float | None:
    for name in names:
        if name in values:
            return values[name]
    return None


DEBT_TYPE_PATTERN = re.compile(
    r"Borrowing|Borrowings|BondsPayable|LeaseLiabilit|ShortTermBillsPayable|CurrentPortionOfLongtermLiabilities",
    re.IGNORECASE,
)
DEBT_ORIGIN_PATTERN = re.compile(r"借款|應付公司債|租賃負債|應付短期票券|一年內到期長期負債")


def _debt_value(rows: list[dict[str, Any]]) -> tuple[float, set[str]]:
    families: dict[str, dict[str, float]] = defaultdict(dict)
    unknown: set[str] = set()
    for row in rows:
        metric_type = str(row.get("type") or "")
        origin = str(row.get("origin_name") or "")
        if not metric_type or metric_type.endswith("_per"):
            continue
        origin_match = bool(DEBT_ORIGIN_PATTERN.search(origin))
        type_match = bool(DEBT_TYPE_PATTERN.search(metric_type))
        if not origin_match and not type_match:
            continue
        value = as_number(row.get("value"))
        if value is None or value <= 0:
            continue
        lowered = metric_type.lower()
        if "lease" in lowered or "租賃負債" in origin:
            family = "lease"
        elif "bond" in lowered or "公司債" in origin:
            family = "bond"
        elif "bill" in lowered or "短期票券" in origin:
            family = "bill"
        else:
            family = "borrowing"
        families[family][metric_type] = value
        if origin_match and not type_match:
            unknown.add(f"{metric_type}｜{origin}")

    total = 0.0
    for family, metrics in families.items():
        aggregate_names = {
            "borrowings",
            "totalborrowings",
            "leaseliabilities",
            "totalleaseliabilities",
            "bondspayabletotal",
        }
        aggregate = [value for key, value in metrics.items() if key.lower() in aggregate_names]
        components = [value for key, value in metrics.items() if key.lower() not in aggregate_names]
        if aggregate:
            total += max(max(aggregate), sum(components))
        else:
            total += sum(components)
    return total, unknown


def parse_balance(rows: list[dict[str, Any]]) -> tuple[dict[str, float | None], set[str]]:
    values = _row_map(rows)
    debt, unknown_debt = _debt_value(rows)

    financial_parts = [
        "CurrentFinancialAssetsAtFairvalueThroughProfitOrLoss",
        "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
        "FinancialAssetsAtFairvalueThroughOtherComprehensiveIncome",
        "FinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
        "FinancialAssetsAtAmortizedCost",
    ]
    financial_assets_sum = sum(values.get(name, 0.0) for name in financial_parts)
    financial_assets_aggregate = _first(values, ["CurrentFinancialAssets"])
    current_financial_assets = max(financial_assets_sum, financial_assets_aggregate or 0.0)

    receivables = sum(
        value
        for name, value in values.items()
        if re.match(r"^(AccountsReceivableNet|NotesReceivableNet)$", name)
    )

    metrics: dict[str, float | None] = {
        "cash": _first(values, ["CashAndCashEquivalents", "CashCashEquivalents"]),
        "current_financial_assets": current_financial_assets,
        "receivables": receivables,
        "inventory": _first(values, ["Inventories", "Inventory"]),
        "property_plant_equipment": _first(values, ["PropertyPlantAndEquipment"]),
        "goodwill": _first(values, ["Goodwill"]),
        "current_assets": _first(values, ["CurrentAssets"]),
        "current_liabilities": _first(values, ["CurrentLiabilities"]),
        "liabilities": _first(values, ["Liabilities", "TotalLiabilities"]),
        "total_assets": _first(values, ["TotalAssets", "Assets"]),
        "equity": _first(values, ["EquityAttributableToOwnersOfParent", "Equity"]),
        "debt": debt,
    }
    return metrics, unknown_debt


def parse_income(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    values = _row_map(rows)
    return {
        "revenue": _first(values, ["Revenue", "OperatingRevenue"]),
        "operating_income": _first(values, ["OperatingIncome", "NetOperatingIncomeLoss"]),
        "net_income": _first(values, ["IncomeAfterTaxes", "IncomeFromContinuingOperations"]),
        "eps": _first(values, ["EPS", "BasicEarningsLossPerShare"]),
    }


def parse_cashflow(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    values = _row_map(rows)
    cfo = _first(values, ["CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities"])
    capex = _first(
        values,
        [
            "PropertyAndPlantAndEquipment",
            "AcquisitionOfPropertyPlantAndEquipment",
            "PaymentsToAcquirePropertyPlantAndEquipment",
        ],
    )
    fcf = None if cfo is None or capex is None else cfo - abs(capex)
    return {"cfo": cfo, "capex": capex, "fcf": fcf}


def revenue_window_yoy(
    revenues: dict[tuple[int, int], float],
    periods: list[tuple[int, int]],
) -> float | None:
    prior_periods = [(year - 1, month) for year, month in periods]
    current_values = [revenues.get(period) for period in periods]
    prior_values = [revenues.get(period) for period in prior_periods]
    if not all(value is not None for value in current_values + prior_values):
        return None
    prior_sum = sum(float(value) for value in prior_values if value is not None)
    if prior_sum <= 0:
        return None
    return sum(float(value) for value in current_values if value is not None) / prior_sum - 1


def _latest_rows(rows: Iterable[dict[str, Any]], allowed: set[str]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        if stock_id not in allowed:
            continue
        if stock_id not in output or str(row.get("date") or "") > str(output[stock_id].get("date") or ""):
            output[stock_id] = row
    return output


def _percentiles(results: list[dict[str, Any]], metric: str) -> dict[str, float | None]:
    groups: dict[str, list[float]] = defaultdict(list)
    global_values: list[float] = []
    for row in results:
        value = as_number(row.get(metric))
        if value is None:
            continue
        if metric in {"per", "pbr"} and value <= 0:
            continue
        groups[row["industry"]].append(value)
        global_values.append(value)
    for values in groups.values():
        values.sort()
    global_values.sort()

    output: dict[str, float | None] = {}
    for row in results:
        value = as_number(row.get(metric))
        if value is None or (metric in {"per", "pbr"} and value <= 0):
            output[row["stock_id"]] = None
            continue
        values = groups[row["industry"]]
        if len(values) < 5:
            values = global_values
        if len(values) <= 1:
            output[row["stock_id"]] = 0.5
            continue
        position = bisect.bisect_left(values, value)
        output[row["stock_id"]] = position / (len(values) - 1)
    return output


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "是"}


def analyze(
    datasets: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    manual_review: dict[str, dict[str, str]],
    *,
    as_of: date,
    latest_quarter: date,
    annual_years: list[int],
) -> dict[str, Any]:
    universe_cfg = config["universe"]
    id_pattern = re.compile(universe_cfg["stock_id_pattern"])
    markets = set(universe_cfg["markets"])
    excluded_industries = set(universe_cfg["excluded_industries"])
    generic_industries = set(universe_cfg["generic_industries"])
    financial_industries = set(universe_cfg["financial_industries"])

    info_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in datasets["info"]:
        stock_id = str(row.get("stock_id") or "")
        if id_pattern.fullmatch(stock_id) and row.get("type") in markets:
            info_groups[stock_id].append(row)

    universe: dict[str, dict[str, str]] = {}
    for stock_id, rows in info_groups.items():
        categories = [str(row.get("industry_category") or "其他") for row in rows]
        if any(category in excluded_industries for category in categories):
            continue
        specific = [category for category in categories if category not in generic_industries]
        category = specific[0] if specific else categories[0]
        latest_info = max(rows, key=lambda row: str(row.get("date") or ""))
        universe[stock_id] = {
            "stock_id": stock_id,
            "stock_name": str(latest_info.get("stock_name") or ""),
            "market": str(latest_info.get("type") or ""),
            "industry": category,
        }

    ids = set(universe)
    old_ids = {str(row.get("stock_id")) for row in datasets["price_old"] if str(row.get("stock_id")) in ids}

    price_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in datasets["price_recent"]:
        stock_id = str(row.get("stock_id") or "")
        if stock_id in ids:
            price_groups[stock_id].append(row)
    for rows in price_groups.values():
        rows.sort(key=lambda row: str(row.get("date") or ""))

    latest_market_date = max(
        (str(row.get("date") or "") for rows in price_groups.values() for row in rows),
        default="",
    )
    market_value_rows = _latest_rows(datasets["market_value"], ids)
    per_rows = _latest_rows(datasets["per"], ids)

    balance_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in datasets["balance"]:
        stock_id = str(row.get("stock_id") or "")
        if stock_id in ids:
            balance_groups[stock_id].append(row)

    income_groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in datasets["income"]:
        stock_id = str(row.get("stock_id") or "")
        if stock_id in ids:
            income_groups[stock_id][str(row.get("date") or "")].append(row)

    cashflow_groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in datasets["cashflow"]:
        stock_id = str(row.get("stock_id") or "")
        if stock_id in ids:
            cashflow_groups[stock_id][str(row.get("date") or "")].append(row)

    revenue_groups: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    revenue_periods: set[tuple[int, int]] = set()
    for row in datasets["revenue"]:
        stock_id = str(row.get("stock_id") or "")
        if stock_id not in ids:
            continue
        year = int(row.get("revenue_year") or 0)
        month = int(row.get("revenue_month") or 0)
        revenue = as_number(row.get("revenue"))
        if year and month and revenue is not None:
            revenue_groups[stock_id][(year, month)] = revenue
            revenue_periods.add((year, month))
    latest_revenue_period = max(revenue_periods) if revenue_periods else None

    ttm_quarters = last_quarters(latest_quarter, 4)
    prior_ttm_quarters = last_quarters(previous_quarter(ttm_quarters[0]), 4)
    haircuts = config["liquidation_haircuts"]
    unknown_debt_types: set[str] = set()
    results: list[dict[str, Any]] = []

    for stock_id in sorted(ids):
        info = universe[stock_id]
        prices = price_groups.get(stock_id, [])
        recent_20 = prices[-20:]
        latest_price = prices[-1] if prices else {}
        avg_turnover = None
        if recent_20:
            turnovers = [as_number(row.get("Trading_money")) for row in recent_20]
            valid_turnovers = [value for value in turnovers if value is not None]
            if valid_turnovers:
                avg_turnover = sum(valid_turnovers) / len(valid_turnovers)

        balance, unknown = parse_balance(balance_groups.get(stock_id, []))
        unknown_debt_types.update(unknown)
        cash = balance.get("cash") or 0.0
        debt = balance.get("debt") or 0.0
        liabilities = balance.get("liabilities")
        market_value = as_number(market_value_rows.get(stock_id, {}).get("market_value"))
        net_cash_ratio = ratio(cash - debt, market_value)
        current_ratio = ratio(balance.get("current_assets"), balance.get("current_liabilities"))
        liabilities_ratio = ratio(liabilities, balance.get("total_assets"))
        debt_to_cash = ratio(debt, cash)

        liquidation_value = None
        if liabilities is not None:
            liquidation_value = (
                cash * float(haircuts["cash"])
                + (balance.get("current_financial_assets") or 0.0)
                * float(haircuts["current_financial_assets"])
                + (balance.get("receivables") or 0.0) * float(haircuts["receivables"])
                + (balance.get("inventory") or 0.0) * float(haircuts["inventory"])
                + (balance.get("property_plant_equipment") or 0.0)
                * float(haircuts["property_plant_equipment"])
                + (balance.get("goodwill") or 0.0) * float(haircuts["goodwill"])
                - liabilities
            )
        liquidation_coverage = ratio(liquidation_value, market_value)

        quarterly: dict[date, dict[str, float | None]] = {}
        for date_text, rows in income_groups.get(stock_id, {}).items():
            try:
                quarter_date = date.fromisoformat(date_text)
            except ValueError:
                continue
            quarterly[quarter_date] = parse_income(rows)

        annual_income: dict[int, float] = {}
        complete_profit_years = 0
        profitable_years = 0
        for year in annual_years:
            values = [
                quarterly.get(date(year, month, 31 if month in {3, 12} else 30), {}).get("net_income")
                for month in (3, 6, 9, 12)
            ]
            if all(value is not None for value in values):
                complete_profit_years += 1
                annual_income[year] = sum(float(value) for value in values if value is not None)
                if annual_income[year] > 0:
                    profitable_years += 1

        def sum_quarter_metric(quarters: list[date], metric: str) -> float | None:
            values = [quarterly.get(value, {}).get(metric) for value in quarters]
            if not all(value is not None for value in values):
                return None
            return sum(float(value) for value in values if value is not None)

        ttm_revenue = sum_quarter_metric(ttm_quarters, "revenue")
        ttm_operating_income = sum_quarter_metric(ttm_quarters, "operating_income")
        ttm_net_income = sum_quarter_metric(ttm_quarters, "net_income")
        prior_ttm_revenue = sum_quarter_metric(prior_ttm_quarters, "revenue")
        prior_ttm_operating_income = sum_quarter_metric(prior_ttm_quarters, "operating_income")
        prior_ttm_net_income = sum_quarter_metric(prior_ttm_quarters, "net_income")
        operating_margin = ratio(ttm_operating_income, ttm_revenue)
        prior_operating_margin = ratio(prior_ttm_operating_income, prior_ttm_revenue)
        operating_margin_change = None
        if operating_margin is not None and prior_operating_margin is not None:
            operating_margin_change = operating_margin - prior_operating_margin
        net_income_growth = None
        if ttm_net_income is not None and prior_ttm_net_income is not None and prior_ttm_net_income > 0:
            net_income_growth = ttm_net_income / prior_ttm_net_income - 1

        positive_fcf_years = 0
        complete_fcf_years = 0
        annual_fcf: dict[int, float] = {}
        annual_cfo: dict[int, float] = {}
        for year in annual_years:
            metrics = parse_cashflow(cashflow_groups.get(stock_id, {}).get(f"{year}-12-31", []))
            if metrics["cfo"] is not None:
                annual_cfo[year] = float(metrics["cfo"])
            if metrics["fcf"] is not None:
                complete_fcf_years += 1
                annual_fcf[year] = float(metrics["fcf"])
                if metrics["fcf"] > 0:
                    positive_fcf_years += 1

        latest_annual_year = annual_years[-1]
        latest_annual_cfo = annual_cfo.get(latest_annual_year)
        latest_annual_fcf = annual_fcf.get(latest_annual_year)
        latest_annual_net_income = annual_income.get(latest_annual_year)
        cash_conversion = None
        if latest_annual_net_income is not None and latest_annual_net_income > 0:
            cash_conversion = ratio(latest_annual_cfo, latest_annual_net_income)

        revenue_3m_yoy = None
        previous_revenue_3m_yoy = None
        revenue_acceleration = None
        latest_revenue_yoy = None
        if latest_revenue_period:
            current_periods = [shift_month(*latest_revenue_period, offset) for offset in (-2, -1, 0)]
            previous_periods = [shift_month(*latest_revenue_period, offset) for offset in (-5, -4, -3)]
            revenue_3m_yoy = revenue_window_yoy(revenue_groups[stock_id], current_periods)
            previous_revenue_3m_yoy = revenue_window_yoy(revenue_groups[stock_id], previous_periods)
            if revenue_3m_yoy is not None and previous_revenue_3m_yoy is not None:
                revenue_acceleration = revenue_3m_yoy - previous_revenue_3m_yoy
            current_latest = revenue_groups[stock_id].get(latest_revenue_period)
            prior_latest = revenue_groups[stock_id].get((latest_revenue_period[0] - 1, latest_revenue_period[1]))
            if current_latest is not None and prior_latest is not None and prior_latest > 0:
                latest_revenue_yoy = current_latest / prior_latest - 1

        manual = manual_review.get(stock_id, {})
        per_row = per_rows.get(stock_id, {})
        results.append(
            {
                **info,
                "market_date": str(latest_price.get("date") or ""),
                "close": as_number(latest_price.get("close")),
                "market_value": market_value,
                "avg_daily_turnover": avg_turnover,
                "per": as_number(per_row.get("PER")),
                "pbr": as_number(per_row.get("PBR")),
                "dividend_yield": as_number(per_row.get("dividend_yield")),
                **balance,
                "net_cash_ratio": net_cash_ratio,
                "current_ratio": current_ratio,
                "liabilities_ratio": liabilities_ratio,
                "debt_to_cash": debt_to_cash,
                "liquidation_value": liquidation_value,
                "liquidation_coverage": liquidation_coverage,
                "profitable_years": profitable_years,
                "complete_profit_years": complete_profit_years,
                "positive_fcf_years": positive_fcf_years,
                "complete_fcf_years": complete_fcf_years,
                "ttm_revenue": ttm_revenue,
                "ttm_operating_income": ttm_operating_income,
                "ttm_net_income": ttm_net_income,
                "prior_ttm_net_income": prior_ttm_net_income,
                "ttm_operating_margin": operating_margin,
                "prior_ttm_operating_margin": prior_operating_margin,
                "ttm_operating_margin_change": operating_margin_change,
                "ttm_net_income_growth": net_income_growth,
                "revenue_3m_yoy": revenue_3m_yoy,
                "previous_revenue_3m_yoy": previous_revenue_3m_yoy,
                "revenue_acceleration": revenue_acceleration,
                "latest_revenue_yoy": latest_revenue_yoy,
                "latest_annual_cfo": latest_annual_cfo,
                "latest_annual_fcf": latest_annual_fcf,
                "cash_conversion": cash_conversion,
                "established_10y": stock_id in old_ids,
                "governance_status": manual.get("governance_status") or "待複核",
                "catalyst": manual.get("catalyst") or "",
                "manual_notes": manual.get("notes") or "",
                "manual_exclude": _truthy(manual.get("exclude") or ""),
            }
        )

    per_percentiles = _percentiles(results, "per")
    pbr_percentiles = _percentiles(results, "pbr")
    margin_percentiles = _percentiles(results, "ttm_operating_margin")
    targets = config["score_targets"]
    gates = config["hard_gates"]

    for row in results:
        stock_id = row["stock_id"]
        row["sector_per_percentile"] = per_percentiles[stock_id]
        row["sector_pbr_percentile"] = pbr_percentiles[stock_id]
        row["sector_margin_percentile"] = margin_percentiles[stock_id]

        defense_score = (
            linear_score(
                row["net_cash_ratio"],
                float(targets["net_cash_ratio_floor"]),
                float(targets["net_cash_ratio_target"]),
                15,
            )
            + linear_score(
                row["current_ratio"],
                float(targets["current_ratio_floor"]),
                float(targets["current_ratio_target"]),
                10,
            )
            + descending_score(
                row["liabilities_ratio"],
                float(targets["liabilities_ratio_target"]),
                float(targets["liabilities_ratio_worst"]),
                10,
            )
            + 10 * clamp(row["profitable_years"] / max(1, int(gates["min_profitable_years"])))
            + 5 * clamp(row["positive_fcf_years"] / max(1, len(annual_years)))
        )
        valuation_score = (
            linear_score(
                row["liquidation_coverage"],
                float(targets["liquidation_coverage_floor"]),
                float(targets["liquidation_coverage_target"]),
                12,
            )
            + (10 * (1 - row["sector_per_percentile"]) if row["sector_per_percentile"] is not None else 0)
            + (4 * (1 - row["sector_pbr_percentile"]) if row["sector_pbr_percentile"] is not None else 0)
            + descending_score(row["per"], float(targets["per_best"]), float(targets["per_worst"]), 4)
        )
        momentum_score = (
            linear_score(
                row["revenue_3m_yoy"],
                float(targets["growth_floor"]),
                float(targets["growth_target"]),
                8,
            )
            + linear_score(
                row["latest_revenue_yoy"],
                float(targets["growth_floor"]),
                float(targets["growth_target"]),
                4,
            )
            + (4 * row["sector_margin_percentile"] if row["sector_margin_percentile"] is not None else 0)
            + linear_score(
                row["ttm_net_income_growth"],
                float(targets["growth_floor"]),
                float(targets["growth_target"]),
                4,
            )
        )
        row["defense_score"] = round(defense_score, 4)
        row["valuation_score"] = round(valuation_score, 4)
        row["momentum_score"] = round(momentum_score, 4)
        row["total_score"] = round(defense_score + valuation_score + momentum_score, 4)

        reasons: list[str] = []
        if row["industry"] in financial_industries:
            reasons.append("金融業需使用專用模型")
        if row["manual_exclude"]:
            reasons.append("人工排除")
        if not row["established_10y"]:
            reasons.append("未確認滿10年交易歷史")
        if row["market_value"] is None or row["close"] is None:
            reasons.append("缺少市值或收盤價")
        if row["cash"] is None or row["total_assets"] is None or row["liabilities"] is None:
            reasons.append("缺少最新資產負債表")
        if row["complete_profit_years"] < int(gates["min_complete_profit_years"]):
            reasons.append("五年獲利資料不完整")
        elif row["profitable_years"] < int(gates["min_profitable_years"]):
            reasons.append("未連續五年獲利")
        if row["positive_fcf_years"] < int(gates["min_positive_fcf_years"]):
            reasons.append("正自由現金流年數不足")
        if row["current_ratio"] is None or row["current_ratio"] < float(gates["min_current_ratio"]):
            reasons.append("流動比率未達門檻")
        if row["liabilities_ratio"] is None or row["liabilities_ratio"] > float(gates["max_liabilities_to_assets"]):
            reasons.append("負債比率超標或缺漏")
        if row["debt_to_cash"] is None or row["debt_to_cash"] > float(gates["max_debt_to_cash"]):
            reasons.append("有息負債高於現金門檻")
        if row["avg_daily_turnover"] is None or row["avg_daily_turnover"] < float(gates["min_avg_daily_turnover_twd"]):
            reasons.append("20日均成交金額不足")
        if gates.get("require_positive_ttm_income") and (row["ttm_net_income"] is None or row["ttm_net_income"] <= 0):
            reasons.append("TTM淨利非正或缺漏")

        row["hard_pass"] = not reasons
        row["exclusion_reasons"] = "；".join(reasons)
        missing = []
        for label, key in (
            ("PER", "per"),
            ("PBR", "pbr"),
            ("3M營收", "revenue_3m_yoy"),
            ("TTM成長", "ttm_net_income_growth"),
        ):
            if row[key] is None:
                missing.append(label)
        row["missing_flags"] = "、".join(missing)

    results.sort(key=lambda row: (not row["hard_pass"], -row["total_score"], row["stock_id"]))
    rank = 0
    watchlist_size = int(config["report"]["watchlist_size"])
    focus_size = int(config["report"]["focus_size"])
    for row in results:
        if row["hard_pass"]:
            rank += 1
            row["rank"] = rank
            if rank <= focus_size:
                row["funnel_stage"] = "精華20"
            elif rank <= watchlist_size:
                row["funnel_stage"] = "自選100"
            else:
                row["funnel_stage"] = "量化通過"
        else:
            row["rank"] = None
            row["funnel_stage"] = "基礎觀察"

    universe_count = len(results)
    active_results = [row for row in results if row["close"] is not None]
    active_count = len(active_results)
    financial_count = sum(row["industry"] in financial_industries for row in results)
    market_coverage = sum(row["market_value"] is not None for row in active_results) / max(1, active_count)
    balance_coverage = sum(row["total_assets"] is not None for row in active_results) / max(1, active_count)
    profit_coverage = (
        sum(row["complete_profit_years"] == len(annual_years) for row in active_results) / max(1, active_count)
    )
    hard_pass_count = sum(row["hard_pass"] for row in results)
    revenue_threshold = float(config["quality_checks"]["min_revenue_coverage"])
    revenue_checks, revenue_metrics = revenue_coverage_checks(
        results,
        threshold=revenue_threshold,
        financial_industries=financial_industries,
    )
    checks = [
        {
            "check": "評分權重合計",
            "actual": sum(float(value) for value in config["weights"].values()),
            "expected": 100,
            "tolerance": 0,
            "status": "OK" if sum(float(value) for value in config["weights"].values()) == 100 else "FAIL",
            "notes": "防禦50／估值30／動能20",
        },
        {
            "check": "市值資料覆蓋率",
            "actual": market_coverage,
            "expected": 0.95,
            "tolerance": 0,
            "status": "OK" if market_coverage >= 0.95 else "FAIL",
            "notes": "以近20交易日有成交的活躍普通股為分母",
        },
        {
            "check": "資產負債表覆蓋率",
            "actual": balance_coverage,
            "expected": 0.80,
            "tolerance": 0,
            "status": "OK" if balance_coverage >= 0.80 else "FAIL",
            "notes": f"使用完整季度 {latest_quarter.isoformat()}",
        },
        {
            "check": "五年獲利資料覆蓋率",
            "actual": profit_coverage,
            "expected": 0.70,
            "tolerance": 0,
            "status": "OK" if profit_coverage >= 0.70 else "WARN",
            "notes": "新上市公司與資料缺漏會降低覆蓋",
        },
        *revenue_checks,
        {
            "check": "量化硬門檻通過數",
            "actual": hard_pass_count,
            "expected": 1,
            "tolerance": 0,
            "status": "OK" if hard_pass_count >= 1 else "WARN",
            "notes": "門檻刻意嚴格；0 檔不代表程式錯誤",
        },
        {
            "check": "未識別有息負債標籤",
            "actual": len(unknown_debt_types),
            "expected": 0,
            "tolerance": 0,
            "status": "OK" if not unknown_debt_types else "WARN",
            "notes": "需定期檢視 FinMind XBRL 標籤變化",
        },
    ]
    data_check_names = {
        "市值資料覆蓋率",
        "資產負債表覆蓋率",
        "五年獲利資料覆蓋率",
        "排名母體營收覆蓋率",
        "一般公司營收覆蓋率",
        "未識別有息負債標籤",
    }
    data_status = aggregate_check_status(item for item in checks if item["check"] in data_check_names)
    model_status = aggregate_check_status(checks)

    metadata = {
        "as_of": as_of.isoformat(),
        "latest_market_date": latest_market_date,
        "latest_financial_quarter": latest_quarter.isoformat(),
        "annual_years": annual_years,
        "latest_revenue_period": (
            f"{latest_revenue_period[0]}-{latest_revenue_period[1]:02d}" if latest_revenue_period else ""
        ),
        "universe_count": universe_count,
        "active_count": active_count,
        "no_recent_price_count": universe_count - active_count,
        "financial_count": financial_count,
        "operating_company_count": universe_count - financial_count,
        "hard_pass_count": hard_pass_count,
        "watchlist_count": min(hard_pass_count, watchlist_size),
        "focus_count": min(hard_pass_count, focus_size),
        "model_status": model_status,
        "data_status": data_status,
        "market_coverage": market_coverage,
        "balance_coverage": balance_coverage,
        "profit_history_coverage": profit_coverage,
        "ranked_revenue_coverage": revenue_metrics["ranked_revenue_coverage"],
        "universe_revenue_coverage": revenue_metrics["universe_revenue_coverage"],
        "revenue_coverage_threshold": revenue_threshold,
        "unknown_debt_types": sorted(unknown_debt_types),
        "source_row_counts": {key: len(value) for key, value in datasets.items()},
    }
    return {"metadata": metadata, "config": config, "checks": checks, "results": results}
