from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


HISTORY_SCHEMA_VERSION = 1
MIN_REVENUE_COVERAGE = 0.80
FINANCIAL_INDUSTRIES = {"金融保險", "金融業"}


def _coverage(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(row.get(key) is not None for row in rows) / len(rows)


def build_history_record(payload: dict[str, Any], source_path: Path, *, root: Path) -> dict[str, Any]:
    metadata = payload["metadata"]
    results = payload["results"]
    model_id = str(metadata.get("model_id") or "defensive_value")
    model_name = str(metadata.get("model_name") or "台股防禦型價值篩選")
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    as_of = str(metadata["as_of"])
    report_id = f"{model_id}:{as_of}:{source_sha256[:16]}"

    ranked_rows = [row for row in results if row.get("hard_pass")]
    active_operating_rows = [
        row
        for row in results
        if row.get("close") is not None and row.get("industry") not in FINANCIAL_INDUSTRIES
    ]
    ranked_revenue_coverage = _coverage(ranked_rows, "revenue_3m_yoy")
    universe_revenue_coverage = _coverage(active_operating_rows, "revenue_3m_yoy")

    ineligible_reasons: list[str] = []
    if metadata.get("model_status") != "OK":
        ineligible_reasons.append(f"模型狀態為 {metadata.get('model_status') or 'UNKNOWN'}")
    if ranked_revenue_coverage < MIN_REVENUE_COVERAGE:
        ineligible_reasons.append("排名母體營收覆蓋率低於80%")
    if universe_revenue_coverage < MIN_REVENUE_COVERAGE:
        ineligible_reasons.append("一般公司營收覆蓋率低於80%")

    try:
        source_relative = str(source_path.resolve().relative_to(root.resolve()))
    except ValueError:
        source_relative = str(source_path.resolve())

    rankings = [
        {
            "stock_id": str(row["stock_id"]),
            "stock_name": str(row.get("stock_name") or ""),
            "rank": int(row["rank"]),
            "total_score": row.get("total_score"),
            "close": row.get("close"),
            "funnel_stage": str(row.get("funnel_stage") or ""),
        }
        for row in sorted(ranked_rows, key=lambda item: int(item["rank"]))
    ]

    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "report_id": report_id,
        "source_path": source_relative,
        "source_sha256": source_sha256,
        "model_id": model_id,
        "model_name": model_name,
        "config_version": payload.get("config", {}).get("version"),
        "as_of": as_of,
        "latest_market_date": str(metadata.get("latest_market_date") or ""),
        "latest_revenue_period": str(metadata.get("latest_revenue_period") or ""),
        "latest_financial_quarter": str(metadata.get("latest_financial_quarter") or ""),
        "model_status": str(metadata.get("model_status") or ""),
        "hard_pass_count": int(metadata.get("hard_pass_count") or 0),
        "ranked_revenue_coverage": ranked_revenue_coverage,
        "universe_revenue_coverage": universe_revenue_coverage,
        "eligible_for_backtest": not ineligible_reasons,
        "ineligible_reasons": ineligible_reasons,
        "rankings": rankings,
    }


def append_history_records(
    history_path: Path,
    report_paths: Iterable[Path],
    *,
    root: Path,
) -> list[dict[str, Any]]:
    records = [
        build_history_record(json.loads(path.read_text(encoding="utf-8")), path, root=root)
        for path in report_paths
    ]
    history_path.parent.mkdir(parents=True, exist_ok=True)

    appended: list[dict[str, Any]] = []
    with history_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing_ids: set[str] = set()
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"歷史檔第 {line_number} 行不是有效 JSON") from exc
            report_id = str(existing.get("report_id") or "")
            if not report_id:
                raise ValueError(f"歷史檔第 {line_number} 行缺少 report_id")
            existing_ids.add(report_id)

        handle.seek(0, 2)
        for record in records:
            if record["report_id"] in existing_ids:
                continue
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            existing_ids.add(record["report_id"])
            appended.append(record)
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return appended
