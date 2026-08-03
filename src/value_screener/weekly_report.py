from __future__ import annotations

import html
import json
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from .report_common import monitor_report_css, period_navigation


MODEL_LABELS = {
    "defensive_value": "防禦價值",
    "operating_momentum": "營運動能",
}
COMPONENT_LABELS = {
    "defensive_value": [("defense", "防禦"), ("valuation", "估值"), ("momentum", "動能")],
    "operating_momentum": [
        ("operating_momentum", "營運動能"),
        ("quality", "品質"),
        ("valuation_liquidity", "估值流動性"),
    ],
}


def load_history(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"歷史檔第 {line_number} 行不是有效 JSON") from exc
    return records


def completed_week_window(records: Iterable[dict[str, Any]], *, as_of: date) -> tuple[date, date]:
    market_dates = sorted(
        date.fromisoformat(str(record["latest_market_date"]))
        for record in records
        if record.get("latest_market_date")
    )
    if not market_dates:
        raise ValueError("排名歷史沒有市場日期")
    current_week_start = as_of - timedelta(days=as_of.weekday())
    if as_of.weekday() >= 5:
        candidates = [item for item in market_dates if item <= as_of]
    else:
        candidates = [item for item in market_dates if item < current_week_start]
    if not candidates:
        raise ValueError("尚無完整週資料")
    latest = max(candidates)
    week_start = latest - timedelta(days=latest.weekday())
    return week_start, week_start + timedelta(days=4)


def last_eligible_by_market_date(
    records: Iterable[dict[str, Any]],
    *,
    model_id: str,
    week_start: date,
    week_end: date,
) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if str(record.get("model_id") or "") != model_id:
            continue
        market_date = str(record.get("latest_market_date") or "")
        if not market_date:
            continue
        parsed = date.fromisoformat(market_date)
        if week_start <= parsed <= week_end:
            grouped[market_date].append(record)

    selected: list[dict[str, Any]] = []
    invalid: list[tuple[str, list[str]]] = []
    for market_date in sorted(grouped):
        eligible = [record for record in grouped[market_date] if record.get("eligible_for_backtest")]
        if eligible:
            selected.append(eligible[-1])
        else:
            reasons = list(grouped[market_date][-1].get("ineligible_reasons") or ["沒有有效模型版本"])
            invalid.append((market_date, [str(reason) for reason in reasons]))
    return selected, invalid


def longest_version_segment(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    if not records:
        return [], []
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_version: Any = object()
    for record in records:
        version = record.get("config_version")
        if current and version != current_version:
            segments.append(current)
            current = []
        current.append(record)
        current_version = version
    if current:
        segments.append(current)
    longest = max(segments, key=lambda segment: (len(segment), str(segment[-1].get("latest_market_date") or "")))
    return longest, segments


def _rank_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("stock_id") or ""): item
        for item in record.get("rankings", [])
        if item.get("stock_id") and item.get("rank") is not None
    }


def _top(record: dict[str, Any], size: int = 20) -> dict[str, dict[str, Any]]:
    return {stock_id: item for stock_id, item in _rank_map(record).items() if int(item["rank"]) <= size}


def _version_label(value: Any) -> str:
    return html.escape(str(value)) if value not in (None, "", "None") else "舊版未記錄"


def _invalid_summary(items: list[tuple[str, list[str]]]) -> str:
    if not items:
        return "—"
    return "；".join(f'{market_date}: {"、".join(reasons)}' for market_date, reasons in items)


def _chips(items: Iterable[dict[str, Any]], css_class: str) -> str:
    values = list(items)
    if not values:
        return '<span class="dim">—</span>'
    return "".join(
        f'<span class="weekly-chip {css_class}"><b>{html.escape(str(item.get("stock_id") or ""))}</b> '
        f'{html.escape(str(item.get("stock_name") or ""))}</span>'
        for item in values
    )


def _longest_streak(presence: list[bool]) -> int:
    best = current = 0
    for present in presence:
        current = current + 1 if present else 0
        best = max(best, current)
    return best


