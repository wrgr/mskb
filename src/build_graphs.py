
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import pandas as pd

from .utils import ensure_dir, load_config

try:
    import community as community_louvain
except Exception:
    community_louvain = None

try:
    import igraph as ig
    import leidenalg
    _LEIDEN_AVAILABLE = True
except Exception:
    _LEIDEN_AVAILABLE = False


def _pagerank(graph: nx.DiGraph, alpha: float = 0.85, max_iter: int = 100, tol: float = 1.0e-6) -> dict:
    if graph.number_of_nodes() == 0:
        return {}
    nodes = list(graph.nodes())
    n = len(nodes)
    ranks = {node: 1.0 / n for node in nodes}
    out_degree = {node: graph.out_degree(node) for node in nodes}
    base = (1.0 - alpha) / n

    for _ in range(max_iter):
        prev = ranks.copy()
        dangling_mass = alpha * sum(prev[node] for node, degree in out_degree.items() if degree == 0) / n
        ranks = {node: base + dangling_mass for node in nodes}
        for node in nodes:
            degree = out_degree[node]
            if degree == 0:
                continue
            share = alpha * prev[node] / degree
            for neighbor in graph.successors(node):
                ranks[neighbor] += share
        err = sum(abs(ranks[node] - prev[node]) for node in nodes)
        if err < n * tol:
            break
    return ranks


def _louvain_partition(graph: nx.Graph) -> dict:
    """Return a {node: community_id} partition using Louvain or Leiden as fallback."""
    if graph.number_of_nodes() == 0:
        return {}

    # Preferred: python-louvain
    if community_louvain is not None:
        return community_louvain.best_partition(graph)

    # Fallback: leidenalg (Leiden algorithm — comparable quality to Louvain)
    if _LEIDEN_AVAILABLE:
        nodes = list(graph.nodes())
        node_index = {n: i for i, n in enumerate(nodes)}
        edges = [(node_index[u], node_index[v]) for u, v in graph.edges() if u in node_index and v in node_index]
        ig_graph = ig.Graph(n=len(nodes), edges=edges, directed=False)
        partition = leidenalg.find_partition(ig_graph, leidenalg.ModularityVertexPartition)
        return {nodes[i]: cid for cid, members in enumerate(partition) for i in members}

    # Last resort: assign every node to community 0
    return {n: 0 for n in graph.nodes()}


