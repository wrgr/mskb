import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .utils import load_config


POSITIVE_TERMS = [
    "multiple sclerosis", "demyelinat", "remyelinat", "oligodendrocyte",
    "experimental autoimmune encephalomyelitis", "eae model",
    "myelin", "neuroinflammation", "blood-brain barrier",
    "neurofilament", "disease-modifying therapy",
    "relapsing-remitting", "progressive ms", "primary progressive",
    "secondary progressive", "clinically isolated syndrome",
    "ocrelizumab", "natalizumab", "interferon beta", "glatiramer",
    "fingolimod", "dimethyl fumarate", "teriflunomide",
    "optic neuritis", "mcdonald criteria", "oligoclonal band",
    "central nervous system autoimmun", "ms lesion",
    "cuprizone", "myelin basic protein", "myelin oligodendrocyte glycoprotein",
    "epstein-barr virus ms", "hla-drb1",
]
NEGATIVE_TERMS = [
    "amyotrophic lateral sclerosis", "parkinson", "alzheimer",
    "mass spectrometry",
    "multiple system atrophy",
]


def _lexical_score(title: str, abstract: str) -> float:
    text = f"{title or ''} {abstract or ''}".lower()
    pos = sum(1 for t in POSITIVE_TERMS if t in text)
    neg = sum(1 for t in NEGATIVE_TERMS if t in text)
    return max(0.0, float(pos - 2 * neg))


def _normalize_log1p(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=0.0)
    scaled = np.log1p(values)
    max_value = float(scaled.max()) if len(scaled) else 0.0
    if max_value <= 0.0:
        return pd.Series(0.0, index=series.index, dtype=float)
    return scaled / max_value


