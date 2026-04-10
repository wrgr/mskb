"""Tests for T4 expert-signal ingestion and matching in compute_scores."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from src import compute_scores


def test_load_t4_registry_reads_v2_yaml(tmp_path: Path) -> None:
    """v2 format (concept_path at group level, doi field, relevance) is loaded correctly."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "version": "2.0",
        "by_concept": {
            "fatigue_ms": {
                "concept_path": "concepts/clinical/fatigue-ms",
                "papers": [
                    {
                        "t4_id": "T4-001",
                        "title": "Expert Paper Alpha",
                        "doi": "https://doi.org/10.1000/alpha",
                        "topic_codes": ["T10"],
                        "relevance": "fatigue epidemiology baseline",
                    },
                    {
                        "t4_id": "T4-002",
                        "title": "Expert Paper Beta",
                        "corpus_status": "not_found",
                        "topic_codes": ["T13"],
                        "relevance": "global south review",
                    },
                ],
            }
        },
    }
    (data_dir / "t4_expert_signal.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    registry = compute_scores._load_t4_registry(tmp_path)
    assert not registry.empty
    assert "10.1000/alpha" in set(registry["doi_norm"].tolist())
    assert "expert paper alpha" in set(registry["title_norm"].tolist())
    assert "expert paper beta" in set(registry["title_norm"].tolist())
    # selection_source should come from the group-level concept_path
    assert all(
        src == "concepts/clinical/fatigue-ms"
        for src in registry["selection_source"].tolist()
    )
    # rationale should be the relevance field
    alpha_row = registry[registry["title_norm"] == "expert paper alpha"].iloc[0]
    assert alpha_row["rationale"] == "fatigue epidemiology baseline"


def test_load_t4_registry_v1_fallback(tmp_path: Path) -> None:
    """v1 format (list directly under concept key) still loads without error."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    payload = {
        "by_concept": {
            "equity_sdoh": [
                {
                    "t4_id": "T4-001",
                    "title": "Legacy Paper",
                    "corpus_doi": "https://doi.org/10.1000/legacy",
                    "topic_codes": ["T13"],
                    "concept": "equity_sdoh",
                    "concept_path": "concepts/populations/equity-sdoh",
                    "t4_signal": "Expert pushed",
                    "t4_source_type": "concept_anchor_signal",
                }
            ]
        }
    }
    (data_dir / "t4_expert_signal.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    registry = compute_scores._load_t4_registry(tmp_path)
    assert not registry.empty
    assert "10.1000/legacy" in set(registry["doi_norm"].tolist())


def test_add_t4_expert_columns_matches_by_title_when_doi_missing() -> None:
    """Papers without a DOI are matched by normalised title."""
    papers = pd.DataFrame(
        [
            {"canonical_paper_id": "p1", "doi": "", "title": "Expert Paper Beta"},
            {"canonical_paper_id": "p2", "doi": "10.1000/other", "title": "Regular Paper"},
        ]
    )
    registry = pd.DataFrame(
        [
            {
                "doi_norm": "",
                "title_norm": "expert paper beta",
                "selection_source": "concepts/populations/equity-sdoh",
                "signal_type": "concept_anchor_signal",
                "topic_code": "T13",
                "rationale": "global south review",
            }
        ]
    )

    compute_scores._add_t4_expert_columns(papers, registry)
    p1 = papers[papers["canonical_paper_id"] == "p1"].iloc[0]
    p2 = papers[papers["canonical_paper_id"] == "p2"].iloc[0]

    assert int(p1["signal_t4_expert"]) == 1
    assert p1["t4_topic_code"] == "T13"
    assert int(p2["signal_t4_expert"]) == 0
