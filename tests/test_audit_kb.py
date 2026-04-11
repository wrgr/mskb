"""Tests for audit KB governance checks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src import audit_kb


def test_bin_by_topic_category_multi_assignment() -> None:
    """TOPIC-XX codes that map to multiple categories contribute to each."""
    series = pd.Series(
        [
            "TOPIC-02",  # pathogenesis only
            "TOPIC-09 Progressive MS & Smoldering",  # pathogenesis + trials
            "TOPIC-05",  # pathogenesis + epi
            "",  # unmapped
            "T02",  # legacy/invalid → unmapped
        ]
    )
    counts = audit_kb._bin_by_topic_category(series)
    assert counts["pathogenesis_and_immunology"] == 3
    assert counts["clinical_trials_and_therapeutics"] == 1
    assert counts["epidemiology_and_population_health"] == 1
    assert counts["unmapped"] == 2
    # Unused buckets should still be present with zero.
    assert counts["imaging_and_biomarkers"] == 0


def test_audit_prefers_tracked_with_t4_over_scored(tmp_path: Path) -> None:
    """When core_corpus_tracked_with_t4.csv exists the audit must use it."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                "governance:",
                "  audit_gates:",
                "    fail_on_error: false",
                "    min_ms_focus_pct: 0.0",
                "    max_biology_no_ms_link: 100",
                "    max_missing_abstract_pct: 100.0",
                '    missing_abstract_policy: "todo"',
                "    max_missing_source_link_pct: 100.0",
                "    enforce_category_bounds: false",
            ]
        ),
        encoding="utf-8",
    )

    graph_dir = tmp_path / "outputs" / "graph"
    topics_dir = tmp_path / "outputs" / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    # scored_papers.csv has many pre-selection rows, tracked has only 2.
    pd.DataFrame(
        [
            {
                "canonical_paper_id": f"pre{i}",
                "title": f"pre {i}",
                "year": 2020,
                "doi": f"10.1/{i}",
                "openalex_id": f"https://openalex.org/Wpre{i}",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "abs",
                "anchor_category": "pathogenesis_and_immunology",
                "paper_importance_score": 0.1,
                "age_normalized_importance_score": 0.1,
                "merged_cited_by_count": 1,
                "pagerank": 0.01,
                "evidence_type": "review",
            }
            for i in range(100)
        ]
    ).to_csv(graph_dir / "scored_papers.csv", index=False)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "sel1",
                "title": "Selected One",
                "year": 2022,
                "doi": "10.1/sel1",
                "openalex_id": "https://openalex.org/Wsel1",
                "all_openalex_ids": "",
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "A",
                "primary_topic_code": "TOPIC-02",
                "paper_importance_score": 0.9,
                "age_normalized_importance_score": 0.8,
                "merged_cited_by_count": 20,
                "pagerank": 0.2,
                "evidence_type": "review",
                "core_selection_tier": "T2",
            },
            {
                "canonical_paper_id": "sel2",
                "title": "Selected Two",
                "year": 2023,
                "doi": "10.1/sel2",
                "openalex_id": "https://openalex.org/Wsel2",
                "all_openalex_ids": "",
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "B",
                "primary_topic_code": "TOPIC-07",
                "paper_importance_score": 0.8,
                "age_normalized_importance_score": 0.7,
                "merged_cited_by_count": 18,
                "pagerank": 0.15,
                "evidence_type": "review",
                "core_selection_tier": "T3",
            },
        ]
    ).to_csv(graph_dir / "core_corpus_tracked_with_t4.csv", index=False)

    pd.DataFrame(
        [
            {"canonical_paper_id": "sel1", "primary_topic_code": "TOPIC-02", "topic_assignment_method": "seed_link"},
            {"canonical_paper_id": "sel2", "primary_topic_code": "TOPIC-07", "topic_assignment_method": "lexical"},
        ]
    ).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))

    report = json.loads((tmp_path / "outputs" / "audit" / "kb_audit_report.json").read_text(encoding="utf-8"))
    assert report["n_final_corpus"] == 2, "audit must use tracked_with_t4 (2 rows), not scored (100 rows)"
    assert report["corpus_source"] == "core_corpus_tracked_with_t4.csv"
    assert report["category_counts"]["pathogenesis_and_immunology"] == 1
    assert report["category_counts"]["imaging_and_biomarkers"] == 1
    assert report["category_counts"]["unmapped"] == 0


