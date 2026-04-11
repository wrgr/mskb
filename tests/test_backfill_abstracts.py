"""Tests for abstract backfill scoped retry behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src import backfill_abstracts


def test_backfill_scope_includes_on_hold_ids_when_hold_mode_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                'openalex_base_url: "https://api.openalex.org"',
                'email: "test@example.com"',
                "governance:",
                "  hold_missing_abstracts_from_graph: true",
                "abstract_backfill:",
                "  enabled: true",
                "  max_openalex_queries: 0",
                "  max_secondary_queries: 0",
                "  selected_scope:",
                "    enabled: true",
                '    selected_csv_path: "outputs/graph/core_corpus_tracked_with_t4.csv"',
                '    selected_id_column: "canonical_paper_id"',
            ]
        ),
        encoding="utf-8",
    )

    outputs = tmp_path / "outputs"
    normalized = outputs / "normalized"
    graph = outputs / "graph"
    raw = outputs / "raw"
    normalized.mkdir(parents=True)
    graph.mkdir(parents=True)
    raw.mkdir(parents=True)

    pd.DataFrame(
        [
            {"canonical_paper_id": "p1", "title": "Tracked", "doi": "10.1/p1", "openalex_id": "W1", "abstract": ""},
            {"canonical_paper_id": "p2", "title": "Held", "doi": "10.1/p2", "openalex_id": "W2", "abstract": ""},
        ]
    ).to_csv(normalized / "canonical_papers.csv", index=False)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-01",
                "t4_id": "",
                "tracked_source": "T1_T2_T3",
                "doi": "10.1/p1",
                "title": "Tracked",
                "abstract": "",
            }
        ]
    ).to_csv(graph / "core_corpus_tracked_with_t4.csv", index=False)
    pd.DataFrame([{"canonical_paper_id": "p2"}]).to_csv(graph / "papers_on_hold_missing_abstract.csv", index=False)

    backfill_abstracts.run(str(config_path))

    stats = json.loads((raw / "abstract_backfill_stats.json").read_text(encoding="utf-8"))
    assert stats["selected_scope_enabled"] is True
    assert stats["selected_scope_size"] == 2
    assert stats["missing_before_scope"] == 2


def test_backfill_preserves_unresolved_prior_hold_rows(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                'openalex_base_url: "https://api.openalex.org"',
                'email: "test@example.com"',
                "governance:",
                "  hold_missing_abstracts_from_graph: true",
                "abstract_backfill:",
                "  enabled: true",
                "  max_openalex_queries: 0",
                "  max_secondary_queries: 0",
                "  selected_scope:",
                "    enabled: true",
                '    selected_csv_path: "outputs/graph/core_corpus_tracked_with_t4.csv"',
                '    selected_id_column: "canonical_paper_id"',
            ]
        ),
        encoding="utf-8",
    )

    outputs = tmp_path / "outputs"
    normalized = outputs / "normalized"
    graph = outputs / "graph"
    raw = outputs / "raw"
    normalized.mkdir(parents=True)
    graph.mkdir(parents=True)
    raw.mkdir(parents=True)

    pd.DataFrame(
        [
            {"canonical_paper_id": "p1", "title": "Tracked", "doi": "10.1/p1", "openalex_id": "W1", "abstract": "Filled"},
            {"canonical_paper_id": "p2", "title": "Held", "doi": "10.1/p2", "openalex_id": "W2", "abstract": ""},
        ]
    ).to_csv(normalized / "canonical_papers.csv", index=False)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-01",
                "t4_id": "",
                "tracked_source": "T1_T2_T3",
                "doi": "10.1/p1",
                "title": "Tracked",
                "abstract": "Filled",
            }
        ]
    ).to_csv(graph / "core_corpus_tracked_with_t4.csv", index=False)
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p2",
                "core_selection_tier": "T3",
                "primary_topic_code": "TOPIC-16",
                "t4_id": "",
                "tracked_source": "T3",
                "doi": "10.1/p2",
                "title": "Held",
                "hold_reason": "missing_abstract_after_backfill",
            }
        ]
    ).to_csv(graph / "papers_on_hold_missing_abstract.csv", index=False)

    backfill_abstracts.run(str(config_path))

    hold_df = pd.read_csv(graph / "papers_on_hold_missing_abstract.csv")
    assert set(hold_df["canonical_paper_id"].astype(str)) == {"p2"}

    stats = json.loads((raw / "abstract_backfill_stats.json").read_text(encoding="utf-8"))
    assert stats["hold_missing_abstracts_count"] == 1


def test_backfill_readds_recovered_hold_rows_to_tracked_and_selected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir: "outputs"',
                'openalex_base_url: "https://api.openalex.org"',
                'email: "test@example.com"',
                "governance:",
                "  hold_missing_abstracts_from_graph: true",
                "abstract_backfill:",
                "  enabled: true",
                "  max_openalex_queries: 0",
                "  max_secondary_queries: 0",
                "  selected_scope:",
                "    enabled: true",
                '    selected_csv_path: "outputs/graph/core_corpus_tracked_with_t4.csv"',
                '    selected_id_column: "canonical_paper_id"',
            ]
        ),
        encoding="utf-8",
    )

    outputs = tmp_path / "outputs"
    normalized = outputs / "normalized"
    graph = outputs / "graph"
    raw = outputs / "raw"
    normalized.mkdir(parents=True)
    graph.mkdir(parents=True)
    raw.mkdir(parents=True)

    pd.DataFrame(
        [
            {"canonical_paper_id": "p1", "title": "Tracked", "doi": "10.1/p1", "openalex_id": "W1", "abstract": "Filled"},
            {"canonical_paper_id": "p2", "title": "Recovered", "doi": "10.1/p2", "openalex_id": "W2", "abstract": "Now filled"},
        ]
    ).to_csv(normalized / "canonical_papers.csv", index=False)

    tracked_cols = [
        "canonical_paper_id",
        "title",
        "doi",
        "abstract",
        "core_selection_tier",
        "primary_topic_code",
        "tracked_source",
        "t4_id",
    ]
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "title": "Tracked",
                "doi": "10.1/p1",
                "abstract": "Filled",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-01",
                "tracked_source": "T1_T2_T3",
                "t4_id": "",
            }
        ]
    )[tracked_cols].to_csv(graph / "core_corpus_tracked_with_t4.csv", index=False)
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "title": "Tracked",
                "doi": "10.1/p1",
                "abstract": "Filled",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-01",
            }
        ]
    ).to_csv(graph / "core_corpus_selected.csv", index=False)
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "title": "Tracked",
                "doi": "10.1/p1",
                "abstract": "Filled",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-01",
                "tracked_source": "T1_T2_T3",
                "t4_id": "",
            },
            {
                "canonical_paper_id": "p2",
                "title": "Recovered",
                "doi": "10.1/p2",
                "abstract": "Now filled",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-16",
                "tracked_source": "T1_T2_T3",
                "t4_id": "",
            },
        ]
    )[tracked_cols].to_csv(graph / "scored_papers.csv", index=False)
    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p2",
                "core_selection_tier": "T2",
                "primary_topic_code": "TOPIC-16",
                "t4_id": "",
                "tracked_source": "T1_T2_T3",
                "doi": "10.1/p2",
                "title": "Recovered",
                "hold_reason": "missing_abstract_after_backfill",
            }
        ]
    ).to_csv(graph / "papers_on_hold_missing_abstract.csv", index=False)

    backfill_abstracts.run(str(config_path))

    hold_df = pd.read_csv(graph / "papers_on_hold_missing_abstract.csv")
    assert hold_df.empty

    tracked = pd.read_csv(graph / "core_corpus_tracked_with_t4.csv")
    assert set(tracked["canonical_paper_id"].astype(str)) == {"p1", "p2"}

    selected = pd.read_csv(graph / "core_corpus_selected.csv")
    assert set(selected["canonical_paper_id"].astype(str)) == {"p1", "p2"}
