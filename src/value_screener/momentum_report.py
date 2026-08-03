from __future__ import annotations

import csv
import html
import json
import shutil
from pathlib import Path
from typing import Any

from .report_common import (
    build_monitor_status,
    format_rank_change,
    load_rank_comparison,
    monitor_report_css,
    rank_comparison_note,
    score_composition_bar,
    sortable_cell,
    sortable_table_script,
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
    enrichment: dict[str, dict[str, str]] | None = None,
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
    html_path.write_text(
        _build_momentum_html(result, history_path=history_path, enrichment=enrichment),
        encoding="utf-8",
    )

    for source in (json_path, csv_path, html_path):
        shutil.copy2(source, latest_dir / source.name)
    return {"json": json_path, "csv": csv_path, "html": html_path}


def _momentum_row_html(
    row: dict[str, Any],
    comparison: dict[str, Any],
    enrichment: dict[str, dict[str, str]],
) -> str:
    stock_id = str(row["stock_id"])
    extra = enrichment.get(stock_id, {})
    change = format_rank_change(row, comparison)
    composition = score_composition_bar(
        [
            ("營運動能", row.get("operating_momentum_score"), "score-operating"),
            ("動能品質", row.get("quality_score"), "score-quality"),
            ("估值流動性", row.get("valuation_liquidity_score"), "score-momentum-valuation"),
        ]
    )
    row_id = f"momentum-{stock_id}"
    main = f'<tr data-row-id="{html.escape(row_id, quote=True)}">' + "".join(
        [
            sortable_cell(str(row["rank"]), row["rank"]),
            sortable_cell(html.escape(change), change, css_class="rank-change"),
            sortable_cell(f"<strong>{html.escape(stock_id)}</strong>", stock_id),
            sortable_cell(html.escape(str(row.get("stock_name") or "")), row.get("stock_name")),
            sortable_cell(html.escape(str(row.get("industry") or "")), row.get("industry")),
            sortable_cell(composition, row.get("total_score"), css_class="composition"),
            sortable_cell(_format_number(row.get("total_score")), row.get("total_score"), css_class="total"),
            sortable_cell(_format_percent(row.get("revenue_3m_yoy")), row.get("revenue_3m_yoy")),
            sortable_cell(_format_percent(row.get("revenue_acceleration")), row.get("revenue_acceleration")),
            sortable_cell(_format_percent(row.get("ttm_net_income_growth")), row.get("ttm_net_income_growth")),
            sortable_cell(_format_percent(row.get("ttm_operating_margin_change")), row.get("ttm_operating_margin_change")),
            sortable_cell(_format_number(row.get("per"), 2), row.get("per")),
            sortable_cell(_format_number(row.get("pbr"), 2), row.get("pbr")),
            sortable_cell(
                _format_number(float(row["avg_daily_turnover"]) / 1_000_000, 0)
                if row.get("avg_daily_turnover") is not None else "—",
                row.get("avg_daily_turnover"),
            ),
        ]
    ) + "</tr>"
    detail = (
        f'<tr class="row-detail" data-detail-for="{html.escape(row_id, quote=True)}"><td colspan="14">'
        '<details><summary>技術面、籌碼面與模型短評</summary><div class="research-grid">'
        f'<div><b>技術面</b><br>{html.escape(extra.get("technical", "—"))}</div>'
        f'<div><b>籌碼面</b><br>{html.escape(extra.get("chip", "—"))}</div>'
        f'<div><b>模型短評</b><br>{html.escape(str(row.get("model_summary") or ""))}</div>'
        '</div></details></td></tr>'
    )
    return main + detail


def _momentum_table(rows: list[dict[str, Any]], comparison: dict[str, Any], enrichment: dict[str, dict[str, str]]) -> str:
    headers = [
        ("排名", "number"), ("較前次", "text"), ("代碼", "text"), ("公司", "text"), ("產業", "text"),
        ("分數組成", "number"), ("總分", "number"), ("3M營收", "number"), ("營收加速度", "number"),
        ("TTM淨利成長", "number"), ("營益率變化", "number"), ("本益比", "number"), ("本淨比", "number"),
        ("日均額（百萬）", "number"),
    ]
    score_columns = {5: "key-first", 7: "key-first", 8: "key-first", 9: "key-second", 10: "key-second", 11: "key-third", 12: "key-third"}
    head = "".join(
        f'<th data-type="{kind}">'
        f'{f"""<span class="key-dot {score_columns[index]}"></span>""" if index in score_columns else ""}'
        f'{html.escape(label)}</th>'
        for index, (label, kind) in enumerate(headers)
    )
    body = "".join(_momentum_row_html(row, comparison, enrichment) for row in rows)
    return f'<table class="sortable-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _build_momentum_html(
    result: dict[str, Any],
    *,
    history_path: Path | None = None,
    enrichment: dict[str, dict[str, str]] | None = None,
) -> str:
    meta = result["metadata"]
    comparison = load_rank_comparison(result, history_path)
    enrichment = enrichment or {}
    passing = [row for row in result["results"] if row["hard_pass"]]
    focus_size = int(result["config"]["report"]["focus_size"])
    watchlist_size = int(result["config"]["report"]["watchlist_size"])
    focus = passing[:focus_size]
    watchlist_remainder = passing[focus_size:watchlist_size]
    focus_table = _momentum_table(focus, comparison, enrichment)
    remainder_table = _momentum_table(watchlist_remainder, comparison, enrichment)
    checks_panel = build_monitor_status(
        meta,
        result.get("checks", []),
        stats=[
            ("普通股母體", meta.get("universe_count")),
            ("硬門檻通過", meta.get("hard_pass_count")),
            ("轉機觀察", meta.get("turnaround_count")),
            ("前期資料不足", meta.get("insufficient_history_count")),
        ],
    )
    comparison_note = rank_comparison_note(comparison)
    sortable_script = sortable_table_script()
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股高品質營運動能篩選｜{html.escape(meta['as_of'])}</title>
<style>{monitor_report_css()}</style>
</head>
<body><div class="wrap">
<div class="hero"><div><h1>台股營運動能監控台</h1><p>市場資料 {html.escape(meta['latest_market_date'])}｜營收期 {html.escape(meta['latest_revenue_period'])}｜財報季 {html.escape(meta['latest_financial_quarter'])}｜研究候選，不是買進建議</p></div><div class="hero-status">模型 {html.escape(str(meta.get('model_status') or 'UNKNOWN'))}</div></div>
{checks_panel}
<div class="panel"><div class="panel-head"><div><h2>營運動能精華候選</h2><p class="note">{comparison_note}</p></div><div class="legend"><span class="key-dot key-first"></span>營運動能　<span class="key-dot key-second"></span>動能品質　<span class="key-dot key-third"></span>估值流動性</div></div>{focus_table}
<details class="watchlist"><summary>展開觀察前100第 21–100 名（{len(watchlist_remainder)} 檔）</summary>{remainder_table}</details></div>
<div class="panel copy"><h2>模型說明</h2><h3>核心概念</h3><p>本模型以高品質營運動能為核心，尋找營收、獲利與營益率正在改善，而且成長能獲得現金流與財務體質支持的公司。模型關注企業營運是否加速，而不是短期股價上漲；單月暴增、低基期轉盈及一次性收益須另行覆核。</p>
<h3>篩選流程</h3><ol><li>建立上市、上櫃四位數普通股母體，金融業獨立處理。</li><li>確認最近六個月營收、至少三年財報與20日均成交額5,000萬元。</li><li>要求TTM淨利為正，並排除重大負債異常及人工否決公司。</li><li>營運動能占60分，評估營收、營收加速度、淨利與營益率改善。</li><li>動能品質占25分，檢視獲利、現金流、現金轉換與負債安全。</li><li>估值與流動性占15分，比較同業PER、PBR與成交金額。</li><li>依總分形成觀察前100與精華20。</li><li>最後人工查證成長來源、治理風險、低基期及一次性因素。</li></ol></div>
<p class="note">營運動能分數只負責縮小研究範圍。排名不是預期報酬或買進建議；治理、競爭優勢與成長延續性仍須以年報、法說及公開資訊查證。技術面與籌碼面為外部呈現欄位，不影響模型排名。</p>
{sortable_script}</div></body></html>"""
