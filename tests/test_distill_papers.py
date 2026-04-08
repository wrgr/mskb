import pytest

from src.distill_papers import _rules_based_distill


def test_rules_based_distill_basic():
    row = {
        "title": "Ocrelizumab in relapsing multiple sclerosis",
        "abstract": (
            "Background: Ocrelizumab is a humanized anti-CD20 monoclonal antibody. "
            "Methods: We conducted a randomized controlled trial. "
            "Results: We found that ocrelizumab significantly reduced relapse rates. "
            "Conclusions: Ocrelizumab is effective for relapsing MS."
        ),
        "year": 2017,
        "venue": "New England Journal of Medicine",
    }
    result = _rules_based_distill(row)
    assert "summary" in result
    assert "key_takeaways" in result
    assert "why_it_matters" in result
    assert "difficulty" in result
    assert "language_difficulty" in result
    assert "jargon" in result
    assert isinstance(result["key_takeaways"], list)
    assert 1 <= len(result["key_takeaways"]) <= 4
    for takeaway in result["key_takeaways"]:
        assert not takeaway.lower().startswith(("opportunity:", "challenge:", "action:", "resolution:"))
    assert 1 <= int(result["language_difficulty"]) <= 5


def test_rules_based_distill_empty_abstract():
    row = {
        "title": "Some paper",
        "abstract": "",
        "year": 2020,
        "venue": "Journal",
    }
    result = _rules_based_distill(row)
    assert result["summary"]
    assert 1 <= int(result["difficulty"]) <= 5


def test_rules_based_distill_finds_results():
    row = {
        "title": "EBV and MS",
        "abstract": (
            "We investigated the relationship between EBV and MS. "
            "Our results demonstrate a strong causal link. "
            "The odds ratio was 32.4."
        ),
        "year": 2022,
        "venue": "Science",
    }
    result = _rules_based_distill(row)
    assert any("causal" in t.lower() or "demonstrate" in t.lower() for t in result["key_takeaways"])
    for takeaway in result["key_takeaways"]:
        assert not takeaway.lower().startswith(("opportunity:", "challenge:", "action:", "resolution:"))
