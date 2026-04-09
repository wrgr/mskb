"""Tests for seed governance quota counting based on primary topic categories."""

import pandas as pd

from src import seed_governance


def _build_core_seed_frame() -> pd.DataFrame:
    # Mirrors current core seed topic distribution (40 seeds total).
    topic_counts = {
        "T00 Epidemiology": 2,
        "T01 Disease Overview": 2,
        "T1b Natural History": 2,
        "T02 Pathophysiology": 2,
        "T03 Genetics": 2,
        "T04 Risk Factors": 2,
        "T05 Diagnosis & Monitoring": 2,
        "T06 Biomarkers": 2,
        "T07 DMTs": 2,
        "T08 Progressive MS": 2,
        "T09 PROs": 4,
        "T10 Comorbidities": 2,
        "T11 Pregnancy": 2,
        "T12 Pediatric MS": 2,
        "T13 Equity & SDOH": 3,
        "T14 Clinical AI": 2,
        "T15 Emerging Frontiers": 2,
        "T16 Research Priorities": 3,
    }
    rows = []
    for topic, count in topic_counts.items():
        rows.extend([{"primary_topic": topic, "category": "unused"} for _ in range(count)])
    return pd.DataFrame(rows)


def test_count_seed_categories_from_primary_topic() -> None:
    core = _build_core_seed_frame()
    counts = seed_governance._count_seed_categories_from_primary_topic(core)
    assert counts["pathogenesis_and_immunology"] == 10
    assert counts["imaging_and_biomarkers"] == 8
    assert counts["clinical_trials_and_therapeutics"] == 11
    assert counts["clinical_care_and_management"] == 10
    assert counts["epidemiology_and_population_health"] == 13


def test_evaluate_category_quotas_prefers_primary_topic_mapping() -> None:
    core = _build_core_seed_frame()
    quota_cfg = {
        "pathogenesis_and_immunology": {"min": 8, "max": 14},
        "imaging_and_biomarkers": {"min": 8, "max": 14},
        "clinical_trials_and_therapeutics": {"min": 8, "max": 14},
        "clinical_care_and_management": {"min": 8, "max": 14},
        "epidemiology_and_population_health": {"min": 8, "max": 14},
    }

    errors, effective_counts, _mapped_counts, sources = seed_governance._evaluate_category_quotas(core, quota_cfg)

    assert errors == []
    assert effective_counts["pathogenesis_and_immunology"] == 10
    assert effective_counts["imaging_and_biomarkers"] == 8
    assert effective_counts["clinical_trials_and_therapeutics"] == 11
    assert effective_counts["clinical_care_and_management"] == 10
    assert effective_counts["epidemiology_and_population_health"] == 13
    assert set(sources.values()) == {"primary_topic_map"}
