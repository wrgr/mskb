"""Tests for seed governance quota counting based on primary topic categories."""

import pandas as pd

from src import seed_governance


def _build_core_seed_frame() -> pd.DataFrame:
    # Mirrors v1.3 core seed topic distribution using TOPIC-XX codes.
    topic_counts = {
        "TOPIC-00 Disease Overview": 2,
        "TOPIC-01 Genetics": 2,
        "TOPIC-02 Pathophysiology": 2,
        "TOPIC-03 Epidemiology": 2,
        "TOPIC-04 Natural History": 2,
        "TOPIC-05 Risk Factors": 2,
        "TOPIC-06 Diagnosis & Monitoring": 2,
        "TOPIC-07 Biomarkers": 3,
        "TOPIC-08 DMTs": 3,
        "TOPIC-09 Progressive MS & Smoldering": 4,
        "TOPIC-10 PROs": 4,
        "TOPIC-11 Symptom Management": 2,
        "TOPIC-12 Comorbidities": 2,
        "TOPIC-13 Pregnancy": 2,
        "TOPIC-14 Pediatric MS": 2,
        "TOPIC-15 Equity & SDOH": 5,
        "TOPIC-16 Clinical AI": 3,
        "TOPIC-17 Remyelination & Neuroprotection": 2,
    }
    rows = []
    for topic, count in topic_counts.items():
        rows.extend([{"primary_topic": topic, "category": "unused"} for _ in range(count)])
    return pd.DataFrame(rows)


def test_count_seed_categories_from_primary_topic() -> None:
    core = _build_core_seed_frame()
    counts = seed_governance._count_seed_categories_from_primary_topic(core)
    # Expected counts derived from v1.3 TOPIC-XX mapping (see TOPIC_CATEGORY_MAP).
    assert counts["pathogenesis_and_immunology"] == 12
    assert counts["imaging_and_biomarkers"] == 10
    assert counts["clinical_trials_and_therapeutics"] == 11
    assert counts["clinical_care_and_management"] == 12
    assert counts["epidemiology_and_population_health"] == 15


def test_evaluate_category_quotas_prefers_primary_topic_mapping() -> None:
    core = _build_core_seed_frame()
    quota_cfg = {
        "pathogenesis_and_immunology": {"min": 8, "max": 16},
        "imaging_and_biomarkers": {"min": 8, "max": 14},
        "clinical_trials_and_therapeutics": {"min": 8, "max": 14},
        "clinical_care_and_management": {"min": 8, "max": 16},
        "epidemiology_and_population_health": {"min": 8, "max": 18},
    }

    errors, effective_counts, _mapped_counts, sources = seed_governance._evaluate_category_quotas(core, quota_cfg)

    assert errors == []
    assert effective_counts["pathogenesis_and_immunology"] == 12
    assert effective_counts["imaging_and_biomarkers"] == 10
    assert effective_counts["clinical_trials_and_therapeutics"] == 11
    assert effective_counts["clinical_care_and_management"] == 12
    assert effective_counts["epidemiology_and_population_health"] == 15
    assert set(sources.values()) == {"primary_topic_map"}
