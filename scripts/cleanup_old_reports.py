#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.retention import cleanup_dated_directories_by_root  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刪除超過保留天數的日報目錄")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "retention.json",
        help="各輸出目錄的保留日數設定",
    )
    parser.add_argument("--keep-days", type=int, help="相容用：暫時覆寫所有目錄的保留日數")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_policy = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(raw_policy, dict) or not raw_policy:
        raise ValueError("保留期設定必須是非空白 JSON 物件")
    policy: dict[Path, int] = {}
    for relative, configured_days in raw_policy.items():
        keep_days = args.keep_days if args.keep_days is not None else int(configured_days)
        if keep_days < 1:
            raise ValueError(f"{relative} 的保留日數必須至少為 1")
        policy[ROOT / str(relative)] = keep_days

    deleted = cleanup_dated_directories_by_root(policy, as_of=args.as_of, dry_run=args.dry_run)

    if not deleted:
        print("[保留] 沒有超過保留期限的日報目錄", flush=True)
        return 0

    action = "將刪除" if args.dry_run else "刪除"
    for path in deleted:
        print(f"[{action}] {path.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
