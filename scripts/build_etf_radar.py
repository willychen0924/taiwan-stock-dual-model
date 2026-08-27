#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.etf_radar import run_etf_radar_data, write_radar_result_json  # noqa: E402
from value_screener.etf_radar_report import write_etf_radar_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立主動式 ETF 低部位轉向雷達")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "etf_radar.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_etf_radar_data(
        ROOT,
        requested_as_of=args.as_of,
        config_path=args.config,
    )
    paths = {
        **write_radar_result_json(result, ROOT / "reports"),
        **write_etf_radar_report(result, ROOT / "reports"),
    }
    coverage = result["metadata"]["coverage"]
    print(
        f'[完成] ETF 雷達：揭露 {coverage["healthy"]}/{coverage["total"]}，'
        f'資料日 {result["metadata"]["data_date"]}',
        flush=True,
    )
    for name, path in paths.items():
        print(f"[輸出] etf_radar_{name}: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
