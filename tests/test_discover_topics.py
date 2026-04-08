"""Tests for src/discover_topics: topic labelling, spectrum scoring, and difficulty estimation."""

import pandas as pd
import pytest

from src.discover_topics import (
    SPECTRUM_ANCHORS,
    _auto_label,
    _estimate_difficulty,
    _extract_concepts,
    _spectrum_score,
)


def test_auto_label_with_concepts():
    concepts = ["Immunology", "T cells", "Multiple sclerosis"]
    label = _auto_label(concepts)
    assert "Immunology" in label
    assert "T cells" in label
    assert "Multiple sclerosis" in label


def test_auto_label_empty():
    assert _auto_label([]) == "Unlabeled cluster"


def test_spectrum_score_pathogenesis():
    texts = ["This paper studies myelin and oligodendrocyte cells with protein expression and EAE mouse model"]
    scores = _spectrum_score(texts)
    assert scores["pathogenesis_and_immunology"] > scores["clinical_care_and_management"]
    assert scores["pathogenesis_and_immunology"] > scores["epidemiology_and_population_health"]


def test_spectrum_score_clinical_trials():
    texts = ["A randomized placebo controlled clinical trial of a new disease-modifying therapy showing relapse rate reduction"]
    scores = _spectrum_score(texts)
    assert scores["clinical_trials_and_therapeutics"] > scores["pathogenesis_and_immunology"]


def test_spectrum_score_epidemiology():
    texts = ["Epidemiology and prevalence of MS in a large population cohort study of risk factors and gwas"]
    scores = _spectrum_score(texts)
    assert scores["epidemiology_and_population_health"] > scores["pathogenesis_and_immunology"]


def test_estimate_difficulty_low():
    texts = ["A simple study of cell biology and basic neuroscience"]
    assert _estimate_difficulty(texts) <= 2


def test_estimate_difficulty_high():
    texts = [
        "phosphorylation transcriptome proteome cytokine chemokine "
        "interleukin immunoglobulin oligodendrocyte astrocyte "
        "demyelination remyelination neurodegeneration"
    ]
    assert _estimate_difficulty(texts) >= 4


def test_extract_concepts():
    papers = pd.DataFrame({
        "concepts": ["Immunology;T cells;B cells", "Neuroscience;Demyelination"],
        "topics": ["MS;Autoimmunity", ""],
    })
    community = papers.iloc[:1]
    concepts = _extract_concepts(papers, community)
    assert "Immunology" in concepts
    assert "T cells" in concepts
