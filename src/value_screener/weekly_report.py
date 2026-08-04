from __future__ import annotations

import html
import json
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from .portal_layout import portal_css
from .report_common import period_navigation


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


# ── 週對週、產業分布、交集延續性、人工複核進度 ───────────────────────────

def prior_week_window(week_start: date, week_end: date) -> tuple[date, date]:
    return week_start - timedelta(days=7), week_end - timedelta(days=7)


def week_over_week(
    records: list[dict[str, Any]],
    *,
    model_id: str,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    """比較本週末與上週末的精華20。跨模型版本時不做比較——名次差異會同時
    包含市場變動與模型變動，無法歸因。"""
    this_week, _ = last_eligible_by_market_date(
        records, model_id=model_id, week_start=week_start, week_end=week_end
    )
    prior_start, prior_end = prior_week_window(week_start, week_end)
    prior_week, _ = last_eligible_by_market_date(
        records, model_id=model_id, week_start=prior_start, week_end=prior_end
    )
    if not this_week or not prior_week:
        return {"comparable": False, "reason": "上一週沒有有效觀測"}
    current, previous = this_week[-1], prior_week[-1]
    if current.get("config_version") != previous.get("config_version"):
        return {
            "comparable": False,
            "reason": (
                f"上週為 {_version_label(previous.get('config_version'))}，"
                f"本週為 {_version_label(current.get('config_version'))}，跨版本不可比"
            ),
        }
    current_top, previous_top = _top(current), _top(previous)
    stayed = [current_top[key] for key in current_top if key in previous_top]
    entered = [current_top[key] for key in current_top if key not in previous_top]
    left = [previous_top[key] for key in previous_top if key not in current_top]
    return {
        "comparable": True,
        "prior_market_date": str(previous.get("latest_market_date") or ""),
        "market_date": str(current.get("latest_market_date") or ""),
        "stayed": sorted(stayed, key=lambda item: int(item["rank"])),
        "entered": sorted(entered, key=lambda item: int(item["rank"])),
        "left": sorted(left, key=lambda item: int(item["rank"])),
    }


def industry_mix(record: dict[str, Any] | None, size: int = 20) -> dict[str, int]:
    if not record:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for item in record.get("rankings", [])[:size]:
        counts[str(item.get("industry") or "未分類")] += 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def intersection_persistence(
    value_by_date: dict[str, dict[str, Any]],
    momentum_by_date: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], int]], int]:
    """回傳（全週都在的、只出現部分天數的（含天數）、共同有效市場日數）。"""
    shared_dates = sorted(value_by_date.keys() & momentum_by_date.keys())
    appearances: dict[str, list[Any]] = defaultdict(list)
    for market_date in shared_dates:
        value_top = _top(value_by_date[market_date])
        momentum_top = _top(momentum_by_date[market_date])
        for stock_id in value_top.keys() & momentum_top.keys():
            appearances[stock_id].append(value_top[stock_id])
    total = len(shared_dates)
    always = [items[-1] for items in appearances.values() if len(items) == total and total]
    partial = [(items[-1], len(items)) for items in appearances.values() if 0 < len(items) < total]
    always.sort(key=lambda item: int(item["rank"]))
    partial.sort(key=lambda pair: (-pair[1], int(pair[0]["rank"])))
    return always, partial, total


def manual_review_progress(
    manual_review: dict[str, dict[str, str]],
    focus_ids: set[str],
) -> dict[str, int]:
    reviewed = {
        stock_id
        for stock_id, row in manual_review.items()
        if (row.get("governance_status") or "").strip() not in ("", "待複核")
    }
    return {
        "filled": len(manual_review),
        "reviewed": len(reviewed),
        "focus_total": len(focus_ids),
        "focus_reviewed": len(focus_ids & reviewed),
    }


def section(title: str, note: str, body: str) -> str:
    """一節＝標題＋同一行的說明＋內容。說明不另起段落，否則資料會被推到很下面。"""
    hint = f'<span class="sechint">{note}</span>' if note else ""
    return f'<div class="sec"><div class="sechead"><h3>{title}</h3>{hint}</div>{body}</div>'


