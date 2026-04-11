
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .utils import ensure_dir, load_config, load_downstream_corpus, sha256_file

DRUG_PATTERNS = {
    "Ocrelizumab": ["ocrelizumab", "ocrevus"],
    "Natalizumab": ["natalizumab", "tysabri"],
    "Interferon beta": ["interferon beta", "ifn-beta", "avonex", "rebif", "betaferon", "plegridy"],
    "Glatiramer acetate": ["glatiramer", "copaxone"],
    "Fingolimod": ["fingolimod", "gilenya"],
    "Dimethyl fumarate": ["dimethyl fumarate", "tecfidera"],
    "Teriflunomide": ["teriflunomide", "aubagio"],
    "Cladribine": ["cladribine", "mavenclad"],
    "Alemtuzumab": ["alemtuzumab", "lemtrada"],
    "Siponimod": ["siponimod", "mayzent"],
    "Ozanimod": ["ozanimod", "zeposia"],
    "Ponesimod": ["ponesimod", "ponvory"],
    "Ofatumumab": ["ofatumumab", "kesimpta"],
    "Rituximab": ["rituximab", "rituxan"],
    "Mitoxantrone": ["mitoxantrone", "novantrone"],
    "Ublituximab": ["ublituximab", "briumvi"],
    "Tolebrutinib": ["tolebrutinib"],
    "Fenebrutinib": ["fenebrutinib"],
}
GENE_PATTERNS = {
    "HLA-DRB1": ["hla-drb1", "hla drb1", "drb1*15:01"],
    "IL-7R": ["il-7r", "il7r", "interleukin-7 receptor"],
    "IL-2RA": ["il-2ra", "il2ra", "cd25"],
    "CD58": ["cd58"],
    "EVI5": ["evi5"],
    "CLEC16A": ["clec16a"],
    "TNFRSF1A": ["tnfrsf1a"],
    "IRF8": ["irf8"],
    "CD6": ["cd6 gene", "cd6 locus"],
}
PATHOLOGY_PATTERNS = {
    "Demyelination": ["demyelination", "demyelinating"],
    "Neurodegeneration": ["neurodegeneration", "neurodegenerative", "axonal loss", "axonal damage"],
    "Neuroinflammation": ["neuroinflammation", "neuroinflammatory"],
    "Remyelination": ["remyelination", "remyelinating"],
    "Blood-brain barrier disruption": ["blood-brain barrier", "bbb disruption", "bbb breakdown"],
    "Cortical lesion": ["cortical lesion", "cortical demyelination"],
    "White matter lesion": ["white matter lesion", "periventricular lesion"],
    "Grey matter atrophy": ["grey matter atrophy", "gray matter atrophy", "brain atrophy"],
}
BIOMARKER_PATTERNS = {
    "Neurofilament light": ["neurofilament light", "nfl", "nf-l"],
    "Oligoclonal bands": ["oligoclonal bands", "oligoclonal band", "ocb"],
    "GFAP": ["gfap", "glial fibrillary acidic protein"],
    "Chitinase-3-like protein 1": ["chi3l1", "ykl-40", "chitinase"],
    "Kappa free light chains": ["kappa free light chain"],
    "MRI T2 lesion load": ["t2 lesion load", "t2 lesion volume"],
    "Gadolinium-enhancing lesions": ["gadolinium-enhancing", "gd-enhancing", "contrast-enhancing lesion"],
}
ANIMAL_MODEL_PATTERNS = {
    "EAE": ["experimental autoimmune encephalomyelitis", "eae model", "eae mice"],
    "Cuprizone model": ["cuprizone"],
    "Lysolecithin model": ["lysolecithin", "lysophosphatidylcholine"],
    "Theiler's virus": ["theiler", "tmev"],
}


def _tag(text: str, patterns: dict) -> list:
    text = (text or "").lower()
    hits = []
    for label, pats in patterns.items():
        if any(p in text for p in pats):
            hits.append(label)
    return hits


