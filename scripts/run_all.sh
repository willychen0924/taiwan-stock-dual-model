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
"$NODE_BIN" scripts/build_report.mjs \
  reports/latest/screening_results.json \
  "outputs/${AS_OF}/台股價值篩選_${AS_OF}.xlsx"
"$NODE_BIN" scripts/build_momentum_report.mjs \
  reports/momentum/latest/screening_results.json \
  "outputs/${AS_OF}/台股營運動能_${AS_OF}.xlsx"
"$PYTHON_BIN" scripts/cleanup_old_reports.py --as-of "$AS_OF" --keep-days 7

print "完成：outputs/${AS_OF}/台股價值篩選_${AS_OF}.xlsx"
print "完成：outputs/${AS_OF}/台股營運動能_${AS_OF}.xlsx"
