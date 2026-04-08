"""Structural checks for explorer/journey/topic graph assets."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPLORER_MD = REPO_ROOT / "site" / "src" / "content" / "docs" / "explorer.mdx"
JOURNEY_MD = REPO_ROOT / "site" / "src" / "content" / "docs" / "journey.mdx"
TOPICS_INDEX_MDX = REPO_ROOT / "site" / "src" / "content" / "docs" / "topics" / "index.mdx"
EXPLORER_JS = REPO_ROOT / "site" / "public" / "javascripts" / "explorer.js"
GRAPH_RENDERER_JS = REPO_ROOT / "site" / "public" / "javascripts" / "mskb_graph_renderer.js"
CYTOSCAPE_JS = REPO_ROOT / "site" / "public" / "javascripts" / "vendor" / "cytoscape.min.js"
TOPIC_PAGES_DIR = REPO_ROOT / "site" / "src" / "content" / "docs" / "topics"

EXPLORER_REQUIRED_IDS = [
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
    "journey-clear",
    "graph-relayout",
    "node-drag-toggle",
    "graph-status",
    "core-metric",
    "reading-level",
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

JOURNEY_REQUIRED_IDS = [
    "mskb-graph-spine",
    "journey-selected",
    "journey-clear",
    "journey-results",
    "journey-generate",
    "community-stats",
    "community-results",
    "community-generate",
    "community-download",
    "journey-import",
    "journey-export-json",
    "journey-export-bibtex",
    "journey-export-markdown",
]


@pytest.fixture(scope="module")
def explorer_md_text() -> str:
    assert EXPLORER_MD.exists(), f"missing {EXPLORER_MD}"
    return EXPLORER_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def journey_md_text() -> str:
    assert JOURNEY_MD.exists(), f"missing {JOURNEY_MD}"
    return JOURNEY_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def topics_index_text() -> str:
    assert TOPICS_INDEX_MDX.exists(), f"missing {TOPICS_INDEX_MDX}"
    return TOPICS_INDEX_MDX.read_text(encoding="utf-8")


def test_explorer_js_is_non_trivial() -> None:
    text = EXPLORER_JS.read_text(encoding="utf-8")
    assert len(text) > 50_000, "explorer.js looks suspiciously small"
    assert text.startswith("// ---- explorer boot")
    assert text.rstrip().endswith("})();")


def test_graph_renderer_js_is_non_trivial() -> None:
    text = GRAPH_RENDERER_JS.read_text(encoding="utf-8")
    assert len(text) > 8_000
    assert "window.MSKBGraph" in text


def test_js_files_parse_with_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node not available; skipping JS syntax check")
    for path in [EXPLORER_JS, GRAPH_RENDERER_JS]:
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"node --check failed for {path}:\n{result.stderr}"


def test_vendor_bundle_present() -> None:
    assert CYTOSCAPE_JS.exists(), "Cytoscape vendor bundle missing"
    assert CYTOSCAPE_JS.stat().st_size > 100_000


def test_explorer_loads_scripts_in_order(explorer_md_text: str) -> None:
    cy_marker = '/mskb/javascripts/vendor/cytoscape.min.js'
    js_marker = '/mskb/javascripts/explorer.js'
    assert cy_marker in explorer_md_text
    assert js_marker in explorer_md_text
    assert explorer_md_text.index(cy_marker) < explorer_md_text.index(js_marker)


@pytest.mark.parametrize("dom_id", EXPLORER_REQUIRED_IDS)
def test_explorer_contains_required_dom_ids(explorer_md_text: str, dom_id: str) -> None:
    assert f'id="{dom_id}"' in explorer_md_text


@pytest.mark.parametrize("dom_id", JOURNEY_REQUIRED_IDS)
def test_journey_contains_required_dom_ids(journey_md_text: str, dom_id: str) -> None:
    assert f'id="{dom_id}"' in journey_md_text


def test_topics_index_has_research_graph_root(topics_index_text: str) -> None:
    assert 'id="mskb-graph-research"' in topics_index_text


def test_generated_topic_pages_do_not_contain_ocar_prefix() -> None:
    topic_pages = [p for p in TOPIC_PAGES_DIR.glob("*.md") if p.name != "index.md"]
    assert topic_pages, "expected generated topic pages"
    for page in topic_pages:
        text = page.read_text(encoding="utf-8")
        assert "OCAR:" not in text
        assert "OCAR-" not in text
