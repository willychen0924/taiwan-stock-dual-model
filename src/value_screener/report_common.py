from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def current_report_comparability(result: dict[str, Any]) -> tuple[bool, str]:
    metadata = result.get("metadata", {})
    if str(metadata.get("model_status") or "UNKNOWN") != "OK":
        return False, f"模型狀態為 {metadata.get('model_status') or 'UNKNOWN'}"

    coverage = metadata.get("revenue_signal_coverage")
    if not isinstance(coverage, dict):
        return False, "缺少營收訊號覆蓋資訊"
    try:
        ranked = float(coverage["ranked"])
        universe = float(coverage["universe"])
        threshold = float(coverage["threshold"])
    except (KeyError, TypeError, ValueError):
        return False, "營收訊號覆蓋資訊不完整"
    if ranked < threshold or universe < threshold:
        return False, "營收訊號覆蓋不足"
    return True, ""


def load_rank_comparison(
    result: dict[str, Any],
    history_path: Path | None,
) -> dict[str, Any]:
    """Select the latest earlier eligible market observation for rank comparison."""
    comparable, reason = current_report_comparability(result)
    comparison: dict[str, Any] = {
        "comparable": comparable,
        "reason": reason,
        "prior_market_date": "",
        "prior_as_of": "",
        "prior_ranks": {},
    }
    if not comparable or history_path is None or not history_path.exists():
        return comparison

    metadata = result.get("metadata", {})
    model_id = str(metadata.get("model_id") or "defensive_value")
    current_market_date = str(metadata.get("latest_market_date") or "")
    best: dict[str, Any] | None = None
    with history_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("model_id") or "") != model_id:
                continue
            if not record.get("eligible_for_backtest"):
                continue
            market_date = str(record.get("latest_market_date") or "")
            if not market_date or market_date >= current_market_date:
                continue
            if best is None or market_date >= str(best.get("latest_market_date") or ""):
                # Replacing on equality deliberately selects the last record in the file.
                best = record

    if best is None:
        return comparison
    comparison["prior_market_date"] = str(best.get("latest_market_date") or "")
    comparison["prior_as_of"] = str(best.get("as_of") or "")
    comparison["prior_ranks"] = {
        str(item.get("stock_id") or ""): int(item["rank"])
        for item in best.get("rankings", [])
        if item.get("stock_id") and item.get("rank") is not None
    }
    return comparison


def format_rank_change(row: dict[str, Any], comparison: dict[str, Any]) -> str:
    if not comparison.get("comparable"):
        return "-"
    if not comparison.get("prior_market_date"):
        return "—"
    previous_rank = comparison.get("prior_ranks", {}).get(str(row.get("stock_id") or ""))
    if previous_rank is None:
        return "NEW"
    current_rank = int(row["rank"])
    change = int(previous_rank) - current_rank
    if change > 0:
        return f"↑{change}"
    if change < 0:
        return f"↓{abs(change)}"
    return "–"


def rank_comparison_note(comparison: dict[str, Any]) -> str:
    if not comparison.get("comparable"):
        return f"排名變化：資料不可比（{html.escape(str(comparison.get('reason') or '本次資料未通過檢核'))}）。"
    if not comparison.get("prior_market_date"):
        return "排名變化：沒有更早且有效的市場觀測可供比較。"
    return (
        "排名變化比較基準：市場資料 "
        f"{html.escape(str(comparison['prior_market_date']))}"
        f"（報表日 {html.escape(str(comparison['prior_as_of']))}）。"
    )


def _format_check_value(value: Any, *, is_rate: bool) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        if is_rate:
            return f"{float(value):.1%}"
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{float(value):,.4f}".rstrip("0").rstrip(".")
    return str(value)


