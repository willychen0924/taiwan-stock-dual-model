#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="盤點轉機觀察公司的可用訊號，不改動模型排名")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "reports" / "momentum" / "latest" / "screening_results.json",
    )
    return parser.parse_args()


def coverage(rows: list[dict[str, Any]], key: str) -> tuple[int, float]:
    count = sum(row.get(key) is not None for row in rows)
    return count, count / len(rows) if rows else 0.0


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = [row for row in payload["results"] if row.get("momentum_bucket") == "轉機觀察"]
    keys = [
        "revenue_3m_yoy",
        "latest_revenue_yoy",
        "revenue_acceleration",
        "ttm_net_income_growth",
        "ttm_operating_margin",
        "ttm_operating_margin_change",
        "cash_conversion",
    ]
    print(f"[轉機訊號] 轉機觀察 {len(rows)} 檔", flush=True)
    for key in keys:
        count, ratio = coverage(rows, key)
        print(f"[轉機訊號] {key}: {count}/{len(rows)} ({ratio:.1%})", flush=True)
    complete_keys = [
        "revenue_3m_yoy",
        "latest_revenue_yoy",
        "revenue_acceleration",
        "ttm_operating_margin_change",
        "cash_conversion",
    ]
    complete = sum(all(row.get(key) is not None for key in complete_keys) for row in rows)
    net_margin = sum(
        row.get("ttm_net_income") is not None and row.get("ttm_revenue") not in (None, 0)
        for row in rows
    )
    print(f"[轉機訊號] 除淨利成長外五項全齊: {complete}/{len(rows)} ({complete / len(rows) if rows else 0:.1%})", flush=True)
    print(f"[轉機訊號] 可計算TTM淨利率: {net_margin}/{len(rows)} ({net_margin / len(rows) if rows else 0:.1%})", flush=True)
    print("[轉機訊號] 僅供軌道設計；未改動 total_score、hard_pass 或排名。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
