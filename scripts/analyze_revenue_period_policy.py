#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.revenue_policy import (  # noqa: E402
    select_latest_covered_period,
    signal_coverage,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shadow-check a coverage-based monthly-revenue period policy without changing rankings."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "latest" / "screening_results.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "qa" / "shadow" / "revenue_period_policy.json",
    )
    return parser.parse_args()


def _load_revenue_cache(directory: Path) -> dict[str, dict[tuple[int, int], float]]:
    output: dict[str, dict[tuple[int, int], float]] = {}
    for path in sorted(directory.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        for row in payload.get("data", []):
            stock_id = str(row.get("stock_id") or "")
            year = int(row.get("revenue_year") or 0)
            month = int(row.get("revenue_month") or 0)
            value = row.get("revenue")
            if stock_id and year and month and value is not None:
                output.setdefault(stock_id, {})[(year, month)] = float(value)
    return output


def _period_label(period: tuple[int, int] | None) -> str:
    return f"{period[0]}-{period[1]:02d}" if period else ""


def build_shadow_analysis(report: dict[str, Any], root: Path) -> dict[str, Any]:
    config = report["config"]
    threshold = float(config["quality_checks"]["min_revenue_coverage"])
    financial = set(config["universe"]["financial_industries"])
    stock_ids = [
        str(row["stock_id"])
        for row in report["results"]
        if str(row.get("industry") or "") not in financial
    ]
    revenue_by_stock = _load_revenue_cache(root / "data" / "raw" / "TaiwanStockMonthRevenue")
    periods = {period for values in revenue_by_stock.values() for period in values}
    max_period = max(periods) if periods else None
    signals: dict[str, Any] = {}
    for signal in ("latest_revenue_yoy", "revenue_3m_yoy", "revenue_acceleration"):
        selected, selected_coverage = select_latest_covered_period(
            revenue_by_stock,
            stock_ids,
            periods,
            signal=signal,
            threshold=threshold,
        )
        signals[signal] = {
            "max_period_coverage": (
                signal_coverage(revenue_by_stock, stock_ids, max_period, signal=signal)
                if max_period else 0.0
            ),
            "selected_period": _period_label(selected),
            "selected_coverage": selected_coverage,
        }
    return {
        "mode": "shadow_only",
        "as_of": str(report["metadata"].get("as_of") or ""),
        "universe_count": len(stock_ids),
        "threshold": threshold,
        "current_production_period": str(report["metadata"].get("latest_revenue_period") or ""),
        "max_cached_period": _period_label(max_period),
        "signals": signals,
        "production_changed": False,
        "note": "This file measures candidate coverage only; it does not alter scores, gates, statuses, or ranks.",
    }


def main() -> int:
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    analysis = build_shadow_analysis(report, ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    print(f"[輸出] {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
