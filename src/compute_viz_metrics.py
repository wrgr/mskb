"""Compute lineage and field-development JSON assets for the MSKB website."""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from .utils import ensure_dir, load_config

LOG = logging.getLogger(__name__)

# Human-readable labels for the five MS research domains.
CATEGORY_LABELS: dict[str, str] = {
    "pathogenesis_and_immunology": "Pathogenesis & Immunology",
    "imaging_and_biomarkers": "Imaging & Biomarkers",
    "clinical_trials_and_therapeutics": "Therapeutics",
    "clinical_care_and_management": "Clinical Care",
    "epidemiology_and_population_health": "Epidemiology",
}

# Sanity bounds: papers outside this year range are dropped from charts.
_YEAR_MIN = 1970
_YEAR_MAX = 2030

# Tier codes that indicate a paper should appear in visualizations.
_INCLUDED_TIERS = {"T1", "T2", "T3", "T4", "included", "core"}


def _safe_int(v: Any, default: int = 0) -> int:
    """Coerce v to int, returning default on failure."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Coerce v to float, returning default on failure."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _compute_generations(graph: nx.DiGraph) -> dict[str, int]:
    """BFS backward from foundational papers; generation 0 has no outgoing citations.

    Papers with out-degree 0 are treated as foundational (generation 0). Every
    paper that cites a generation-N paper receives generation N+1. Papers not
    reachable in this BFS (isolated nodes) default to generation 0.
    """
    out_deg = dict(graph.out_degree())
    # reverse_adj[p] = list of papers that cite p
    reverse_adj: dict[str, list[str]] = defaultdict(list)
    for src, tgt in graph.edges():
        reverse_adj[tgt].append(src)

    generations: dict[str, int] = {}
    queue: deque[str] = deque()
    visited: set[str] = set()

    for pid, deg in out_deg.items():
        if deg == 0:
            generations[pid] = 0
            queue.append(pid)
            visited.add(pid)

    while queue:
        curr = queue.popleft()
        for citing in reverse_adj[curr]:
            if citing not in visited:
                generations[citing] = generations[curr] + 1
                visited.add(citing)
                queue.append(citing)

    for pid in graph.nodes():
        if pid not in generations:
            generations[pid] = 0

    return generations


def _build_citation_graph(included_ids: set[str], edges: pd.DataFrame) -> nx.DiGraph:
    """Build a directed citation graph restricted to the included paper set."""
    g: nx.DiGraph = nx.DiGraph()
    g.add_nodes_from(included_ids)
    src_col = next((c for c in ("source_paper_id", "citing_paper_id") if c in edges.columns), None)
    tgt_col = next((c for c in ("target_paper_id", "cited_paper_id") if c in edges.columns), None)
    if src_col is None or tgt_col is None:
        return g
    for _, row in edges.iterrows():
        src, tgt = str(row[src_col]), str(row[tgt_col])
        if src in included_ids and tgt in included_ids and src != tgt:
            g.add_edge(src, tgt)
    return g


def _build_topic_map(topics_dir: Path) -> dict[str, str]:
    """Join paper_topics.csv + topic_clusters.csv to get per-paper category."""
    pt_path = topics_dir / "paper_topics.csv"
    tc_path = topics_dir / "topic_clusters.csv"
    if not pt_path.exists() or not tc_path.exists():
        return {}

    pt = pd.read_csv(pt_path, usecols=lambda c: c in {"canonical_paper_id", "topic_id"})
    tc = pd.read_csv(tc_path, usecols=lambda c: c in {"topic_id", "dominant_category"})
    if "dominant_category" not in tc.columns:
        return {}

    merged = pt.merge(tc, on="topic_id", how="left")
    topic_map: dict[str, str] = {}
    for _, row in merged.iterrows():
        pid = str(row["canonical_paper_id"])
        # First assignment wins (papers belong to at most one primary topic)
        if pid not in topic_map:
            topic_map[pid] = str(row.get("dominant_category", "unknown"))
    return topic_map


def _build_lineage_nodes(
    papers: pd.DataFrame,
    graph: nx.DiGraph,
    generations: dict[str, int],
    topic_map: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return sorted node list and paper-id-to-index mapping for lineage JSON."""
    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())
    rows = {str(r["canonical_paper_id"]): r for _, r in papers.iterrows()}

    # Sort: foundational first (gen 0), then ascending year within each generation.
    sorted_pids = sorted(
        rows,
        key=lambda p: (generations.get(p, 0), _safe_int(rows[p].get("year", 0))),
    )

    node_index: dict[str, int] = {}
    nodes: list[dict[str, Any]] = []
    for idx, pid in enumerate(sorted_pids):
        node_index[pid] = idx
        row = rows[pid]
        importance = _safe_float(row.get("paper_importance_score", 0.0))
        # Fall back to dominant_category column when topic join unavailable
        category = topic_map.get(pid) or str(row.get("dominant_category", "unknown"))
        nodes.append({
            "id": idx,
            "paper_id": pid,
            "title": str(row.get("title", "")),
            "year": _safe_int(row.get("year", 0)),
            "cited_by_count": _safe_int(row.get("merged_cited_by_count", 0)),
            "doi": str(row.get("doi", "")),
            "first_author": str(row.get("first_author", "")),
            "in_degree": in_deg.get(pid, 0),
            "out_degree": out_deg.get(pid, 0),
            "generation": generations.get(pid, 0),
            "importance_score": round(importance, 4),
            "category": category,
            "tier": str(row.get("tier", "included")),
        })
    return nodes, node_index


