"""Backfill missing abstracts in the canonical corpus from local data and OpenAlex."""

import argparse
import html as html_lib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests
from rapidfuzz import fuzz

from .openalex_client import OpenAlexClient
from .utils import ensure_dir, invert_abstract_index, load_config, normalize_name, normalize_title


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _env_bool(name: str, default: bool) -> bool:
    raw = _clean_text(os.environ.get(name, "")).lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


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


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _retry_call(
    fn: Callable[[], Any],
    *,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.6,
    max_backoff_seconds: float = 6.0,
) -> tuple[Any, str, int]:
    """Run fn with retry/backoff; return (result, final_error, retries_used)."""
    retries = max(0, int(max_retries))
    backoff = max(0.0, float(retry_backoff_seconds))
    max_backoff = max(0.0, float(max_backoff_seconds))
    last_err = ""
    for attempt in range(retries + 1):
        try:
            return fn(), "", int(attempt)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt >= retries:
                break
            if backoff > 0:
                delay = min(max_backoff, backoff * (2 ** attempt))
                time.sleep(delay)
    return None, last_err, int(retries)


def _request_text_with_retries(
    session: requests.Session,
    *,
    url: str,
    params: Optional[dict[str, Any]] = None,
    timeout: int = 10,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.6,
    headers: Optional[dict[str, str]] = None,
) -> tuple[str, str, int]:
    def _do() -> str:
        resp = session.get(url, params=params, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.text

    text, err, retries_used = _retry_call(
        _do,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    return _clean_text(text), err, retries_used


def _extract_meta_tags(html_text: str) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    for raw_tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs: dict[str, str] = {}
        for match in re.finditer(r'([a-zA-Z_:.-]+)\s*=\s*([\"\'])(.*?)\2', raw_tag):
            key = match.group(1).strip().lower()
            val = html_lib.unescape(match.group(3).strip())
            attrs[key] = val
        if attrs:
            tags.append(attrs)
    return tags


def _clean_extracted_abstract(value: str) -> str:
    text = html_lib.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_ldjson_descriptions(html_text: str) -> list[str]:
    descriptions: list[str] = []
    script_pattern = re.compile(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for payload in script_pattern.findall(html_text):
        raw = payload.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue

        stack = [obj]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                desc = _clean_text(current.get("description", ""))
                if desc:
                    descriptions.append(desc)
                for v in current.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(current, list):
                for v in current:
                    if isinstance(v, (dict, list)):
                        stack.append(v)
    return descriptions


def _extract_html_abstract_candidate(html_text: str, *, min_chars: int = 120) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []
    preferred_keys = [
        "citation_abstract",
        "dc.description",
        "description",
        "og:description",
        "twitter:description",
    ]
    for attrs in _extract_meta_tags(html_text):
        content = _clean_extracted_abstract(attrs.get("content", ""))
        if not content:
            continue
        tag_key = _clean_text(attrs.get("name", "")).lower() or _clean_text(attrs.get("property", "")).lower()
        if not tag_key:
            tag_key = _clean_text(attrs.get("itemprop", "")).lower()
        if tag_key in preferred_keys:
            try:
                priority = preferred_keys.index(tag_key)
            except ValueError:
                priority = len(preferred_keys)
            candidates.append((priority, f"meta:{tag_key}", content))

    for desc in _extract_ldjson_descriptions(html_text):
        cleaned = _clean_extracted_abstract(desc)
        if cleaned:
            candidates.append((len(preferred_keys), "ldjson:description", cleaned))

    if not candidates:
        return "", ""

    # Prefer stronger tag keys, then longer snippets.
    candidates.sort(key=lambda x: (x[0], -len(x[2])))
    for _prio, source, text in candidates:
        if len(text) >= int(min_chars):
            return text, source
    return "", ""


def _html_fallback_from_doi_meta(
    session: requests.Session,
    *,
    doi: str,
    timeout: int,
    max_retries: int,
    retry_backoff_seconds: float,
    min_chars: int = 120,
) -> tuple[str, str, dict[str, Any]]:
    details: dict[str, Any] = {"query_doi": doi, "error": "", "retries_used": 0, "source": "", "chars": 0}
    doi_text = _clean_text(doi)
    if not doi_text:
        details["error"] = "missing_doi"
        return "", "", details
    if doi_text.lower().startswith("doi:"):
        doi_text = doi_text[4:].strip()
    if doi_text.lower().startswith("http://doi.org/") or doi_text.lower().startswith("https://doi.org/"):
        doi_url = doi_text
    else:
        doi_url = f"https://doi.org/{doi_text}"

    html_text, err, retries_used = _request_text_with_retries(
        session,
        url=doi_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
    )
    details["retries_used"] = int(retries_used)
    if err:
        details["error"] = err
        return "", "", details

    abstract, source = _extract_html_abstract_candidate(html_text, min_chars=min_chars)
    if abstract:
        details["source"] = source
        details["chars"] = int(len(abstract))
        return abstract, f"doi_html:{source}", details

    details["error"] = "no_html_abstract_candidate"
    return "", "", details


def _first_author_last_name_from_work(work: dict) -> str:
    authorships = work.get("authorships", []) or []
    if not authorships:
        return ""
    display = ((authorships[0].get("author") or {}).get("display_name")) or ""
    norm = normalize_name(display)
    return norm.split()[-1] if norm else ""


def _extract_pmid_from_work(work: dict) -> str:
    ids = work.get("ids") or {}
    raw = _clean_text(ids.get("pmid", ""))
    if not raw:
        return ""
    match = re.search(r"(\d+)", raw)
    return match.group(1) if match else ""


def _title_similarity(a: str, b: str) -> float:
    norm_a = normalize_title(a)
    norm_b = normalize_title(b)
    if not norm_a or not norm_b:
        return 0.0
    return float(fuzz.token_set_ratio(norm_a, norm_b))


def _choose_best_openalex_title_match_meta(
    works: list[dict],
    target_title: str,
    target_first_author: str,
    target_year: Optional[int],
    min_title_similarity: float,
    max_year_delta: int,
) -> tuple[Optional[dict], dict[str, Any]]:
    target_author_norm = normalize_name(target_first_author)
    target_last = target_author_norm.split()[-1] if target_author_norm else ""

    best_work: Optional[dict] = None
    best_similarity = 0.0
    best_meta: dict[str, Any] = {}
    for work in works:
        work_title = _clean_text(work.get("title", ""))
        if not work_title:
            continue
        sim = _title_similarity(target_title, work_title)
        if sim < min_title_similarity:
            continue

        work_year = work.get("publication_year")
        year_delta: Optional[int] = None
        if target_year is not None and work_year is not None:
            try:
                year_delta = abs(int(work_year) - int(target_year))
                if year_delta > max_year_delta:
                    continue
            except (TypeError, ValueError):
                year_delta = None

        author_match = None
        if target_last:
            work_last = _first_author_last_name_from_work(work)
            if work_last:
                author_match = bool(work_last == target_last)
                if not author_match:
                    continue

        if sim > best_similarity:
            best_similarity = sim
            best_work = work
            best_meta = {
                "match_similarity": round(float(sim), 4),
                "match_year_delta": year_delta,
                "match_author_last_name": target_last,
                "match_author_last_name_ok": author_match,
                "matched_openalex_id": _clean_text(work.get("id", "")),
                "matched_title": work_title,
                "matched_year": work_year,
            }
    return best_work, best_meta


def _choose_best_openalex_title_match(
    works: list[dict],
    target_title: str,
    target_first_author: str,
    target_year: Optional[int],
    min_title_similarity: float,
    max_year_delta: int,
) -> Optional[dict]:
    best_work, _ = _choose_best_openalex_title_match_meta(
        works=works,
        target_title=target_title,
        target_first_author=target_first_author,
        target_year=target_year,
        min_title_similarity=min_title_similarity,
        max_year_delta=max_year_delta,
    )
    return best_work


def _pubmed_esearch(
    session: requests.Session,
    term: str,
    timeout: int = 10,
    retmax: int = 5,
    *,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.6,
) -> tuple[list[str], str, int]:
    if not _clean_text(term):
        return [], "", 0
    text, err, retries_used = _request_text_with_retries(
        session,
        url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "retmode": "xml", "term": term, "retmax": int(retmax)},
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    if err or not text:
        return [], err or "pubmed_esearch_request_failed", retries_used
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], "pubmed_esearch_xml_parse_error", retries_used
    ids = [node.text.strip() for node in root.findall(".//IdList/Id") if node.text and node.text.strip()]
    return ids, "", retries_used


def _pubmed_efetch_records(
    session: requests.Session,
    pmids: list[str],
    timeout: int = 10,
    *,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.6,
) -> tuple[dict[str, dict[str, str]], str, int]:
    if not pmids:
        return {}, "", 0
    text, err, retries_used = _request_text_with_retries(
        session,
        url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    if err or not text:
        return {}, err or "pubmed_efetch_request_failed", retries_used
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}, "pubmed_efetch_xml_parse_error", retries_used

    records: dict[str, dict[str, str]] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid_node = article.find(".//PMID")
        if pmid_node is None or not _clean_text(pmid_node.text):
            continue
        pmid = _clean_text(pmid_node.text)
        title_node = article.find(".//ArticleTitle")
        title = ""
        if title_node is not None:
            title = " ".join("".join(title_node.itertext()).split())
        abstract_parts = []
        for node in article.findall(".//Abstract/AbstractText"):
            text = " ".join("".join(node.itertext()).split())
            if text:
                abstract_parts.append(text)
        records[pmid] = {"title": title, "abstract": " ".join(abstract_parts).strip()}
    return records, "", retries_used


def _pubmed_fetch_best_abstract(
    session: requests.Session,
    target_title: str,
    target_first_author: str,
    doi: str,
    pmid_hint: str,
    timeout: int,
    min_title_similarity: float,
) -> tuple[str, str]:
    abstract, source, _ = _pubmed_fetch_best_abstract_meta(
        session=session,
        target_title=target_title,
        target_first_author=target_first_author,
        doi=doi,
        pmid_hint=pmid_hint,
        timeout=timeout,
        min_title_similarity=min_title_similarity,
    )
    return abstract, source


def _pubmed_fetch_best_abstract_meta(
    session: requests.Session,
    target_title: str,
    target_first_author: str,
    doi: str,
    pmid_hint: str,
    timeout: int,
    min_title_similarity: float,
    *,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.6,
) -> tuple[str, str, dict[str, Any]]:
    details: dict[str, Any] = {
        "pmid_hint": _clean_text(pmid_hint),
        "pmids_from_doi": [],
        "pmids_from_title_author": [],
        "pmids_considered": [],
        "selected_pmid": "",
        "selected_similarity": 0.0,
        "errors": [],
        "retries_used": {},
    }
    # 1) Direct PMID hint from OpenAlex ids payload (most reliable)
    if pmid_hint:
        records, efetch_err, efetch_retries = _pubmed_efetch_records(
            session,
            [pmid_hint],
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        details["retries_used"]["pmid_hint_efetch"] = int(efetch_retries)
        if efetch_err:
            details["errors"].append(f"pmid_hint_efetch: {efetch_err}")
        rec = records.get(pmid_hint, {})
        abstract = _clean_text(rec.get("abstract", ""))
        if abstract:
            details["pmids_considered"] = [pmid_hint]
            details["selected_pmid"] = pmid_hint
            details["selected_similarity"] = 1.0
            return abstract, f"pubmed_pmid:{pmid_hint}", details

    # 2) DOI-to-PMID search
    doi_norm = _clean_text(doi).replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    pmids: list[str] = []
    if doi_norm:
        pmids, esearch_err, esearch_retries = _pubmed_esearch(
            session,
            f"{doi_norm}[AID]",
            timeout=timeout,
            retmax=5,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        details["retries_used"]["doi_esearch"] = int(esearch_retries)
        if esearch_err:
            details["errors"].append(f"doi_esearch: {esearch_err}")
        details["pmids_from_doi"] = pmids

    # 3) Title + first author search if DOI did not resolve
    if not pmids:
        author_norm = normalize_name(target_first_author)
        author_last = author_norm.split()[-1] if author_norm else ""
        title_q = _clean_text(target_title)
        if title_q:
            query = f"\"{title_q}\"[Title]"
            if author_last:
                query = f"{query} AND {author_last}[Author]"
            pmids, esearch_err, esearch_retries = _pubmed_esearch(
                session,
                query,
                timeout=timeout,
                retmax=5,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            details["retries_used"]["title_author_esearch"] = int(esearch_retries)
            if esearch_err:
                details["errors"].append(f"title_author_esearch: {esearch_err}")
            details["pmids_from_title_author"] = pmids

    if not pmids:
        return "", "", details

    records, efetch_err, efetch_retries = _pubmed_efetch_records(
        session,
        pmids,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    details["retries_used"]["candidate_pmids_efetch"] = int(efetch_retries)
    if efetch_err:
        details["errors"].append(f"candidate_pmids_efetch: {efetch_err}")
    details["pmids_considered"] = pmids
    target_norm_title = _clean_text(target_title)
    best_abstract = ""
    best_source = ""
    best_sim = 0.0
    for pmid in pmids:
        rec = records.get(pmid, {})
        title = _clean_text(rec.get("title", ""))
        abstract = _clean_text(rec.get("abstract", ""))
        if not title or not abstract:
            continue
        sim = _title_similarity(target_norm_title, title)
        if sim < min_title_similarity:
            continue
        if sim > best_sim:
            best_sim = sim
            best_abstract = abstract
            best_source = f"pubmed_pmid:{pmid}"
            details["selected_pmid"] = pmid
            details["selected_similarity"] = round(float(sim), 4)
    return best_abstract, best_source, details


def _is_missing_abstract(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().str.lower().isin(["", "nan"])


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _load_manual_decision_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            rows = payload.get("decisions") or payload.get("updates") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        return [row for row in rows if isinstance(row, dict)]
    if suffix == ".csv":
        frame = pd.read_csv(path, dtype=str).fillna("")
        return frame.to_dict(orient="records")
    raise ValueError(f"Unsupported manual decision file format: {path}")


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

    backfill_cfg = cfg.get("abstract_backfill", {}) or {}
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
        selected_scope_mask = canonical["canonical_paper_id"].astype(str).isin(selected_scope_ids)
    selected_scope_not_in_canonical = set(selected_scope_ids) - set(canonical["canonical_paper_id"].astype(str))

    missing_before = _is_missing_abstract(canonical["abstract"])
    missing_ids_before = set(canonical.loc[missing_before & selected_scope_mask, "canonical_paper_id"].astype(str))

    stats = {
        "total_canonical_papers": int(len(canonical)),
        "missing_before_all": int(missing_before.sum()),
        "missing_before_scope": int(len(missing_ids_before)),
        "selected_scope_enabled": bool(selected_scope_enabled),
        "selected_scope_size": int(selected_scope_mask.sum()),
        "selected_scope_ids_not_in_canonical": int(len(selected_scope_not_in_canonical)),
        "manual_decisions_loaded": 0,
        "manual_decisions_applied": 0,
        "manual_decisions_skipped_missing_text": 0,
        "manual_decisions_skipped_outside_scope": 0,
        "manual_decisions_not_in_canonical": 0,
        "manual_decisions_skipped_existing_abstract": 0,
        "filled_from_candidate_versions": 0,
        "attempted_openalex_queries": 0,
        "attempted_secondary_queries": 0,
        "successful_secondary_backfills": 0,
        "attempted_html_fallbacks": 0,
        "successful_html_backfills": 0,
        "successful_openalex_backfills": 0,
        "openalex_errors": 0,
        "missing_after_all": 0,
        "missing_after_scope": 0,
    }
    trace_enabled = bool(backfill_cfg.get("verbose_trace", False))
    trace_overwrite = bool(backfill_cfg.get("trace_overwrite", True))
    trace_jsonl_path = raw_dir / "abstract_backfill_trace.jsonl"
    trace_summary_path = raw_dir / "abstract_backfill_trace_summary.csv"
    trace_not_in_canonical_path = raw_dir / "abstract_backfill_selected_not_in_canonical.csv"
    trace_rows: list[dict[str, Any]] = []
    if trace_enabled:
        if trace_overwrite:
            trace_jsonl_path.unlink(missing_ok=True)
        if selected_scope_not_in_canonical:
            pd.DataFrame(
                {"canonical_paper_id": sorted(selected_scope_not_in_canonical)}
            ).to_csv(trace_not_in_canonical_path, index=False)
        else:
            pd.DataFrame(columns=["canonical_paper_id"]).to_csv(trace_not_in_canonical_path, index=False)

    # Pass 1: apply explicit manual expert decisions before API lookups.
    manual_cfg = backfill_cfg.get("manual_decisions", {}) or {}
    manual_enabled = bool(manual_cfg.get("enabled", False))
    manual_updates: list[dict[str, Any]] = []
    manual_not_in_canonical: list[dict[str, Any]] = []
    if manual_enabled:
        manual_path_rel = _clean_text(manual_cfg.get("path", ""))
        if not manual_path_rel:
            raise ValueError("abstract_backfill.manual_decisions.enabled=true but no path is configured")
        manual_path = root / manual_path_rel
        if not manual_path.exists():
            raise FileNotFoundError(f"Manual abstract decision file not found: {manual_path}")
        id_column = _clean_text(manual_cfg.get("id_column", "canonical_paper_id")) or "canonical_paper_id"
        abstract_column = _clean_text(manual_cfg.get("abstract_column", "manual_abstract")) or "manual_abstract"
        overwrite_existing = bool(manual_cfg.get("overwrite_existing", False))
        source_label_default = _clean_text(manual_cfg.get("source_label", "manual_expert")) or "manual_expert"
        source_column = _clean_text(manual_cfg.get("source_column", "source")) or "source"
        reviewer_column = _clean_text(manual_cfg.get("reviewer_column", "verified_by")) or "verified_by"
        reason_column = _clean_text(manual_cfg.get("reason_column", "reason")) or "reason"
        source_url_column = _clean_text(manual_cfg.get("source_url_column", "source_url")) or "source_url"
        decision_tag_column = _clean_text(manual_cfg.get("decision_tag_column", "decision_tag")) or "decision_tag"
        website_note_column = _clean_text(manual_cfg.get("website_note_column", "website_note")) or "website_note"
        citation_column = _clean_text(manual_cfg.get("citation_column", "citation")) or "citation"
        provenance_enabled = bool(manual_cfg.get("write_provenance", True))
        provenance_source = _clean_text(manual_cfg.get("provenance_source", source_label_default)) or source_label_default

        rows = _load_manual_decision_rows(manual_path)
        stats["manual_decisions_loaded"] = int(len(rows))
        for raw in rows:
            pid = _clean_text(raw.get(id_column, ""))
            manual_abstract = _clean_text(raw.get(abstract_column, ""))
            if not pid:
                continue
            if not manual_abstract:
                stats["manual_decisions_skipped_missing_text"] = int(stats["manual_decisions_skipped_missing_text"]) + 1
                continue
            selector = canonical["canonical_paper_id"].astype(str).eq(pid)
            if not selector.any():
                stats["manual_decisions_not_in_canonical"] = int(stats["manual_decisions_not_in_canonical"]) + 1
                manual_not_in_canonical.append(
                    {
                        "canonical_paper_id": pid,
                        "reason": "not_in_canonical",
                        "source_url": _clean_text(raw.get(source_url_column, "")),
                    }
                )
                continue
            if selected_scope_enabled and not bool((selector & selected_scope_mask).any()):
                stats["manual_decisions_skipped_outside_scope"] = int(stats["manual_decisions_skipped_outside_scope"]) + 1
                continue

            scoped_selector = selector & selected_scope_mask
            if not overwrite_existing:
                existing_present = (~_is_missing_abstract(canonical.loc[scoped_selector, "abstract"])).any()
                if bool(existing_present):
                    stats["manual_decisions_skipped_existing_abstract"] = int(stats["manual_decisions_skipped_existing_abstract"]) + 1
                    continue

            source_label = _clean_text(raw.get(source_column, "")) or source_label_default
            reviewer = _clean_text(raw.get(reviewer_column, ""))
            source_token = source_label if not reviewer else f"{source_label}:{reviewer}"
            canonical.loc[scoped_selector, "abstract"] = manual_abstract
            canonical.loc[scoped_selector, "abstract_backfill_source"] = source_token
            stats["manual_decisions_applied"] = int(stats["manual_decisions_applied"]) + int(scoped_selector.sum())

            sample_row = canonical.loc[scoped_selector].head(1)
            title = _clean_text(sample_row["title"].iloc[0]) if not sample_row.empty and "title" in sample_row.columns else ""
            doi = _clean_text(sample_row["doi"].iloc[0]) if not sample_row.empty and "doi" in sample_row.columns else ""
            openalex_id = (
                _clean_text(sample_row["openalex_id"].iloc[0])
                if not sample_row.empty and "openalex_id" in sample_row.columns
                else ""
            )
            update_obj = {
                "canonical_paper_id": pid,
                "title": title,
                "doi": doi,
                "openalex_id": openalex_id,
                "updated_rows": int(scoped_selector.sum()),
                "abstract_chars": int(len(manual_abstract)),
                "verified_by": reviewer,
                "reason": _clean_text(raw.get(reason_column, "")),
                "source_url": _clean_text(raw.get(source_url_column, "")),
                "decision_tag": _clean_text(raw.get(decision_tag_column, "")),
                "website_note": _clean_text(raw.get(website_note_column, "")),
                "citation": _clean_text(raw.get(citation_column, "")),
            }
            manual_updates.append(update_obj)
            if trace_enabled:
                trace_obj = {
                    "canonical_paper_id": pid,
                    "stage": "manual_decision",
                    "recovered": True,
                    "source": source_token,
                    "reason": update_obj["reason"],
                    "source_url": update_obj["source_url"],
                    "decision_tag": update_obj["decision_tag"],
                }
                _append_jsonl(trace_jsonl_path, trace_obj)
                trace_rows.append(
                    {
                        "canonical_paper_id": pid,
                        "title": title,
                        "year": "",
                        "doi": doi,
                        "openalex_id": openalex_id,
                        "all_openalex_ids": "",
                        "recovered": True,
                        "recovered_source": source_token,
                        "recovered_abstract_chars": int(len(manual_abstract)),
                        "attempted_openalex_id_lookups": 0,
                        "attempted_doi_lookup": 0,
                        "attempted_title_author_openalex_search": 0,
                        "attempted_pubmed": 0,
                        "attempted_html": 0,
                        "stop_reason": "manual_decision",
                    }
                )

        if provenance_enabled and manual_updates:
            provenance_dir = output_dir / "provenance"
            ensure_dir(provenance_dir)
            ts = datetime.now(timezone.utc)
            stamp = ts.strftime("%Y%m%dT%H%M%SZ")
            payload = {
                "updated_at_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": provenance_source,
                "input_file": str(manual_path),
                "updates": manual_updates,
                "not_in_canonical": manual_not_in_canonical,
            }
            (provenance_dir / f"manual_abstract_updates_{stamp}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    # Pass 2: recover from any candidate version in local raw output.
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
            stats["filled_from_candidate_versions"] = int(selector.sum())
            if trace_enabled:
                for pid in canonical.loc[selector, "canonical_paper_id"].astype(str).tolist():
                    trace_obj = {
                        "canonical_paper_id": pid,
                        "stage": "candidate_version_recovery",
                        "recovered": True,
                        "source": "candidate_version",
                    }
                    _append_jsonl(trace_jsonl_path, trace_obj)
                    trace_rows.append(
                        {
                            "canonical_paper_id": pid,
                            "title": "",
                            "year": "",
                            "doi": "",
                            "openalex_id": "",
                            "all_openalex_ids": "",
                            "recovered": True,
                            "recovered_source": "candidate_version",
                            "attempted_openalex_id_lookups": 0,
                            "attempted_doi_lookup": 0,
                            "attempted_title_author_openalex_search": 0,
                            "attempted_pubmed": 0,
                            "stop_reason": "candidate_version",
                        }
                    )

    # Pass 3: query OpenAlex for remaining missing abstracts.
    max_queries = backfill_cfg.get("max_openalex_queries")
    env_max_queries = _clean_text(os.environ.get("MSKB_MAX_OPENALEX_QUERIES", ""))
    if env_max_queries:
        max_queries = env_max_queries
    per_request_sleep_s = float(backfill_cfg.get("sleep_seconds", 0.03))
    max_secondary_queries = backfill_cfg.get("max_secondary_queries")
    env_max_secondary = _clean_text(os.environ.get("MSKB_MAX_SECONDARY_QUERIES", ""))
    if env_max_secondary:
        max_secondary_queries = env_max_secondary
    if max_secondary_queries is not None:
        try:
            max_secondary_queries = int(max_secondary_queries)
        except (TypeError, ValueError):
            max_secondary_queries = None

    secondary_title_min_similarity = float(backfill_cfg.get("title_author_min_similarity", 88.0))
    secondary_max_year_delta = int(backfill_cfg.get("title_author_max_year_delta", 3))
    secondary_openalex_search_results = int(backfill_cfg.get("title_author_max_search_results", 8))
    fetch_max_retries = max(0, int(backfill_cfg.get("fetch_max_retries", 2)))
    fetch_retry_backoff_seconds = max(0.0, float(backfill_cfg.get("fetch_retry_backoff_seconds", 0.6)))

    pubmed_cfg = backfill_cfg.get("pubmed_fallback", {}) or {}
    pubmed_enabled = bool(pubmed_cfg.get("enabled", True))
    pubmed_timeout = int(pubmed_cfg.get("timeout_seconds", 10))
    pubmed_min_similarity = float(pubmed_cfg.get("min_title_similarity", 85.0))
    html_cfg = backfill_cfg.get("html_fallback", {}) or {}
    html_enabled = bool(html_cfg.get("enabled", True))
    html_min_chars = int(html_cfg.get("min_chars", 120))
    requests_verify_ssl = _env_bool("MSKB_SSL_VERIFY", True)
    cache_dir = raw_dir / "openalex_cache"
    pubmed_session = requests.Session()
    pubmed_session.headers.update({"User-Agent": f"mskb/0.1 ({cfg['email']})"})
    pubmed_session.verify = requests_verify_ssl
    html_session = requests.Session()
    html_session.headers.update({"User-Agent": f"mskb/0.1 ({cfg['email']})"})
    html_session.verify = requests_verify_ssl

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

        remaining_missing = canonical[_is_missing_abstract(canonical["abstract"]) & selected_scope_mask].copy()
        consecutive_errors = 0
        for idx, row in remaining_missing.iterrows():
            if max_queries is not None and stats["attempted_openalex_queries"] >= max_queries:
                break
            if consecutive_errors >= max_consecutive_errors:
                break
            fetched_abstract = ""
            fetched_source = ""
            fetched_work = None
            trace_obj: dict[str, Any] = {
                "canonical_paper_id": str(row.get("canonical_paper_id", "")),
                "title": _clean_text(row.get("title", "")),
                "year": row.get("year", ""),
                "first_author": _clean_text(row.get("first_author", "")),
                "doi": _clean_text(row.get("doi", "")),
                "openalex_id": _clean_text(row.get("openalex_id", "")),
                "all_openalex_ids": _clean_text(row.get("all_openalex_ids", "")),
                "attempts": [],
                "selected_scope_enabled": bool(selected_scope_enabled),
                "recovered": False,
                "recovered_source": "",
                "stop_reason": "",
            }
            attempted_openalex_id_lookups = 0
            attempted_doi_lookup = 0
            attempted_title_author_openalex_search = 0
            attempted_pubmed = 0
            attempted_html = 0

            openalex_ids = []
            openalex_ids.extend(_extract_ids(row.get("openalex_id", "")))
            openalex_ids.extend(_extract_ids(row.get("all_openalex_ids", "")))
            # Preserve order and de-duplicate.
            dedup_openalex_ids = list(dict.fromkeys(openalex_ids))

            for oa_id in dedup_openalex_ids:
                stats["attempted_openalex_queries"] += 1
                attempted_openalex_id_lookups += 1
                work, err, retries_used = _retry_call(
                    lambda: client.get_work_by_openalex_id(oa_id),
                    max_retries=fetch_max_retries,
                    retry_backoff_seconds=fetch_retry_backoff_seconds,
                )
                if err:
                    stats["openalex_errors"] += 1
                    consecutive_errors += 1
                if trace_enabled:
                    attempt_row = {
                        "stage": "openalex_id",
                        "query": oa_id,
                        "work_found": bool(work),
                        "error": err,
                        "retries_used": int(retries_used),
                    }
                    if work:
                        attempt_row.update(
                            {
                                "matched_openalex_id": _clean_text(work.get("id", "")),
                                "has_abstract_inverted_index": bool(work.get("abstract_inverted_index")),
                                "referenced_works_count": int(len(work.get("referenced_works") or [])),
                                "pmid_hint": _extract_pmid_from_work(work),
                            }
                        )
                    trace_obj["attempts"].append(attempt_row)
                if not work:
                    continue
                consecutive_errors = 0
                fetched_work = work
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
                    attempted_doi_lookup = 1
                    work, err, retries_used = _retry_call(
                        lambda: client.get_work_by_doi(doi.replace("https://doi.org/", "")),
                        max_retries=fetch_max_retries,
                        retry_backoff_seconds=fetch_retry_backoff_seconds,
                    )
                    if err:
                        stats["openalex_errors"] += 1
                        consecutive_errors += 1
                    if trace_enabled:
                        attempt_row = {
                            "stage": "openalex_doi",
                            "query": doi,
                            "work_found": bool(work),
                            "error": err,
                            "retries_used": int(retries_used),
                        }
                        if work:
                            attempt_row.update(
                                {
                                    "matched_openalex_id": _clean_text(work.get("id", "")),
                                    "has_abstract_inverted_index": bool(work.get("abstract_inverted_index")),
                                    "referenced_works_count": int(len(work.get("referenced_works") or [])),
                                    "pmid_hint": _extract_pmid_from_work(work),
                                }
                            )
                        trace_obj["attempts"].append(attempt_row)
                    if work:
                        consecutive_errors = 0
                        fetched_work = work
                        fetched_abstract = invert_abstract_index(work.get("abstract_inverted_index", {}))
                        if fetched_abstract:
                            fetched_source = f"doi:{doi}"
                    if per_request_sleep_s > 0:
                        time.sleep(per_request_sleep_s)

            # Secondary fallback A: OpenAlex title+author search.
            if not fetched_abstract and (max_secondary_queries is None or stats.get("attempted_secondary_queries", 0) < max_secondary_queries):
                title = _clean_text(row.get("title", ""))
                first_author = _clean_text(row.get("first_author", ""))
                row_year = row.get("year")
                row_year_int: Optional[int] = None
                try:
                    if pd.notna(row_year):
                        row_year_int = int(float(row_year))
                except (TypeError, ValueError):
                    row_year_int = None
                if title:
                    stats["attempted_secondary_queries"] = int(stats.get("attempted_secondary_queries", 0)) + 1
                    attempted_title_author_openalex_search = 1
                    works, search_err, retries_used = _retry_call(
                        lambda: client.search_works(
                            query=title,
                            max_results=max(1, secondary_openalex_search_results),
                        ),
                        max_retries=fetch_max_retries,
                        retry_backoff_seconds=fetch_retry_backoff_seconds,
                    )
                    if search_err or works is None:
                        works = []
                        stats["openalex_errors"] += 1
                        consecutive_errors += 1
                    best_work, best_meta = _choose_best_openalex_title_match_meta(
                        works=works,
                        target_title=title,
                        target_first_author=first_author,
                        target_year=row_year_int,
                        min_title_similarity=secondary_title_min_similarity,
                        max_year_delta=secondary_max_year_delta,
                    )
                    if trace_enabled:
                        trace_obj["attempts"].append(
                            {
                                "stage": "openalex_title_author",
                                "query": title,
                                "first_author": first_author,
                                "year": row_year_int,
                                "n_results": int(len(works)),
                                "error": search_err,
                                "retries_used": int(retries_used),
                                "best_match": best_meta,
                            }
                        )
                    if best_work:
                        fetched_work = best_work
                        candidate_abstract = invert_abstract_index(best_work.get("abstract_inverted_index", {}))
                        if candidate_abstract:
                            fetched_abstract = candidate_abstract
                            fetched_source = "openalex_title_author"
                            stats["successful_secondary_backfills"] = int(stats.get("successful_secondary_backfills", 0)) + 1

            # Secondary fallback B: PubMed abstract retrieval.
            if (
                not fetched_abstract
                and pubmed_enabled
                and (max_secondary_queries is None or stats.get("attempted_secondary_queries", 0) < max_secondary_queries)
            ):
                title = _clean_text(row.get("title", ""))
                first_author = _clean_text(row.get("first_author", ""))
                doi = _clean_text(row.get("doi", ""))
                pmid_hint = _extract_pmid_from_work(fetched_work or {})
                stats["attempted_secondary_queries"] = int(stats.get("attempted_secondary_queries", 0)) + 1
                attempted_pubmed = 1
                pubmed_abstract, pubmed_source, pubmed_meta = _pubmed_fetch_best_abstract_meta(
                    session=pubmed_session,
                    target_title=title,
                    target_first_author=first_author,
                    doi=doi,
                    pmid_hint=pmid_hint,
                    timeout=pubmed_timeout,
                    min_title_similarity=pubmed_min_similarity,
                    max_retries=fetch_max_retries,
                    retry_backoff_seconds=fetch_retry_backoff_seconds,
                )
                if trace_enabled:
                    trace_obj["attempts"].append(
                        {
                            "stage": "pubmed_fallback",
                            "query_title": title,
                            "query_first_author": first_author,
                            "query_doi": doi,
                            "meta": pubmed_meta,
                        }
                    )
                if pubmed_abstract:
                    fetched_abstract = pubmed_abstract
                    fetched_source = pubmed_source or "pubmed"
                    stats["successful_secondary_backfills"] = int(stats.get("successful_secondary_backfills", 0)) + 1

            # Secondary fallback C: DOI landing page HTML metadata.
            if (
                not fetched_abstract
                and html_enabled
                and (max_secondary_queries is None or stats.get("attempted_secondary_queries", 0) < max_secondary_queries)
            ):
                doi = _clean_text(row.get("doi", ""))
                if doi:
                    stats["attempted_secondary_queries"] = int(stats.get("attempted_secondary_queries", 0)) + 1
                    stats["attempted_html_fallbacks"] = int(stats.get("attempted_html_fallbacks", 0)) + 1
                    attempted_html = 1
                    html_abstract, html_source, html_meta = _html_fallback_from_doi_meta(
                        html_session,
                        doi=doi,
                        timeout=timeout,
                        max_retries=fetch_max_retries,
                        retry_backoff_seconds=fetch_retry_backoff_seconds,
                        min_chars=html_min_chars,
                    )
                    if trace_enabled:
                        trace_obj["attempts"].append(
                            {
                                "stage": "doi_html_meta_fallback",
                                "query_doi": doi,
                                "meta": html_meta,
                            }
                        )
                    if html_abstract:
                        fetched_abstract = html_abstract
                        fetched_source = html_source or "doi_html"
                        stats["successful_secondary_backfills"] = int(stats.get("successful_secondary_backfills", 0)) + 1
                        stats["successful_html_backfills"] = int(stats.get("successful_html_backfills", 0)) + 1

            if fetched_abstract:
                canonical.at[idx, "abstract"] = fetched_abstract
                canonical.at[idx, "abstract_backfill_source"] = fetched_source or "openalex_backfill"
                stats["successful_openalex_backfills"] += 1
                trace_obj["recovered"] = True
                trace_obj["recovered_source"] = fetched_source
                trace_obj["recovered_abstract_chars"] = int(len(_clean_text(fetched_abstract)))
            trace_obj["attempted_openalex_id_lookups"] = int(attempted_openalex_id_lookups)
            trace_obj["attempted_doi_lookup"] = int(attempted_doi_lookup)
            trace_obj["attempted_title_author_openalex_search"] = int(attempted_title_author_openalex_search)
            trace_obj["attempted_pubmed"] = int(attempted_pubmed)
            trace_obj["attempted_html"] = int(attempted_html)
            if trace_obj["recovered"]:
                trace_obj["stop_reason"] = "recovered"
            elif max_queries is not None and stats["attempted_openalex_queries"] >= max_queries:
                trace_obj["stop_reason"] = "openalex_query_budget_exhausted"
            elif max_secondary_queries is not None and stats.get("attempted_secondary_queries", 0) >= max_secondary_queries:
                trace_obj["stop_reason"] = "secondary_query_budget_exhausted"
            else:
                trace_obj["stop_reason"] = "no_abstract_found"
            if trace_enabled:
                _append_jsonl(trace_jsonl_path, trace_obj)
                trace_rows.append(
                    {
                        "canonical_paper_id": trace_obj["canonical_paper_id"],
                        "title": trace_obj["title"],
                        "year": trace_obj["year"],
                        "doi": trace_obj["doi"],
                        "openalex_id": trace_obj["openalex_id"],
                        "all_openalex_ids": trace_obj["all_openalex_ids"],
                        "recovered": bool(trace_obj["recovered"]),
                        "recovered_source": trace_obj["recovered_source"],
                        "recovered_abstract_chars": int(trace_obj.get("recovered_abstract_chars", 0)),
                        "attempted_openalex_id_lookups": int(trace_obj["attempted_openalex_id_lookups"]),
                        "attempted_doi_lookup": int(trace_obj["attempted_doi_lookup"]),
                        "attempted_title_author_openalex_search": int(trace_obj["attempted_title_author_openalex_search"]),
                        "attempted_pubmed": int(trace_obj["attempted_pubmed"]),
                        "attempted_html": int(trace_obj.get("attempted_html", 0)),
                        "stop_reason": trace_obj["stop_reason"],
                    }
                )

    missing_after = _is_missing_abstract(canonical["abstract"])
    missing_after_scope = missing_after & selected_scope_mask
    stats["missing_after_all"] = int(missing_after.sum())
    stats["missing_after_scope"] = int(missing_after_scope.sum())
    stats["filled_total_scope"] = int(stats["missing_before_scope"] - stats["missing_after_scope"])

    canonical.to_csv(canonical_path, index=False)

    canonical_abstracts = canonical[["canonical_paper_id", "abstract", "abstract_backfill_source"]].copy()

    scored_path = graph_dir / "scored_papers.csv"
    if scored_path.exists():
        scored = pd.read_csv(scored_path)
        scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
        scored = scored.drop(columns=["abstract", "abstract_backfill_source"], errors="ignore")
        scored = scored.merge(canonical_abstracts, on="canonical_paper_id", how="left")
        # Left-merge leaves NaN for unmatched rows; write "" so re-reads don't
        # trigger a DtypeWarning from mixed chunk-level type inference.
        scored["abstract_backfill_source"] = scored["abstract_backfill_source"].fillna("")
        scored.to_csv(scored_path, index=False)

    # Sync abstracts into the post-selection corpus snapshots so audit_kb and
    # expert_comms see recovered abstracts when they read tracked/selected CSVs.
    for selected_csv in (
        graph_dir / "core_corpus_tracked_with_t4.csv",
        graph_dir / "core_corpus_selected.csv",
    ):
        if selected_csv.exists():
            sel = pd.read_csv(selected_csv, low_memory=False)
            sel["canonical_paper_id"] = sel["canonical_paper_id"].astype(str)
            sel = sel.drop(columns=["abstract", "abstract_backfill_source"], errors="ignore")
            sel = sel.merge(canonical_abstracts, on="canonical_paper_id", how="left")
            sel.to_csv(selected_csv, index=False)

    stats_path = raw_dir / "abstract_backfill_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    if trace_enabled:
        pd.DataFrame(trace_rows).to_csv(trace_summary_path, index=False)
        print(f"trace_jsonl: {trace_jsonl_path}")
        print(f"trace_summary_csv: {trace_summary_path}")
        print(f"trace_selected_not_in_canonical_csv: {trace_not_in_canonical_path}")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
