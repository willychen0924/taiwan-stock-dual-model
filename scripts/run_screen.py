#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.config import load_config  # noqa: E402
from value_screener.finmind import load_dotenv  # noqa: E402
from value_screener.momentum import build_momentum_result, load_momentum_config  # noqa: E402
from value_screener.momentum_report import write_momentum_reports  # noqa: E402
from value_screener.pipeline import run_pipeline  # noqa: E402
from value_screener.report import write_reports  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="台股防禦型價值全市場篩選")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "screening.json")
    parser.add_argument(
        "--momentum-config",
        type=Path,
        default=ROOT / "config" / "momentum_screening.json",
    )
    parser.add_argument("--force", action="store_true", help="忽略快取並重新下載")
    parser.add_argument("--include-as-of", action="store_true", help="盤後確認資料完整時納入報表當日")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    config = load_config(args.config)
    result = run_pipeline(
        ROOT,
        config,
        as_of=args.as_of,
        force=args.force,
        include_as_of=args.include_as_of,
    )
    paths = write_reports(result, ROOT / "reports")
    print("[完成] 全市場篩選", flush=True)
    for name, path in paths.items():
        print(f"[輸出] {name}: {path}", flush=True)
    momentum_config = load_momentum_config(args.momentum_config)
    momentum_result = build_momentum_result(result, momentum_config)
    momentum_paths = write_momentum_reports(momentum_result, ROOT / "reports" / "momentum")
    print("[完成] 營運動能篩選", flush=True)
    for name, path in momentum_paths.items():
        print(f"[輸出] momentum_{name}: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
