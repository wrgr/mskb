#!/usr/bin/env python3
"""
backfill_t4_dois.py

Backfill missing DOI/OpenAlex identifiers in data/t4_expert_signal.yaml.

For each T4 entry lacking a doi field, this script searches OpenAlex by title
(+/- 2 years when year is available), picks the best title match, and writes:
  - doi
  - openalex_id

It does not change corpus_status semantics (e.g. not_found remains not_found).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import requests
import yaml
from rapidfuzz import fuzz

from src.openalex_client import OpenAlexClient
from src.retrieve_corpora import _choose_best_openalex_match
from src.utils import load_config, normalize_title


def _normalize_doi(value: object) -> str:
    """Strip URL prefix and normalise a DOI string to bare lowercase form."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    return text.strip().lower()


def _all_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield all paper dicts from a v2 (or v1-fallback) by_concept payload."""
    out: list[dict[str, Any]] = []
    by_concept = payload.get("by_concept", {}) if isinstance(payload, dict) else {}
    for concept_block in by_concept.values():
        if isinstance(concept_block, dict):
            out.extend(e for e in (concept_block.get("papers", []) or []) if isinstance(e, dict))
        else:
            out.extend(e for e in (concept_block or []) if isinstance(e, dict))
    return out


def _score_match(title: str, year: object, work: dict[str, Any]) -> tuple[float, int | None]:
    """Return (title_similarity, year_delta) for a candidate OpenAlex work."""
    target = normalize_title(title)
    candidate = normalize_title(str(work.get("title", "") or ""))
    similarity = float(fuzz.token_set_ratio(target, candidate))
    year_delta = None
    try:
        y = int(str(year))
        wy = int(str(work.get("publication_year")))
        year_delta = abs(wy - y)
    except Exception:
        year_delta = None
    return similarity, year_delta


def main() -> None:
    """Resolve missing DOIs in t4_expert_signal.yaml via OpenAlex title search."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--yaml-path", default="data/t4_expert_signal.yaml")
    parser.add_argument("--min-title-similarity", type=float, default=88.0)
    parser.add_argument("--max-year-delta", type=int, default=2)
    parser.add_argument("--max-results", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.config).resolve().parent
    cfg = load_config(args.config)
    yaml_path = (
        (root / args.yaml_path).resolve()
        if not Path(args.yaml_path).is_absolute()
        else Path(args.yaml_path)
    )
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    entries = _all_entries(payload)

    client = OpenAlexClient(
        base_url=cfg["openalex_base_url"],
        email=cfg["email"],
        per_page=int(cfg.get("retrieval", {}).get("per_page", 200)),
        cache_dir=root / cfg["output_dir"] / "raw" / "openalex_cache",
        max_retries=12,
        max_retry_sleep_s=120.0,
    )

    # t4_id → {doi, openalex_id} for entries that resolve successfully.
    by_t4id: dict[str, dict[str, str]] = {}
    looked_up = 0
    resolved = 0
    unresolved = 0

    for entry in entries:
        t4_id = str(entry.get("t4_id", "") or "").strip()
        title = str(entry.get("title", "") or "").strip()
        year = entry.get("year")
        existing_doi = _normalize_doi(entry.get("doi", "") or entry.get("corpus_doi", ""))

        if existing_doi:
            continue
        if not title:
            unresolved += 1
            continue

        looked_up += 1
        filter_expr = ""
        try:
            yr = int(str(year))
            filter_expr = (
                f"from_publication_year:{yr - args.max_year_delta},"
                f"to_publication_year:{yr + args.max_year_delta}"
            )
        except Exception:
            pass

        try:
            works = client.search_works(title, max_results=args.max_results, filter_expr=filter_expr)
            if not works and filter_expr:
                works = client.search_works(title, max_results=args.max_results)
        except requests.HTTPError:
            unresolved += 1
            continue

        best = _choose_best_openalex_match(
            {"title": title, "year": year},
            works,
            min_title_similarity=float(args.min_title_similarity),
            max_year_delta=int(args.max_year_delta),
        )
        if not best:
            unresolved += 1
            continue

        doi = _normalize_doi(best.get("doi", ""))
        if not doi:
            unresolved += 1
            continue

        by_t4id[t4_id] = {
            "doi": f"https://doi.org/{doi}",
            "openalex_id": str(best.get("id", "") or ""),
        }
        resolved += 1

    if not by_t4id:
        print(f"No updates. looked_up={looked_up}, resolved={resolved}, unresolved={unresolved}")
        return

    def apply_updates(items: list[dict[str, Any]]) -> None:
        """Write doi/openalex_id into matching entries in-place."""
        for item in items:
            if not isinstance(item, dict):
                continue
            t4_id = str(item.get("t4_id", "") or "").strip()
            update = by_t4id.get(t4_id)
            if not update:
                continue
            item["doi"] = update["doi"]
            item["openalex_id"] = update["openalex_id"]

    by_concept = payload.get("by_concept", {})
    if isinstance(by_concept, dict):
        for concept_block in by_concept.values():
            if isinstance(concept_block, dict):
                apply_updates(concept_block.get("papers", []) or [])
            elif isinstance(concept_block, list):
                apply_updates(concept_block)

    if args.dry_run:
        print(
            f"[dry-run] updates={len(by_t4id)} looked_up={looked_up} "
            f"resolved={resolved} unresolved={unresolved}"
        )
        return

    class NoAliasDumper(yaml.Dumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    yaml_path.write_text(
        yaml.dump(
            payload,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    print(f"Updated {yaml_path}")
    print(
        f"entries_updated={len(by_t4id)} looked_up={looked_up} "
        f"resolved={resolved} unresolved={unresolved}"
    )


if __name__ == "__main__":
    main()
