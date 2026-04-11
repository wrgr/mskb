"""Tests for audit KB governance checks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src import audit_kb


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
                "primary_topic_code": "TOPIC-02",
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


def test_audit_enforces_topic_share_bounds(tmp_path: Path) -> None:
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
                "    enforce_topic_bounds: true",
                "    topic_min_pct: 25.0",
                "    topic_max_pct: 75.0",
                "    topic_bounds_include_unmapped: false",
                "    topic_expected_codes: [TOPIC-01, TOPIC-02, TOPIC-03]",
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
                "year": 2020,
                "doi": "10.1000/p2",
                "openalex_id": "https://openalex.org/W2",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "B",
                "anchor_category": "pathogenesis_and_immunology",
                "paper_importance_score": 0.8,
                "age_normalized_importance_score": 0.7,
                "merged_cited_by_count": 10,
                "pagerank": 0.1,
                "evidence_type": "review",
            },
            {
                "canonical_paper_id": "p3",
                "title": "Paper Three",
                "year": 2020,
                "doi": "10.1000/p3",
                "openalex_id": "https://openalex.org/W3",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "C",
                "anchor_category": "pathogenesis_and_immunology",
                "paper_importance_score": 0.7,
                "age_normalized_importance_score": 0.6,
                "merged_cited_by_count": 5,
                "pagerank": 0.05,
                "evidence_type": "review",
            },
            {
                "canonical_paper_id": "p4",
                "title": "Paper Four",
                "year": 2020,
                "doi": "10.1000/p4",
                "openalex_id": "https://openalex.org/W4",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "D",
                "anchor_category": "clinical_care_and_management",
                "paper_importance_score": 0.6,
                "age_normalized_importance_score": 0.5,
                "merged_cited_by_count": 3,
                "pagerank": 0.03,
                "evidence_type": "review",
            },
        ]
    ).to_csv(graph_dir / "scored_papers.csv", index=False)

    pd.DataFrame(
            [
            {"canonical_paper_id": "p1", "primary_topic_code": "TOPIC-01", "topic_assignment_method": "seed_link"},
            {"canonical_paper_id": "p2", "primary_topic_code": "TOPIC-01", "topic_assignment_method": "seed_link"},
            {"canonical_paper_id": "p3", "primary_topic_code": "TOPIC-01", "topic_assignment_method": "seed_link"},
            {"canonical_paper_id": "p4", "primary_topic_code": "TOPIC-02", "topic_assignment_method": "seed_link"},
        ]
    ).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))

    report_path = tmp_path / "outputs" / "audit" / "kb_audit_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # T01=75%, T02=25% pass; T03=0% fails because expected-topic checks include missing topics.
    assert any("topic 'TOPIC-03' out of bounds" in err for err in report["errors"])


def test_audit_rejects_legacy_expected_topic_codes(tmp_path: Path) -> None:
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
                "    enforce_topic_bounds: true",
                "    topic_min_pct: 1.0",
                "    topic_max_pct: 100.0",
                "    topic_bounds_include_unmapped: false",
                "    topic_expected_codes: [T01]",
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
            }
        ]
    ).to_csv(graph_dir / "scored_papers.csv", index=False)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "primary_topic_code": "TOPIC-01",
                "topic_assignment_method": "seed_link",
            }
        ]
    ).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    import pytest

    with pytest.raises(ValueError):
        audit_kb.run(str(config_path))


def test_audit_excludes_review_cluster_from_unmapped(tmp_path: Path) -> None:
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
                "    enforce_topic_bounds: true",
                "    topic_min_pct: 1.0",
                "    topic_max_pct: 100.0",
                "    topic_expected_codes: [TOPIC-01]",
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
                "title": "Seed-linked paper",
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
                "title": "Cross-sectional review",
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
            {"canonical_paper_id": "p1", "primary_topic_code": "TOPIC-01", "topic_assignment_method": "seed_link"},
            {
                "canonical_paper_id": "p2",
                "primary_topic_code": "",
                "topic_assignment_method": "review_cross_sectional",
                "topic_cluster": "REVIEW_CLUSTER",
            },
        ]
    ).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))
    report = json.loads((tmp_path / "outputs" / "audit" / "kb_audit_report.json").read_text(encoding="utf-8"))

    assert report["gate_metrics"]["unmapped_topic_count"] == 0
    assert report["gate_metrics"]["review_cluster_count"] == 1
    assert report["topic_mix_pct"]["REVIEW_CLUSTER"] == 50.0


def test_audit_recent_topic_velocity_warn_and_error_thresholds(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                "core_corpus_selection:",
                "  t3:",
                "    min_year: 2022",
                "    min_citations_per_year: 20.0",
                "    cap_fraction_of_t2_per_topic: 0.20",
                "    floor_per_topic: 5",
                "governance:",
                "  audit_gates:",
                "    fail_on_error: false",
                "    min_ms_focus_pct: 0.0",
                "    max_biology_no_ms_link: 100",
                "    max_missing_abstract_pct: 100.0",
                '    missing_abstract_policy: "todo"',
                "    max_missing_source_link_pct: 100.0",
                "    enforce_category_bounds: false",
                "    enforce_topic_bounds: false",
                "    enforce_recent_topic_coverage: true",
                "    recent_topic_warn_below_count: 5",
                "    recent_topic_error_below_count: 3",
                "    topic_expected_codes: [TOPIC-01, TOPIC-02]",
            ]
        ),
        encoding="utf-8",
    )

    graph_dir = tmp_path / "outputs" / "graph"
    topics_dir = tmp_path / "outputs" / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    rows = []
    topic_rows = []
    for i in range(1, 6):
        rows.append(
            {
                "canonical_paper_id": f"t1_{i}",
                "title": f"T1 Paper {i}",
                "year": 2023 if i <= 4 else 2019,
                "citations_per_year_raw": 25.0 if i <= 4 else 2.0,
                "doi": f"10.1000/t1_{i}",
                "openalex_id": f"https://openalex.org/WT1{i}",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "A",
                "anchor_category": "pathogenesis_and_immunology",
                "paper_importance_score": 0.8,
                "age_normalized_importance_score": 0.7,
                "merged_cited_by_count": 20,
                "pagerank": 0.2,
                "evidence_type": "review",
            }
        )
        topic_rows.append({"canonical_paper_id": f"t1_{i}", "primary_topic_code": "TOPIC-01", "topic_assignment_method": "seed_link"})
    for i in range(1, 6):
        rows.append(
            {
                "canonical_paper_id": f"t2_{i}",
                "title": f"T2 Paper {i}",
                "year": 2024 if i <= 2 else 2018,
                "citations_per_year_raw": 30.0 if i <= 2 else 1.0,
                "doi": f"10.1000/t2_{i}",
                "openalex_id": f"https://openalex.org/WT2{i}",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "B",
                "anchor_category": "clinical_care_and_management",
                "paper_importance_score": 0.7,
                "age_normalized_importance_score": 0.6,
                "merged_cited_by_count": 12,
                "pagerank": 0.1,
                "evidence_type": "review",
            }
        )
        topic_rows.append({"canonical_paper_id": f"t2_{i}", "primary_topic_code": "TOPIC-02", "topic_assignment_method": "seed_link"})

    pd.DataFrame(rows).to_csv(graph_dir / "scored_papers.csv", index=False)
    pd.DataFrame(topic_rows).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))
    report = json.loads((tmp_path / "outputs" / "audit" / "kb_audit_report.json").read_text(encoding="utf-8"))

    assert any("topic 'TOPIC-01' has low recent-paper coverage" in w for w in report["warnings"])
    assert any("topic 'TOPIC-02' has too few recent papers" in e for e in report["errors"])
    recent_cfg = report["recent_topic_velocity"]
    assert recent_cfg["topics_below_warn_count"] >= 1
    assert recent_cfg["topics_below_error_count"] >= 1


def test_audit_recent_topic_velocity_error_can_be_waived_to_warning(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                "core_corpus_selection:",
                "  t3:",
                "    min_year: 2022",
                "    min_citations_per_year: 20.0",
                "    cap_fraction_of_t2_per_topic: 0.20",
                "    floor_per_topic: 5",
                "governance:",
                "  audit_gates:",
                "    fail_on_error: false",
                "    min_ms_focus_pct: 0.0",
                "    max_biology_no_ms_link: 100",
                "    max_missing_abstract_pct: 100.0",
                '    missing_abstract_policy: "todo"',
                "    max_missing_source_link_pct: 100.0",
                "    enforce_category_bounds: false",
                "    enforce_topic_bounds: false",
                "    enforce_recent_topic_coverage: true",
                "    recent_topic_warn_below_count: 5",
                "    recent_topic_error_below_count: 3",
                "    recent_topic_error_warn_only_codes: [TOPIC-02]",
                "    topic_expected_codes: [TOPIC-02]",
            ]
        ),
        encoding="utf-8",
    )

    graph_dir = tmp_path / "outputs" / "graph"
    topics_dir = tmp_path / "outputs" / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    rows = []
    topic_rows = []
    for i in range(1, 6):
        rows.append(
            {
                "canonical_paper_id": f"t2_{i}",
                "title": f"T2 Paper {i}",
                "year": 2024 if i <= 2 else 2018,
                "citations_per_year_raw": 30.0 if i <= 2 else 1.0,
                "doi": f"10.1000/t2_{i}",
                "openalex_id": f"https://openalex.org/WT2{i}",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "B",
                "anchor_category": "clinical_care_and_management",
                "paper_importance_score": 0.7,
                "age_normalized_importance_score": 0.6,
                "merged_cited_by_count": 12,
                "pagerank": 0.1,
                "evidence_type": "review",
            }
        )
        topic_rows.append(
            {
                "canonical_paper_id": f"t2_{i}",
                "primary_topic_code": "TOPIC-02",
                "topic_assignment_method": "seed_link",
            }
        )

    pd.DataFrame(rows).to_csv(graph_dir / "scored_papers.csv", index=False)
    pd.DataFrame(topic_rows).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))
    report = json.loads((tmp_path / "outputs" / "audit" / "kb_audit_report.json").read_text(encoding="utf-8"))

    assert not any("topic 'TOPIC-02' has too few recent papers" in e for e in report["errors"])
    assert any("topic 'TOPIC-02' has too few recent papers" in w for w in report["warnings"])
    assert report["recent_topic_velocity"]["topics_below_error_count"] == 0
    assert report["recent_topic_velocity"]["topics_below_error_count_waived"] == 1
    assert any(
        note.get("topic_code") == "TOPIC-02" and note.get("status") == "warning_recent_error_waived"
        for note in report.get("topic_gap_notes", [])
    )


def test_audit_topic_bounds_error_can_be_waived_to_warning(tmp_path: Path) -> None:
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
                "    enforce_topic_bounds: true",
                "    topic_min_pct: 10.0",
                "    topic_max_pct: 40.0",
                "    topic_bounds_use_rebalance_from_selection_summary: false",
                "    topic_bounds_warn_only_codes: [TOPIC-01]",
                "    topic_expected_codes: [TOPIC-01]",
            ]
        ),
        encoding="utf-8",
    )

    graph_dir = tmp_path / "outputs" / "graph"
    topics_dir = tmp_path / "outputs" / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    rows = []
    topic_rows = []
    for i in range(1, 6):
        rows.append(
            {
                "canonical_paper_id": f"p{i}",
                "title": f"Paper {i}",
                "year": 2020,
                "doi": f"10.1000/p{i}",
                "openalex_id": f"https://openalex.org/W{i}",
                "all_openalex_ids": "",
                "in_final_corpus": 1,
                "has_ms_focus": True,
                "biology_no_ms_link": False,
                "abstract": "A",
                "anchor_category": "pathogenesis_and_immunology",
                "paper_importance_score": 0.8,
                "age_normalized_importance_score": 0.7,
                "merged_cited_by_count": 10,
                "pagerank": 0.1,
                "evidence_type": "review",
            }
        )
        topic_rows.append(
            {
                "canonical_paper_id": f"p{i}",
                "primary_topic_code": "TOPIC-01",
                "topic_assignment_method": "seed_link",
            }
        )

    pd.DataFrame(rows).to_csv(graph_dir / "scored_papers.csv", index=False)
    pd.DataFrame(topic_rows).to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    audit_kb.run(str(config_path))
    report = json.loads((tmp_path / "outputs" / "audit" / "kb_audit_report.json").read_text(encoding="utf-8"))

    assert not any("topic 'TOPIC-01' out of bounds" in e for e in report["errors"])
    assert any("topic 'TOPIC-01' out of bounds (warning-only override)" in w for w in report["warnings"])
    assert any(
        note.get("topic_code") == "TOPIC-01" and note.get("status") == "warning_bounds_override_over"
        for note in report.get("topic_gap_notes", [])
    )
