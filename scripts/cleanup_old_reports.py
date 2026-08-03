#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.retention import cleanup_dated_directories, iter_expired_dated_directories  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刪除超過保留天數的日報目錄")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--keep-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    roots = [
        ROOT / "reports",
        ROOT / "reports" / "momentum",
        ROOT / "outputs",
        ROOT / "qa",
    ]

    if args.dry_run:
        deleted: list[Path] = []
        for root in roots:
            deleted.extend(iter_expired_dated_directories(root, as_of=args.as_of, keep_days=args.keep_days))
    else:
        deleted = cleanup_dated_directories(roots, as_of=args.as_of, keep_days=args.keep_days)

    if not deleted:
        print("[保留] 沒有超過保留期限的日報目錄", flush=True)
        return 0

    action = "將刪除" if args.dry_run else "刪除"
    for path in deleted:
        print(f"[{action}] {path.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
