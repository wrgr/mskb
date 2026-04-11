"""Unit tests for generate_reports helpers."""

from datetime import datetime, timezone

import pandas as pd

from src.generate_reports import (
    _build_review_sheets,
    _build_cluster_lens,
    _build_cluster_topic_alignment,
    _build_topic_brief,
    _load_topic_map,
    _tier_label,
    _timestamp_slug,
)


def test_load_topic_map_extracts_order_names_and_targets(tmp_path) -> None:
    path = tmp_path / "topic_map.json"
    path.write_text(
        """
{
  "topics": [
    {"topic_code": "TOPIC-00", "topic_name": "A", "layer": "Foundation", "target_n": "25-30"},
    {"topic_code": "TOPIC-01", "topic_name": "B", "layer": "Clinical", "target_n": "15-20"}
  ]
}
""".strip(),
        encoding="utf-8",
    )

    ordered, names, layers, target_min = _load_topic_map(path)

    assert ordered == ["TOPIC-00", "TOPIC-01"]
    assert names["TOPIC-00"] == "A"
    assert layers["TOPIC-01"] == "Clinical"
    assert target_min["TOPIC-00"] == 25
    assert target_min["TOPIC-01"] == 15


def test_build_topic_brief_flags_empty_topic() -> None:
    papers = pd.DataFrame(columns=["canonical_paper_id", "year", "title"])
    summaries = pd.DataFrame(columns=["canonical_paper_id", "summary_certainty_label"])

    brief = _build_topic_brief(
        topic_id="TOPIC-17",
        label="Remyelination & Neuroprotection",
        papers=papers,
        summaries=summaries,
        target_min_n=15,
        layer="Context/Future",
    )

    assert brief["n_papers"] == 0
    assert any("No papers mapped" in flag for flag in brief["flags"])


def test_build_cluster_lens_uses_primary_topic_distribution() -> None:
    corpus = pd.DataFrame(
        {
            "canonical_paper_id": ["p1", "p2", "p3", "p4"],
            "primary_topic_code": ["TOPIC-00", "TOPIC-00", "TOPIC-01", "TOPIC-02"],
        }
    )
    paper_to_cluster = {"p1": "1", "p2": "1", "p3": "2"}
    cluster_labels = {"1": "Cluster One", "2": "Cluster Two"}

    lens = _build_cluster_lens(corpus, paper_to_cluster, cluster_labels)
    by_id = {row["cluster_id"]: row for row in lens}

    assert by_id["1"]["n_papers"] == 2
    assert by_id["1"]["label"] == "Cluster One"
    assert by_id["1"]["top_topic_codes"]["TOPIC-00"] == 2
    assert by_id["2"]["n_papers"] == 1
    assert by_id["unmapped"]["n_papers"] == 1


def test_cluster_topic_alignment_reports_purity_and_representation() -> None:
    corpus = pd.DataFrame(
        {
            "canonical_paper_id": ["p1", "p2", "p3", "p4", "p5", "p6"],
            "primary_topic_code": ["TOPIC-00", "TOPIC-00", "TOPIC-01", "TOPIC-01", "TOPIC-01", "TOPIC-02"],
        }
    )
    paper_to_cluster = {"p1": "0", "p2": "0", "p3": "0", "p4": "1", "p5": "1", "p6": "1"}

    out = _build_cluster_topic_alignment(corpus, paper_to_cluster)

    assert out["n_papers_scored"] == 6
    assert out["n_clusters"] == 2
    assert out["n_topics"] == 3
    assert 0.0 <= out["cluster_purity_weighted"] <= 1.0
    assert 0.0 <= out["topic_representation_weighted"] <= 1.0
    assert 0.0 <= out["fidelity_harmonic_mean"] <= 1.0
    assert len(out["cluster_to_topic"]) == 2
    assert len(out["topic_to_cluster"]) == 3


