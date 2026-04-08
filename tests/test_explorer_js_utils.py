"""Behavior tests for site/docs/javascripts/explorer/utils.js.

We load utils.js through Node (as a CommonJS module via its UMD wrapper) and
assert the output of each exported helper. This guards against regressions in
pure logic without needing a headless browser.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UTILS_JS = REPO_ROOT / "site" / "docs" / "javascripts" / "explorer" / "utils.js"


def _run_node(script: str) -> dict:
    """Execute a Node snippet that requires utils.js and prints JSON to stdout."""
    if shutil.which("node") is None:
        pytest.skip("node not available")
    assert UTILS_JS.exists(), f"missing {UTILS_JS}"
    full = (
        f"const utils = require({json.dumps(str(UTILS_JS))});\n"
        + script
        + "\nprocess.stdout.write(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "-e", full],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node failed: stdout={result.stdout} stderr={result.stderr}"
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------

def test_utils_exports_expected_api() -> None:
    out = _run_node("const out = Object.keys(utils).sort();")
    expected = sorted(
        [
            "bm25",
            "categoryColors",
            "citationBibtexForNode",
            "citationPlaintextForNode",
            "cleanDoi",
            "cleanNarrativeText",
            "colorFor",
            "computeKcoreThresholds",
            "escapeHtml",
            "FIELD_WEIGHTS",
            "formatMB",
            "nodeSetSignature",
            "nodeSizeFromCitations",
            "normalizeNode",
            "normalizeText",
            "QUERY_EXPANSIONS",
            "quantile",
            "stemToken",
            "stopWords",
            "tokenCounts",
            "tokenize",
        ]
    )
    assert out == expected


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def test_escape_html_escapes_all_five_chars() -> None:
    out = _run_node(
        "const out = utils.escapeHtml('<a href=\"x\">&y\\'s</a>');"
    )
    assert out == "&lt;a href=&quot;x&quot;&gt;&amp;y&#39;s&lt;/a&gt;"


def test_clean_narrative_text_strips_nan_and_generic_sentences() -> None:
    out = _run_node(
        "const out = [\n"
        "  utils.cleanNarrativeText('  Real  result   nan here '),\n"
        "  utils.cleanNarrativeText('This 2024 paper in Nature contributes to our understanding of multiple sclerosis.'),\n"
        "  utils.cleanNarrativeText('This paper in Brain contributes to our understanding of multiple sclerosis.'),\n"
        "];"
    )
    assert out[0] == "Real result here"
    assert out[1] == ""
    assert out[2] == ""


def test_format_mb_renders_megabytes() -> None:
    out = _run_node(
        "const out = [utils.formatMB(0), utils.formatMB(-1), utils.formatMB(2_621_440), utils.formatMB(NaN)];"
    )
    assert out == ["n/a", "n/a", "2.5 MB", "n/a"]


# ---------------------------------------------------------------------------
# Node normalization
# ---------------------------------------------------------------------------

def test_normalize_node_clamps_and_defaults_fields() -> None:
    out = _run_node(
        "const out = utils.normalizeNode({ id: 123, difficulty: '9', citation_count: '12.9', evidence_strength: 0, key_takeaways: 'not-an-array' });"
    )
    assert out["id"] == "123"
    assert out["title"] == "Untitled"
    assert out["difficulty"] == 5  # clamped from 9
    assert out["citation_count"] == 12
    # 0 is falsy so `|| 2` kicks in → default strength = 2
    assert out["evidence_strength"] == 2
    assert out["key_takeaways"] == []
    assert out["_detailsLoaded"] is False


# ---------------------------------------------------------------------------
# Citation helpers
# ---------------------------------------------------------------------------

def test_clean_doi_strips_url_prefix() -> None:
    out = _run_node(
        "const out = [utils.cleanDoi('https://doi.org/10.1/foo'), utils.cleanDoi('10.2/bar'), utils.cleanDoi('')];"
    )
    assert out == ["10.1/foo", "10.2/bar", ""]


def test_citation_plaintext_uses_n_d_when_year_missing() -> None:
    out = _run_node(
        "const out = utils.citationPlaintextForNode({ title: 'A', first_author: 'Doe J' });"
    )
    assert "Doe J." in out
    assert "(n.d.)" in out


def test_citation_bibtex_builds_article_entry() -> None:
    out = _run_node(
        "const out = utils.citationBibtexForNode({ id: 'abc-123', title: 'A {tricky} Title', first_author: 'Doe J', year: 2020, venue: 'Nature', doi: '10.1/x', source_url: 'https://example.org/p' });"
    )
    assert out.startswith("@article{mskb_abc123_2020,")
    assert "title = {A \\{tricky\\} Title}" in out
    assert "journal = {Nature}" in out
    assert "doi = {10.1/x}" in out
    assert "url = {https://example.org/p}" in out
    assert out.rstrip().endswith("}")


# ---------------------------------------------------------------------------
# Tokenization + BM25
# ---------------------------------------------------------------------------

def test_normalize_text_strips_punctuation_and_lowercases() -> None:
    out = _run_node(
        "const out = utils.normalizeText('Running Tests: 42% faster!');"
    )
    assert out == "running tests 42 faster"


def test_tokenize_applies_stopwords_and_stemming() -> None:
    # "running" -> "runn" (ing), "strategies" -> "strategy" (ies),
    # "tactics" -> "tactic" (s), "the" filtered as stopword.
    out = _run_node(
        "const out = utils.tokenize('the running strategies and tactics');"
    )
    assert "runn" in out
    assert "strategy" in out
    assert "tactic" in out
    assert "the" not in out
    assert "and" not in out


def test_token_counts_returns_expected_totals() -> None:
    out = _run_node(
        "const m = utils.tokenCounts(['a', 'b', 'a', 'c', 'a', 'b']);\n"
        "const out = { a: m.get('a'), b: m.get('b'), c: m.get('c') };"
    )
    assert out == {"a": 3, "b": 2, "c": 1}


def test_node_set_signature_combines_length_and_endpoints() -> None:
    out = _run_node(
        "const out = [\n"
        "  utils.nodeSetSignature([]),\n"
        "  utils.nodeSetSignature([{ id: 'x' }]),\n"
        "  utils.nodeSetSignature([{ id: 'a' }, { id: 'b' }, { id: 'c' }]),\n"
        "];"
    )
    assert out == ["0", "1:x:x", "3:a:c"]


def test_bm25_is_monotonic_in_term_frequency() -> None:
    out = _run_node(
        "const out = [utils.bm25(0, 100, 80, 1.5), utils.bm25(1, 100, 80, 1.5), utils.bm25(5, 100, 80, 1.5)];"
    )
    assert out[0] == 0
    assert out[1] > 0
    assert out[2] > out[1]


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

def test_color_for_matches_topic_prefix() -> None:
    out = _run_node(
        "const out = {\n"
        "  immuno: utils.colorFor({ topic_label: 'Pathogenesis and immunology' }),\n"
        "  unknown: utils.colorFor({ topic_label: 'random' }),\n"
        "  none: utils.colorFor({}),\n"
        "};"
    )
    assert out["immuno"] == "#1f77b4"  # pathogenesis_and_immunology
    assert out["unknown"] == "#4c78a8"  # default
    assert out["none"] == "#4c78a8"


def test_node_size_from_citations_grows_with_log() -> None:
    out = _run_node(
        "const out = [\n"
        "  utils.nodeSizeFromCitations({ citation_count: 0 }),\n"
        "  utils.nodeSizeFromCitations({ citation_count: 10 }),\n"
        "  utils.nodeSizeFromCitations({ citation_count: 1000 }),\n"
        "];"
    )
    assert out[0] == 4  # floor
    assert out[2] > out[1] > out[0]


def test_quantile_interpolates_between_values() -> None:
    out = _run_node(
        "const out = [\n"
        "  utils.quantile([1, 2, 3, 4, 5], 0),\n"
        "  utils.quantile([1, 2, 3, 4, 5], 0.5),\n"
        "  utils.quantile([1, 2, 3, 4, 5], 1),\n"
        "];"
    )
    assert out == [1, 3, 5]


def test_compute_kcore_thresholds_returns_tertiles() -> None:
    out = _run_node(
        "const nodes = Array.from({ length: 100 }, (_, i) => ({ kcore: i }));\n"
        "const out = utils.computeKcoreThresholds(nodes);"
    )
    assert out["lowMax"] == pytest.approx(32.67, abs=0.1)
    assert out["midMax"] == pytest.approx(65.34, abs=0.1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_exposed_constants_are_populated() -> None:
    out = _run_node(
        "const out = {\n"
        "  colors: Object.keys(utils.categoryColors).length,\n"
        "  stopWordsType: Object.prototype.toString.call(utils.stopWords),\n"
        "  stopWordsHasThe: utils.stopWords.has('the'),\n"
        "  fieldWeightsTitle: utils.FIELD_WEIGHTS.title,\n"
        "  queryExpansionsMs: utils.QUERY_EXPANSIONS.ms,\n"
        "};"
    )
    assert out["colors"] == 5
    assert out["stopWordsType"] == "[object Set]"
    assert out["stopWordsHasThe"] is True
    assert out["fieldWeightsTitle"] == 3.4
    assert out["queryExpansionsMs"] == ["multiple", "sclerosis", "demyelination", "neuroinflammation"]
