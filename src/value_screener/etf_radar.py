"""Storage, weighting and signal lifecycle for ETF Radar.

ETF Radar is deliberately isolated from both 100-point stock models.  Its only
inputs are issuer portfolio snapshots plus read-only stock metadata used for
display.
"""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from .etf_radar_sources import ETF_SOURCES, fetch_official_snapshots


SIGNAL_ORDER = {
    "跨投信共振": 0,
    "確認布局": 1,
    "開始加碼": 2,
    "低部位觀察": 3,
}

PAIR_LABELS = {
    "missing": "資料不足",
    "unheld": "未持有",
    "decline_tail": "減碼尾倉",
    "residual": "配股殘留",
    "non_low": "非低部位",
    "low": "低部位觀察",
    "stopped": "已止跌",
    "start": "開始加碼",
    "confirm": "確認布局",
    "post_turn": "轉向後追蹤",
}


def load_etf_radar_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "version",
        "low_position_max_weight",
        "exclude_decline_days",
        "exclude_drop_5d",
        "boost_min_increase",
        "resonance_window_days",
        "resonance_min_issuers",
        "warmup_trading_days",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"ETF radar config missing: {', '.join(missing)}")
    if not 0 < float(config["low_position_max_weight"]) < 1:
        raise ValueError("low_position_max_weight must be between zero and one")
    return config


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _snapshot_by_code(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(snapshot["etf_code"]): snapshot for snapshot in snapshots}


def normalize_snapshot_day(
    snapshots: list[dict[str, Any]], *, requested_as_of: date
) -> dict[str, Any]:
    """Select one common disclosed date and mark stale issuers as missing."""

    healthy_dates = [
        str(item["data_date"])
        for item in snapshots
        if item.get("status") == "healthy" and item.get("data_date")
    ]
    if healthy_dates:
        counts = Counter(healthy_dates)
        target_date = max(counts, key=lambda item: (counts[item], item))
    else:
        target_date = requested_as_of.isoformat()

    normalized: dict[str, dict[str, Any]] = {}
    for source in ETF_SOURCES:
        item = dict(_snapshot_by_code(snapshots).get(source.code) or {})
        if not item:
            item = {
                "etf_code": source.code,
                "etf_name": source.name,
                "issuer": source.issuer,
                "source_url": source.url,
                "data_date": None,
                "aum": None,
                "positions": [],
                "position_count": 0,
                "status": "missing",
                "error": "source did not return a snapshot",
            }
        if item.get("status") == "healthy" and item.get("data_date") != target_date:
            item["status"] = "missing"
            item["error"] = (
                f"source date {item.get('data_date')} does not match common date {target_date}"
            )
            item["positions"] = []
            item["position_count"] = 0
        normalized[source.code] = item

    healthy = sum(item.get("status") == "healthy" for item in normalized.values())
    return {
        "schema_version": 1,
        "data_date": target_date,
        "requested_as_of": requested_as_of.isoformat(),
        "created_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
        "coverage": {"healthy": healthy, "total": len(ETF_SOURCES)},
        "snapshots": normalized,
    }


def save_snapshot_day(root: Path, day: dict[str, Any]) -> Path:
    data_date = str(day["data_date"])
    for code, snapshot in day["snapshots"].items():
        if snapshot.get("status") != "healthy":
            continue
        raw_path = root / "data" / "raw" / "etf_pcf" / code / f"{data_date}.json"
        if not raw_path.exists():
            _json_dump(raw_path, snapshot)
    processed = root / "data" / "processed" / "etf_radar" / data_date / "positions.json"
    _json_dump(processed, day)
    return processed


