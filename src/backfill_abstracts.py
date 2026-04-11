"""Backfill missing abstracts from local data, OpenAlex, and secondary metadata sources."""

import argparse
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from .crossref_client import CrossrefClient
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


def _normalize_doi(value: object) -> str:
    text = _clean_text(value).lower()
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    return text.strip()


def _strip_markup(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_plausible_abstract(text: str, min_chars: int = 60) -> bool:
    text = _clean_text(text)
    if not text:
        return False
    if len(text) < min_chars:
        return False
    # Require at least one sentence-like delimiter to avoid headings/titles.
    if all(mark not in text for mark in [". ", "; ", ": "]):
        return False
    return True


def _source_quality(source: str) -> str:
    s = _clean_text(source).lower()
    if not s:
        return ""
    if s.startswith("fulltext_"):
        return "inferred_from_fulltext"
    return "abstract_text"


def _fetch_crossref_abstract(doi_norm: str, client: CrossrefClient) -> tuple[str, str]:
    work = client.get_work_by_doi(doi_norm)
    if not work:
        return "", ""
    abstract = _strip_markup(work.get("abstract", ""))
    if not abstract:
        return "", ""
    return abstract, "crossref"


def _fetch_datacite_abstract(doi_norm: str, timeout: int, email: str) -> tuple[str, str]:
    url = f"https://doi.org/{doi_norm}"
    headers = {
        "Accept": "application/vnd.citationstyles.csl+json",
        "User-Agent": f"mskb/0.1 ({email or 'unknown'})",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        return "", ""
    try:
        payload = resp.json()
    except ValueError:
        return "", ""
    abstract = _strip_markup(payload.get("abstract", ""))
    if not abstract:
        return "", ""
    return abstract, "doi_csl_json"


def _fetch_europepmc_abstract(doi_norm: str, timeout: int, email: str) -> tuple[str, str]:
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {"query": f"DOI:{doi_norm}", "format": "json", "pageSize": 1}
    headers = {"User-Agent": f"mskb/0.1 ({email or 'unknown'})"}
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        return "", ""
    try:
        payload = resp.json()
    except ValueError:
        return "", ""
    hits = ((payload.get("resultList") or {}).get("result") or [])
    if not hits:
        return "", ""
    abstract = _strip_markup((hits[0] or {}).get("abstractText", ""))
    if not abstract:
        return "", ""
    return abstract, "europe_pmc"


def _fetch_pubmed_abstract(doi_norm: str, timeout: int, email: str) -> tuple[str, str]:
    headers = {"User-Agent": f"mskb/0.1 ({email or 'unknown'})"}
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {"db": "pubmed", "term": f"{doi_norm}[AID]", "retmax": 1, "retmode": "json"}
    search_resp = requests.get(search_url, params=search_params, headers=headers, timeout=timeout)
    if search_resp.status_code >= 400:
        return "", ""
    try:
        search_payload = search_resp.json()
    except ValueError:
        return "", ""
    id_list = ((search_payload.get("esearchresult") or {}).get("idlist") or [])
    if not id_list:
        return "", ""
    pmid = str(id_list[0]).strip()
    if not pmid:
        return "", ""

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    fetch_params = {"db": "pubmed", "id": pmid, "retmode": "xml"}
    fetch_resp = requests.get(fetch_url, params=fetch_params, headers=headers, timeout=timeout)
    if fetch_resp.status_code >= 400:
        return "", ""
    try:
        root = ET.fromstring(fetch_resp.text)
    except ET.ParseError:
        return "", ""
    texts: list[str] = []
    for node in root.findall(".//Abstract/AbstractText"):
        part = _strip_markup("".join(node.itertext()))
        if part:
            texts.append(part)
    abstract = _clean_text(" ".join(texts))
    if not abstract:
        return "", ""
    return abstract, "pubmed"


def _fetch_semantic_scholar_abstract(doi_norm: str, timeout: int, email: str) -> tuple[str, str]:
    if not doi_norm:
        return "", ""
    encoded_doi = quote(doi_norm, safe="")
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{encoded_doi}"
    params = {"fields": "abstract"}
    headers = {"User-Agent": f"mskb/0.1 ({email or 'unknown'})"}
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        return "", ""
    try:
        payload = resp.json()
    except ValueError:
        return "", ""
    abstract = _strip_markup((payload or {}).get("abstract", ""))
    if not abstract:
        return "", ""
    return abstract, "semantic_scholar"


def _extract_abstract_from_fulltext_text(pid: str, text_dir: Path) -> tuple[str, str]:
    path = text_dir / f"{pid}.txt"
    if not path.exists():
        return "", ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    text = _strip_markup(raw)
    if not text:
        return "", ""
    pattern = re.compile(
        r"(?is)\babstract\b[:\s-]*(.{120,6000}?)(?:\bintroduction\b|\bbackground\b|\bmethods?\b|\bkeywords?\b|\n\s*1[\.\)]\s*introduction\b)"
    )
    match = pattern.search(text)
    if match:
        abstract = _clean_text(match.group(1))
        if _is_plausible_abstract(abstract):
            return abstract, "fulltext_heuristic"
    # Fallback: take the abstract-like pre-introduction prefix when explicit heading is absent.
    intro_match = re.search(r"(?is)\bintroduction\b", text)
    if intro_match:
        prefix = text[: intro_match.start()]
        prefix = re.sub(r"\s+", " ", prefix).strip()
        # Drop very short prefixes and likely metadata-only stubs.
        if _is_plausible_abstract(prefix, min_chars=180) and prefix.count(".") >= 3:
            return prefix, "fulltext_prefix_heuristic"
    return "", ""


def _extract_website_abstract_from_html(html_text: str) -> tuple[str, str]:
    text = _clean_text(html_text)
    if not text:
        return "", ""

    # 1) High-quality publisher tags.
    patterns = [
        (r'(?is)<meta[^>]+name=["\']citation_abstract["\'][^>]+content=["\'](.*?)["\']', "website_citation_abstract"),
        (r'(?is)<meta[^>]+name=["\']dc\.description["\'][^>]+content=["\'](.*?)["\']', "website_dc_description"),
        (r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', "website_og_description"),
        (r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', "website_meta_description"),
    ]
    for pattern, source in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        candidate = _strip_markup(m.group(1))
        if _is_plausible_abstract(candidate, min_chars=100):
            return candidate, source

    # 2) JSON-LD description.
    for block in re.findall(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text):
        block_text = _clean_text(block)
        if not block_text:
            continue
        try:
            payload = json.loads(block_text)
        except Exception:
            continue
        records = payload if isinstance(payload, list) else [payload]
        for rec in records:
            if not isinstance(rec, dict):
                continue
            candidate = _strip_markup(rec.get("description", ""))
            if _is_plausible_abstract(candidate, min_chars=100):
                return candidate, "website_jsonld_description"

    # 3) Abstract section blocks.
    section_patterns = [
        r'(?is)(?:<h2[^>]*>\s*abstract\s*</h2>|<h3[^>]*>\s*abstract\s*</h3>)\s*(.{120,6000}?)(?:<h2|<h3|</section>)',
        r'(?is)<section[^>]*(?:id|class)=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.{120,6000}?)</section>',
        r'(?is)<div[^>]*(?:id|class)=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.{120,6000}?)</div>',
    ]
    for pattern in section_patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        candidate = _strip_markup(m.group(1))
        if _is_plausible_abstract(candidate, min_chars=120):
            return candidate, "website_abstract_section"

    return "", ""


def _fetch_website_abstract(doi_norm: str, timeout: int, email: str) -> tuple[str, str]:
    if not doi_norm:
        return "", ""
    url = f"https://doi.org/{doi_norm}"
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": f"mskb/0.1 ({email or 'unknown'})",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if resp.status_code >= 400:
        return "", ""
    html_text = resp.text or ""
    return _extract_website_abstract_from_html(html_text)


def run(config_path: str) -> None:
    """Backfill missing abstracts from local candidate versions then OpenAlex, updating canonical CSVs."""
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
    canonical["abstract_backfill_source"] = canonical["abstract_backfill_source"].fillna("").astype(str)
    if "abstract_backfill_quality" not in canonical.columns:
        canonical["abstract_backfill_quality"] = ""
    canonical["abstract_backfill_quality"] = canonical["abstract_backfill_quality"].fillna("").astype(str)

    backfill_cfg = cfg.get("abstract_backfill", {}) or {}
    governance_cfg = cfg.get("governance", {}) or {}
    hold_missing_abstracts_from_graph = bool(governance_cfg.get("hold_missing_abstracts_from_graph", False))
    enabled = bool(backfill_cfg.get("enabled", True))
    selected_cfg = backfill_cfg.get("selected_scope", {}) or {}
    selected_scope_enabled = bool(enabled and selected_cfg.get("enabled", False))
    selected_scope_ids: set[str] = set()
    selected_scope_mask = pd.Series(True, index=canonical.index)
    if selected_scope_enabled:
        selected_path_rel = _clean_text(selected_cfg.get("selected_csv_path", ""))
        selected_id_column = _clean_text(selected_cfg.get("selected_id_column", "canonical_paper_id")) or "canonical_paper_id"
        selected_path = (Path(config_path).resolve().parent / selected_path_rel) if selected_path_rel else None
        if not selected_path or not selected_path.exists():
            raise FileNotFoundError(
                "abstract_backfill.selected_scope.enabled=true but selected_csv_path is missing or not found"
            )
        selected_df = pd.read_csv(selected_path, usecols=lambda c: c == selected_id_column)
        if selected_id_column not in selected_df.columns:
            raise KeyError(
                f"abstract_backfill.selected_scope.selected_id_column '{selected_id_column}' "
                f"not found in {selected_path}"
            )
        selected_scope_ids = set(selected_df[selected_id_column].dropna().astype(str).tolist())
        if hold_missing_abstracts_from_graph:
            hold_path = graph_dir / "papers_on_hold_missing_abstract.csv"
            if hold_path.exists():
                hold_df = pd.read_csv(hold_path, usecols=lambda c: c == "canonical_paper_id")
                if "canonical_paper_id" in hold_df.columns:
                    hold_ids = set(hold_df["canonical_paper_id"].dropna().astype(str).tolist())
                    selected_scope_ids |= hold_ids
        selected_scope_mask = canonical["canonical_paper_id"].astype(str).isin(selected_scope_ids)

    missing_before = _is_missing_abstract(canonical["abstract"])
    missing_ids_before = set(canonical.loc[missing_before & selected_scope_mask, "canonical_paper_id"].astype(str))

    stats = {
        "total_canonical_papers": int(len(canonical)),
        "missing_before_all": int(missing_before.sum()),
        "missing_before_scope": int(len(missing_ids_before)),
        "selected_scope_enabled": bool(selected_scope_enabled),
        "selected_scope_size": int(selected_scope_mask.sum()),
        "filled_from_candidate_versions": 0,
        "attempted_openalex_queries": 0,
        "successful_openalex_backfills": 0,
        "openalex_errors": 0,
        "attempted_secondary_queries": 0,
        "successful_secondary_backfills": 0,
        "secondary_errors": 0,
        "attempted_by_source": {
            "crossref": 0,
            "doi_csl_json": 0,
            "pubmed": 0,
            "europe_pmc": 0,
            "semantic_scholar": 0,
            "fulltext_heuristic": 0,
            "website_scrape": 0,
        },
        "successful_by_source": {
            "crossref": 0,
            "doi_csl_json": 0,
            "pubmed": 0,
            "europe_pmc": 0,
            "semantic_scholar": 0,
            "fulltext_heuristic": 0,
            "website_scrape": 0,
        },
        "errors_by_source": {
            "crossref": 0,
            "doi_csl_json": 0,
            "pubmed": 0,
            "europe_pmc": 0,
            "semantic_scholar": 0,
            "fulltext_heuristic": 0,
            "website_scrape": 0,
        },
        "missing_after_all": 0,
        "missing_after_scope": 0,
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
            ) & selected_scope_mask
            canonical.loc[selector, "abstract"] = canonical.loc[selector, "canonical_paper_id"].map(recoverable_map)
            canonical.loc[selector, "abstract_backfill_source"] = "candidate_version"
            canonical.loc[selector, "abstract_backfill_quality"] = "abstract_text"
            stats["filled_from_candidate_versions"] = int(selector.sum())

    # Pass 2: query OpenAlex then secondary metadata channels for remaining missing abstracts.
    max_queries = backfill_cfg.get("max_openalex_queries")
    env_max_queries = _clean_text(os.environ.get("MSKB_MAX_OPENALEX_QUERIES", ""))
    if env_max_queries:
        max_queries = env_max_queries
    max_secondary_queries = backfill_cfg.get("max_secondary_queries")
    env_max_secondary_queries = _clean_text(os.environ.get("MSKB_MAX_SECONDARY_QUERIES", ""))
    if env_max_secondary_queries:
        max_secondary_queries = env_max_secondary_queries
    per_request_sleep_s = float(backfill_cfg.get("sleep_seconds", 0.03))
    cache_dir = raw_dir / "openalex_cache"
    crossref_cache_dir = raw_dir / "crossref_cache"
    fulltext_text_dir = output_dir / "fulltext" / "text"

    if enabled:
        if max_queries is not None:
            try:
                max_queries = int(max_queries)
            except (TypeError, ValueError):
                max_queries = None
        if max_secondary_queries is not None:
            try:
                max_secondary_queries = int(max_secondary_queries)
            except (TypeError, ValueError):
                max_secondary_queries = None
        timeout = int(backfill_cfg.get("request_timeout_seconds", 12))
        max_consecutive_errors = int(backfill_cfg.get("max_consecutive_errors", 6))
        client = OpenAlexClient(
            base_url=cfg["openalex_base_url"],
            email=cfg["email"],
            per_page=int(cfg.get("retrieval", {}).get("per_page", 200)),
            timeout=timeout,
            cache_dir=cache_dir,
        )
        crossref_client = CrossrefClient(email=str(cfg.get("email", "") or ""), timeout=timeout, cache_dir=crossref_cache_dir)
        secondary_cache: dict[tuple[str, str], tuple[str, str]] = {}

        remaining_missing = canonical[_is_missing_abstract(canonical["abstract"]) & selected_scope_mask].copy()
        consecutive_errors = 0
        for idx, row in remaining_missing.iterrows():
            if max_queries is not None and stats["attempted_openalex_queries"] >= max_queries:
                pass
            if consecutive_errors >= max_consecutive_errors:
                break
            fetched_abstract = ""
            fetched_source = ""
            pid = str(row.get("canonical_paper_id", "") or "").strip()
            doi_norm = _normalize_doi(row.get("doi", ""))

            openalex_ids = []
            openalex_ids.extend(_extract_ids(row.get("openalex_id", "")))
            openalex_ids.extend(_extract_ids(row.get("all_openalex_ids", "")))
            # Preserve order and de-duplicate.
            dedup_openalex_ids = list(dict.fromkeys(openalex_ids))

            if max_queries is None or stats["attempted_openalex_queries"] < max_queries:
                for oa_id in dedup_openalex_ids:
                    if max_queries is not None and stats["attempted_openalex_queries"] >= max_queries:
                        break
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
                    fetched_abstract = _strip_markup(invert_abstract_index(work.get("abstract_inverted_index", {})))
                    if _is_plausible_abstract(fetched_abstract):
                        fetched_source = f"openalex_id:{oa_id}"
                        break
                    fetched_abstract = ""
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
                        fetched_abstract = _strip_markup(invert_abstract_index(work.get("abstract_inverted_index", {})))
                        if _is_plausible_abstract(fetched_abstract):
                            fetched_source = f"doi:{doi}"
                        else:
                            fetched_abstract = ""
                    if per_request_sleep_s > 0:
                        time.sleep(per_request_sleep_s)

            if not fetched_abstract and (max_secondary_queries is None or stats["attempted_secondary_queries"] < max_secondary_queries):
                secondary_steps: list[tuple[str, object]] = [
                    ("crossref", lambda: _fetch_crossref_abstract(doi_norm, crossref_client)),
                    ("doi_csl_json", lambda: _fetch_datacite_abstract(doi_norm, timeout, str(cfg.get("email", "") or ""))),
                    ("pubmed", lambda: _fetch_pubmed_abstract(doi_norm, timeout, str(cfg.get("email", "") or ""))),
                    ("europe_pmc", lambda: _fetch_europepmc_abstract(doi_norm, timeout, str(cfg.get("email", "") or ""))),
                    ("semantic_scholar", lambda: _fetch_semantic_scholar_abstract(doi_norm, timeout, str(cfg.get("email", "") or ""))),
                    ("fulltext_heuristic", lambda: _extract_abstract_from_fulltext_text(pid, fulltext_text_dir)),
                    ("website_scrape", lambda: _fetch_website_abstract(doi_norm, timeout, str(cfg.get("email", "") or ""))),
                ]
                for source_key, fetch_fn in secondary_steps:
                    if source_key not in {"fulltext_heuristic"} and not doi_norm:
                        continue
                    if max_secondary_queries is not None and stats["attempted_secondary_queries"] >= max_secondary_queries:
                        break
                    cache_key = (source_key, doi_norm if source_key != "fulltext_heuristic" else pid)
                    stats["attempted_secondary_queries"] += 1
                    stats["attempted_by_source"][source_key] += 1
                    if cache_key in secondary_cache:
                        candidate_abstract, candidate_source = secondary_cache[cache_key]
                    else:
                        try:
                            candidate_abstract, candidate_source = fetch_fn()
                        except Exception:
                            candidate_abstract, candidate_source = "", ""
                            stats["secondary_errors"] += 1
                            stats["errors_by_source"][source_key] += 1
                        secondary_cache[cache_key] = (candidate_abstract, candidate_source)
                    candidate_abstract = _strip_markup(candidate_abstract)
                    if _is_plausible_abstract(candidate_abstract):
                        fetched_abstract = candidate_abstract
                        fetched_source = candidate_source or source_key
                        stats["successful_secondary_backfills"] += 1
                        stats["successful_by_source"][source_key] += 1
                        break
                    if per_request_sleep_s > 0:
                        time.sleep(per_request_sleep_s)

            if fetched_abstract:
                canonical.at[idx, "abstract"] = fetched_abstract
                canonical.at[idx, "abstract_backfill_source"] = fetched_source or "openalex_backfill"
                canonical.at[idx, "abstract_backfill_quality"] = _source_quality(fetched_source or "openalex_backfill")
                if str(fetched_source).startswith("openalex_") or str(fetched_source).startswith("doi:"):
                    stats["successful_openalex_backfills"] += 1

    # Normalize quality tags for all rows with known source.
    known_source_mask = canonical["abstract_backfill_source"].map(_clean_text).astype(str) != ""
    empty_quality_mask = canonical["abstract_backfill_quality"].map(_clean_text).astype(str) == ""
    for idx in canonical[known_source_mask & empty_quality_mask].index:
        src = _clean_text(canonical.at[idx, "abstract_backfill_source"])
        canonical.at[idx, "abstract_backfill_quality"] = _source_quality(src)

    missing_after = _is_missing_abstract(canonical["abstract"])
    missing_after_scope = missing_after & selected_scope_mask
    stats["missing_after_all"] = int(missing_after.sum())
    stats["missing_after_scope"] = int(missing_after_scope.sum())
    stats["filled_total_scope"] = int(stats["missing_before_scope"] - stats["missing_after_scope"])

    canonical.to_csv(canonical_path, index=False)

    scored_path = graph_dir / "scored_papers.csv"
    if scored_path.exists():
        scored = pd.read_csv(scored_path, low_memory=False)
        scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
        canonical_abstracts = canonical[
            ["canonical_paper_id", "abstract", "abstract_backfill_source", "abstract_backfill_quality"]
        ].copy()
        scored = scored.drop(
            columns=["abstract", "abstract_backfill_source", "abstract_backfill_quality"], errors="ignore"
        )
        scored = scored.merge(canonical_abstracts, on="canonical_paper_id", how="left")
        scored.to_csv(scored_path, index=False)

    # Keep post-selection corpus artifacts in sync now that downstream stages consume them.
    canonical_abstracts = canonical[
        ["canonical_paper_id", "abstract", "abstract_backfill_source", "abstract_backfill_quality"]
    ].copy()
    for fname in ["core_corpus_selected.csv", "core_corpus_tracked_with_t4.csv"]:
        path = graph_dir / fname
        if not path.exists():
            continue
        frame = pd.read_csv(path, low_memory=False)
        if "canonical_paper_id" not in frame.columns:
            continue
        frame["canonical_paper_id"] = frame["canonical_paper_id"].astype(str)
        frame = frame.drop(
            columns=["abstract", "abstract_backfill_source", "abstract_backfill_quality"], errors="ignore"
        )
        frame = frame.merge(canonical_abstracts, on="canonical_paper_id", how="left")
        frame.to_csv(path, index=False)

    # Apply "hold missing abstracts" only after all backfill attempts have run.
    hold_path = graph_dir / "papers_on_hold_missing_abstract.csv"
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
    hold_df = pd.DataFrame(columns=hold_columns)
    if hold_missing_abstracts_from_graph:
        previous_hold_df = pd.DataFrame(columns=hold_columns)
        if hold_path.exists():
            previous_hold_df = pd.read_csv(hold_path, low_memory=False)
            if "canonical_paper_id" in previous_hold_df.columns:
                previous_hold_df["canonical_paper_id"] = previous_hold_df["canonical_paper_id"].astype(str)
            for col in hold_columns:
                if col not in previous_hold_df.columns:
                    previous_hold_df[col] = ""
            previous_hold_df = previous_hold_df[hold_columns].copy()

        tracked = pd.DataFrame()
        tracked_has_ids = False
        tracked_missing_hold_df = pd.DataFrame(columns=hold_columns)
        tracked_path = graph_dir / "core_corpus_tracked_with_t4.csv"
        if tracked_path.exists():
            tracked = pd.read_csv(tracked_path, low_memory=False)
            if "canonical_paper_id" in tracked.columns:
                tracked_has_ids = True
                tracked["canonical_paper_id"] = tracked["canonical_paper_id"].astype(str)
                tracked_missing_mask = _is_missing_abstract(
                    tracked.get("abstract", pd.Series("", index=tracked.index))
                )
                if bool(tracked_missing_mask.any()):
                    tracked_missing_hold_df = tracked.loc[
                        tracked_missing_mask,
                        [
                            "canonical_paper_id",
                            "core_selection_tier",
                            "primary_topic_code",
                            "t4_id",
                            "tracked_source",
                            "doi",
                            "title",
                        ],
                    ].copy()
                    tracked_missing_hold_df["hold_reason"] = "missing_abstract_after_backfill"

        merged_hold = pd.concat([previous_hold_df, tracked_missing_hold_df], ignore_index=True)
        if "canonical_paper_id" in merged_hold.columns:
            merged_hold["canonical_paper_id"] = merged_hold["canonical_paper_id"].astype(str)
            merged_hold = merged_hold.loc[merged_hold["canonical_paper_id"].str.strip() != ""].copy()
            merged_hold = merged_hold.drop_duplicates(subset=["canonical_paper_id"], keep="last")

            missing_now_ids = set(
                canonical.loc[_is_missing_abstract(canonical["abstract"]), "canonical_paper_id"]
                .dropna()
                .astype(str)
                .tolist()
            )
            hold_df = merged_hold.loc[merged_hold["canonical_paper_id"].isin(missing_now_ids)].copy()
            hold_df = hold_df[hold_columns].copy()

            held_ids = set(hold_df["canonical_paper_id"].astype(str))
            previous_hold_ids = (
                set(previous_hold_df["canonical_paper_id"].astype(str))
                if "canonical_paper_id" in previous_hold_df.columns
                else set()
            )
            recovered_ids = previous_hold_ids - held_ids
            if tracked_path.exists() and tracked_has_ids:
                tracked = tracked.loc[~tracked["canonical_paper_id"].astype(str).isin(held_ids)].copy()

                if recovered_ids:
                    tracked_existing_ids = set(tracked["canonical_paper_id"].astype(str))
                    recover_add_ids = sorted(recovered_ids - tracked_existing_ids)
                    if recover_add_ids:
                        recover_map = previous_hold_df.set_index("canonical_paper_id").to_dict("index")
                        recovered_rows = pd.DataFrame()
                        if scored_path.exists():
                            scored_full = pd.read_csv(scored_path, low_memory=False)
                            if "canonical_paper_id" in scored_full.columns:
                                scored_full["canonical_paper_id"] = scored_full["canonical_paper_id"].astype(str)
                                recovered_rows = scored_full.loc[
                                    scored_full["canonical_paper_id"].isin(recover_add_ids)
                                ].copy()
                        if not recovered_rows.empty:
                            recovered_rows["core_selection_tier"] = recovered_rows["canonical_paper_id"].map(
                                lambda pid: _clean_text(recover_map.get(str(pid), {}).get("core_selection_tier"))
                            )
                            recovered_rows["primary_topic_code"] = recovered_rows["canonical_paper_id"].map(
                                lambda pid: _clean_text(recover_map.get(str(pid), {}).get("primary_topic_code"))
                            )
                            recovered_rows["tracked_source"] = recovered_rows["canonical_paper_id"].map(
                                lambda pid: _clean_text(recover_map.get(str(pid), {}).get("tracked_source")) or "T1_T2_T3"
                            )
                            recovered_rows["t4_id"] = recovered_rows["canonical_paper_id"].map(
                                lambda pid: _clean_text(recover_map.get(str(pid), {}).get("t4_id"))
                            )
                            for col in tracked.columns:
                                if col not in recovered_rows.columns:
                                    recovered_rows[col] = pd.NA
                            recovered_rows = recovered_rows[tracked.columns].copy()
                            tracked = pd.concat([tracked, recovered_rows], ignore_index=True)

                tracked.to_csv(tracked_path, index=False)

            selected_path = graph_dir / "core_corpus_selected.csv"
            if selected_path.exists():
                selected = pd.read_csv(selected_path, low_memory=False)
                if "canonical_paper_id" in selected.columns:
                    selected["canonical_paper_id"] = selected["canonical_paper_id"].astype(str)
                    selected = selected.loc[~selected["canonical_paper_id"].astype(str).isin(held_ids)].copy()
                    if recovered_ids and tracked_path.exists() and tracked_has_ids and not tracked.empty:
                        selected_existing_ids = set(selected["canonical_paper_id"].astype(str))
                        tracked_recovered = tracked.loc[
                            tracked["canonical_paper_id"].astype(str).isin(recovered_ids)
                        ].copy()
                        if "core_selection_tier" in tracked_recovered.columns:
                            tracked_recovered = tracked_recovered.loc[
                                tracked_recovered["core_selection_tier"].astype(str).str.upper() != "T4"
                            ].copy()
                        tracked_recovered = tracked_recovered.loc[
                            ~tracked_recovered["canonical_paper_id"].astype(str).isin(selected_existing_ids)
                        ].copy()
                        if not tracked_recovered.empty:
                            for col in selected.columns:
                                if col not in tracked_recovered.columns:
                                    tracked_recovered[col] = pd.NA
                            tracked_recovered = tracked_recovered[selected.columns].copy()
                            selected = pd.concat([selected, tracked_recovered], ignore_index=True)
                    selected.to_csv(selected_path, index=False)
    hold_df.to_csv(hold_path, index=False)
    stats["hold_missing_abstracts_enabled"] = bool(hold_missing_abstracts_from_graph)
    stats["hold_missing_abstracts_count"] = int(len(hold_df))

    stats_path = raw_dir / "abstract_backfill_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