def _normalize_rank(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if len(values) == 0 or float(values.max()) <= 0.0:
        return pd.Series(0.0, index=series.index, dtype=float)
    return values.rank(method="average", pct=True).fillna(0.0).astype(float)


def _normalize_max(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=0.0)
    max_value = float(values.max()) if len(values) else 0.0
    if max_value <= 0.0:
        return pd.Series(0.0, index=series.index, dtype=float)
    return values / max_value


def _seed_affinity(edges: pd.DataFrame, seed_ids: set[str]) -> pd.Series:
    if edges.empty or not seed_ids:
        return pd.Series(dtype=float)
    source_hits = (
        edges[edges["source_paper_id"].astype(str).isin(seed_ids)][["target_paper_id", "weight"]]
        .rename(columns={"target_paper_id": "canonical_paper_id"})
    )
    target_hits = (
        edges[edges["target_paper_id"].astype(str).isin(seed_ids)][["source_paper_id", "weight"]]
        .rename(columns={"source_paper_id": "canonical_paper_id"})
    )
    if source_hits.empty and target_hits.empty:
        return pd.Series(dtype=float)
    hits = pd.concat([source_hits, target_hits], ignore_index=True)
    hits["canonical_paper_id"] = hits["canonical_paper_id"].astype(str)
    return hits.groupby("canonical_paper_id")["weight"].sum()


def _top_k_sum(series: pd.Series, k: int = 3) -> float:
    return float(series.nlargest(k).sum())


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    norm = root / cfg["output_dir"] / "normalized"
    graph = root / cfg["output_dir"] / "graph"

    papers = pd.read_csv(norm / "canonical_papers.csv")
    metrics = pd.read_csv(graph / "paper_graph_metrics.csv") if (graph / "paper_graph_metrics.csv").exists() else pd.DataFrame()
    paper_authors = pd.read_csv(norm / "paper_authors.csv") if (norm / "paper_authors.csv").exists() else pd.DataFrame()
    canonical_authors = pd.read_csv(norm / "canonical_authors.csv") if (norm / "canonical_authors.csv").exists() else pd.DataFrame()
    cocitation_edges = pd.read_csv(graph / "co_citation_edges.csv") if (graph / "co_citation_edges.csv").exists() else pd.DataFrame()
    bibcoupling_edges = pd.read_csv(graph / "bibliographic_coupling_edges.csv") if (graph / "bibliographic_coupling_edges.csv").exists() else pd.DataFrame()

    papers = papers.merge(metrics, on="canonical_paper_id", how="left")
    papers["canonical_paper_id"] = papers["canonical_paper_id"].astype(str)

    seed_paper_ids = set(
        papers.loc[papers["all_channels"].fillna("").str.contains("seed_resolution"), "canonical_paper_id"].astype(str)
    )
    cocitation_affinity = _seed_affinity(cocitation_edges, seed_paper_ids)
    bibcoupling_affinity = _seed_affinity(bibcoupling_edges, seed_paper_ids)

    seed_author_ids = set()
    if not paper_authors.empty:
        seed_author_ids = set(
            paper_authors.loc[
                paper_authors["canonical_paper_id"].astype(str).isin(seed_paper_ids), "canonical_author_id"
            ].astype(str)
        )

    papers["signal_seed"] = papers["all_channels"].fillna("").str.contains("seed_").astype(int)
    papers["signal_lexical"] = papers["all_channels"].fillna("").str.contains("lexical").astype(int)
    papers["signal_dataset"] = papers["all_channels"].fillna("").str.contains("dataset").astype(int)

    papers["lexical_score_raw"] = papers.apply(
        lambda r: _lexical_score(str(r.get("title", "")), str(r.get("abstract", ""))), axis=1
    )
    papers["cocitation_seed_affinity_raw"] = papers["canonical_paper_id"].map(cocitation_affinity).fillna(0.0)
    papers["bibcoupling_seed_affinity_raw"] = papers["canonical_paper_id"].map(bibcoupling_affinity).fillna(0.0)

    if not paper_authors.empty and seed_author_ids:
        core_author_overlap = (
            paper_authors.assign(
                core_author_overlap=paper_authors["canonical_author_id"].astype(str).isin(seed_author_ids).astype(int)
            )
            .groupby("canonical_paper_id")["core_author_overlap"]
            .max()
        )
        papers["score_core_author_overlap"] = papers["canonical_paper_id"].map(core_author_overlap).fillna(0.0)
    else:
        papers["score_core_author_overlap"] = 0.0

    papers["score_lexical_relevance"] = _normalize_log1p(papers["lexical_score_raw"])
    papers["score_direct_seed_citation"] = papers["signal_seed"].astype(float)
    papers["score_dataset_method_alignment"] = papers["signal_dataset"].astype(float)
    papers["score_cocitation"] = _normalize_log1p(papers["cocitation_seed_affinity_raw"])
    papers["score_bibcoupling"] = _normalize_log1p(papers["bibcoupling_seed_affinity_raw"])
    papers["score_pagerank"] = _normalize_rank(papers["pagerank"])
    papers["score_kcore"] = _normalize_max(papers["kcore"])
    papers["score_global_citations"] = _normalize_log1p(papers["merged_cited_by_count"])
    papers["score_corpus_citations"] = _normalize_log1p(papers["in_degree"])
    papers["score_lineage"] = (
        0.7 * _normalize_log1p(papers["lineage_score_raw"]) +
        0.3 * _normalize_log1p(papers["seed_reachability_count"])
    )

    w = cfg["scoring"]["weights"]
    papers["score_field_membership"] = (
        w["direct_seed_citation"] * papers["score_direct_seed_citation"] +
        w["lexical_relevance"] * papers["score_lexical_relevance"] +
        w["dataset_method_alignment"] * papers["score_dataset_method_alignment"] +
        w["cocitation"] * papers["score_cocitation"] +
        w["bibcoupling"] * papers["score_bibcoupling"] +
        w["core_author_overlap"] * papers["score_core_author_overlap"]
    )
    papers["score_impact"] = (
        2.0 * papers["score_corpus_citations"] +
        2.0 * papers["score_pagerank"] +
        1.5 * papers["score_global_citations"] +
        1.0 * papers["score_kcore"]
    )
    papers["paper_importance_score"] = papers["score_impact"]
    papers["score_total"] = papers["score_field_membership"]

    papers["n_independent_signals"] = papers[["signal_seed", "signal_lexical", "signal_dataset"]].sum(axis=1)
    papers["in_final_corpus"] = (
        (papers["n_independent_signals"] >= cfg["scoring"]["include_if_min_signals"]) &
        (papers["score_field_membership"] >= cfg["scoring"]["include_if_score_at_least"])
    )

    papers["tier"] = "excluded"
    papers.loc[papers["signal_seed"] == 1, "tier"] = "seed_neighbor"
    papers.loc[papers["in_final_corpus"], "tier"] = "included"
    papers.loc[papers["version_count"].fillna(1).astype(int) > 1, "merge_flag"] = "merged_versions"
    papers["merge_flag"] = papers["merge_flag"].fillna("single_version")
    papers.to_csv(graph / "scored_papers.csv", index=False)

    if paper_authors.empty:
        canonical_authors.to_csv(graph / "author_metrics.csv", index=False)
        return

    author_papers = paper_authors.merge(
        papers[
            [
                "canonical_paper_id",
                "tier",
                "score_total",
                "score_field_membership",
                "score_impact",
                "score_lineage",
                "paper_importance_score",
                "merged_cited_by_count",
                "in_degree",
                "out_degree",
                "pagerank",
                "community_id",
            ]
        ],
        on="canonical_paper_id",
        how="left",
    )

    author_metrics = (
        author_papers.groupby("canonical_author_id", as_index=False)
        .agg(
            n_papers=("canonical_paper_id", "nunique"),
            n_included_papers=("tier", lambda s: int((s == "included").sum())),
            total_score=("score_total", "sum"),
            total_field_membership_score=("score_field_membership", "sum"),
            total_impact_score=("score_impact", "sum"),
            total_lineage_score=("score_lineage", "sum"),
            mean_score=("score_total", "mean"),
            total_citations=("merged_cited_by_count", "sum"),
            mean_citations=("merged_cited_by_count", "mean"),
            corpus_citations_received=("in_degree", "sum"),
            corpus_references_made=("out_degree", "sum"),
            total_pagerank=("pagerank", "sum"),
            max_paper_importance_score=("paper_importance_score", "max"),
            dominant_community_id=("community_id", lambda s: s.mode().iloc[0] if not s.mode().empty else -1),
        )
    )

    top3_field = (
        author_papers.groupby("canonical_author_id")["score_field_membership"]
        .apply(_top_k_sum)
        .rename("top3_field_membership_score")
        .reset_index()
    )
    top3_impact = (
        author_papers.groupby("canonical_author_id")["paper_importance_score"]
        .apply(_top_k_sum)
        .rename("top3_paper_importance_score")
        .reset_index()
    )
    top3_lineage = (
        author_papers.groupby("canonical_author_id")["score_lineage"]
        .apply(_top_k_sum)
        .rename("top3_lineage_score")
        .reset_index()
    )
    author_metrics = author_metrics.merge(top3_field, on="canonical_author_id", how="left")
    author_metrics = author_metrics.merge(top3_impact, on="canonical_author_id", how="left")
    author_metrics = author_metrics.merge(top3_lineage, on="canonical_author_id", how="left")

    author_metrics["author_field_membership_score"] = (
        2.0 * _normalize_log1p(author_metrics["top3_field_membership_score"]) +
        1.5 * _normalize_log1p(author_metrics["n_included_papers"]) +
        0.5 * _normalize_log1p(author_metrics["n_papers"])
    )
    author_metrics["author_lineage_score"] = (
        2.0 * _normalize_log1p(author_metrics["top3_lineage_score"]) +
        1.0 * _normalize_log1p(author_metrics["n_included_papers"]) +
        0.5 * _normalize_log1p(author_metrics["n_papers"])
    )
    author_metrics["author_importance_score"] = (
        2.0 * _normalize_log1p(author_metrics["top3_paper_importance_score"]) +
        1.5 * _normalize_log1p(author_metrics["corpus_citations_received"]) +
        1.0 * _normalize_log1p(author_metrics["total_citations"]) +
        0.5 * _normalize_log1p(author_metrics["n_included_papers"]) +
        0.5 * _normalize_rank(author_metrics["total_pagerank"])
    )

    author_metrics = author_metrics.merge(canonical_authors, on="canonical_author_id", how="left")
    author_metrics["display_name"] = (
        author_metrics["display_name"].fillna(author_metrics["norm_name"]).fillna(author_metrics["canonical_author_id"])
    )
    author_metrics = author_metrics.sort_values(
        ["author_importance_score", "author_field_membership_score", "total_citations", "n_papers"],
        ascending=[False, False, False, False],
    )
    author_metrics.to_csv(graph / "author_metrics.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