def test_timestamp_slug_uses_second_level_utc_format() -> None:
    dt = datetime(2026, 4, 10, 15, 26, 33, tzinfo=timezone.utc)
    assert _timestamp_slug(dt) == "20260410T152633Z"


def test_tier_label_supports_reference_seed_tier() -> None:
    assert _tier_label(pd.Series({"core_selection_tier": "T1_REF"})) == "T1_REF"
    assert _tier_label(pd.Series({"is_reference_seed": True})) == "T1_REF"


def test_build_review_sheets_uses_live_t4_and_hold_state(tmp_path) -> None:
    root = tmp_path
    out_dir = root / "outputs"
    (root / "data").mkdir(parents=True)
    (out_dir / "graph").mkdir(parents=True)
    (out_dir / "normalized").mkdir(parents=True)

    (root / "data" / "t4_expert_signal.yaml").write_text(
        """
version: "2.0"
by_concept:
  concept_a:
    papers:
      - t4_id: T4-001
        title: Included Paper
        year: 2022
        journal: Test
        topic_codes: [TOPIC-01]
        corpus_status: active
        doi: https://doi.org/10.1/a
      - t4_id: T4-002
        title: Held Paper
        year: 2021
        journal: Test
        topic_codes: [TOPIC-16]
        corpus_status: active
        doi: https://doi.org/10.1/b
      - t4_id: T4-003
        title: Excluded Paper
        year: 2020
        journal: Test
        topic_codes: [TOPIC-10]
        corpus_status: not_found
        doi: https://doi.org/10.1/c
        include_in_graph: false
""".strip(),
        encoding="utf-8",
    )

    pd.DataFrame(
        [
            {"canonical_paper_id": "p1", "doi": "https://doi.org/10.1/a"},
            {"canonical_paper_id": "p2", "doi": "https://doi.org/10.1/b"},
            {"canonical_paper_id": "p3", "doi": "https://doi.org/10.1/c"},
        ]
    ).to_csv(out_dir / "graph" / "scored_papers.csv", index=False)
    pd.DataFrame([{"canonical_paper_id": "p1"}]).to_csv(out_dir / "graph" / "core_corpus_selected.csv", index=False)
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "core_selection_tier": "T4",
                "tracked_source": "T4_mapped",
                "t4_id": "T4-001",
            }
        ]
    ).to_csv(out_dir / "graph" / "core_corpus_tracked_with_t4.csv", index=False)
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p2",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-16",
                "t4_id": "T4-002",
                "tracked_source": "T1_T2_T3_plus_T4",
                "doi": "https://doi.org/10.1/b",
                "title": "Held Paper",
                "hold_reason": "missing_abstract_after_backfill",
            }
        ]
    ).to_csv(out_dir / "graph" / "papers_on_hold_missing_abstract.csv", index=False)
    pd.DataFrame(
        [
            {"canonical_paper_id": "p2", "year": 2021, "venue": "Test", "openalex_id": "W2", "abstract": ""},
        ]
    ).to_csv(out_dir / "normalized" / "canonical_papers.csv", index=False)

    artifacts = _build_review_sheets(root=root, out_dir=out_dir, timestamp_slug="20260411T000000Z")
    assert artifacts["t4_rows"] == 3
    assert artifacts["held_rows"] == 1
    assert artifacts["topic16_held_rows"] == 1

    t4_sheet = pd.read_csv(out_dir / "review" / "t4_nomination_status.csv")
    status = {row["t4_id"]: row["selection_status"] for _, row in t4_sheet.iterrows()}
    assert status["T4-001"] == "in_tracked"
    assert status["T4-002"] == "held_missing_abstract"
    assert status["T4-003"] == "excluded_note_only"

    topic16_sheet = pd.read_csv(out_dir / "review" / "topic16_held_missing_abstract.csv")
    assert len(topic16_sheet) == 1
    assert str(topic16_sheet.iloc[0]["canonical_paper_id"]) == "p2"
