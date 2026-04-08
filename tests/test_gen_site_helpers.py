"""Unit tests for the pure helpers in site/gen_site.py.

Most of gen_site.py is one giant generate() that touches the filesystem,
the pipeline outputs, and pandas DataFrames; we don't try to exercise that
end-to-end here. We just lock in the small, pure helpers it relies on so
the asset-generation step doesn't quietly drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
sys.path.insert(0, str(SITE_DIR))

import gen_site  # noqa: E402  (path manipulation above)


# ---------------------------------------------------------------------------
# _slug / _topic_slug
# ---------------------------------------------------------------------------

def test_slug_basic() -> None:
    assert gen_site._slug("Hello World!") == "hello-world"


def test_slug_strips_punctuation_and_caps_length() -> None:
    long = "A" * 200
    out = gen_site._slug(long)
    assert len(out) <= 60
    assert out == "a" * 60


def test_topic_slug_includes_topic_id() -> None:
    assert gen_site._topic_slug("Pathogenesis & Immunology", 7) == "pathogenesis-immunology-7"


def test_topic_slug_falls_back_when_label_empty() -> None:
    assert gen_site._topic_slug("", 3) == "topic-3"


# ---------------------------------------------------------------------------
# _coerce_year / _safe_int / _safe_float / _round_float
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        (2024, 2024),
        ("2019", 2019),
        ("2018.0", 2018),
        (None, None),
        ("", None),
        ("not a year", None),
    ],
)
def test_coerce_year(value, expected) -> None:
    assert gen_site._coerce_year(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(7, 7), ("7", 7), ("7.4", 7), (None, 0), ("nope", 0)],
)
def test_safe_int(value, expected) -> None:
    assert gen_site._safe_int(value) == expected


def test_safe_int_default() -> None:
    assert gen_site._safe_int("nope", default=42) == 42


@pytest.mark.parametrize(
    "value,expected",
    [(1.5, 1.5), ("2.5", 2.5), (None, 0.0), ("bad", 0.0)],
)
def test_safe_float(value, expected) -> None:
    assert gen_site._safe_float(value) == expected


def test_round_float_rounds_to_six_digits() -> None:
    assert gen_site._round_float(1.23456789) == 1.234568


# ---------------------------------------------------------------------------
# _parse_json_list
# ---------------------------------------------------------------------------

def test_parse_json_list_from_json_string() -> None:
    assert gen_site._parse_json_list('["a", "b", "c"]') == ["a", "b", "c"]


def test_parse_json_list_from_python_list() -> None:
    assert gen_site._parse_json_list(["x", "y"]) == ["x", "y"]


def test_parse_json_list_drops_nan_strings() -> None:
    # Both literal "nan" and the float NaN-equivalents should be filtered.
    assert gen_site._parse_json_list("nan") == []
    assert gen_site._parse_json_list("") == []
    assert gen_site._parse_json_list(None) == []


def test_parse_json_list_falls_back_to_raw_string() -> None:
    # Non-JSON, non-empty strings are returned as a single-element list.
    assert gen_site._parse_json_list("Just one entry") == ["Just one entry"]


# ---------------------------------------------------------------------------
# _parse_jargon_structured
# ---------------------------------------------------------------------------

def test_parse_jargon_structured_from_json_string() -> None:
    raw = '[{"term": "EBV", "definition": "Epstein-Barr virus"}, {"term": "NfL", "definition": "Neurofilament light"}]'
    assert gen_site._parse_jargon_structured(raw) == [
        {"term": "EBV", "definition": "Epstein-Barr virus"},
        {"term": "NfL", "definition": "Neurofilament light"},
    ]


def test_parse_jargon_structured_from_list() -> None:
    raw = [
        {"term": "OCB", "definition": "Oligoclonal bands"},
        {"term": "", "definition": "missing term"},
        {"no_term": True},
    ]
    assert gen_site._parse_jargon_structured(raw) == [
        {"term": "OCB", "definition": "Oligoclonal bands"},
    ]


def test_parse_jargon_structured_handles_empty_inputs() -> None:
    assert gen_site._parse_jargon_structured(None) == []
    assert gen_site._parse_jargon_structured("") == []
    assert gen_site._parse_jargon_structured("nan") == []
    assert gen_site._parse_jargon_structured("not-json") == []
    assert gen_site._parse_jargon_structured({"term": "X"}) == []


# ---------------------------------------------------------------------------
# _topic_concepts_block
# ---------------------------------------------------------------------------

def test_topic_concepts_block_aggregates_and_sorts_by_frequency() -> None:
    papers = [
        {"jargon": [
            {"term": "EBV", "definition": "Epstein-Barr virus"},
            {"term": "NfL", "definition": "Neurofilament light"},
        ]},
        {"jargon": [
            {"term": "ebv", "definition": ""},
            {"term": "OCB", "definition": "Oligoclonal bands"},
        ]},
    ]
    block = gen_site._topic_concepts_block(papers, limit=10)
    assert "Concepts" in block
    # EBV appears twice, so it should be first; its definition should be kept.
    ebv_pos = block.find("EBV")
    nfl_pos = block.find("NfL")
    ocb_pos = block.find("OCB")
    assert ebv_pos != -1 and nfl_pos != -1 and ocb_pos != -1
    assert ebv_pos < nfl_pos
    assert ebv_pos < ocb_pos
    assert "Epstein-Barr virus" in block
    assert "Oligoclonal bands" in block


def test_topic_concepts_block_empty_when_no_jargon() -> None:
    assert gen_site._topic_concepts_block([]) == ""
    assert gen_site._topic_concepts_block([{"jargon": []}]) == ""


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

def test_clean_text_strips_and_handles_nan() -> None:
    assert gen_site._clean_text("  hello  ") == "hello"
    assert gen_site._clean_text("nan") == ""
    assert gen_site._clean_text("") == ""
    assert gen_site._clean_text(None) == ""


# ---------------------------------------------------------------------------
# _bibtex_escape
# ---------------------------------------------------------------------------

def test_bibtex_escape() -> None:
    assert gen_site._bibtex_escape("a {b} c") == "a \\{b\\} c"
    assert gen_site._bibtex_escape("path\\name") == "path\\\\name"


# ---------------------------------------------------------------------------
# _source_url_from_row / _openalex_url_from_row
# ---------------------------------------------------------------------------

def test_source_url_prefers_doi() -> None:
    row = {"doi": "10.1000/abc", "openalex_id": "W123"}
    assert gen_site._source_url_from_row(row) == "https://doi.org/10.1000/abc"


def test_source_url_passes_through_full_doi_url() -> None:
    row = {"doi": "https://doi.org/10.1000/abc"}
    assert gen_site._source_url_from_row(row) == "https://doi.org/10.1000/abc"


def test_source_url_falls_back_to_openalex_id() -> None:
    row = {"doi": "", "openalex_id": "W42"}
    assert gen_site._source_url_from_row(row) == "https://openalex.org/W42"


def test_source_url_falls_back_to_first_of_all_openalex_ids() -> None:
    row = {"doi": "", "openalex_id": "", "all_openalex_ids": "W7;W8;W9"}
    assert gen_site._source_url_from_row(row) == "https://openalex.org/W7"


def test_source_url_returns_empty_when_nothing() -> None:
    assert gen_site._source_url_from_row({}) == ""


# ---------------------------------------------------------------------------
# _citation_plaintext / _citation_bibtex
# ---------------------------------------------------------------------------

def test_citation_plaintext_basic() -> None:
    row = {
        "first_author": "Doe J",
        "year": 2020,
        "title": "A Study of MS",
        "venue": "NEJM",
        "doi": "10.1000/abc",
    }
    out = gen_site._citation_plaintext(row)
    assert "Doe J. (2020). A Study of MS." in out
    assert "NEJM." in out
    assert "https://doi.org/10.1000/abc" in out


def test_citation_plaintext_uses_nd_when_year_missing() -> None:
    row = {"title": "x"}
    assert "(n.d.)" in gen_site._citation_plaintext(row)


def test_citation_bibtex_emits_required_keys() -> None:
    row = {
        "canonical_paper_id": "abc-123",
        "first_author": "Doe J",
        "year": 2020,
        "title": "A {tricky} Title",
        "venue": "Nature",
        "doi": "10.1/x",
    }
    bib = gen_site._citation_bibtex(row)
    assert bib.startswith("@article{mskb_abc123_2020,")
    assert "title = {A \\{tricky\\} Title}" in bib
    assert "author = {Doe J}" in bib
    assert "year = {2020}" in bib
    assert "journal = {Nature}" in bib
    assert "doi = {10.1/x}" in bib
    assert bib.rstrip().endswith("}")


# ---------------------------------------------------------------------------
# _split_sentences / _structured_takeaways_for_display
# ---------------------------------------------------------------------------

def test_split_sentences() -> None:
    out = gen_site._split_sentences("First sentence. Second one! Third? Done")
    assert out == ["First sentence.", "Second one!", "Third?", "Done"]


def test_split_sentences_empty() -> None:
    assert gen_site._split_sentences("") == []
    assert gen_site._split_sentences(None) == []


def test_structured_takeaways_returns_four_labeled_items() -> None:
    out = gen_site._structured_takeaways_for_display(
        candidates=["Already labeled finding"],
        summary="A useful summary sentence. Another supporting fact.",
        abstract="Background. Methods. Results. Conclusion.",
    )
    assert len(out) == 4
    labels = [item.split(":", 1)[0] for item in out]
    assert labels == ["Opportunity", "Challenge", "Action", "Resolution"]
    # All entries should end with a period.
    for item in out:
        assert item.endswith(".")