def card(*parts: str) -> str:
    """整個面板一張卡、內部以細線分節——十幾張獨立圓角卡片是視覺噪音的來源。"""
    return f'<div class="card">{"".join(part for part in parts if part)}</div>'


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

    segment_note = (
        f'<p class="note">比較區間 <b>{first.get("latest_market_date")}～{last.get("latest_market_date")}</b>'
        f'（{_version_label(first.get("config_version"))}，{len(segment)} 個有效市場日）。'
        + ("本週有多個模型版本，只取同版本內最長區間；詳見頁尾「模型版本與比較區間」。</p>"
           if len(segments) > 1 else "</p>")
    )

    stability_rows: list[str] = []
    for stock_id, item in sorted(last_top.items(), key=lambda pair: int(pair[1]["rank"])):
        presence = [stock_id in _top(record) for record in segment]
        days = sum(presence)
        streak = _longest_streak(presence)
        stability_rows.append(
            "<tr>"
            f'<td class="stock-id">{html.escape(stock_id)}</td><td>{html.escape(str(item.get("stock_name") or ""))}</td>'
            f'<td class="number">{days}／{streak}</td>'
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
        component_table = section(
            "分數組成變化",
            "期末精華20中分數區塊變化最大的10檔；正負號只描述模型分數變化",
            '<div class="tablewrap"><table><thead><tr><th>代碼</th><th>公司</th>'
            f'{component_head}<th class="number">總分</th></tr></thead><tbody>'
            f'{"".join(row for _, row in component_rows[:10])}</tbody></table></div>',
        )
    else:
        component_table = section(
            "分數組成變化", "",
            '<p class="dim">此區間的歷史 schema 尚無完整 components，暫不呈現。</p>',
        )

    if len(segment) < 2:
        return segment_note + card(
            section("比較說明", "", '<p class="dim">同版本有效觀測只有 1 日，暫不計算進出榜與名次變化。</p>'),
            component_table,
        )
    return segment_note + card(
        section(
            "精華20名單變動", "",
            f'<div class="inout"><div><b class="in">新增</b>{_chips(incoming, "in")}</div>'
            f'<div><b class="out">移出</b>{_chips(outgoing, "out")}</div></div>',
        ),
        section(
            "期末精華20穩定度",
            "分母為本段有效市場觀測；最長連續為連續入選精華20的觀測數",
            '<div class="tablewrap"><table><thead><tr><th>代碼</th><th>公司</th>'
            '<th class="number">在榜日／最長連續</th><th>穩定度</th>'
            f'<th class="number">期末名次</th></tr></thead><tbody>{"".join(stability_rows)}</tbody></table></div>',
        ),
        section(
            "重大名次變化",
            "只比較期初與期末皆在硬門檻排名內的公司，取絕對變動最大的10檔",
            '<div class="tablewrap"><table><thead><tr><th>代碼</th><th>公司</th>'
            '<th class="number">期初</th><th class="number">期末</th>'
            f'<th class="number">變動</th></tr></thead><tbody>{change_rows}</tbody></table></div>',
        ),
        component_table,
    )


def build_weekly_html(
    records: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
    manual_review: dict[str, dict[str, str]] | None = None,
) -> str:
    manual_review = manual_review or {}
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

    always, partial, shared_days = intersection_persistence(value_by_date, momentum_by_date)
    partial_chips = "".join(
        f'<span class="weekly-chip"><b>{html.escape(str(item.get("stock_id") or ""))}</b> '
        f'{html.escape(str(item.get("stock_name") or ""))}'
        f'<small class="dim"> {days}/{shared_days}日</small></span>'
        for item, days in partial
    ) or '<span class="dim">—</span>'
    persistence_block = (
        f'<div class="inout"><div><b class="in">全週都在</b>{_chips(always, "in")}</div>'
        f'<div><b class="out">部分天數</b>{partial_chips}</div></div>'
        if shared_days else '<p class="dim">本週沒有共同的有效市場日。</p>'
    )

    prior_start, prior_end = prior_week_window(week_start, week_end)
    industry_rows: list[str] = []
    for model_id, label in MODEL_LABELS.items():
        selected = selected_by_model[model_id]
        prior_selected, _ = last_eligible_by_market_date(
            records, model_id=model_id, week_start=prior_start, week_end=prior_end
        )
        now = industry_mix(selected[-1] if selected else None)
        before = industry_mix(prior_selected[-1] if prior_selected else None)
        names = sorted(set(now) | set(before), key=lambda key: (-now.get(key, 0), key))
        if not names:
            industry_rows.append(f'<tr><td>{label}</td><td class="dim" colspan="2">本週沒有有效觀測</td></tr>')
            continue
        cells = "、".join(
            f'{html.escape(name)} <b>{now.get(name, 0)}</b>'
            + (
                f'<small class="{"up" if now.get(name, 0) > before.get(name, 0) else "out"}">'
                f'{now.get(name, 0) - before.get(name, 0):+d}</small>'
                if before and now.get(name, 0) != before.get(name, 0) else ""
            )
            for name in names[:8]
        )
        industry_rows.append(
            f'<tr><td>{label}</td><td>{cells}</td>'
            f'<td class="dim">{"對照上週" if before else "上週無有效觀測"}</td></tr>'
        )

    wow_blocks: list[str] = []
    for model_id, label in MODEL_LABELS.items():
        wow = week_over_week(records, model_id=model_id, week_start=week_start, week_end=week_end)
        if not wow["comparable"]:
            wow_blocks.append(
                f'<tr><td>{label}</td><td class="dim" colspan="4">不可比：{html.escape(wow["reason"])}</td></tr>'
            )
            continue
        wow_blocks.append(
            f'<tr><td>{label}</td>'
            f'<td class="number">{len(wow["stayed"])}</td>'
            f'<td class="number up">{len(wow["entered"])}</td>'
            f'<td class="number out">{len(wow["left"])}</td>'
            f'<td class="dim">{html.escape(wow["prior_market_date"])} → {html.escape(wow["market_date"])}</td></tr>'
        )

    focus_ids = {
        str(item.get("stock_id"))
        for selected in selected_by_model.values()
        if selected
        for item in selected[-1].get("rankings", [])[:20]
    }
    review = manual_review_progress(manual_review, focus_ids)
    review_block = (
        f'<p class="note">本週兩個模型精華20 合計 <b>{review["focus_total"]}</b> 檔，'
        f'其中已完成治理複核 <b>{review["focus_reviewed"]}</b> 檔；'
        f'config/manual_review.csv 累計 <b>{review["filled"]}</b> 筆、'
        f'已定狀態 <b>{review["reviewed"]}</b> 筆。</p>'
        + ('<div class="weekly-todo">質化複核尚未開始。量化排名只是研究漏斗；'
           '未完成治理、護城河與催化查證前，精華20 仍只是待研究候選。</div>'
           if review["focus_reviewed"] == 0 else "")
    )

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
    version_rows: list[str] = []
    for model_id, label in MODEL_LABELS.items():
        selected = selected_by_model[model_id]
        if not selected:
            version_rows.append(f'<tr><td>{label}</td><td class="dim" colspan="3">本週沒有有效觀測</td></tr>')
            continue
        segment, segments = longest_version_segment(selected)
        used = (
            f'{segment[0].get("latest_market_date")}～{segment[-1].get("latest_market_date")}'
            f'（{len(segment)} 日）'
        )
        others = "；".join(
            f'{part[0].get("latest_market_date")}～{part[-1].get("latest_market_date")}'
            f'（{_version_label(part[0].get("config_version"))}，{len(part)} 日）'
            for part in segments if part is not segment
        ) or "—"
        version_rows.append(
            f'<tr><td>{label}</td>'
            f'<td>{_version_label(segment[0].get("config_version"))}</td>'
            f'<td>{used}</td><td class="dim">{others}</td></tr>'
        )
    has_change = bool(version_changes)
    valid_counts = "／".join(
        f"{label} {len(selected_by_model[model_id])}"
        for model_id, label in MODEL_LABELS.items()
    )
    highlights: list[str] = []
    for model_id, label in MODEL_LABELS.items():
        wow = week_over_week(records, model_id=model_id, week_start=week_start, week_end=week_end)
        if wow["comparable"]:
            highlights.append(
                f'{label}精華20 較上週留任 {len(wow["stayed"])}、'
                f'新進 {len(wow["entered"])}、掉出 {len(wow["left"])}'
            )
        else:
            highlights.append(f"{label}與上週不可比（{wow['reason']}）")
    summary_bits = [
        f'市場週 <b>{week_start}～{week_end}</b>，有效市場日 {valid_counts}。',
        "；".join(highlights) + "。",
    ]
    if shared_days:
        summary_bits.append(
            f'雙模型交集共 <b>{len(always) + len(partial)}</b> 檔，'
            f'其中 <b>{len(always)}</b> 檔全週都在。'
        )
    if version_changes:
        summary_bits.append("本週模型版本有變動，跨版本區間已排除，詳見頁尾。")
    summary_block = (
        '<section class="summary"><h2>本週摘要</h2><p>' + " ".join(summary_bits) + "</p></section>"
    )

    version_section = (
        '<div class="audit"><h2>模型版本與比較區間</h2>'
        + ('<p class="weekly-warning">本週模型版本有變動：'
           + "；".join(version_changes)
           + '。跨版本的名次差異同時包含市場變動與模型變動，無法歸因，因此各模型只比較'
             '同一版本內最長的連續區間。</p>' if has_change else
           '<p class="note">本週各模型版本一致，全期間可直接比較。</p>')
        + card(section(
            "各模型採用的區間", "",
            '<div class="tablewrap"><table><thead><tr><th>模型</th><th>採用版本</th>'
            '<th>比較區間</th><th>排除區間</th></tr></thead>'
            f'<tbody>{"".join(version_rows)}</tbody></table></div>',
        ))
        + "</div>"
    )
    navigation = period_navigation(
        "weekly",
        daily_href="../../latest/index.html",
        weekly_href="index.html",
        monthly_href=None,
    )
    css = portal_css() + """
.n,.number{text-align:right;font-variant-numeric:tabular-nums}
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;
 margin-bottom:16px;box-shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -16px rgba(11,11,11,.12)}
.sec{padding:15px 18px 17px}
.sec+.sec{border-top:1px solid var(--line2)}
.sechead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:9px}
.sechead h3{margin:0;font-size:13.5px;font-weight:700;color:var(--ink)}
.sechint{font-size:11.5px;color:var(--muted);line-height:1.5}
.tablewrap{overflow-x:auto;margin:0 -18px -17px;padding:0}
.tablewrap table{width:100%;border-collapse:collapse;font-size:13.5px}
.tablewrap thead th{background:var(--fill);color:var(--ink2);text-align:left;padding:10px 14px;font-weight:700;
 font-size:11.5px;border-bottom:1px solid var(--line2);white-space:nowrap}
.tablewrap thead th.number,.tablewrap thead th.n{text-align:right}
.tablewrap tbody td{padding:11px 14px;border-bottom:1px solid var(--tint);vertical-align:top}
.tablewrap tbody tr:last-child td{border-bottom:none}
.tablewrap thead th:first-child,.tablewrap tbody td:first-child{padding-left:18px}
.tablewrap thead th:last-child,.tablewrap tbody td:last-child{padding-right:18px}
.tablewrap tbody tr:hover td{background:var(--fill)}
.stock-id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--link)}
/* 警示色與日報一致；整個系統只有一種警報色，異常的辨識度才不會隨頁面浮動 */
.weekly-warning{margin:14px 0;background:rgba(208,59,59,.07);border-left:4px solid #d03b3b;
 border-radius:9px;padding:12px 15px;color:#a8331f;line-height:1.75;font-size:12.5px}
.weekly-chip{display:inline-block;background:var(--tint);border:1px solid var(--line2);border-radius:8px;
 padding:4px 10px;margin:0 6px 5px 0;font-size:12.5px}
.weekly-chip.in{background:#e7f0e3;border-color:#cfe0c8;color:#3f6b46}
.weekly-chip.out{background:#fae5dd;border-color:#f0cfc4;color:#b8452a}
.weekly-chip b{font-family:ui-monospace,Menlo,monospace;color:var(--link)}
.inout>div{margin:8px 0}
.inout>div>b{display:inline-block;width:52px;font-size:11.5px;letter-spacing:.3px}
.in{color:#3f6b46}.out{color:#b8452a}
/* 穩定度衡量的是「在榜天數」，不是分數區塊——不沿用分數三色，避免誤讀 */
.stability{display:block;width:120px;height:8px;border-radius:999px;background:var(--line2);
 overflow:hidden}
.stability i{display:block;height:100%;background:var(--active);opacity:.55}
.weekly-todo{margin-top:10px;background:var(--fill);border:1px dashed var(--faint);
 border-radius:10px;padding:10px 13px;color:var(--ink2);font-size:12.5px;line-height:1.7}
.weekly-todo b{color:var(--inks)}
.summary{background:var(--surface);border:1px solid var(--line);border-radius:16px;
 padding:16px 20px;margin:16px 0 0;
 box-shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -16px rgba(11,11,11,.12)}
.summary h2{margin:0 0 6px;font-size:11.5px;color:var(--ink2);font-weight:700;letter-spacing:.5px}
.summary p{margin:0;font-size:13.5px;line-height:1.85;color:var(--ink)}
.summary b{font-variant-numeric:tabular-nums}
.weekly-chip small{margin-left:5px;font-size:11px}
.inout>div>b{width:64px}
td small{margin-left:3px;font-size:11px;font-variant-numeric:tabular-nums}
#w-overview:checked ~ #weekly-overview,
#w-value:checked    ~ #weekly-defensive_value,
#w-momentum:checked ~ #weekly-operating_momentum{display:block}
.weekly-panel{display:none;padding-top:18px}
#w-overview:checked ~ .head .tabs label[for=w-overview],
#w-value:checked    ~ .head .tabs label[for=w-value],
#w-momentum:checked ~ .head .tabs label[for=w-momentum]{background:var(--active);color:#fff;font-weight:700}
"""
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>週報 {week_start}～{week_end}｜台股雙模型監控台</title>
<style>{css}</style></head><body><div class="wrap">

<input type="radio" name="wtab" id="w-momentum" class="tabin" checked>
<input type="radio" name="wtab" id="w-value" class="tabin">
<input type="radio" name="wtab" id="w-overview" class="tabin">
<div class="pagebg" aria-hidden="true"></div>

<header class="head">
  <div class="accent"></div>
  <div class="headrow"><h1>台股雙模型週報</h1></div>
  <p class="metaline">市場週 {week_start}～{week_end}<em>·</em>只採用有效且可比較的模型觀測</p>
  <div class="tabrow">
    <div class="tabs">
      <label for="w-momentum">營運動能</label>
      <label for="w-value">防禦價值</label>
      <label for="w-overview">總覽</label>
    </div>
    {navigation}
  </div>
</header>
{summary_block}
<section class="weekly-panel" id="weekly-operating_momentum">{_model_section('operating_momentum', selected_by_model['operating_momentum'])}</section>
<section class="weekly-panel" id="weekly-defensive_value">{_model_section('defensive_value', selected_by_model['defensive_value'])}</section>
<section class="weekly-panel" id="weekly-overview">
{card(
  section("較上週變化",
          "比較本週末與上週末的精華20；跨模型版本時不計算",
          '<div class="tablewrap"><table><thead><tr><th>模型</th><th class="number">留任</th>'
          '<th class="number">新進</th><th class="number">掉出</th><th>比較基準</th></tr></thead>'
          f'<tbody>{"".join(wow_blocks)}</tbody></table></div>'),
  section("精華20產業分布",
          "期末組成與上週末對照；產業輪動在週頻最看得出來",
          '<div class="tablewrap"><table><thead><tr><th>模型</th><th>產業（檔數）</th>'
          f'<th>對照</th></tr></thead><tbody>{"".join(industry_rows)}</tbody></table></div>'),
  section("雙模型交集",
          "全週都在的比只出現一兩天的更值得優先研究",
          persistence_block
          + '<div class="tablewrap"><table><thead><tr><th>市場日</th><th class="number">檔數</th>'
          f'<th>標的</th></tr></thead><tbody>{intersection_body}</tbody></table></div>'),
)}
{card(
  section("資料品質",
          "失效日不納入排名、進出榜或交集比較",
          '<div class="tablewrap"><table><thead><tr><th>模型</th><th class="number">有效日</th>'
          '<th class="number">失效日</th><th>失效原因</th></tr></thead>'
          f'<tbody>{quality_rows}</tbody></table></div>'),
  section("人工複核進度", "", review_block),
  section("前瞻報酬",
          "需累積足夠的 5／20／60 交易日資料，並處理股利與公司行動後才啟用",
          '<p class="dim">暫不提供。</p>'),
)}
</section>

{version_section}

<p class="foot">本報告只由 rankings_history.jsonl 產生，不依賴 14 天內清除的 reports 目錄。
每個市場日取檔案中最後一份有效版本；跨版本區間分開處理。
量化排名只負責縮小研究範圍，不是買進建議。</p>
</div></body></html>"""


def write_weekly_report(
    records: list[dict[str, Any]],
    reports_root: Path,
    *,
    week_start: date,
    week_end: date,
    manual_review: dict[str, dict[str, str]] | None = None,
) -> dict[str, Path]:
    label = f"{week_start.isoformat()}_{week_end.isoformat()}"
    dated_dir = reports_root / "weekly" / label
    latest_dir = reports_root / "weekly" / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    dated_path = dated_dir / "index.html"
    latest_path = latest_dir / "index.html"
    dated_path.write_text(
        build_weekly_html(records, week_start=week_start, week_end=week_end, manual_review=manual_review),
        encoding="utf-8",
    )
    shutil.copy2(dated_path, latest_path)
    return {"html": dated_path, "latest_html": latest_path}
