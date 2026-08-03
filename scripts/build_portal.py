#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.combined_report import write_combined_report  # noqa: E402
from value_screener.enrichment import load_enrichment  # noqa: E402


def main() -> int:
    value = json.loads((ROOT / "reports" / "latest" / "screening_results.json").read_text(encoding="utf-8"))
    momentum = json.loads((ROOT / "reports" / "momentum" / "latest" / "screening_results.json").read_text(encoding="utf-8"))
    as_of = str(value["metadata"]["as_of"])
    paths = write_combined_report(
        value,
        momentum,
        ROOT / "reports",
        enrichment=load_enrichment(ROOT, as_of),
        history_path=ROOT / "data" / "processed" / "rankings_history.jsonl",
        weekly_available=(ROOT / "reports" / "weekly" / "latest" / "index.html").exists(),
    )
    for name, path in paths.items():
        print(f"[入口] {name}: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
