"""Tests for compute_viz_metrics: generation BFS, lineage/field-dev JSON shape."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from src.compute_viz_metrics import (
    _build_citation_graph,
    _build_field_development_json,
    _build_lineage_json,
    _build_site_stats_json,
    _build_topic_map,
    _compute_generations,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LINEAGE_JS = REPO_ROOT / "site" / "public" / "javascripts" / "lineage.js"
FIELD_DEV_JS = REPO_ROOT / "site" / "public" / "javascripts" / "field_development.js"
LINEAGE_MDX = REPO_ROOT / "site" / "src" / "content" / "docs" / "lineage.mdx"
FIELD_DEV_MDX = REPO_ROOT / "site" / "src" / "content" / "docs" / "field-development.mdx"


# ── generation computation ────────────────────────────────────────────────────

def _simple_graph() -> nx.DiGraph:
    """Build a three-generation chain: A → B → C (A foundational, C frontier)."""
    g = nx.DiGraph()
    g.add_nodes_from(["A", "B", "C"])
    # A cites nothing (foundational), B cites A, C cites B
    g.add_edge("B", "A")
    g.add_edge("C", "B")
    return g


def test_compute_generations_chain() -> None:
    """Foundational paper gets generation 0; each citing layer increments by one."""
    g = _simple_graph()
    gens = _compute_generations(g)
    assert gens["A"] == 0
    assert gens["B"] == 1
    assert gens["C"] == 2


def test_compute_generations_isolated_node() -> None:
    """Isolated nodes (no edges) default to generation 0."""
    g = nx.DiGraph()
    g.add_node("X")
    gens = _compute_generations(g)
    assert gens["X"] == 0


def test_compute_generations_empty_graph() -> None:
    """Empty graph returns an empty dict without raising."""
    gens = _compute_generations(nx.DiGraph())
    assert gens == {}


# ── citation graph builder ────────────────────────────────────────────────────

def test_build_citation_graph_filters_excluded() -> None:
    """Edges referencing papers not in included_ids are dropped."""
    edges = pd.DataFrame({"source_paper_id": ["A", "B"], "target_paper_id": ["B", "C"]})
    g = _build_citation_graph({"A", "B"}, edges)
    # Edge B→C is dropped because C is excluded
    assert g.has_edge("A", "B")
    assert not g.has_edge("B", "C")


def test_build_citation_graph_self_loops_dropped() -> None:
    """Self-loop edges are silently ignored."""
    edges = pd.DataFrame({"source_paper_id": ["A"], "target_paper_id": ["A"]})
    g = _build_citation_graph({"A"}, edges)
    assert not g.has_edge("A", "A")


# ── lineage JSON structure ────────────────────────────────────────────────────

def _sample_papers() -> pd.DataFrame:
    return pd.DataFrame({
        "canonical_paper_id": ["A", "B", "C"],
        "title": ["Alpha", "Beta", "Gamma"],
        "year": [2000, 2010, 2020],
        "doi": ["10.1/a", "10.1/b", "10.1/c"],
        "first_author": ["Smith", "Jones", "Lee"],
        "merged_cited_by_count": [100, 50, 10],
        "paper_importance_score": [0.9, 0.5, 0.2],
        "dominant_category": ["pathogenesis_and_immunology"] * 3,
        "tier": ["T1", "T2", "T3"],
    })


def test_build_lineage_json_structure() -> None:
    """lineage_data.json has expected top-level keys and correct node count."""
    papers = _sample_papers()
    g = _build_citation_graph(set(papers["canonical_paper_id"]), pd.DataFrame(columns=["source_paper_id", "target_paper_id"]))
    gens = _compute_generations(g)
    payload = _build_lineage_json(papers, g, gens, {})
    assert set(payload) == {"nodes", "links", "metadata"}
    assert payload["metadata"]["total_papers"] == 3
    assert isinstance(payload["nodes"], list)
    assert isinstance(payload["links"], list)


def test_build_lineage_json_node_fields() -> None:
    """Each node carries required fields for the front-end renderer."""
    papers = _sample_papers()
    g = _build_citation_graph(set(papers["canonical_paper_id"]), pd.DataFrame(columns=["source_paper_id", "target_paper_id"]))
    gens = _compute_generations(g)
    payload = _build_lineage_json(papers, g, gens, {})
    required = {"id", "paper_id", "title", "year", "cited_by_count", "in_degree", "out_degree", "generation", "importance_score", "category"}
    for node in payload["nodes"]:
        assert required.issubset(node), f"Missing fields in node: {required - set(node)}"


# ── field development JSON structure ─────────────────────────────────────────

def _sample_nodes() -> list[dict]:
    return [
        {"paper_id": "A", "title": "Alpha", "year": 2000, "importance_score": 0.9,
         "cited_by_count": 100, "category": "pathogenesis_and_immunology"},
        {"paper_id": "B", "title": "Beta", "year": 2010, "importance_score": 0.5,
         "cited_by_count": 50, "category": "imaging_and_biomarkers"},
    ]


def test_build_field_development_json_structure() -> None:
    """field_development.json has expected top-level keys and timeline entries."""
    payload = _build_field_development_json(_sample_nodes())
    assert set(payload) == {"timeline", "scatter", "categories", "metadata"}
    assert len(payload["timeline"]) == 2
    assert len(payload["scatter"]) == 2


def test_build_field_development_json_year_bounds() -> None:
    """Papers with years outside [1970, 2030] are excluded from timeline and scatter."""
    nodes = _sample_nodes() + [
        {"paper_id": "X", "title": "Old", "year": 1800, "importance_score": 0.1,
         "cited_by_count": 5, "category": "unknown"},
    ]
    payload = _build_field_development_json(nodes)
    years = [e["year"] for e in payload["timeline"]]
    assert 1800 not in years


# ── site stats JSON structure ────────────────────────────────────────────────

def test_build_site_stats_splits_curated_and_neighborhood() -> None:
    """curatedPapers counts core + expert_signal; neighborhoodPapers counts context; total is their sum."""
    included = pd.DataFrame({
        "canonical_paper_id": ["A", "B", "C", "D", "E"],
        "corpus_role": ["core", "core", "expert_signal", "context", "context"],
    })
    stats = _build_site_stats_json(included, as_of="April 2026")
    assert stats == {
        "curatedPapers": 3,
        "neighborhoodPapers": 2,
        "totalArtifacts": 5,
        "asOf": "April 2026",
    }


def test_build_site_stats_empty_frame() -> None:
    """Empty input yields zero counts and preserves the provided as_of string."""
    included = pd.DataFrame({"canonical_paper_id": [], "corpus_role": []})
    stats = _build_site_stats_json(included, as_of="January 2026")
    assert stats["curatedPapers"] == 0
    assert stats["neighborhoodPapers"] == 0
    assert stats["totalArtifacts"] == 0
    assert stats["asOf"] == "January 2026"


# ── file existence checks ─────────────────────────────────────────────────────

def test_lineage_js_exists() -> None:
    """lineage.js asset file must exist for the visualization to load."""
    assert LINEAGE_JS.exists(), f"Missing: {LINEAGE_JS}"


def test_field_development_js_exists() -> None:
    """field_development.js asset file must exist for charts to render."""
    assert FIELD_DEV_JS.exists(), f"Missing: {FIELD_DEV_JS}"


def test_lineage_mdx_exists() -> None:
    """lineage.mdx page file must exist in site content."""
    assert LINEAGE_MDX.exists(), f"Missing: {LINEAGE_MDX}"


def test_field_development_mdx_exists() -> None:
    """field-development.mdx page file must exist in site content."""
    assert FIELD_DEV_MDX.exists(), f"Missing: {FIELD_DEV_MDX}"
