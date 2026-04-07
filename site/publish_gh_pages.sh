#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Create it and install dependencies first."
  exit 1
fi

echo "[1/3] Generating docs + building site"
.venv/bin/python site/build_site.py --config config.yaml --strict

echo "[2/3] Preflight checks for explorer assets"
for p in \
  "site/docs/explorer.md" \
  "site/docs/assets/explorer_graph_lite.json" \
  "site/docs/assets/explorer_details_lite.json" \
  "site/docs/assets/explorer_graph.json" \
  "site/docs/assets/explorer_details.json"
do
  if [[ ! -f "$p" ]]; then
    echo "Missing required file: $p"
    exit 1
  fi
done

echo "[3/3] Deploying to gh-pages"
.venv/bin/python -m mkdocs gh-deploy -f site/mkdocs.yml --force

echo "Done. Verify in GitHub Settings -> Pages that source is gh-pages /(root)."
