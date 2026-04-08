#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Create it and install dependencies first."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the Starlight site."
  exit 1
fi

echo "[1/3] Generating topic pages + explorer payloads, then building Starlight"
.venv/bin/python site/build_site.py --config config.yaml --strict

echo "[2/3] Preflight checks for explorer assets"
for p in \
  "site/src/content/docs/explorer.mdx" \
  "site/public/javascripts/explorer.js" \
  "site/public/assets/explorer_graph_lite.json" \
  "site/public/assets/explorer_details_lite.json" \
  "site/public/assets/explorer_graph.json" \
  "site/public/assets/explorer_details.json" \
  "site/dist/index.html"
do
  if [[ ! -f "$p" ]]; then
    echo "Missing required file: $p"
    exit 1
  fi
done

echo "[3/3] Pushing site/dist to gh-pages branch"
# Use the same publish strategy as the GitHub Actions workflow: orphaned
# gh-pages branch built from site/dist. This relies on the `gh` CLI being
# present locally; for unattended deploys use the GitHub Actions workflow.
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
git worktree add "$TMPDIR" gh-pages 2>/dev/null || git worktree add -b gh-pages "$TMPDIR"
rsync -a --delete --exclude '.git' site/dist/ "$TMPDIR"/
(cd "$TMPDIR" && git add -A && git commit -m "Deploy site $(date -u +%Y-%m-%dT%H:%M:%SZ)" || true)
(cd "$TMPDIR" && git push origin gh-pages)
git worktree remove "$TMPDIR"

echo "Done. Verify in GitHub Settings -> Pages that source is gh-pages /(root)."
