"""入口頁版面：暖石陶土配色、純 CSS 分頁、逐列 details 展開。

設計約束（與模型無關，但影響可用性，改動前請先確認）：

* 分頁與逐列展開一律使用原生機制（radio + ``:checked``、``<details>``），
  不得依賴 JavaScript——禁用 script 的環境仍必須能切換分頁與展開明細。
* 純 CSS 分頁的 radio 必須與所有受控元素同層；包進卡片會讓 ``~`` 兄弟選擇器失效。
* 技術面／籌碼面只是呈現欄位，不進入分數、硬門檻或模型狀態。
"""

from __future__ import annotations

import html
from typing import Any

# 分數組成三色。明度刻意拉開（L* 59 / 40 / 60）：小色塊主要靠明暗分辨，
# 色相是次要線索，兩色明度相近時無論色相差多少都難以區分。
SCORE_COLORS = {"first": "#5c9b62", "second": "#1e5fae", "third": "#eb6834"}

# 欄寬依標題字數估算（11.5px 粗體，中文約 11.5px、拉丁約 6px，色點另計 13px）。
COLS_VALUE = "40px 50px 62px 90px 94px 106px 64px 78px 78px 78px 78px 78px 68px 70px"
COLS_MOMENTUM = COLS_VALUE
COLS_INTERSECTION = "66px 104px 112px 72px 78px 72px 78px 68px 70px"

_COLUMN_GAP = 14
_ROW_PADDING = 32


def grid_min_width(cols: str) -> int:
    parts = cols.split()
    return sum(int(part[:-2]) for part in parts) + (len(parts) - 1) * _COLUMN_GAP + _ROW_PADDING


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def percent(value: Any, digits: int = 0) -> str:
    return "—" if value is None else f"{float(value) * 100:.{digits}f}%"


def number(value: Any, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value):,.{digits}f}"


def score_bar(segments: list[tuple[str, Any, str]]) -> str:
    """固定 100 分尺度；未取得的分數留灰，不重新正規化。"""
    used = 0.0
    parts: list[str] = []
    labels: list[str] = []
    for label, raw, color in segments:
        value = max(0.0, float(raw or 0.0))
        used += value
        labels.append(f"{label} {value:.1f}")
        parts.append(f'<i style="width:{min(value, 100.0):.2f}%;background:{color}"></i>')
    parts.append(f'<i style="width:{max(0.0, 100.0 - used):.2f}%"></i>')
    # 整條給一個 aria-label 就夠；逐段 title 在 200 列的頁面上是純粹的體積
    return f'<span class="bar" role="img" aria-label="{esc("／".join(labels))}">{"".join(parts)}</span>'


def head_row(columns: list[tuple[str, str]], grid_class: str) -> str:
    cells = "".join(f'<span class="{css}">{label}</span>' for label, css in columns)
    return f'<div class="lhead {grid_class}">{cells}</div>'


def signal_cells(extra: dict[str, str]) -> str:
    if not extra:
        return '<span class="sig dim">—</span><span class="sig dim">—</span>'
    out = []
    for prefix in ("technical", "chip"):
        status = extra.get(f"{prefix}_status") or extra.get(prefix) or ""
        if not status or status == "—":
            out.append('<span class="sig dim">—</span>')
            continue
        tone = extra.get(f"{prefix}_tone") or "mid"
        out.append(f'<span class="sig"><b class="sigchip {esc(tone)}">{esc(status)}</b></span>')
    return "".join(out)


def detail_block(row: dict[str, Any], extra: dict[str, str]) -> str:
    """展開後的明細：標籤靠左、內文靠右，不再包卡片。"""
    lines = [
        f'<div class="drow"><dt>模型短評</dt><dd>{esc(row.get("model_summary") or "—")}</dd></div>'
    ]
    for label, prefix in (("技術面", "technical"), ("籌碼面", "chip")):
        status = extra.get(f"{prefix}_status") or ""
        summary = extra.get(f"{prefix}_summary") or ""
        if not status and not summary:
            fallback = extra.get(prefix) or ""
            if not fallback or fallback == "—":
                lines.append(f'<div class="drow"><dt>{label}</dt><dd class="dim">—</dd></div>')
                continue
            summary = fallback
        chip = (
            f'<span class="sigchip {esc(extra.get(f"{prefix}_tone") or "mid")}">{esc(status)}</span>'
            if status
            else ""
        )
        lines.append(f'<div class="drow"><dt>{label}</dt><dd>{chip}{esc(summary)}</dd></div>')
    return f'<dl class="dwrap">{"".join(lines)}</dl>'


