"""Smoke test for `mkdocs build --strict`.

This test is the cheapest end-to-end signal we can get for the site:
it doesn't run the data pipeline (gen_site.py), it just walks whatever
docs are already on disk through MkDocs in strict mode and verifies the
explorer page renders with both the cytoscape vendor bundle and our
extracted explorer.js script tag, in the right order.

Skipped if `mkdocs` is not importable on the test runner.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MKDOCS_YML = REPO_ROOT / "site" / "mkdocs.yml"
BUILT_EXPLORER = REPO_ROOT / "site" / "site" / "explorer" / "index.html"
BUILT_EXPLORER_JS = REPO_ROOT / "site" / "site" / "javascripts" / "explorer.js"


def _have_mkdocs() -> bool:
    try:
        import mkdocs  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(scope="module")
def built_site() -> None:
    if not _have_mkdocs():
        pytest.skip("mkdocs not installed; skipping build smoke test")
    if not MKDOCS_YML.exists():
        pytest.skip(f"missing mkdocs.yml at {MKDOCS_YML}")

    cmd = [sys.executable, "-m", "mkdocs", "build", "-f", str(MKDOCS_YML), "--strict"]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(
            "mkdocs build --strict failed.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def test_explorer_page_built(built_site: None) -> None:
    assert BUILT_EXPLORER.exists(), (
        f"mkdocs did not produce {BUILT_EXPLORER}; explorer page rendering broken."
    )


def test_explorer_js_copied_to_site(built_site: None) -> None:
    assert BUILT_EXPLORER_JS.exists(), (
        "mkdocs did not copy javascripts/explorer.js into the built site/site tree."
    )
    assert BUILT_EXPLORER_JS.stat().st_size > 50_000


def test_built_explorer_loads_scripts_in_correct_order(built_site: None) -> None:
    html = BUILT_EXPLORER.read_text(encoding="utf-8")
    cy = "cytoscape.min.js"
    js = "explorer.js"
    assert cy in html, "built explorer/index.html missing cytoscape vendor reference"
    assert js in html, "built explorer/index.html missing explorer.js reference"
    assert html.index(cy) < html.index(js), (
        "cytoscape vendor must load before explorer.js in the rendered HTML"
    )


def test_built_explorer_has_paper_graph_div(built_site: None) -> None:
    html = BUILT_EXPLORER.read_text(encoding="utf-8")
    assert 'id="paper-graph"' in html
