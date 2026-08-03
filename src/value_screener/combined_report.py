from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from .report_common import (
    build_freshness_banner,
    current_report_comparability,
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
                ("營運動能", row.get("operating_momentum_score"), "operating"),
                ("動能品質", row.get("quality_score"), "quality"),
                ("估值流動性", row.get("valuation_liquidity_score"), "momentum-valuation"),
            ]
        else:
            segments = [
                ("防禦", row.get("defense_score"), "defense"),
                ("估值", row.get("valuation_score"), "valuation"),
                ("動能", row.get("momentum_score"), "momentum"),
            ]
        body.append("<tr>" + "".join([
            sortable_cell(str(row["rank"]), row["rank"]),
            sortable_cell(f"<strong>{html.escape(stock_id)}</strong>", stock_id),
            sortable_cell(html.escape(str(row.get("stock_name") or "")), row.get("stock_name")),
            sortable_cell(html.escape(str(row.get("industry") or "")), row.get("industry")),
            sortable_cell(f"{float(row.get('total_score') or 0):.1f}", row.get("total_score")),
            sortable_cell(score_composition_bar(segments), row.get("total_score"), css_class="composition"),
            sortable_cell(html.escape(extra.get("technical", "—")), extra.get("technical", "—"), css_class="enrichment"),
            sortable_cell(html.escape(extra.get("chip", "—")), extra.get("chip", "—"), css_class="enrichment"),
        ]) + "</tr>")
    headers = [
        ("排名", "number"), ("代碼", "text"), ("公司", "text"), ("產業", "text"),
        ("總分", "number"), ("分數組成", "number"), ("技術面", "text"), ("籌碼面", "text"),
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

    sortable_script = sortable_table_script()
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股雙模型研究報告｜{html.escape(str(value_meta.get('as_of') or ''))}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif;margin:0;background:#f4f6f8;color:#172033}} .wrap{{max-width:1400px;margin:auto;padding:30px}}
.hero{{background:linear-gradient(120deg,#12263f,#173f35);color:white;border-radius:18px;padding:28px 32px}} .hero h1{{margin:0 0 8px}} .hero p{{margin:0;color:#d7e3ec}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} .panel{{background:white;border-radius:14px;padding:20px;margin-top:18px;overflow:auto;box-shadow:0 2px 14px #15324f14}}
.freshness{{margin:12px 0;padding:9px 12px;border-radius:9px;font-size:13px;font-weight:650}} .freshness.good{{background:#dcfce7;color:#14532d}} .freshness.bad{{background:#fee2e2;color:#991b1b}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th{{background:#17324c;color:white;text-align:left;padding:9px;white-space:nowrap}} td{{padding:9px;border-bottom:1px solid #e5ebf1;white-space:nowrap}}
.sortable{{cursor:pointer;user-select:none}} .sortable::after{{content:" ↕";color:#9fb3c8;font-size:10px}} .sortable[data-order="asc"]::after{{content:" ↑"}} .sortable[data-order="desc"]::after{{content:" ↓"}}
.scorebar{{display:flex;width:140px;height:11px;border-radius:999px;overflow:hidden;background:#e2e8f0}} .score-segment{{display:block;height:100%}} .defense,.operating{{background:#0f766e}} .valuation,.quality{{background:#2563eb}} .momentum,.momentum-valuation{{background:#d97706}} .score-remainder{{background:#e2e8f0}}
td.composition{{min-width:150px}} td.enrichment{{max-width:15rem;white-space:normal;line-height:1.4}} .unavailable{{background:#fee2e2;color:#991b1b;padding:14px;border-radius:10px}} .empty{{color:#64748b}} .note{{color:#526174;line-height:1.6}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}.wrap{{padding:14px}}}}
</style></head><body><div class="wrap">
<div class="hero"><h1>台股雙模型研究報告</h1><p>報表日 {html.escape(str(value_meta.get('as_of') or ''))}｜市場資料 {html.escape(str(value_meta.get('latest_market_date') or ''))}｜排名只用於研究排序，不是買進建議</p></div>
<div class="panel"><h2>雙模型交集</h2><p class="note">{html.escape(intersection_note)}</p>{intersection}</div>
<div class="grid"><section class="panel"><h2>防禦型價值精華20</h2>{build_freshness_banner(value_meta)}{_model_table(value_focus, model_id='defensive_value', enrichment=enrichment)}</section>
<section class="panel"><h2>營運動能精華20</h2>{build_freshness_banner(momentum_meta)}{_model_table(momentum_focus, model_id='operating_momentum', enrichment=enrichment)}</section></div>
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
