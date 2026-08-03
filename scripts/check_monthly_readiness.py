#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.weekly_report import (  # noqa: E402
    MODEL_LABELS,
    last_eligible_by_market_date,
    load_history,
    longest_version_segment,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="檢查前一個完整月份是否足以產生可比較月報")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "processed" / "rankings_history.jsonl",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config" / "reporting_policy.json",
    )
    return parser.parse_args()


def previous_month_window(as_of: date) -> tuple[date, date]:
    first_this_month = as_of.replace(day=1)
    previous_end = date.fromordinal(first_this_month.toordinal() - 1)
    return previous_end.replace(day=1), previous_end


def main() -> int:
    args = parse_args()
    records = load_history(args.history)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))["monthly"]
    minimum_valid = int(policy["min_valid_market_days_per_model"])
    minimum_segment = int(policy["min_same_version_days_per_model"])
    month_start, month_end = previous_month_window(args.as_of)
    all_ready = True
    print(f"[月報檢查] {month_start}～{month_end}", flush=True)
    for model_id, label in MODEL_LABELS.items():
        selected, invalid = last_eligible_by_market_date(
            records,
            model_id=model_id,
            week_start=month_start,
            week_end=month_end,
        )
        longest, segments = longest_version_segment(selected)
        ready = len(selected) >= minimum_valid and len(longest) >= minimum_segment
        all_ready = all_ready and ready
        print(
            f"[月報檢查] {label}：有效 {len(selected)} 日／失效 {len(invalid)} 日／"
            f"最長同版本 {len(longest)} 日／版本區段 {len(segments)}｜{'READY' if ready else 'NOT_READY'}",
            flush=True,
        )
    print(
        f"[月報檢查] 門檻：每模型至少 {minimum_valid} 個有效市場日，且最長同版本區間至少 {minimum_segment} 日",
        flush=True,
    )
    return 0 if all_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