def load_snapshot_days(root: Path, *, through: str | None = None) -> list[dict[str, Any]]:
    base = root / "data" / "processed" / "etf_radar"
    if not base.exists():
        return []
    days: dict[str, dict[str, Any]] = {}
    for path in sorted(base.glob("*/positions.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        data_date = str(value.get("data_date") or "")
        if data_date and (through is None or data_date <= through):
            days[data_date] = value
    return [days[key] for key in sorted(days)]


def _aum_medians(days: list[dict[str, Any]], lookback: int = 20) -> dict[str, float]:
    medians: dict[str, float] = {}
    for source in ETF_SOURCES:
        values = []
        for day in days[-lookback:]:
            snapshot = (day.get("snapshots") or {}).get(source.code) or {}
            if snapshot.get("status") == "healthy" and snapshot.get("aum") is not None:
                values.append(float(snapshot["aum"]))
        if values:
            medians[source.code] = median(values)
    return medians


def _weight_ranking(values: dict[str, float]) -> list[str]:
    return sorted(values, key=lambda code: (-values[code], code))


def _computed_weights(aum_medians: dict[str, float]) -> dict[str, float]:
    roots = {code: math.sqrt(value) for code, value in aum_medians.items() if value > 0}
    total = sum(roots.values())
    return {code: value / total for code, value in roots.items()} if total else {}


def _last_history_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last


def choose_radar_weights(
    days: list[dict[str, Any]], *, data_date: str, history_path: Path
) -> tuple[str, dict[str, float], dict[str, float], bool]:
    medians = _aum_medians(days)
    computed = _computed_weights(medians)
    ranking = _weight_ranking(medians)
    last = _last_history_record(history_path)
    month = data_date[:7]
    if last:
        previous_medians = {
            str(key): float(value) for key, value in (last.get("aum_medians") or {}).items()
        }
        previous_ranking = _weight_ranking(previous_medians)
        if str(last.get("weight_month") or "") == month and previous_ranking == ranking:
            weights = {str(key): float(value) for key, value in (last.get("weights") or {}).items()}
            if weights:
                return str(last.get("weight_version") or month), weights, medians, len(days) < 20
    suffix = "-rank-change" if last and str(last.get("weight_month") or "") == month else ""
    return f"{month}{suffix}", computed, medians, len(days) < 20


def _positions(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if snapshot.get("status") != "healthy":
        return {}
    return {
        str(item["stock_id"]): item
        for item in snapshot.get("positions", [])
        if item.get("stock_id")
    }


def _tail_state(weights: list[float], config: dict[str, Any]) -> bool:
    decline = config["exclude_decline_days"]
    window = int(decline["window"])
    recent = weights[-window:]
    if len(recent) == window:
        declines = sum(current < previous for previous, current in zip(recent, recent[1:]))
        if declines >= int(decline["min_declines"]):
            return True
    if len(weights) >= 6 and weights[-6] > 0:
        return weights[-1] / weights[-6] - 1 <= -float(config["exclude_drop_5d"])
    return False


def _pair_series(
    days: list[dict[str, Any]], code: str, stock_id: str, config: dict[str, Any]
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    comparable_weights: list[float] = []
    consecutive = 0
    armed = False
    needs_rearm = False
    stable_low_days = 0
    active_turn = False
    previous_qualifying_low = False
    previous_weight: float | None = None
    previous_event: str | None = None
    low_limit = float(config["low_position_max_weight"])
    warmup = int(config["warmup_trading_days"])

    for day in days:
        snapshot = (day.get("snapshots") or {}).get(code) or {}
        healthy = snapshot.get("status") == "healthy"
        position = _positions(snapshot).get(stock_id) if healthy else None
        if not healthy:
            points.append(
                {
                    "date": day["data_date"],
                    "state": "missing",
                    "event": None,
                    "weight": None,
                    "shares": None,
                    "pos_5d": None,
                }
            )
            # Lifecycle is frozen, but comparisons cannot bridge the disclosure gap.
            comparable_weights = []
            consecutive = 0
            previous_qualifying_low = False
            previous_weight = None
            previous_event = None
            stable_low_days = 0
            continue

        weight = float(position.get("weight") or 0.0) if position else 0.0
        shares = int(position.get("shares") or 0) if position else 0
        comparable_weights.append(weight)
        consecutive += 1
        pos_5d = None
        if len(comparable_weights) >= 6 and comparable_weights[-6] > 0:
            pos_5d = weight / comparable_weights[-6] - 1
        warm = consecutive > warmup
        tail = weight > 0 and _tail_state(comparable_weights, config)
        residual = bool(
            weight > 0
            and config.get("require_round_lot", True)
            and shares % 1000 != 0
        )
        is_low = 0 < weight <= low_limit and not residual and not tail
        event = None

        if weight == 0:
            internal_state = "unheld"
            active_turn = False
            armed = False
            needs_rearm = True
            stable_low_days = 0
        elif tail:
            internal_state = "decline_tail"
            active_turn = False
            armed = False
            needs_rearm = True
            stable_low_days = 0
        elif residual:
            internal_state = "residual"
            previous_qualifying_low = False
        else:
            increase = (
                weight / previous_weight - 1
                if previous_weight is not None and previous_weight > 0
                else None
            )
            can_start = (
                warm
                and previous_qualifying_low
                and armed
                and increase is not None
                and increase >= float(config["boost_min_increase"])
            )
            can_confirm = (
                warm
                and previous_event == "start"
                and previous_weight is not None
                and weight > previous_weight
            )
            if can_confirm:
                internal_state = "confirm"
                event = "confirm"
                active_turn = True
            elif can_start:
                internal_state = "start"
                event = "start"
                active_turn = True
            elif active_turn:
                internal_state = "post_turn"
            elif is_low:
                non_decline = previous_weight is None or weight >= previous_weight
                stable_low_days = stable_low_days + 1 if non_decline else 0
                if needs_rearm:
                    armed = stable_low_days >= int(config.get("confirm_consecutive_days", 2))
                    if armed:
                        needs_rearm = False
                    internal_state = "stopped" if armed else "low"
                else:
                    armed = True
                    internal_state = "low"
            else:
                internal_state = "non_low"

        state = internal_state if warm else "missing"
        points.append(
            {
                "date": day["data_date"],
                "state": state,
                "event": event if warm else None,
                "weight": weight,
                "shares": shares,
                "pos_5d": pos_5d if warm else None,
            }
        )
        previous_qualifying_low = is_low and internal_state in {"low", "stopped"}
        previous_weight = weight
        previous_event = event if warm else None
    return points


def _stock_universe(days: list[dict[str, Any]]) -> tuple[set[str], dict[str, str]]:
    universe: set[str] = set()
    names: dict[str, str] = {}
    for day in days:
        for snapshot in (day.get("snapshots") or {}).values():
            for position in snapshot.get("positions", []):
                stock_id = str(position.get("stock_id") or "")
                if stock_id:
                    universe.add(stock_id)
                    names[stock_id] = str(position.get("stock_name") or stock_id)
    return universe, names


def _low_start(points: list[dict[str, Any]]) -> str:
    allowed = {"low", "stopped", "start", "confirm", "post_turn"}
    dates = []
    for point in reversed(points):
        if point["state"] not in allowed:
            break
        dates.append(str(point["date"]))
    return dates[-1] if dates else ""


def _fmt_cell(
    point: dict[str, Any], *, contributor: bool
) -> dict[str, Any]:
    if point["state"] == "missing":
        return {"kind": "missing", "text": "缺", "title": "資料不足"}
    shares = int(point.get("shares") or 0)
    lots = shares // 1000
    if contributor and point["state"] in {"start", "confirm", "post_turn", "low", "stopped"}:
        return {"kind": "up", "text": str(lots), "title": PAIR_LABELS[point["state"]]}
    if point["state"] in {"low", "stopped"}:
        return {"kind": "low", "text": str(lots), "title": PAIR_LABELS[point["state"]]}
    title = "未持有" if point["state"] == "unheld" else f"未納入訊號：{PAIR_LABELS[point['state']]}"
    return {"kind": "none", "text": "—", "title": title}


def load_stock_cross_reference(root: Path) -> dict[str, dict[str, Any]]:
    models = (
        ("value", root / "reports" / "latest" / "screening_results.json"),
        ("momentum", root / "reports" / "momentum" / "latest" / "screening_results.json"),
    )
    output: dict[str, dict[str, Any]] = {}
    for label, path in models:
        if not path.exists():
            continue
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for row in result.get("results", []):
            stock_id = str(row.get("stock_id") or "")
            if not stock_id:
                continue
            target = output.setdefault(stock_id, {})
            for key in ("stock_name", "close", "market_value", "avg_daily_turnover"):
                if row.get(key) is not None:
                    target[key] = row[key]
            if row.get("rank") is not None:
                target[f"{label}_rank"] = int(row["rank"])
            if row.get("hard_pass"):
                target[f"{label}_hard_pass"] = True
    return output


def build_radar_result(
    days: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    weights: dict[str, float],
    weight_version: str,
    aum_medians: dict[str, float],
    provisional_weights: bool,
    cross_reference: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not days:
        raise ValueError("ETF radar requires at least one snapshot day")
    cross_reference = cross_reference or {}
    universe, names = _stock_universe(days)
    codes = [source.code for source in ETF_SOURCES]
    issuer_by_code = {source.code: source.issuer for source in ETF_SOURCES}
    source_by_code = {source.code: source for source in ETF_SOURCES}
    series: dict[str, dict[str, list[dict[str, Any]]]] = {
        stock_id: {code: _pair_series(days, code, stock_id, config) for code in codes}
        for stock_id in universe
    }
    window = int(config["resonance_window_days"])
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for stock_id in sorted(universe):
        current = {code: series[stock_id][code][-1] for code in codes}
        event_contributors: dict[str, str] = {}
        event_dates: list[str] = []
        for code in codes:
            if current[code]["state"] in {"missing", "unheld", "decline_tail"}:
                continue
            for point in series[stock_id][code][-window:]:
                if point.get("event") in {"start", "confirm"}:
                    event_contributors[code] = str(point["event"])
                    event_dates.append(str(point["date"]))
        event_issuers = {issuer_by_code[code] for code in event_contributors}
        confirm_codes = [code for code, point in current.items() if point.get("event") == "confirm"]
        start_codes = [code for code, point in current.items() if point.get("event") == "start"]
        low_codes = [code for code, point in current.items() if point["state"] in {"low", "stopped"}]

        if len(event_issuers) >= int(config["resonance_min_issuers"]):
            signal = "跨投信共振"
            contributors = sorted(event_contributors)
        elif confirm_codes:
            signal = "確認布局"
            contributors = confirm_codes
        elif start_codes:
            signal = "開始加碼"
            contributors = start_codes
        elif low_codes:
            signal = "低部位觀察"
            contributors = low_codes
        else:
            signal = ""
            contributors = []

        if signal:
            issuers = {issuer_by_code[code] for code in contributors}
            detail = []
            for code in codes:
                point = current[code]
                detail.append(
                    {
                        "etf_code": code,
                        "issuer": issuer_by_code[code],
                        "radar_weight": weights.get(code),
                        "stock_weight": point.get("weight"),
                        "pos_5d": point.get("pos_5d"),
                        "shares": point.get("shares"),
                        "state": point["state"],
                        "state_label": PAIR_LABELS[point["state"]],
                        "contributor": code in contributors,
                    }
                )
            low_dates = [_low_start(series[stock_id][code]) for code in contributors]
            low_dates = [value for value in low_dates if value]
            meta = cross_reference.get(stock_id, {})
            rows.append(
                {
                    "signal": signal,
                    "stock_id": stock_id,
                    "stock_name": meta.get("stock_name") or names.get(stock_id) or stock_id,
                    "contributors": contributors,
                    "etf_count": len(contributors),
                    "issuer_count": len(issuers),
                    "radar_weight_sum": sum(weights.get(code, 0.0) for code in contributors),
                    "low_start": min(low_dates) if low_dates else "",
                    "last_turn": max(event_dates) if event_dates else "",
                    "close": meta.get("close"),
                    "market_value": meta.get("market_value"),
                    "avg_daily_turnover": meta.get("avg_daily_turnover"),
                    "value_rank": meta.get("value_rank"),
                    "momentum_rank": meta.get("momentum_rank"),
                    "cells": {
                        code: _fmt_cell(current[code], contributor=code in contributors)
                        for code in codes
                    },
                    "details": detail,
                }
            )
            continue

        reasons = sorted(
            {
                PAIR_LABELS[point["state"]]
                for point in current.values()
                if point["state"] in {"missing", "decline_tail", "residual", "non_low"}
            }
        )
        if reasons:
            recent = [
                point for point in current.values() if point.get("weight") is not None and point["weight"] > 0
            ]
            pos5 = [point["pos_5d"] for point in recent if point.get("pos_5d") is not None]
            excluded.append(
                {
                    "stock_id": stock_id,
                    "stock_name": cross_reference.get(stock_id, {}).get("stock_name")
                    or names.get(stock_id)
                    or stock_id,
                    "reasons": reasons,
                    "pos_5d": min(pos5) if pos5 else None,
                }
            )

    rows.sort(
        key=lambda row: (
            SIGNAL_ORDER[row["signal"]],
            -row["radar_weight_sum"],
            -row["issuer_count"],
            row["low_start"] or "9999-99-99",
            row["stock_id"],
        )
    )
    excluded.sort(key=lambda row: (row["reasons"], row["stock_id"]))
    latest = days[-1]
    code_order = sorted(codes, key=lambda code: (-weights.get(code, 0.0), code))
    return {
        "metadata": {
            "data_date": latest["data_date"],
            "requested_as_of": latest.get("requested_as_of"),
            "coverage": latest.get("coverage"),
            "history_days": len(days),
            "warmup_trading_days": int(config["warmup_trading_days"]),
            "config_version": config["version"],
            "weight_version": weight_version,
            "weights_provisional": provisional_weights,
            "etf_order": code_order,
            "weights": weights,
            "aum_medians": aum_medians,
            "sources": {
                code: {
                    "name": source_by_code[code].name,
                    "issuer": source_by_code[code].issuer,
                    "url": source_by_code[code].url,
                    "status": latest["snapshots"][code]["status"],
                    "error": latest["snapshots"][code].get("error") or "",
                }
                for code in codes
            },
        },
        "rows": rows,
        "excluded": excluded,
    }


def append_radar_history(path: Path, result: dict[str, Any]) -> bool:
    meta = result["metadata"]
    record = {
        "data_date": meta["data_date"],
        "config_version": meta["config_version"],
        "weight_month": str(meta["data_date"])[:7],
        "weight_version": meta["weight_version"],
        "weights": meta["weights"],
        "aum_medians": meta["aum_medians"],
        "coverage": meta["coverage"],
        "signals": [
            {
                "stock_id": row["stock_id"],
                "signal": row["signal"],
                "contributors": row["contributors"],
            }
            for row in result["rows"]
        ],
    }
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if path.exists() and encoded in {
        json.dumps(json.loads(line), ensure_ascii=False, sort_keys=True)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded + "\n")
    return True


def run_etf_radar_data(
    root: Path,
    *,
    requested_as_of: date,
    config_path: Path,
    fetcher=fetch_official_snapshots,
) -> dict[str, Any]:
    config = load_etf_radar_config(config_path)
    snapshots = fetcher(requested_as_of=requested_as_of)
    day = normalize_snapshot_day(snapshots, requested_as_of=requested_as_of)
    save_snapshot_day(root, day)
    days = load_snapshot_days(root, through=str(day["data_date"]))
    history_path = root / "data" / "processed" / "etf_radar_history.jsonl"
    version, weights, medians, provisional = choose_radar_weights(
        days, data_date=str(day["data_date"]), history_path=history_path
    )
    result = build_radar_result(
        days,
        config,
        weights=weights,
        weight_version=version,
        aum_medians=medians,
        provisional_weights=provisional,
        cross_reference=load_stock_cross_reference(root),
    )
    append_radar_history(history_path, result)
    return result


def write_radar_result_json(result: dict[str, Any], reports_root: Path) -> dict[str, Path]:
    data_date = str(result["metadata"]["data_date"])
    dated = reports_root / "etf_radar" / data_date
    latest = reports_root / "etf_radar" / "latest"
    dated.mkdir(parents=True, exist_ok=True)
    latest.mkdir(parents=True, exist_ok=True)
    dated_json = dated / "etf_radar.json"
    latest_json = latest / "etf_radar.json"
    _json_dump(dated_json, result)
    shutil.copy2(dated_json, latest_json)
    return {"dated_json": dated_json, "latest_json": latest_json}
