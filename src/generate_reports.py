"""Generate two post-pipeline reports:
1) QA/QC corpus report (authoritative topic-code lens)
2) Expert comms site-readiness pass (look/feel, engagement, errors)

Outputs are written to outputs/expert_comms/ with both stable and timestamped filenames.
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .utils import ensure_dir, load_config, load_downstream_corpus, save_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_str(value: object) -> str:
    """Return string form of value, or '' for None/NaN."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _safe_int(value: object, default: int = 0) -> int:
    """Coerce value to int, returning default on failure."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    """Coerce value to float, returning default on failure."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _boolish(value: object) -> bool:
    """Interpret bool-like config values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _timestamp_slug(dt: datetime) -> str:
    """Return filesystem-safe UTC timestamp like YYYYMMDDTHHMMSSZ."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _top_venues(papers: pd.DataFrame, k: int = 5) -> list[tuple[str, int]]:
    """Return top-k (venue, count) pairs sorted by count descending."""
    venue_col = "venue" if "venue" in papers.columns else "journal"
    if venue_col not in papers.columns:
        return []
    counts: Counter = Counter()
    for v in papers[venue_col]:
        s = _safe_str(v)
        if s and s.lower() != "nan":
            counts[s] += 1
    return counts.most_common(k)


def _year_span(papers: pd.DataFrame) -> tuple[int | None, int | None]:
    """Return (min_year, max_year) for a set of papers, or (None, None) if unavailable."""
    if "year" not in papers.columns or papers.empty:
        return None, None
    years = pd.to_numeric(papers["year"], errors="coerce").dropna().astype(int)
    if years.empty:
        return None, None
    return int(years.min()), int(years.max())


def _tier_label(row: pd.Series) -> str:
    """Derive a human-readable tier label from row flags."""
    core_tier = _safe_str(row.get("core_selection_tier")).upper()
    if core_tier in {"T1", "T1_REF", "T2", "T3", "T4"}:
        return core_tier

    if _safe_int(row.get("in_t4_expert_signal"), 0):
        return "T4"
    if _safe_int(row.get("is_seed"), 0) or _safe_int(row.get("is_core_seed"), 0):
        return "T1"
    if _safe_int(row.get("is_reference_seed"), 0):
        return "T1_REF"
    if _safe_int(row.get("t3_selected"), 0):
        return "T3"
    tier = _safe_str(row.get("tier"))
    if tier == "velocity":
        return "T3"
    return "T2"


def _normalize_doi(doi: str) -> str:
    text = _safe_str(doi)
    if not text:
        return ""
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    return text.strip()


def _top_papers(papers: pd.DataFrame, k: int = 10) -> list[dict[str, Any]]:
    """Return top-k paper records sorted by paper_importance_score."""
    if papers.empty:
        return []
    score_col = "paper_importance_score"
    if score_col not in papers.columns:
        score_col = "pagerank"
    df = papers.copy()
    df[score_col] = pd.to_numeric(df.get(score_col, pd.Series(0.0)), errors="coerce").fillna(0.0)
    df = df.sort_values(score_col, ascending=False).head(k)
    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "title": _safe_str(row.get("title")),
                "year": _safe_int(row.get("year")),
                "venue": _safe_str(row.get("venue") or row.get("journal")),
                "citations": _safe_int(row.get("merged_cited_by_count")),
                "importance": round(_safe_float(row.get("paper_importance_score")), 4),
                "tier": _tier_label(row),
                "doi": _normalize_doi(_safe_str(row.get("doi"))),
            }
        )
    return out


def _parse_target_min(value: object) -> int | None:
    """Parse min from topic target field like '25-30'."""
    text = _safe_str(value)
    if not text:
        return None
    m = re.match(r"^(\d+)", text)
    if not m:
        return None
    return int(m.group(1))


def _load_topic_map(topic_map_path: Path) -> tuple[list[str], dict[str, str], dict[str, str], dict[str, int | None]]:
    """Return (ordered codes, code->name, code->layer, code->target_min)."""
    if not topic_map_path.exists():
        return [], {}, {}, {}
    try:
        payload = json.loads(topic_map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], {}, {}, {}

    ordered: list[str] = []
    names: dict[str, str] = {}
    layers: dict[str, str] = {}
    target_min: dict[str, int | None] = {}
    for row in payload.get("topics", []):
        code = _safe_str(row.get("topic_code"))
        if not code:
            continue
        if code not in ordered:
            ordered.append(code)
        names[code] = _safe_str(row.get("topic_name")) or code
        layers[code] = _safe_str(row.get("layer"))
        target_min[code] = _parse_target_min(row.get("target_n"))
    return ordered, names, layers, target_min


