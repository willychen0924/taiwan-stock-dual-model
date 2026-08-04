from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from .portal_layout import (
    SCORE_COLORS,
    detail_block,
    esc,
    head_row,
    list_row,
    number,
    percent,
    portal_css,
    score_bar,
    signal_cells,
)
from .report_common import (
    build_monitor_status,
    current_report_comparability,
    format_rank_change,
    load_rank_comparison,
    period_navigation,
    rank_comparison_note,
)

_FIRST, _SECOND, _THIRD = SCORE_COLORS["first"], SCORE_COLORS["second"], SCORE_COLORS["third"]

_HEAD_VALUE = [
    ("#", ""), ("Δ", ""), ("代碼", ""), ("公司", ""), ("產業", ""), ("分數組成", ""), ("總分", "n"),
    ("淨現金比", "n k1"), ("清算覆蓋", "n k2"), ("本益比", "n k2"), ("本淨比", "n k2"),
    ("3M營收", "n k3"), ("技術", ""), ("籌碼", ""),
]
_HEAD_MOMENTUM = [
    ("#", ""), ("Δ", ""), ("代碼", ""), ("公司", ""), ("產業", ""), ("分數組成", ""), ("總分", "n"),
    ("3M營收", "n k1"), ("營收加速度", "n k1"), ("淨利成長", "n k1"), ("營益率變化", "n k1"),
    ("現金轉換", "n k2"), ("技術", ""), ("籌碼", ""),
]
_HEAD_INTERSECTION = [
    ("代碼", ""), ("公司", ""), ("產業", ""),
    ("價值名次", "n"), ("價值總分", "n"), ("動能名次", "n"), ("動能總分", "n"),
    ("技術", ""), ("籌碼", ""),
]

_LEGEND_VALUE = (
    f'<div class="legend">分數組成<span><i style="background:{_FIRST}"></i>防禦50</span>'
    f'<span><i style="background:{_SECOND}"></i>估值30</span>'
    f'<span><i style="background:{_THIRD}"></i>動能20</span>'
    '<span><i style="background:#ece2d4"></i>未取得</span></div>'
)
_LEGEND_MOMENTUM = (
    f'<div class="legend">分數組成<span><i style="background:{_FIRST}"></i>營運動能60</span>'
    f'<span><i style="background:{_SECOND}"></i>品質25</span>'
    f'<span><i style="background:{_THIRD}"></i>估值流動15</span>'
    '<span><i style="background:#ece2d4"></i>未取得</span></div>'
)
_NOTE_INTERSECTION = (
    '<div class="legend">兩個模型的總分尺度不同，不可直接互相比較；'
    '各自的分數組成請切換到該模型分頁查看。</div>'
)

_DELTA_CLASS = {"↑": "up", "↓": "down"}


def _delta_cell(row: dict[str, Any], comparison: dict[str, Any]) -> str:
    text = format_rank_change(row, comparison)
    css = _DELTA_CLASS.get(text[:1], "new" if text == "NEW" else "flat")
    return f'<span class="{css}">{esc(text)}</span>'


def _identity_cells(row: dict[str, Any], comparison: dict[str, Any]) -> list[str]:
    return [
        f'<span class="rk">{int(row["rank"])}</span>',
        _delta_cell(row, comparison),
        f'<span class="mono">{esc(row.get("stock_id"))}</span>',
        f'<span class="nm">{esc(row.get("stock_name"))}</span>',
        f'<span class="dim sm">{esc(row.get("industry"))}</span>',
    ]


def _value_rows(rows: list[dict[str, Any]], comparison: dict[str, Any], enrichment: dict,
                *, expandable: bool = True) -> str:
    out = []
    for row in rows:
        extra = enrichment.get(str(row.get("stock_id")), {})
        bar = score_bar([
            ("防禦", row.get("defense_score"), _FIRST),
            ("估值", row.get("valuation_score"), _SECOND),
            ("動能", row.get("momentum_score"), _THIRD),
        ])
        cells = _identity_cells(row, comparison) + [
            f'<span class="barcell">{bar}</span>',
            f'<span class="n tot">{float(row.get("total_score") or 0):.1f}</span>',
            f'<span class="n">{percent(row.get("net_cash_ratio"))}</span>',
            f'<span class="n">{percent(row.get("liquidation_coverage"))}</span>',
            f'<span class="n">{number(row.get("per"))}</span>',
            f'<span class="n">{number(row.get("pbr"), 2)}</span>',
            f'<span class="n">{percent(row.get("revenue_3m_yoy"))}</span>',
            signal_cells(extra),
        ]
        out.append(list_row(cells, "lgrid-model", detail=detail_block(row, extra) if expandable else ""))
    return "".join(out)


