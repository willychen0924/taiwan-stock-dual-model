from __future__ import annotations

from typing import Any, Iterable


def aggregate_check_status(checks: Iterable[dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "WARN") for item in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if statuses != {"OK"}:
        return "WARN"
    return "OK"


def _coverage(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(row.get(key) is not None for row in rows) / len(rows)


def revenue_signal_coverage_metrics(
    rows: Iterable[dict[str, Any]],
    *,
    signal_key: str,
    financial_industries: Iterable[str],
) -> dict[str, float]:
    values = list(rows)
    financials = set(financial_industries)
    ranked_rows = [row for row in values if row.get("hard_pass")]
    active_operating_rows = [
        row
        for row in values
        if row.get("close") is not None and row.get("industry") not in financials
    ]
    return {
        "ranked_revenue_coverage": _coverage(ranked_rows, signal_key),
        "universe_revenue_coverage": _coverage(active_operating_rows, signal_key),
    }


def revenue_coverage_checks(
    rows: Iterable[dict[str, Any]],
    *,
    threshold: float,
    financial_industries: Iterable[str],
    signal_key: str = "revenue_3m_yoy",
    signal_label: str = "3M月營收年增率",
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    metrics = revenue_signal_coverage_metrics(
        rows,
        signal_key=signal_key,
        financial_industries=financial_industries,
    )
    threshold_label = f"{threshold:.0%}"
    checks = [
        {
            "check": "排名母體營收覆蓋率",
            "actual": metrics["ranked_revenue_coverage"],
            "expected": threshold,
            "tolerance": 0,
            "status": "OK" if metrics["ranked_revenue_coverage"] >= threshold else "WARN",
            "notes": f"以量化硬門檻通過公司為分母，{signal_label}需達 {threshold_label}",
        },
        {
            "check": "一般公司營收覆蓋率",
            "actual": metrics["universe_revenue_coverage"],
            "expected": threshold,
            "tolerance": 0,
            "status": "OK" if metrics["universe_revenue_coverage"] >= threshold else "WARN",
            "notes": f"以有成交且非金融業公司為分母，{signal_label}需達 {threshold_label}",
        },
    ]
    return checks, metrics


def revenue_signal_coverage_metadata(
    metrics: dict[str, float],
    *,
    signal_key: str,
    signal_label: str,
    threshold: float,
) -> dict[str, Any]:
    return {
        "signal_key": signal_key,
        "signal_label": signal_label,
        "ranked": metrics["ranked_revenue_coverage"],
        "universe": metrics["universe_revenue_coverage"],
        "threshold": threshold,
    }
