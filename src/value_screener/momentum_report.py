from __future__ import annotations

import csv
import html
import json
import shutil
from pathlib import Path
from typing import Any

from .report_common import (
    build_checks_panel,
    build_freshness_banner,
    format_rank_change,
    load_rank_comparison,
    rank_comparison_note,
)


MOMENTUM_CSV_FIELDS = [
    "rank",
    "funnel_stage",
    "momentum_bucket",
    "stock_id",
    "stock_name",
    "industry",
    "market",
    "hard_pass",
    "total_score",
    "operating_momentum_score",
    "quality_score",
    "valuation_liquidity_score",
    "market_date",
    "close",
    "market_value",
    "avg_daily_turnover",
    "per",
    "pbr",
    "revenue_3m_yoy",
    "latest_revenue_yoy",
    "previous_revenue_3m_yoy",
    "revenue_acceleration",
    "ttm_net_income",
    "prior_ttm_net_income",
    "ttm_net_income_growth",
    "ttm_operating_margin",
    "prior_ttm_operating_margin",
    "ttm_operating_margin_change",
    "profitable_years",
    "complete_profit_years",
    "positive_fcf_years",
    "cash_conversion",
    "liabilities_ratio",
    "net_cash_ratio",
    "sector_per_percentile",
    "sector_pbr_percentile",
    "sector_margin_percentile",
    "model_summary",
    "governance_status",
    "catalyst",
    "manual_notes",
    "exclusion_reasons",
    "missing_flags",
]


def _format_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def _format_percent(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1%}"


def write_momentum_reports(
    result: dict[str, Any],
    reports_root: Path,
    *,
    history_path: Path | None = None,
) -> dict[str, Path]:
    as_of = result["metadata"]["as_of"]
    dated_dir = reports_root / as_of
    latest_dir = reports_root / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    json_path = dated_dir / "screening_results.json"
    csv_path = dated_dir / "screening_results.csv"
    html_path = dated_dir / "screening_report.html"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOMENTUM_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["results"])
    html_path.write_text(_build_momentum_html(result, history_path=history_path), encoding="utf-8")

    for source in (json_path, csv_path, html_path):
        shutil.copy2(source, latest_dir / source.name)
    return {"json": json_path, "csv": csv_path, "html": html_path}


def _build_momentum_html(result: dict[str, Any], *, history_path: Path | None = None) -> str:
    meta = result["metadata"]
    comparison = load_rank_comparison(result, history_path)
    focus = [row for row in result["results"] if row["hard_pass"]][: result["config"]["report"]["focus_size"]]
    rows = []
    for row in focus:
        rows.append(
            "<tr>"
            f"<td>{row['rank']}</td>"
            f"<td class=\"rank-change\">{format_rank_change(row, comparison)}</td>"
            f"<td><strong>{html.escape(row['stock_id'])}</strong></td>"
            f"<td>{html.escape(row['stock_name'])}</td>"
            f"<td>{html.escape(row['industry'])}</td>"
            f"<td>{_format_number(row['total_score'])}</td>"
            f"<td>{_format_percent(row['revenue_3m_yoy'])}</td>"
            f"<td>{_format_percent(row['revenue_acceleration'])}</td>"
            f"<td>{_format_percent(row['ttm_net_income_growth'])}</td>"
            f"<td>{_format_percent(row['ttm_operating_margin_change'])}</td>"
            f"<td class=\"summary\">{html.escape(row['model_summary'])}</td>"
            "</tr>"
        )
    freshness = build_freshness_banner(meta)
    checks_panel = build_checks_panel(result.get("checks", []))
    comparison_note = rank_comparison_note(comparison)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股高品質營運動能篩選｜{html.escape(meta['as_of'])}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif;margin:0;background:#f3f7f4;color:#17302a}}