def _model_section(model_id: str, selected: list[dict[str, Any]]) -> str:
    label = MODEL_LABELS[model_id]
    segment, segments = longest_version_segment(selected)
    if not segment:
        return f'<p class="unavailable">{label}本週沒有有效觀測。</p>'

    first, last = segment[0], segment[-1]
    first_map, last_map = _rank_map(first), _rank_map(last)
    first_top, last_top = _top(first), _top(last)
    incoming = [last_top[key] for key in sorted(last_top.keys() - first_top.keys(), key=lambda key: int(last_top[key]["rank"]))]
    outgoing = [first_top[key] for key in sorted(first_top.keys() - last_top.keys(), key=lambda key: int(first_top[key]["rank"]))]

    segment_note = ""
    if len(segments) > 1:
        descriptions = "；".join(
            f'{part[0].get("latest_market_date")}～{part[-1].get("latest_market_date")} '
            f'({_version_label(part[0].get("config_version"))}，{len(part)}日)'
            for part in segments
        )
        segment_note = (
            '<p class="weekly-warning">本週包含多個模型版本，以下只比較同版本內最長區間：'
            f'<b>{first.get("latest_market_date")}～{last.get("latest_market_date")}</b> '
            f'({_version_label(first.get("config_version"))}，{len(segment)}個有效市場日)。其餘區間：{descriptions}</p>'
        )

    stability_rows: list[str] = []
    for stock_id, item in sorted(last_top.items(), key=lambda pair: int(pair[1]["rank"])):
        presence = [stock_id in _top(record) for record in segment]
        days = sum(presence)
        streak = _longest_streak(presence)
        stability_rows.append(
            "<tr>"
            f'<td class="stock-id">{html.escape(stock_id)}</td><td>{html.escape(str(item.get("stock_name") or ""))}</td>'
            f'<td class="number">{days}/{len(segment)}</td><td class="number">{streak}</td>'
            f'<td><span class="stability"><i style="width:{days / len(segment):.1%}"></i></span></td>'
            f'<td class="number">{int(item["rank"])}</td></tr>'
        )

    changes: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
    for stock_id in first_map.keys() & last_map.keys():
        delta = int(first_map[stock_id]["rank"]) - int(last_map[stock_id]["rank"])
        if delta:
            changes.append((delta, stock_id, first_map[stock_id], last_map[stock_id]))
    changes.sort(key=lambda item: (abs(item[0]), item[0]), reverse=True)
    change_rows = "".join(
        "<tr>"
        f'<td class="stock-id">{html.escape(stock_id)}</td><td>{html.escape(str(last_item.get("stock_name") or ""))}</td>'
        f'<td class="number dim">{int(first_item["rank"])}</td><td class="number">{int(last_item["rank"])}</td>'
        f'<td class="number {"up" if delta > 0 else "down"}">{"↑" if delta > 0 else "↓"}{abs(delta)}</td></tr>'
        for delta, stock_id, first_item, last_item in changes[:10]
    ) or '<tr><td colspan="5" class="dim">本區間沒有名次變化。</td></tr>'

    component_defs = COMPONENT_LABELS[model_id]
    component_rows: list[tuple[float, str]] = []
    for stock_id, last_item in last_top.items():
        first_item = first_map.get(stock_id)
        first_components = first_item.get("components") if first_item else None
        last_components = last_item.get("components")
        if not isinstance(first_components, dict) or not isinstance(last_components, dict):
            continue
        deltas = [float(last_components.get(key) or 0) - float(first_components.get(key) or 0) for key, _ in component_defs]
        cells = "".join(f'<td class="number">{delta:+.1f}</td>' for delta in deltas)
        row = (
            "<tr>"
            f'<td class="stock-id">{html.escape(stock_id)}</td><td>{html.escape(str(last_item.get("stock_name") or ""))}</td>'
            f'{cells}<td class="number">{float(last_item.get("total_score") or 0) - float(first_item.get("total_score") or 0):+.1f}</td></tr>'
        )
        component_rows.append((sum(abs(value) for value in deltas), row))
    component_rows.sort(key=lambda item: item[0], reverse=True)
    if component_rows:
        component_head = "".join(f'<th class="number">{html.escape(name)}</th>' for _, name in component_defs)
        component_table = (
            '<h3>分數組成變化</h3><p class="note">顯示期末精華20中，分數區塊變化最大的10檔；正負號只描述模型分數變化。</p>'
            '<div class="tablewrap"><table><thead><tr><th>代碼</th><th>公司</th>'
            f'{component_head}<th class="number">總分</th></tr></thead><tbody>'
            f'{"".join(row for _, row in component_rows[:10])}</tbody></table></div>'
        )
    else:
        component_table = '<div class="weekly-todo">此區間的歷史 schema 尚無完整 components，暫不呈現分數組成變化。</div>'

    if len(segment) < 2:
        comparisons = '<p class="weekly-warning">同版本有效觀測只有1日，暫不計算進出榜與名次變化。</p>'
    else:
        comparisons = f"""
<h3>精華20期初至期末淨進出</h3><div class="inout"><div><b class="in">進榜</b>{_chips(incoming, 'in')}</div><div><b class="out">掉出</b>{_chips(outgoing, 'out')}</div></div>
<h3>期末精華20穩定度</h3><p class="note">在榜日以本段有效市場觀測為分母；最長連續是實際連續出現在精華20的觀測數。</p><div class="tablewrap"><table><thead><tr><th>代碼</th><th>公司</th><th class="number">在榜日</th><th class="number">最長連續</th><th>穩定度</th><th class="number">期末名次</th></tr></thead><tbody>{''.join(stability_rows)}</tbody></table></div>
<h3>重大名次變化</h3><p class="note">只比較期初與期末皆在硬門檻排名內的公司，列出絕對變動最大的10檔。</p><div class="tablewrap"><table><thead><tr><th>代碼</th><th>公司</th><th class="number">期初</th><th class="number">期末</th><th class="number">變動</th></tr></thead><tbody>{change_rows}</tbody></table></div>
{component_table}"""
    return segment_note + comparisons