def _load_cluster_data(out_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (paper_id->cluster_id, cluster_id->label)."""
    topics_dir = out_dir / "topics"
    paper_to_cluster: dict[str, str] = {}
    cluster_labels: dict[str, str] = {}

    paper_topics_path = topics_dir / "paper_topics.csv"
    if paper_topics_path.exists():
        pt = pd.read_csv(paper_topics_path)
        paper_to_cluster = dict(
            zip(pt["canonical_paper_id"].astype(str), pt["topic_id"].astype(str))
        )

    topic_clusters_path = topics_dir / "topic_clusters.csv"
    if topic_clusters_path.exists():
        tc = pd.read_csv(topic_clusters_path)
        label_series = tc.get("auto_label", tc.get("topic_id", pd.Series(dtype=str))).astype(str)
        cluster_labels = dict(zip(tc["topic_id"].astype(str), label_series))

    return paper_to_cluster, cluster_labels


def _load_t4_signal_entries(root: Path) -> pd.DataFrame:
    """Load live T4 nomination rows from data/t4_expert_signal.yaml."""
    path = root / "data" / "t4_expert_signal.yaml"
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "t4_id",
                "t4_concept",
                "title",
                "year",
                "journal",
                "topic_codes",
                "include_in_graph",
                "corpus_status_yaml",
                "corpus_id_yaml",
                "doi_yaml",
                "exclusion_note",
                "relevance",
            ]
        )

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_concept = payload.get("by_concept", {}) if isinstance(payload, dict) else {}

    rows: list[dict[str, Any]] = []
    for concept, concept_block in by_concept.items():
        entries = concept_block.get("papers", []) if isinstance(concept_block, dict) else concept_block
        for item in entries or []:
            topic_codes = item.get("topic_codes", [])
            if isinstance(topic_codes, list):
                topic_codes_str = ",".join(str(x).strip() for x in topic_codes if str(x).strip())
            else:
                topic_codes_str = _safe_str(topic_codes)

            rows.append(
                {
                    "t4_id": _safe_str(item.get("t4_id")),
                    "t4_concept": _safe_str(concept),
                    "title": _safe_str(item.get("title")),
                    "year": item.get("year"),
                    "journal": _safe_str(item.get("journal")),
                    "topic_codes": topic_codes_str,
                    "include_in_graph": _boolish(item.get("include_in_graph", True)),
                    "corpus_status_yaml": _safe_str(item.get("corpus_status")),
                    "corpus_id_yaml": _safe_str(item.get("corpus_id")),
                    "doi_yaml": _safe_str(item.get("doi") or item.get("corpus_doi")),
                    "exclusion_note": _safe_str(item.get("exclusion_note")),
                    "relevance": _safe_str(item.get("relevance")),
                }
            )
    return pd.DataFrame(rows)


def _build_review_sheets(root: Path, out_dir: Path, timestamp_slug: str) -> dict[str, Any]:
    """Write live review sheets (T4 status + held papers) with stable and timestamped filenames."""
    review_dir = out_dir / "review"
    graph_dir = out_dir / "graph"
    normalized_dir = out_dir / "normalized"
    ensure_dir(review_dir)

    hold_columns = [
        "canonical_paper_id",
        "core_selection_tier",
        "primary_topic_code",
        "t4_id",
        "tracked_source",
        "doi",
        "title",
        "hold_reason",
    ]
    hold_path = graph_dir / "papers_on_hold_missing_abstract.csv"
    if hold_path.exists():
        hold_df = pd.read_csv(hold_path, low_memory=False)
    else:
        hold_df = pd.DataFrame(columns=hold_columns)
    for col in hold_columns:
        if col not in hold_df.columns:
            hold_df[col] = ""
    hold_df = hold_df[hold_columns].copy()
    hold_df["canonical_paper_id"] = hold_df["canonical_paper_id"].astype(str)

    canonical_path = normalized_dir / "canonical_papers.csv"
    if canonical_path.exists() and not hold_df.empty:
        canonical = pd.read_csv(canonical_path, low_memory=False)
        canonical["canonical_paper_id"] = canonical["canonical_paper_id"].astype(str)
        merge_cols = [c for c in ["canonical_paper_id", "year", "venue", "openalex_id", "abstract"] if c in canonical.columns]
        if merge_cols:
            hold_df = hold_df.merge(canonical[merge_cols], on="canonical_paper_id", how="left")

    hold_sheet_cols = [
        "canonical_paper_id",
        "title",
        "year",
        "venue",
        "doi",
        "openalex_id",
        "core_selection_tier",
        "primary_topic_code",
        "t4_id",
        "tracked_source",
        "hold_reason",
        "review_decision",
        "replacement_doi",
        "provided_abstract",
        "review_notes",
    ]
    hold_df["review_decision"] = ""
    hold_df["replacement_doi"] = ""
    hold_df["provided_abstract"] = ""
    hold_df["review_notes"] = ""
    for col in hold_sheet_cols:
        if col not in hold_df.columns:
            hold_df[col] = ""
    hold_sheet = hold_df[hold_sheet_cols].copy()
    hold_sheet = hold_sheet.sort_values(["primary_topic_code", "title"], na_position="last").reset_index(drop=True)

    hold_latest = review_dir / "held_missing_abstract_status.csv"
    hold_stamp = review_dir / f"held_missing_abstract_status_{timestamp_slug}.csv"
    hold_sheet.to_csv(hold_latest, index=False)
    hold_sheet.to_csv(hold_stamp, index=False)

    topic16_sheet = hold_sheet[hold_sheet["primary_topic_code"].astype(str) == "TOPIC-16"].copy()
    topic16_latest = review_dir / "topic16_held_missing_abstract.csv"
    topic16_stamp = review_dir / f"topic16_held_missing_abstract_{timestamp_slug}.csv"
    topic16_sheet.to_csv(topic16_latest, index=False)
    topic16_sheet.to_csv(topic16_stamp, index=False)

    t4_df = _load_t4_signal_entries(root)
    if t4_df.empty:
        t4_sheet = pd.DataFrame(
            columns=[
                "t4_id",
                "t4_concept",
                "title",
                "year",
                "journal",
                "topic_codes",
                "include_in_graph",
                "selection_status",
                "corpus_status_yaml",
                "mapped_to_scored",
                "map_method",
                "mapped_canonical_paper_id",
                "in_selected",
                "in_tracked",
                "on_hold",
                "core_selection_tier",
                "tracked_source",
                "doi_yaml",
                "corpus_id_yaml",
                "exclusion_note",
                "relevance",
                "review_decision",
                "replacement_doi",
                "provided_abstract",
                "review_notes",
            ]
        )
    else:
        for col in ["t4_id", "t4_concept", "title", "journal", "topic_codes", "corpus_status_yaml", "corpus_id_yaml", "doi_yaml"]:
            t4_df[col] = t4_df[col].map(_safe_str).astype(str)

        scored_path = graph_dir / "scored_papers.csv"
        tracked_path = graph_dir / "core_corpus_tracked_with_t4.csv"
        selected_path = graph_dir / "core_corpus_selected.csv"

        if scored_path.exists():
            scored = pd.read_csv(scored_path, low_memory=False, usecols=lambda c: c in {"canonical_paper_id", "doi"})
        else:
            scored = pd.DataFrame(columns=["canonical_paper_id", "doi"])
        scored["canonical_paper_id"] = scored.get("canonical_paper_id", pd.Series(dtype=str)).astype(str)
        scored["doi_norm"] = scored.get("doi", pd.Series("", index=scored.index)).map(_normalize_doi)

        known_ids = set(scored["canonical_paper_id"].astype(str))
        doi_to_id = dict(
            zip(
                scored.loc[scored["doi_norm"].astype(str) != "", "doi_norm"],
                scored.loc[scored["doi_norm"].astype(str) != "", "canonical_paper_id"],
            )
        )

        tracked = (
            pd.read_csv(tracked_path, low_memory=False, usecols=lambda c: c in {"canonical_paper_id", "core_selection_tier", "tracked_source", "t4_id"})
            if tracked_path.exists()
            else pd.DataFrame(columns=["canonical_paper_id", "core_selection_tier", "tracked_source", "t4_id"])
        )
        selected = (
            pd.read_csv(selected_path, low_memory=False, usecols=lambda c: c == "canonical_paper_id")
            if selected_path.exists()
            else pd.DataFrame(columns=["canonical_paper_id"])
        )

        tracked["canonical_paper_id"] = tracked.get("canonical_paper_id", pd.Series(dtype=str)).astype(str)
        tracked["t4_id"] = tracked.get("t4_id", pd.Series("", index=tracked.index)).map(_safe_str).astype(str)
        selected["canonical_paper_id"] = selected.get("canonical_paper_id", pd.Series(dtype=str)).astype(str)
        hold_ids = set(hold_df["canonical_paper_id"].astype(str))
        tracked_ids = set(tracked["canonical_paper_id"].astype(str))
        selected_ids = set(selected["canonical_paper_id"].astype(str))

        mapped_ids: list[str] = []
        map_methods: list[str] = []
        for _, row in t4_df.iterrows():
            mapped_id = ""
            method = ""
            cid = _safe_str(row.get("corpus_id_yaml"))
            if cid and cid in known_ids:
                mapped_id = cid
                method = "corpus_id"
            else:
                doi_norm = _normalize_doi(_safe_str(row.get("doi_yaml")))
                if doi_norm and doi_norm in doi_to_id:
                    mapped_id = str(doi_to_id[doi_norm])
                    method = "doi"
            mapped_ids.append(mapped_id)
            map_methods.append(method)
        t4_df["mapped_canonical_paper_id"] = mapped_ids
        t4_df["map_method"] = map_methods
        t4_df["mapped_to_scored"] = t4_df["mapped_canonical_paper_id"].astype(str).str.strip() != ""
        t4_df["in_selected"] = t4_df["mapped_canonical_paper_id"].astype(str).isin(selected_ids)
        t4_df["in_tracked"] = t4_df["mapped_canonical_paper_id"].astype(str).isin(tracked_ids)
        t4_df["on_hold"] = t4_df["mapped_canonical_paper_id"].astype(str).isin(hold_ids)

        tracked_meta = tracked.rename(columns={"canonical_paper_id": "mapped_canonical_paper_id"})[
            ["mapped_canonical_paper_id", "t4_id", "core_selection_tier", "tracked_source"]
        ].copy()
        t4_df = t4_df.merge(tracked_meta, on=["mapped_canonical_paper_id", "t4_id"], how="left")

        def _selection_status(row: pd.Series) -> str:
            if not _boolish(row.get("include_in_graph", True)):
                return "excluded_note_only"
            if _boolish(row.get("on_hold", False)):
                return "held_missing_abstract"
            if _boolish(row.get("in_tracked", False)):
                return "in_tracked"
            if _boolish(row.get("mapped_to_scored", False)):
                return "mapped_not_tracked"
            return "not_mapped"

        t4_df["selection_status"] = t4_df.apply(_selection_status, axis=1)
        t4_df["review_decision"] = ""
        t4_df["replacement_doi"] = ""
        t4_df["provided_abstract"] = ""
        t4_df["review_notes"] = ""

        t4_sheet_cols = [
            "t4_id",
            "t4_concept",
            "title",
            "year",
            "journal",
            "topic_codes",
            "include_in_graph",
            "selection_status",
            "corpus_status_yaml",
            "mapped_to_scored",
            "map_method",
            "mapped_canonical_paper_id",
            "in_selected",
            "in_tracked",
            "on_hold",
            "core_selection_tier",
            "tracked_source",
            "doi_yaml",
            "corpus_id_yaml",
            "exclusion_note",
            "relevance",
            "review_decision",
            "replacement_doi",
            "provided_abstract",
            "review_notes",
        ]
        for col in t4_sheet_cols:
            if col not in t4_df.columns:
                t4_df[col] = ""
        t4_sheet = t4_df[t4_sheet_cols].copy()
        t4_sheet = t4_sheet.sort_values(["selection_status", "t4_concept", "t4_id"], na_position="last").reset_index(drop=True)

    t4_latest = review_dir / "t4_nomination_status.csv"
    t4_stamp = review_dir / f"t4_nomination_status_{timestamp_slug}.csv"
    t4_sheet.to_csv(t4_latest, index=False)
    t4_sheet.to_csv(t4_stamp, index=False)

    return {
        "review_dir": str(review_dir),
        "t4_rows": int(len(t4_sheet)),
        "held_rows": int(len(hold_sheet)),
        "topic16_held_rows": int(len(topic16_sheet)),
        "t4_latest_csv": str(t4_latest),
        "t4_snapshot_csv": str(t4_stamp),
        "held_latest_csv": str(hold_latest),
        "held_snapshot_csv": str(hold_stamp),
        "topic16_latest_csv": str(topic16_latest),
        "topic16_snapshot_csv": str(topic16_stamp),
    }


# ---------------------------------------------------------------------------
# Per-topic / per-cluster builders
# ---------------------------------------------------------------------------


def _build_topic_brief(
    topic_id: str,
    label: str,
    papers: pd.DataFrame,
    summaries: pd.DataFrame,
    target_min_n: int | None = None,
    layer: str = "",
) -> dict[str, Any]:
    """Build one QA/QC topic brief keyed to authoritative topic-code assignment."""
    yr_min, yr_max = _year_span(papers)
    top_venues = _top_venues(papers, k=5)

    low_conf = 0
    if not summaries.empty and not papers.empty:
        topic_ids = set(papers["canonical_paper_id"].astype(str))
        topic_sums = summaries[summaries["canonical_paper_id"].astype(str).isin(topic_ids)]
        low_conf = int(
            (topic_sums.get("summary_certainty_label", pd.Series()).astype(str).str.lower() == "low").sum()
        )

    recent_cut = 2020
    if "year" in papers.columns:
        n_recent = int((pd.to_numeric(papers["year"], errors="coerce") >= recent_cut).sum())
    else:
        n_recent = 0

    flags: list[str] = []
    if papers.empty:
        flags.append("No papers mapped to this topic in the final corpus.")
    elif target_min_n is not None and len(papers) < target_min_n:
        flags.append(f"Coverage below topic target ({len(papers)} < target minimum {target_min_n}).")

    if n_recent < 3 and len(papers) > 0:
        flags.append(f"Only {n_recent} paper(s) from {recent_cut}+ — consider adding recent literature.")
    if low_conf > 0:
        flags.append(f"{low_conf} paper(s) have low-confidence AI summaries — recommend manual review.")

    return {
        "topic_id": topic_id,
        "label": label,
        "layer": layer,
        "target_min_n": target_min_n,
        "n_papers": len(papers),
        "year_span": [yr_min, yr_max],
        "n_recent": n_recent,
        "top_venues": [{"venue": v, "count": c} for v, c in top_venues],
        "top_papers": _top_papers(papers, k=10),
        "low_conf_summaries": low_conf,
        "flags": flags,
    }


def _build_cluster_lens(
    corpus: pd.DataFrame,
    paper_to_cluster: dict[str, str],
    cluster_labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Summarise algorithmic clusters as informational context."""
    if corpus.empty:
        return []

    cluster_df = corpus[["canonical_paper_id", "primary_topic_code"]].copy()
    cluster_df["canonical_paper_id"] = cluster_df["canonical_paper_id"].astype(str)
    cluster_df["cluster_id"] = cluster_df["canonical_paper_id"].map(paper_to_cluster).fillna("unmapped")
    cluster_df["primary_topic_code"] = cluster_df["primary_topic_code"].fillna("UNMAPPED").astype(str)

    out: list[dict[str, Any]] = []
    for cluster_id, group in cluster_df.groupby("cluster_id"):
        topic_counts = (
            group["primary_topic_code"].value_counts().head(3).to_dict()
            if "primary_topic_code" in group.columns
            else {}
        )
        out.append(
            {
                "cluster_id": str(cluster_id),
                "label": cluster_labels.get(str(cluster_id), f"Cluster {cluster_id}"),
                "n_papers": int(len(group)),
                "top_topic_codes": {str(k): int(v) for k, v in topic_counts.items()},
            }
        )

    def _cluster_sort_key(item: dict[str, Any]) -> tuple[int, str]:
        cid = item["cluster_id"]
        if cid.isdigit():
            return (0, f"{int(cid):04d}")
        return (1, cid)

    return sorted(out, key=_cluster_sort_key)


def _build_cluster_topic_alignment(
    corpus: pd.DataFrame,
    paper_to_cluster: dict[str, str],
) -> dict[str, Any]:
    """Measure how algorithmic clusters align with authoritative TOPIC codes."""
    if corpus.empty:
        return {
            "n_papers_scored": 0,
            "n_clusters": 0,
            "n_topics": 0,
            "cluster_purity_weighted": 0.0,
            "topic_representation_weighted": 0.0,
            "fidelity_harmonic_mean": 0.0,
            "cluster_to_topic": [],
            "topic_to_cluster": [],
        }

    df = corpus[["canonical_paper_id", "primary_topic_code"]].copy()
    df["canonical_paper_id"] = df["canonical_paper_id"].astype(str)
    df["cluster_id"] = df["canonical_paper_id"].map(paper_to_cluster).fillna("unmapped")
    df["primary_topic_code"] = df["primary_topic_code"].fillna("UNMAPPED").astype(str)

    # Focus alignment metrics on authoritative TOPIC-## assignments.
    df = df[df["primary_topic_code"].str.match(r"^TOPIC-\d{2}$", na=False)].copy()
    if df.empty:
        return {
            "n_papers_scored": 0,
            "n_clusters": 0,
            "n_topics": 0,
            "cluster_purity_weighted": 0.0,
            "topic_representation_weighted": 0.0,
            "fidelity_harmonic_mean": 0.0,
            "cluster_to_topic": [],
            "topic_to_cluster": [],
        }

    contingency = pd.crosstab(df["cluster_id"], df["primary_topic_code"])
    cluster_totals = contingency.sum(axis=1)
    topic_totals = contingency.sum(axis=0)
    n_total = int(cluster_totals.sum())

    cluster_rows: list[dict[str, Any]] = []
    for cluster_id in contingency.index:
        row = contingency.loc[cluster_id]
        dominant_topic = str(row.idxmax())
        dominant_count = int(row.max())
        cluster_n = int(cluster_totals.loc[cluster_id])
        purity = float(dominant_count / cluster_n) if cluster_n > 0 else 0.0
        topic_total = int(topic_totals.get(dominant_topic, 0))
        topic_rep = float(dominant_count / topic_total) if topic_total > 0 else 0.0
        cluster_rows.append(
            {
                "cluster_id": str(cluster_id),
                "cluster_n_papers": cluster_n,
                "dominant_topic_code": dominant_topic,
                "dominant_topic_count": dominant_count,
                "cluster_purity": round(purity, 4),
                "topic_representation": round(topic_rep, 4),
            }
        )

    topic_rows: list[dict[str, Any]] = []
    for topic_code in contingency.columns:
        col = contingency[topic_code]
        dominant_cluster = str(col.idxmax())
        dominant_count = int(col.max())
        topic_n = int(topic_totals.loc[topic_code])
        rep = float(dominant_count / topic_n) if topic_n > 0 else 0.0
        cluster_n = int(cluster_totals.get(dominant_cluster, 0))
        purity = float(dominant_count / cluster_n) if cluster_n > 0 else 0.0
        topic_rows.append(
            {
                "topic_code": str(topic_code),
                "topic_n_papers": topic_n,
                "dominant_cluster_id": dominant_cluster,
                "dominant_cluster_count": dominant_count,
                "topic_representation": round(rep, 4),
                "cluster_purity": round(purity, 4),
            }
        )

    cluster_purity_weighted = float(sum(contingency.max(axis=1)) / n_total) if n_total > 0 else 0.0
    topic_rep_weighted = float(sum(contingency.max(axis=0)) / n_total) if n_total > 0 else 0.0
    if cluster_purity_weighted + topic_rep_weighted > 0:
        fidelity_hmean = 2.0 * cluster_purity_weighted * topic_rep_weighted / (
            cluster_purity_weighted + topic_rep_weighted
        )
    else:
        fidelity_hmean = 0.0

    def _cluster_sort_key(row: dict[str, Any]) -> tuple[int, str]:
        cid = row["cluster_id"]
        if cid.isdigit():
            return (0, f"{int(cid):04d}")
        return (1, cid)

    return {
        "n_papers_scored": n_total,
        "n_clusters": int(len(contingency.index)),
        "n_topics": int(len(contingency.columns)),
        "cluster_purity_weighted": round(cluster_purity_weighted, 4),
        "topic_representation_weighted": round(topic_rep_weighted, 4),
        "fidelity_harmonic_mean": round(fidelity_hmean, 4),
        "cluster_to_topic": sorted(cluster_rows, key=_cluster_sort_key),
        "topic_to_cluster": sorted(topic_rows, key=lambda r: r["topic_code"]),
    }


# ---------------------------------------------------------------------------
# Executive summary builders
# ---------------------------------------------------------------------------


def _build_executive_summary(
    corpus: pd.DataFrame,
    audit_report: dict[str, Any],
    topic_briefs: list[dict[str, Any]],
    n_topics_expected: int,
    n_topics_with_papers: int,
    n_clusters_observed: int,
    cluster_topic_alignment: dict[str, Any],
) -> dict[str, Any]:
    """Summarise the corpus for the top-level QA/QC section."""
    n_total = len(corpus)

    tier_counts: Counter = Counter()
    for _, row in corpus.iterrows():
        tier_counts[_tier_label(row)] += 1

    yr_min, yr_max = _year_span(corpus)
    top_corpus_venues = _top_venues(corpus, k=8)
    flagged_topics = [b["topic_id"] for b in topic_briefs if b["flags"]]

    gm = audit_report.get("gate_metrics", {})
    return {
        "n_papers": n_total,
        "tier_breakdown": dict(tier_counts),
        "year_range": [yr_min, yr_max],
        "top_venues": [{"venue": v, "count": c} for v, c in top_corpus_venues],
        "ms_focus_pct": round(_safe_float(gm.get("ms_focus_pct")), 2),
        "missing_abstract_pct": round(_safe_float(gm.get("missing_abstract_pct")), 2),
        "category_entropy_normalized": round(_safe_float(audit_report.get("category_entropy_normalized")), 4),
        "audit_passed": bool(audit_report.get("passed", False)),
        "n_audit_errors": len(audit_report.get("errors", [])),
        "n_audit_warnings": len(audit_report.get("warnings", [])),
        "n_topics_expected": int(n_topics_expected),
        "n_topics_with_papers": int(n_topics_with_papers),
        "n_clusters_observed": int(n_clusters_observed),
        "cluster_purity_weighted": round(_safe_float(cluster_topic_alignment.get("cluster_purity_weighted")), 4),
        "topic_representation_weighted": round(
            _safe_float(cluster_topic_alignment.get("topic_representation_weighted")), 4
        ),
        "cluster_topic_fidelity": round(_safe_float(cluster_topic_alignment.get("fidelity_harmonic_mean")), 4),
        "flagged_topics": flagged_topics,
    }


def _build_expert_comms_summary(
    root: Path,
    out_dir: Path,
    exec_summary: dict[str, Any],
    topic_briefs: list[dict[str, Any]],
    audit_report: dict[str, Any],
    summaries: pd.DataFrame,
) -> dict[str, Any]:
    """Build site-readiness signals for the expert comms pass."""
    assets = {
        "explorer_graph": root / "site" / "public" / "assets" / "explorer_graph.json",
        "research_map_graph": root / "site" / "public" / "assets" / "research_map_graph.json",
        "learning_spine_graph": root / "site" / "public" / "assets" / "learning_spine_graph.json",
        "explorer_js": root / "site" / "public" / "javascripts" / "explorer.js",
        "graph_renderer_js": root / "site" / "public" / "javascripts" / "mskb_graph_renderer.js",
        "kg_nodes_csv": out_dir / "kg" / "kg_nodes.csv",
        "kg_edges_csv": out_dir / "kg" / "kg_edges.csv",
    }
    asset_status = {name: path.exists() for name, path in assets.items()}

    low_conf = 0
    total_summaries = 0
    if not summaries.empty:
        total_summaries = int(len(summaries))
        low_conf = int(
            (summaries.get("summary_certainty_label", pd.Series()).astype(str).str.lower() == "low").sum()
        )

    topics_with_no_papers = [
        brief["topic_id"]
        for brief in topic_briefs
        if str(brief["topic_id"]).startswith("TOPIC-") and int(brief.get("n_papers", 0)) == 0
    ]

    thin_topics = [
        brief["topic_id"]
        for brief in topic_briefs
        if str(brief["topic_id"]).startswith("TOPIC-")
        and brief.get("target_min_n") is not None
        and int(brief.get("n_papers", 0)) > 0
        and int(brief.get("n_papers", 0)) < int(brief.get("target_min_n"))
    ]

    return {
        "qa_gate_passed": bool(exec_summary.get("audit_passed", False)),
        "qa_errors": list(audit_report.get("errors", [])),
        "qa_warnings": list(audit_report.get("warnings", [])),
        "n_topics_expected": int(exec_summary.get("n_topics_expected", 0)),
        "n_topics_with_papers": int(exec_summary.get("n_topics_with_papers", 0)),
        "topics_with_no_papers": topics_with_no_papers,
        "thin_topics": thin_topics,
        "summary_low_conf_count": low_conf,
        "summary_total_count": total_summaries,
        "summary_low_conf_pct": round((100.0 * low_conf / total_summaries), 2) if total_summaries > 0 else 0.0,
        "site_asset_status": asset_status,
        "missing_assets": sorted([name for name, ok in asset_status.items() if not ok]),
    }


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------


def _render_topic_brief_md(brief: dict[str, Any]) -> str:
    """Render one topic brief as Markdown."""
    lines: list[str] = []
    yr = brief.get("year_span", [None, None])
    yr_str = f"{yr[0]}–{yr[1]}" if yr[0] else "n/a"

    label = brief["label"]
    topic_id = brief["topic_id"]
    layer = _safe_str(brief.get("layer"))
    lines.append(f"## {topic_id} — {label}")
    lines.append("")
    layer_part = f" | Layer: {layer}" if layer else ""
    target_min = brief.get("target_min_n")
    target_part = f" | Target min: {target_min}" if target_min is not None else ""
    lines.append(
        f"**{brief['n_papers']} papers** | "
        f"Year span: {yr_str} | "
        f"Recent (≥2020): {brief.get('n_recent', 0)}"
        f"{layer_part}{target_part}"
    )
    lines.append("")

    if brief.get("top_venues"):
        lines.append("**Top venues:**")
        for entry in brief["top_venues"][:5]:
            lines.append(f"- {entry['venue']} ({entry['count']})")
        lines.append("")

    if brief.get("top_papers"):
        lines.append("**Top papers by importance:**")
        lines.append("")
        lines.append("| # | Title | Year | Venue | Citations | Tier |")
        lines.append("|---|-------|------|-------|-----------|------|")
        for i, p in enumerate(brief["top_papers"], 1):
            title = p["title"][:80] + ("…" if len(p["title"]) > 80 else "")
            venue = p["venue"][:40] + ("…" if len(p["venue"]) > 40 else "")
            doi_link = f"[DOI](https://doi.org/{p['doi']})" if p.get("doi") else "—"
            lines.append(
                f"| {i} | {title} {doi_link} | {p['year'] or '—'} | {venue or '—'} | "
                f"{p['citations']} | {p['tier']} |"
            )
        lines.append("")

    if brief.get("flags"):
        lines.append("**Reviewer flags:**")
        for flag in brief["flags"]:
            lines.append(f"- {flag}")
        lines.append("")

    return "\n".join(lines)


def _render_qa_report_md(
    exec_summary: dict[str, Any],
    topic_briefs: list[dict[str, Any]],
    cluster_lens: list[dict[str, Any]],
    cluster_topic_alignment: dict[str, Any],
    audit_report: dict[str, Any],
    generated_at: str,
    run_date_utc: str,
) -> str:
    """Render the complete QA/QC report as Markdown."""
    lines: list[str] = []
    lines.append("# MS Knowledge Base — QA/QC Report (v1.3)")
    lines.append("")
    lines.append(f"_Run date (UTC): {run_date_utc} | Generated: {generated_at}_")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    es = exec_summary
    gate_badge = "**PASS**" if es["audit_passed"] else "**FAIL**"
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Final corpus size | {es['n_papers']} papers |")
    lines.append(f"| Tier breakdown | {es['tier_breakdown']} |")
    yr = es.get("year_range", [None, None])
    lines.append(f"| Year range | {yr[0]}–{yr[1]} |")
    lines.append(f"| MS focus rate | {es['ms_focus_pct']}% |")
    lines.append(f"| Missing abstract rate | {es['missing_abstract_pct']}% |")
    lines.append(f"| Category diversity (entropy) | {es['category_entropy_normalized']} |")
    lines.append(f"| QA gate status | {gate_badge} ({es['n_audit_errors']} errors, {es['n_audit_warnings']} warnings) |")
    lines.append(f"| Topic coverage (authoritative) | {es['n_topics_with_papers']} / {es['n_topics_expected']} TOPIC codes with papers |")
    lines.append(f"| Cluster lens (informational) | {es['n_clusters_observed']} observed clusters in final corpus |")
    lines.append(f"| Cluster purity (weighted) | {es['cluster_purity_weighted']} |")
    lines.append(f"| Topic representation (weighted) | {es['topic_representation_weighted']} |")
    lines.append(f"| Cluster↔Topic fidelity (harmonic mean) | {es['cluster_topic_fidelity']} |")
    lines.append("")

    lines.append("**Inline Commentary:**")
    lines.append(
        f"- `QA gate status` is the pass/fail from `audit_kb`; this run is "
        f"{'passing' if es['audit_passed'] else 'failing'} "
        f"with {es['n_audit_errors']} error(s) and {es['n_audit_warnings']} warning(s)."
    )
    lines.append(
        f"- `Topic coverage` shows authoritative taxonomy coverage: "
        f"{es['n_topics_with_papers']}/{es['n_topics_expected']} TOPIC codes currently have at least one paper."
    )
    lines.append(
        f"- `Cluster purity` ({es['cluster_purity_weighted']}) asks: \"if I pick a cluster, "
        "how often are papers in its dominant TOPIC?\" "
        "Higher means clusters are more single-topic."
    )
    lines.append(
        f"- `Topic representation` ({es['topic_representation_weighted']}) asks: \"if I pick a TOPIC, "
        "how much of it sits in one dominant cluster?\" "
        "Higher means each TOPIC is less fragmented across clusters."
    )
    lines.append(
        f"- `Cluster↔Topic fidelity` ({es['cluster_topic_fidelity']}) is the harmonic mean of purity+representation; "
        "it is high only when both are high."
    )
    lines.append("")

    if es.get("top_venues"):
        lines.append("**Top venues across corpus:**")
        for entry in es["top_venues"]:
            lines.append(f"- {entry['venue']} ({entry['count']} papers)")
        lines.append("")

    if es.get("flagged_topics"):
        lines.append("**TOPIC codes requiring attention:**")
        for t in es["flagged_topics"]:
            lines.append(f"- {t}")
        lines.append("")

    lines.append("## QA / QC Digest")
    lines.append("")
    errors = audit_report.get("errors", [])
    warnings = audit_report.get("warnings", [])
    if errors:
        lines.append("### Gate Failures")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")
    if warnings:
        lines.append("### Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    if not errors and not warnings:
        lines.append("All gates passed. No warnings recorded.")
        lines.append("")

    lines.append("## Per-TOPIC QA Briefs")
    lines.append("")
    lines.append(
        "Each section is keyed to `primary_topic_code` (TOPIC-00..TOPIC-17), "
        "which is the authoritative topic assignment used for corpus balance and QA gates."
    )
    lines.append("")
    for brief in topic_briefs:
        lines.append(_render_topic_brief_md(brief))

    lines.append("## Cluster Lens (Informational Only)")
    lines.append("")
    lines.append(
        "Clusters are algorithmic citation communities and are useful for structure discovery, "
        "but they are not the authoritative topic taxonomy for QA decisions."
    )
    lines.append("")
    lines.append("| Cluster ID | Label | Papers | Top mapped TOPIC codes |")
    lines.append("|------------|-------|--------|------------------------|")
    for row in cluster_lens:
        top_codes = row.get("top_topic_codes", {})
        top_codes_text = ", ".join(f"{k}:{v}" for k, v in top_codes.items()) if top_codes else "—"
        lines.append(f"| {row['cluster_id']} | {row['label']} | {row['n_papers']} | {top_codes_text} |")
    lines.append("")

    lines.append("## Cluster↔Topic Alignment")
    lines.append("")
    lines.append(
        "Alignment uses authoritative `TOPIC-##` labels only. "
        "`cluster_purity` answers \"how single-topic is this cluster?\" and "
        "`topic_representation` answers \"how concentrated is this topic in one cluster?\"."
    )
    lines.append("")
    lines.append(
        f"Overall: purity={cluster_topic_alignment.get('cluster_purity_weighted', 0.0)}, "
        f"representation={cluster_topic_alignment.get('topic_representation_weighted', 0.0)}, "
        f"fidelity={cluster_topic_alignment.get('fidelity_harmonic_mean', 0.0)}"
    )
    lines.append("")
    lines.append(
        "Inline interpretation guide: `>=0.70` strong alignment, `0.50–0.69` moderate, `<0.50` weak."
    )
    lines.append("")

    lines.append("### Cluster → Dominant Topic")
    lines.append("")
    lines.append("| Cluster | Papers | Dominant TOPIC | Purity | Topic representation | Commentary |")
    lines.append("|---------|--------|----------------|--------|----------------------|------------|")
    for row in cluster_topic_alignment.get("cluster_to_topic", []):
        purity = _safe_float(row.get("cluster_purity"))
        topic_rep = _safe_float(row.get("topic_representation"))
        if purity >= 0.7:
            comment = "High-purity cluster (mostly one TOPIC)."
        elif purity >= 0.5:
            comment = "Moderate purity."
        else:
            comment = "Mixed cluster across multiple TOPIC codes."
        if topic_rep < 0.5:
            comment += " Dominant TOPIC is split across clusters."
        lines.append(
            f"| {row['cluster_id']} | {row['cluster_n_papers']} | {row['dominant_topic_code']} | "
            f"{row['cluster_purity']} | {row['topic_representation']} | {comment} |"
        )
    lines.append("")

    lines.append("### TOPIC → Dominant Cluster")
    lines.append("")
    lines.append("| TOPIC | Papers | Dominant cluster | Representation | Cluster purity | Commentary |")
    lines.append("|-------|--------|------------------|----------------|----------------|------------|")
    for row in cluster_topic_alignment.get("topic_to_cluster", []):
        topic_rep = _safe_float(row.get("topic_representation"))
        cluster_purity = _safe_float(row.get("cluster_purity"))
        if topic_rep >= 0.7:
            comment = "TOPIC is concentrated in one cluster."
        elif topic_rep >= 0.5:
            comment = "TOPIC is moderately concentrated."
        else:
            comment = "TOPIC is fragmented across clusters."
        if cluster_purity < 0.5:
            comment += " Dominant cluster is itself mixed."
        lines.append(
            f"| {row['topic_code']} | {row['topic_n_papers']} | {row['dominant_cluster_id']} | "
            f"{row['topic_representation']} | {row['cluster_purity']} | {comment} |"
        )
    lines.append("")

    return "\n".join(lines)


def _render_expert_comms_md(
    summary: dict[str, Any],
    generated_at: str,
    run_date_utc: str,
) -> str:
    """Render site-facing expert comms pass."""
    lines: list[str] = []
    lines.append("# MS Knowledge Base — Expert Comms Pass (Site Readiness)")
    lines.append("")
    lines.append(f"_Run date (UTC): {run_date_utc} | Generated: {generated_at}_")
    lines.append("")

    qa_status = "PASS" if summary.get("qa_gate_passed") else "FAIL"
    lines.append("## Snapshot")
    lines.append("")
    lines.append("| Signal | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| QA gate status | {qa_status} |")
    lines.append(f"| QA errors | {len(summary.get('qa_errors', []))} |")
    lines.append(f"| QA warnings | {len(summary.get('qa_warnings', []))} |")
    lines.append(
        f"| Topic coverage | {summary.get('n_topics_with_papers', 0)} / {summary.get('n_topics_expected', 0)} with papers |"
    )
    lines.append(
        f"| Low-confidence summaries | {summary.get('summary_low_conf_count', 0)} / {summary.get('summary_total_count', 0)} "
        f"({summary.get('summary_low_conf_pct', 0.0)}%) |"
    )
    lines.append(
        f"| Missing required site assets | {len(summary.get('missing_assets', []))} |"
    )
    lines.append("")

    lines.append("## Site Asset Status")
    lines.append("")
    for asset, ok in summary.get("site_asset_status", {}).items():
        lines.append(f"- {'OK' if ok else 'MISSING'}: `{asset}`")
    lines.append("")

    lines.append("## Error and Risk Digest")
    lines.append("")
    if summary.get("qa_errors"):
        lines.append("**QA errors:**")
        for err in summary["qa_errors"]:
            lines.append(f"- {err}")
        lines.append("")
    if summary.get("qa_warnings"):
        lines.append("**QA warnings:**")
        for warn in summary["qa_warnings"]:
            lines.append(f"- {warn}")
        lines.append("")
    if summary.get("topics_with_no_papers"):
        lines.append("**TOPIC codes with zero papers:**")
        for code in summary["topics_with_no_papers"]:
            lines.append(f"- {code}")
        lines.append("")
    if summary.get("thin_topics"):
        lines.append("**TOPIC codes below target minimum:**")
        for code in summary["thin_topics"]:
            lines.append(f"- {code}")
        lines.append("")
    if summary.get("missing_assets"):
        lines.append("**Missing site assets:**")
        for asset in summary["missing_assets"]:
            lines.append(f"- {asset}")
        lines.append("")
    if (
        not summary.get("qa_errors")
        and not summary.get("qa_warnings")
        and not summary.get("topics_with_no_papers")
        and not summary.get("thin_topics")
        and not summary.get("missing_assets")
    ):
        lines.append("No blocking risks surfaced by automated checks.")
        lines.append("")

    lines.append("## Manual Comms Checklist")
    lines.append("")
    lines.append("- Desktop + mobile look/feel pass on home, explorer, journey, and topic pages.")
    lines.append("- Engagement pass: verify narrative flow, clarity of call-to-action links, and skim readability.")
    lines.append("- Error pass: browser console/network checks on key graph pages and search interactions.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(config_path: str) -> None:
    """Generate QA/QC + expert-comms packets and write to outputs/expert_comms/."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    out_dir = root / cfg["output_dir"]
    comms_dir = out_dir / "expert_comms"
    ensure_dir(comms_dir)

    audit_path = out_dir / "audit" / "kb_audit_report.json"
    if not audit_path.exists():
        raise FileNotFoundError(
            f"Audit report not found: {audit_path}. Run stage 9 (audit_kb) first."
        )
    with open(audit_path, encoding="utf-8") as f:
        audit_report: dict[str, Any] = json.load(f)

    corpus, _source_path = load_downstream_corpus(out_dir / "graph")
    if corpus.empty:
        raise RuntimeError("No papers in final corpus — cannot generate QA/QC and expert comms reports.")
    corpus["canonical_paper_id"] = corpus["canonical_paper_id"].astype(str)

    if "primary_topic_code" not in corpus.columns:
        evidence_path = out_dir / "topics" / "paper_topic_evidence.csv"
        if evidence_path.exists():
            evidence = pd.read_csv(evidence_path, usecols=["canonical_paper_id", "primary_topic_code"])
            evidence["canonical_paper_id"] = evidence["canonical_paper_id"].astype(str)
            corpus = corpus.merge(evidence, on="canonical_paper_id", how="left")
        else:
            corpus["primary_topic_code"] = "UNMAPPED"

    corpus["primary_topic_code"] = (
        corpus.get("primary_topic_code", pd.Series("UNMAPPED", index=corpus.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "UNMAPPED")
    )

    summaries_path = out_dir / "distilled" / "paper_summaries.csv"
    summaries = pd.DataFrame()
    if summaries_path.exists():
        summaries = pd.read_csv(summaries_path, low_memory=False)
        summaries["canonical_paper_id"] = summaries["canonical_paper_id"].astype(str)

    topic_codes, topic_names, topic_layers, topic_target_min = _load_topic_map(root / "data" / "topic_map.json")

    topic_briefs: list[dict[str, Any]] = []
    for topic_code in topic_codes:
        topic_papers = corpus[corpus["primary_topic_code"] == topic_code].copy()
        topic_briefs.append(
            _build_topic_brief(
                topic_code,
                topic_names.get(topic_code, topic_code),
                topic_papers,
                summaries,
                target_min_n=topic_target_min.get(topic_code),
                layer=topic_layers.get(topic_code, ""),
            )
        )

    extras = sorted(set(corpus["primary_topic_code"].astype(str)) - set(topic_codes))
    for code in extras:
        topic_papers = corpus[corpus["primary_topic_code"] == code].copy()
        topic_briefs.append(
            _build_topic_brief(
                code,
                topic_names.get(code, code),
                topic_papers,
                summaries,
                target_min_n=None,
                layer=topic_layers.get(code, ""),
            )
        )

    paper_to_cluster, cluster_labels = _load_cluster_data(out_dir)
    cluster_lens = _build_cluster_lens(corpus, paper_to_cluster, cluster_labels)
    cluster_topic_alignment = _build_cluster_topic_alignment(corpus, paper_to_cluster)

    n_topics_with_papers = sum(
        1
        for brief in topic_briefs
        if str(brief["topic_id"]).startswith("TOPIC-") and int(brief.get("n_papers", 0)) > 0
    )
    exec_summary = _build_executive_summary(
        corpus,
        audit_report,
        topic_briefs,
        n_topics_expected=len(topic_codes),
        n_topics_with_papers=n_topics_with_papers,
        n_clusters_observed=len(cluster_lens),
        cluster_topic_alignment=cluster_topic_alignment,
    )

    generated_dt = datetime.now(timezone.utc)
    generated_at = generated_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_date_utc = generated_at[:10]
    timestamp_slug = _timestamp_slug(generated_dt)

    qa_payload: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "run_date_utc": run_date_utc,
        "run_timestamp_utc": generated_at,
        "snapshot_id_utc": timestamp_slug,
        "executive_summary": exec_summary,
        "topic_briefs": topic_briefs,
        "cluster_lens": cluster_lens,
        "cluster_topic_alignment": cluster_topic_alignment,
        "audit_report": audit_report,
    }
    qa_md = _render_qa_report_md(
        exec_summary,
        topic_briefs,
        cluster_lens,
        cluster_topic_alignment,
        audit_report,
        generated_at,
        run_date_utc,
    )

    expert_summary = _build_expert_comms_summary(
        root=root,
        out_dir=out_dir,
        exec_summary=exec_summary,
        topic_briefs=topic_briefs,
        audit_report=audit_report,
        summaries=summaries,
    )
    expert_payload: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "run_date_utc": run_date_utc,
        "run_timestamp_utc": generated_at,
        "snapshot_id_utc": timestamp_slug,
        "summary": expert_summary,
    }
    expert_md = _render_expert_comms_md(expert_summary, generated_at, run_date_utc)

    # Stable latest filenames
    qa_json_path = comms_dir / "qa_qc_report.json"
    qa_md_path = comms_dir / "qa_qc_report.md"
    expert_json_path = comms_dir / "expert_comms_report.json"
    expert_md_path = comms_dir / "expert_comms_report.md"

    save_json(qa_payload, qa_json_path)
    qa_md_path.write_text(qa_md, encoding="utf-8")
    save_json(expert_payload, expert_json_path)
    expert_md_path.write_text(expert_md, encoding="utf-8")

    # Timestamped snapshots (immutable per run)
    save_json(qa_payload, comms_dir / f"qa_qc_report_{timestamp_slug}.json")
    (comms_dir / f"qa_qc_report_{timestamp_slug}.md").write_text(qa_md, encoding="utf-8")
    save_json(expert_payload, comms_dir / f"expert_comms_report_{timestamp_slug}.json")
    (comms_dir / f"expert_comms_report_{timestamp_slug}.md").write_text(expert_md, encoding="utf-8")
    review_artifacts = _build_review_sheets(root=root, out_dir=out_dir, timestamp_slug=timestamp_slug)

    gate = "PASS" if exec_summary["audit_passed"] else "FAIL"
    print(
        f"Reports written to {comms_dir} "
        f"| Corpus: {exec_summary['n_papers']} papers "
        f"| Topic coverage: {exec_summary['n_topics_with_papers']}/{exec_summary['n_topics_expected']} "
        f"| Clusters observed: {exec_summary['n_clusters_observed']} "
        f"| QA: {gate} "
        f"| Snapshot ID: {timestamp_slug} "
        f"| Review sheets: t4={review_artifacts['t4_rows']}, held={review_artifacts['held_rows']}, "
        f"topic16_held={review_artifacts['topic16_held_rows']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()
    run(args.config)
