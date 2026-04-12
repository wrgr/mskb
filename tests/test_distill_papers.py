"""Tests for src/distill_papers: rules-based distillation of paper abstracts."""

import pandas as pd
import pytest

from src.distill_papers import _init_api_client, _rules_based_distill, _select_tiered_distill_corpus


def test_init_api_client_strict_anthropic_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit provider=anthropic with no credentials must error, not fall back."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="anthropic"):
        _init_api_client({"provider": "anthropic"})


def test_init_api_client_strict_gemini_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit provider=gemini with no credentials must error, not fall back."""
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="gemini"):
        _init_api_client({"provider": "gemini"})


def test_init_api_client_auto_prefers_gemini_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto provider selection should resolve Gemini first when a Gemini key is present."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client, provider = _init_api_client({})
    assert client is not None
    assert provider == "gemini"


def test_init_api_client_auto_prefers_gemini_over_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both keys exist and provider is unset, Gemini remains the default."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key")
    client, provider = _init_api_client({})
    assert client is not None
    assert provider == "gemini"


def test_init_api_client_rules_based_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=rules_based returns (None, 'rules_based') without checking env vars."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    client, provider = _init_api_client({"provider": "rules_based"})
    assert client is None
    assert provider == "rules_based"


def test_init_api_client_strict_bypass_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """strict_provider=false allows silent fallback for explicit providers."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    client, provider = _init_api_client({"provider": "anthropic", "strict_provider": False})
    assert client is None
    assert provider == "anthropic"


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
