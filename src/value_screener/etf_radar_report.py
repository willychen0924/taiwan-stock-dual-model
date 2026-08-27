from __future__ import annotations

import html
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .portal_layout import esc, portal_css
from .report_common import period_navigation


_SIGNAL_CLASS = {
    "跨投信共振": "up",
    "確認布局": "conf",
    "開始加碼": "start",
    "低部位觀察": "mid",
    "待觀察": "wait",
}


def _percent(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    scaled = float(value) * 100
    rendered = f"{scaled:.{digits}f}"
    if scaled > 0 and float(rendered) == 0:
        return f"<{10 ** -digits:.{digits}f}%"
    return f"{rendered}%"


def _change(value: Any) -> str:
    if value is None:
        return "資料不足"
    return f"{float(value):+.0%}"


def _date(value: Any) -> str:
    text = str(value or "")
    return text[5:] if len(text) >= 10 else "—"


def _number(value: Any, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value):,.{digits}f}"


def _lots(value: Any) -> str:
    if value is None:
        return "—"
    rendered = f"{float(value) / 1000:,.3f}"
    return rendered.rstrip("0").rstrip(".")


def _money_yi(value: Any) -> str:
    return "—" if value is None else f"{float(value) / 100_000_000:,.1f} 億"


def _cell(cell: dict[str, Any]) -> str:
    kind = str(cell["kind"])
    title = html.escape(str(cell.get("title") or ""), quote=True)
    if kind == "up":
        return f'<span class="etfc up" title="{title}"><i class="mark">▲</i>{esc(cell["text"])}</span>'
    if kind == "low":
        return f'<span class="etfc on" title="{title}"><i class="mark">●</i>{esc(cell["text"])}</span>'
    if kind == "missing":
        return f'<span class="etfc miss" title="{title}">缺</span>'
    return f'<span class="etfc off" title="{title}">—</span>'


def _judgement(row: dict[str, Any]) -> str:
    contributors = "、".join(row["contributors"])
    if row["signal"] == "跨投信共振":
        return (
            f'{esc(contributors)} 在最近 3 個交易日內由低部位轉向加碼，去重後來自 '
            f'{row["signal_issuer_count"]} 家投信，因此形成跨投信共振。'
            "ETF／投信欄計入目前符合低部位雷達的持有，包含歷史不足的少量部位。"
        )
    if row["signal"] == "確認布局":
        return f'{esc(contributors)} 承接前一交易日的開始加碼，個股權重再次提高，列為確認布局。'
    if row["signal"] == "開始加碼":
        return f'{esc(contributors)} 原為低部位，當日個股權重提高至少 20%，列為開始加碼。'
    if row["signal"] == "待觀察":
        return (
            f'{esc(contributors)} 當日符合低部位與整張數，但目前只有單日或不足歷史，'
            "尚無法完成連續減碼尾倉檢查；不屬於加碼或共振訊號。"
        )
    return (
        f'{esc(contributors)} 通過低部位、整張數與非連續減碼檢查；目前尚未出現加碼轉向。'
        "ETF／投信欄仍計入其他歷史不足的少量持有；同一家投信旗下多檔只算一家。"
    )


