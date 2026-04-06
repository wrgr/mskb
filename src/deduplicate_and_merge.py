
import argparse
from collections import defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from .utils import ensure_dir, load_config, normalize_name, normalize_title, stable_hash


def _title_sim(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(normalize_title(a), normalize_title(b)) / 100.0


def _canonical_paper_id(row: pd.Series) -> str:
    if row.get("doi"):
        return stable_hash("doi", str(row["doi"]).lower())
    return stable_hash("title", normalize_title(str(row.get("title", ""))), str(row.get("year", "")))


def _venue_flags(venue: str) -> dict:
    venue = (venue or "").lower()
    return {
        "is_preprint": int("biorxiv" in venue or "arxiv" in venue or "medrxiv" in venue),
        "is_journal": int(venue not in {"", "biorxiv", "arxiv", "medrxiv"}),
    }


def _clean_author_name(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    raw = root / cfg["output_dir"] / "raw"
    outdir = root / cfg["output_dir"] / "normalized"
    ensure_dir(outdir)

    cand = pd.read_csv(raw / "candidate_papers.csv")
    if cand.empty:
        raise ValueError("candidate_papers.csv is empty")

    cand["norm_title"] = cand["title"].fillna("").map(normalize_title)
    cand["norm_first_author"] = cand["first_author"].fillna("").map(normalize_name)
    cand["canonical_paper_id"] = cand.apply(_canonical_paper_id, axis=1)

    merged = []
    used = set()
    merged_paper_ids = {}

    rows = cand.to_dict("records")
    doi_groups = defaultdict(list)
    author_groups = defaultdict(list)
    for idx, row in enumerate(rows):
        doi = str(row.get("doi", "") or "").strip().lower()
        if doi:
            doi_groups[doi].append(idx)
        author = str(row.get("norm_first_author", "") or "").strip()
        if author:
            author_groups[author].append(idx)

    for i, row in enumerate(rows):
        if i in used:
            continue
        cluster = [i]
        candidate_js = set()
        doi = str(row.get("doi", "") or "").strip().lower()
        if doi:
            candidate_js.update(doi_groups[doi])
        author = str(row.get("norm_first_author", "") or "").strip()
        if author:
            year_i = row.get("year")
            for j in author_groups[author]:
                if j <= i:
                    continue
                year_j = rows[j].get("year")
                if pd.isna(year_i) or pd.isna(year_j) or abs(float(year_i) - float(year_j)) <= 6:
                    candidate_js.add(j)

        for j in sorted(candidate_js):
            if j in used:
                continue
            other = rows[j]
            same_doi = bool(row.get("doi")) and str(row.get("doi")).lower() == str(other.get("doi")).lower()
            sim = _title_sim(row.get("title", ""), other.get("title", ""))
            same_author = row.get("norm_first_author") and row.get("norm_first_author") == other.get("norm_first_author")
            year_i = row.get("year")
            year_j = other.get("year")
            year_penalty_ok = (pd.isna(year_i) or pd.isna(year_j) or abs(float(year_i) - float(year_j)) <= 6)
            if same_doi or (sim >= cfg["dedup"]["auto_merge_threshold"] and same_author and year_penalty_ok):
                cluster.append(j)
                used.add(j)
        used.add(i)
        cluster_rows = [rows[k] for k in cluster]
        cluster_df = pd.DataFrame(cluster_rows)
        cluster_df["is_preprint"] = cluster_df["venue"].fillna("").str.lower().str.contains("biorxiv|arxiv|medrxiv")
        cluster_df = cluster_df.sort_values(by=["is_preprint", "cited_by_count"], ascending=[True, False])
        rep = cluster_df.iloc[0].to_dict()
        rep["canonical_paper_id"] = stable_hash("canonical", rep.get("doi", "") or rep.get("norm_title", ""), str(rep.get("year", "")))
        rep["all_dois"] = ";".join(sorted({str(x) for x in cluster_df["doi"].fillna("") if str(x).strip()}))
        rep["all_openalex_ids"] = ";".join(sorted({str(x) for x in cluster_df["openalex_id"].fillna("") if str(x).strip()}))
        rep["all_channels"] = ";".join(sorted({str(x) for x in cluster_df["channel"].fillna("") if str(x).strip()}))
        rep["version_count"] = int(len(cluster_df))
        rep["merged_cited_by_count"] = int(cluster_df["cited_by_count"].fillna(0).sum())
        rep["has_named_author"] = int(cluster_df["first_author"].map(_clean_author_name).ne("").any())
        for k in cluster:
            merged_paper_ids[k] = rep["canonical_paper_id"]
        merged.append(rep)

    canonical_papers = pd.DataFrame(merged)
    canonical_papers.to_csv(outdir / "canonical_papers.csv", index=False)

    version_map = cand[["candidate_id", "openalex_id", "doi", "title", "year", "venue", "channel", "canonical_paper_id"]].copy()
    version_map["canonical_paper_id"] = [merged_paper_ids[i] for i in range(len(version_map))]
    version_map.to_csv(outdir / "paper_version_map.csv", index=False)

    author_rows = []
    paper_author_rows = []
    for idx, row in cand.iterrows():
        first = _clean_author_name(row.get("first_author", ""))
        norm_first = normalize_name(first)
        if not norm_first:
            continue
        canonical_author_id = stable_hash("author", norm_first)
        author_rows.append({"canonical_author_id": canonical_author_id, "display_name": first, "norm_name": norm_first})
        paper_author_rows.append({"canonical_paper_id": merged_paper_ids[idx], "canonical_author_id": canonical_author_id, "author_position": 1})

    canonical_authors = pd.DataFrame(author_rows).drop_duplicates(subset=["canonical_author_id"])
    canonical_authors.to_csv(outdir / "canonical_authors.csv", index=False)
    pd.DataFrame(paper_author_rows).drop_duplicates().to_csv(outdir / "paper_authors.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
