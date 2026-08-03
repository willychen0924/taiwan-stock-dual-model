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


CSV_FIELDS = [
    "rank",
    "funnel_stage",
    "stock_id",
    "stock_name",
    "industry",
    "market",
    "hard_pass",
    "total_score",
    "defense_score",
    "valuation_score",
    "momentum_score",
    "market_date",
    "close",
    "market_value",
    "avg_daily_turnover",
    "per",
    "pbr",
    "dividend_yield",
    "cash",
    "debt",
    "net_cash_ratio",
    "current_ratio",
    "liabilities_ratio",
    "debt_to_cash",
    "liquidation_value",
    "liquidation_coverage",
    "profitable_years",
    "complete_profit_years",
    "positive_fcf_years",
    "complete_fcf_years",
    "revenue_3m_yoy",
    "latest_revenue_yoy",
    "ttm_operating_margin",
    "ttm_net_income_growth",
    "sector_per_percentile",
    "sector_pbr_percentile",
    "sector_margin_percentile",
    "established_10y",
    "model_summary",
    "governance_status",
    "catalyst",
    "manual_notes",
    "exclusion_reasons",
    "missing_flags",
]

SUMMARY_MIN_CHARS = 50
SUMMARY_MAX_CHARS = 70


def _compact_percent(value: Any) -> str:
    magnitude = abs(float(value))
    if magnitude >= 10:
        return "逾999%"
    return f"{magnitude:.0%}"


def _qualitative_clause(row: dict[str, Any]) -> str:
    status = row.get("governance_status") or "待複核"
    if row.get("manual_exclude") or status == "否決":
        return "治理覆核為否決，列入人工排除"
    if status == "通過" and row.get("catalyst"):
        return "治理與催化已完成人工覆核"
    if status == "通過":
        return "治理已通過，催化內容仍待查證"
    return "治理與催化仍需公開資訊查證"


def _risk_clause(row: dict[str, Any], min_turnover: float) -> str:
    revenue_3m = row.get("revenue_3m_yoy")
    net_income_growth = row.get("ttm_net_income_growth")
    per = row.get("per")
    operating_margin = row.get("ttm_operating_margin")
    turnover = row.get("avg_daily_turnover")
    liquidation_coverage = row.get("liquidation_coverage")

    if revenue_3m is not None and float(revenue_3m) < 0:
        return f"近三月營收年減{_compact_percent(revenue_3m)}"
    if net_income_growth is not None and float(net_income_growth) < 0:
        return f"TTM淨利年減{_compact_percent(net_income_growth)}"
    if per is not None and float(per) >= 30:
        return f"本益比{float(per):.1f}倍偏高"
    if operating_margin is not None and float(operating_margin) < 0.05:
        return f"營益率僅{float(operating_margin):.1%}"
    if turnover is not None and float(turnover) < min_turnover * 1.5:
        return "成交額接近流動性門檻"
    if liquidation_coverage is not None and float(liquidation_coverage) < 0.2:
        return "清算覆蓋偏低"
    return "估值與成長持續性仍需追蹤"