def _detail(row: dict[str, Any]) -> str:
    detail_rows = []
    for item in row["details"]:
        state = str(item["state"])
        if state == "missing":
            position_change = "資料不足"
        elif state == "unheld":
            position_change = "—"
        elif item.get("pos_5d") is None:
            position_change = "歷史不足"
        else:
            position_change = _change(item.get("pos_5d"))
        tone = "hot" if item.get("contributor") and state in {"start", "confirm", "post_turn"} else "neu"
        if state in {"missing", "decline_tail", "residual"}:
            tone = "hot" if state != "missing" else "neu"
        detail_rows.append(
            "<tr>"
            f'<td class="f">{esc(item["etf_code"])}</td>'
            f'<td>{esc(item["issuer"])}</td>'
            f'<td>{_percent(item.get("radar_weight"), 1)}</td>'
            f'<td>{_lots(item.get("shares"))}</td>'
            f'<td>{esc("低於揭露精度") if item.get("below_precision") else _percent(item.get("stock_weight"), 2)}</td>'
            f'<td class="{tone}">{esc(position_change)}</td>'
            f'<td>{esc(item["state_label"])}</td>'
            "</tr>"
        )
    ranks = []
    if row.get("momentum_rank") is not None:
        ranks.append(f'營運動能第 {int(row["momentum_rank"])} 名')
    if row.get("value_rank") is not None:
        ranks.append(f'防禦價值第 {int(row["value_rank"])} 名')
    model_text = "、".join(ranks) if ranks else "兩模型皆未入榜"
    reference = (
        f'雙模型：{esc(model_text)}——本頁不影響其分數或排名。'
        f'市值 {_money_yi(row.get("market_value"))}，20 日均額 {_money_yi(row.get("avg_daily_turnover"))}。'
    )
    return (
        '<dl class="dwrap">'
        f'<div class="drow"><dt>判定</dt><dd>{_judgement(row)}</dd></div>'
        '<div class="drow"><dt>逐檔明細</dt><dd><table class="subt"><thead><tr>'
        '<th>ETF</th><th>投信</th><th>雷達權重（√AUM）</th><th>持有張數</th><th>個股權重</th>'
        '<th>5日標準化部位</th><th>目前狀態</th></tr></thead><tbody>'
        f'{"".join(detail_rows)}</tbody></table></dd></div>'
        f'<div class="drow"><dt>交叉參照</dt><dd>{reference}</dd></div>'
        '</dl>'
    )


def _row(row: dict[str, Any], codes: list[str]) -> str:
    signal_class = _SIGNAL_CLASS[row["signal"]]
    hot = " hot" if row["signal"] != "低部位觀察" else ""
    cells = [
        f'<span class="sigcell"><span class="sigchip {signal_class}">{esc(row["signal"])}</span></span>',
        f'<span class="mono">{esc(row["stock_id"])}</span>',
        f'<span class="nm">{esc(row["stock_name"])}</span>',
    ]
    cells.extend(_cell(row["cells"][code]) for code in codes)
    cells.extend(
        [
            f'<span class="split">{row["etf_count"]}<s>/</s>{row["issuer_count"]}</span>',
            f'<span class="n">{_date(row.get("low_start"))}</span>',
            f'<span class="n">{_date(row.get("last_turn"))}</span>',
            f'<span class="n">{_number(row.get("close"), 1)}</span>',
        ]
    )
    return f'<details class="lrow lgrid-etf{hot}"><summary>{"".join(cells)}</summary>{_detail(row)}</details>'


def _listing(rows: list[dict[str, Any]], codes: list[str]) -> str:
    headers = ["訊號", "代碼", "公司"] + [code.lstrip("0") for code in codes] + [
        "ETF/投信",
        "低部位起點",
        "最近轉向",
        "收盤",
    ]
    header_cells = []
    for index, label in enumerate(headers):
        css = "etfh" if 3 <= index < 8 else "n" if index >= 8 else ""
        header_cells.append(f'<span class="{css}">{esc(label)}</span>')
    return (
        '<div class="listwrap">'
        f'<div class="lhead lgrid-etf">{"".join(header_cells)}</div>'
        f'{"".join(_row(row, codes) for row in rows)}'
        '</div>'
    )


def _excluded(result: dict[str, Any]) -> str:
    rows = result["excluded"]
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(str(reason) for reason in row.get("reasons", []))
    order = ["減碼尾倉", "配股殘留", "非低部位", "資料不足"]
    labels = [reason for reason in order if counts[reason]]
    labels.extend(sorted(reason for reason in counts if reason not in order))
    categories = "".join(
        f'<span class="excat"><b>{esc(reason)}</b><i>{counts[reason]}</i></span>'
        for reason in labels
    )
    if not categories:
        categories = '<span class="exnone">本日無排除項目</span>'
    return (
        '<div class="exbox"><div class="exhead"><h3>排除分類</h3>'
        f'<span>{len(rows)} 檔 · 不進入排序</span></div>'
        f'<div class="exsummary">{categories}</div></div>'
    )


