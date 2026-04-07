import argparse
from datetime import datetime, timezone
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

MS_FOCUS_TERMS = [
    "multiple sclerosis",
    "relapsing-remitting",
    "progressive ms",
    "primary progressive",
    "secondary progressive",
    "clinically isolated syndrome",
    "mcdonald criteria",
    "ocrelizumab",
    "natalizumab",
    "fingolimod",
    "dimethyl fumarate",
    "teriflunomide",
    "interferon beta",
    "glatiramer",
    "oligoclonal band",
    "neurofilament light",
    "ms lesion",
]

MS_CONCEPT_TERMS = [
    "multiple sclerosis",
    "multiple sclerosis research studies",
    "experimental autoimmune encephalomyelitis",
    "disease-modifying therapy",
    "neurofilament light",
    "oligoclonal band",
    "mcdonald criteria",
]

BIOLOGY_GENERIC_TERMS = [
    "cell biology",
    "molecular biology",
    "transcriptome",
    "proteome",
    "phosphorylation",
    "metabolism",
    "mouse model",
    "murine",
    "rat model",
    "in vitro",
]

CATEGORY_ANCHORS = {
    "pathogenesis_and_immunology": [
        "immunology", "immune", "t cell", "b cell", "microglia", "astrocyte",
        "oligodendrocyte", "demyelination", "remyelination", "ebv", "epstein-barr",
    ],
    "imaging_and_biomarkers": [
        "mri", "magnetic resonance", "oct", "optical coherence", "neurofilament",
        "biomarker", "gfap", "oligoclonal", "lesion load",
    ],
    "clinical_trials_and_therapeutics": [
        "clinical trial", "phase ii", "phase iii", "randomized", "placebo",
        "disease-modifying therapy", "ocrelizumab", "natalizumab", "fingolimod",
    ],
    "clinical_care_and_management": [
        "mcdonald criteria", "diagnosis", "disease course", "guideline",
        "rehabilitation", "cognitive", "symptom management",
    ],
    "epidemiology_and_population_health": [
        "epidemiology", "prevalence", "incidence", "population", "cohort",
        "registry", "gwas", "risk factor", "disparities", "pediatric",
    ],
}

EVIDENCE_PATTERNS = [
    ("guideline", ["guideline", "consensus", "recommendation", "position statement", "practice advisory"]),
    ("clinical_trial", ["randomized", "placebo", "phase ii", "phase iii", "clinical trial"]),
    ("systematic_review_meta_analysis", ["systematic review", "meta-analysis", "meta analysis", "pooled analysis"]),
    ("observational", ["cohort", "registry", "case-control", "cross-sectional", "population-based"]),
    ("review", ["review", "narrative review"]),
    ("preclinical", ["mouse", "murine", "in vitro", "animal model", "eae", "cuprizone", "lysolecithin"]),
]

EVIDENCE_STRENGTH_MAP = {
    "guideline": 5,
    "clinical_trial": 4,
    "systematic_review_meta_analysis": 4,
    "observational": 3,
    "review": 3,
    "preclinical": 2,
    "other": 2,
}


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


