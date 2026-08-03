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
        return "資料不可比"
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
        '<div class="panel checks"><h2>模型檢核</h2>'
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
      const rows = Array.from(body.rows);
      rows.sort((left, right) => {
        const a = left.cells[index]?.dataset.sort ?? '';
        const b = right.cells[index]?.dataset.sort ?? '';
        const comparison = numeric
          ? ((Number(a) || 0) - (Number(b) || 0))
          : a.localeCompare(b, 'zh-Hant', { numeric: true });
        return ascending ? comparison : -comparison;
      });
      rows.forEach((row) => body.appendChild(row));
    };
    header.addEventListener('click', sort);
    header.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); }
    });
  });
});
</script>"""
