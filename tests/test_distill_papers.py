"""Tests for src/distill_papers: rules-based distillation of paper abstracts."""

import pandas as pd
import pytest

from src.distill_papers import _rules_based_distill, _select_tiered_distill_corpus


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


def test_select_tiered_distill_corpus_prioritizes_t1_t2_t3():
    scored = pd.DataFrame(
        [
            {
                "canonical_paper_id": "seed-1",
                "is_core_seed": True,
                "cross_seed_score": 0,
                "review_anchor_link_count": 0,
                "paper_importance_score": 0.1,
                "citations_per_year_raw": 1.0,
                "year": 2010,
                "meets_t2_effective": False,
            },
            {
                "canonical_paper_id": "t2-bridge",
                "is_core_seed": False,
                "cross_seed_score": 1,
                "review_anchor_link_count": 2,
                "paper_importance_score": 0.7,
                "citations_per_year_raw": 5.0,
                "year": 2020,
                "meets_t2_effective": True,
            },
            {
                "canonical_paper_id": "t3-recent",
                "is_core_seed": False,
                "cross_seed_score": 0,
                "review_anchor_link_count": 0,
                "paper_importance_score": 0.2,
                "citations_per_year_raw": 30.0,
                "year": 2024,
                "meets_t2_effective": False,
            },
            {
                "canonical_paper_id": "fallback",
                "is_core_seed": False,
                "cross_seed_score": 0,
                "review_anchor_link_count": 0,
                "paper_importance_score": 0.95,
                "citations_per_year_raw": 3.0,
                "year": 2018,
                "meets_t2_effective": False,
            },
        ]
    )

    selected = _select_tiered_distill_corpus(
        scored=scored,
        max_papers=3,
        dist_cfg={
            "tiered_selection": {
                "t2_max_papers": 1,
                "t3_max_papers": 1,
                "t3_min_year": 2022,
                "t3_min_citations_per_year": 20.0,
                "t3_min_cross_seed_score": 0,
            }
        },
    )

    picked = set(selected["canonical_paper_id"].tolist())
    assert "seed-1" in picked
    assert "t2-bridge" in picked
    assert "t3-recent" in picked
    assert "fallback" not in picked
    assert set(selected["distill_selection_tier"].tolist()) == {"T1", "T2", "T3"}
