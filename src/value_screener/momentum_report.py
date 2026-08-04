from __future__ import annotations

import csv
import html
import json
import shutil
from pathlib import Path
from typing import Any



MOMENTUM_CSV_FIELDS = [
    "rank",
    "funnel_stage",
    "momentum_bucket",
    "stock_id",
    "stock_name",
    "industry",
    "market",
    "hard_pass",
    "total_score",
    "operating_momentum_score",
    "quality_score",
    "valuation_liquidity_score",
    "market_date",
    "close",
    "market_value",
    "avg_daily_turnover",
    "avg_daily_volume",
    "per",
    "pbr",
    "revenue_period",
    "revenue_3m_yoy",
    "latest_revenue_yoy",
    "previous_revenue_3m_yoy",
    "revenue_acceleration",
    "ttm_net_income",
    "prior_ttm_net_income",
    "ttm_net_income_growth",
    "ttm_operating_margin",
    "prior_ttm_operating_margin",
    "ttm_operating_margin_change",
    "profitable_years",
    "complete_profit_years",
    "positive_fcf_years",
    "cash_conversion",
    "liabilities_ratio",
    "net_cash_ratio",
    "sector_per_percentile",
    "sector_pbr_percentile",
    "sector_margin_percentile",
    "model_summary",
    "governance_status",
    "catalyst",
    "manual_notes",
    "exclusion_reasons",
    "missing_flags",
]


def _format_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def _format_percent(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1%}"


def write_momentum_reports(
    result: dict[str, Any],
    reports_root: Path,
    *,
    history_path: Path | None = None,
    enrichment: dict[str, dict[str, str]] | None = None,
) -> dict[str, Path]:
    as_of = result["metadata"]["as_of"]
    dated_dir = reports_root / as_of
    latest_dir = reports_root / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    json_path = dated_dir / "screening_results.json"
    csv_path = dated_dir / "screening_results.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOMENTUM_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["results"])
    for source in (json_path, csv_path):
        shutil.copy2(source, latest_dir / source.name)
    return {"json": json_path, "csv": csv_path}


