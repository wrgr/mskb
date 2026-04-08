"""Discover and label research topic clusters from Louvain community assignments in the citation graph."""

import argparse
import re
from collections import Counter
from pathlib import Path

import networkx as nx
import pandas as pd

from .utils import ensure_dir, load_config


# Topic categories aligned with major MS organizations:
# ACTRIMS (Americas Committee for Treatment and Research in MS)
# CMSC (Consortium of MS Centers)
# MSJ (Multiple Sclerosis Journal)
#
# These categories reflect how the MS field organizes its research
# across conferences and journals, providing a familiar scaffold
# for researchers navigating the literature.
SPECTRUM_ANCHORS = {
    "pathogenesis_and_immunology": [
        "myelin", "axon", "neuron", "oligodendrocyte", "astrocyte", "microglia",
        "cell", "protein", "gene", "molecular", "receptor", "signaling",
        "pathway", "expression", "in vitro", "mouse", "rat", "eae",
        "autoimmune", "t cell", "b cell", "cytokine", "immunology",
        "demyelination", "remyelination", "neurodegeneration", "blood-brain barrier",
        "epstein-barr", "immune", "antigen", "tolerance",
    ],
    "imaging_and_biomarkers": [
        "mri", "lesion", "imaging", "neuroimaging", "magnetization",
        "gadolinium", "atrophy", "cortical lesion", "white matter",
        "neurofilament", "biomarker", "oligoclonal", "cerebrospinal fluid",
        "optical coherence tomography", "oct", "pet", "volumetric",
    ],
    "clinical_trials_and_therapeutics": [
        "clinical trial", "randomized", "placebo", "treatment", "therapy",
        "disease-modifying", "relapse rate", "disability progression",
        "ocrelizumab", "natalizumab", "interferon", "fingolimod",
        "efficacy", "safety", "adverse event", "phase 3", "phase 2",
    ],
    "clinical_care_and_management": [
        "patient", "clinical", "diagnosis", "relapsing", "progressive",
        "edss", "symptom", "rehabilitation", "fatigue", "cognition",
        "spasticity", "pain", "bladder", "mcdonald criteria",
        "clinically isolated", "phenotype", "prognosis",
    ],
    "epidemiology_and_population_health": [
        "prevalence", "incidence", "cohort", "population", "epidemiology",
        "risk factor", "genome-wide", "gwas", "registry", "health economics",
        "quality of life", "mortality", "disparity", "comorbidity",
        "pregnancy", "pediatric", "race", "ethnicity", "vitamin d",
        "smoking", "latitude",
    ],
}

JARGON_WORDS = {
    "phosphorylation", "transcriptome", "proteome", "cytokine", "chemokine",
    "interleukin", "immunoglobulin", "oligodendrocyte", "astrocyte",
    "demyelination", "remyelination", "neurodegeneration", "axonopathy",
    "cerebrospinal", "gadolinium", "magnetization", "neurofilament",
    "epitope", "autoantibody", "immunopathology", "neuropathology",
    "histopathology", "electrophysiology", "pharmacokinetics",
}


def _extract_concepts(papers: pd.DataFrame, community_papers: pd.DataFrame) -> list[str]:
    concept_counts = Counter()
    for _, row in community_papers.iterrows():
        concepts_str = str(row.get("concepts", "") or "")
        for concept in concepts_str.split(";"):
            concept = concept.strip()
            if concept:
                concept_counts[concept] += 1
        topics_str = str(row.get("topics", "") or "")
        for topic in topics_str.split(";"):
            topic = topic.strip()
            if topic:
                concept_counts[topic] += 1
    return [c for c, _ in concept_counts.most_common(10)]


def _auto_label(top_concepts: list[str]) -> str:
    if not top_concepts:
        return "Unlabeled cluster"
    return " / ".join(top_concepts[:3])


def _spectrum_score(texts: list[str]) -> dict[str, float]:
    combined = " ".join(texts).lower()
    scores = {}
    for category, anchors in SPECTRUM_ANCHORS.items():
        # Normalize by anchor-list length to avoid systematic bias toward
        # categories with more anchors.
        matched = sum(1 for a in anchors if a in combined)
        scores[category] = matched / max(1, len(anchors))
    total = sum(scores.values()) or 1
    return {k: v / total for k, v in scores.items()}


def _estimate_difficulty(texts: list[str]) -> int:
    combined = " ".join(texts).lower()
    words = set(re.findall(r"\b\w+\b", combined))
    jargon_count = len(words & JARGON_WORDS)
    if jargon_count >= 10:
        return 5
    if jargon_count >= 7:
        return 4
    if jargon_count >= 4:
        return 3
    if jargon_count >= 2:
        return 2
    return 1


