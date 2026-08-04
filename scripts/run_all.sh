#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
AS_OF="${1:-$(date +%F)}"
if (( $# > 0 )); then
  shift
fi
CODEX_RUNTIME="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
DEFAULT_PYTHON="python3"
DEFAULT_NODE="node"
[[ -x "$CODEX_RUNTIME/python/bin/python3" ]] && DEFAULT_PYTHON="$CODEX_RUNTIME/python/bin/python3"
[[ -x "$CODEX_RUNTIME/node/bin/node" ]] && DEFAULT_NODE="$CODEX_RUNTIME/node/bin/node"
PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON}"
NODE_BIN="${NODE_BIN:-$DEFAULT_NODE}"

cd "$ROOT"
"$PYTHON_BIN" scripts/run_screen.py --as-of "$AS_OF" "$@"
"$PYTHON_BIN" scripts/update_rankings_history.py
if ! "$PYTHON_BIN" scripts/build_technical_chip_enrichment.py --as-of "$AS_OF" --top-n 5; then
  print -u2 "警告：技術面／籌碼面更新失敗；基本面模型與排名歷史已完成，報表將顯示既有資料或 —。"
fi
"$PYTHON_BIN" scripts/build_weekly_report.py --as-of "$AS_OF"
"$PYTHON_BIN" scripts/build_portal.py

EXCEL_AVAILABLE=1
if ! "$NODE_BIN" --version >/dev/null 2>&1; then
  EXCEL_AVAILABLE=0
  print -u2 "警告：找不到可用的 Node.js；JSON、CSV、HTML 與排名歷史已完成，略過 Excel。"
elif ! "$NODE_BIN" -e 'import("@oai/artifact-tool")' >/dev/null 2>&1; then
  EXCEL_AVAILABLE=0
  print -u2 "警告：找不到 @oai/artifact-tool（預期版本見 config/report_toolchain.json）；JSON、CSV、HTML 與排名歷史已完成，略過 Excel。"
fi

if (( EXCEL_AVAILABLE )); then
  "$NODE_BIN" scripts/build_report.mjs \
    reports/latest/screening_results.json \
    "outputs/${AS_OF}/台股防禦價值篩選_${AS_OF}.xlsx"
  "$NODE_BIN" scripts/build_momentum_report.mjs \
    reports/momentum/latest/screening_results.json \
    "outputs/${AS_OF}/台股營運動能篩選_${AS_OF}.xlsx"
fi

"$PYTHON_BIN" scripts/cleanup_old_reports.py --as-of "$AS_OF"

print "完成：reports/latest 與 reports/momentum/latest 的 JSON、CSV、HTML"
if (( EXCEL_AVAILABLE )); then
  print "完成：outputs/${AS_OF}/台股防禦價值篩選_${AS_OF}.xlsx"
  print "完成：outputs/${AS_OF}/台股營運動能篩選_${AS_OF}.xlsx"
else
  print "Excel：本次略過；補齊 config/report_toolchain.json 所列工具鏈後可單獨重建。"
fi
