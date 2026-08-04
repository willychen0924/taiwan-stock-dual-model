#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.config import load_manual_review  # noqa: E402
from value_screener.weekly_report import completed_week_window, load_history, write_weekly_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="從排名歷史產生雙模型週報")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--week-ending", type=date.fromisoformat)
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "processed" / "rankings_history.jsonl",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_history(args.history)
    if args.week_ending:
        week_end = args.week_ending
        week_start = week_end - timedelta(days=week_end.weekday())
        week_end = week_start + timedelta(days=4)
    else:
        try:
            week_start, week_end = completed_week_window(records, as_of=args.as_of)
        except ValueError as exc:
            print(f"[週報略過] {exc}", flush=True)
            return 0
    paths = write_weekly_report(
        records,
        ROOT / "reports",
        week_start=week_start,
        week_end=week_end,
        manual_review=load_manual_review(ROOT / "config" / "manual_review.csv"),
    )
    for name, path in paths.items():
        print(f"[週報] {name}: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