def _passing_detail_clauses(row: dict[str, Any]) -> list[str]:
    clauses: list[str] = []
    current_ratio = row.get("current_ratio")
    positive_fcf_years = row.get("positive_fcf_years")
    profitable_years = row.get("profitable_years")
    revenue_3m = row.get("revenue_3m_yoy")
    per = row.get("per")
    net_cash_ratio = row.get("net_cash_ratio")
    liquidation_coverage = row.get("liquidation_coverage")
    net_income_growth = row.get("ttm_net_income_growth")
    turnover = row.get("avg_daily_turnover")
    score = row.get("total_score")

    if current_ratio is not None:
        clauses.append(f"流動比率{float(current_ratio):.1f}倍")
    if positive_fcf_years is not None and int(positive_fcf_years) >= 5:
        clauses.append("五年自由現金流皆正")
    elif positive_fcf_years is not None:
        clauses.append(f"五年中{int(positive_fcf_years)}年自由現金流為正")
    elif profitable_years is not None:
        clauses.append(f"連續{int(profitable_years)}年獲利")
    if revenue_3m is not None and float(revenue_3m) >= 0:
        clauses.append(f"近三月營收年增{_compact_percent(revenue_3m)}")
    if per is not None:
        clauses.append(f"本益比{float(per):.1f}倍")
    if net_cash_ratio is not None and float(net_cash_ratio) > 0:
        clauses.append(f"淨現金占市值{_compact_percent(net_cash_ratio)}")
    if liquidation_coverage is not None and float(liquidation_coverage) > 0:
        clauses.append(f"清算覆蓋{_compact_percent(liquidation_coverage)}")
    if net_income_growth is not None and float(net_income_growth) >= 0:
        clauses.append(f"TTM淨利年增{_compact_percent(net_income_growth)}")
    if score is not None:
        clauses.append(f"量化總分{float(score):.1f}分")
    if turnover is not None:
        clauses.append(f"20日均成交額{float(turnover) / 1_000_000:.0f}百萬元")
    return clauses or ["可用量化欄位有限"]


def _failed_detail_clauses(row: dict[str, Any]) -> list[str]:
    reasons = [item for item in str(row.get("exclusion_reasons") or "").split("；") if item]
    reason_aliases = {
        "有息負債高於現金門檻": "有息負債偏高",
        "20日均成交金額不足": "成交金額不足",
        "負債比率超標或缺漏": "負債比率未達標",
    }
    clauses = [f"主要原因為{reason_aliases.get(reason, reason)}" for reason in reasons]
    score = row.get("total_score")
    if score is not None:
        clauses.append(f"量化總分{float(score):.1f}分")
    turnover = row.get("avg_daily_turnover")
    if turnover is not None:
        clauses.append(f"20日均成交額{float(turnover) / 1_000_000:.0f}百萬元")
    return clauses or ["未通過原因資料待確認"]


def build_model_summary(row: dict[str, Any], min_turnover: float = 20_000_000) -> str:
    """Build an auditable 50-70 character summary from model fields only."""
    name = str(row.get("stock_name") or row.get("stock_id") or "公司")
    passed = bool(row.get("hard_pass"))
    prefix = f"{name}{'通過' if passed else '未通過'}硬門檻，"
    qualitative = _qualitative_clause(row)
    if passed:
        risk = _risk_clause(row, min_turnover)

        def compose(details: list[str]) -> str:
            return f"{prefix}{'、'.join(details)}；惟{risk}，{qualitative}。"

        candidates = _passing_detail_clauses(row)
    else:
        def compose(details: list[str]) -> str:
            return f"{prefix}{'、'.join(details)}；{qualitative}。"

        candidates = _failed_detail_clauses(row)

    selected: list[str] = []
    for clause in candidates:
        candidate = compose([*selected, clause])
        if len(candidate) <= SUMMARY_MAX_CHARS:
            selected.append(clause)
        if len(selected) >= 3 and len(compose(selected)) >= SUMMARY_MIN_CHARS:
            break

    summary = compose(selected or [candidates[0]])
    if len(summary) < SUMMARY_MIN_CHARS:
        filler = "量化資料仍需搭配後續基本面變化判讀"
        candidate = summary[:-1] + f"，{filler}。"
        if len(candidate) <= SUMMARY_MAX_CHARS:
            summary = candidate
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[: SUMMARY_MAX_CHARS - 1].rstrip("，、；") + "。"
    return summary


def write_reports(
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

    min_turnover = float(result["config"]["hard_gates"]["min_avg_daily_turnover_twd"])
    for row in result["results"]:
        row["model_summary"] = build_model_summary(row, min_turnover)

    json_path = dated_dir / "screening_results.json"
    csv_path = dated_dir / "screening_results.csv"
    html_path = dated_dir / "screening_report.html"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["results"])

    html_path.write_text(_build_html(result, history_path=history_path), encoding="utf-8")

    for source in (json_path, csv_path, html_path):
        shutil.copy2(source, latest_dir / source.name)
    return {"json": json_path, "csv": csv_path, "html": html_path}