def build_checks_panel(checks: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in checks:
        name = str(item.get("check") or "")
        status = str(item.get("status") or "WARN")
        status_class = status.lower() if status in {"OK", "WARN", "FAIL"} else "warn"
        is_rate = "覆蓋率" in name
        actual = _format_check_value(item.get("actual"), is_rate=is_rate)
        expected = _format_check_value(item.get("expected"), is_rate=is_rate)
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{html.escape(actual)}</td>"
            f"<td>{html.escape(expected)}</td>"
            f'<td><span class="status {status_class}">{html.escape(status)}</span></td>'
            f"<td class=\"check-note\">{html.escape(str(item.get('notes') or ''))}</td>"
            "</tr>"
        )
    return (
        '<div class="checks">'
        "<table><thead><tr><th>檢核名稱</th><th>實際值</th><th>門檻</th><th>狀態</th><th>說明</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def build_freshness_banner(metadata: dict[str, Any]) -> str:
    coverage = metadata.get("revenue_signal_coverage")
    if not isinstance(coverage, dict):
        return '<div class="freshness bad">營收訊號覆蓋資訊缺漏｜動能分數本日不可用</div>'
    try:
        ranked = float(coverage["ranked"])
        universe = float(coverage["universe"])
        threshold = float(coverage["threshold"])
    except (KeyError, TypeError, ValueError):
        return '<div class="freshness bad">營收訊號覆蓋資訊不完整｜動能分數本日不可用</div>'
    label = html.escape(str(coverage.get("signal_label") or "營收訊號"))
    invalid = ranked < threshold or universe < threshold
    warning = "｜動能分數本日不可用" if invalid else ""
    css_class = "freshness bad" if invalid else "freshness good"
    return (
        f'<div class="{css_class}">營收期 {html.escape(str(metadata.get("latest_revenue_period") or "—"))}'
        f"｜排名母體{label}覆蓋 {ranked:.1%}｜一般公司覆蓋 {universe:.1%}{warning}</div>"
    )


def build_monitor_status(
    metadata: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    stats: list[tuple[str, Any]],
    extra_summary: str = "",
) -> str:
    """Build the compact Version-A status strip; abnormal reports open server-side."""
    statuses = [str(item.get("status") or "WARN") for item in checks]
    model_status = str(metadata.get("model_status") or "UNKNOWN")
    abnormal = model_status != "OK" or any(status != "OK" for status in statuses)
    severity = "fail" if model_status == "FAIL" or "FAIL" in statuses else ("warn" if abnormal else "ok")
    open_attribute = " open" if abnormal else ""
    ok_count = sum(status == "OK" for status in statuses)
    coverage = metadata.get("revenue_signal_coverage")
    if isinstance(coverage, dict):
        try:
            ranked = f"{float(coverage['ranked']):.1%}"
            universe = f"{float(coverage['universe']):.1%}"
            threshold = f"{float(coverage['threshold']):.0%}"
            period = html.escape(str(metadata.get("latest_revenue_period") or "—"))
            coverage_text = (
                f"營收期 {period}｜排名母體覆蓋 {ranked}｜一般公司覆蓋 {universe}｜門檻 {threshold}"
            )
        except (KeyError, TypeError, ValueError):
            coverage_text = "營收訊號覆蓋資訊不完整"
    else:
        coverage_text = "營收訊號覆蓋資訊缺漏"

    warning = ""
    if abnormal:
        warning = "｜本次資料或模型檢核異常，排名變化與動能訊號不可直接比較"
    if extra_summary:
        warning += f"｜{html.escape(extra_summary)}"
    stats_html = "｜".join(
        f"{html.escape(label)} <strong>{html.escape(_format_check_value(value, is_rate=False))}</strong>"
        for label, value in stats
    )
    return (
        f'<details class="statusbox {severity}"{open_attribute}>'
        '<summary><span class="status-dot" aria-hidden="true"></span>'
        f'<span class="status-summary">{coverage_text}{warning}</span>'
        f'<span class="check-count">檢核 {ok_count}/{len(checks)} 通過</span></summary>'
        f'<div class="status-stats">{stats_html}</div>'
        f'{build_checks_panel(checks)}'
        '</details>'
    )


def sortable_cell(display: str, sort_value: Any, *, css_class: str = "") -> str:
    class_attribute = f' class="{html.escape(css_class)}"' if css_class else ""
    raw = "" if sort_value is None else str(sort_value)
    return f'<td{class_attribute} data-sort="{html.escape(raw, quote=True)}">{display}</td>'


def score_composition_bar(segments: list[tuple[str, float | None, str]]) -> str:
    normalized: list[tuple[str, float, str]] = []
    total = 0.0
    for label, raw_value, css_class in segments:
        value = max(0.0, float(raw_value or 0.0))
        normalized.append((label, value, css_class))
        total += value
    remainder = max(0.0, 100.0 - total)
    parts = [
        (
            f'<span class="score-segment {html.escape(css_class)}" style="width:{min(value, 100.0):.4f}%" '
            f'title="{html.escape(label, quote=True)} {value:.1f}"></span>'
        )
        for label, value, css_class in normalized
    ]
    parts.append(
        f'<span class="score-segment score-remainder" style="width:{remainder:.4f}%" title="未配置 {remainder:.1f}"></span>'
    )
    label = "／".join(f"{name} {value:.1f}" for name, value, _ in normalized)
    return (
        f'<div class="scorebar" role="img" aria-label="{html.escape(label, quote=True)}">'
        f"{''.join(parts)}</div>"
    )


def monitor_report_css() -> str:
    """Shared Version-A visual system for all standalone HTML reports."""
    return """
:root{--navy:#0f2742;--navy2:#173a5e;--ink:#172033;--muted:#64748b;--line:#dbe4ee;
--first:#16a34a;--second:#1d4ed8;--third:#ea580c;--ok:#15803d;--warn:#b45309;--fail:#b91c1c}
*{box-sizing:border-box} body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif;
margin:0;background:#f1f5f9;color:var(--ink)} .wrap{max-width:1500px;margin:auto;padding:24px}
.hero{background:linear-gradient(120deg,var(--navy),var(--navy2));color:white;border-radius:16px;padding:22px 26px;
display:flex;align-items:center;justify-content:space-between;gap:18px}.hero h1{margin:0 0 6px;font-size:25px}.hero p{margin:0;color:#cfdae7;font-size:13px}
.hero-status{flex:none;border:1px solid #ffffff42;border-radius:999px;padding:7px 12px;font-size:12px;font-weight:800}
.panel{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px;margin-top:16px;overflow:auto;
box-shadow:0 2px 10px #15324f0d}.panel-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:10px}
.panel h2{font-size:18px;margin:0}.note{color:#526174;font-size:12.5px;line-height:1.7}.legend{font-size:12px;color:var(--muted)}
.key-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.key-first{background:var(--first)}
.key-second{background:var(--second)}.key-third{background:var(--third)}
.statusbox{margin-top:14px;background:#fff;border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:12px;overflow:hidden}
.statusbox.warn{border-left-color:var(--warn);background:#fffbeb}.statusbox.fail{border-left-color:var(--fail);background:#fff7f7}
.statusbox summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:9px;padding:12px 14px;font-size:13px}
.statusbox summary::-webkit-details-marker{display:none}.status-dot{width:9px;height:9px;border-radius:50%;background:var(--ok);flex:none}
.statusbox.warn .status-dot{background:var(--warn)}.statusbox.fail .status-dot{background:var(--fail)}
.status-summary{flex:1}.check-count{font-weight:800;white-space:nowrap}.status-stats{padding:10px 14px;border-top:1px solid var(--line);font-size:13px;color:#475569}
.checks{padding:0 14px 14px}.checks table{font-size:12px}.checks th{background:#e9eff6;color:#334155}.checks td{padding:8px}
table{width:100%;border-collapse:collapse;font-size:13.5px}th{background:var(--navy);color:white;text-align:left;padding:10px;white-space:nowrap}
td{padding:12px 10px;border-bottom:1px solid #e7edf4;white-space:nowrap}tbody tr[data-row-id]:hover td{background:#f8fafc}
.sortable{cursor:pointer;user-select:none}.sortable::after{content:" ↕";color:#9fb3c8;font-size:10px}.sortable[data-order="asc"]::after{content:" ↑"}
.sortable[data-order="desc"]::after{content:" ↓"}.total{font-size:15.5px;font-weight:850;color:var(--navy)}
.rank-change{font-weight:800}.composition{min-width:174px}.scorebar{display:flex;width:160px;height:12px;border-radius:999px;overflow:hidden;background:#e2e8f0}
.score-segment{display:block;height:100%}.score-defense,.score-operating{background:var(--first)}
.score-valuation,.score-quality{background:var(--second)}.score-momentum,.score-momentum-valuation{background:var(--third)}
.score-remainder{background:#e2e8f0}.row-detail td{padding:0 10px 9px;background:#f8fafc}.row-detail details{margin:0;border:0;padding:0}
.row-detail summary{font-size:12px;color:#475569;padding:7px 0}.research-grid{display:grid;grid-template-columns:1fr 1fr 2fr;gap:12px;
padding:8px 0 12px;font-size:12.5px;white-space:normal;line-height:1.55}.research-grid b{color:#334155}
.watchlist{margin:14px 0 0;border:1px solid var(--line);border-radius:10px;padding:10px}.watchlist>summary{cursor:pointer;font-weight:800;color:var(--navy)}
.status{display:inline-block;padding:3px 9px;border-radius:999px;font-weight:750}.status.ok{background:#dcfce7;color:#166534}
.status.warn{background:#fef3c7;color:#92400e}.status.fail{background:#fee2e2;color:#991b1b}.unavailable{background:#fee2e2;color:#991b1b;padding:14px;border-radius:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.empty{color:var(--muted)}.copy{line-height:1.8;color:#40564f}.copy h3{color:var(--third);margin-bottom:6px}
@media(max-width:980px){.wrap{padding:12px}.hero{align-items:flex-start;flex-direction:column}.grid{grid-template-columns:1fr}.research-grid{grid-template-columns:1fr}}
"""


def sortable_table_script() -> str:
    return """<script>
document.querySelectorAll('table.sortable-table').forEach((table) => {
  table.querySelectorAll('thead th').forEach((header, index) => {
    header.classList.add('sortable');
    header.tabIndex = 0;
    header.setAttribute('role', 'button');
    const sort = () => {
      const numeric = header.dataset.type === 'number';
      const ascending = header.dataset.order !== 'asc';
      table.querySelectorAll('thead th').forEach((item) => delete item.dataset.order);
      header.dataset.order = ascending ? 'asc' : 'desc';
      const body = table.tBodies[0];
      const allRows = Array.from(body.rows);
      const rows = allRows.filter((row) => !row.dataset.detailFor);
      const detailById = new Map(
        allRows.filter((row) => row.dataset.detailFor).map((row) => [row.dataset.detailFor, row])
      );
      rows.sort((left, right) => {
        const a = left.cells[index]?.dataset.sort ?? '';
        const b = right.cells[index]?.dataset.sort ?? '';
        const comparison = numeric
          ? ((Number(a) || 0) - (Number(b) || 0))
          : a.localeCompare(b, 'zh-Hant', { numeric: true });
        return ascending ? comparison : -comparison;
      });
      rows.forEach((row) => {
        body.appendChild(row);
        const detail = detailById.get(row.dataset.rowId);
        if (detail) body.appendChild(detail);
      });
    };
    header.addEventListener('click', sort);
    header.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); }
    });
  });
});
</script>"""