def _iter_cached_works(cache_dir: Path):
    if not cache_dir.exists():
        return
    for path in sorted(cache_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("id"):
            yield payload
            continue
        if isinstance(payload, dict):
            for work in payload.get("results", []):
                if isinstance(work, dict) and work.get("id"):
                    yield work


def _cached_reference_edges(
    papers: pd.DataFrame,
    oa_to_canonical: dict,
    cache_dir: Path,
) -> list[dict]:
    refs_by_openalex_id = {}
    for work in _iter_cached_works(cache_dir):
        refs_by_openalex_id[str(work.get("id", ""))] = [
            str(ref) for ref in (work.get("referenced_works") or []) if str(ref).strip()
        ]

    edges = {}
    for _, row in papers.iterrows():
        source_id = str(row["canonical_paper_id"])
        candidate_openalex_ids = []
        for value in [row.get("openalex_id", ""), row.get("all_openalex_ids", "")]:
            for part in str(value or "").split(";"):
                part = part.strip()
                if part:
                    candidate_openalex_ids.append(part)
        for work_id in sorted(set(candidate_openalex_ids)):
            for ref_id in refs_by_openalex_id.get(work_id, []):
                target_id = oa_to_canonical.get(ref_id)
                if target_id and target_id != source_id:
                    key = (source_id, target_id)
                    edges[key] = {
                        "source_paper_id": source_id,
                        "target_paper_id": target_id,
                        "edge_type": "CITES",
                        "edge_source": "cached_reference",
                    }
    return list(edges.values())


def _seed_lineage_metrics(
    graph: nx.DiGraph,
    seed_ids: set[str],
    max_depth: int = 4,
    decay: float = 0.7,
) -> pd.DataFrame:
    if graph.number_of_nodes() == 0:
        return pd.DataFrame(columns=["canonical_paper_id", "min_seed_distance", "seed_reachability_count", "lineage_score_raw"])

    reverse_graph = graph.reverse(copy=False)
    min_seed_distance = {node: None for node in graph.nodes()}
    seed_reachability_count = Counter()
    lineage_score_raw = Counter()

    for seed_id in sorted(seed_ids):
        if seed_id not in reverse_graph:
            continue
        distances = nx.single_source_shortest_path_length(reverse_graph, seed_id, cutoff=max_depth)
        for node, distance in distances.items():
            seed_reachability_count[node] += 1
            lineage_score_raw[node] += decay ** distance
            current = min_seed_distance[node]
            if current is None or distance < current:
                min_seed_distance[node] = distance

    rows = []
    for node in graph.nodes():
        rows.append(
            {
                "canonical_paper_id": node,
                "min_seed_distance": -1 if min_seed_distance[node] is None else int(min_seed_distance[node]),
                "seed_reachability_count": int(seed_reachability_count.get(node, 0)),
                "lineage_score_raw": float(lineage_score_raw.get(node, 0.0)),
            }
        )
    return pd.DataFrame(rows)


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    norm = root / cfg["output_dir"] / "normalized"
    raw = root / cfg["output_dir"] / "raw"
    outdir = root / cfg["output_dir"] / "graph"
    ensure_dir(outdir)

    papers = pd.read_csv(norm / "canonical_papers.csv")
    version_map = pd.read_csv(norm / "paper_version_map.csv")
    seed_edges_path = raw / "seed_citation_edges.csv"
    if seed_edges_path.exists():
        seed_edges = pd.read_csv(seed_edges_path)
    else:
        seed_edges = pd.DataFrame(columns=["source_openalex_id", "target_openalex_id", "edge_type"])

    oa_to_canonical = {}
    for _, row in version_map.iterrows():
        if pd.notna(row.get("openalex_id")) and str(row["openalex_id"]).strip():
            oa_to_canonical[str(row["openalex_id"])] = row["canonical_paper_id"]

    seed_edge_rows = []
    for _, row in seed_edges.iterrows():
        s = oa_to_canonical.get(str(row["source_openalex_id"]))
        t = oa_to_canonical.get(str(row["target_openalex_id"]))
        if s and t and s != t:
            seed_edge_rows.append(
                {
                    "source_paper_id": s,
                    "target_paper_id": t,
                    "edge_type": "CITES",
                    "edge_source": "seed_expansion",
                }
            )

    cached_edge_rows = _cached_reference_edges(papers, oa_to_canonical, raw / "openalex_cache")
    citation_edges_df = pd.DataFrame(seed_edge_rows + cached_edge_rows).drop_duplicates(
        subset=["source_paper_id", "target_paper_id"]
    )
    citation_edges_df.to_csv(outdir / "corpus_citation_edges.csv", index=False)
    cit_edges = list(
        citation_edges_df[["source_paper_id", "target_paper_id"]].itertuples(index=False, name=None)
    )

    G = nx.DiGraph()
    for _, row in papers.iterrows():
        G.add_node(row["canonical_paper_id"], title=row["title"], year=row.get("year"), doi=row.get("doi"), cited_by=row.get("merged_cited_by_count", row.get("cited_by_count", 0)))
    G.add_edges_from(cit_edges)

    pagerank = _pagerank(G)
    betweenness = nx.betweenness_centrality(G) if G.number_of_nodes() <= 5000 else nx.betweenness_centrality(G, k=min(500, G.number_of_nodes()))
    degree = dict(G.degree())
    in_degree = dict(G.in_degree())
    out_degree = dict(G.out_degree())
    UG = G.to_undirected()
    core_number = nx.core_number(UG) if UG.number_of_nodes() else {}
    partition = _louvain_partition(UG)
    seed_ids = set(
        papers.loc[papers["all_channels"].fillna("").str.contains("seed_resolution"), "canonical_paper_id"].astype(str)
    )
    lineage = _seed_lineage_metrics(G, seed_ids)
    lineage_map = lineage.set_index("canonical_paper_id").to_dict("index") if not lineage.empty else {}

    metrics = []
    for n in G.nodes():
        lineage_row = lineage_map.get(n, {})
        metrics.append({
            "canonical_paper_id": n,
            "degree": degree.get(n, 0),
            "in_degree": in_degree.get(n, 0),
            "out_degree": out_degree.get(n, 0),
            "pagerank": pagerank.get(n, 0.0),
            "betweenness": betweenness.get(n, 0.0),
            "kcore": core_number.get(n, 0),
            "community_id": partition.get(n, 0),
            "min_seed_distance": lineage_row.get("min_seed_distance", -1),
            "seed_reachability_count": lineage_row.get("seed_reachability_count", 0),
            "lineage_score_raw": lineage_row.get("lineage_score_raw", 0.0),
        })
    metrics_df = pd.DataFrame(metrics)
    metrics_df.to_csv(outdir / "paper_graph_metrics.csv", index=False)

    incoming = defaultdict(set)
    outgoing = defaultdict(set)
    for s, t in cit_edges:
        outgoing[s].add(t)
        incoming[t].add(s)

    # Skip hub papers with too many in-corpus citers: O(n²) pairs would exhaust memory.
    # Papers cited by >200 corpus works are bibliometric hubs whose co-citation pairs
    # are too numerous and too non-specific to be informative for similarity scoring.
    MAX_CITERS_PER_HUB = 200
    cocit = Counter()
    for cited_paper, citers in incoming.items():
        if len(citers) > MAX_CITERS_PER_HUB:
            continue
        citers = sorted(citers)
        for i in range(len(citers)):
            for j in range(i + 1, len(citers)):
                cocit[(citers[i], citers[j])] += 1

    cocit_rows = [{"source_paper_id": a, "target_paper_id": b, "weight": w, "edge_type": "CO_CITED"} for (a, b), w in cocit.items() if w >= cfg["graphs"]["min_cocitation_weight"]]
    pd.DataFrame(cocit_rows).to_csv(outdir / "co_citation_edges.csv", index=False)

    # Compute bibliographic coupling by inverting references:
    # for each referenced paper, connect all corpus papers that cite it.
    # This avoids O(n^2) pairwise paper intersections on large corpora.
    ref_to_papers = defaultdict(set)
    for source_paper_id, ref_ids in outgoing.items():
        for ref_id in ref_ids:
            ref_to_papers[ref_id].add(source_paper_id)

    # Same hub cap as co-citation: skip reference hubs with too many citing corpus papers.
    bib = Counter()
    for citing_papers in ref_to_papers.values():
        if len(citing_papers) > MAX_CITERS_PER_HUB:
            continue
        citing_list = sorted(citing_papers)
        for i in range(len(citing_list)):
            for j in range(i + 1, len(citing_list)):
                bib[(citing_list[i], citing_list[j])] += 1
    min_bib = cfg["graphs"]["min_bibcoupling_weight"]
    bib_rows = [
        {"source_paper_id": a, "target_paper_id": b, "weight": w, "edge_type": "BIBLIOGRAPHIC_COUPLING"}
        for (a, b), w in bib.items()
        if w >= min_bib
    ]
    pd.DataFrame(bib_rows).to_csv(outdir / "bibliographic_coupling_edges.csv", index=False)

    pa = pd.read_csv(norm / "paper_authors.csv")
    auth_groups = pa.groupby("canonical_paper_id")["canonical_author_id"].apply(list)
    coauth = Counter()
    for _, authors in auth_groups.items():
        authors = sorted(set(authors))
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                coauth[(authors[i], authors[j])] += 1
    coauth_rows = [{"source_author_id": a, "target_author_id": b, "weight": w, "edge_type": "CO_AUTHOR"} for (a, b), w in coauth.items() if w >= cfg["graphs"]["min_coauthorship_weight"]]
    pd.DataFrame(coauth_rows).to_csv(outdir / "coauthorship_edges.csv", index=False)

    # Write only the primary citation graph; co-citation and bib-coupling graphs are
    # not consumed by any downstream stage and are too large to serialise as XML.
    nx.write_graphml(G, outdir / "citation_graph.graphml")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
