#!/usr/bin/env python3
"""Shared taxonomy derivation helpers for site generation.

This module centralizes concept/topic/pathway relationships so multiple pages
can render from one consistent derivation.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


CATEGORY_ORDER = [
    "pathogenesis_and_immunology",
    "imaging_and_biomarkers",
    "clinical_trials_and_therapeutics",
    "clinical_care_and_management",
    "epidemiology_and_population_health",
]

CONCEPT_TO_TOPIC_CATEGORY = {
    "foundations": "clinical_care_and_management",
    "mechanisms": "pathogenesis_and_immunology",
    "diagnosis": "imaging_and_biomarkers",
    "therapeutics": "clinical_trials_and_therapeutics",
    "clinical": "clinical_care_and_management",
}


def normalize_topic_id(value: Any) -> str:
    """Normalize topic ids so maps can use a stable key type."""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    try:
        # Keep numeric ids stable even if read as floats in CSV pipelines.
        return str(int(float(text)))
    except ValueError:
        return text


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def canonicalize_category(value: Any, fallback: str = "") -> str:
    """Map concept-level categories into the 5-category topic taxonomy."""
    raw = _clean_text(value)
    if not raw:
        return _clean_text(fallback)
    if raw in CATEGORY_ORDER:
        return raw
    mapped = CONCEPT_TO_TOPIC_CATEGORY.get(raw)
    if mapped:
        return mapped
    return _clean_text(fallback) or raw


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.DOTALL)
    if not match:
        return {}, text
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def load_concept_index(concepts_root: Path) -> dict[str, dict[str, Any]]:
    """Load canonical concept metadata from concept markdown frontmatter."""
    if not concepts_root.exists():
        raise FileNotFoundError(f"Concept directory not found: {concepts_root}")

    concept_index: dict[str, dict[str, Any]] = {}
    by_route: dict[str, str] = {}
    for path in sorted(concepts_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        if path.name == "index.mdx":
            continue

        rel = path.relative_to(concepts_root)
        if len(rel.parts) != 2:
            continue
        section = rel.parts[0]
        slug = path.stem

        frontmatter, _body = _parse_frontmatter(path)
        concept_meta = frontmatter.get("concept")
        if not isinstance(concept_meta, dict):
            continue

        concept_id = _clean_text(concept_meta.get("id"))
        if not concept_id:
            continue
        category = _clean_text(concept_meta.get("category")) or section
        title = _clean_text(frontmatter.get("title")) or concept_id.replace("_", " ").title()
        description = _clean_text(frontmatter.get("description"))
        raw_papers = concept_meta.get("papers") or []
        papers = tuple(_clean_text(paper) for paper in raw_papers if _clean_text(paper))

        concept_index[concept_id] = {
            "id": concept_id,
            "category": category,
            "title": title,
            "description": description,
            "path": f"{section}/{slug}",
            "source_path": str(path),
            "papers_frontmatter": papers,
        }
        by_route[f"{section}/{slug}"] = concept_id

    # Attach reverse route map for pathway parsing convenience.
    concept_index["__route_map__"] = by_route
    return concept_index


def _iter_pathway_files(pathways_root: Path) -> list[Path]:
    paths = []
    for path in sorted(pathways_root.glob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        if path.name.startswith("index."):
            continue
        paths.append(path)
    return paths


def build_pathway_steps(pathways_root: Path, concept_index: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Extract ordered pathway concept ids from pathway markdown links."""
    route_map = concept_index.get("__route_map__", {})
    if not isinstance(route_map, dict):
        route_map = {}

    # Matches: /mskb/concepts/<section>/<slug>/...
    concept_link_pattern = re.compile(r"/mskb/concepts/([^/]+)/([^)/#]+)/?")
    out: dict[str, list[str]] = {}
    for path in _iter_pathway_files(pathways_root):
        text = path.read_text(encoding="utf-8")
        seen: set[str] = set()
        ordered: list[str] = []
        for section, slug in concept_link_pattern.findall(text):
            route = f"{section}/{slug}"
            concept_id = route_map.get(route)
            if not concept_id or concept_id in seen:
                continue
            seen.add(concept_id)
            ordered.append(concept_id)
        out[path.stem] = ordered
    return out