def _rank_within_group(series: pd.Series, groups: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    out = pd.Series(0.0, index=values.index, dtype=float)
    for _, idx in groups.groupby(groups).groups.items():
        subset = values.loc[idx]
        out.loc[idx] = subset.rank(method="average", pct=True).fillna(0.0).astype(float)
    return out


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


def _normalize_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().lower()


def _normalize_doi(value: object) -> str:
    doi = _normalize_text(value)
    if not doi:
        return ""
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    return doi.strip()


def _count_term_hits(text: str, terms: list[str]) -> int:
    t = _normalize_text(text)
    if not t:
        return 0
    return int(sum(1 for term in terms if term in t))


def _anchor_category_from_text(text: str) -> str:
    t = _normalize_text(text)
    best_cat = "unmapped"
    best_score = 0
    for cat, anchors in CATEGORY_ANCHORS.items():
        score = _count_term_hits(t, anchors)
        if score > best_score:
            best_cat = cat
            best_score = score
    return best_cat


def _safe_float(value: object, default: float) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _evidence_type_from_text(title: str, abstract: str) -> str:
    text = f"{_normalize_text(title)} {_normalize_text(abstract)}"
    for evidence_type, patterns in EVIDENCE_PATTERNS:
        if any(p in text for p in patterns):
            return evidence_type
    return "other"


def _rebalance_by_category(
    papers: pd.DataFrame,
    selected_mask: pd.Series,
    eligible_mask: pd.Series,
    score_col: str,
    category_col: str,
    target_ranges: dict,
) -> pd.Series:
    if selected_mask.sum() == 0 or not isinstance(target_ranges, dict) or not target_ranges:
        return selected_mask

    selected = set(papers.index[selected_mask])
    if not selected:
        return selected_mask

    # 1) Enforce upper bounds by trimming lowest-score papers in overrepresented categories.
    total = len(selected)
    for cat, bounds in target_ranges.items():
        if not isinstance(bounds, dict):
            continue
        max_pct = _safe_float(bounds.get("max_pct"), 1.0)
        max_pct = min(max(max_pct, 0.0), 1.0)
        max_allowed = int(np.floor(max_pct * total))
        cat_selected = [idx for idx in selected if papers.at[idx, category_col] == cat]
        if len(cat_selected) <= max_allowed:
            continue
        remove_n = len(cat_selected) - max_allowed
        cat_selected_sorted = sorted(cat_selected, key=lambda idx: papers.at[idx, score_col])
        for idx in cat_selected_sorted[:remove_n]:
            selected.discard(idx)

    # 2) Enforce lower bounds by promoting highest-score eligible papers.
    total = len(selected)
    for cat, bounds in target_ranges.items():
        if not isinstance(bounds, dict):
            continue
        min_pct = _safe_float(bounds.get("min_pct"), 0.0)
        min_pct = min(max(min_pct, 0.0), 1.0)
        min_required = int(np.ceil(min_pct * total))
        current = sum(1 for idx in selected if papers.at[idx, category_col] == cat)
        need = max(0, min_required - current)
        if need <= 0:
            continue

        candidates = papers[
            eligible_mask
            & (~papers.index.isin(selected))
            & (papers[category_col] == cat)
        ].copy()
        if candidates.empty:
            continue
        candidates = candidates.sort_values(score_col, ascending=False).head(need)
        selected.update(candidates.index.tolist())

    out = pd.Series(False, index=papers.index)
    if selected:
        out.loc[list(selected)] = True
    return out


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

    anchor_dois = set()
    anchor_paths = [
        root / "seeds" / "landmark_anchor_seeds.csv",
        root / cfg["output_dir"] / "audit" / "landmark_anchor_candidates.csv",
    ]
    for anchor_path in anchor_paths:
        if not anchor_path.exists():
            continue
        try:
            anchor_df = pd.read_csv(anchor_path)
            if "doi" in anchor_df.columns:
                anchor_dois.update({d for d in anchor_df["doi"].apply(_normalize_doi).tolist() if d})
        except Exception:
            continue

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
    papers["signal_landmark_anchor"] = papers.get("doi", pd.Series("", index=papers.index)).apply(_normalize_doi).isin(anchor_dois).astype(int)
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

    scoring_cfg = cfg.get("scoring", {})
    ms_focus_cfg = scoring_cfg.get("ms_focus", {})
    core_context_cfg = scoring_cfg.get("core_vs_context", {})
    downweight_cfg = scoring_cfg.get("downweight", {})
    topic_balance_cfg = scoring_cfg.get("topic_balance", {})

    papers["score_lexical_relevance"] = _normalize_log1p(papers["lexical_score_raw"])
    papers["score_direct_seed_citation"] = papers["signal_seed"].astype(float)
    papers["score_landmark_anchor"] = papers["signal_landmark_anchor"].astype(float)
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

    w = scoring_cfg.get("weights", {})
    papers["score_field_membership_base"] = (
        w["direct_seed_citation"] * papers["score_direct_seed_citation"] +
        _safe_float(w.get("landmark_anchor", 0.5), 0.5) * papers["score_landmark_anchor"] +
        w["lexical_relevance"] * papers["score_lexical_relevance"] +
        w["dataset_method_alignment"] * papers["score_dataset_method_alignment"] +
        w["cocitation"] * papers["score_cocitation"] +
        w["bibcoupling"] * papers["score_bibcoupling"] +
        w["core_author_overlap"] * papers["score_core_author_overlap"]
    )

    ms_focus_text = (
        papers["title"].fillna("").astype(str)
        + " "
        + papers["abstract"].fillna("").astype(str)
        + " "
        + papers.get("concepts", pd.Series("", index=papers.index)).fillna("").astype(str)
        + " "
        + papers.get("topics", pd.Series("", index=papers.index)).fillna("").astype(str)
    )
    papers["ms_lexical_hits"] = ms_focus_text.apply(lambda t: _count_term_hits(t, MS_FOCUS_TERMS))
    papers["ms_concept_hits"] = ms_focus_text.apply(lambda t: _count_term_hits(t, MS_CONCEPT_TERMS))
    papers["biology_generic_hits"] = ms_focus_text.apply(lambda t: _count_term_hits(t, BIOLOGY_GENERIC_TERMS))
    papers["anchor_category"] = ms_focus_text.apply(_anchor_category_from_text)
    papers["evidence_type"] = papers.apply(
        lambda r: _evidence_type_from_text(str(r.get("title", "")), str(r.get("abstract", ""))),
        axis=1,
    )
    papers["evidence_strength"] = papers["evidence_type"].map(EVIDENCE_STRENGTH_MAP).fillna(2).astype(int)

    ms_lexical_min = max(1, int(ms_focus_cfg.get("lexical_min_hits", 1)))
    ms_concept_min = max(1, int(ms_focus_cfg.get("concept_min_hits", 1)))
    ms_focus_boost = max(1.0, _safe_float(ms_focus_cfg.get("boost_multiplier", 1.65), 1.65))
    ms_focus_minor_boost = max(1.0, _safe_float(ms_focus_cfg.get("minor_boost_multiplier", 1.2), 1.2))
    biology_downweight = min(1.0, max(0.0, _safe_float(downweight_cfg.get("biology_no_ms_multiplier", 0.35), 0.35)))
    biology_hit_min = max(1, int(downweight_cfg.get("biology_hit_min", 2)))

    papers["has_ms_focus"] = (
        (papers["ms_lexical_hits"] >= ms_lexical_min)
        | (papers["ms_concept_hits"] >= ms_concept_min)
    )
    papers["has_strong_ms_focus"] = (
        (papers["ms_lexical_hits"] >= ms_lexical_min)
        & (papers["ms_concept_hits"] >= ms_concept_min)
    )
    papers["seed_affinity_raw_total"] = (
        papers["cocitation_seed_affinity_raw"] + papers["bibcoupling_seed_affinity_raw"]
    )
    papers["biology_no_ms_link"] = (
        (papers["biology_generic_hits"] >= biology_hit_min)
        & (~papers["has_ms_focus"])
        & (papers["seed_affinity_raw_total"] < 3.0)
        & (papers["signal_seed"] == 0)
    )

    papers["score_focus_adjustment"] = 1.0
    papers.loc[papers["has_ms_focus"], "score_focus_adjustment"] *= ms_focus_minor_boost
    papers.loc[papers["has_strong_ms_focus"], "score_focus_adjustment"] *= ms_focus_boost
    papers.loc[papers["biology_no_ms_link"], "score_focus_adjustment"] *= biology_downweight
    papers["score_field_membership"] = papers["score_field_membership_base"] * papers["score_focus_adjustment"]

    papers["score_impact"] = (
        2.0 * papers["score_corpus_citations"] +
        2.0 * papers["score_pagerank"] +
        1.5 * papers["score_global_citations"] +
        1.0 * papers["score_kcore"]
    )
    current_year = datetime.now(timezone.utc).year
    papers["year_int"] = pd.to_numeric(papers.get("year"), errors="coerce")
    papers["paper_age_years"] = (current_year - papers["year_int"].fillna(current_year) + 1).clip(lower=1)
    papers["citations_per_year_raw"] = (
        pd.to_numeric(papers.get("merged_cited_by_count"), errors="coerce").fillna(0.0)
        / papers["paper_age_years"]
    )
    papers["score_citations_per_year"] = _normalize_log1p(papers["citations_per_year_raw"])

    year_groups = papers["year_int"].fillna(-1).astype(int)
    papers["rank_pagerank_year"] = _rank_within_group(papers["pagerank"], year_groups)
    papers["rank_in_degree_year"] = _rank_within_group(papers["in_degree"], year_groups)
    papers["rank_citations_per_year_year"] = _rank_within_group(papers["citations_per_year_raw"], year_groups)
    papers["age_normalized_importance_score"] = (
        0.45 * papers["rank_citations_per_year_year"]
        + 0.35 * papers["rank_pagerank_year"]
        + 0.20 * papers["rank_in_degree_year"]
    )
    papers["rank_age_normalized_importance"] = _normalize_rank(papers["age_normalized_importance_score"])

    papers["paper_importance_score"] = papers["score_impact"]
    papers["score_total"] = papers["score_field_membership"]

    papers["n_independent_signals"] = papers[
        ["signal_seed", "signal_landmark_anchor", "signal_lexical", "signal_dataset"]
    ].sum(axis=1)
    base_inclusion = (
        (papers["n_independent_signals"] >= scoring_cfg.get("include_if_min_signals", 1))
        & (papers["score_field_membership"] >= scoring_cfg.get("include_if_score_at_least", 0.15))
    )
    papers["in_core_corpus"] = base_inclusion & papers["has_ms_focus"]

    bridge_cfg = core_context_cfg.get("bridge", {})
    bridge_min_seed_affinity = max(0.0, _safe_float(bridge_cfg.get("min_seed_affinity", 2.0), 2.0))
    bridge_min_in_degree = max(0, int(bridge_cfg.get("min_in_degree", 3)))
    bridge_min_kcore = max(0, int(bridge_cfg.get("min_kcore", 4)))
    bridge_signal = (
        (papers["seed_affinity_raw_total"] >= bridge_min_seed_affinity)
        | (
            (papers["in_degree"].fillna(0) >= bridge_min_in_degree)
            & (papers["kcore"].fillna(0) >= bridge_min_kcore)
        )
        | (papers["signal_seed"] == 1)
    )
    papers["in_context_corpus"] = (
        base_inclusion
        & (~papers["in_core_corpus"])
        & bridge_signal
        & (~papers["biology_no_ms_link"])
    )

    mode = str(core_context_cfg.get("mode", "core_plus_context")).strip().lower()
    if mode == "core_only":
        papers["in_final_corpus"] = papers["in_core_corpus"]
    else:
        papers["in_final_corpus"] = papers["in_core_corpus"] | papers["in_context_corpus"]

    if bool(topic_balance_cfg.get("enabled", False)):
        target_ranges = topic_balance_cfg.get("target_ranges", {})
        eligible_for_promotion = base_inclusion & (~papers["biology_no_ms_link"])
        papers["in_final_corpus"] = _rebalance_by_category(
            papers=papers,
            selected_mask=papers["in_final_corpus"],
            eligible_mask=eligible_for_promotion,
            score_col="score_total",
            category_col="anchor_category",
            target_ranges=target_ranges,
        )
        papers["in_core_corpus"] = papers["in_final_corpus"] & papers["has_ms_focus"]
        papers["in_context_corpus"] = papers["in_final_corpus"] & (~papers["in_core_corpus"])

    papers["tier"] = "excluded"
    papers["corpus_role"] = "excluded"
    papers.loc[papers["signal_seed"] == 1, "tier"] = "seed_neighbor"
    papers.loc[papers["in_context_corpus"], "corpus_role"] = "context"
    papers.loc[papers["in_core_corpus"], "corpus_role"] = "core"
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
