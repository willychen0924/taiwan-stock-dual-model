#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.history import HISTORY_SCHEMA_VERSION, migrate_history_records  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="以原始報表雜湊驗證後升級排名歷史欄位")
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data" / "processed" / "rankings_history.jsonl",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stats = migrate_history_records(args.history, root=ROOT, dry_run=args.dry_run)
    action = "可升級" if args.dry_run else "已升級"
    print(
        f"[歷史 schema {HISTORY_SCHEMA_VERSION}] {action} {stats['migrated']} 筆｜"
        f"已是新版 {stats['already_current']} 筆｜來源不符 {stats['source_mismatch']} 筆｜"
        f"內容不一致 {stats['inconsistent']} 筆｜總計 {stats['records']} 筆",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
