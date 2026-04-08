"""Structural / contract tests for the Explorer page and its extracted JS.

These tests don't try to exercise the runtime behavior of the explorer
(that needs a browser) but they do guard against the kinds of regressions
we've actually hit while iterating on this branch:

- the inline script accidentally being out of sync with the external file,
- the cytoscape vendor bundle being missing or loaded after explorer.js,
- DOM ids referenced from JS being renamed or deleted in the markdown,
- the JS file getting truncated or syntactically broken by an edit.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPLORER_MD = REPO_ROOT / "site" / "docs" / "explorer.md"
EXPLORER_JS = REPO_ROOT / "site" / "docs" / "javascripts" / "explorer.js"
EXPLORER_UTILS_JS = REPO_ROOT / "site" / "docs" / "javascripts" / "explorer" / "utils.js"
EXPLORER_DEBUG_JS = REPO_ROOT / "site" / "docs" / "javascripts" / "explorer" / "debug.js"
CYTOSCAPE_JS = REPO_ROOT / "site" / "docs" / "javascripts" / "vendor" / "cytoscape.min.js"


# DOM ids that explorer.js looks up via getElementById on boot.
# If any of these disappear from explorer.md the IIFE crashes immediately.
REQUIRED_DOM_IDS = [
    "paper-graph",
    "paper-details",
    "parent-links",
    "child-links",
    "related-links",
    "direct-search-mode",
    "direct-search-input",
    "direct-search-run",
    "direct-search-results",
    "idea-input",
    "idea-results",
    "idea-run",
    "journey-selected",
    "journey-results",
    "journey-generate",
    "journey-clear",
    "community-stats",
    "community-results",
    "community-generate",
    "community-download",
    "graph-relayout",
    "node-drag-toggle",
    "graph-status",
    "core-metric",
    "difficulty-max",
    "min-in-degree",
    "min-out-degree",
    "min-kcore",
    "core-percentile",
    "core-percentile-value",
    "core-apply",
    "load-full-corpus",
    "require-abstract",
    "preset-undergrad",
    "preset-balanced",
    "preset-grad",
]


@pytest.fixture(scope="module")
def explorer_md_text() -> str:
    assert EXPLORER_MD.exists(), f"missing {EXPLORER_MD}"
    return EXPLORER_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def explorer_js_text() -> str:
    assert EXPLORER_JS.exists(), f"missing {EXPLORER_JS}"
    return EXPLORER_JS.read_text(encoding="utf-8")


def test_explorer_js_is_non_trivial(explorer_js_text: str) -> None:
    # The extracted file should be at least a few hundred lines / kilobytes.
    # If we ever accidentally truncate it we want a loud failure here.
    assert len(explorer_js_text) > 50_000, "explorer.js looks suspiciously small"
    assert explorer_js_text.startswith("// Main explorer IIFE")
    assert explorer_js_text.rstrip().endswith("})();")


def test_explorer_js_destructures_utils_module(explorer_js_text: str) -> None:
    """The main IIFE should pull its pure helpers from window.MSKBExplorerUtils."""
    assert "window.MSKBExplorerUtils" in explorer_js_text, (
        "explorer.js should destructure helpers from window.MSKBExplorerUtils "
        "rather than redefining them locally."
    )
    # Spot-check that a few helpers are pulled from the module rather than
    # defined as top-level functions.
    for helper in ("escapeHtml", "cleanNarrativeText", "normalizeNode", "bm25", "colorFor"):
        assert f"function {helper}(" not in explorer_js_text, (
            f"explorer.js still defines {helper} locally; it should come from utils.js."
        )


@pytest.mark.parametrize(
    "path",
    [EXPLORER_JS, EXPLORER_UTILS_JS, EXPLORER_DEBUG_JS],
    ids=["explorer.js", "explorer/utils.js", "explorer/debug.js"],
)
def test_explorer_js_parses_with_node(path: Path) -> None:
    """Run `node --check` to catch parse-level breakage."""
    if shutil.which("node") is None:
        pytest.skip("node not available; skipping JS syntax check")
    assert path.exists(), f"missing {path}"
    result = subprocess.run(
        ["node", "--check", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check failed for {path.name}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_cytoscape_vendor_bundle_present() -> None:
    assert CYTOSCAPE_JS.exists(), (
        "Cytoscape vendor bundle missing. The explorer cannot render without it."
    )
    # cytoscape.min.js should be a fairly large file (~1MB);
    # a stub of a few hundred bytes would silently break the page.
    assert CYTOSCAPE_JS.stat().st_size > 100_000


def test_explorer_md_loads_cytoscape_then_explorer_js(explorer_md_text: str) -> None:
    cy_marker = '<script src="../javascripts/vendor/cytoscape.min.js">'
    utils_marker = '<script src="../javascripts/explorer/utils.js">'
    debug_marker = '<script src="../javascripts/explorer/debug.js">'
    js_marker = '<script src="../javascripts/explorer.js">'
    assert cy_marker in explorer_md_text, "cytoscape vendor script tag missing"
    assert utils_marker in explorer_md_text, "explorer/utils.js script tag missing"
    assert debug_marker in explorer_md_text, "explorer/debug.js script tag missing"
    assert js_marker in explorer_md_text, "explorer.js script tag missing"
    cy_idx = explorer_md_text.index(cy_marker)
    utils_idx = explorer_md_text.index(utils_marker)
    debug_idx = explorer_md_text.index(debug_marker)
    js_idx = explorer_md_text.index(js_marker)
    assert cy_idx < js_idx, (
        "cytoscape vendor must be loaded BEFORE explorer.js so window.cytoscape "
        "is defined when the IIFE runs."
    )
    assert utils_idx < js_idx, (
        "explorer/utils.js must be loaded BEFORE explorer.js so the "
        "MSKBExplorerUtils destructure at the top of the IIFE works."
    )
    assert debug_idx < js_idx, (
        "explorer/debug.js must be loaded BEFORE explorer.js so window.__mskbDebug "
        "is defined when the IIFE's fallback error path runs."
    )


def test_explorer_md_has_no_inline_script(explorer_md_text: str) -> None:
    """We extracted everything; an opening <script> with no src should not exist."""
    # Lines that start with `<script>` (no attributes) indicate a leftover inline block.
    for line in explorer_md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<script>"):
            pytest.fail(
                "Found a leftover inline <script> block in explorer.md. "
                "All explorer JS should live in javascripts/explorer.js."
            )


@pytest.mark.parametrize("dom_id", REQUIRED_DOM_IDS)
def test_explorer_md_contains_required_dom_id(
    explorer_md_text: str, dom_id: str
) -> None:
    needle = f'id="{dom_id}"'
    assert needle in explorer_md_text, (
        f"explorer.md is missing #{dom_id}; explorer.js will throw on load."
    )


@pytest.mark.parametrize("dom_id", REQUIRED_DOM_IDS)
def test_explorer_js_references_required_dom_id(
    explorer_js_text: str, dom_id: str
) -> None:
    needle = f'getElementById("{dom_id}")'
    assert needle in explorer_js_text, (
        f"explorer.js no longer looks up #{dom_id} via getElementById; "
        f"either the id was renamed in the markdown or the JS lookup was removed."
    )
