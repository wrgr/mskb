import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from .openalex_client import OpenAlexClient
from .utils import invert_abstract_index, load_config


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _extract_ids(value: object) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    parts = []
    for token in text.split(";"):
        token = token.strip()
        if not token:
            continue
        if token.startswith("https://openalex.org/"):
            token = token.split("/")[-1]
        parts.append(token)
    return parts


def _is_missing_abstract(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().str.lower().isin(["", "nan"])


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    output_dir = root / cfg["output_dir"]
    normalized_dir = output_dir / "normalized"
    graph_dir = output_dir / "graph"
    raw_dir = output_dir / "raw"

    canonical_path = normalized_dir / "canonical_papers.csv"
    if not canonical_path.exists():
        raise FileNotFoundError(f"Missing {canonical_path}")

    canonical = pd.read_csv(canonical_path)
    canonical["canonical_paper_id"] = canonical["canonical_paper_id"].astype(str)

    if "abstract_backfill_source" not in canonical.columns:
        canonical["abstract_backfill_source"] = ""

    missing_before = _is_missing_abstract(canonical["abstract"])
    missing_ids_before = set(canonical.loc[missing_before, "canonical_paper_id"].astype(str))

    stats = {
        "total_canonical_papers": int(len(canonical)),
        "missing_before": int(len(missing_ids_before)),
        "filled_from_candidate_versions": 0,
        "attempted_openalex_queries": 0,
        "successful_openalex_backfills": 0,
        "openalex_errors": 0,
        "missing_after": 0,
    }

    # Pass 1: recover from any candidate version in local raw output.
    candidate_path = raw_dir / "candidate_papers.csv"
    version_map_path = normalized_dir / "paper_version_map.csv"
    if candidate_path.exists() and version_map_path.exists():
        candidates = pd.read_csv(candidate_path, usecols=lambda c: c in {"candidate_id", "abstract"})
        version_map = pd.read_csv(
            version_map_path, usecols=lambda c: c in {"candidate_id", "canonical_paper_id"}
        )
        candidates = candidates.merge(version_map, on="candidate_id", how="left")
        candidates["canonical_paper_id"] = candidates["canonical_paper_id"].astype(str)
        candidates["abstract"] = candidates["abstract"].map(_clean_text)
        recoverable = (
            candidates[candidates["canonical_paper_id"].isin(missing_ids_before)]
            .groupby("canonical_paper_id", as_index=False)["abstract"]
            .agg(lambda s: _first_nonempty(list(s)))
        )
        recoverable = recoverable[recoverable["abstract"].map(bool)]
        if not recoverable.empty:
            recoverable_map = dict(zip(recoverable["canonical_paper_id"], recoverable["abstract"]))
            selector = canonical["canonical_paper_id"].isin(recoverable_map.keys()) & _is_missing_abstract(
                canonical["abstract"]
            )
            canonical.loc[selector, "abstract"] = canonical.loc[selector, "canonical_paper_id"].map(recoverable_map)
            canonical.loc[selector, "abstract_backfill_source"] = "candidate_version"
            stats["filled_from_candidate_versions"] = int(selector.sum())

    # Pass 2: query OpenAlex for remaining missing abstracts.
    backfill_cfg = cfg.get("abstract_backfill", {}) or {}
    enabled = bool(backfill_cfg.get("enabled", True))
    max_queries = backfill_cfg.get("max_openalex_queries")
    env_max_queries = _clean_text(os.environ.get("MSKB_MAX_OPENALEX_QUERIES", ""))
    if env_max_queries:
        max_queries = env_max_queries
    per_request_sleep_s = float(backfill_cfg.get("sleep_seconds", 0.03))
    cache_dir = raw_dir / "openalex_cache"

    if enabled:
        if max_queries is not None:
            try:
                max_queries = int(max_queries)
            except (TypeError, ValueError):
                max_queries = None
        timeout = int(backfill_cfg.get("request_timeout_seconds", 12))
        max_consecutive_errors = int(backfill_cfg.get("max_consecutive_errors", 6))
        client = OpenAlexClient(
            base_url=cfg["openalex_base_url"],
            email=cfg["email"],
            per_page=int(cfg.get("retrieval", {}).get("per_page", 200)),
            timeout=timeout,
            cache_dir=cache_dir,
        )

        remaining_missing = canonical[_is_missing_abstract(canonical["abstract"])].copy()
        consecutive_errors = 0
        for idx, row in remaining_missing.iterrows():
            if max_queries is not None and stats["attempted_openalex_queries"] >= max_queries:
                break
            if consecutive_errors >= max_consecutive_errors:
                break
            fetched_abstract = ""
            fetched_source = ""

            openalex_ids = []
            openalex_ids.extend(_extract_ids(row.get("openalex_id", "")))
            openalex_ids.extend(_extract_ids(row.get("all_openalex_ids", "")))
            # Preserve order and de-duplicate.
            dedup_openalex_ids = list(dict.fromkeys(openalex_ids))

            for oa_id in dedup_openalex_ids:
                stats["attempted_openalex_queries"] += 1
                try:
                    work = client.get_work_by_openalex_id(oa_id)
                except Exception:
                    work = None
                    stats["openalex_errors"] += 1
                    consecutive_errors += 1
                if not work:
                    continue
                consecutive_errors = 0
                fetched_abstract = invert_abstract_index(work.get("abstract_inverted_index", {}))
                if fetched_abstract:
                    fetched_source = f"openalex_id:{oa_id}"
                    break
                if max_queries is not None and stats["attempted_openalex_queries"] >= max_queries:
                    break
                if per_request_sleep_s > 0:
                    time.sleep(per_request_sleep_s)

            if not fetched_abstract:
                doi = _clean_text(row.get("doi", ""))
                if doi and (max_queries is None or stats["attempted_openalex_queries"] < max_queries):
                    stats["attempted_openalex_queries"] += 1
                    try:
                        work = client.get_work_by_doi(doi.replace("https://doi.org/", ""))
                    except Exception:
                        work = None
                        stats["openalex_errors"] += 1
                        consecutive_errors += 1
                    if work:
                        consecutive_errors = 0
                        fetched_abstract = invert_abstract_index(work.get("abstract_inverted_index", {}))
                        if fetched_abstract:
                            fetched_source = f"doi:{doi}"
                    if per_request_sleep_s > 0:
                        time.sleep(per_request_sleep_s)

            if fetched_abstract:
                canonical.at[idx, "abstract"] = fetched_abstract
                canonical.at[idx, "abstract_backfill_source"] = fetched_source or "openalex_backfill"
                stats["successful_openalex_backfills"] += 1

    missing_after = _is_missing_abstract(canonical["abstract"])
    stats["missing_after"] = int(missing_after.sum())
    stats["filled_total"] = int(stats["missing_before"] - stats["missing_after"])

    canonical.to_csv(canonical_path, index=False)

    scored_path = graph_dir / "scored_papers.csv"
    if scored_path.exists():
        scored = pd.read_csv(scored_path)
        scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
        canonical_abstracts = canonical[["canonical_paper_id", "abstract", "abstract_backfill_source"]].copy()
        scored = scored.drop(columns=["abstract", "abstract_backfill_source"], errors="ignore")
        scored = scored.merge(canonical_abstracts, on="canonical_paper_id", how="left")
        scored.to_csv(scored_path, index=False)

    stats_path = raw_dir / "abstract_backfill_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
