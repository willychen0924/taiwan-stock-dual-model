#!/usr/bin/env python3
"""Rank the stocks previously discussed using a common FinMind data cut.

This script deliberately separates objective FinMind scores from the manually
reviewed re-rating catalyst.  It writes auditable JSON and CSV outputs under the
dated reports directory.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.value_screener.finmind import FinMindClient, FinMindError, load_dotenv


AS_OF = "2026-07-22"
DATA_END = "2026-07-22"
CHIP_START = "2026-04-01"
HOLDING_START = "2026-05-01"

# The second answer actually contained 12 names, not 10.  3596 appeared in
# both answers, leaving 16 unique stocks.
STOCKS: dict[str, dict[str, Any]] = {
    "3413": {"group": "第一次5檔", "catalyst_score": 11.5, "forward_eps": 25.35},
    "3044": {"group": "第一次5檔", "catalyst_score": 10.0, "forward_eps": 27.10},
    "3596": {"group": "兩次重複", "catalyst_score": 10.0, "forward_eps": 13.65},
    "6412": {"group": "第一次5檔", "catalyst_score": 7.5, "forward_eps": 6.05},
    "8081": {"group": "第一次5檔", "catalyst_score": 7.5, "forward_eps": 18.50},
    "1319": {"group": "第二次第一梯隊", "catalyst_score": 9.0, "forward_eps": 9.25},
    "3036": {"group": "第二次第一梯隊", "catalyst_score": 9.5, "forward_eps": 20.60},
    "3231": {"group": "第二次第一梯隊", "catalyst_score": 12.5, "forward_eps": 15.10},
    "5871": {"group": "第二次第一梯隊", "catalyst_score": 8.0, "forward_eps": 11.90},
    "2357": {"group": "第二次第一梯隊", "catalyst_score": 10.5, "forward_eps": 60.60},
    "6191": {"group": "第二次第二梯隊", "catalyst_score": 10.5, "forward_eps": 7.68},
    "2385": {"group": "第二次第二梯隊", "catalyst_score": 6.5, "forward_eps": 9.35},
    "6121": {"group": "第二次第二梯隊", "catalyst_score": 9.0, "forward_eps": 30.00},
    "2727": {"group": "第二次第二梯隊", "catalyst_score": 6.5, "forward_eps": 16.65},
    "1795": {"group": "第二次第二梯隊", "catalyst_score": 11.5, "forward_eps": 14.80},
    "2603": {"group": "第二次第二梯隊", "catalyst_score": 5.0, "forward_eps": 24.70},
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def linear_score(value: float, worst: float, best: float, points: float) -> float:
    if best == worst:
        return 0.0
    return clamp((value - worst) / (best - worst), 0.0, 1.0) * points


def net_institutional(row: dict[str, Any]) -> int:
    buys = sum(int(value or 0) for key, value in row.items() if key.endswith("_buy"))
    sells = sum(int(value or 0) for key, value in row.items() if key.endswith("_sell"))
    return buys - sells


def lower_bound(level: str) -> int | None:
    if "差異" in level:
        return None
    numbers = re.findall(r"[0-9,]+", level)
    if not numbers:
        return None
    return int(numbers[0].replace(",", ""))


def large_holder_series(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    by_date: dict[str, float] = {}
    for row in rows:
        bound = lower_bound(str(row.get("HoldingSharesLevel", "")))
        if bound is not None and bound >= 400_001:
            date = str(row["date"])
            by_date[date] = by_date.get(date, 0.0) + float(row.get("percent") or 0.0)
    return sorted(by_date.items())


def chip_score(
    inst20_pct: float,
    inst60_pct: float,
    margin_ratio: float,
    margin_change: float,
    holder_change: float | None,
) -> float:
    score = 0.0
    score += linear_score(inst20_pct, -0.01, 0.01, 4.0)
    score += linear_score(inst60_pct, -0.02, 0.02, 3.0)
    score += linear_score(-margin_ratio, -0.08, -0.005, 4.0)
    score += linear_score(-margin_change, -0.50, 0.25, 3.0)
    if holder_change is None:
        score += 0.5
    else:
        score += linear_score(holder_change, -0.03, 0.03, 1.0)
    return clamp(score, 0.0, 15.0)


def risk_penalty(
    net_income_growth: float,
    margin_change: float,
    annual_fcf: float,
    margin_ratio: float,
    margin_change_financing: float,
    institutional_20d_pct: float,
) -> float:
    """Explicitly penalize deteriorating earnings and crowded financing.

    The base momentum model floors negative growth at zero but does not subtract
    points.  That is appropriate for a broad screener, but too forgiving for an
    "EPS-protected re-rating" ranking, so this overlay makes the downside risks
    visible and auditable.
    """
    penalty = 0.0
    if net_income_growth < 0:
        penalty += linear_score(-net_income_growth, 0.0, 0.50, 8.0)
    if margin_change < -0.01:
        penalty += linear_score(-margin_change, 0.01, 0.08, 4.0)
    if annual_fcf < 0:
        penalty += 2.0
    if margin_ratio > 0.04:
        penalty += linear_score(margin_ratio, 0.04, 0.08, 2.0)
    if margin_change_financing > 0.30:
        penalty += linear_score(margin_change_financing, 0.30, 0.80, 1.0)
    if institutional_20d_pct < -0.01:
        penalty += linear_score(-institutional_20d_pct, 0.01, 0.03, 1.0)
    return clamp(penalty, 0.0, 15.0)


def fetch_rows(client: FinMindClient, dataset: str, stock_id: str, start: str) -> list[dict[str, Any]]:
    return client.fetch(
        dataset,
        data_id=stock_id,
        start_date=start,
        end_date=DATA_END,
        max_age_hours=12,
    )


def main() -> None:
    load_dotenv(ROOT / ".env")
    token = os.environ.get("FINMIND_TOKEN", "")
    client = FinMindClient(token, ROOT / "data" / "cache")

    momentum_path = ROOT / "reports" / "momentum" / "latest" / "screening_results.json"
    payload = json.loads(momentum_path.read_text(encoding="utf-8"))
    finmind_rows = {row["stock_id"]: row for row in payload["results"] if row["stock_id"] in STOCKS}

    output: list[dict[str, Any]] = []
    for index, (stock_id, manual) in enumerate(STOCKS.items(), start=1):
        print(f"[{index:02d}/{len(STOCKS)}] {stock_id}", flush=True)
        base = finmind_rows[stock_id]
        shares = float(base["market_value"]) / float(base["close"])

        institutional = fetch_rows(client, "TaiwanStockInstitutionalInvestorsBuySellWide", stock_id, CHIP_START)
        institutional.sort(key=lambda row: row["date"])
        inst_values = [net_institutional(row) for row in institutional]
        inst20 = sum(inst_values[-20:])
        inst60 = sum(inst_values[-60:])
        inst20_pct = inst20 / shares
        inst60_pct = inst60 / shares

        margins = fetch_rows(client, "TaiwanStockMarginPurchaseShortSale", stock_id, CHIP_START)
        margins.sort(key=lambda row: row["date"])
        margin_first = float(margins[0].get("MarginPurchaseTodayBalance") or 0.0) if margins else 0.0
        margin_last = float(margins[-1].get("MarginPurchaseTodayBalance") or 0.0) if margins else 0.0
        margin_ratio = margin_last * 1000.0 / shares
        margin_change = (margin_last / margin_first - 1.0) if margin_first else 0.0

        holder_change: float | None = None
        holder_latest: float | None = None
        holder_latest_date: str | None = None
        try:
            holders = fetch_rows(client, "TaiwanStockHoldingSharesPer", stock_id, HOLDING_START)
            holder_points = large_holder_series(holders)
            if holder_points:
                holder_latest_date = holder_points[-1][0]
                holder_latest = holder_points[-1][1] / 100.0
                holder_change = (holder_points[-1][1] - holder_points[0][1]) / 100.0
        except FinMindError as exc:
            print(f"  holding data unavailable: {exc}", flush=True)

        chips = chip_score(inst20_pct, inst60_pct, margin_ratio, margin_change, holder_change)
        growth = float(base["operating_momentum_score"]) / 60.0 * 25.0
        quality = float(base["quality_score"]) / 25.0 * 20.0
        valuation = float(base["valuation_liquidity_score"]) / 15.0 * 25.0
        catalyst = float(manual["catalyst_score"])
        total = growth + quality + valuation + chips + catalyst

        penalty = risk_penalty(
            float(base["ttm_net_income_growth"]),
            float(base["ttm_operating_margin_change"]),
            float(base["latest_annual_fcf"]),
            margin_ratio,
            margin_change,
            inst20_pct,
        )
        risk_adjusted = total - penalty

        forward_eps = float(manual["forward_eps"])
        output.append(
            {
                "stock_id": stock_id,
                "stock_name": base["stock_name"],
                "group": manual["group"],
                "market_date": base["market_date"],
                "close": base["close"],
                "ttm_per": base["per"],
                "forward_eps_reference": forward_eps,
                "forward_per_reference": float(base["close"]) / forward_eps,
                "pbr": base["pbr"],
                "dividend_yield": base["dividend_yield"],
                "revenue_3m_yoy": base["revenue_3m_yoy"],
                "revenue_acceleration": base["revenue_acceleration"],
                "ttm_net_income_growth": base["ttm_net_income_growth"],
                "ttm_operating_margin": base["ttm_operating_margin"],
                "ttm_operating_margin_change": base["ttm_operating_margin_change"],
                "latest_annual_fcf": base["latest_annual_fcf"],
                "cash_conversion": base["cash_conversion"],
                "net_cash_ratio": base["net_cash_ratio"],
                "liabilities_ratio": base["liabilities_ratio"],
                "institutional_net_20d": inst20,
                "institutional_net_20d_pct_shares": inst20_pct,
                "institutional_net_60d": inst60,
                "institutional_net_60d_pct_shares": inst60_pct,
                "margin_balance_lots": margin_last,
                "margin_balance_pct_shares": margin_ratio,
                "margin_change_since_2026_04_01": margin_change,
                "large_holder_400_lots_pct": holder_latest,
                "large_holder_latest_date": holder_latest_date,
                "large_holder_change_since_2026_05": holder_change,
                "score_growth_25": growth,
                "score_quality_20": quality,
                "score_valuation_25": valuation,
                "score_chips_15": chips,
                "score_catalyst_15": catalyst,
                "score_raw_100": total,
                "risk_penalty": penalty,
                "score_total_100": risk_adjusted,
            }
        )

    output.sort(key=lambda row: row["score_total_100"], reverse=True)
    for rank, row in enumerate(output, start=1):
        row["rank"] = rank

    out_dir = ROOT / "reports" / AS_OF
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "recommendation_ranking_finmind.json"
    csv_path = out_dir / "recommendation_ranking_finmind.csv"
    envelope = {
        "metadata": {
            "as_of": AS_OF,
            "source": "FinMind API and the local FinMind-based screening pipeline",
            "finmind_market_date": payload["metadata"]["latest_market_date"],
            "finmind_financial_quarter": payload["metadata"]["latest_financial_quarter"],
            "finmind_revenue_period": payload["metadata"]["latest_revenue_period"],
            "chip_period": {"start": CHIP_START, "end": payload["metadata"]["latest_market_date"]},
            "large_holder_period": {"start": HOLDING_START, "end": "latest weekly row per stock"},
            "finmind_datasets": [
                "TaiwanStockPrice",
                "TaiwanStockPER",
                "TaiwanStockMarketValue",
                "TaiwanStockMonthRevenue",
                "TaiwanStockFinancialStatements",
                "TaiwanStockBalanceSheet",
                "TaiwanStockCashFlowsStatement",
                "TaiwanStockInstitutionalInvestorsBuySellWide",
                "TaiwanStockMarginPurchaseShortSale",
                "TaiwanStockHoldingSharesPer",
            ],
            "stock_count": len(output),
            "score_weights": {"growth": 25, "quality": 20, "valuation": 25, "chips": 15, "catalyst_manual": 15},
            "risk_penalty_max": 15,
            "notes": [
                "forward_eps_reference and forward_per_reference are prior public-consensus/model references, not FinMind forecasts and not a direct ranking input",
                "catalyst_manual is a qualitative re-rating score; all other score layers are reproducible from the listed FinMind datasets",
                "the generic balance-sheet comparison is less suitable for financial/leasing companies such as 5871 and for lease-heavy businesses",
            ],
        },
        "results": output,
    }
    json_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0].keys()))
        writer.writeheader()
        writer.writerows(output)

    print(json_path)
    print(csv_path)
    for row in output:
        print(
            f"{row['rank']:>2} {row['stock_id']} {row['stock_name']:<8} "
            f"{row['score_total_100']:5.1f} TTMPE={row['ttm_per']!s:<5} "
            f"FwdPE={row['forward_per_reference']:4.1f} "
            f"Rev3M={row['revenue_3m_yoy']:+.1%} NI={row['ttm_net_income_growth']:+.1%} "
            f"Margin={row['margin_balance_pct_shares']:.1%}/{row['margin_change_since_2026_04_01']:+.0%} "
            f"Inst20={row['institutional_net_20d_pct_shares']:+.2%}",
            flush=True,
        )


if __name__ == "__main__":
    main()
