"""Select the core corpus using explicit tier rules with topic-balance constraints."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd
import yaml

from .utils import ensure_dir, load_config, save_json


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _is_missing_abstract(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().str.lower().isin({"", "nan"})


def _topic_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {str(k): int(v) for k, v in frame["primary_topic_code"].value_counts().sort_index().items()}


def _normalize_doi(value: object) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip()


def _load_t4_signal_rows(root: Path, scored: pd.DataFrame) -> pd.DataFrame:
    path = root / "data" / "t4_expert_signal.yaml"
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "t4_id",
                "t4_concept",
                "title",
                "authors",
                "year",
                "journal",
                "topic_codes",
                "corpus_status",
                "corpus_id",
                "corpus_doi",
                "mapped_canonical_paper_id",
            ]
        )
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_concept = payload.get("by_concept", {}) if isinstance(payload, dict) else {}
    rows: list[dict] = []
    for concept, concept_block in by_concept.items():
        # v2 format: {concept_path: str, papers: [...]}; v1 fallback: list directly.
        if isinstance(concept_block, dict):
            items = concept_block.get("papers", []) or []
        else:
            items = concept_block or []
        for item in items:
            topic_codes = item.get("topic_codes", [])
            if not isinstance(topic_codes, list):
                topic_codes = []
            rows.append(
                {
                    "t4_id": str(item.get("t4_id", "")).strip(),
                    "t4_concept": str(concept or "").strip(),
                    "title": str(item.get("title", "")).strip(),
                    "authors": str(item.get("authors", "")).strip(),
                    "year": pd.to_numeric(item.get("year"), errors="coerce"),
                    "journal": str(item.get("journal", "")).strip(),
                    "topic_codes": ",".join(str(code).strip() for code in topic_codes if str(code).strip()),
                    "corpus_status": str(item.get("corpus_status", "")).strip(),
                    "corpus_id": str(item.get("corpus_id", "")).strip(),
                    # v2: doi field; v1 fallback: corpus_doi
                    "corpus_doi": str(item.get("doi", "") or item.get("corpus_doi", "")).strip(),
                }
            )
    t4 = pd.DataFrame(rows)
    if t4.empty:
        t4["mapped_canonical_paper_id"] = ""
        return t4

    scored_ref = scored[["canonical_paper_id", "doi"]].copy()
    scored_ref["canonical_paper_id"] = scored_ref["canonical_paper_id"].astype(str)
    scored_ref["doi_norm"] = scored_ref["doi"].map(_normalize_doi)
    known_ids = set(scored_ref["canonical_paper_id"])
    doi_to_id = dict(
        zip(
            scored_ref.loc[scored_ref["doi_norm"].astype(str) != "", "doi_norm"],
            scored_ref.loc[scored_ref["doi_norm"].astype(str) != "", "canonical_paper_id"],
        )
    )

    mapped: list[str] = []
    for _, row in t4.iterrows():
        cid = ""
        corpus_id = str(row.get("corpus_id", "") or "").strip()
        if corpus_id and corpus_id in known_ids:
            cid = corpus_id
        else:
            doi_norm = _normalize_doi(row.get("corpus_doi", ""))
            if doi_norm and doi_norm in doi_to_id:
                cid = str(doi_to_id[doi_norm])
        mapped.append(cid)
    t4["mapped_canonical_paper_id"] = mapped
    return t4


def _apply_t2_per_topic_cap(
    scoped: pd.DataFrame,
    is_t1: pd.Series,
    is_t2: pd.Series,
    max_t2_per_topic: int,
    diversity_fraction: float = 0.20,
) -> pd.Series:
    """Cap T2 papers per topic, using Leiden-cluster diversity for the final slot allocation.

    For oversubscribed topics, selection is two-phase:
      Phase 1 — keep top (1 - diversity_fraction) * cap papers by importance score.
      Phase 2 — fill remaining slots by preferring papers from Leiden clusters
                 least represented in Phase 1, breaking ties by importance score.
                 Falls back to pure importance order when community_id is absent.

    Seeds (T1) are never dropped. Papers excluded by the cap may still qualify
    for T3 if they meet the velocity threshold.

    # TODO: revisit diversity_fraction tuning in v1.4+ once corpus runs are stable.
    # The 0.20 default is a reasonable starting point but has not been empirically
    # validated against topic-coverage or retrieval-diversity metrics.
    """
    if max_t2_per_topic <= 0:
        return is_t2.copy()

    community_col = next(
        (c for c in ("dominant_community_id", "community_id") if c in scoped.columns),
        None,
    )

    capped = is_t2.copy()
    for topic, group in scoped.groupby("primary_topic_code"):
        topic_t2 = group[is_t2.loc[group.index] & ~is_t1.loc[group.index]].copy()
        if len(topic_t2) <= max_t2_per_topic:
            continue

        by_importance = topic_t2.sort_values("paper_importance_score", ascending=False)

        # Phase 1: importance-ranked core
        phase1_n = max(1, round((1.0 - diversity_fraction) * max_t2_per_topic))
        phase2_n = max_t2_per_topic - phase1_n
        keep_ids: set[str] = set(
            by_importance.iloc[:phase1_n]["canonical_paper_id"].astype(str)
        )

        # Phase 2: diversity fill from underrepresented Leiden clusters
        if phase2_n > 0 and community_col is not None:
            phase1_rows = by_importance.iloc[:phase1_n]
            cluster_counts: Counter = Counter(
                phase1_rows[community_col].dropna().astype(str)
            )
            remaining = by_importance.iloc[phase1_n:].copy()
            remaining["_cluster_str"] = remaining[community_col].fillna("").astype(str)
            # Lower count = underrepresented = preferred
            remaining["_cluster_count"] = remaining["_cluster_str"].map(
                lambda c: cluster_counts.get(c, 0)
            )
            diversity_sorted = remaining.sort_values(
                ["_cluster_count", "paper_importance_score"], ascending=[True, False]
            )
            keep_ids.update(
                diversity_sorted.iloc[:phase2_n]["canonical_paper_id"].astype(str)
            )
        elif phase2_n > 0:
            # Fallback: no community_id column; extend importance selection
            keep_ids.update(
                by_importance.iloc[phase1_n : phase1_n + phase2_n][
                    "canonical_paper_id"
                ].astype(str)
            )

        drop_ids = set(topic_t2["canonical_paper_id"].astype(str)) - keep_ids
        capped.loc[scoped["canonical_paper_id"].astype(str).isin(drop_ids)] = False

    return capped


def _select_t3_ids(
    scoped: pd.DataFrame,
    is_t1: pd.Series,
    is_t2: pd.Series,
    t3_min_year: int,
    t3_min_citations_per_year: float,
    t3_fraction_of_t2: float,
    t3_floor_per_topic: int,
) -> tuple[set[str], dict[str, dict[str, int]]]:
    eligible = (
        (~is_t1)
        & (~is_t2)
        & (scoped["year_int"] >= t3_min_year)
        & (scoped["citations_per_year_raw"] >= t3_min_citations_per_year)
    )
    selected_ids: set[str] = set()
    diagnostics: dict[str, dict[str, int]] = {}

    for topic, group in scoped.groupby("primary_topic_code"):
        topic_is_t2 = is_t2.loc[group.index]
        topic_eligible = group[eligible.loc[group.index]].copy()
        topic_t2_count = int(topic_is_t2.sum())
        topic_cap = max(t3_floor_per_topic, int(math.ceil(t3_fraction_of_t2 * topic_t2_count)))
        topic_eligible = topic_eligible.sort_values(
            ["citations_per_year_raw", "paper_importance_score", "merged_cited_by_count"],
            ascending=False,
        )
        picked = topic_eligible.head(topic_cap)
        selected_ids.update(picked["canonical_paper_id"].astype(str).tolist())
        diagnostics[str(topic)] = {
            "t2_count": topic_t2_count,
            "t3_cap": int(topic_cap),
            "t3_eligible": int(len(topic_eligible)),
            "t3_selected": int(len(picked)),
        }
    return selected_ids, diagnostics


def _apply_topic_cap(
    selected: pd.DataFrame,
    max_topic_share: float,
) -> tuple[pd.DataFrame, list[dict]]:
    capped = selected.copy()
    removed: list[dict] = []
    tier_rank = {"T3": 0, "T2": 1, "T1": 2}

    while True:
        total = int(len(capped))
        if total <= 0:
            break
        max_allowed = int(math.floor(max_topic_share * total))
        over = capped["primary_topic_code"].value_counts()
        over = over[over > max_allowed]
        if over.empty:
            break

        topic = str((over - max_allowed).sort_values(ascending=False).index[0])
        candidates = capped[(capped["primary_topic_code"] == topic) & (capped["core_selection_tier"] != "T1")].copy()
        if candidates.empty:
            break
        candidates["tier_rank"] = candidates["core_selection_tier"].map(tier_rank).fillna(1)
        candidates = candidates.sort_values(["tier_rank", "paper_importance_score", "citations_per_year_raw"])
        drop_row = candidates.iloc[0]
        drop_id = str(drop_row["canonical_paper_id"])
        removed.append(
            {
                "canonical_paper_id": drop_id,
                "primary_topic_code": topic,
                "removed_tier": str(drop_row.get("core_selection_tier", "")),
                "paper_importance_score": float(drop_row.get("paper_importance_score", 0.0)),
            }
        )
        capped = capped[capped["canonical_paper_id"].astype(str) != drop_id].copy()

    return capped, removed


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    outdir = root / cfg["output_dir"]
    graph_dir = outdir / "graph"
    topics_dir = outdir / "topics"
    ensure_dir(graph_dir)

    scored_path = graph_dir / "scored_papers.csv"
    topic_evidence_path = topics_dir / "paper_topic_evidence.csv"
    if not scored_path.exists():
        raise FileNotFoundError(f"Missing {scored_path}")
    if not topic_evidence_path.exists():
        raise FileNotFoundError(
            f"Missing {topic_evidence_path}. Run `python -m src.assign_topic_evidence --config {config_path}` first."
        )

    selection_cfg = cfg.get("core_corpus_selection", {}) or {}
    t2_cfg = selection_cfg.get("t2", {}) or {}
    t3_cfg = selection_cfg.get("t3", {}) or {}
    balance_cfg = selection_cfg.get("balance", {}) or {}

    t2_min_cross_seed = max(1, int(t2_cfg.get("min_cross_seed_score", 2)))
    t2_min_kcore = max(0, int(t2_cfg.get("min_kcore", 4)))
    t2_min_in_degree = max(0, int(t2_cfg.get("min_in_degree", 2)))
    t2_importance_pct = float(t2_cfg.get("importance_percentile_by_category", 70.0))
    t2_importance_quantile = min(0.999, max(0.0, t2_importance_pct / 100.0))
    t2_relax_below_topic_share = min(1.0, max(0.0, float(t2_cfg.get("relax_structure_below_topic_share", 0.02))))
    t2_max_per_topic = int(t2_cfg.get("max_per_topic", 100))
    t2_diversity_fraction = float(t2_cfg.get("diversity_fraction", 0.20))

    t3_min_year = int(t3_cfg.get("min_year", 2022))
    t3_min_citations_per_year = float(t3_cfg.get("min_citations_per_year", 20.0))
    t3_fraction_of_t2 = max(0.0, float(t3_cfg.get("cap_fraction_of_t2_per_topic", 0.20)))
    t3_floor_per_topic = max(0, int(t3_cfg.get("floor_per_topic", 5)))

    max_topic_share = min(1.0, max(0.0, float(balance_cfg.get("max_topic_share", 0.20))))

    scored = pd.read_csv(scored_path, low_memory=False)
    scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
    scoped = scored.copy()
    if "in_final_corpus" in scoped.columns:
        scoped = scoped[scoped["in_final_corpus"] == True].copy()  # noqa: E712
    elif "tier" in scoped.columns:
        scoped = scoped[scoped["tier"].astype(str).isin({"included", "seed_neighbor"})].copy()

    topic_evidence = pd.read_csv(topic_evidence_path, usecols=["canonical_paper_id", "primary_topic_code"])
    topic_evidence["canonical_paper_id"] = topic_evidence["canonical_paper_id"].astype(str)
    scoped = scoped.merge(topic_evidence, on="canonical_paper_id", how="left")
    scoped["primary_topic_code"] = scoped["primary_topic_code"].fillna("UNMAPPED").astype(str)
    scoped["anchor_category"] = scoped.get("anchor_category", pd.Series("", index=scoped.index)).fillna("unmapped")
    scoped["anchor_category"] = scoped["anchor_category"].astype(str).replace({"": "unmapped"})
    scoped["is_core_seed"] = scoped.get("is_core_seed", pd.Series(False, index=scoped.index)).map(_boolish)

    for col in [
        "cross_seed_score",
        "kcore",
        "in_degree",
        "paper_importance_score",
        "year_int",
        "year",
        "citations_per_year_raw",
        "merged_cited_by_count",
    ]:
        if col in scoped.columns:
            scoped[col] = pd.to_numeric(scoped[col], errors="coerce")
    scoped["cross_seed_score"] = scoped.get("cross_seed_score", pd.Series(0.0, index=scoped.index)).fillna(0.0)
    scoped["kcore"] = scoped.get("kcore", pd.Series(0.0, index=scoped.index)).fillna(0.0)
    scoped["in_degree"] = scoped.get("in_degree", pd.Series(0.0, index=scoped.index)).fillna(0.0)
    scoped["paper_importance_score"] = scoped.get("paper_importance_score", pd.Series(0.0, index=scoped.index)).fillna(0.0)
    scoped["citations_per_year_raw"] = scoped.get("citations_per_year_raw", pd.Series(0.0, index=scoped.index)).fillna(0.0)
    scoped["merged_cited_by_count"] = scoped.get("merged_cited_by_count", pd.Series(0.0, index=scoped.index)).fillna(0.0)
    if "year_int" in scoped.columns:
        scoped["year_int"] = scoped["year_int"].fillna(scoped.get("year", 0)).fillna(0).astype(int)
    else:
        scoped["year_int"] = pd.to_numeric(scoped.get("year", pd.Series(0, index=scoped.index)), errors="coerce").fillna(0).astype(int)

    cat_threshold = scoped.groupby("anchor_category")["paper_importance_score"].quantile(t2_importance_quantile).to_dict()
    scoped["t2_category_importance_threshold"] = scoped["anchor_category"].map(cat_threshold).fillna(float("inf"))

    is_t1 = scoped["is_core_seed"].copy()
    t2_base_gate = (
        (~is_t1)
        & (scoped["cross_seed_score"] >= t2_min_cross_seed)
        & (scoped["paper_importance_score"] > scoped["t2_category_importance_threshold"])
    )
    t2_structure_gate = (scoped["kcore"] >= t2_min_kcore) & (scoped["in_degree"] >= t2_min_in_degree)
    t2_strict = t2_base_gate & t2_structure_gate

    strict_t3_ids, strict_t3_diag = _select_t3_ids(
        scoped=scoped,
        is_t1=is_t1,
        is_t2=t2_strict,
        t3_min_year=t3_min_year,
        t3_min_citations_per_year=t3_min_citations_per_year,
        t3_fraction_of_t2=t3_fraction_of_t2,
        t3_floor_per_topic=t3_floor_per_topic,
    )
    strict_union = scoped[
        is_t1
        | t2_strict
        | scoped["canonical_paper_id"].astype(str).isin(strict_t3_ids)
    ].copy()
    strict_topic_share = strict_union["primary_topic_code"].value_counts(normalize=True)
    low_share_topics = sorted(strict_topic_share[strict_topic_share < t2_relax_below_topic_share].index.tolist())

    t2_relax_gate = t2_base_gate & scoped["primary_topic_code"].isin(low_share_topics)
    t2_final = t2_strict | t2_relax_gate
    # Hard per-topic cap with Leiden-cluster diversity fill (Option A).
    # Seeds excluded; papers dropped here may still qualify for T3.
    t2_final = _apply_t2_per_topic_cap(
        scoped,
        is_t1=is_t1,
        is_t2=t2_final,
        max_t2_per_topic=t2_max_per_topic,
        diversity_fraction=t2_diversity_fraction,
    )

    t3_ids, t3_diag = _select_t3_ids(
        scoped=scoped,
        is_t1=is_t1,
        is_t2=t2_final,
        t3_min_year=t3_min_year,
        t3_min_citations_per_year=t3_min_citations_per_year,
        t3_fraction_of_t2=t3_fraction_of_t2,
        t3_floor_per_topic=t3_floor_per_topic,
    )
    is_t3 = scoped["canonical_paper_id"].astype(str).isin(t3_ids)

    pre_cap = scoped[is_t1 | t2_final | is_t3].copy()
    pre_cap["core_selection_tier"] = "T3"
    pre_cap.loc[t2_final.loc[pre_cap.index], "core_selection_tier"] = "T2"
    pre_cap.loc[is_t1.loc[pre_cap.index], "core_selection_tier"] = "T1"
    pre_cap["t2_base_gate"] = t2_base_gate.loc[pre_cap.index].astype(bool)
    pre_cap["t2_structure_gate"] = t2_structure_gate.loc[pre_cap.index].astype(bool)
    pre_cap["t2_relax_gate"] = t2_relax_gate.loc[pre_cap.index].astype(bool)
    pre_cap["t3_selected"] = is_t3.loc[pre_cap.index].astype(bool)

    t3_rank_df = pd.DataFrame({"canonical_paper_id": scoped["canonical_paper_id"].astype(str), "t3_rank_in_topic": 0, "t3_topic_cap": 0})
    for topic, group in scoped.groupby("primary_topic_code"):
        topic_cap = int(t3_diag.get(str(topic), {}).get("t3_cap", 0))
        elig = group[
            (~is_t1.loc[group.index])
            & (~t2_final.loc[group.index])
            & (scoped.loc[group.index, "year_int"] >= t3_min_year)
            & (scoped.loc[group.index, "citations_per_year_raw"] >= t3_min_citations_per_year)
        ].copy()
        elig = elig.sort_values(["citations_per_year_raw", "paper_importance_score", "merged_cited_by_count"], ascending=False)
        for rank, (_, row) in enumerate(elig.iterrows(), start=1):
            pid = str(row["canonical_paper_id"])
            t3_rank_df.loc[t3_rank_df["canonical_paper_id"] == pid, "t3_rank_in_topic"] = int(rank)
            t3_rank_df.loc[t3_rank_df["canonical_paper_id"] == pid, "t3_topic_cap"] = int(topic_cap)
    pre_cap = pre_cap.merge(t3_rank_df, on="canonical_paper_id", how="left")
    pre_cap["t3_rank_in_topic"] = pre_cap["t3_rank_in_topic"].fillna(0).astype(int)
    pre_cap["t3_topic_cap"] = pre_cap["t3_topic_cap"].fillna(0).astype(int)

    capped, removed = _apply_topic_cap(pre_cap, max_topic_share=max_topic_share)

    selected_path = graph_dir / "core_corpus_selected.csv"
    capped.to_csv(selected_path, index=False)

    removed_df = pd.DataFrame(removed)
    removed_path = graph_dir / "core_corpus_removed_by_topic_cap.csv"
    if removed_df.empty:
        removed_df = pd.DataFrame(columns=["canonical_paper_id", "primary_topic_code", "removed_tier", "paper_importance_score"])
    removed_df.to_csv(removed_path, index=False)

    missing = capped[_is_missing_abstract(capped.get("abstract", pd.Series("", index=capped.index)))]
    missing_path = graph_dir / "core_corpus_missing_abstracts.csv"
    missing.to_csv(missing_path, index=False)

    t4_rows = _load_t4_signal_rows(root, scored)
    t4_meta_cols = ["t4_id", "t4_concept", "t4_source_type", "t4_topic_codes", "t4_corpus_status"]
    tracked = capped.copy()
    tracked["tracked_source"] = "T1_T2_T3"
    for col in t4_meta_cols:
        tracked[col] = ""

    mapped_rows = t4_rows[t4_rows["mapped_canonical_paper_id"].astype(str) != ""].copy() if not t4_rows.empty else pd.DataFrame()
    mapped_rows_df = pd.DataFrame(
        columns=["canonical_paper_id", "t4_id", "t4_concept", "t4_source_type", "t4_topic_codes", "t4_corpus_status"]
    )
    if not mapped_rows.empty:
        mapped_rows_df = mapped_rows.rename(columns={"mapped_canonical_paper_id": "canonical_paper_id"})[
            ["canonical_paper_id", "t4_id", "t4_concept", "topic_codes", "corpus_status"]
        ].copy()
        mapped_rows_df["canonical_paper_id"] = mapped_rows_df["canonical_paper_id"].astype(str)
        mapped_rows_df["t4_source_type"] = "concept_anchor_signal"
        mapped_rows_df = mapped_rows_df.rename(
            columns={"topic_codes": "t4_topic_codes", "corpus_status": "t4_corpus_status"}
        ).drop_duplicates(subset=["canonical_paper_id"])
        tracked = tracked.drop(columns=t4_meta_cols, errors="ignore").merge(
            mapped_rows_df, on="canonical_paper_id", how="left"
        )
        for col in t4_meta_cols:
            tracked[col] = tracked[col].fillna("")
        tracked.loc[tracked["t4_id"].astype(str) != "", "tracked_source"] = "T1_T2_T3_plus_T4"

    selected_ids = set(tracked["canonical_paper_id"].astype(str))
    t4_mapped_ids = set(mapped_rows_df["canonical_paper_id"].astype(str)) if not mapped_rows_df.empty else set()
    t4_mapped_add_ids = sorted(t4_mapped_ids - selected_ids)

    scored_with_topic = scored.merge(topic_evidence, on="canonical_paper_id", how="left")
    scored_with_topic["primary_topic_code"] = scored_with_topic["primary_topic_code"].fillna("UNMAPPED").astype(str)

    t4_mapped_add_df = pd.DataFrame(columns=tracked.columns)
    if t4_mapped_add_ids:
        t4_mapped_add_df = scored_with_topic[
            scored_with_topic["canonical_paper_id"].astype(str).isin(t4_mapped_add_ids)
        ].copy()
        for col in tracked.columns:
            if col not in t4_mapped_add_df.columns:
                t4_mapped_add_df[col] = pd.NA
        t4_mapped_add_df = t4_mapped_add_df[tracked.columns].copy()
        t4_mapped_add_df["core_selection_tier"] = "T4"
        t4_mapped_add_df["tracked_source"] = "T4_mapped"
        for flag_col, val in (
            ("t2_base_gate", False),
            ("t2_structure_gate", False),
            ("t2_relax_gate", False),
            ("t3_selected", False),
            ("t3_rank_in_topic", 0),
            ("t3_topic_cap", 0),
        ):
            if flag_col in t4_mapped_add_df.columns:
                t4_mapped_add_df[flag_col] = val
        t4_mapped_add_df = t4_mapped_add_df.drop(columns=t4_meta_cols, errors="ignore").merge(
            mapped_rows_df, on="canonical_paper_id", how="left"
        )
        for col in t4_meta_cols:
            t4_mapped_add_df[col] = t4_mapped_add_df[col].fillna("")
        tracked = pd.concat([tracked, t4_mapped_add_df[tracked.columns]], ignore_index=True)

    forced_rows = (
        t4_rows[t4_rows["mapped_canonical_paper_id"].astype(str) == ""].copy() if not t4_rows.empty else pd.DataFrame()
    )
    forced_rows = forced_rows[
        forced_rows["corpus_status"].astype(str).str.lower().str.startswith("not_found")
    ].copy() if not forced_rows.empty else forced_rows

    forced_df = pd.DataFrame(columns=tracked.columns)
    if not forced_rows.empty:
        forced_records: list[dict] = []
        for _, row in forced_rows.iterrows():
            t4_id = str(row.get("t4_id", "")).strip()
            pid = f"t4::{t4_id.lower()}" if t4_id else f"t4::{len(forced_records) + 1}"
            topic_codes = [part.strip() for part in str(row.get("topic_codes", "")).split(",") if part.strip()]
            primary_topic = topic_codes[0] if topic_codes else "UNMAPPED"
            year_value = int(row["year"]) if not pd.isna(row.get("year")) else pd.NA
            forced_records.append(
                {
                    "canonical_paper_id": pid,
                    "title": str(row.get("title", "")).strip(),
                    "year": year_value,
                    "year_int": year_value if year_value is not pd.NA else 0,
                    "doi": _normalize_doi(row.get("corpus_doi", "")),
                    "venue": str(row.get("journal", "")).strip(),
                    "first_author": str(row.get("authors", "")).strip(),
                    "openalex_id": "",
                    "all_openalex_ids": "",
                    "abstract": "",
                    "tier": "included",
                    "core_selection_tier": "T4",
                    "primary_topic_code": primary_topic,
                    "paper_importance_score": 0.0,
                    "age_normalized_importance_score": 0.0,
                    "rank_age_normalized_importance": 0.0,
                    "citations_per_year_raw": 0.0,
                    "paper_age_years": 0.0,
                    "merged_cited_by_count": 0,
                    "pagerank": 0.0,
                    "kcore": 0,
                    "in_degree": 0,
                    "out_degree": 0,
                    "cross_seed_score": 0.0,
                    "is_core_seed": False,
                    "t2_base_gate": False,
                    "t2_structure_gate": False,
                    "t2_relax_gate": False,
                    "t3_selected": False,
                    "t3_rank_in_topic": 0,
                    "t3_topic_cap": 0,
                    "tracked_source": "T4_forced_not_found",
                    "t4_id": t4_id,
                    "t4_concept": str(row.get("t4_concept", "")).strip(),
                    "t4_source_type": "concept_anchor_signal",
                    "t4_topic_codes": str(row.get("topic_codes", "")).strip(),
                    "t4_corpus_status": str(row.get("corpus_status", "")).strip(),
                    "evidence_type": "expert_pick",
                    "evidence_strength": 1,
                }
            )
        forced_df = pd.DataFrame(forced_records)
        for col in tracked.columns:
            if col not in forced_df.columns:
                forced_df[col] = pd.NA
        forced_df = forced_df[tracked.columns].copy()
        tracked = pd.concat([tracked, forced_df], ignore_index=True)

    tracked_path = graph_dir / "core_corpus_tracked_with_t4.csv"
    tracked.to_csv(tracked_path, index=False)
    t4_additions_path = graph_dir / "t4_mapped_additions_not_in_t1_t3.csv"
    if t4_mapped_add_df.empty:
        pd.DataFrame(columns=tracked.columns).to_csv(t4_additions_path, index=False)
    else:
        t4_mapped_add_df.to_csv(t4_additions_path, index=False)
    t4_forced_path = graph_dir / "t4_forced_not_found.csv"
    if forced_df.empty:
        pd.DataFrame(columns=tracked.columns).to_csv(t4_forced_path, index=False)
    else:
        forced_df.to_csv(t4_forced_path, index=False)

    # Document the three classification systems and their roles for provenance.
    classification_systems = {
        "topic_codes": {
            "description": (
                "19 T-codes (T00–T16 plus T1b) manually assigned by editors based on "
                "the MS Field Orientation Guide. Primary_topic from core_seeds.csv is "
                "propagated to neighboring papers by assign_topic_evidence."
            ),
            "role": (
                "primary — drives corpus balance (max_topic_share gate) and is the "
                "authoritative topic label for all pipeline outputs"
            ),
            "source": "seeds/core_seeds.csv (primary_topic column) → outputs/topics/paper_topic_evidence.csv",
            "not_used_for": "Leiden citation clusters are not used here",
        },
        "leiden_citation_clusters": {
            "description": (
                "9 algorithmically derived citation clusters produced by Louvain community "
                "detection on the citation graph (discover_topics stage). Stored as topic_id "
                "on paper nodes in explorer_graph.json."
            ),
            "role": (
                "informational — available on the website as an alternative framing and "
                "in explorer_graph.json for graph exploration; NOT used in corpus balance "
                "or selection decisions at any pipeline stage"
            ),
            "source": "outputs/graph/topic_clusters.csv (discover_topics stage)",
            "not_used_for": "balance gate, T2/T3 selection, or topic assignment",
        },
        "learner_concepts": {
            "description": (
                "~30 pedagogical concept pages derived from literature and learning science "
                "(site/src/content/docs/concepts/). Concepts are manually authored and link "
                "to corpus papers. They also serve as the nomination source for T4 expert "
                "signals via data/t4_expert_signal.yaml."
            ),
            "role": (
                "site navigation only — drives concept page links and T4 expert signal "
                "nomination; NOT used in corpus selection or balance"
            ),
            "source": "site/src/content/docs/concepts/**/*.md → data/t4_expert_signal.yaml",
            "not_used_for": "balance gate, T2/T3 selection, or topic_code assignment",
        },
    }

    summary = {
        "input_scoped_rows": int(len(scoped)),
        "classification_systems": classification_systems,
        "rules": {
            "t2": {
                "min_cross_seed_score": t2_min_cross_seed,
                "min_kcore": t2_min_kcore,
                "min_in_degree": t2_min_in_degree,
                "importance_percentile_by_category": t2_importance_pct,
                "relax_structure_below_topic_share": t2_relax_below_topic_share,
            },
            "t3": {
                "min_year": t3_min_year,
                "min_citations_per_year": t3_min_citations_per_year,
                "cap_fraction_of_t2_per_topic": t3_fraction_of_t2,
                "floor_per_topic": t3_floor_per_topic,
            },
            "balance": {"max_topic_share": max_topic_share},
        },
        "low_share_topics_for_t2_relaxation": low_share_topics,
        "strict_pass_counts": {
            "t1": int(is_t1.sum()),
            "t2_strict": int(t2_strict.sum()),
            "t3_strict_selected": int(len(strict_t3_ids)),
            "union_strict_pre_relax": int(len(strict_union)),
        },
        "final_pre_cap_counts": {
            "t1": int(is_t1.sum()),
            "t2": int(t2_final.sum()),
            "t3": int(is_t3.sum()),
            "union": int(len(pre_cap)),
        },
        "final_post_cap_counts": {
            "union": int(len(capped)),
            "tier_counts": {str(k): int(v) for k, v in Counter(capped["core_selection_tier"]).items()},
            "topic_counts": _topic_counts(capped),
            "max_topic_share_pct": round(100.0 * float(capped["primary_topic_code"].value_counts(normalize=True).max()), 4)
            if len(capped) > 0
            else 0.0,
        },
        "topic_counts_pre_cap": _topic_counts(pre_cap),
        "t3_topic_diagnostics": t3_diag,
        "t3_topic_diagnostics_strict": strict_t3_diag,
        "topic_cap_removals": {
            "total_removed": int(len(removed)),
            "removed_by_topic": {str(k): int(v) for k, v in removed_df["primary_topic_code"].value_counts().items()} if not removed_df.empty else {},
            "removed_by_tier": {str(k): int(v) for k, v in removed_df["removed_tier"].value_counts().items()} if not removed_df.empty else {},
        },
        "missing_abstracts_in_selected": {
            "count": int(len(missing)),
            "pct": round(100.0 * float(len(missing)) / float(len(capped)), 4) if len(capped) > 0 else 0.0,
            "path": str(missing_path),
        },
        "t4": {
            "yaml_rows_total": int(len(t4_rows)),
            "mapped_to_existing_corpus": int(len(t4_mapped_ids)),
            "mapped_additions_not_in_t1_t2_t3": int(len(t4_mapped_add_df)),
            "forced_not_found_added": int(len(forced_df)),
            "tracked_total_with_t4": int(len(tracked)),
        },
        "artifacts": {
            "selected_csv": str(selected_path),
            "removed_csv": str(removed_path),
            "missing_csv": str(missing_path),
            "tracked_with_t4_csv": str(tracked_path),
            "t4_mapped_additions_csv": str(t4_additions_path),
            "t4_forced_not_found_csv": str(t4_forced_path),
        },
    }
    summary_path = graph_dir / "core_corpus_selection_summary.json"
    save_json(summary, summary_path)

    print(f"core_corpus_selected.csv: {selected_path}")
    print(f"core_corpus_selection_summary.json: {summary_path}")
    print(f"core_corpus_missing_abstracts.csv: {missing_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