def _build_lineage_json(
    papers: pd.DataFrame,
    graph: nx.DiGraph,
    generations: dict[str, int],
    topic_map: dict[str, str],
) -> dict[str, Any]:
    """Assemble lineage_data.json with nodes, citation links, and corpus metadata."""
    nodes, node_index = _build_lineage_nodes(papers, graph, generations, topic_map)
    in_deg = dict(graph.in_degree())

    links = [
        {"source": node_index[src], "target": node_index[tgt], "strength": in_deg.get(tgt, 1)}
        for src, tgt in graph.edges()
        if src in node_index and tgt in node_index
    ]

    valid_years = [n["year"] for n in nodes if _YEAR_MIN < n["year"] < _YEAR_MAX]
    gen_vals = [n["generation"] for n in nodes]
    return {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_papers": len(nodes),
            "total_citations": len(links),
            "generation_count": (max(gen_vals) + 1) if gen_vals else 0,
            "year_range": [
                min(valid_years, default=0),
                max(valid_years, default=0),
            ],
        },
    }


def _build_field_development_json(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble field_development.json with yearly timeline and paper scatter data."""
    yearly_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    yearly_importance: dict[int, list[float]] = defaultdict(list)
    scatter: list[dict[str, Any]] = []

    for n in nodes:
        year = n["year"]
        if not (_YEAR_MIN < year < _YEAR_MAX):
            continue
        cat = n["category"]
        yearly_counts[year][cat] += 1
        yearly_importance[year].append(n["importance_score"])
        scatter.append({
            "id": n["paper_id"],
            "title": n["title"][:80],
            "year": year,
            "importance_score": n["importance_score"],
            "cited_by_count": n["cited_by_count"],
            "category": cat,
        })

    all_cats = sorted({c for yd in yearly_counts.values() for c in yd})
    timeline = []
    for year in sorted(yearly_counts):
        entry: dict[str, Any] = {"year": year, "total": 0}
        for cat in all_cats:
            cnt = yearly_counts[year].get(cat, 0)
            entry[cat] = cnt
            entry["total"] += cnt
        imp = yearly_importance.get(year, [0.0])
        entry["avg_importance"] = round(sum(imp) / len(imp), 4)
        timeline.append(entry)

    valid_years = [n["year"] for n in nodes if _YEAR_MIN < n["year"] < _YEAR_MAX]
    return {
        "timeline": timeline,
        "scatter": scatter,
        "categories": {c: CATEGORY_LABELS.get(c, c.replace("_", " ").title()) for c in all_cats},
        "metadata": {
            "total_papers": len(nodes),
            "year_range": [
                min(valid_years, default=0),
                max(valid_years, default=0),
            ],
        },
    }


def _load_scored_papers(graph_dir: Path) -> pd.DataFrame | None:
    """Load scored papers from the first existing candidate CSV path."""
    candidates = [
        graph_dir / "core_corpus_tracked_with_t4.csv",
        graph_dir / "core_corpus_selected.csv",
        graph_dir / "scored_papers.csv",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return None

    wanted = {
        "canonical_paper_id", "title", "year", "doi", "first_author",
        "merged_cited_by_count", "paper_importance_score", "dominant_category",
        "anchor_category", "tier", "venue", "corpus_role",
    }
    df = pd.read_csv(path, usecols=lambda c: c in wanted)
    df["canonical_paper_id"] = df["canonical_paper_id"].astype(str)
    return df


def _build_corpus_stats_json(
    papers: pd.DataFrame,
    graph: nx.DiGraph,
    topic_map: dict[str, str],
    author_metrics_path: Path,
) -> dict[str, Any]:
    """Assemble corpus_stats.json with top papers, top authors, and venue/domain breakdowns."""
    in_deg = dict(graph.in_degree())

    # ── Per-paper rows ───────────────────────────────────────────────────────
    paper_rows: list[dict[str, Any]] = []
    for _, row in papers.iterrows():
        pid = str(row["canonical_paper_id"])
        year = _safe_int(row.get("year", 0))
        if not (_YEAR_MIN < year < _YEAR_MAX):
            continue
        # anchor_category is set specifically for the core corpus; prefer it
        # over the full-graph topic_map which can be skewed.
        _nan = {"nan", "none", "unmapped", ""}
        _anchor = str(row.get("anchor_category", "") or "").lower().strip()
        _dominant = str(row.get("dominant_category", "") or "").lower().strip()
        category = (
            str(row.get("anchor_category", "")) if _anchor not in _nan else ""
        ) or (
            str(row.get("dominant_category", "")) if _dominant not in _nan else ""
        ) or topic_map.get(pid, "") or "unknown"
        venue = str(row.get("venue", "") or "")
        paper_rows.append({
            "id": pid,
            "title": str(row.get("title", ""))[:120],
            "year": year,
            "first_author": str(row.get("first_author", "")),
            "venue": venue if venue.lower() not in {"nan", "none", ""} else "",
            "doi": str(row.get("doi", "") or ""),
            "global_citations": _safe_int(row.get("merged_cited_by_count", 0)),
            "corpus_citations": in_deg.get(pid, 0),
            "importance_score": round(_safe_float(row.get("paper_importance_score", 0.0)), 4),
            "category": category,
            "corpus_role": str(row.get("corpus_role", "core")),
        })

    # ── Top papers (25 each) ─────────────────────────────────────────────────
    def top_papers(key: str, n: int = 25) -> list[dict[str, Any]]:
        return sorted(paper_rows, key=lambda p: p[key], reverse=True)[:n]

    # ── Venue counts ─────────────────────────────────────────────────────────
    venue_counts: dict[str, int] = defaultdict(int)
    for p in paper_rows:
        v = p["venue"].strip()
        if v and v.lower() not in {"nan", "none", ""}:
            venue_counts[v] += 1
    venues = sorted(venue_counts.items(), key=lambda x: x[1], reverse=True)

    # ── Domain counts ────────────────────────────────────────────────────────
    domain_counts: dict[str, int] = defaultdict(int)
    for p in paper_rows:
        domain_counts[p["category"]] += 1

    # ── Decade distribution ──────────────────────────────────────────────────
    decade_counts: dict[str, int] = defaultdict(int)
    for p in paper_rows:
        decade = (p["year"] // 10) * 10
        decade_counts[str(decade)] += 1

    # ── Author metrics ───────────────────────────────────────────────────────
    top_authors: list[dict[str, Any]] = []
    if author_metrics_path.exists():
        auth = pd.read_csv(author_metrics_path)
        # Require at least 2 included papers to filter out single-paper cameos.
        active = auth[auth["n_included_papers"] >= 2].copy()
        active_sorted = active.nlargest(30, "author_importance_score")
        for _, row in active_sorted.iterrows():
            top_authors.append({
                "name": str(row.get("display_name", "")),
                "papers": _safe_int(row.get("n_included_papers", 0)),
                "global_citations": _safe_int(row.get("total_citations", 0)),
                "corpus_citations": _safe_int(row.get("corpus_citations_received", 0)),
                "importance_score": round(_safe_float(row.get("author_importance_score", 0.0)), 3),
            })

    # ── Metadata ─────────────────────────────────────────────────────────────
    valid_years = [p["year"] for p in paper_rows]
    total_global_cites = sum(p["global_citations"] for p in paper_rows)
    peak_venue = venues[0][0] if venues else ""

    return {
        "metadata": {
            "total_papers": len(paper_rows),
            "year_range": [min(valid_years, default=0), max(valid_years, default=0)],
            "total_global_citations": total_global_cites,
            "n_authors": len(top_authors),
            "n_venues": len(venues),
            "peak_venue": peak_venue,
            "domains": dict(domain_counts),
            "decades": dict(sorted(decade_counts.items())),
        },
        "top_papers_by_global_citations": top_papers("global_citations"),
        "top_papers_by_corpus_citations": top_papers("corpus_citations"),
        "top_papers_by_importance": top_papers("importance_score"),
        "top_authors": top_authors,
        "venues": [{"name": v, "count": c} for v, c in venues[:40]],
    }


def run(config_path: str) -> None:
    """Load pipeline outputs and write lineage, field-development, and corpus-stats JSON assets."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph_dir = root / cfg["output_dir"] / "graph"
    topics_dir = root / cfg["output_dir"] / "topics"
    web_dir = root / cfg["output_dir"] / "website"
    ensure_dir(web_dir)

    papers = _load_scored_papers(graph_dir)
    edges_path = graph_dir / "corpus_citation_edges.csv"
    if papers is None or not edges_path.exists():
        LOG.warning("Skipping viz metrics: scored papers or citation edges not found.")
        return

    edges = pd.read_csv(edges_path)
    topic_map = _build_topic_map(topics_dir)

    if "tier" in papers.columns:
        included = papers[papers["tier"].isin(_INCLUDED_TIERS)]
    else:
        included = papers

    included_ids = set(included["canonical_paper_id"].tolist())
    graph = _build_citation_graph(included_ids, edges)
    generations = _compute_generations(graph)

    lineage = _build_lineage_json(included, graph, generations, topic_map)
    (web_dir / "lineage_data.json").write_text(
        json.dumps(lineage, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    LOG.info("lineage_data.json: %d nodes, %d links", len(lineage["nodes"]), len(lineage["links"]))

    field_dev = _build_field_development_json(lineage["nodes"])
    (web_dir / "field_development.json").write_text(
        json.dumps(field_dev, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    LOG.info(
        "field_development.json: %d years, %d papers",
        len(field_dev["timeline"]),
        len(field_dev["scatter"]),
    )

    corpus_stats = _build_corpus_stats_json(
        included, graph, topic_map, graph_dir / "author_metrics.csv"
    )
    (web_dir / "corpus_stats.json").write_text(
        json.dumps(corpus_stats, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    LOG.info(
        "corpus_stats.json: %d papers, %d authors, %d venues",
        corpus_stats["metadata"]["total_papers"],
        len(corpus_stats["top_authors"]),
        corpus_stats["metadata"]["n_venues"],
    )
