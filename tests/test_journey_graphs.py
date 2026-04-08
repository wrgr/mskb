"""Contract tests for generated learning-spine and research-map graph JSON assets."""

from __future__ import annotations

import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "site" / "public" / "assets"
SPINE_PATH = ASSETS_DIR / "learning_spine_graph.json"
RESEARCH_PATH = ASSETS_DIR / "research_map_graph.json"


def _load(path: Path) -> dict:
    assert path.exists(), f"missing graph asset: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload.get("nodes"), list)
    assert isinstance(payload.get("edges"), list)
    return payload


def _validate_node_geometry(nodes: list[dict]) -> None:
    for node in nodes:
        x = float(node.get("x", 0.0))
        y = float(node.get("y", 0.0))
        assert math.isfinite(x), f"non-finite x for node {node.get('id')}"
        assert math.isfinite(y), f"non-finite y for node {node.get('id')}"


def _validate_edge_endpoints(nodes: list[dict], edges: list[dict]) -> None:
    ids = {str(node.get("id", "")) for node in nodes}
    for edge in edges:
        src = str(edge.get("source", ""))
        dst = str(edge.get("target", ""))
        assert src in ids, f"dangling edge source: {src}"
        assert dst in ids, f"dangling edge target: {dst}"


def test_learning_spine_graph_contract() -> None:
    payload = _load(SPINE_PATH)
    nodes = payload["nodes"]
    edges = payload["edges"]

    _validate_node_geometry(nodes)
    _validate_edge_endpoints(nodes, edges)

    pathway_nodes = [n for n in nodes if str(n.get("id", "")).startswith("pathway:")]
    category_nodes = [n for n in nodes if str(n.get("id", "")).startswith("category:")]
    concept_nodes = [n for n in nodes if str(n.get("id", "")).startswith("concept:")]

    assert len(pathway_nodes) == 3, f"expected 3 pathway nodes, got {len(pathway_nodes)}"
    assert len(category_nodes) == 5, f"expected 5 category nodes, got {len(category_nodes)}"
    assert len(concept_nodes) >= 30, f"expected >=30 concept nodes, got {len(concept_nodes)}"


def test_research_map_graph_contract() -> None:
    payload = _load(RESEARCH_PATH)
    nodes = payload["nodes"]
    edges = payload["edges"]

    _validate_node_geometry(nodes)
    _validate_edge_endpoints(nodes, edges)

    category_ids = {str(n.get("id")) for n in nodes if str(n.get("id", "")).startswith("category:")}
    topic_ids = {str(n.get("id")) for n in nodes if str(n.get("id", "")).startswith("topic:")}

    assert category_ids, "expected at least one category node in research map"
    assert topic_ids, "expected at least one topic node in research map"

    topics_by_category = {cid: set() for cid in category_ids}
    for edge in edges:
        src = str(edge.get("source", ""))
        dst = str(edge.get("target", ""))
        if src in category_ids and dst in topic_ids:
            topics_by_category[src].add(dst)

    for category_id, topic_set in topics_by_category.items():
        assert topic_set, f"category {category_id} has no linked topics"
