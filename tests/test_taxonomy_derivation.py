"""Unit tests for site/gen_site_taxonomy.py."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
sys.path.insert(0, str(SITE_DIR))

import gen_site_taxonomy as taxonomy  # noqa: E402


def test_build_concept_topic_links_counts_overlap() -> None:
    concept_papers = {
        "concept_a": {
            "foundational": ["p1", "p2"],
            "advanced": ["p3"],
            "rationales": {},
        },
        "concept_b": {
            "foundational": ["p4"],
            "advanced": [],
            "rationales": {},
        },
    }
    paper_topics_rows = [
        {"canonical_paper_id": "p1", "topic_id": 1},
        {"canonical_paper_id": "p2", "topic_id": 1},
        {"canonical_paper_id": "p3", "topic_id": 2},
        {"canonical_paper_id": "p4", "topic_id": 2},
    ]

    concept_to_topics, topic_to_concepts = taxonomy.build_concept_topic_links(
        concept_papers=concept_papers,
        paper_topics_rows=paper_topics_rows,
    )

    assert concept_to_topics["concept_a"] == {"1": 2, "2": 1}
    assert concept_to_topics["concept_b"] == {"2": 1}
    assert topic_to_concepts["1"] == {"concept_a": 2}
    assert topic_to_concepts["2"] == {"concept_a": 1, "concept_b": 1}


def test_derive_topic_categories_prefers_concept_overlap_then_fallback() -> None:
    topic_clusters_rows = [
        {"topic_id": 1, "dominant_category": "imaging_and_biomarkers"},
        {"topic_id": 2, "dominant_category": "clinical_care_and_management"},
    ]
    concept_index = {
        "concept_a": {"category": "pathogenesis_and_immunology"},
        "concept_b": {"category": "clinical_trials_and_therapeutics"},
    }
    topic_to_concepts = {
        "1": {"concept_a": 3, "concept_b": 1},
        # topic 2 intentionally omitted to force fallback
    }

    out = taxonomy.derive_topic_categories(
        topic_clusters_rows=topic_clusters_rows,
        concept_index=concept_index,
        topic_to_concepts=topic_to_concepts,
    )

    assert out["1"]["topic_category"] == "pathogenesis_and_immunology"
    assert out["1"]["category_source"] == "concept"
    assert out["1"]["top_concept_id"] == "concept_a"
    assert out["1"]["overlap_count"] == 3

    assert out["2"]["topic_category"] == "clinical_care_and_management"
    assert out["2"]["category_source"] == "fallback"
    assert out["2"]["top_concept_id"] == ""
    assert out["2"]["overlap_count"] == 0


def test_layout_layered_returns_finite_coordinates_and_layer_metadata() -> None:
    layers = [["a", "b"], ["c", "d"], ["e"]]
    edges = [("a", "c"), ("b", "d"), ("c", "e"), ("d", "e")]

    coords = taxonomy.layout_layered(layers=layers, edges=edges, sweeps=3)

    assert set(coords.keys()) == {"a", "b", "c", "d", "e"}
    assert coords["a"]["layer"] == 0
    assert coords["c"]["layer"] == 1
    assert coords["e"]["layer"] == 2
    assert coords["a"]["x"] < coords["c"]["x"] < coords["e"]["x"]
    for values in coords.values():
        assert math.isfinite(float(values["x"]))
        assert math.isfinite(float(values["y"]))


def test_build_pathway_steps_extracts_unique_ordered_concepts(tmp_path: Path) -> None:
    concepts_root = tmp_path / "concepts"
    pathways_root = tmp_path / "pathways"
    (concepts_root / "foundations").mkdir(parents=True)
    (concepts_root / "mechanisms").mkdir(parents=True)
    pathways_root.mkdir(parents=True)

    (concepts_root / "foundations" / "what-is-ms.mdx").write_text(
        "\n".join(
            [
                "---",
                "title: What is MS?",
                "concept:",
                "  id: what_is_ms",
                "  category: foundations",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (concepts_root / "mechanisms" / "neuroinflammation.md").write_text(
        "\n".join(
            [
                "---",
                "title: Neuroinflammation",
                "concept:",
                "  id: mechanisms_neuroinflammation",
                "  category: mechanisms",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pathways_root / "clinical.md").write_text(
        "\n".join(
            [
                "1. [What is MS](/mskb/concepts/foundations/what-is-ms/)",
                "2. [Neuroinflammation](/mskb/concepts/mechanisms/neuroinflammation/)",
                "3. [What is MS again](/mskb/concepts/foundations/what-is-ms/)",
            ]
        ),
        encoding="utf-8",
    )

    concept_index = taxonomy.load_concept_index(concepts_root)
    steps = taxonomy.build_pathway_steps(pathways_root, concept_index)

    assert steps["clinical"] == ["what_is_ms", "mechanisms_neuroinflammation"]


def test_all_real_pathway_steps_resolve_to_known_concepts() -> None:
    concepts_root = REPO_ROOT / "site" / "src" / "content" / "docs" / "concepts"
    pathways_root = REPO_ROOT / "site" / "src" / "content" / "docs" / "pathways"
    concept_index = taxonomy.load_concept_index(concepts_root)
    pathway_steps = taxonomy.build_pathway_steps(pathways_root, concept_index)

    known_ids = {cid for cid in concept_index.keys() if not cid.startswith("__")}
    assert pathway_steps, "expected non-empty pathway extraction from real docs"
    for pathway_id, steps in pathway_steps.items():
        assert steps, f"pathway {pathway_id} has no resolved concept steps"
        for concept_id in steps:
            assert concept_id in known_ids, f"pathway {pathway_id} references unknown concept id: {concept_id}"


def test_real_topic_categories_and_concept_topic_coverage() -> None:
    concepts_root = REPO_ROOT / "site" / "src" / "content" / "docs" / "concepts"
    concept_index = taxonomy.load_concept_index(concepts_root)
    concept_ids = [cid for cid in concept_index.keys() if not cid.startswith("__")]

    concept_cache = json.loads((REPO_ROOT / "data" / "concept_papers.json").read_text(encoding="utf-8"))
    concept_papers = concept_cache.get("concepts") or {}

    paper_topics = pd.read_csv(REPO_ROOT / "outputs" / "topics" / "paper_topics.csv")
    topic_clusters = pd.read_csv(REPO_ROOT / "outputs" / "topics" / "topic_clusters.csv")
    concept_to_topics, topic_to_concepts = taxonomy.build_concept_topic_links(
        concept_papers=concept_papers,
        paper_topics_rows=paper_topics.to_dict(orient="records"),
    )
    derived = taxonomy.derive_topic_categories(
        topic_clusters_rows=topic_clusters.to_dict(orient="records"),
        concept_index=concept_index,
        topic_to_concepts=topic_to_concepts,
    )

    assert derived, "expected derived topic categories"
    for topic_id, info in derived.items():
        assert info["topic_category"] in taxonomy.CATEGORY_ORDER, (
            f"topic {topic_id} mapped outside the 5-category set: {info['topic_category']}"
        )
        assert info["category_source"] in {"concept", "fallback"}

    linked_concepts = sum(1 for cid in concept_ids if concept_to_topics.get(cid))
    assert linked_concepts >= 30, f"expected >=30 linked concepts, got {linked_concepts}"
    assert (linked_concepts / max(1, len(concept_ids))) >= 0.75, (
        f"expected at least 75% of concepts linked to topics; got {linked_concepts}/{len(concept_ids)}"
    )
