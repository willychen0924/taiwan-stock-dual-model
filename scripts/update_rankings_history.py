#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.history import append_history_records  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="將模型排名報表附加至可稽核歷史 JSONL")
    parser.add_argument("--backfill", action="store_true", help="回填所有現存日期報表")
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "processed" / "rankings_history.jsonl",
    )
    return parser.parse_args()


def dated_reports() -> list[Path]:
    value_reports = sorted((ROOT / "reports").glob("20??-??-??/screening_results.json"))
    momentum_reports = sorted((ROOT / "reports" / "momentum").glob("20??-??-??/screening_results.json"))
    return sorted([*value_reports, *momentum_reports], key=lambda path: (path.parent.name, str(path)))


def latest_reports() -> list[Path]:
    return [
        ROOT / "reports" / "latest" / "screening_results.json",
        ROOT / "reports" / "momentum" / "latest" / "screening_results.json",
    ]


def main() -> int:
    args = parse_args()
    report_paths = dated_reports() if args.backfill else latest_reports()
    missing = [path for path in report_paths if not path.exists()]
    if missing:
        labels = "、".join(str(path.relative_to(ROOT)) for path in missing)
        raise FileNotFoundError(f"缺少排名報表：{labels}")
    if not report_paths:
        raise FileNotFoundError("沒有可寫入排名歷史的日期報表")

    appended = append_history_records(args.history, report_paths, root=ROOT)
    print(f"[排名歷史] 掃描 {len(report_paths)} 份報表，新增 {len(appended)} 份", flush=True)
    for record in appended:
        eligibility = "有效" if record["eligible_for_backtest"] else "不納入回測"
        print(
            f"[排名歷史] {record['as_of']} {record['model_id']} "
            f"市場日 {record['latest_market_date']}｜{eligibility}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
