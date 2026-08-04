#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.finmind import FinMindClient, FinMindError, load_dotenv  # noqa: E402
from value_screener.technical_chip import (  # noqa: E402
    DAILY_FIELDS,
    WEEKLY_FIELDS,
    analyze_chip,
    analyze_technical,
    build_daily_master,
    rows_through,
    top_stock_universe,
    write_csv,
    write_summary,
)


DATASETS = {
    "price": "TaiwanStockPrice",
    "institutional": "TaiwanStockInstitutionalInvestorsBuySell",
    "shareholding": "TaiwanStockShareholding",
    "margin": "TaiwanStockMarginPurchaseShortSale",
    "holding": "TaiwanStockHoldingSharesPer",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="為兩模型前N名產生FinMind技術面與籌碼面短評")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--top-n", type=int, default=5, help="每個模型取前N名，重複股票只抓一次")
    parser.add_argument("--force", action="store_true", help="忽略個股資料快取")
    return parser.parse_args()


def load_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_optional(
    client: FinMindClient,
    dataset: str,
    *,
    stock_id: str,
    start_date: str,
    end_date: str,
    force: bool,
) -> list[dict[str, Any]]:
    try:
        rows = client.fetch(
            dataset,
            start_date=start_date,
            end_date=end_date,
            data_id=stock_id,
            force=force,
            max_age_hours=12,
            cache_tag="enrichment",
        )
    except (FinMindError, OSError, ValueError) as exc:
        print(f"[技術籌碼][警告] {stock_id} {dataset}: {exc}", flush=True)
        return []
    time.sleep(0.15)
    return rows


def main() -> int:
    args = parse_args()
    if args.top_n < 1:
        raise ValueError("--top-n 必須至少為 1")
    load_dotenv(ROOT / ".env")
    value_result = load_result(ROOT / "reports" / "latest" / "screening_results.json")
    momentum_result = load_result(ROOT / "reports" / "momentum" / "latest" / "screening_results.json")
    report_as_of = str(value_result["metadata"]["as_of"])
    if report_as_of != args.as_of.isoformat() or str(momentum_result["metadata"]["as_of"]) != report_as_of:
        raise ValueError(f"最新兩份報表日不是 {args.as_of.isoformat()}，拒絕寫入錯誤日期的 enrichment")
    market_dates = {
        str(value_result["metadata"].get("latest_market_date") or ""),
        str(momentum_result["metadata"].get("latest_market_date") or ""),
    }
    if len(market_dates) != 1 or "" in market_dates:
        raise ValueError("兩模型市場資料日不一致，不能共用技術籌碼短評")
    market_date = date.fromisoformat(next(iter(market_dates)))
    start_date = (market_date - timedelta(days=240)).isoformat()
    end_date = market_date.isoformat()

    stock_ids, selection = top_stock_universe(value_result, momentum_result, top_n=args.top_n)
    client = FinMindClient(os.environ.get("FINMIND_TOKEN", ""), ROOT / "data" / "raw")
    output_root = ROOT / "data" / "processed" / "enrichment" / report_as_of
    stocks: dict[str, Any] = {}
    for index, stock_id in enumerate(stock_ids, start=1):
        label = selection[stock_id]["stock_name"]
        print(f"[技術籌碼] {index}/{len(stock_ids)} {stock_id} {label}", flush=True)
        raw_sources = {
            key: fetch_optional(
                client,
                dataset,
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                force=args.force,
            )
            for key, dataset in DATASETS.items()
        }
        sources = {
            key: rows_through(rows, market_date.isoformat())
            for key, rows in raw_sources.items()
        }
        technical = analyze_technical(sources["price"])
        chip = analyze_chip(
            sources["institutional"],
            sources["shareholding"],
            sources["margin"],
            sources["holding"],
        )
        stock_dir = output_root / stock_id
        write_csv(
            stock_dir / "日主表.csv",
            DAILY_FIELDS,
            build_daily_master(
                sources["price"], sources["institutional"], sources["shareholding"], sources["margin"]
            ),
        )
        write_csv(stock_dir / "週持股表.csv", WEEKLY_FIELDS, sorted(sources["holding"], key=lambda row: str(row.get("date") or "")))
        stocks[stock_id] = {
            "stock_name": label,
            "models": selection[stock_id]["models"],
            "technical": technical,
            "chip": chip,
            "source_date": max(str(technical.get("data_date") or ""), str(chip.get("data_date") or "")),
            "files": {
                "daily": str((stock_dir / "日主表.csv").relative_to(ROOT)),
                "weekly_holding": str((stock_dir / "週持股表.csv").relative_to(ROOT)),
            },
        }

    payload = {
        "schema_version": 1,
        "as_of": report_as_of,
        "market_date": market_date.isoformat(),
        "scope": {
            "top_n_per_model": args.top_n,
            "unique_stock_count": len(stock_ids),
            "stock_ids": stock_ids,
        },
        "disclaimer": "技術面與籌碼面只供研究呈現，不進入模型分數、硬門檻或排名。",
        "stocks": stocks,
    }
    summary_path = output_root / "technical_chip_summary.json"
    write_summary(summary_path, payload)
    print(f"[技術籌碼] 完成 {len(stock_ids)} 檔: {summary_path.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
