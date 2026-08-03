from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "universe",
        "hard_gates",
        "liquidation_haircuts",
        "score_targets",
        "weights",
        "report",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"設定缺少區塊: {', '.join(sorted(missing))}")

    weights = config["weights"]
    total = sum(float(weights[name]) for name in ("defense", "valuation", "momentum"))
    if abs(total - 100.0) > 1e-9:
        raise ValueError(f"評分權重合計必須為 100，目前為 {total}")

    haircuts = config["liquidation_haircuts"]
    invalid = {key: value for key, value in haircuts.items() if not 0 <= float(value) <= 1}
    if invalid:
        raise ValueError(f"清算折價必須介於 0 與 1: {invalid}")


def load_manual_review(path: Path) -> dict[str, dict[str, str]]:
    import csv

    if not path.exists():
        return {}
    output: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            stock_id = (row.get("stock_id") or "").strip()
            if stock_id:
                output[stock_id] = {key: (value or "").strip() for key, value in row.items()}
    return output