def test_audit_flags_screened_papers_without_topic_assignment(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                "governance:",
                "  audit_gates:",
                "    fail_on_error: false",
                "    min_ms_focus_pct: 0.0",
                "    max_biology_no_ms_link: 100",
                "    max_missing_abstract_pct: 100.0",
                '    missing_abstract_policy: "todo"',
                "    max_missing_source_link_pct: 100.0",
                "    enforce_category_bounds: false",
            ]
        ),
        encoding="utf-8",
    )

    graph_dir = tmp_path / "outputs" / "graph"
    topics_dir = tmp_path / "outputs" / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "title": "Paper One",
                "year": 2020,
                "doi": "10.1000/p1",
                "openalex_id": "https://openalex.org/W1",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "A",
                "anchor_category": "pathogenesis_and_immunology",
                "paper_importance_score": 0.9,
                "age_normalized_importance_score": 0.8,
                "merged_cited_by_count": 20,
                "pagerank": 0.2,
                "evidence_type": "review",
            },
            {
                "canonical_paper_id": "p2",
                "title": "Paper Two",
                "year": 2021,
                "doi": "10.1000/p2",
                "openalex_id": "https://openalex.org/W2",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "B",
                "anchor_category": "clinical_care_and_management",
                "paper_importance_score": 0.7,
                "age_normalized_importance_score": 0.6,
                "merged_cited_by_count": 10,
                "pagerank": 0.1,
                "evidence_type": "review",
            },
        ]
    ).to_csv(graph_dir / "scored_papers.csv", index=False)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "primary_topic_code": "",
                "topic_assignment_method": "unassigned",
            },
            {
                "canonical_paper_id": "p2",
                "primary_topic_code": "T02",
                "topic_assignment_method": "seed_link",
            },
        ]
    ).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))

    report_path = tmp_path / "outputs" / "audit" / "kb_audit_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["gate_metrics"]["unmapped_topic_count"] == 1
    assert abs(report["gate_metrics"]["unmapped_topic_pct"] - 50.0) < 1e-6
    assert any("missing topic assignment" in w for w in report["warnings"])

    unmapped_path = tmp_path / "outputs" / "audit" / "final_corpus_unmapped_topics.csv"
    assert unmapped_path.exists()
    unmapped = pd.read_csv(unmapped_path)
    assert unmapped["canonical_paper_id"].tolist() == ["p1"]


def test_audit_exempts_t4_from_ms_focus_gate(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                "governance:",
                "  audit_gates:",
                "    fail_on_error: false",
                "    min_ms_focus_pct: 100.0",
                "    max_biology_no_ms_link: 100",
                "    max_missing_abstract_pct: 100.0",
                '    missing_abstract_policy: "todo"',
                "    max_missing_source_link_pct: 100.0",
                "    enforce_category_bounds: false",
            ]
        ),
        encoding="utf-8",
    )

    graph_dir = tmp_path / "outputs" / "graph"
    topics_dir = tmp_path / "outputs" / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    # p_t4 has no MS lexical satisfaction but is explicitly marked expert T4.
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p_non_t4",
                "title": "Non T4",
                "year": 2021,
                "doi": "10.1000/non",
                "openalex_id": "https://openalex.org/WN",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "ms_focus_exempt_t4": False,
                "in_t4_expert_signal": False,
                "biology_no_ms_link": False,
                "abstract": "A",
                "anchor_category": "clinical_care_and_management",
                "paper_importance_score": 0.8,
                "age_normalized_importance_score": 0.7,
                "merged_cited_by_count": 12,
                "pagerank": 0.1,
                "evidence_type": "review",
            },
            {
                "canonical_paper_id": "p_t4",
                "title": "T4 expert pick",
                "year": 2020,
                "doi": "10.1000/t4",
                "openalex_id": "https://openalex.org/WT4",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": False,
                "ms_focus_exempt_t4": True,
                "in_t4_expert_signal": True,
                "biology_no_ms_link": False,
                "abstract": "B",
                "anchor_category": "unmapped",
                "paper_importance_score": 0.2,
                "age_normalized_importance_score": 0.2,
                "merged_cited_by_count": 1,
                "pagerank": 0.01,
                "evidence_type": "expert_pick",
            },
        ]
    ).to_csv(graph_dir / "scored_papers.csv", index=False)

    pd.DataFrame(
        [
            {"canonical_paper_id": "p_non_t4", "primary_topic_code": "T02", "topic_assignment_method": "seed_link"},
            {"canonical_paper_id": "p_t4", "primary_topic_code": "T09", "topic_assignment_method": "unassigned"},
        ]
    ).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))

    report_path = tmp_path / "outputs" / "audit" / "kb_audit_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # With T4 exemption, denominator only includes p_non_t4.
    assert report["gate_metrics"]["ms_focus_eval_count"] == 1
    assert report["gate_metrics"]["ms_focus_exempt_t4_count"] == 1
    assert abs(report["gate_metrics"]["ms_focus_pct"] - 100.0) < 1e-6
    assert not any("ms_focus_pct below threshold" in err for err in report["errors"])
