"""Tests for backfill abstract matching helpers."""

from src.backfill_abstracts import (
    _choose_best_openalex_title_match,
    _extract_html_abstract_candidate,
    _extract_pmid_from_work,
    _retry_call,
)


def test_extract_pmid_from_work_url() -> None:
    work = {"ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/18970977"}}
    assert _extract_pmid_from_work(work) == "18970977"


def test_choose_best_openalex_title_match_prefers_author_year() -> None:
    works = [
        {
            "title": "Multiple sclerosis",
            "publication_year": 2008,
            "authorships": [{"author": {"display_name": "Alastair Compston"}}],
        },
        {
            "title": "Multiple sclerosis",
            "publication_year": 2002,
            "authorships": [{"author": {"display_name": "Wrong Author"}}],
        },
    ]

    best = _choose_best_openalex_title_match(
        works=works,
        target_title="Multiple sclerosis",
        target_first_author="Alastair Compston",
        target_year=2008,
        min_title_similarity=80.0,
        max_year_delta=3,
    )

    assert best is not None
    assert int(best.get("publication_year", 0)) == 2008


def test_retry_call_retries_then_succeeds() -> None:
    state = {"calls": 0}

    def flaky() -> str:
        state["calls"] += 1
        if state["calls"] < 3:
            raise RuntimeError("transient")
        return "ok"

    value, err, retries_used = _retry_call(flaky, max_retries=3, retry_backoff_seconds=0.0)

    assert value == "ok"
    assert err == ""
    assert retries_used == 2
    assert state["calls"] == 3


def test_retry_call_returns_error_after_exhausting_retries() -> None:
    state = {"calls": 0}

    def always_fail() -> None:
        state["calls"] += 1
        raise ConnectionError("down")

    value, err, retries_used = _retry_call(always_fail, max_retries=2, retry_backoff_seconds=0.0)

    assert value is None
    assert "ConnectionError" in err
    assert retries_used == 2
    assert state["calls"] == 3


def test_extract_html_abstract_candidate_prefers_citation_abstract() -> None:
    html = """
    <html><head>
      <meta name="description" content="Short site description.">
      <meta name="citation_abstract" content="This is a long abstract sentence about multiple sclerosis and treatment response with enough detail to pass minimum length. Another sentence to ensure this is clearly abstract-like text for parser testing.">
    </head></html>
    """
    text, source = _extract_html_abstract_candidate(html, min_chars=80)
    assert "multiple sclerosis" in text.lower()
    assert source == "meta:citation_abstract"
