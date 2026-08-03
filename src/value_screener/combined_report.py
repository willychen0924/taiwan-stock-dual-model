from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from .report_common import (
    build_monitor_status,
    current_report_comparability,
    monitor_report_css,
    score_composition_bar,
    sortable_cell,
    sortable_table_script,
)


def _focus(result: dict[str, Any]) -> list[dict[str, Any]]:
    size = int(result["config"]["report"]["focus_size"])
    return [row for row in result["results"] if row.get("hard_pass")][:size]


def _model_table(
    rows: list[dict[str, Any]],
    *,
    model_id: str,
    enrichment: dict[str, dict[str, str]],
) -> str:
    body: list[str] = []
    for row in rows:
        stock_id = str(row["stock_id"])
        extra = enrichment.get(stock_id, {})
        if model_id == "operating_momentum":
            segments = [
                ("營運動能", row.get("operating_momentum_score"), "score-operating"),
                ("動能品質", row.get("quality_score"), "score-quality"),
                ("估值流動性", row.get("valuation_liquidity_score"), "score-momentum-valuation"),
            ]
        else:
            segments = [
                ("防禦", row.get("defense_score"), "score-defense"),
                ("估值", row.get("valuation_score"), "score-valuation"),
                ("動能", row.get("momentum_score"), "score-momentum"),
            ]
        row_id = f"{model_id}-{stock_id}"
        body.append(f'<tr data-row-id="{html.escape(row_id, quote=True)}">' + "".join([
            sortable_cell(str(row["rank"]), row["rank"]),
            sortable_cell(f"<strong>{html.escape(stock_id)}</strong>", stock_id),
            sortable_cell(html.escape(str(row.get("stock_name") or "")), row.get("stock_name")),
            sortable_cell(html.escape(str(row.get("industry") or "")), row.get("industry")),
            sortable_cell(score_composition_bar(segments), row.get("total_score"), css_class="composition"),
            sortable_cell(f"{float(row.get('total_score') or 0):.1f}", row.get("total_score"), css_class="total"),
        ]) + "</tr>" + (
            f'<tr class="row-detail" data-detail-for="{html.escape(row_id, quote=True)}"><td colspan="6">'
            '<details><summary>技術面與籌碼面</summary><div class="research-grid">'
            f'<div><b>技術面</b><br>{html.escape(extra.get("technical", "—"))}</div>'
            f'<div><b>籌碼面</b><br>{html.escape(extra.get("chip", "—"))}</div>'
            '<div><b>定位</b><br>外部研究資訊，不進入模型分數、硬門檻或排名。</div>'
            '</div></details></td></tr>'
        ))
    headers = [
        ("排名", "number"), ("代碼", "text"), ("公司", "text"), ("產業", "text"),
        ("分數組成", "number"), ("總分", "number"),
    ]
    head = "".join(f'<th data-type="{kind}">{html.escape(label)}</th>' for label, kind in headers)
    return f'<table class="sortable-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def build_combined_html(
    value_result: dict[str, Any],
    momentum_result: dict[str, Any],
    *,
    enrichment: dict[str, dict[str, str]] | None = None,
) -> str:
    enrichment = enrichment or {}
    value_meta = value_result["metadata"]
    momentum_meta = momentum_result["metadata"]
    value_focus = _focus(value_result)
    momentum_focus = _focus(momentum_result)
    value_ok, value_reason = current_report_comparability(value_result)
    momentum_ok, momentum_reason = current_report_comparability(momentum_result)
    same_market_date = value_meta.get("latest_market_date") == momentum_meta.get("latest_market_date")
    comparable = value_ok and momentum_ok and same_market_date

    value_by_id = {str(row["stock_id"]): row for row in value_focus}
    momentum_by_id = {str(row["stock_id"]): row for row in momentum_focus}
    intersection_ids = [stock_id for stock_id in value_by_id if stock_id in momentum_by_id] if comparable else []
    if comparable:
        intersection_rows = "".join(
            "<tr>" + "".join([
                sortable_cell(html.escape(stock_id), stock_id),
                sortable_cell(html.escape(str(value_by_id[stock_id].get("stock_name") or "")), value_by_id[stock_id].get("stock_name")),
                sortable_cell(str(value_by_id[stock_id]["rank"]), value_by_id[stock_id]["rank"]),
                sortable_cell(str(momentum_by_id[stock_id]["rank"]), momentum_by_id[stock_id]["rank"]),
                sortable_cell(f"{float(value_by_id[stock_id].get('total_score') or 0):.1f}", value_by_id[stock_id].get("total_score")),
                sortable_cell(f"{float(momentum_by_id[stock_id].get('total_score') or 0):.1f}", momentum_by_id[stock_id].get("total_score")),
            ]) + "</tr>"
            for stock_id in intersection_ids
        )
        if intersection_rows:
            intersection = (
                '<table class="sortable-table"><thead><tr><th data-type="text">代碼</th><th data-type="text">公司</th>'
                '<th data-type="number">價值排名</th><th data-type="number">動能排名</th>'
                '<th data-type="number">價值總分</th><th data-type="number">動能總分</th></tr></thead>'
                f"<tbody>{intersection_rows}</tbody></table>"
            )
        else:
            intersection = '<p class="empty">本次兩邊精華20沒有交集。</p>'
        intersection_note = f"同一市場資料日 {html.escape(str(value_meta.get('latest_market_date') or ''))}，共 {len(intersection_ids)} 檔。"
    else:
        reasons = []
        if not value_ok:
            reasons.append(f"價值模型：{value_reason}")
        if not momentum_ok:
            reasons.append(f"動能模型：{momentum_reason}")
        if not same_market_date:
            reasons.append("兩模型市場資料日不同")
        intersection_note = "資料不可比（" + "；".join(reasons) + "）"
        intersection = '<p class="unavailable">本次不產生雙模型交集，避免把失效或不同步資料解讀為研究訊號。</p>'

    intersection_count = len(intersection_ids) if comparable else "—"
    value_status = build_monitor_status(
        value_meta,
        value_result.get("checks", []),
        stats=[
            ("普通股母體", value_meta.get("universe_count")),
            ("一般公司", value_meta.get("operating_company_count")),
            ("硬門檻通過", value_meta.get("hard_pass_count")),
            ("雙模型交集", intersection_count),
        ],
        extra_summary="防禦型價值",
    )
    momentum_status = build_monitor_status(
        momentum_meta,
        momentum_result.get("checks", []),
        stats=[
            ("普通股母體", momentum_meta.get("universe_count")),
            ("硬門檻通過", momentum_meta.get("hard_pass_count")),
            ("轉機觀察", momentum_meta.get("turnaround_count")),
            ("雙模型交集", intersection_count),
        ],
        extra_summary="營運動能",
    )
    sortable_script = sortable_table_script()
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股雙模型研究報告｜{html.escape(str(value_meta.get('as_of') or ''))}</title>
<style>{monitor_report_css()}</style></head><body><div class="wrap">
<div class="hero"><div><h1>台股雙模型監控台</h1><p>報表日 {html.escape(str(value_meta.get('as_of') or ''))}｜市場資料 {html.escape(str(value_meta.get('latest_market_date') or ''))}｜排名只用於研究排序，不是買進建議</p></div><div class="hero-status">交集 {html.escape(str(intersection_count))}</div></div>
<div class="grid">{value_status}{momentum_status}</div>
<div class="panel"><h2>雙模型交集</h2><p class="note">{html.escape(intersection_note)}</p>{intersection}</div>
<div class="grid"><section class="panel"><div class="panel-head"><h2>防禦型價值精華20</h2><div class="legend"><span class="key-dot key-first"></span>防禦　<span class="key-dot key-second"></span>估值　<span class="key-dot key-third"></span>動能</div></div>{_model_table(value_focus, model_id='defensive_value', enrichment=enrichment)}</section>
<section class="panel"><div class="panel-head"><h2>營運動能精華20</h2><div class="legend"><span class="key-dot key-first"></span>營運動能　<span class="key-dot key-second"></span>品質　<span class="key-dot key-third"></span>估值流動性</div></div>{_model_table(momentum_focus, model_id='operating_momentum', enrichment=enrichment)}</section></div>
<p class="note">技術面與籌碼面僅為外部呈現欄位，不進入分數、硬門檻、模型狀態或排名歷史。</p>
{sortable_script}</div></body></html>"""


def write_combined_report(
    value_result: dict[str, Any],
    momentum_result: dict[str, Any],
    reports_root: Path,
    *,
    enrichment: dict[str, dict[str, str]] | None = None,
) -> dict[str, Path]:
    as_of = str(value_result["metadata"]["as_of"])
    dated_dir = reports_root / as_of
    latest_dir = reports_root / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    dated_path = dated_dir / "combined_report.html"
    latest_path = latest_dir / "combined_report.html"
    dated_path.write_text(
        build_combined_html(value_result, momentum_result, enrichment=enrichment),
        encoding="utf-8",
    )
    shutil.copy2(dated_path, latest_path)
    return {"html": dated_path, "latest_html": latest_path}