.wrap{{max-width:1380px;margin:0 auto;padding:32px}} .hero{{background:#173f35;color:white;border-radius:18px;padding:28px 32px}}
.hero h1{{margin:0 0 8px;font-size:28px}} .hero p{{margin:0;color:#cbe2d9}} .cards{{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin:18px 0}}
.freshness{{margin-top:14px;padding:10px 14px;border-radius:10px;font-size:14px;font-weight:650}} .freshness.good{{background:#dcfce7;color:#14532d}} .freshness.bad{{background:#fee2e2;color:#991b1b}}
.card{{background:white;border-radius:14px;padding:18px;box-shadow:0 2px 14px #153d3014}} .card b{{display:block;font-size:24px;color:#b45309}} .card span{{font-size:13px;color:#64748b}}
.panel{{background:white;border-radius:14px;padding:20px;margin-top:18px;overflow:auto;box-shadow:0 2px 14px #153d3014}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th{{background:#173f35;color:white;text-align:left;padding:10px;white-space:nowrap}} td{{padding:9px 10px;border-bottom:1px solid #e4ece8;white-space:nowrap}}
td.summary,td.check-note{{min-width:24rem;white-space:normal;line-height:1.6}} td.rank-change{{font-weight:700}} tr:hover td{{background:#fffbeb}} .copy{{line-height:1.8;color:#40564f}} .copy h3{{color:#b45309;margin-bottom:6px}} .copy ol{{padding-left:22px}}
.status{{display:inline-block;padding:3px 9px;border-radius:999px;font-weight:750}} .status.ok{{background:#dcfce7;color:#166534}} .status.warn{{background:#fef3c7;color:#92400e}} .status.fail{{background:#fee2e2;color:#991b1b}}
.note{{margin-top:18px;color:#526174;font-size:13px;line-height:1.7}} @media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}.wrap{{padding:16px}}}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><h1>台股高品質營運動能篩選</h1><p>市場資料 {html.escape(meta['latest_market_date'])}｜營收期 {html.escape(meta['latest_revenue_period'])}｜財報季 {html.escape(meta['latest_financial_quarter'])}｜研究候選，不是買進建議</p>{freshness}</div>
<div class="cards">
<div class="card"><b>{meta['universe_count']:,}</b><span>普通股母體</span></div><div class="card"><b>{meta['hard_pass_count']:,}</b><span>動能門檻通過</span></div>
<div class="card"><b>{meta['watchlist_count']:,}</b><span>觀察前100</span></div><div class="card"><b>{meta['focus_count']:,}</b><span>精華20</span></div>
<div class="card"><b>{meta['turnaround_count']:,}</b><span>轉機觀察</span></div><div class="card"><b>{meta['insufficient_history_count']:,}</b><span>前期資料不足</span></div><div class="card"><b>{html.escape(meta['model_status'])}</b><span>模型狀態</span></div>
</div>
<div class="panel"><h2>營運動能精華候選</h2><p class="note">{comparison_note}</p><table><thead><tr><th>排名</th><th>較前次</th><th>代碼</th><th>公司</th><th>產業</th><th>總分</th><th>近3月營收</th><th>營收加速度</th><th>TTM淨利成長</th><th>營益率變化</th><th>模型短評（自動）</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{checks_panel}
<div class="panel copy"><h2>模型說明</h2><h3>核心概念</h3><p>本模型以高品質營運動能為核心，尋找營收、獲利與營益率正在改善，而且成長能獲得現金流與財務體質支持的公司。模型關注企業營運是否加速，而不是短期股價上漲；單月暴增、低基期轉盈及一次性收益須另行覆核。</p>
<h3>篩選流程</h3><ol><li>建立上市、上櫃四位數普通股母體，金融業獨立處理。</li><li>確認最近六個月營收、至少三年財報與20日均成交額5,000萬元。</li><li>要求TTM淨利為正，並排除重大負債異常及人工否決公司。</li><li>營運動能占60分，評估營收、營收加速度、淨利與營益率改善。</li><li>動能品質占25分，檢視獲利、現金流、現金轉換與負債安全。</li><li>估值與流動性占15分，比較同業PER、PBR與成交金額。</li><li>依總分形成觀察前100與精華20。</li><li>最後人工查證成長來源、治理風險、低基期及一次性因素。</li></ol></div>
<p class="note">營運動能分數只負責縮小研究範圍。排名不是預期報酬或買進建議；治理、競爭優勢與成長延續性仍須以年報、法說及公開資訊查證。</p>
</div></body></html>"""