def _artifact_info(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def _safe_int(value, default=0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def write_provenance_snapshot(root: Path, output_dir: str) -> None:
    outputs = root / output_dir
    raw = outputs / "raw"
    normalized = outputs / "normalized"
    graph = outputs / "graph"
    explorer = outputs / "explorer"
    provenance_dir = outputs / "provenance"
    ensure_dir(provenance_dir)

    key_files = [
        raw / "candidate_papers.csv",
        raw / "seed_citation_edges.csv",
        raw / "retrieval_stats.json",
        normalized / "canonical_papers.csv",
        normalized / "paper_version_map.csv",
        graph / "corpus_citation_edges.csv",
        graph / "paper_graph_metrics.csv",
        graph / "scored_papers.csv",
        graph / "author_metrics.csv",
        graph / "learner_journey_papers.csv",
        graph / "learner_journey_topics.csv",
        graph / "learner_journey.json",
        explorer / "explorer_papers.parquet",
        explorer / "explorer_authors.parquet",
    ]
    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": [_artifact_info(path) for path in key_files],
    }
    (provenance_dir / "retrieval_snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph = root / cfg["output_dir"] / "graph"
    norm = root / cfg["output_dir"] / "normalized"
    topics_dir = root / cfg["output_dir"] / "topics"
    outkg = root / cfg["output_dir"] / "kg"
    outex = root / cfg["output_dir"] / "explorer"
    ensure_dir(outkg)
    ensure_dir(outex)

    papers, _ = load_downstream_corpus(graph)
    author_metrics = pd.read_csv(graph / "author_metrics.csv") if (graph / "author_metrics.csv").exists() else pd.DataFrame()
    authors = pd.read_csv(norm / "canonical_authors.csv")
    paper_authors = pd.read_csv(norm / "paper_authors.csv")

    paper_topics = pd.DataFrame()
    topic_clusters = pd.DataFrame()
    if (topics_dir / "paper_topics.csv").exists():
        paper_topics = pd.read_csv(topics_dir / "paper_topics.csv")
    if (topics_dir / "topic_clusters.csv").exists():
        topic_clusters = pd.read_csv(topics_dir / "topic_clusters.csv")

    nodes = []
    edges = []
    selected_paper_ids = set(papers["canonical_paper_id"].astype(str))

    for _, row in papers.iterrows():
        pid = row["canonical_paper_id"]
        title = row.get("title", "")
        abstract = row.get("abstract", "")
        text = f"{title} {abstract}"
        drugs = _tag(text, DRUG_PATTERNS)
        genes = _tag(text, GENE_PATTERNS)
        pathology = _tag(text, PATHOLOGY_PATTERNS)
        biomarkers = _tag(text, BIOMARKER_PATTERNS)
        animal_models = _tag(text, ANIMAL_MODEL_PATTERNS)

        nodes.append({"node_id": pid, "label": "Paper", "name": title, "year": row.get("year"), "doi": row.get("doi"), "tier": row.get("tier"), "score_total": row.get("score_total", 0.0)})

        for d in drugs:
            did = f"drug::{d}"
            nodes.append({"node_id": did, "label": "Drug", "name": d})
            edges.append({"source_id": pid, "target_id": did, "edge_type": "MENTIONS_DRUG"})
        for g in genes:
            gid = f"gene::{g}"
            nodes.append({"node_id": gid, "label": "Gene", "name": g})
            edges.append({"source_id": pid, "target_id": gid, "edge_type": "MENTIONS_GENE"})
        for p in pathology:
            pathid = f"pathology::{p}"
            nodes.append({"node_id": pathid, "label": "Pathology", "name": p})
            edges.append({"source_id": pid, "target_id": pathid, "edge_type": "STUDIES_PATHOLOGY"})
        for b in biomarkers:
            bid = f"biomarker::{b}"
            nodes.append({"node_id": bid, "label": "Biomarker", "name": b})
            edges.append({"source_id": pid, "target_id": bid, "edge_type": "USES_BIOMARKER"})
        for m in animal_models:
            mid = f"model::{m}"
            nodes.append({"node_id": mid, "label": "AnimalModel", "name": m})
            edges.append({"source_id": pid, "target_id": mid, "edge_type": "USES_MODEL"})

    for _, row in authors.iterrows():
        aid = row["canonical_author_id"]
        nodes.append({"node_id": aid, "label": "Author", "name": row.get("display_name", "")})
    for _, row in paper_authors.iterrows():
        source_pid = str(row["canonical_paper_id"])
        if source_pid in selected_paper_ids:
            edges.append({"source_id": source_pid, "target_id": row["canonical_author_id"], "edge_type": "AUTHORED_BY"})

    if not topic_clusters.empty:
        for _, row in topic_clusters.iterrows():
            tid = f"topic::{row['topic_id']}"
            nodes.append({"node_id": tid, "label": "Topic", "name": row.get("auto_label", "")})
    if not paper_topics.empty:
        for _, row in paper_topics.iterrows():
            source_pid = str(row["canonical_paper_id"])
            if source_pid not in selected_paper_ids:
                continue
            tid = f"topic::{row['topic_id']}"
            edges.append({"source_id": source_pid, "target_id": tid, "edge_type": "BELONGS_TO_TOPIC"})

    learner_membership_path = graph / "learner_topic_membership.csv"
    if learner_membership_path.exists():
        learner_membership = pd.read_csv(learner_membership_path)
        for _, row in learner_membership.iterrows():
            pid = str(row.get("paper_id", ""))
            tid = str(row.get("topic_id", ""))
            if not pid or not tid or pid not in selected_paper_ids:
                continue
            tlabel = str(row.get("topic_label", "") or tid)
            nodes.append({"node_id": tid, "label": "Topic", "name": tlabel})
            edges.append({"source_id": pid, "target_id": tid, "edge_type": "BELONGS_TO_TOPIC"})

    # Include explicit paper citation edges in the KG for graph traversal.
    cites_path = graph / "corpus_citation_edges.csv"
    if cites_path.exists():
        cite_edges = pd.read_csv(cites_path, usecols=["source_paper_id", "target_paper_id"])
        for _, row in cite_edges.iterrows():
            src = str(row["source_paper_id"])
            dst = str(row["target_paper_id"])
            if src in selected_paper_ids and dst in selected_paper_ids and src != dst:
                edges.append({"source_id": src, "target_id": dst, "edge_type": "CITES"})

    learner_papers_path = graph / "learner_journey_papers.csv"
    if learner_papers_path.exists():
        learner_papers = pd.read_csv(learner_papers_path)
        for _, row in learner_papers.iterrows():
            src = str(row.get("from_paper_id", ""))
            dst = str(row.get("to_paper_id", ""))
            if not src or not dst or src not in selected_paper_ids or dst not in selected_paper_ids or src == dst:
                continue
            edges.append(
                {
                    "source_id": src,
                    "target_id": dst,
                    "edge_type": "NEXT_PAPER_TO_LEARN",
                    "journey_type": str(row.get("journey_type", "")),
                    "journey_rank": _safe_int(row.get("rank", 0)),
                    "journey_score": _safe_float(row.get("journey_score", 0.0)),
                }
            )

    learner_topics_path = graph / "learner_journey_topics.csv"
    if learner_topics_path.exists():
        learner_topics = pd.read_csv(learner_topics_path)
        for _, row in learner_topics.iterrows():
            src = str(row.get("from_topic_id", ""))
            dst = str(row.get("to_topic_id", ""))
            if not src or not dst or src == dst:
                continue
            src_label = str(row.get("from_topic_label", "") or src)
            dst_label = str(row.get("to_topic_label", "") or dst)
            nodes.append({"node_id": src, "label": "Topic", "name": src_label})
            nodes.append({"node_id": dst, "label": "Topic", "name": dst_label})
            edges.append(
                {
                    "source_id": src,
                    "target_id": dst,
                    "edge_type": "NEXT_TOPIC_TO_LEARN",
                    "journey_rank": _safe_int(row.get("rank", 0)),
                    "journey_score": _safe_float(row.get("transition_score", 0.0)),
                    "evidence_edges": _safe_int(row.get("evidence_edges", 0)),
                }
            )

    nodes_df = pd.DataFrame(nodes).drop_duplicates(subset=["node_id", "label"])
    edges_df = pd.DataFrame(edges).drop_duplicates()

    nodes_df.to_csv(outkg / "kg_nodes.csv", index=False)
    edges_df.to_csv(outkg / "kg_edges.csv", index=False)
    nodes_df.to_parquet(outex / "explorer_nodes_heterogeneous.parquet", index=False)
    edges_df.to_parquet(outex / "explorer_edges_heterogeneous.parquet", index=False)

    paper_view = papers[
        [
            "canonical_paper_id",
            "title",
            "year",
            "doi",
            "venue",
            "merged_cited_by_count",
            "score_total",
            "score_field_membership",
            "score_impact",
            "score_lineage",
            "paper_importance_score",
            "score_global_citations",
            "score_corpus_citations",
            "score_pagerank",
            "score_kcore",
            "score_cocitation",
            "score_bibcoupling",
            "cocitation_seed_affinity_raw",
            "bibcoupling_seed_affinity_raw",
            "tier",
            "kcore",
            "community_id",
            "in_degree",
            "out_degree",
            "pagerank",
            "min_seed_distance",
            "seed_reachability_count",
            "lineage_score_raw",
            "n_independent_signals",
        ]
    ].copy()
    paper_view = paper_view.rename(columns={"canonical_paper_id": "paper_id", "merged_cited_by_count": "citation_count"})
    paper_view.to_parquet(outex / "explorer_papers.parquet", index=False)
    if not author_metrics.empty:
        author_metrics.to_parquet(outex / "explorer_authors.parquet", index=False)

    write_provenance_snapshot(root, cfg["output_dir"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