def build_weekly_html(
    records: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
) -> str:
    selected_by_model: dict[str, list[dict[str, Any]]] = {}
    invalid_by_model: dict[str, list[tuple[str, list[str]]]] = {}
    for model_id in MODEL_LABELS:
        selected, invalid = last_eligible_by_market_date(
            records,
            model_id=model_id,
            week_start=week_start,
            week_end=week_end,
        )
        selected_by_model[model_id] = selected
        invalid_by_model[model_id] = invalid

    quality_rows = "".join(
        "<tr>"
        f'<td>{label}</td><td class="number">{len(selected_by_model[model_id])}</td>'
        f'<td class="number">{len(invalid_by_model[model_id])}</td>'
        f'<td class="dim">{html.escape(_invalid_summary(invalid_by_model[model_id]))}</td></tr>'
        for model_id, label in MODEL_LABELS.items()
    )

    value_by_date = {str(record["latest_market_date"]): record for record in selected_by_model["defensive_value"]}
    momentum_by_date = {str(record["latest_market_date"]): record for record in selected_by_model["operating_momentum"]}
    intersection_rows: list[str] = []
    for market_date in sorted(value_by_date.keys() & momentum_by_date.keys()):
        value_top = _top(value_by_date[market_date])
        momentum_top = _top(momentum_by_date[market_date])
        common = [value_top[key] for key in value_top if key in momentum_top]
        intersection_rows.append(
            "<tr>"
            f'<td class="stock-id">{html.escape(market_date)}</td><td class="number">{len(common)}</td>'
            f'<td>{_chips(common, "")}</td></tr>'
        )
    intersection_body = "".join(intersection_rows) or '<tr><td colspan="3" class="dim">本週沒有可比較的雙模型有效市場日。</td></tr>'

    version_changes: list[str] = []
    for model_id, selected in selected_by_model.items():
        versions = []
        for record in selected:
            version = record.get("config_version")
            if version not in versions:
                versions.append(version)
        if len(versions) > 1:
            version_changes.append(
                f'{MODEL_LABELS[model_id]}：{" → ".join(_version_label(version) for version in versions)}'
            )
    version_banner = (
        '<div class="weekly-warning"><b>本週模型版本有變動，跨版本數字不直接比較。</b><br>'
        f'{"；".join(version_changes)}</div>'
        if version_changes else ""
    )
    navigation = period_navigation(
        "weekly",
        daily_href="../../latest/index.html",
        weekly_href="index.html",
        monthly_href=None,
    )
    css = monitor_report_css() + """
h3{font-size:14px;margin:22px 0 8px;color:var(--navy)}.number{text-align:right;font-variant-numeric:tabular-nums}
.weekly-warning{margin:14px 0;background:#fffbeb;border-left:4px solid #d97706;border-radius:9px;padding:12px 15px;color:#92400e;line-height:1.75}
.weekly-tabs{display:flex;gap:4px;margin-top:16px;border-bottom:2px solid #e2e8f0}.weekly-tabs button{background:none;border:0;padding:10px 18px 11px;font:600 13.5px inherit;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px;cursor:pointer}.weekly-tabs button[aria-selected="true"]{color:var(--navy);border-bottom-color:var(--navy)}
.weekly-panel{padding-top:18px}.js .weekly-panel[hidden]{display:none}.weekly-chip{display:inline-block;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:7px;padding:4px 10px;margin:0 6px 5px 0}.weekly-chip.in{background:#f0fdf4;border-color:#bbf7d0}.weekly-chip.out{background:#fef2f2;border-color:#fecaca}.weekly-chip b{font-family:ui-monospace,monospace;color:#0369a1}.inout>div{margin:8px 0}.inout>div>b{display:inline-block;width:50px}.in{color:#047857}.out,.down{color:#b91c1c}.up{color:#047857}.stability{display:block;width:120px;height:8px;border-radius:999px;background:#e2e8f0;overflow:hidden}.stability i{display:block;height:100%;background:#16a34a}.weekly-todo{margin-top:16px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:9px;padding:12px 15px;color:#94a3b8}
"""
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>週報 {week_start}～{week_end}｜台股雙模型監控台</title><script>document.documentElement.classList.add('js')</script><style>{css}</style></head><body><div class="wrap">
<div class="hero"><div><h1>台股雙模型週報</h1><p>市場週 {week_start}～{week_end}　·　只採用有效且可比較的模型觀測</p></div>{navigation}</div>{version_banner}
<div class="weekly-tabs" role="tablist"><button type="button" aria-selected="true" data-tab="overview">總覽</button><button type="button" aria-selected="false" data-tab="defensive_value">防禦價值</button><button type="button" aria-selected="false" data-tab="operating_momentum">營運動能</button></div>
<section class="weekly-panel" id="weekly-overview"><h3>資料品質</h3><p class="note">失效日不納入排名、進出榜或交集比較。</p><div class="tablewrap"><table><thead><tr><th>模型</th><th class="number">有效日</th><th class="number">失效日</th><th>失效原因</th></tr></thead><tbody>{quality_rows}</tbody></table></div><h3>雙模型交集逐日變化</h3><p class="note">交集不代表買進建議，只表示同一有效市場日同時進入兩個模型精華20。</p><div class="tablewrap"><table><thead><tr><th>市場日</th><th class="number">檔數</th><th>標的</th></tr></thead><tbody>{intersection_body}</tbody></table></div><div class="weekly-todo"><b>前瞻報酬暫不提供：</b>需累積足夠的5／20／60交易日資料，並處理股利與公司行動後才啟用。</div></section>
<section class="weekly-panel" id="weekly-defensive_value">{_model_section('defensive_value', selected_by_model['defensive_value'])}</section><section class="weekly-panel" id="weekly-operating_momentum">{_model_section('operating_momentum', selected_by_model['operating_momentum'])}</section>
<p class="note">本報告只由 rankings_history.jsonl 產生。每個市場日取檔案中最後一份有效版本；跨版本區間分開處理。量化排名只負責縮小研究範圍，不是買進建議。</p>
<script>const weeklyTabs=Array.from(document.querySelectorAll('.weekly-tabs button'));const weeklyPanels=Array.from(document.querySelectorAll('.weekly-panel'));function selectWeekly(key){{weeklyTabs.forEach((button)=>button.setAttribute('aria-selected',String(button.dataset.tab===key)));weeklyPanels.forEach((panel)=>{{panel.hidden=panel.id!==`weekly-${{key}}`;}});}}weeklyTabs.forEach((button)=>button.addEventListener('click',()=>selectWeekly(button.dataset.tab)));selectWeekly('overview');</script></div></body></html>"""


def write_weekly_report(
    records: list[dict[str, Any]],
    reports_root: Path,
    *,
    week_start: date,
    week_end: date,
) -> dict[str, Path]:
    label = f"{week_start.isoformat()}_{week_end.isoformat()}"
    dated_dir = reports_root / "weekly" / label
    latest_dir = reports_root / "weekly" / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    dated_path = dated_dir / "index.html"
    latest_path = latest_dir / "index.html"
    dated_path.write_text(build_weekly_html(records, week_start=week_start, week_end=week_end), encoding="utf-8")
    shutil.copy2(dated_path, latest_path)
    return {"html": dated_path, "latest_html": latest_path}
