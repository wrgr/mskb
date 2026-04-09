"""Best-effort full-text retrieval for corpus papers.

Writes:
- outputs/fulltext/fulltext_retrieval.jsonl
- outputs/fulltext/fulltext_retrieval.csv
- outputs/fulltext/fulltext_retrieval_stats.json
- outputs/fulltext/text/<canonical_paper_id>.txt
"""

from __future__ import annotations

import argparse
import json
import re
import time
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .openalex_client import OpenAlexClient
from .utils import ensure_dir, load_config, save_json

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None


UA = (
    "Mozilla/5.0 (compatible; MSKB-Fulltext/0.1; "
    "+https://github.com/wrgr/mskb)"
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _norm_openalex_id(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text.startswith("https://openalex.org/"):
        return text
    return f"https://openalex.org/{text}"


def _extract_openalex_ids(row: pd.Series) -> list[str]:
    ids: list[str] = []
    primary = _norm_openalex_id(_clean_text(row.get("openalex_id", "")))
    if primary:
        ids.append(primary)
    all_ids = _clean_text(row.get("all_openalex_ids", ""))
    if all_ids:
        for token in all_ids.split(";"):
            oid = _norm_openalex_id(token.strip())
            if oid:
                ids.append(oid)
    # Preserve order and dedupe.
    return list(dict.fromkeys(ids))


def _extract_candidate_urls(work: dict[str, Any]) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []

    def add(url: object, kind: str) -> None:
        u = _clean_text(url)
        if not u:
            return
        urls.append((u, kind))

    add((work.get("open_access") or {}).get("oa_url"), "open_access")

    for loc in [work.get("best_oa_location"), work.get("primary_location")]:
        if isinstance(loc, dict):
            add(loc.get("pdf_url"), "pdf_url")
            add(loc.get("landing_page_url"), "landing_page_url")

    for loc in (work.get("locations") or []):
        if isinstance(loc, dict):
            add(loc.get("pdf_url"), "pdf_url")
            add(loc.get("landing_page_url"), "landing_page_url")

    pmcid = _clean_text((work.get("ids") or {}).get("pmcid"))
    if pmcid:
        if pmcid.startswith("http"):
            add(pmcid, "pmcid")
        elif pmcid.upper().startswith("PMC"):
            add(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid.upper()}/", "pmcid")

    # Dedupe preserving order.
    dedup: list[tuple[str, str]] = []
    seen: set[str] = set()
    for u, k in urls:
        if u in seen:
            continue
        seen.add(u)
        dedup.append((u, k))
    return dedup


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_pdf_text(blob: bytes) -> str:
    if not blob or PdfReader is None:
        return ""
    try:
        reader = PdfReader(BytesIO(blob))
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        text = " ".join(pages)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""


def _fetch_text_from_url(
    session: requests.Session,
    url: str,
    timeout_seconds: int,
    max_bytes: int,
    min_chars: int,
) -> tuple[str, str, str]:
    """Return (text, final_url, error)."""
    try:
        resp = session.get(url, timeout=timeout_seconds, allow_redirects=True)
    except Exception as exc:
        return "", "", f"request_error:{type(exc).__name__}"

    if resp.status_code >= 400:
        return "", "", f"http_{resp.status_code}"

    final_url = resp.url
    ctype = _clean_text(resp.headers.get("content-type", "")).lower()
    data = resp.content[:max_bytes]

    text = ""
    is_pdf = ("application/pdf" in ctype) or final_url.lower().endswith(".pdf")
    if is_pdf:
        text = _extract_pdf_text(data)
    else:
        try:
            raw = data.decode(resp.encoding or "utf-8", errors="ignore")
        except Exception:
            raw = data.decode("utf-8", errors="ignore")
        if "<html" in raw.lower() or "text/html" in ctype:
            text = _strip_html(raw)
        else:
            text = re.sub(r"\s+", " ", raw).strip()

    if len(text) < min_chars:
        return "", final_url, "text_too_short"
    return text, final_url, ""


def _load_cached_works(cache_dir: Path) -> dict[str, dict[str, Any]]:
    works: dict[str, dict[str, Any]] = {}
    if not cache_dir.exists():
        return works
    for path in cache_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        oid = _clean_text(payload.get("id", ""))
        if oid.startswith("https://openalex.org/W"):
            works[oid] = payload
    return works


def run(config_path: str, scope: str, max_papers: int | None, max_openalex_lookups: int) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    outdir = root / cfg["output_dir"]
    norm_dir = outdir / "normalized"
    graph_dir = outdir / "graph"
    raw_dir = outdir / "raw"
    fulltext_dir = outdir / "fulltext"
    text_dir = fulltext_dir / "text"
    ensure_dir(fulltext_dir)
    ensure_dir(text_dir)

    if scope == "selected":
        papers_path = graph_dir / "core_corpus_selected.csv"
        if not papers_path.exists():
            raise FileNotFoundError(f"Missing {papers_path}")
    else:
        papers_path = norm_dir / "canonical_papers.csv"
        if not papers_path.exists():
            raise FileNotFoundError(f"Missing {papers_path}")

    papers = pd.read_csv(papers_path, low_memory=False)
    papers["canonical_paper_id"] = papers["canonical_paper_id"].astype(str)
    if max_papers is not None and max_papers > 0:
        papers = papers.head(max_papers).copy()

    jsonl_path = fulltext_dir / "fulltext_retrieval.jsonl"
    done_ids: set[str] = set()
    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    pid = _clean_text(row.get("canonical_paper_id", ""))
                    if pid:
                        done_ids.add(pid)
                except Exception:
                    continue

    cached_works = _load_cached_works(raw_dir / "openalex_cache")
    client = OpenAlexClient(
        base_url=cfg["openalex_base_url"],
        email=cfg["email"],
        per_page=int(cfg.get("retrieval", {}).get("per_page", 200)),
        timeout=20,
        cache_dir=raw_dir / "openalex_cache",
    )

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    timeout_seconds = 25
    max_bytes = 25 * 1024 * 1024
    min_chars = 1000
    openalex_lookups = 0

    stats = {
        "scope": scope,
        "total_input_papers": int(len(papers)),
        "skipped_already_done": 0,
        "openalex_cache_hits": 0,
        "openalex_api_lookups": 0,
        "openalex_api_not_found": 0,
        "openalex_api_errors": 0,
        "fulltext_success": 0,
        "fulltext_fail": 0,
    }

    with jsonl_path.open("a", encoding="utf-8") as out:
        for i, (_, row) in enumerate(papers.iterrows(), start=1):
            pid = str(row["canonical_paper_id"])
            if pid in done_ids:
                stats["skipped_already_done"] += 1
                continue

            work = None
            work_source = ""
            oa_ids = _extract_openalex_ids(row)
            for oid in oa_ids:
                if oid in cached_works:
                    work = cached_works[oid]
                    work_source = "cache"
                    stats["openalex_cache_hits"] += 1
                    break

            if work is None and openalex_lookups < max_openalex_lookups:
                for oid in oa_ids:
                    try:
                        openalex_lookups += 1
                        work = client.get_work_by_openalex_id(oid)
                        stats["openalex_api_lookups"] = openalex_lookups
                    except Exception:
                        stats["openalex_api_errors"] += 1
                        work = None
                    if work:
                        work_source = "openalex_api"
                        break
                if work is None:
                    stats["openalex_api_not_found"] += 1

            urls = _extract_candidate_urls(work or {})
            text = ""
            final_url = ""
            status = "no_url"
            source_kind = ""
            error = ""
            for url, kind in urls:
                source_kind = kind
                text, final_url, error = _fetch_text_from_url(
                    session=session,
                    url=url,
                    timeout_seconds=timeout_seconds,
                    max_bytes=max_bytes,
                    min_chars=min_chars,
                )
                if text:
                    status = "ok"
                    break
                status = "failed_url"

            if text:
                (text_dir / f"{pid}.txt").write_text(text, encoding="utf-8")
                stats["fulltext_success"] += 1
            else:
                stats["fulltext_fail"] += 1

            rec = {
                "canonical_paper_id": pid,
                "doi": _clean_text(row.get("doi", "")),
                "openalex_id": _clean_text(row.get("openalex_id", "")),
                "openalex_work_source": work_source,
                "candidate_url_count": int(len(urls)),
                "source_kind": source_kind,
                "source_url": final_url,
                "status": status,
                "error": error,
                "full_text": text,
                "full_text_chars": int(len(text)),
                "full_text_path": str((text_dir / f"{pid}.txt")) if text else "",
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")

            if i % 100 == 0:
                print(
                    f"processed={i}/{len(papers)} success={stats['fulltext_success']} "
                    f"fail={stats['fulltext_fail']} openalex_lookups={openalex_lookups}"
                )
                out.flush()
                time.sleep(0.02)

    # Materialize CSV for downstream ingestion.
    rows: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    df = pd.DataFrame(rows)
    df.to_csv(fulltext_dir / "fulltext_retrieval.csv", index=False)
    save_json(stats, fulltext_dir / "fulltext_retrieval_stats.json")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--scope", choices=["canonical", "selected"], default="canonical")
    parser.add_argument("--max-papers", type=int, default=0)
    parser.add_argument("--max-openalex-lookups", type=int, default=9000)
    args = parser.parse_args()
    max_papers = args.max_papers if args.max_papers > 0 else None
    run(
        config_path=args.config,
        scope=args.scope,
        max_papers=max_papers,
        max_openalex_lookups=max(0, int(args.max_openalex_lookups)),
    )
