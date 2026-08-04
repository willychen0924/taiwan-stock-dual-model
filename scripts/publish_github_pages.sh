#!/bin/zsh
set -euo pipefail

ROOT="${PROJECT_ROOT:-${0:A:h:h}}"
AS_OF="${1:-$(date +%F)}"
DAILY_SOURCE="$ROOT/reports/latest/index.html"
WEEKLY_SOURCE="$ROOT/reports/weekly/latest/index.html"
ROOT_TEMPLATE="$ROOT/docs/github_pages_index.html"

for required in "$DAILY_SOURCE" "$WEEKLY_SOURCE" "$ROOT_TEMPLATE"; do
  if [[ ! -f "$required" ]]; then
    print -u2 "GitHub Pages 發布失敗：找不到 $required"
    exit 1
  fi
done

REMOTE_URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)"
if [[ -z "$REMOTE_URL" ]]; then
  print -u2 "GitHub Pages 發布失敗：Git repository 沒有 origin。"
  exit 1
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/taiwan-stock-pages.XXXXXX")"
SITE_ROOT="$TEMP_ROOT/site"
cleanup() {
  if [[ -n "${TEMP_ROOT:-}" && "$TEMP_ROOT" == *"/taiwan-stock-pages."* && -d "$TEMP_ROOT" ]]; then
    rm -rf -- "$TEMP_ROOT"
  fi
}
trap cleanup EXIT

if git ls-remote --exit-code --heads "$REMOTE_URL" gh-pages >/dev/null 2>&1; then
  git clone --quiet --depth 1 --branch gh-pages "$REMOTE_URL" "$SITE_ROOT"
else
  mkdir -p "$SITE_ROOT"
  git -C "$SITE_ROOT" init --quiet
  git -C "$SITE_ROOT" switch --orphan gh-pages >/dev/null
  git -C "$SITE_ROOT" remote add origin "$REMOTE_URL"
fi

mkdir -p "$SITE_ROOT/reports/latest" "$SITE_ROOT/reports/weekly/latest"
cp "$ROOT_TEMPLATE" "$SITE_ROOT/index.html"
cp "$DAILY_SOURCE" "$SITE_ROOT/reports/latest/index.html"
cp "$WEEKLY_SOURCE" "$SITE_ROOT/reports/weekly/latest/index.html"
touch "$SITE_ROOT/.nojekyll"

git -C "$SITE_ROOT" add .nojekyll index.html reports/latest/index.html reports/weekly/latest/index.html
if git -C "$SITE_ROOT" diff --cached --quiet; then
  print "GitHub Pages：內容沒有變更，略過推送。"
  exit 0
fi

AUTHOR_NAME="$(git -C "$ROOT" config user.name || true)"
AUTHOR_EMAIL="$(git -C "$ROOT" config user.email || true)"
git -C "$SITE_ROOT" config user.name "${AUTHOR_NAME:-Taiwan Stock Report Bot}"
git -C "$SITE_ROOT" config user.email "${AUTHOR_EMAIL:-report-bot@users.noreply.github.com}"
git -C "$SITE_ROOT" commit --quiet -m "Publish reports $AS_OF"
git -C "$SITE_ROOT" push --quiet origin gh-pages
print "GitHub Pages：已發布日報與週報（$AS_OF）。"
