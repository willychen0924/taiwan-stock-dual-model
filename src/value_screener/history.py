from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .quality import revenue_signal_coverage_metadata, revenue_signal_coverage_metrics

HISTORY_SCHEMA_VERSION = 3
VOLATILE_METADATA_KEYS = {"created_at", "generated_at", "report_generated_at", "timestamp"}


def _semantic_sha256(payload: dict[str, Any]) -> str:
    stable_payload = dict(payload)
    stable_metadata = dict(payload.get("metadata", {}))
    for key in VOLATILE_METADATA_KEYS:
        stable_metadata.pop(key, None)
    stable_payload["metadata"] = stable_metadata
    canonical = json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_history_record(
    payload: dict[str, Any],
    source_path: Path,
    *,
    root: Path,
    min_revenue_coverage: float,
    financial_industries: Iterable[str],
) -> dict[str, Any]:
    metadata = payload["metadata"]
    results = payload["results"]
    model_id = str(metadata.get("model_id") or "defensive_value")
    model_name = str(metadata.get("model_name") or "台股防禦型價值篩選")
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    snapshot_sha256 = _semantic_sha256(payload)
    as_of = str(metadata["as_of"])
    report_id = f"{model_id}:{as_of}:{snapshot_sha256[:16]}"

    ranked_rows = [row for row in results if row.get("hard_pass")]
    if model_id == "operating_momentum":
        signal_key = "revenue_acceleration"
        signal_label = "營收加速度"
        signal_threshold = float(
            payload.get("config", {})
            .get("quality_checks", {})
            .get("min_revenue_acceleration_coverage", min_revenue_coverage)
        )
    else:
        signal_key = "revenue_3m_yoy"
        signal_label = "3M月營收年增率"
        signal_threshold = min_revenue_coverage
    revenue_metrics = revenue_signal_coverage_metrics(
        results,
        signal_key=signal_key,
        financial_industries=financial_industries,
    )
    ranked_revenue_coverage = revenue_metrics["ranked_revenue_coverage"]
    universe_revenue_coverage = revenue_metrics["universe_revenue_coverage"]

    ineligible_reasons: list[str] = []
    source_model_status = str(metadata.get("model_status") or "UNKNOWN")
    if source_model_status != "OK":
        ineligible_reasons.append(f"來源模型狀態為 {source_model_status}")
    threshold_label = f"{signal_threshold:.0%}"
    if ranked_revenue_coverage < signal_threshold:
        ineligible_reasons.append(f"排名母體{signal_label}覆蓋率低於{threshold_label}")
    if universe_revenue_coverage < signal_threshold:
        ineligible_reasons.append(f"一般公司{signal_label}覆蓋率低於{threshold_label}")
    effective_model_status = (
        "FAIL"
        if source_model_status == "FAIL"
        else "WARN"
        if ineligible_reasons
        else "OK"
    )

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
        "snapshot_sha256": snapshot_sha256,
        "model_id": model_id,
        "model_name": model_name,
        "config_version": payload.get("config", {}).get("version"),
        "as_of": as_of,
        "latest_market_date": str(metadata.get("latest_market_date") or ""),
        "latest_revenue_period": str(metadata.get("latest_revenue_period") or ""),
        "latest_financial_quarter": str(metadata.get("latest_financial_quarter") or ""),
        "model_status": source_model_status,
        "source_model_status": source_model_status,
        "effective_model_status": effective_model_status,
        "hard_pass_count": int(metadata.get("hard_pass_count") or 0),
        "ranked_revenue_coverage": ranked_revenue_coverage,
        "universe_revenue_coverage": universe_revenue_coverage,
        "revenue_coverage_threshold": signal_threshold,
        "revenue_signal_coverage": revenue_signal_coverage_metadata(
            revenue_metrics,
            signal_key=signal_key,
            signal_label=signal_label,
            threshold=signal_threshold,
        ),
        "eligible_for_backtest": not ineligible_reasons,
        "ineligible_reasons": ineligible_reasons,
        "rankings": rankings,
    }


def append_history_records(
    history_path: Path,
    report_paths: Iterable[Path],
    *,
    root: Path,
    min_revenue_coverage: float,
    financial_industries: Iterable[str],
) -> list[dict[str, Any]]:
    records = [
        build_history_record(
            json.loads(path.read_text(encoding="utf-8")),
            path,
            root=root,
            min_revenue_coverage=min_revenue_coverage,
            financial_industries=financial_industries,
        )
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