def _momentum_rows(rows: list[dict[str, Any]], comparison: dict[str, Any], enrichment: dict,
                   *, expandable: bool = True) -> str:
    out = []
    for row in rows:
        extra = enrichment.get(str(row.get("stock_id")), {})
        bar = score_bar([
            ("營運動能", row.get("operating_momentum_score"), _FIRST),
            ("品質", row.get("quality_score"), _SECOND),
            ("估值流動性", row.get("valuation_liquidity_score"), _THIRD),
        ])
        cells = _identity_cells(row, comparison) + [
            f'<span class="barcell">{bar}</span>',
            f'<span class="n tot">{float(row.get("total_score") or 0):.1f}</span>',
            f'<span class="n">{percent(row.get("revenue_3m_yoy"))}</span>',
            f'<span class="n">{percent(row.get("revenue_acceleration"))}</span>',
            f'<span class="n">{percent(row.get("ttm_net_income_growth"))}</span>',
            f'<span class="n">{percent(row.get("ttm_operating_margin_change"), 1)}</span>',
            f'<span class="n">{number(row.get("cash_conversion"), 2)}</span>',
            signal_cells(extra),
        ]
        out.append(list_row(cells, "lgrid-model", detail=detail_block(row, extra) if expandable else ""))
    return "".join(out)


def _split_top(rows: list[dict[str, Any]], render, cutoff: int = 5) -> str:
    """精華20 內部再切前 5 與其後。第 1 名與第 20 名的總分常差 10 分以上，
    第 20 與第 21 名卻只差零點幾分——一視同仁會讓眼睛沒有落點。"""
    if len(rows) <= cutoff:
        return render(rows)
    return (
        render(rows[:cutoff])
        + f'<div class="groupsep">第 {cutoff + 1}–{len(rows)} 名</div>'
        + render(rows[cutoff:])
    )


def _listing(head: list[tuple[str, str]], grid_class: str, body: str) -> str:
    return f'<div class="listwrap">{head_row(head, grid_class)}{body}</div>'


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
    value_rest = value_passing[value_focus_size:value_watch_size]
    momentum_rest = momentum_passing[momentum_focus_size:momentum_watch_size]

    value_ok, value_reason = current_report_comparability(value_result)
    momentum_ok, momentum_reason = current_report_comparability(momentum_result)
    same_market_date = value_meta.get("latest_market_date") == momentum_meta.get("latest_market_date")
    comparable = value_ok and momentum_ok and same_market_date

    value_by_id = {str(row["stock_id"]): row for row in value_focus}
    momentum_by_id = {str(row["stock_id"]): row for row in momentum_focus}
    intersection_ids = [sid for sid in value_by_id if sid in momentum_by_id] if comparable else []

    if comparable:
        rows = []
        for sid in intersection_ids:
            v, m = value_by_id[sid], momentum_by_id[sid]
            extra = enrichment.get(sid, {})
            cells = [
                f'<span class="mono ind">{esc(sid)}</span>',
                f'<span class="nm">{esc(v.get("stock_name"))}</span>',
                f'<span class="dim sm">{esc(v.get("industry"))}</span>',
                f'<span class="n">#{int(v["rank"])}</span>',
                f'<span class="n tot">{float(v.get("total_score") or 0):.1f}</span>',
                f'<span class="n">#{int(m["rank"])}</span>',
                f'<span class="n tot">{float(m.get("total_score") or 0):.1f}</span>',
                signal_cells(extra),
            ]
            rows.append(list_row(cells, "lgrid-inter", detail=detail_block(v, extra)))
        if rows:
            intersection = _NOTE_INTERSECTION + _listing(_HEAD_INTERSECTION, "lgrid-inter", "".join(rows))
        else:
            intersection = '<p class="empty">本次兩邊精華20沒有交集。</p>'
        intersection_note = (
            f"同一市場資料日 {esc(value_meta.get('latest_market_date'))}，共 {len(intersection_ids)} 檔。"
        )
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
    statuses = [str(value_meta.get("model_status") or "UNKNOWN"), str(momentum_meta.get("model_status") or "UNKNOWN")]
    overall = "FAIL" if "FAIL" in statuses else "WARN" if any(s != "OK" for s in statuses) else "OK"
    navigation = period_navigation(
        "daily",
        daily_href="index.html",
        weekly_href="../weekly/latest/index.html" if weekly_available else None,
        monthly_href=None,
    )

    def watchlist(rest: list[dict[str, Any]], label: str, body: str) -> str:
        if not rest:
            return ""
        return f'<details class="watchlist"><summary>展開{label}第 21–100 名（{len(rest)} 檔）</summary>{body}</details>'

    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股雙模型監控台｜{esc(value_meta.get('as_of'))}</title>
