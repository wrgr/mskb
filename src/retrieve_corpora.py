"""Retrieve paper candidates from OpenAlex via seed, seed-reference, lexical, and dataset channels."""

import argparse
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import yaml
from rapidfuzz import fuzz

from .crossref_client import CrossrefClient
from .openalex_client import OpenAlexClient
from .semantic_scholar_client import SemanticScholarClient
from .utils import ensure_dir, invert_abstract_index, load_config, normalize_name, normalize_title, save_json, stable_hash

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)


def _paper_row(work: dict, channel: str, query: str = "", seed_title: str = "", seed_doi: str = "") -> dict:
    oa_id = work.get("id", "")
    doi = work.get("doi") or ""
    title = work.get("title") or ""
    abstract = invert_abstract_index(work.get("abstract_inverted_index", {}))
    authorships = work.get("authorships", [])
    first_author = ""
    if authorships:
        first_author = ((authorships[0].get("author") or {}).get("display_name")) or ""
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""

    concepts = work.get("concepts", []) or []
    concept_names = ";".join(c.get("display_name", "") for c in concepts[:10])

    topics = work.get("topics", []) or []
    topic_names = ";".join(t.get("display_name", "") for t in topics[:5])

    return {
        "candidate_id": stable_hash(oa_id, doi or title),
        "openalex_id": oa_id,
        "doi": doi,
        "title": title,
        "year": work.get("publication_year"),
        "abstract": abstract,
        "venue": venue,
        "channel": channel,
        "query": query,
        "seed_title": seed_title,
        "seed_doi": seed_doi,
        "first_author": first_author,
        "cited_by_count": work.get("cited_by_count", 0),
        "concepts": concept_names,
        "topics": topic_names,
        "is_retrieved": True,
    }