def build_concept_topic_links(
    *,
    concept_papers: dict[str, dict[str, Any]],
    paper_topics_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """Build concept->topics and topic->concept overlap counts."""
    paper_to_topics: dict[str, set[str]] = defaultdict(set)
    for row in paper_topics_rows:
        paper_id = _clean_text(row.get("canonical_paper_id"))
        topic_id = normalize_topic_id(row.get("topic_id"))
        if not paper_id or not topic_id:
            continue
        paper_to_topics[paper_id].add(topic_id)

    concept_to_topics: dict[str, dict[str, int]] = {}
    topic_to_concepts_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for concept_id, payload in concept_papers.items():
        if concept_id.startswith("__"):
            continue
        if not isinstance(payload, dict):
            continue
        selected_ids: list[str] = []
        for group in ("foundational", "advanced"):
            values = payload.get(group)
            if isinstance(values, list):
                selected_ids.extend(_clean_text(v) for v in values if _clean_text(v))
        if not selected_ids:
            concept_to_topics[concept_id] = {}
            continue

        counts: Counter[str] = Counter()
        for paper_id in selected_ids:
            for topic_id in paper_to_topics.get(paper_id, set()):
                counts[topic_id] += 1
                topic_to_concepts_counts[topic_id][concept_id] += 1
        concept_to_topics[concept_id] = dict(counts)

    topic_to_concepts = {topic_id: dict(counter) for topic_id, counter in topic_to_concepts_counts.items()}
    return concept_to_topics, topic_to_concepts


def derive_topic_categories(
    *,
    topic_clusters_rows: list[dict[str, Any]],
    concept_index: dict[str, dict[str, Any]],
    topic_to_concepts: dict[str, dict[str, int]],
) -> dict[str, dict[str, Any]]:
    """Derive topic display categories from concept overlap (with fallback)."""
    out: dict[str, dict[str, Any]] = {}
    for row in topic_clusters_rows:
        topic_id = normalize_topic_id(row.get("topic_id"))
        if not topic_id:
            continue
        fallback = canonicalize_category(row.get("dominant_category"), CATEGORY_ORDER[0]) or CATEGORY_ORDER[0]
        overlap = topic_to_concepts.get(topic_id, {})
        if not overlap:
            out[topic_id] = {
                "topic_category": fallback,
                "category_source": "fallback",
                "top_concept_id": "",
                "overlap_count": 0,
            }
            continue

        category_counts: Counter[str] = Counter()
        for concept_id, count in overlap.items():
            concept = concept_index.get(concept_id) or {}
            category = canonicalize_category(concept.get("category"))
            if not category:
                continue
            category_counts[category] += int(count)

        if not category_counts:
            out[topic_id] = {
                "topic_category": fallback,
                "category_source": "fallback",
                "top_concept_id": "",
                "overlap_count": 0,
            }
            continue

        def category_sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
            category, count = item
            try:
                order_idx = CATEGORY_ORDER.index(category)
            except ValueError:
                order_idx = len(CATEGORY_ORDER)
            return (-count, order_idx, category)

        best_category, best_count = sorted(category_counts.items(), key=category_sort_key)[0]
        top_concept_id, _top_count = sorted(
            overlap.items(),
            key=lambda item: (-int(item[1]), item[0]),
        )[0]
        out[topic_id] = {
            "topic_category": best_category,
            "category_source": "concept",
            "top_concept_id": top_concept_id,
            "overlap_count": int(best_count),
        }
    return out


def layout_layered(
    *,
    layers: list[list[str]],
    edges: list[tuple[str, str]],
    sweeps: int = 4,
    x_gap: float = 260.0,
    y_gap: float = 86.0,
) -> dict[str, dict[str, float | int]]:
    """Compute layered coordinates with barycenter sweeps (L->R then R->L)."""
    if not layers:
        return {}

    ordered_layers = [list(layer) for layer in layers]
    node_layer: dict[str, int] = {}
    for layer_idx, layer_nodes in enumerate(ordered_layers):
        for node_id in layer_nodes:
            node_layer[node_id] = layer_idx

    # Keep only adjacent-layer edges for barycenter ordering.
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        if source not in node_layer or target not in node_layer:
            continue
        s_layer = node_layer[source]
        t_layer = node_layer[target]
        if abs(s_layer - t_layer) != 1:
            continue
        outgoing[source].add(target)
        incoming[target].add(source)

    def index_map(layer_nodes: list[str]) -> dict[str, int]:
        return {node_id: idx for idx, node_id in enumerate(layer_nodes)}

    for _ in range(max(1, sweeps)):
        # L -> R using incoming neighbors.
        for layer_idx in range(1, len(ordered_layers)):
            prev_idx = index_map(ordered_layers[layer_idx - 1])
            current = ordered_layers[layer_idx]

            def left_bary(node_id: str) -> tuple[float, int]:
                neighbors = incoming.get(node_id, set())
                if not neighbors:
                    return (float("inf"), current.index(node_id))
                vals = [prev_idx[n] for n in neighbors if n in prev_idx]
                if not vals:
                    return (float("inf"), current.index(node_id))
                return (sum(vals) / len(vals), current.index(node_id))

            ordered_layers[layer_idx] = sorted(current, key=left_bary)

        # R -> L using outgoing neighbors.
        for layer_idx in range(len(ordered_layers) - 2, -1, -1):
            next_idx = index_map(ordered_layers[layer_idx + 1])
            current = ordered_layers[layer_idx]

            def right_bary(node_id: str) -> tuple[float, int]:
                neighbors = outgoing.get(node_id, set())
                if not neighbors:
                    return (float("inf"), current.index(node_id))
                vals = [next_idx[n] for n in neighbors if n in next_idx]
                if not vals:
                    return (float("inf"), current.index(node_id))
                return (sum(vals) / len(vals), current.index(node_id))

            ordered_layers[layer_idx] = sorted(current, key=right_bary)

    coords: dict[str, dict[str, float | int]] = {}
    for layer_idx, layer_nodes in enumerate(ordered_layers):
        for rank, node_id in enumerate(layer_nodes):
            coords[node_id] = {
                "x": round(layer_idx * x_gap, 4),
                "y": round(rank * y_gap, 4),
                "layer": layer_idx,
                "rank": rank,
            }
    return coords