<style>{portal_css()}</style></head><body><div class="wrap">

<input type="radio" name="tab" id="t-momentum" class="tabin" checked>
<input type="radio" name="tab" id="t-value" class="tabin">
<input type="radio" name="tab" id="t-inter" class="tabin">
<div class="pagebg" aria-hidden="true"></div>

<header class="head">
  <div class="accent"></div>
  <div class="headrow">
    <h1>台股雙模型監控台</h1>
  </div>
  <p class="metaline">
    <span class="statusdot {overall.lower()}"></span>{esc(overall)}
    <em>·</em> 市場日 {esc(value_meta.get('latest_market_date'))}
    <em>·</em> 財報季 {esc(value_meta.get('latest_financial_quarter'))}
    <em>·</em> 營收期 {esc(value_meta.get('latest_revenue_period'))}
  </p>
  <div class="tabrow">
    <div class="tabs">
      <label for="t-momentum">營運動能</label>
      <label for="t-value">防禦價值</label>
      <label for="t-inter">雙模型交集</label>
    </div>
    {navigation}
  </div>
</header>

<section class="panel" id="p-momentum">
  <p class="note">{rank_comparison_note(momentum_comparison)}</p>
  {_LEGEND_MOMENTUM}
  {_listing(_HEAD_MOMENTUM, "lgrid-model", _split_top(momentum_focus, lambda part: _momentum_rows(part, momentum_comparison, enrichment)))}
  {watchlist(momentum_rest, "觀察前100", _listing(_HEAD_MOMENTUM, "lgrid-model", _momentum_rows(momentum_rest, momentum_comparison, enrichment, expandable=False)))}
</section>

<section class="panel" id="p-value">
  <p class="note">{rank_comparison_note(value_comparison)}</p>
  {_LEGEND_VALUE}
  {_listing(_HEAD_VALUE, "lgrid-model", _split_top(value_focus, lambda part: _value_rows(part, value_comparison, enrichment)))}
  {watchlist(value_rest, "自選100", _listing(_HEAD_VALUE, "lgrid-model", _value_rows(value_rest, value_comparison, enrichment, expandable=False)))}
</section>

<section class="panel" id="p-inter">
  <p class="note">{html.escape(intersection_note)} 交集只表示兩套獨立條件同時成立。</p>
  {intersection}
</section>

<div class="audit">
  <h2>資料狀態與模型檢核</h2>
  <div id="status-value" class="model-status">{value_status}</div>
  <div id="status-momentum" class="model-status">{momentum_status}</div>
</div>

<p class="foot">
量化分數只負責縮小研究範圍，不代表預期報酬或買進建議。治理誠信、競爭優勢與新技術催化必須經年報、法說及公開資訊人工查證。
清算價值為折價情境估計，商譽預設為零，不保證股價下檔。<br>
排名變動以「較前一個有效市場觀測」計算；當日資料不合格時不顯示變動，亦不計算雙模型交集。
技術面與籌碼面僅為外部呈現欄位，不進入分數、硬門檻、模型狀態或排名歷史。量化排序不是買進建議。
</p>
</div></body></html>"""


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