def _format_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def _format_percent(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1%}"


def _build_html(result: dict[str, Any], *, history_path: Path | None = None) -> str:
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
            f"<td>{_format_number(row['per'])}</td>"
            f"<td>{_format_percent(row['net_cash_ratio'])}</td>"
            f"<td>{_format_percent(row['liquidation_coverage'])}</td>"
            f"<td>{_format_percent(row['revenue_3m_yoy'])}</td>"
            f"<td class=\"summary\">{html.escape(row['model_summary'])}</td>"
            f"<td>{html.escape(row['governance_status'])}</td>"
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
<title>台股防禦型價值篩選｜{html.escape(meta['as_of'])}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif;margin:0;background:#f4f7fb;color:#172033}}
.wrap{{max-width:1280px;margin:0 auto;padding:32px}}
.hero{{background:#12263f;color:white;border-radius:18px;padding:28px 32px}}
.hero h1{{margin:0 0 8px;font-size:28px}} .hero p{{margin:0;color:#c8d6e5}}
.freshness{{margin-top:14px;padding:10px 14px;border-radius:10px;font-size:14px;font-weight:650}} .freshness.good{{background:#dcfce7;color:#14532d}} .freshness.bad{{background:#fee2e2;color:#991b1b}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:18px 0}}
.card{{background:white;border-radius:14px;padding:18px;box-shadow:0 2px 14px #15324f14}}
.card b{{display:block;font-size:24px;color:#0f766e}} .card span{{font-size:13px;color:#64748b}}
.panel{{background:white;border-radius:14px;padding:20px;margin-top:18px;overflow:auto;box-shadow:0 2px 14px #15324f14}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th{{background:#12263f;color:white;text-align:left;padding:10px;white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid #e7edf4;white-space:nowrap}} td.summary,td.check-note{{min-width:24rem;white-space:normal;line-height:1.6}} td.rank-change{{font-weight:700}} tr:hover td{{background:#f0fdfa}}
.status{{display:inline-block;padding:3px 9px;border-radius:999px;font-weight:750}} .status.ok{{background:#dcfce7;color:#166534}} .status.warn{{background:#fef3c7;color:#92400e}} .status.fail{{background:#fee2e2;color:#991b1b}}
.note{{margin-top:18px;color:#526174;font-size:13px;line-height:1.7}}
@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}.wrap{{padding:16px}}}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><h1>台股防禦型價值篩選</h1><p>資料日 {html.escape(meta['latest_market_date'])}｜完整財報季 {html.escape(meta['latest_financial_quarter'])}｜研究候選，不是買進建議</p>{freshness}</div>
<div class="cards">
<div class="card"><b>{meta['universe_count']:,}</b><span>普通股母體</span></div>
<div class="card"><b>{meta['operating_company_count']:,}</b><span>一般公司模型</span></div>
<div class="card"><b>{meta['hard_pass_count']:,}</b><span>硬門檻通過</span></div>
<div class="card"><b>{meta['watchlist_count']:,}</b><span>自選 100</span></div>
<div class="card"><b>{meta['focus_count']:,}</b><span>精華 20</span></div>
</div>
<div class="panel"><h2>精華候選</h2><p class="note">{comparison_note}</p><table><thead><tr><th>排名</th><th>較前次</th><th>代碼</th><th>公司</th><th>產業</th><th>總分</th><th>PER</th><th>淨現金/市值</th><th>清算覆蓋</th><th>近3月營收YoY</th><th>模型短評（自動）</th><th>治理</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{checks_panel}
<p class="note">量化分數只負責縮小研究範圍。治理誠信、競爭優勢、AI／機器人／矽光子等催化必須經法說、年報與公開資訊人工查證。清算價值採折價估計，商譽預設為零，不保證股價下檔。</p>
</div></body></html>"""