def _normalize_doi(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    match = _DOI_RE.search(text)
    if match:
        text = match.group(0)
    text = text.strip().strip(".,;:()[]{}<>")
    return text.lower()


def _as_year(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if 1600 <= year <= 2100:
        return year
    return None


def _coerce_title(value: object) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _coerce_first_author(value: object) -> str:
    if isinstance(value, list):
        if not value:
            return ""
        first = value[0]
        if isinstance(first, dict):
            given = str(first.get("given", "") or "").strip()
            family = str(first.get("family", "") or "").strip()
            return " ".join(x for x in [given, family] if x).strip()
        return str(first or "").strip()
    return str(value or "").strip()


def _reference_candidate(
    source: str,
    doi: object = "",
    title: object = "",
    year: object = None,
    first_author: object = "",
    raw_text: object = "",
) -> Dict[str, object]:
    return {
        "source": source,
        "doi": _normalize_doi(doi),
        "title": _coerce_title(title),
        "year": _as_year(year),
        "first_author": _coerce_first_author(first_author),
        "raw_text": str(raw_text or "").strip(),
    }


def _reference_candidate_key(candidate: Dict[str, object]) -> tuple:
    norm_doi = _normalize_doi(candidate.get("doi", ""))
    norm_title = normalize_title(str(candidate.get("title", "") or ""))
    year = _as_year(candidate.get("year"))
    norm_raw = normalize_title(str(candidate.get("raw_text", "") or ""))[:180]
    if norm_title:
        return ("title", norm_title, year)
    if norm_doi:
        return ("doi", norm_doi)
    norm_author = normalize_name(str(candidate.get("first_author", "") or ""))
    return ("raw", norm_raw, year, norm_author)


def _candidate_richness(candidate: Dict[str, object]) -> int:
    score = 0
    if _normalize_doi(candidate.get("doi", "")):
        score += 4
    if str(candidate.get("title", "") or "").strip():
        score += 2
    if _as_year(candidate.get("year")) is not None:
        score += 1
    if str(candidate.get("first_author", "") or "").strip():
        score += 1
    return score


def _dedupe_reference_candidates(candidates: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    deduped: Dict[tuple, Dict[str, object]] = {}
    for candidate in candidates:
        if not (
            _normalize_doi(candidate.get("doi", ""))
            or normalize_title(str(candidate.get("title", "") or ""))
            or normalize_title(str(candidate.get("raw_text", "") or ""))
        ):
            continue
        key = _reference_candidate_key(candidate)
        prior = deduped.get(key)
        if prior is None or _candidate_richness(candidate) > _candidate_richness(prior):
            deduped[key] = candidate
    return list(deduped.values())


def _extract_crossref_reference_candidates(references: List[Dict[str, object]]) -> List[Dict[str, object]]:
    candidates = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        title = (
            ref.get("article-title")
            or ref.get("volume-title")
            or ref.get("series-title")
            or ref.get("journal-title")
            or ""
        )
        candidates.append(
            _reference_candidate(
                source="crossref",
                doi=ref.get("DOI") or ref.get("doi") or "",
                title=title,
                year=ref.get("year"),
                first_author=ref.get("author"),
                raw_text=ref.get("unstructured") or "",
            )
        )
    return candidates


def _extract_semantic_scholar_reference_candidates(references: List[Dict[str, object]]) -> List[Dict[str, object]]:
    candidates = []
    for row in references:
        if not isinstance(row, dict):
            continue
        paper = row.get("citedPaper") if isinstance(row.get("citedPaper"), dict) else row
        external_ids = paper.get("externalIds", {}) if isinstance(paper, dict) else {}
        candidates.append(
            _reference_candidate(
                source="semantic_scholar",
                doi=(external_ids or {}).get("DOI") or "",
                title=(paper or {}).get("title") or "",
                year=(paper or {}).get("year"),
                first_author=(paper or {}).get("authors") or [],
                raw_text=row.get("context", "") or "",
            )
        )
    return candidates


def _build_openalex_search_query(candidate: Dict[str, object]) -> str:
    title = str(candidate.get("title", "") or "").strip()
    if title:
        return title
    raw_text = str(candidate.get("raw_text", "") or "").strip()
    raw_text = re.sub(r"\s+", " ", raw_text)
    if not raw_text:
        return ""
    return raw_text[:180]


def _first_author_last_name(work: Dict[str, object]) -> str:
    authorships = work.get("authorships", []) or []
    if not authorships:
        return ""
    first_author = ((authorships[0].get("author") or {}).get("display_name")) or ""
    normalized = normalize_name(first_author)
    if not normalized:
        return ""
    return normalized.split()[-1]


def _choose_best_openalex_match(
    candidate: Dict[str, object],
    works: List[Dict[str, object]],
    min_title_similarity: float = 88.0,
    max_year_delta: int = 3,
) -> Optional[Dict[str, object]]:
    target_query = _build_openalex_search_query(candidate)
    target_norm = normalize_title(target_query)
    if not target_norm:
        return None
    target_year = _as_year(candidate.get("year"))
    target_author = normalize_name(str(candidate.get("first_author", "") or ""))
    target_author_last = target_author.split()[-1] if target_author else ""

    best_work: Optional[Dict[str, object]] = None
    best_score = float("-inf")
    best_similarity = 0.0
    best_year_delta: Optional[int] = None

    for work in works:
        title = str(work.get("title", "") or "").strip()
        title_norm = normalize_title(title)
        if not title_norm:
            continue
        similarity = float(fuzz.token_set_ratio(target_norm, title_norm))
        score = similarity

        candidate_year = _as_year((work or {}).get("publication_year"))
        year_delta: Optional[int] = None
        if target_year is not None and candidate_year is not None:
            year_delta = abs(target_year - candidate_year)
            if year_delta == 0:
                score += 4.0
            elif year_delta == 1:
                score += 2.0
            elif year_delta > max_year_delta:
                score -= min(24.0, float(6 * year_delta))

        if target_author_last:
            work_author_last = _first_author_last_name(work)
            if work_author_last and work_author_last == target_author_last:
                score += 2.5

        if score > best_score:
            best_score = score
            best_work = work
            best_similarity = similarity
            best_year_delta = year_delta

    if best_work is None:
        return None
    if best_similarity < float(min_title_similarity):
        return None
    if (
        target_year is not None
        and best_year_delta is not None
        and best_year_delta > max_year_delta
        and best_similarity < float(min_title_similarity) + 6.0
    ):
        return None
    return best_work


def _enrich_seed_references(
    *,
    seed_doi: str,
    seed_title: str,
    seed_work: Dict[str, object],
    openalex_client: OpenAlexClient,
    existing_reference_ids: set,
    crossref_client: Optional[CrossrefClient],
    semantic_scholar_client: Optional[SemanticScholarClient],
    enrichment_cfg: Dict[str, object],
) -> tuple:
    added_rows = []
    added_edges = []
    stats = {
        "n_crossref_refs_raw": 0,
        "n_semantic_scholar_refs_raw": 0,
        "n_reference_candidates": 0,
        "n_candidates_with_doi": 0,
        "n_resolved_via_doi": 0,
        "n_resolved_via_search": 0,
        "n_already_in_openalex_refs": 0,
        "n_unresolved": 0,
        "n_title_queries_used": 0,
    }
    seed_openalex_id = str(seed_work.get("id", "") or "").strip()
    if not seed_openalex_id:
        return added_rows, added_edges, stats

    ref_candidates = []
    if crossref_client is not None and bool(enrichment_cfg.get("use_crossref", True)):
        max_crossref_refs = int(enrichment_cfg.get("max_crossref_refs_per_seed", 250))
        crossref_refs = crossref_client.get_references_by_doi(seed_doi, max_refs=max_crossref_refs)
        stats["n_crossref_refs_raw"] += len(crossref_refs)
        ref_candidates.extend(_extract_crossref_reference_candidates(crossref_refs))

    if semantic_scholar_client is not None and bool(enrichment_cfg.get("use_semantic_scholar", True)):
        max_s2_refs = int(enrichment_cfg.get("max_semantic_scholar_refs_per_seed", 250))
        s2_refs = semantic_scholar_client.get_references_by_doi(seed_doi, max_refs=max_s2_refs)
        stats["n_semantic_scholar_refs_raw"] += len(s2_refs)
        ref_candidates.extend(_extract_semantic_scholar_reference_candidates(s2_refs))

    ref_candidates = _dedupe_reference_candidates(ref_candidates)
    stats["n_reference_candidates"] = len(ref_candidates)
    if not ref_candidates:
        return added_rows, added_edges, stats

    min_title_similarity = float(enrichment_cfg.get("min_title_similarity", 88.0))
    max_year_delta = int(enrichment_cfg.get("max_year_delta", 3))
    max_search_results = int(enrichment_cfg.get("max_search_results_per_reference", 8))
    max_title_queries = int(enrichment_cfg.get("max_title_queries_per_seed", 40))
    search_sleep_s = float(enrichment_cfg.get("search_sleep_seconds", 0.03))
    allow_title_search = bool(enrichment_cfg.get("use_openalex_title_search", True))

    doi_cache: Dict[str, Optional[Dict[str, object]]] = {}
    search_cache: Dict[tuple, Optional[Dict[str, object]]] = {}

    for candidate in ref_candidates:
        resolved_work: Optional[Dict[str, object]] = None
        resolved_channel = ""

        candidate_doi = _normalize_doi(candidate.get("doi", ""))
        if candidate_doi:
            stats["n_candidates_with_doi"] += 1
            if candidate_doi not in doi_cache:
                doi_cache[candidate_doi] = openalex_client.get_work_by_doi(candidate_doi)
            resolved_work = doi_cache[candidate_doi]
            if resolved_work:
                resolved_channel = f"seed_reference_{str(candidate.get('source', 'endnote')).strip()}"
                stats["n_resolved_via_doi"] += 1

        if not resolved_work and allow_title_search:
            query = _build_openalex_search_query(candidate)
            if query and stats["n_title_queries_used"] < max_title_queries:
                key = (
                    normalize_title(query),
                    _as_year(candidate.get("year")),
                    normalize_name(str(candidate.get("first_author", "") or "")),
                )
                if key not in search_cache:
                    year = _as_year(candidate.get("year"))
                    filter_expr = ""
                    if year is not None:
                        filter_expr = f"from_publication_year:{year - 1},to_publication_year:{year + 1}"
                    search_results = openalex_client.search_works(
                        query,
                        max_results=max_search_results,
                        filter_expr=filter_expr,
                    )
                    search_cache[key] = _choose_best_openalex_match(
                        candidate,
                        search_results,
                        min_title_similarity=min_title_similarity,
                        max_year_delta=max_year_delta,
                    )
                    stats["n_title_queries_used"] += 1
                    if search_sleep_s > 0:
                        time.sleep(search_sleep_s)
                resolved_work = search_cache[key]
                if resolved_work:
                    resolved_channel = "seed_reference_search"
                    stats["n_resolved_via_search"] += 1

        if not resolved_work:
            stats["n_unresolved"] += 1
            continue

        target_id = str((resolved_work or {}).get("id", "") or "").strip()
        if not target_id or target_id == seed_openalex_id:
            continue
        if target_id in existing_reference_ids:
            stats["n_already_in_openalex_refs"] += 1
            continue
        existing_reference_ids.add(target_id)

        added_rows.append(_paper_row(resolved_work, resolved_channel, seed_doi=seed_doi, seed_title=seed_title))
        added_edges.append({"source_openalex_id": seed_openalex_id, "target_openalex_id": target_id, "edge_type": "CITES"})

    return added_rows, added_edges, stats


def _empty_enrichment_totals() -> dict:
    """Return a zeroed enrichment statistics dict."""
    return {
        "n_crossref_refs_raw": 0, "n_semantic_scholar_refs_raw": 0,
        "n_reference_candidates": 0, "n_candidates_with_doi": 0,
        "n_resolved_via_doi": 0, "n_resolved_via_search": 0,
        "n_already_in_openalex_refs": 0, "n_unresolved": 0, "n_title_queries_used": 0,
    }


def _run_seed_channel(
    core_seeds: pd.DataFrame,
    client: OpenAlexClient,
    retrieval_cfg: dict,
    enrichment_enabled: bool,
    enrichment_cfg: dict,
    crossref_client: Optional[CrossrefClient],
    semantic_scholar_client: Optional[SemanticScholarClient],
) -> tuple[list[dict], list[dict], dict]:
    """Retrieve papers and citation edges for all core seeds; return rows, edges, enrichment totals."""
    rows: list[dict] = []
    citation_edges: list[dict] = []
    enrichment_totals = _empty_enrichment_totals()

    for _, seed in core_seeds.iterrows():
        doi = str(seed["doi"]) if pd.notna(seed["doi"]) else ""
        title = seed["title"]
        if not doi:
            continue
        work = client.get_work_by_doi(doi)
        if not work:
            continue
        existing_reference_ids: set[str] = set()
        rows.append(_paper_row(work, "seed_resolution", seed_doi=doi, seed_title=title))
        refs = [r.split("/")[-1] for r in work.get("referenced_works", []) if r]
        for ref in client.get_multiple_works(refs):
            rows.append(_paper_row(ref, "seed_reference", seed_doi=doi, seed_title=title))
            ref_id = str(ref.get("id", "") or "").strip()
            if ref_id:
                existing_reference_ids.add(ref_id)
                citation_edges.append({"source_openalex_id": work.get("id", ""), "target_openalex_id": ref_id, "edge_type": "CITES"})
        if enrichment_enabled:
            enriched_rows, enriched_edges, enrich_stats = _enrich_seed_references(
                seed_doi=doi, seed_title=title, seed_work=work, openalex_client=client,
                existing_reference_ids=existing_reference_ids, crossref_client=crossref_client,
                semantic_scholar_client=semantic_scholar_client, enrichment_cfg=enrichment_cfg,
            )
            rows.extend(enriched_rows)
            citation_edges.extend(enriched_edges)
            for key, value in enrich_stats.items():
                enrichment_totals[key] += int(value)
        for citing in client.get_citing_works(work.get("id", ""), max_pages=retrieval_cfg["max_pages_cited_by"]):
            rows.append(_paper_row(citing, "seed_cited_by", seed_doi=doi, seed_title=title))
            citing_id = str(citing.get("id", "") or "").strip()
            work_id = str(work.get("id", "") or "").strip()
            if citing_id and work_id:
                citation_edges.append({"source_openalex_id": citing_id, "target_openalex_id": work_id, "edge_type": "CITES"})

    return rows, citation_edges, enrichment_totals


def _run_query_channel(
    client: OpenAlexClient, queries: list[str], channel: str, max_results: int
) -> list[dict]:
    """Retrieve papers for a list of search queries under a named channel."""
    rows: list[dict] = []
    for query in queries:
        for work in client.search_works(query, max_results=max_results):
            rows.append(_paper_row(work, channel, query=query))
    return rows


def _run_framing_seed_channel(
    framing_seeds: pd.DataFrame,
    client: OpenAlexClient,
    retrieval_cfg: dict,
) -> tuple[list[dict], list[dict]]:
    """Retrieve papers and citation edges for the six review-anchor seeds (R1–R6).

    Framing seeds expand the candidate pool and provide anchor links for topic
    assignment but are NOT counted toward cross_seed_score (that uses only the
    40 core seeds). Channel labels are distinct so downstream scoring can treat
    them separately.
    """
    rows: list[dict] = []
    citation_edges: list[dict] = []
    max_pages = int(retrieval_cfg.get("max_pages_cited_by", 3))

    for _, seed in framing_seeds.iterrows():
        doi = str(seed["doi"]) if pd.notna(seed.get("doi")) else ""
        title = str(seed.get("title", "") or "").strip()
        if not doi:
            continue
        work = client.get_work_by_doi(doi)
        if not work:
            continue
        work_id = str(work.get("id", "") or "").strip()
        rows.append(_paper_row(work, "framing_seed_resolution", seed_doi=doi, seed_title=title))
        refs = [r.split("/")[-1] for r in work.get("referenced_works", []) if r]
        for ref in client.get_multiple_works(refs):
            rows.append(_paper_row(ref, "framing_seed_reference", seed_doi=doi, seed_title=title))
            ref_id = str(ref.get("id", "") or "").strip()
            if ref_id and work_id:
                citation_edges.append(
                    {"source_openalex_id": work_id, "target_openalex_id": ref_id, "edge_type": "CITES"}
                )
        for citing in client.get_citing_works(work_id, max_pages=max_pages):
            rows.append(_paper_row(citing, "framing_seed_cited_by", seed_doi=doi, seed_title=title))
            citing_id = str(citing.get("id", "") or "").strip()
            if citing_id and work_id:
                citation_edges.append(
                    {"source_openalex_id": citing_id, "target_openalex_id": work_id, "edge_type": "CITES"}
                )

    return rows, citation_edges


def _run_t4_expert_channel(
    t4_yaml_path: Path,
    client: OpenAlexClient,
    max_title_queries: int = 0,
) -> list[dict]:
    """Retrieve all expert-signal T4 papers from data/t4_expert_signal.yaml.

    Uses DOI lookup for entries with corpus_doi; falls back to title search for
    not_found entries so papers without a recorded DOI can still be retrieved.
    """
    rows: list[dict] = []
    if not t4_yaml_path.exists():
        return rows
    payload = yaml.safe_load(t4_yaml_path.read_text(encoding="utf-8")) or {}
    # flat_list is the canonical de-duped view; fall back to by_concept if absent.
    entries: list[dict] = payload.get("flat_list", [])
    if not entries:
        by_concept = payload.get("by_concept", {})
        for items in by_concept.values():
            entries.extend(items or [])

    doi_queried: set[str] = set()
    title_queries_used = 0
    unlimited_title_queries = max_title_queries <= 0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        t4_id = str(entry.get("t4_id", "") or "").strip()
        title = str(entry.get("title", "") or "").strip()
        year = entry.get("year")

        # DOI lookup first — corpus_doi is populated for papers already in corpus.
        corpus_doi = str(entry.get("corpus_doi", "") or "").strip()
        doi = _normalize_doi(corpus_doi)
        work: Optional[Dict[str, object]] = None

        if doi and doi not in doi_queried:
            doi_queried.add(doi)
            work = client.get_work_by_doi(doi)

        # Title search for entries without a recorded DOI (most not_found papers).
        if not work and title and (unlimited_title_queries or title_queries_used < max_title_queries):
            filter_expr = ""
            if year is not None:
                try:
                    yr = int(str(year))
                    filter_expr = f"from_publication_year:{yr - 1},to_publication_year:{yr + 1}"
                except (TypeError, ValueError):
                    pass
            results = client.search_works(title, max_results=5, filter_expr=filter_expr)
            if not results and filter_expr:
                # OpenAlex filters can be brittle for historical/legacy records.
                # Retry unfiltered title search before giving up.
                results = client.search_works(title, max_results=5)
            work = _choose_best_openalex_match(
                {"title": title, "year": year},
                results,
                min_title_similarity=88.0,
                max_year_delta=2,
            )
            title_queries_used += 1

        if not work:
            continue
        rows.append(_paper_row(work, "expert_signal_t4", query=t4_id))

    return rows


def run(config_path: str) -> None:
    """Retrieve paper candidates via seed, lexical, and dataset channels and write candidate_papers.csv."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    outdir = root / cfg["output_dir"] / "raw"
    ensure_dir(outdir)
    retrieval_cfg = cfg.get("retrieval", {})

    client = OpenAlexClient(
        base_url=cfg["openalex_base_url"], email=cfg["email"],
        per_page=retrieval_cfg["per_page"], cache_dir=outdir / "openalex_cache",
    )
    enrichment_cfg = retrieval_cfg.get("seed_reference_enrichment", {})
    enrichment_enabled = bool(enrichment_cfg.get("enabled", True))
    enrichment_timeout = int(enrichment_cfg.get("request_timeout_seconds", 30))

    crossref_client: Optional[CrossrefClient] = None
    if enrichment_enabled and bool(enrichment_cfg.get("use_crossref", True)):
        crossref_client = CrossrefClient(email=cfg.get("email", ""), timeout=enrichment_timeout, cache_dir=outdir / "crossref_cache")

    semantic_scholar_client: Optional[SemanticScholarClient] = None
    if enrichment_enabled and bool(enrichment_cfg.get("use_semantic_scholar", True)):
        api_key_env = str(enrichment_cfg.get("semantic_scholar_api_key_env", "SEMANTIC_SCHOLAR_API_KEY"))
        semantic_scholar_client = SemanticScholarClient(
            api_key=os.environ.get(api_key_env, ""), timeout=enrichment_timeout,
            cache_dir=outdir / "semantic_scholar_cache",
        )

    core_seeds = pd.read_csv(root / "seeds" / "core_seeds.csv")
    framing_seeds = pd.read_csv(root / "seeds" / "framing_seeds.csv")
    # T4 expert signals are sourced from the YAML (authoritative) not the CSV.
    t4_yaml_path = root / "data" / "t4_expert_signal.yaml"
    max_per_query = retrieval_cfg["max_search_results_per_query"]
    max_t4_title_queries = int(retrieval_cfg.get("t4_max_title_queries", 0))

    rows: list[dict] = []
    citation_edges: list[dict] = []
    enrichment_totals = _empty_enrichment_totals()

    if retrieval_cfg["use_seed_channel"]:
        seed_rows, seed_edges, seed_totals = _run_seed_channel(
            core_seeds, client, retrieval_cfg, enrichment_enabled, enrichment_cfg,
            crossref_client, semantic_scholar_client,
        )
        rows.extend(seed_rows)
        citation_edges.extend(seed_edges)
        for key, value in seed_totals.items():
            enrichment_totals[key] += value

    if bool(retrieval_cfg.get("use_framing_seed_channel", True)):
        framing_rows, framing_edges = _run_framing_seed_channel(framing_seeds, client, retrieval_cfg)
        rows.extend(framing_rows)
        citation_edges.extend(framing_edges)

    if retrieval_cfg["use_lexical_channel"]:
        rows.extend(_run_query_channel(client, cfg["queries"]["lexical"], "lexical", max_per_query))
    if retrieval_cfg["use_dataset_channel"]:
        rows.extend(_run_query_channel(client, cfg["queries"]["dataset"], "dataset", max_per_query))
    if bool(retrieval_cfg.get("use_t4_expert_channel", True)):
        rows.extend(_run_t4_expert_channel(
            t4_yaml_path=t4_yaml_path, client=client, max_title_queries=max_t4_title_queries,
        ))

    candidates = pd.DataFrame(rows).drop_duplicates(subset=["openalex_id", "doi", "title", "channel"])
    candidates.to_csv(outdir / "candidate_papers.csv", index=False)
    citation_edges_df = pd.DataFrame(citation_edges).drop_duplicates()
    citation_edges_df.to_csv(outdir / "seed_citation_edges.csv", index=False)

    # Count T4 YAML entries for provenance.
    n_t4_yaml = 0
    if t4_yaml_path.exists():
        t4_payload = yaml.safe_load(t4_yaml_path.read_text(encoding="utf-8")) or {}
        n_t4_yaml = len(t4_payload.get("flat_list", []) or list(
            item for items in (t4_payload.get("by_concept") or {}).values() for item in (items or [])
        ))

    stats_payload = {
        "n_candidates": int(len(candidates)),
        "n_seed_edges": int(len(citation_edges_df)),
        "n_core_seeds": int(len(core_seeds)),
        "n_framing_seeds": int(len(framing_seeds)),
        "n_t4_yaml_entries": n_t4_yaml,
        "seed_reference_enrichment_enabled": enrichment_enabled,
    }
    stats_payload.update({f"enrichment_{k}": int(v) for k, v in enrichment_totals.items()})
    save_json(stats_payload, outdir / "retrieval_stats.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