def _daily_watch_rows(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(row: dict[str, Any] | None) -> None:
        if row is None or len(selected) >= limit:
            return
        stock_id = str(row.get("stock_id") or "")
        if not stock_id or stock_id in selected_ids:
            return
        selected.append(row)
        selected_ids.add(stock_id)

    active = [
        row
        for row in rows
        if row.get("signal") not in {"低部位觀察", "待觀察"}
    ]
    for row in active:
        add(row)

    consensus = [
        row
        for row in rows
        if int(row.get("etf_count") or 0) >= 2
        and int(row.get("issuer_count") or 0) >= 2
    ]
    add(consensus[0] if consensus else None)

    order = {str(row.get("stock_id") or ""): index for index, row in enumerate(rows)}
    cross_model = sorted(
        (
            row
            for row in rows
            if row.get("value_rank") is not None and row.get("momentum_rank") is not None
        ),
        key=lambda row: (
            int(row["value_rank"]) + int(row["momentum_rank"]),
            max(int(row["value_rank"]), int(row["momentum_rank"])),
            order.get(str(row.get("stock_id") or ""), 9999),
        ),
    )
    for row in cross_model:
        if str(row.get("stock_id") or "") not in selected_ids:
            add(row)
            break

    for row in consensus:
        add(row)
    for row in rows:
        add(row)
    return selected


def _watch_reason(row: dict[str, Any]) -> str:
    parts = [
        f'{int(row.get("etf_count") or 0)} 檔 ETF、'
        f'{int(row.get("issuer_count") or 0)} 家投信符合低部位雷達'
    ]
    history_short = [
        str(item["etf_code"])
        for item in row.get("details", [])
        if item.get("state") == "cold_low"
    ]
    if history_short:
        parts.append(f'{"、".join(history_short)} 歷史仍不足')

    comparable = [
        item
        for item in row.get("details", [])
        if item.get("contributor") and item.get("pos_5d") is not None
    ]
    if comparable:
        item = max(comparable, key=lambda value: abs(float(value["pos_5d"])))
        parts.append(
            f'{item["etf_code"]} 五日標準化部位 {float(item["pos_5d"]):+.1%}'
        )

    value_rank = row.get("value_rank")
    momentum_rank = row.get("momentum_rank")
    if value_rank is not None and momentum_rank is not None:
        parts.append(f'防禦價值第 {int(value_rank)}、營運動能第 {int(momentum_rank)}')
    elif value_rank is not None:
        parts.append(f'防禦價值第 {int(value_rank)}')
    elif momentum_rank is not None:
        parts.append(f'營運動能第 {int(momentum_rank)}')

    revenue_period = str(row.get("revenue_period") or "")
    latest_revenue_yoy = row.get("latest_revenue_yoy")
    revenue_3m_yoy = row.get("revenue_3m_yoy")
    if revenue_period and latest_revenue_yoy is not None:
        revenue_text = f'{revenue_period} 單月營收年增 {float(latest_revenue_yoy):+.1%}'
        if revenue_3m_yoy is not None:
            revenue_text += f'、近三月年增 {float(revenue_3m_yoy):+.1%}'
        parts.append(revenue_text)
    return "；".join(parts) + "。"


def _watch_trigger(row: dict[str, Any]) -> str:
    signal = str(row.get("signal") or "")
    contributors = "、".join(str(code) for code in row.get("contributors", [])) or "現有 ETF"
    if signal == "跨投信共振":
        return "觀察跨投信加碼是否延續，並避免只看單日變化。"
    if signal == "確認布局":
        return "已連續提高部位；繼續確認是否有第二家投信加入。"
    if signal == "開始加碼":
        return "等待下一交易日續增，才升級為確認布局。"
    history_short = [
        str(item["etf_code"])
        for item in row.get("details", [])
        if item.get("state") == "cold_low"
    ]
    if history_short:
        return (
            f'等待 {"、".join(history_short)} 補足歷史並排除連續減碼；'
            f'同時觀察 {contributors} 是否轉為明顯加碼。'
        )
    return f"等待 {contributors} 由低部位轉為明顯加碼，或出現第二家投信同步。"


def _daily_watch(result: dict[str, Any]) -> str:
    rows = list(result.get("rows") or [])
    selected = _daily_watch_rows(rows)
    if not selected:
        return (
            '<section class="daily-watch"><div class="dwhead"><h2>每日觀察</h2>'
            '<span>依 ETF 雷達與雙模型交叉自動整理</span></div>'
            '<p class="dwempty">目前沒有可列入每日觀察的個股。</p></section>'
        )
    body = "".join(
        "<tr>"
        f'<td class="dwpriority">{index}</td>'
        f'<td class="dwstock"><b>{esc(row["stock_name"])}</b><span>{esc(row["stock_id"])}</span></td>'
        f'<td>{esc(_watch_reason(row))}</td>'
        f'<td>{esc(_watch_trigger(row))}</td>'
        "</tr>"
        for index, row in enumerate(selected, 1)
    )
    selected_ids = {str(row.get("stock_id") or "") for row in selected}
    remaining = [
        row for row in rows if str(row.get("stock_id") or "") not in selected_ids
    ]
    secondary = next(
        (
            row
            for row in remaining
            if row.get("signal") not in {"低部位觀察", "待觀察"}
        ),
        None,
    )
    if secondary is None:
        cross_model = sorted(
            (
                row
                for row in remaining
                if row.get("value_rank") is not None
                and row.get("momentum_rank") is not None
            ),
            key=lambda row: (
                int(row["value_rank"]) + int(row["momentum_rank"]),
                max(int(row["value_rank"]), int(row["momentum_rank"])),
            ),
        )
        secondary = cross_model[0] if cross_model else (remaining[0] if remaining else None)
    secondary_text = ""
    if secondary is not None:
        rank_text = ""
        if secondary.get("value_rank") is not None and secondary.get("momentum_rank") is not None:
            rank_text = (
                f'，防禦價值第 {int(secondary["value_rank"])}、'
                f'營運動能第 {int(secondary["momentum_rank"])}'
            )
        secondary_text = (
            '<p class="dwnext"><b>次一級觀察</b>　'
            f'{esc(secondary["stock_name"])}（{esc(secondary["stock_id"])}）：'
            f'{int(secondary.get("etf_count") or 0)} 檔 ETF／'
            f'{int(secondary.get("issuer_count") or 0)} 家投信符合低部位雷達'
            f'{esc(rank_text)}。</p>'
        )
    return (
        '<section class="daily-watch"><div class="dwhead"><h2>每日觀察</h2>'
        '<span>依持有共識、5 日部位、雙模型與營收資料自動整理</span></div>'
        '<div class="dwtable"><table><thead><tr><th>優先</th><th>個股</th>'
        '<th>觀察理由</th><th>等待訊號</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>{secondary_text}'
        '<p class="dwcaution">本區是每日研究清單，不是進場訊號或買進建議；'
        '正式狀態仍以 ETF 雷達主表為準。</p></section>'
    )


def _extra_css() -> str:
    return """
.panel{display:block}.lgrid-etf{--cols:98px 50px 88px 56px 56px 56px 56px 56px 68px 72px 72px 60px;--minw:974px}
.lhead.lgrid-etf>span,.lrow.lgrid-etf>summary>span{box-shadow:none;padding-left:0}
.lhead.lgrid-etf>span:first-child{padding-left:13px}.etfh{text-align:center;letter-spacing:0;font-variant-numeric:tabular-nums}
.etfc{text-align:center;font-variant-numeric:tabular-nums;font-size:12px;padding:2px 0;border-radius:3px}
.etfc .mark{font-size:10px;font-style:normal;vertical-align:1px;margin-right:1px}
.etfc.on{background:#e7f0e3;color:#3f6b46;font-weight:600}.etfc.up{background:rgba(235,104,52,.13);color:#b8452a;font-weight:700}
.etfc.off{color:var(--faint)}.etfc.miss{background:#fae5dd;color:#a8331f;font-weight:700}
.sigchip.conf{background:#e4ecf7;color:#2b5a94}.sigchip.start{background:rgba(235,104,52,.15);color:#b8452a}
.sigchip.wait{background:#efe9dc;color:#75664f}
.sigcell{display:flex;align-items:center}.sigcell .sigchip{white-space:nowrap}.split{text-align:center;font-variant-numeric:tabular-nums;font-size:12px;color:var(--inks)}
.split s{text-decoration:none;color:var(--faint);margin:0 3px}.lrow.hot>summary{background:rgba(235,104,52,.045)}
.lrow.hot>summary:hover{background:rgba(235,104,52,.085)}
.subt{width:100%;border-collapse:collapse;font-size:12px;margin:2px 0 0}.subt th{font-size:10.5px;font-weight:600;color:var(--muted);letter-spacing:.4px;text-align:right;padding:0 0 5px;border-bottom:1px solid var(--rule)}
.subt th:first-child,.subt td:first-child{text-align:left}.subt th:last-child,.subt td:last-child{text-align:left;padding-left:14px}
.subt td{padding:6px 0;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.subt tr:last-child td{border-bottom:none}.subt td.f{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--link)}
.subt td.neu{color:var(--muted)}.subt td.hot{color:#b8452a;font-weight:700}
.daily-watch{margin-bottom:16px;background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -16px rgba(11,11,11,.12)}
.dwhead{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:13px 16px 10px;background:var(--fill);border-bottom:1px solid var(--line2)}
.dwhead h2{margin:0;font-size:15px;color:var(--ink)}.dwhead span{font-size:11.5px;color:var(--muted)}
.dwtable{overflow-x:auto}.dwtable table{width:100%;min-width:900px;border-collapse:collapse;font-size:12.5px}
.dwtable th{padding:8px 12px;text-align:left;font-size:11px;color:var(--ink2);background:var(--surface);border-bottom:1px solid var(--line2);white-space:nowrap}
.dwtable td{padding:10px 12px;color:var(--ink2);line-height:1.65;vertical-align:top;border-bottom:1px solid var(--tint)}
.dwtable tr:last-child td{border-bottom:none}.dwtable th:first-child,.dwtable td:first-child{text-align:center;width:52px}
.dwtable th:nth-child(2),.dwtable td:nth-child(2){width:126px}.dwtable th:last-child,.dwtable td:last-child{width:30%}
.dwpriority{font-weight:800;color:var(--active)!important;font-size:14px}.dwstock b{display:block;color:var(--ink);font-size:13.5px}.dwstock span{display:block;color:var(--link);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:2px}
.dwnext,.dwcaution,.dwempty{margin:0;padding:9px 16px;border-top:1px solid var(--line2);font-size:11.5px;line-height:1.65;color:var(--muted)}
.dwnext b{color:var(--ink2)}.dwcaution{background:var(--fill)}
.exbox{margin-top:16px;border:1px solid var(--line2);border-left:3px solid var(--faint);border-radius:6px;background:var(--surface);display:flex;align-items:center;gap:16px;padding:10px 14px}
.exhead{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.exhead h3{margin:0;font-size:13px;color:var(--active);font-weight:600;letter-spacing:.02em}.exhead span{font-size:11.5px;color:#b8452a;font-weight:600;white-space:nowrap}
.exsummary{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.excat{display:inline-flex;align-items:center;gap:7px;padding:4px 8px;border:1px solid var(--line2);border-radius:999px;background:var(--page);font-size:11.5px;color:var(--ink2)}
.excat b{font-weight:600}.excat i{font-style:normal;color:#b8452a;font-weight:700;font-variant-numeric:tabular-nums}.exnone{font-size:11.5px;color:var(--muted)}
@media(max-width:760px){.dwhead{align-items:flex-start;flex-direction:column;gap:3px}.exbox{align-items:flex-start;flex-direction:column;gap:7px}.exhead{width:100%;justify-content:space-between}}
"""


def build_etf_radar_html(
    result: dict[str, Any], *, published_at: datetime | None = None
) -> str:
    meta = result["metadata"]
    coverage = meta.get("coverage") or {"healthy": 0, "total": 5}
    healthy = int(coverage.get("healthy") or 0)
    total = int(coverage.get("total") or 5)
    missing_codes = [code for code, value in meta["sources"].items() if value["status"] != "healthy"]
    history_days = int(meta.get("history_days") or 0)
    warmup = int(meta.get("warmup_trading_days") or 6)
    history_by_etf = {
        code: int(value)
        for code, value in (meta.get("history_days_by_etf") or {}).items()
    }
    if not history_by_etf:
        history_by_etf = {code: history_days for code in meta["sources"]}
    warning = healthy < total or min(history_by_etf.values(), default=0) <= warmup
    status_class = "warn" if warning else ""
    status_text = f"揭露 {healthy}/{total}"
    published_at = published_at or datetime.now(ZoneInfo("Asia/Taipei"))
    published = published_at.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")
    counts = {label: 0 for label in _SIGNAL_CLASS}
    for row in result["rows"]:
        counts[row["signal"]] += 1
    codes = list(meta["etf_order"])
    watch_signals = {"低部位觀察", "待觀察"}
    active_rows = [row for row in result["rows"] if row["signal"] not in watch_signals]
    low_rows = [row for row in result["rows"] if row["signal"] in watch_signals]
    low_limit = int(meta.get("primary_observation_limit") or 10)
    primary_rows = active_rows + low_rows[:low_limit]
    extra_low = low_rows[low_limit:]
    table = _listing(primary_rows, codes)
    if not primary_rows:
        table += '<p class="empty">目前沒有可排序的訊號；資料仍會每日累積，缺漏不以前一日補值。</p>'
    if extra_low:
        table += (
            f'<details class="watchlist"><summary>展開其餘觀察名單（{len(extra_low)} 檔）</summary>'
            f'{_listing(extra_low, codes)}</details>'
        )
    missing_text = f'<em>·</em> {esc("、".join(missing_codes))} 缺失' if missing_codes else ""
    history_groups: dict[int, list[str]] = {}
    for code in codes:
        history_groups.setdefault(history_by_etf.get(code, 0), []).append(code.lstrip("0"))
    if len(history_groups) == 1:
        only_days = next(iter(history_groups))
        history_label = (
            f"冷啟動 {only_days}/{warmup + 1} 日"
            if only_days <= warmup
            else f"歷史 {only_days} 日"
        )
    else:
        history_label = "歷史 " + "；".join(
            f'{"/".join(group_codes)} {days_count} 日'
            for days_count, group_codes in history_groups.items()
        )
    warmup_text = f'<em>·</em> {esc(history_label)}'
    navigation = period_navigation(
        "radar",
        radar_href="index.html",
        daily_href="../../latest/index.html",
        weekly_href="../../weekly/latest/index.html",
        monthly_href=None,
    )
    weight_text = "／".join(
        f'{code} {_percent(meta["weights"].get(code), 1)}' for code in codes
    )
    provisional = "（暫定；尚未累積滿 20 個交易日）" if meta.get("weights_provisional") else ""
    third_party_codes = [
        code
        for code in codes
        if "third_party" in (meta.get("history_provenance_by_etf") or {}).get(code, [])
    ]
    history_source_note = ""
    if third_party_codes:
        history_source_note = (
            '<p class="foot"><b>歷史補值</b>　'
            f'{esc("／".join(third_party_codes))} 的官方歷史缺口由 Goal Star '
            "公開資料補齊；最新資料與同日衝突一律以投信官方為準。</p>"
        )
    pool_count = int(meta.get("observation_pool_count") or len(low_rows))
    candidate_limit = int(meta.get("observation_candidate_limit") or 15)
    pool_text = (
        f'<span>單日符合 {pool_count} 檔，候選只取排名前 {candidate_limit} 檔</span>'
        if int(meta.get("observation_omitted_count") or 0) > 0
        else ""
    )
    css = portal_css() + _extra_css()
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF 雷達｜{esc(meta['data_date'])}</title><style>{css}</style></head><body><div class="wrap">
<div class="pagebg" aria-hidden="true"></div>
<header class="head"><div class="accent"></div><div class="headrow"><h1>ETF 雷達</h1></div>
<p class="metaline"><span class="statusdot {status_class}"></span>{status_text}
<em>·</em> 資料日 {esc(meta['data_date'])}{missing_text}{warmup_text}
<em>·</em> 跨投信共振 {counts['跨投信共振']} 檔
<em>·</em> 加碼中 {counts['確認布局'] + counts['開始加碼']} 檔
<em>·</em> 低部位觀察 {counts['低部位觀察']} 檔
<em>·</em> 待觀察 {counts['待觀察']} 檔
<em>·</em> 資料發佈 {esc(published)}</p><div class="tabrow">{navigation}</div></header>
<section class="panel">{_daily_watch(result)}<p class="note">主動式 ETF 持有低部位、且非連續賣出殘留的個股，由強至弱排序：<b>跨投信共振</b> → <b>確認布局</b> → <b>開始加碼</b> → <b>低部位觀察</b> → <b>待觀察</b>。冷啟動期間先顯示單日低部位，但不產生加碼或共振訊號。「ETF/投信」計入目前符合低部位雷達的持有，包含歷史不足的少量部位；同一家投信旗下多檔只算一家。點列展開查看完整判定。本頁不使用、也不影響雙模型的 100 分評分與硬門檻。</p>
<p class="legend"><span>▲ 加碼轉向</span><span>● 低部位／待觀察</span><span>數字＝目前持有張數</span><span>— 未納入當前訊號</span><span>缺＝官網資料缺失</span><span>排序：ETF 檔數 → 雷達權重合計 → 投信數</span>{pool_text}<span>張數只供閱讀；訊號以個股權重計算</span><span>統一 981A・403A｜復華 991A｜群益 982A・992A</span></p>
{table}{_excluded(result)}
<div class="audit"><h2>規則與定位</h2>
<p class="foot"><b>低部位</b>　佔基金淨值 ≤ 0.15%、為 1,000 股整數倍，且未觸發最近 4 日至少 3 日減碼或 5 日權重減少 30%。個股權重而非股數用於判定，避免把 ETF 申購贖回誤認為經理人加碼。</p>
<p class="foot"><b>冷啟動待觀察</b>　前 6 份快照先顯示當日低部位與整張數標的，但尚未完成連續減碼排除，不列為開始加碼、確認布局或跨投信共振。</p>
<p class="foot"><b>投信去重</b>　統一旗下 00981A／00403A、群益旗下 00982A／00992A 各併計為一家；跨投信才視為獨立確認。</p>
<p class="foot"><b>雷達權重 {esc(meta['weight_version'])}</b>　{esc(weight_text)}。依近 20 個交易日 AUM 中位數平方根正規化，只用於同級排序，不是分數。{esc(provisional)}</p>
<p class="foot"><b>更新與時效</b>　每個交易日盤後擷取官方完整投資組合，建議於次日上午 08:00–08:30 閱讀。PCF 為 T 日盤後揭露，本頁最快只能在 T+1 跟進 T 日動作；來源缺失時顯示「缺」，不沿用舊值。</p>
{history_source_note}
<p class="foot"><b>證據等級</b>　「低部位＝經理人試單」是市場觀察，不是可驗證事實。小部位仍可能來自配股、轉換或調整過渡。主動式 ETF 歷史短，訊號尚無足夠樣本回測。本頁是觀察工具，不是選股模型，也不寫入雙模型排名歷史。量化排序不是買進建議。</p></div>
</section></div></body></html>"""


def write_etf_radar_report(result: dict[str, Any], reports_root: Path) -> dict[str, Path]:
    data_date = str(result["metadata"]["data_date"])
    dated_dir = reports_root / "etf_radar" / data_date
    latest_dir = reports_root / "etf_radar" / "latest"
    dated_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    dated_path = dated_dir / "index.html"
    latest_path = latest_dir / "index.html"
    dated_path.write_text(build_etf_radar_html(result), encoding="utf-8")
    shutil.copy2(dated_path, latest_path)
    return {"dated_html": dated_path, "latest_html": latest_path}