def list_row(cells: list[str], grid_class: str, *, detail: str = "") -> str:
    """一列一檔。detail 為空時該列不可展開（第 21–100 名採此形式，避免頁面過大）。"""
    body = f'<summary>{"".join(cells)}</summary>{detail}'
    if not detail:
        return f'<div class="lrow flatrow {grid_class}"><div class="rowline">{"".join(cells)}</div></div>'
    return f'<details class="lrow {grid_class}">{body}</details>'


def portal_css() -> str:
    first, second, third = SCORE_COLORS["first"], SCORE_COLORS["second"], SCORE_COLORS["third"]
    model_cols, inter_cols = COLS_VALUE, COLS_INTERSECTION
    model_min, inter_min = grid_min_width(COLS_VALUE), grid_min_width(COLS_INTERSECTION)
    return f"""
*{{box-sizing:border-box}}
body{{margin:0;background:#faf6ef;color:#251f19;font-size:13px;
 font-family:system-ui,-apple-system,"PingFang TC","Noto Sans TC","Segoe UI",sans-serif;
 -webkit-font-smoothing:antialiased}}
.wrap{{max-width:1500px;margin:0 auto;padding:18px 22px 48px}}

/* 分頁控制項：必須與面板、狀態區同層，否則 ~ 選擇器跨不過去 */
.tabin{{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}}

.head{{background:#fffdfa;border:1px solid rgba(37,31,25,.09);border-radius:16px;
 padding:0 24px 4px;overflow:hidden;
 box-shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -16px rgba(11,11,11,.12)}}
.accent{{height:3px;margin:0 -24px 18px;
 background:linear-gradient(90deg,{first} 0 34%,{second} 34% 67%,{third} 67% 100%)}}
.headrow{{display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.head h1{{margin:0;font-size:25px;font-weight:800;letter-spacing:-.4px;color:#251f19;line-height:1.2}}
.metaline{{margin:7px 0 0;font-size:12.5px;color:#6d6055;display:flex;align-items:center;gap:7px;
 flex-wrap:wrap}}
.metaline em{{font-style:normal;color:#d9cdbb}}
.statusdot{{width:7px;height:7px;border-radius:99px;background:#a89b8b;display:inline-block}}
.statusdot.warn{{background:#c07a1e}}.statusdot.fail{{background:#d03b3b}}

.period-nav{{display:inline-flex;gap:2px;background:#f1e8db;padding:3px;
 border-radius:999px;flex:none}}
/* 尺寸與模型分頁一致，緊鄰其右；選中樣式刻意不同，區分主要動作與次要導覽 */
.period-link{{padding:8px 20px;border-radius:999px;font-size:14.5px;text-decoration:none;
 color:#6d6055;font-weight:600;white-space:nowrap;transition:background .15s,color .15s}}
a.period-link:hover{{background:#e8dcc9;color:#3a2c22}}
.period-link.active{{background:#fffdfa;color:#251f19;font-weight:700;
 box-shadow:0 1px 2px rgba(11,11,11,.12)}}
.period-link.disabled{{color:#c6b9a6;cursor:not-allowed}}

.tabrow{{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:18px 0 20px}}
.tabs{{display:inline-flex;background:#f1e8db;border-radius:999px;padding:3px;gap:2px}}
.tabs label{{padding:8px 20px;font-size:14.5px;cursor:pointer;color:#6d6055;font-weight:600;
 border-radius:999px;user-select:none;transition:background .15s,color .15s;white-space:nowrap}}
.tabs label:hover{{background:#e8dcc9}}
#t-momentum:checked ~ .head .tabs label[for=t-momentum],
#t-value:checked    ~ .head .tabs label[for=t-value],
#t-inter:checked    ~ .head .tabs label[for=t-inter]{{background:#3a2c22;color:#fff;font-weight:700}}

.panel{{padding:18px 0 0;display:none}}
#t-momentum:checked ~ #p-momentum,
#t-value:checked    ~ #p-value,
#t-inter:checked    ~ #p-inter{{display:block}}

.legend{{display:flex;gap:11px;align-items:center;font-size:11.5px;color:#a89b8b;margin-bottom:8px;
 flex-wrap:wrap}}
.legend span{{white-space:nowrap}}
.legend i{{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:5px;
 vertical-align:-1px}}

.listwrap{{background:#fffdfa;border:1px solid rgba(37,31,25,.09);border-radius:16px;
 overflow-x:auto;box-shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -16px rgba(11,11,11,.12)}}
.lgrid-model{{--cols:{model_cols};--minw:{model_min}px}}
.lgrid-inter{{--cols:{inter_cols};--minw:{inter_min}px}}
.lrow.flatrow>.rowline,.lhead,.lrow>summary{{display:grid;grid-template-columns:var(--cols);align-items:center;
 gap:0 {_COLUMN_GAP}px;padding:0 16px;min-width:var(--minw,1200px);width:100%}}
.lhead{{background:#f6efe4;border-bottom:1px solid #ece2d4;color:#6d6055;font-size:11.5px;
 font-weight:700;padding-top:9px;padding-bottom:9px;position:sticky;top:0;z-index:2;
 align-items:end;line-height:1.32;min-width:var(--minw,1200px)}}
.lhead span{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
/* 資料列首欄有展開三角的 13px 內距，表頭要跟上才不會整排看起來歪掉 */
.lhead span:first-child{{padding-left:13px}}
.lhead .k1:before,.lhead .k2:before,.lhead .k3:before{{content:"";display:inline-block;
 width:8px;height:8px;border-radius:2px;margin-right:5px}}
.lhead .k1:before{{background:{first}}}
.lhead .k2:before{{background:{second}}}
.lhead .k3:before{{background:{third}}}

.lrow{{border-bottom:1px solid #f1e8db;min-width:var(--minw,1200px)}}
.lrow.flatrow>.rowline{{padding-top:11px;padding-bottom:11px;font-size:13.5px}}
.lrow>summary{{list-style:none;cursor:pointer;padding-top:11px;padding-bottom:11px;font-size:13.5px}}
.lrow>summary::-webkit-details-marker{{display:none}}
.lrow>summary:hover{{background:#f3ebde}}
.lrow[open]>summary{{background:#f6efe4}}
.lrow .rk,.lrow .ind{{color:#a89b8b;font-variant-numeric:tabular-nums;position:relative;
 padding-left:13px}}
.lrow .ind{{color:#2a78d6}}
.lrow .rk:before,.lrow .ind:before{{content:"▸";position:absolute;left:0;color:#d9cdbb;
 font-size:10px;transition:transform .12s;display:inline-block}}
.lrow[open] .rk:before,.lrow[open] .ind:before{{transform:rotate(90deg);color:#3a2c22}}
.lrow .nm{{font-weight:700;font-size:14.5px;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}}
.lrow .n,.lhead .n{{text-align:right;font-variant-numeric:tabular-nums}}
.lrow .tot{{font-weight:700;color:#251f19;font-size:15.5px}}
.lrow .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#2a78d6;font-size:13px}}
.lrow .sm{{font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.lrow .dim,.lhead .dim{{color:#a89b8b}}
.barcell{{display:flex;align-items:center}}
.bar{{display:inline-flex;width:100%;height:8px;border-radius:99px;overflow:hidden;
 background:#ece2d4;vertical-align:middle}}
.bar i{{display:block;height:100%}}
.up{{color:#3f6b46;font-weight:600}}.down{{color:#b8452a;font-weight:600}}
.flat{{color:#a89b8b}}.new{{color:#8a5aa8;font-weight:600}}

/* 技術／籌碼來自外部檔案，與模型欄位之間留一道分隔 */
.lrow .sig:nth-last-child(2),.lhead span:nth-last-child(2){{margin-left:10px;
 border-left:1px solid #ece2d4;padding-left:14px}}
.sigchip{{display:inline-block;padding:2px 9px;border-radius:6px;font-size:11.5px;font-weight:600;
 white-space:nowrap;font-style:normal}}
.sigchip.up{{background:#e7f0e3;color:#3f6b46}}
.sigchip.mid{{background:#f1e8db;color:#6d6055}}
.sigchip.down{{background:#fae5dd;color:#b8452a}}

.dwrap{{margin:0;padding:3px 16px 14px;background:#f6efe4}}
.drow{{display:grid;grid-template-columns:66px 1fr;gap:14px;padding:7px 0;align-items:baseline}}
.drow+.drow{{border-top:1px dotted #e4d9c8}}
.drow dt{{font-size:11.5px;font-weight:700;color:#a89b8b;white-space:nowrap;letter-spacing:.3px}}
.drow dd{{margin:0;font-size:12.5px;line-height:1.8;color:#6d6055}}
.drow dd .sigchip{{margin-right:8px;vertical-align:1px}}

.watchlist>summary{{cursor:pointer;color:#3a2c22;font-size:12.5px;padding:11px 2px;font-weight:600}}
.note{{color:#6d6055;font-size:12.5px;line-height:1.75;margin:0 0 12px}}
.empty,.unavailable{{color:#6d6055;font-size:12.5px;line-height:1.75;margin:0 0 12px}}

/* 資料狀態：正常時安靜，異常時自動展開並轉為警示色 */
.audit{{margin-top:26px;padding-top:14px;border-top:1px solid #e4d9c8}}
.audit h2{{font-size:11.5px;color:#6d6055;margin:0 0 8px;font-weight:700;letter-spacing:.5px}}
.model-status{{display:none}}
#t-momentum:checked ~ .audit #status-momentum,
#t-value:checked    ~ .audit #status-value,
#t-inter:checked    ~ .audit #status-value,
#t-inter:checked    ~ .audit #status-momentum{{display:block}}
.statusbox{{margin:0 0 2px;font-size:12.5px}}
.statusbox.ok{{color:#6d6055}}
.statusbox.warn,.statusbox.fail{{background:rgba(208,59,59,.07);border-left:4px solid #d03b3b;border-radius:8px;
 color:#a8331f;margin-bottom:8px}}
.statusbox summary{{list-style:none;cursor:pointer;padding:5px 2px;display:flex;align-items:center;
 gap:10px;flex-wrap:wrap}}
.statusbox.warn summary,.statusbox.fail summary{{padding:8px 13px}}
.statusbox summary::-webkit-details-marker{{display:none}}
.statusbox summary:after{{content:"▾";margin-left:auto;opacity:.5;font-size:11px}}
.statusbox[open] summary:after{{content:"▴"}}
.statusbox .status-dot{{width:7px;height:7px;border-radius:99px;flex:none;background:#a89b8b}}
.statusbox.warn .status-dot,.statusbox.fail .status-dot{{background:#d03b3b;width:8px;height:8px}}
.statusbox .check-count{{margin-left:14px;opacity:.8;white-space:nowrap}}
.statusbox.ok .status-summary strong{{color:#4a3f35;font-weight:700}}
.statusbox .checks{{background:#f6efe4;border:1px solid #f1e8db;border-radius:8px;margin:2px 0 0;
 overflow:hidden}}
.statusbox .status-stats{{padding:9px 12px 8px;border-bottom:1px solid #f1e8db;color:#6d6055;
 line-height:1.5}}
.statusbox .status-stats strong{{color:#4a3f35;font-variant-numeric:tabular-nums;font-weight:700;
 font-size:13.5px}}
.statusbox table{{width:100%;border-collapse:collapse}}
.statusbox thead th{{text-align:left;padding:7px 12px;font-size:11px;color:#6d6055;font-weight:600;
 border-bottom:1px solid #ece2d4;background:transparent}}
.statusbox td{{padding:6px 12px;border-bottom:1px solid #f1e8db}}
.statusbox td:nth-child(2),.statusbox td:nth-child(3),
.statusbox th:nth-child(2),.statusbox th:nth-child(3){{text-align:right;
 font-variant-numeric:tabular-nums}}
.statusbox .check-note{{color:#a89b8b}}
.status{{display:inline-block;padding:1px 8px;border-radius:5px;font-size:10.5px;font-weight:700}}
.status.ok{{background:#e7f0e3;color:#3f6b46}}
.status.warn{{background:#fbf0dc;color:#8a5a1a}}
.status.fail{{background:#fae5dd;color:#a8331f}}

.foot{{margin-top:10px;color:#6d6055;font-size:11.5px;line-height:1.55}}
@media(max-width:760px){{.wrap{{padding:14px 12px 40px}}.head{{padding:0 16px 4px}}
 .accent{{margin:0 -16px 14px}}
 .tabs label,.period-link{{padding:8px 14px;font-size:13.5px}}}}
"""