def run(config_path: str) -> None:
    """Discover topic clusters from community assignments and write paper_topics.csv and topic_clusters.csv."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph_dir = root / cfg["output_dir"] / "graph"
    norm_dir = root / cfg["output_dir"] / "normalized"
    outdir = root / cfg["output_dir"] / "topics"
    ensure_dir(outdir)

    scored = pd.read_csv(graph_dir / "scored_papers.csv")
    min_cluster_size = cfg.get("topics", {}).get("min_cluster_size", 5)

    if "community_id" not in scored.columns:
        scored["community_id"] = 0

    community_counts = scored["community_id"].value_counts()
    valid_communities = set(community_counts[community_counts >= min_cluster_size].index)

    topic_rows = []
    cluster_rows = []

    for comm_id in sorted(valid_communities):
        comm_papers = scored[scored["community_id"] == comm_id]
        top_concepts = _extract_concepts(scored, comm_papers)
        label = _auto_label(top_concepts)

        texts = []
        for _, row in comm_papers.iterrows():
            t = str(row.get("title", "") or "")
            a = str(row.get("abstract", "") or "")
            texts.append(f"{t} {a}")

        spectrum = _spectrum_score(texts)
        difficulty = _estimate_difficulty(texts)

        cluster_row = {
            "topic_id": int(comm_id),
            "auto_label": label,
            "n_papers": int(len(comm_papers)),
            "difficulty": difficulty,
            "dominant_category": "",
            "top_concepts": ";".join(top_concepts),
        }
        for category in SPECTRUM_ANCHORS:
            cluster_row[f"spectrum_{category}"] = round(spectrum.get(category, 0.0), 3)
        cluster_rows.append(cluster_row)

        for _, row in comm_papers.iterrows():
            topic_rows.append({
                "canonical_paper_id": row["canonical_paper_id"],
                "topic_id": int(comm_id),
                "confidence": 1.0,
                "method": "louvain_community",
            })

    paper_topics_df = pd.DataFrame(topic_rows)
    topic_clusters_df = pd.DataFrame(cluster_rows)

    # Assign dominant category by over-indexing versus corpus-wide topic baseline.
    # This avoids systematic collapse into one category when one anchor set is broader.
    if not topic_clusters_df.empty:
        spectrum_cols = [f"spectrum_{cat}" for cat in SPECTRUM_ANCHORS]
        baselines = topic_clusters_df[spectrum_cols].mean().to_dict()

        def _dominant_from_adjusted(row: pd.Series) -> str:
            best_cat = None
            best_val = None
            for cat in SPECTRUM_ANCHORS:
                col = f"spectrum_{cat}"
                adjusted = float(row.get(col, 0.0)) - float(baselines.get(col, 0.0))
                if best_val is None or adjusted > best_val:
                    best_val = adjusted
                    best_cat = cat
            return best_cat or "pathogenesis_and_immunology"

        topic_clusters_df["dominant_category"] = topic_clusters_df.apply(_dominant_from_adjusted, axis=1)

    paper_topics_df.to_csv(outdir / "paper_topics.csv", index=False)
    topic_clusters_df.to_csv(outdir / "topic_clusters.csv", index=False)

    # Build topic co-occurrence graph
    topic_graph = nx.Graph()
    for _, row in topic_clusters_df.iterrows():
        topic_graph.add_node(
            int(row["topic_id"]),
            label=row["auto_label"],
            n_papers=int(row["n_papers"]),
            difficulty=int(row["difficulty"]),
            dominant_category=row["dominant_category"],
        )

    # Co-occurrence: two topics co-occur if they share citation edges
    if (graph_dir / "corpus_citation_edges.csv").exists():
        cit_edges = pd.read_csv(graph_dir / "corpus_citation_edges.csv")
        paper_to_topic = dict(zip(paper_topics_df["canonical_paper_id"], paper_topics_df["topic_id"]))
        cooccur = Counter()
        for _, edge in cit_edges.iterrows():
            t1 = paper_to_topic.get(edge["source_paper_id"])
            t2 = paper_to_topic.get(edge["target_paper_id"])
            if t1 is not None and t2 is not None and t1 != t2:
                key = tuple(sorted([int(t1), int(t2)]))
                cooccur[key] += 1
        for (a, b), w in cooccur.items():
            topic_graph.add_edge(a, b, weight=w)

    nx.write_graphml(topic_graph, outdir / "topic_graph.graphml")

    print(f"Discovered {len(cluster_rows)} topic clusters from {len(paper_topics_df)} paper assignments.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
