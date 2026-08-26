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
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from .etf_radar_sources import (
    ETF_SOURCES,
    fetch_capital_history_snapshots,
    fetch_fuhwa_history_snapshots,
    fetch_goal_star_history_snapshots,
    fetch_official_snapshots,
)


SIGNAL_ORDER = {
    "跨投信共振": 0,
    "確認布局": 1,
    "開始加碼": 2,
    "低部位觀察": 3,
    "待觀察": 4,
}

PAIR_LABELS = {
    "missing": "資料不足",
    "unheld": "未持有",
    "decline_tail": "減碼尾倉",
    "residual": "配股殘留",
    "non_low": "非低部位",
    "cold_low": "待觀察（歷史不足）",
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


def _raw_snapshot_path(
    root: Path, code: str, data_date: str, snapshot: dict[str, Any]
) -> Path:
    suffix = (
        ".json"
        if snapshot.get("provenance", "official") == "official"
        else ".third_party.json"
    )
    return root / "data" / "raw" / "etf_pcf" / code / f"{data_date}{suffix}"


def save_snapshot_day(root: Path, day: dict[str, Any]) -> Path:
    data_date = str(day["data_date"])
    for code, snapshot in day["snapshots"].items():
        if snapshot.get("status") != "healthy":
            continue
        raw_path = _raw_snapshot_path(root, code, data_date, snapshot)
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


def merge_snapshot_day(root: Path, day: dict[str, Any]) -> Path:
    """Add newly available archives without replacing an already healthy snapshot."""

    data_date = str(day["data_date"])
    processed = root / "data" / "processed" / "etf_radar" / data_date / "positions.json"
    if not processed.exists():
        return save_snapshot_day(root, day)
    try:
        merged = json.loads(processed.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return save_snapshot_day(root, day)
    if str(merged.get("data_date") or "") != data_date:
        raise ValueError(f"snapshot date mismatch at {processed}")

    merged_snapshots = merged.setdefault("snapshots", {})
    for code, incoming in day.get("snapshots", {}).items():
        current = merged_snapshots.get(code) or {}
        if incoming.get("status") != "healthy":
            continue
        current_priority = (
            2 if current.get("provenance", "official") == "official" else 1
        )
        incoming_priority = (
            2 if incoming.get("provenance", "official") == "official" else 1
        )
        if current.get("status") == "healthy" and current_priority >= incoming_priority:
            continue
        merged_snapshots[code] = incoming
        raw_path = _raw_snapshot_path(root, code, data_date, incoming)
        if not raw_path.exists():
            _json_dump(raw_path, incoming)
    healthy = sum(
        (merged_snapshots.get(source.code) or {}).get("status") == "healthy"
        for source in ETF_SOURCES
    )
    merged["coverage"] = {"healthy": healthy, "total": len(ETF_SOURCES)}
    _json_dump(processed, merged)
    return processed


def backfill_capital_history(
    root: Path,
    *,
    through_date: date,
    target_trading_days: int = 20,
    fetcher=fetch_capital_history_snapshots,
) -> dict[str, int]:
    """Fill the official 00982A/00992A archive until both have enough history."""

    capital_codes = [source.code for source in ETF_SOURCES if source.adapter == "capital"]
    healthy_dates: dict[str, set[str]] = {code: set() for code in capital_codes}
    for day in load_snapshot_days(root, through=through_date.isoformat()):
        for code in capital_codes:
            snapshot = (day.get("snapshots") or {}).get(code) or {}
            if snapshot.get("status") == "healthy":
                healthy_dates[code].add(str(day["data_date"]))
    if all(len(values) >= target_trading_days for values in healthy_dates.values()):
        return {code: len(values) for code, values in healthy_dates.items()}

    candidate = through_date - timedelta(days=1)
    attempts = 0
    empty_weekdays = 0
    max_attempts = max(30, target_trading_days * 3)
    while (
        not all(len(values) >= target_trading_days for values in healthy_dates.values())
        and attempts < max_attempts
        and empty_weekdays < 6
    ):
        if candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
            continue
        wanted = [
            source
            for source in ETF_SOURCES
            if source.code in capital_codes
            and candidate.isoformat() not in healthy_dates[source.code]
        ]
        if not wanted:
            candidate -= timedelta(days=1)
            continue
        attempts += 1
        snapshots = fetcher(requested_date=candidate, sources=tuple(wanted))
        healthy = [
            snapshot
            for snapshot in snapshots
            if snapshot.get("status") == "healthy"
            and snapshot.get("data_date") == candidate.isoformat()
        ]
        if healthy:
            archive_day = normalize_snapshot_day(healthy, requested_as_of=candidate)
            merge_snapshot_day(root, archive_day)
            for snapshot in healthy:
                code = str(snapshot["etf_code"])
                if code in healthy_dates:
                    healthy_dates[code].add(candidate.isoformat())
            empty_weekdays = 0
        else:
            empty_weekdays += 1
        candidate -= timedelta(days=1)
    return {code: len(values) for code, values in healthy_dates.items()}


def backfill_history_on_known_dates(
    root: Path,
    *,
    through_date: date,
    codes: tuple[str, ...],
    fetcher,
    target_trading_days: int = 20,
    max_calendar_lookback: int | None = None,
) -> dict[str, int]:
    """Fill source-specific archives on trading dates already verified by official PCF."""

    days = load_snapshot_days(root, through=through_date.isoformat())[-target_trading_days:]
    source_by_code = {source.code: source for source in ETF_SOURCES}
    for historical_day in reversed(days):
        data_date = date.fromisoformat(str(historical_day["data_date"]))
        if (
            max_calendar_lookback is not None
            and (through_date - data_date).days > max_calendar_lookback
        ):
            continue
        wanted = []
        for code in codes:
            snapshot = (historical_day.get("snapshots") or {}).get(code) or {}
            if snapshot.get("status") != "healthy":
                wanted.append(source_by_code[code])
        if not wanted:
            continue
        snapshots = fetcher(requested_date=data_date, sources=tuple(wanted))
        healthy = [
            snapshot
            for snapshot in snapshots
            if snapshot.get("status") == "healthy"
            and snapshot.get("data_date") == data_date.isoformat()
        ]
        if healthy:
            archive_day = normalize_snapshot_day(healthy, requested_as_of=data_date)
            merge_snapshot_day(root, archive_day)

    counts = {code: 0 for code in codes}
    for historical_day in load_snapshot_days(
        root, through=through_date.isoformat()
    )[-target_trading_days:]:
        for code in codes:
            snapshot = (historical_day.get("snapshots") or {}).get(code) or {}
            if snapshot.get("status") == "healthy":
                counts[code] += 1
    return counts


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
                samples = {
                    source.code: sum(
                        ((day.get("snapshots") or {}).get(source.code) or {}).get("status")
                        == "healthy"
                        for day in days[-20:]
                    )
                    for source in ETF_SOURCES
                }
                return (
                    str(last.get("weight_version") or month),
                    weights,
                    medians,
                    any(count < 20 for count in samples.values()),
                )
    suffix = "-rank-change" if last and str(last.get("weight_month") or "") == month else ""
    samples = {
        source.code: sum(
            ((day.get("snapshots") or {}).get(source.code) or {}).get("status") == "healthy"
            for day in days[-20:]
        )
        for source in ETF_SOURCES
    }
    return f"{month}{suffix}", computed, medians, any(
        count < 20 for count in samples.values()
    )


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
        below_precision = bool(position and shares > 0 and weight == 0)
        comparable_weights.append(weight)
        consecutive += 1
        pos_5d = None
        if len(comparable_weights) >= 6 and comparable_weights[-6] > 0:
            pos_5d = weight / comparable_weights[-6] - 1
        warm = consecutive > warmup
        tail = weight > 0 and _tail_state(comparable_weights, config)
        residual = bool(
            shares > 0
            and config.get("require_round_lot", True)
            and shares % 1000 != 0
        )
        is_low = (
            (0 < weight <= low_limit or below_precision)
            and not residual
            and not tail
        )
        event = None

        if shares == 0:
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

        if warm:
            state = internal_state
        elif internal_state in {"low", "stopped"}:
            # A single disclosed snapshot can identify a small position, but
            # cannot yet rule out a multi-day selling tail.  Show it without
            # allowing any start/confirm/resonance event during warm-up.
            state = "cold_low"
        else:
            state = internal_state
        points.append(
            {
                "date": day["data_date"],
                "state": state,
                "event": event if warm else None,
                "weight": weight,
                "shares": shares,
                "pos_5d": pos_5d if warm else None,
                "below_precision": below_precision,
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
    allowed = {"cold_low", "low", "stopped", "start", "confirm", "post_turn"}
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
    if contributor and point["state"] in {"start", "confirm", "post_turn"}:
        return {"kind": "up", "text": str(lots), "title": PAIR_LABELS[point["state"]]}
    if point["state"] in {"cold_low", "low", "stopped"}:
        title = (
            "待觀察：官網權重低於揭露精度"
            if point.get("below_precision")
            else PAIR_LABELS[point["state"]]
        )
        return {"kind": "low", "text": str(lots), "title": title}
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
        cold_codes = [code for code, point in current.items() if point["state"] == "cold_low"]

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
        elif cold_codes:
            signal = "待觀察"
            contributors = cold_codes
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
                        "below_precision": point.get("below_precision", False),
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
            -row["etf_count"],
            -row["radar_weight_sum"],
            -row["issuer_count"],
            row["low_start"] or "9999-99-99",
            row["stock_id"],
        )
    )
    watch_signals = {"低部位觀察", "待觀察"}
    observation_rows = [row for row in rows if row["signal"] in watch_signals]
    active_rows = [row for row in rows if row["signal"] not in watch_signals]
    candidate_limit = int(config.get("observation_candidate_limit", 15))
    rows = active_rows + observation_rows[:candidate_limit]
    excluded.sort(key=lambda row: (row["reasons"], row["stock_id"]))
    latest = days[-1]
    code_order = sorted(codes, key=lambda code: (-weights.get(code, 0.0), code))
    history_days_by_etf = {}
    history_provenance_by_etf = {}
    for code in codes:
        consecutive = 0
        for day in reversed(days):
            snapshot = (day.get("snapshots") or {}).get(code) or {}
            if snapshot.get("status") != "healthy":
                break
            consecutive += 1
        history_days_by_etf[code] = consecutive
        history_provenance_by_etf[code] = sorted(
            {
                str(snapshot.get("provenance") or "official")
                for day in days
                for snapshot in [(day.get("snapshots") or {}).get(code) or {}]
                if snapshot.get("status") == "healthy"
            }
        )
    return {
        "metadata": {
            "data_date": latest["data_date"],
            "requested_as_of": latest.get("requested_as_of"),
            "coverage": latest.get("coverage"),
            "history_days": len(days),
            "history_days_by_etf": history_days_by_etf,
            "history_provenance_by_etf": history_provenance_by_etf,
            "warmup_trading_days": int(config["warmup_trading_days"]),
            "primary_observation_limit": int(config.get("low_observation_limit", 10)),
            "observation_candidate_limit": candidate_limit,
            "observation_pool_count": len(observation_rows),
            "observation_omitted_count": max(0, len(observation_rows) - candidate_limit),
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
    history_fetcher=fetch_capital_history_snapshots,
    fuhwa_history_fetcher=fetch_fuhwa_history_snapshots,
    fallback_history_fetcher=fetch_goal_star_history_snapshots,
) -> dict[str, Any]:
    config = load_etf_radar_config(config_path)
    snapshots = fetcher(requested_as_of=requested_as_of)
    day = normalize_snapshot_day(snapshots, requested_as_of=requested_as_of)
    save_snapshot_day(root, day)
    backfill_capital_history(
        root,
        through_date=date.fromisoformat(str(day["data_date"])),
        target_trading_days=20,
        fetcher=history_fetcher,
    )
    backfill_history_on_known_dates(
        root,
        through_date=date.fromisoformat(str(day["data_date"])),
        codes=("00991A",),
        fetcher=fuhwa_history_fetcher,
    )
    backfill_history_on_known_dates(
        root,
        through_date=date.fromisoformat(str(day["data_date"])),
        codes=tuple(source.code for source in ETF_SOURCES),
        fetcher=fallback_history_fetcher,
        max_calendar_lookback=10,
    )
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
