from src import retrieve_corpora


def test_normalize_doi_strips_prefix_and_suffix_punctuation() -> None:
    assert retrieve_corpora._normalize_doi("https://doi.org/10.1000/ABC.123).") == "10.1000/abc.123"
    assert retrieve_corpora._normalize_doi("doi:10.5555/xyz") == "10.5555/xyz"
    assert retrieve_corpora._normalize_doi("") == ""


def test_dedupe_reference_candidates_prefers_richer_entry() -> None:
    c1 = retrieve_corpora._reference_candidate(source="crossref", doi="", title="A great paper", year=2020)
    c2 = retrieve_corpora._reference_candidate(
        source="semantic_scholar",
        doi="10.1000/abc",
        title="A great paper",
        year=2020,
        first_author="A. Smith",
    )
    out = retrieve_corpora._dedupe_reference_candidates([c1, c2])
    assert len(out) == 1
    assert out[0]["doi"] == "10.1000/abc"


def test_choose_best_openalex_match_uses_title_year_and_author() -> None:
    candidate = retrieve_corpora._reference_candidate(
        source="crossref",
        title="Determinants and Biomarkers of Progression Independent of Relapses in Multiple Sclerosis",
        year=2024,
        first_author="Cree",
    )
    works = [
        {
            "id": "https://openalex.org/W1",
            "title": "Determinants and Biomarkers of Progression Independent of Relapses in Multiple Sclerosis",
            "publication_year": 2024,
            "authorships": [{"author": {"display_name": "Bruce Cree"}}],
        },
        {
            "id": "https://openalex.org/W2",
            "title": "Determinants of progression in neurology",
            "publication_year": 2018,
            "authorships": [{"author": {"display_name": "Someone Else"}}],
        },
    ]
    best = retrieve_corpora._choose_best_openalex_match(candidate, works, min_title_similarity=80.0, max_year_delta=3)
    assert best is not None
    assert best["id"] == "https://openalex.org/W1"


def test_choose_best_openalex_match_rejects_low_similarity() -> None:
    candidate = retrieve_corpora._reference_candidate(source="crossref", title="Totally different paper title", year=2020)
    works = [
        {
            "id": "https://openalex.org/W9",
            "title": "Unrelated neuroimaging cohort study",
            "publication_year": 2020,
            "authorships": [],
        }
    ]
    best = retrieve_corpora._choose_best_openalex_match(candidate, works, min_title_similarity=90.0, max_year_delta=3)
    assert best is None
