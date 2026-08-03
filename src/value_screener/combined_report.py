from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from .report_common import (
    build_monitor_status,
    current_report_comparability,
    load_rank_comparison,
    monitor_report_css,
    period_navigation,
    rank_comparison_note,
    sortable_cell,
    sortable_table_script,
)
from .momentum_report import _momentum_table
from .report import _value_table


def build_combined_html(
    value_result: dict[str, Any],
    momentum_result: dict[str, Any],
    *,
    enrichment: dict[str, dict[str, str]] | None = None,
    history_path: Path | None = None,
    weekly_available: bool = False,
) -> str:
    enrichment = enrichment or {}
    value_meta = value_result["metadata"]
    momentum_meta = momentum_result["metadata"]
    value_passing = [row for row in value_result["results"] if row.get("hard_pass")]
    momentum_passing = [row for row in momentum_result["results"] if row.get("hard_pass")]
    value_focus_size = int(value_result["config"]["report"]["focus_size"])
    momentum_focus_size = int(momentum_result["config"]["report"]["focus_size"])
    value_watch_size = int(value_result["config"]["report"].get("watchlist_size", 100))
    momentum_watch_size = int(momentum_result["config"]["report"].get("watchlist_size", 100))
    value_focus = value_passing[:value_focus_size]
    momentum_focus = momentum_passing[:momentum_focus_size]
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
                sortable_cell(html.escape(str(value_by_id[stock_id].get("industry") or "")), value_by_id[stock_id].get("industry")),
                sortable_cell(str(value_by_id[stock_id]["rank"]), value_by_id[stock_id]["rank"]),
                sortable_cell(str(momentum_by_id[stock_id]["rank"]), momentum_by_id[stock_id]["rank"]),
                sortable_cell(f"{float(value_by_id[stock_id].get('total_score') or 0):.1f}", value_by_id[stock_id].get("total_score")),
                sortable_cell(f"{float(momentum_by_id[stock_id].get('total_score') or 0):.1f}", momentum_by_id[stock_id].get("total_score")),
            ]) + "</tr>"
            for stock_id in intersection_ids
        )
        if intersection_rows:
            intersection = (
                '<div class="tablewrap"><table class="sortable-table"><thead><tr><th data-type="text">代碼</th><th data-type="text">公司</th><th data-type="text">產業</th>'
                '<th data-type="number">價值排名</th><th data-type="number">動能排名</th>'
                '<th data-type="number">價值總分</th><th data-type="number">動能總分</th></tr></thead>'
                f"<tbody>{intersection_rows}</tbody></table></div>"
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
        extra_summary="防禦價值",
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
    value_comparison = load_rank_comparison(value_result, history_path)
    momentum_comparison = load_rank_comparison(momentum_result, history_path)
    value_focus_table = _value_table(value_focus, value_comparison, enrichment)
    value_remainder = value_passing[value_focus_size:value_watch_size]
    momentum_focus_table = _momentum_table(momentum_focus, momentum_comparison, enrichment)
    momentum_remainder = momentum_passing[momentum_focus_size:momentum_watch_size]
    value_remainder_table = _value_table(value_remainder, value_comparison, enrichment)
    momentum_remainder_table = _momentum_table(momentum_remainder, momentum_comparison, enrichment)
    statuses = [str(value_meta.get("model_status") or "UNKNOWN"), str(momentum_meta.get("model_status") or "UNKNOWN")]
    overall_status = "FAIL" if "FAIL" in statuses else "WARN" if any(status != "OK" for status in statuses) else "OK"
    navigation = period_navigation(
        "daily",
        daily_href="index.html",
        weekly_href="../weekly/latest/index.html" if weekly_available else None,
        monthly_href=None,
    )
    sortable_script = sortable_table_script()
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股雙模型監控台｜{html.escape(str(value_meta.get('as_of') or ''))}</title>
<script>document.documentElement.classList.add('js')</script><style>{monitor_report_css()}</style></head><body><div class="wrap">
<div class="hero"><div><h1>台股雙模型監控台</h1><p>報表日 {html.escape(str(value_meta.get('as_of') or ''))}　·　市場日 {html.escape(str(value_meta.get('latest_market_date') or ''))}　·　排名只用於研究排序，不是買進建議</p></div><div class="hero-status {overall_status.lower()}">{overall_status}</div>{navigation}</div>
<div id="status-value" class="model-status">{value_status}</div><div id="status-momentum" class="model-status">{momentum_status}</div>
<div class="report-tabs" role="tablist"><button type="button" role="tab" aria-selected="true" data-tab="intersection">雙模型交集<span class="count">{html.escape(str(intersection_count))}</span></button><button type="button" role="tab" aria-selected="false" data-tab="value">防禦價值</button><button type="button" role="tab" aria-selected="false" data-tab="momentum">營運動能</button></div>
<section class="tab-panel" id="tab-intersection"><div class="panel-head"><div><h2>雙模型交集</h2><p class="note">{html.escape(intersection_note)} 交集只表示兩套獨立條件同時成立。</p></div></div>{intersection}</section>
<section class="tab-panel" id="tab-value"><div class="panel-head"><div><h2>防禦價值</h2><p class="note">{rank_comparison_note(value_comparison)}</p></div><div class="legend"><span class="key-dot key-first"></span>防禦　<span class="key-dot key-second"></span>估值　<span class="key-dot key-third"></span>動能</div></div>{value_focus_table}<details class="watchlist"><summary>展開自選100第 21–100 名（{len(value_remainder)} 檔）</summary>{value_remainder_table}</details></section>
<section class="tab-panel" id="tab-momentum"><div class="panel-head"><div><h2>營運動能</h2><p class="note">{rank_comparison_note(momentum_comparison)}</p></div><div class="legend"><span class="key-dot key-first"></span>營運動能　<span class="key-dot key-second"></span>品質　<span class="key-dot key-third"></span>估值流動性</div></div>{momentum_focus_table}<details class="watchlist"><summary>展開觀察前100第 21–100 名（{len(momentum_remainder)} 檔）</summary>{momentum_remainder_table}</details></section>
<p class="note">技術面與籌碼面僅為外部呈現欄位，不進入分數、硬門檻、模型狀態或排名歷史。量化排序不是買進建議。</p>
{sortable_script}<script>
const tabs = Array.from(document.querySelectorAll('.report-tabs button'));
const panels = Array.from(document.querySelectorAll('.tab-panel'));
const valueStatus = document.getElementById('status-value');
const momentumStatus = document.getElementById('status-momentum');
function selectTab(key) {{
  tabs.forEach((button) => button.setAttribute('aria-selected', String(button.dataset.tab === key)));
  panels.forEach((panel) => {{ panel.hidden = panel.id !== `tab-${{key}}`; }});
  valueStatus.hidden = key === 'momentum';
  momentumStatus.hidden = key === 'value';
}}
tabs.forEach((button) => button.addEventListener('click', () => selectTab(button.dataset.tab)));
selectTab('intersection');
</script></div></body></html>"""


def write_combined_report(
    value_result: dict[str, Any],
    momentum_result: dict[str, Any],
    reports_root: Path,
    *,
    enrichment: dict[str, dict[str, str]] | None = None,
    history_path: Path | None = None,
    weekly_available: bool = False,
) -> dict[str, Path]:
    as_of = str(value_result["metadata"]["as_of"])
    dated_dir = reports_root / as_of
    latest_dir = reports_root / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    dated_path = dated_dir / "combined_report.html"
    latest_path = latest_dir / "combined_report.html"
    index_path = dated_dir / "index.html"
    latest_index_path = latest_dir / "index.html"
    page = build_combined_html(
        value_result,
        momentum_result,
        enrichment=enrichment,
        history_path=history_path,
        weekly_available=weekly_available,
    )
    dated_path.write_text(page, encoding="utf-8")
    index_path.write_text(page, encoding="utf-8")
    shutil.copy2(dated_path, latest_path)
    shutil.copy2(index_path, latest_index_path)
    return {"html": dated_path, "latest_html": latest_path, "index_html": index_path, "latest_index_html": latest_index_path}
