#!/usr/bin/env python3
"""Generate MkDocs site content from pipeline outputs."""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


def _slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())[:60]


def _topic_slug(label: str, topic_id: int) -> str:
    base = _slug(label) or "topic"
    return f"{base}-{int(topic_id)}"


def _coerce_year(value) -> int | None:
    try:
        if value is None or value == "" or pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_float(value, digits: int = 6) -> float:
    return round(_safe_float(value, 0.0), digits)


def _parse_json_list(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.lower() == "nan":
            return []
        try:
            parsed = json.loads(text)
            raw = parsed if isinstance(parsed, list) else [text]
        except json.JSONDecodeError:
            raw = [text]
    else:
        raw = [value]
    cleaned = []
    for item in raw:
        text = str(item).strip()
        if text and text.lower() != "nan":
            cleaned.append(text)
    return cleaned


def _parse_jargon_structured(value) -> list[dict]:
    """Parse a jargon field into a list of ``{term, definition}`` dicts.

    The distill pipeline stores jargon as a JSON-encoded list of objects.
    This helper preserves that structure (unlike ``_parse_json_list``), so
    downstream consumers can surface the term + definition pair.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.lower() == "nan":
            return []
        try:
            parsed = json.loads(text)
            raw = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    else:
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            term = _clean_text(item.get("term"))
            definition = _clean_text(item.get("definition"))
            if term:
                out.append({"term": term, "definition": definition})
    return out


def _clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _bibtex_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _openalex_url_from_row(row: dict) -> str:
    openalex_id = _clean_text(row.get("openalex_id", ""))
    if openalex_id:
        return openalex_id if openalex_id.startswith("http") else f"https://openalex.org/{openalex_id}"
    all_openalex = _clean_text(row.get("all_openalex_ids", ""))
    if not all_openalex:
        return ""
    first = _clean_text(all_openalex.split(";")[0] if ";" in all_openalex else all_openalex)
    if not first:
        return ""
    return first if first.startswith("http") else f"https://openalex.org/{first}"


def _source_url_from_row(row: dict) -> str:
    doi = _clean_text(row.get("doi", ""))
    if doi:
        return doi if doi.startswith("http") else f"https://doi.org/{doi}"
    return _openalex_url_from_row(row)


def _citation_plaintext(row: dict) -> str:
    first_author = _clean_text(row.get("first_author", "")) or "Unknown author"
    year = _coerce_year(row.get("year"))
    year_text = str(year) if year is not None else "n.d."
    title = _clean_text(row.get("title", "")) or "Untitled"
    venue = _clean_text(row.get("venue", ""))
    source_url = _source_url_from_row(row)
    parts = [f"{first_author}. ({year_text}). {title}."]
    if venue:
        parts.append(venue + ".")
    if source_url:
        parts.append(source_url)
    return " ".join(parts).strip()


def _citation_bibtex(row: dict) -> str:
    paper_id = str(row.get("canonical_paper_id", "") or "paper").replace("-", "")[:12]
    first_author = _clean_text(row.get("first_author", "")) or "Unknown"
    year = _coerce_year(row.get("year"))
    year_text = str(year) if year is not None else "0000"
    title = _bibtex_escape(_clean_text(row.get("title", "")) or "Untitled")
    venue = _bibtex_escape(_clean_text(row.get("venue", "")))
    doi = _clean_text(row.get("doi", ""))
    doi_clean = doi.replace("https://doi.org/", "")
    source_url = _source_url_from_row(row)
    key = f"mskb_{paper_id}_{year_text}"
    lines = [f"@article{{{key},", f"  title = {{{title}}},", f"  author = {{{_bibtex_escape(first_author)}}},"]
    lines.append(f"  year = {{{year_text}}},")
    if venue:
        lines.append(f"  journal = {{{venue}}},")
    if doi_clean:
        lines.append(f"  doi = {{{_bibtex_escape(doi_clean)}}},")
    if source_url:
        lines.append(f"  url = {{{_bibtex_escape(source_url)}}},")
    lines.append("}")
    return "\n".join(lines)


def _difficulty_badge(level: int) -> str:
    labels = {1: "Introductory", 2: "Beginner", 3: "Intermediate", 4: "Advanced", 5: "Specialist"}
    return f"**Difficulty: {labels.get(level, 'Unknown')} ({level}/5)**"


DIFFICULTY_JARGON_HINTS = {
    "cytokine",
    "chemokine",
    "oligodendrocyte",
    "astrocyte",
    "microglia",
    "epigenetic",
    "transcriptome",
    "proteome",
    "gadolinium",
    "magnetization",
    "lesion",
    "pharmacokinetics",
    "immunopathology",
    "neuropathology",
    "biomarker",
    "neurofilament",
    "oligoclonal",
    "encephalomyelitis",
    "remyelination",
    "demyelination",
    "metaanalysis",
}


def _split_sentences(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", text) if _clean_text(chunk)]


def _structured_takeaways_for_display(candidates: list[str], summary: str, abstract: str) -> list[str]:
    cleaned = []
    for value in candidates:
        text = _clean_text(value)
        if not text:
            continue
        text = re.sub(r"^(opportunity|challenge|action|resolution)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
        if text:
            cleaned.append(text)

    seeds = []
    seen = set()
    for text in cleaned + _split_sentences(summary) + _split_sentences(abstract):
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        seeds.append(text.rstrip("."))

    return [f"{seed}." for seed in seeds[:4]]


def _estimate_summary_language_difficulty(summary: str, takeaways: list[str] | None = None) -> int:
    takeaway_text = " ".join(_clean_text(t) for t in (takeaways or []))
    text = f"{_clean_text(summary)} {takeaway_text}".lower()
    words = re.findall(r"[a-z0-9]+", text)
    unique_words = set(words)
    if not words:
        return 3

    score = 1
    if len(words) >= 60:
        score += 1
    if len(words) >= 120:
        score += 1

    jargon_hits = sum(1 for token in DIFFICULTY_JARGON_HINTS if token in unique_words)
    if jargon_hits >= 4:
        score += 1
    if jargon_hits >= 8:
        score += 1

    specialist_markers = [
        "hazard ratio",
        "bayesian",
        "multivariate",
        "randomized",
        "longitudinal",
    ]
    score += sum(1 for marker in specialist_markers if marker in text) // 3

    return min(max(score, 1), 5)


def _extract_jargon_from_row(row: dict) -> list[dict]:
    raw = row.get("jargon", [])
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and _clean_text(item.get("term"))]
    return _parse_jargon_structured(raw)


def _yaml_escape(value: str) -> str:
    """Escape a string for use as a single-line YAML scalar."""
    value = _clean_text(value).replace("\n", " ").strip()
    if not value:
        return '""'
    needs_quote = any(ch in value for ch in ':#&*!|>%@`\'"') or value.startswith("-")
    if needs_quote:
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def _topic_concepts_block(paper_rows: list[dict], limit: int = 14) -> str:
    """Build a "Concepts & skills you'll learn" block for a topic page.

    Aggregates the jargon terms (term + definition) across the papers in a topic's
    reading path, ordered by how often they appear so the most common concepts
    surface first. Returns an empty string if nothing useful can be emitted.
    """
    if not paper_rows:
        return ""
    counts: dict[str, int] = {}
    definitions: dict[str, str] = {}
    order: list[str] = []
    for row in paper_rows:
        for entry in _extract_jargon_from_row(row):
            term = _clean_text(entry.get("term"))
            if not term:
                continue
            key = term.lower()
            if key not in counts:
                counts[key] = 0
                order.append(key)
            counts[key] += 1
            if not definitions.get(key):
                definitions[key] = _clean_text(entry.get("definition"))
    if not counts:
        return ""
    display_terms = {}
    for row in paper_rows:
        for entry in _extract_jargon_from_row(row):
            term = _clean_text(entry.get("term"))
            if term and term.lower() not in display_terms:
                display_terms[term.lower()] = term
    ranked = sorted(order, key=lambda k: (-counts[k], k))[:limit]
    if not ranked:
        return ""
    lines = [
        '<div class="info-panel">',
        "<p>Working through this reading path builds fluency in the core vocabulary and techniques of the topic. "
        "Tap a concept to see its plain-English definition.</p>",
        '<div class="journey-skills">',
        "<strong>Concepts &amp; skills</strong>",
        "<ul>",
    ]
    for key in ranked:
        label = display_terms.get(key, key)
        definition = definitions.get(key, "")
        term_html = html.escape(label)
        if definition:
            lines.append(
                f'<li class="journey-skill--concept"><details>'
                f"<summary>{term_html}</summary>"
                f"<p>{html.escape(definition)}</p>"
                "</details></li>"
            )
        else:
            lines.append(f'<li class="journey-skill--concept">{term_html}</li>')
    lines.append("</ul>")
    lines.append("</div>")
    lines.append("</div>")
    return "\n".join(lines)


def _paper_card(row: dict) -> str:
    lines = []
    title = _clean_text(row.get("title", "Untitled")) or "Untitled"
    source_url = _source_url_from_row(row)
    year = _coerce_year(row.get("year", ""))
    abstract = _clean_text(row.get("abstract", ""))
    summary = _clean_text(row.get("summary", ""))
    summary_source = _clean_text(row.get("summary_source", ""))
    summary_generated_at_utc = _clean_text(row.get("summary_generated_at_utc", ""))
    distill_method = _clean_text(row.get("distill_method", ""))
    summary_certainty_score = max(0.0, min(1.0, _safe_float(row.get("summary_certainty_score", 0.0), 0.0)))
    summary_certainty_label = _clean_text(row.get("summary_certainty_label", ""))
    summary_disclaimer = _clean_text(row.get("summary_disclaimer", ""))
    faithfulness_overlap = _safe_float(row.get("faithfulness_overlap", 0.0), 0.0)
    why = _clean_text(row.get("why_it_matters", ""))
    evidence_type = _clean_text(row.get("evidence_type", "other")).replace("_", " ")
    evidence_strength = _safe_int(row.get("evidence_strength", 2), 2)

    takeaways = _structured_takeaways_for_display(
        _parse_json_list(row.get("key_takeaways", "[]")),
        summary=summary,
        abstract=abstract,
    )
    difficulty = row.get("language_difficulty", None)
    try:
        difficulty_int = int(difficulty) if difficulty is not None and not pd.isna(difficulty) else None
    except (TypeError, ValueError):
        difficulty_int = None
    if difficulty_int is None:
        difficulty_int = _estimate_summary_language_difficulty(summary, takeaways)

    lines.append('<article class="paper-card">')
    lines.append(f"<h3>{html.escape(title)}</h3>")
    lines.append('<div class="paper-meta">')
    if year is not None:
        lines.append(f'<span class="kpi-pill">{year}</span>')
    lines.append(f'<span class="kpi-pill">Language level {difficulty_int}/5</span>')
    lines.append(f'<span class="kpi-pill">Evidence {html.escape(evidence_type)} ({evidence_strength}/5)</span>')
    lines.append(
        f'<span class="kpi-pill">Summary certainty {html.escape(summary_certainty_label or "unknown")} ({int(round(summary_certainty_score*100))}%)</span>'
    )
    lines.append("</div>")

    if abstract:
        lines.append("<h4>Abstract</h4>")
        lines.append(f"<p>{html.escape(abstract)}</p>")

    if summary:
        lines.append("<h4>Plain-English Summary</h4>")
        lines.append(f'<p class="paper-summary">{html.escape(summary)}</p>')
    # Provenance debug (summary basis / method / overlap) is intentionally
    # omitted from the rendered pages — it was leaking pipeline internals into
    # the learner-facing site. Provenance is still available in the CSVs.
    del summary_source, summary_generated_at_utc, distill_method, faithfulness_overlap

    if takeaways:
        lines.append("<h4>Key Takeaways</h4>")
        lines.append("<ul>")
        for t in takeaways:
            lines.append(f"<li>{html.escape(t)}</li>")
        lines.append("</ul>")

    jargon = row.get("jargon", "[]")
    if isinstance(jargon, str):
        try:
            jargon = json.loads(jargon)
        except (json.JSONDecodeError, TypeError):
            jargon = []
    if jargon:
        lines.append("<h4>Technical Terms</h4>")
        lines.append("<ul>")
        for j in jargon:
            if isinstance(j, dict):
                term = html.escape(_clean_text(j.get("term", "")))
                definition = html.escape(_clean_text(j.get("definition", "")))
                if term and definition:
                    lines.append(f"<li><strong>{term}</strong>: {definition}</li>")
        lines.append("</ul>")

    if source_url:
        lines.append(
            f'<p><strong><a href="{html.escape(source_url)}" target="_blank" rel="noopener">Open source paper</a></strong></p>'
        )

    lines.append(f"<p><strong>Bibliography (plain text):</strong> {html.escape(_citation_plaintext(row))}</p>")
    bibtex_value = html.escape(_citation_bibtex(row))
    lines.append("<details>")
    lines.append("<summary><strong>View BibTeX</strong></summary>")
    lines.append(f'<pre><code class="language-bibtex">{bibtex_value}</code></pre>')
    lines.append("</details>")
    if summary_disclaimer:
        lines.append(f"<p><em>{html.escape(summary_disclaimer)}</em></p>")

    lines.append("</article>")
    lines.append("")
    return "\n".join(lines)


def _build_explorer_assets(
    root: Path,
    cfg: dict,
    assets_root: Path,
    paper_summaries: pd.DataFrame,
    paper_topics: pd.DataFrame,
    topic_clusters: pd.DataFrame,
) -> None:
    graph_dir = root / cfg["output_dir"] / "graph"
    scored_path = graph_dir / "scored_papers.csv"
    edges_path = graph_dir / "corpus_citation_edges.csv"
    if not scored_path.exists() or not edges_path.exists():
        return

    scored_cols = {
        "canonical_paper_id",
        "title",
        "year",
        "doi",
        "openalex_id",
        "all_openalex_ids",
        "venue",
        "first_author",
        "merged_cited_by_count",
        "paper_importance_score",
        "age_normalized_importance_score",
        "rank_age_normalized_importance",
        "citations_per_year_raw",
        "paper_age_years",
        "pagerank",
        "kcore",
        "in_degree",
        "out_degree",
        "dominant_category",
        "evidence_type",
        "evidence_strength",
        "tier",
        "abstract",
    }
    scored = pd.read_csv(scored_path, usecols=lambda c: c in scored_cols)
    scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
    scored["paper_importance_score"] = pd.to_numeric(scored["paper_importance_score"], errors="coerce").fillna(0.0)
    if "age_normalized_importance_score" in scored.columns:
        scored["age_normalized_importance_score"] = pd.to_numeric(
            scored["age_normalized_importance_score"], errors="coerce"
        ).fillna(0.0)
    else:
        scored["age_normalized_importance_score"] = 0.0
    if "rank_age_normalized_importance" in scored.columns:
        scored["rank_age_normalized_importance"] = pd.to_numeric(
            scored["rank_age_normalized_importance"], errors="coerce"
        ).fillna(0.0)
    else:
        scored["rank_age_normalized_importance"] = 0.0
    if "citations_per_year_raw" in scored.columns:
        scored["citations_per_year_raw"] = pd.to_numeric(scored["citations_per_year_raw"], errors="coerce").fillna(0.0)
    else:
        scored["citations_per_year_raw"] = 0.0
    if "paper_age_years" in scored.columns:
        scored["paper_age_years"] = pd.to_numeric(scored["paper_age_years"], errors="coerce").fillna(0.0)
    else:
        scored["paper_age_years"] = 0.0
    scored["pagerank"] = pd.to_numeric(scored["pagerank"], errors="coerce").fillna(0.0)
    scored["kcore"] = pd.to_numeric(scored["kcore"], errors="coerce").fillna(0)
    scored["in_degree"] = pd.to_numeric(scored["in_degree"], errors="coerce").fillna(0)
    scored["out_degree"] = pd.to_numeric(scored["out_degree"], errors="coerce").fillna(0)

    candidates = scored.copy()

    candidates["has_abstract"] = ~(
        candidates["abstract"].isna()
        | candidates["abstract"].astype(str).str.strip().str.lower().isin(["", "nan"])
    )
    # Explorer payload can be full corpus (configurable via structural thresholds/start_nodes).
    with_abstract = candidates[candidates["has_abstract"]].copy()
    explorer_cfg = (cfg.get("site", {}) or {}).get("explorer", {}) or {}
    start_metric = _clean_text(explorer_cfg.get("start_metric", "pagerank")).lower()
    if start_metric not in {"pagerank", "kcore", "in_degree", "paper_importance_score"}:
        start_metric = "pagerank"
    min_in_degree = max(0, _safe_int(explorer_cfg.get("min_in_degree", 1), 1))
    min_out_degree = max(0, _safe_int(explorer_cfg.get("min_out_degree", 1), 1))
    min_kcore = max(0, _safe_int(explorer_cfg.get("min_kcore", 1), 1))

    start_nodes = _safe_int(explorer_cfg.get("start_nodes", 0), 0)
    start_nodes = max(0, start_nodes)

    # Apply structural relevance thresholds before top-N truncation.
    candidates = with_abstract[
        (with_abstract["in_degree"] >= min_in_degree)
        & (with_abstract["out_degree"] >= min_out_degree)
        & (with_abstract["kcore"] >= min_kcore)
    ].copy()
    if candidates.empty:
        print(
            f"Explorer prefilter empty with min_in_degree={min_in_degree}, min_out_degree={min_out_degree}, min_kcore={min_kcore}; "
            "falling back to abstract-only pool."
        )
        candidates = with_abstract.copy()

    candidates = candidates.sort_values(start_metric, ascending=False)
    if start_nodes > 0:
        candidates = candidates.head(start_nodes)

    for metric in ["pagerank", "kcore", "in_degree"]:
        values = pd.to_numeric(candidates[metric], errors="coerce").fillna(0.0)
        candidates[f"rank_{metric}"] = values.rank(method="average", pct=True).fillna(0.0)
    candidates["core_score"] = (
        0.5 * candidates["rank_pagerank"]
        + 0.3 * candidates["rank_kcore"]
        + 0.2 * candidates["rank_in_degree"]
    )
    selected_ids = set(candidates["canonical_paper_id"])
    if not selected_ids:
        return

    topic_id_by_paper = {}
    if not paper_topics.empty:
        temp = paper_topics[["canonical_paper_id", "topic_id"]].copy()
        temp["canonical_paper_id"] = temp["canonical_paper_id"].astype(str)
        topic_id_by_paper = dict(zip(temp["canonical_paper_id"], temp["topic_id"]))

    topic_label_by_id = {}
    if not topic_clusters.empty:
        topic_label_by_id = dict(zip(topic_clusters["topic_id"], topic_clusters["auto_label"]))

    summaries = {}
    if not paper_summaries.empty:
        temp = paper_summaries.copy()
        temp["canonical_paper_id"] = temp["canonical_paper_id"].astype(str)
        summaries = {row["canonical_paper_id"]: row.to_dict() for _, row in temp.iterrows()}

    nodes = []
    details_rows = []
    for _, row in candidates.iterrows():
        pid = str(row["canonical_paper_id"])
        summary_row = summaries.get(pid, {})
        title = _clean_text(row.get("title", ""))
        abstract = _clean_text(row.get("abstract", ""))
        doi = _clean_text(row.get("doi", ""))
        source_url = _source_url_from_row(row.to_dict())
        topic_id = topic_id_by_paper.get(pid)
        topic_label = topic_label_by_id.get(topic_id, "")
        summary = _clean_text(summary_row.get("summary", ""))
        summary_source = _clean_text(summary_row.get("summary_source", ""))
        why = _clean_text(summary_row.get("why_it_matters", ""))
        summary_generated_at_utc = _clean_text(summary_row.get("summary_generated_at_utc", ""))
        distill_method = _clean_text(summary_row.get("distill_method", ""))
        summary_certainty_score = _safe_float(summary_row.get("summary_certainty_score", 0.0), 0.0)
        summary_certainty_label = _clean_text(summary_row.get("summary_certainty_label", ""))
        summary_disclaimer = _clean_text(summary_row.get("summary_disclaimer", ""))
        faithfulness_overlap = _safe_float(summary_row.get("faithfulness_overlap", 0.0), 0.0)
        key_takeaways = _structured_takeaways_for_display(
            _parse_json_list(summary_row.get("key_takeaways", [])),
            summary=summary,
            abstract=abstract,
        )
        difficulty = summary_row.get("language_difficulty")
        try:
            difficulty = int(difficulty) if difficulty is not None and not pd.isna(difficulty) else None
        except (TypeError, ValueError):
            difficulty = None
        year = _coerce_year(row.get("year"))

        difficulty_level = (
            difficulty
            if difficulty is not None
            else _estimate_summary_language_difficulty(summary, key_takeaways)
        )

        nodes.append(
            {
                "id": pid,
                "title": title or "Untitled",
                "year": year,
                "doi": doi,
                "source_url": source_url,
                "topic_id": None if topic_id is None or pd.isna(topic_id) else int(topic_id),
                "topic_label": topic_label,
                "first_author": _clean_text(row.get("first_author", "")),
                "venue": _clean_text(row.get("venue", "")),
                "importance": _round_float(row.get("paper_importance_score", 0.0), 6),
                "age_normalized_importance": _round_float(row.get("age_normalized_importance_score", 0.0), 6),
                "rank_age_normalized_importance": _round_float(row.get("rank_age_normalized_importance", 0.0), 6),
                "citations_per_year": _round_float(row.get("citations_per_year_raw", 0.0), 6),
                "paper_age_years": _round_float(row.get("paper_age_years", 0.0), 4),
                "citation_count": int(pd.to_numeric(row.get("merged_cited_by_count", 0), errors="coerce") or 0),
                "pagerank": _round_float(row.get("pagerank", 0.0), 9),
                "kcore": int(pd.to_numeric(row.get("kcore", 0), errors="coerce") or 0),
                "in_degree": int(pd.to_numeric(row.get("in_degree", 0), errors="coerce") or 0),
                "out_degree": int(pd.to_numeric(row.get("out_degree", 0), errors="coerce") or 0),
                "rank_pagerank": _round_float(row.get("rank_pagerank", 0.0), 6),
                "rank_kcore": _round_float(row.get("rank_kcore", 0.0), 6),
                "rank_in_degree": _round_float(row.get("rank_in_degree", 0.0), 6),
                "core_score": _round_float(row.get("core_score", 0.0), 6),
                "difficulty": int(max(1, min(5, int(difficulty_level)))),
                "has_abstract": bool(_clean_text(abstract)),
                "tier": str(row.get("tier", "") or ""),
                "evidence_type": _clean_text(row.get("evidence_type", "")) or "other",
                "evidence_strength": int(pd.to_numeric(row.get("evidence_strength", 2), errors="coerce") or 2),
            }
        )
        # Per-level (basic/advanced) variants. Fall back to the default
        # summary/why/takeaways if a level-specific variant is missing so the
        # frontend always has something to render.
        summary_basic = _clean_text(summary_row.get("summary_basic", "")) or summary
        summary_advanced = _clean_text(summary_row.get("summary_advanced", "")) or summary
        why_basic = _clean_text(summary_row.get("why_it_matters_basic", "")) or why
        why_advanced = _clean_text(summary_row.get("why_it_matters_advanced", "")) or why
        takeaways_basic = _structured_takeaways_for_display(
            _parse_json_list(summary_row.get("key_takeaways_basic", [])),
            summary=summary_basic,
            abstract=abstract,
        ) if _parse_json_list(summary_row.get("key_takeaways_basic", [])) else key_takeaways
        takeaways_advanced = _structured_takeaways_for_display(
            _parse_json_list(summary_row.get("key_takeaways_advanced", [])),
            summary=summary_advanced,
            abstract=abstract,
        ) if _parse_json_list(summary_row.get("key_takeaways_advanced", [])) else key_takeaways

        details_rows.append(
            {
                "id": pid,
                "abstract": abstract,
                "summary": summary,
                "summary_source": summary_source,
                "key_takeaways": key_takeaways,
                "why_it_matters": why,
                "jargon": _parse_jargon_structured(summary_row.get("jargon", [])),
                "summary_basic": summary_basic,
                "summary_advanced": summary_advanced,
                "why_it_matters_basic": why_basic,
                "why_it_matters_advanced": why_advanced,
                "key_takeaways_basic": takeaways_basic,
                "key_takeaways_advanced": takeaways_advanced,
                "summary_generated_at_utc": summary_generated_at_utc,
                "distill_method": distill_method,
                "summary_certainty_score": _round_float(summary_certainty_score, 4),
                "summary_certainty_label": summary_certainty_label,
                "summary_disclaimer": summary_disclaimer,
                "faithfulness_overlap": _round_float(faithfulness_overlap, 4),
                "source_text_hash": _clean_text(summary_row.get("source_text_hash", "")),
                "source_text_chars": _safe_int(summary_row.get("source_text_chars", 0), 0),
            }
        )

    edges_df = pd.read_csv(edges_path, usecols=["source_paper_id", "target_paper_id"])
    edges_df["source_paper_id"] = edges_df["source_paper_id"].astype(str)
    edges_df["target_paper_id"] = edges_df["target_paper_id"].astype(str)
    edges_df = edges_df[
        edges_df["source_paper_id"].isin(selected_ids) & edges_df["target_paper_id"].isin(selected_ids)
    ]

    seen = set()
    edges = []
    for _, row in edges_df.iterrows():
        source = row["source_paper_id"]
        target = row["target_paper_id"]
        if source == target:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": source, "target": target, "type": "CITES"})

    assets_dir = assets_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    generated_at_utc = datetime.now(timezone.utc).isoformat()

    node_fields = [
        "id",
        "title",
        "year",
        "doi",
        "source_url",
        "topic_id",
        "topic_label",
        "first_author",
        "venue",
        "importance",
        "age_normalized_importance",
        "rank_age_normalized_importance",
        "citations_per_year",
        "paper_age_years",
        "citation_count",
        "pagerank",
        "kcore",
        "in_degree",
        "out_degree",
        "rank_pagerank",
        "rank_kcore",
        "rank_in_degree",
        "core_score",
        "difficulty",
        "has_abstract",
        "tier",
        "evidence_type",
        "evidence_strength",
    ]
    id_to_index = {str(n["id"]): idx for idx, n in enumerate(nodes)}
    compact_nodes = [[n.get(field) for field in node_fields] for n in nodes]
    compact_edges = []
    for edge in edges:
        s_idx = id_to_index.get(str(edge.get("source", "")))
        t_idx = id_to_index.get(str(edge.get("target", "")))
        if s_idx is None or t_idx is None or s_idx == t_idx:
            continue
        compact_edges.append([int(s_idx), int(t_idx)])

    payload = {
        "version": 2,
        "generated_at_utc": generated_at_utc,
        "node_fields": node_fields,
        "nodes": compact_nodes,
        "edges_are_indexed": True,
        "edges": compact_edges,
    }
    (assets_dir / "explorer_graph.json").write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )

    details_fields = [
        "id",
        "abstract",
        "summary",
        "summary_source",
        "key_takeaways",
        "why_it_matters",
        "jargon",
        "summary_basic",
        "summary_advanced",
        "why_it_matters_basic",
        "why_it_matters_advanced",
        "key_takeaways_basic",
        "key_takeaways_advanced",
        "summary_generated_at_utc",
        "distill_method",
        "summary_certainty_score",
        "summary_certainty_label",
        "summary_disclaimer",
        "faithfulness_overlap",
        "source_text_hash",
        "source_text_chars",
    ]
    compact_details_rows = [[d.get(field) for field in details_fields] for d in details_rows]
    details_payload = {
        "version": 2,
        "generated_at_utc": generated_at_utc,
        "fields": details_fields,
        "rows": compact_details_rows,
    }
    (assets_dir / "explorer_details.json").write_text(
        json.dumps(details_payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    explorer_cfg = (cfg.get("site", {}) or {}).get("explorer", {}) or {}
    lite_start_nodes = max(0, _safe_int(explorer_cfg.get("lite_start_nodes", 1500), 1500))
    mobile_start_nodes = max(0, _safe_int(explorer_cfg.get("mobile_start_nodes", 1500), 1500))
    lite_payload = payload
    lite_details_payload = details_payload
    if lite_start_nodes > 0 and len(nodes) > lite_start_nodes:
        lite_nodes = sorted(
            nodes,
            key=lambda n: (float(n.get("core_score", 0.0)), float(n.get("importance", 0.0))),
            reverse=True,
        )[:lite_start_nodes]
        lite_ids = {str(n.get("id", "")) for n in lite_nodes}
        lite_id_to_index = {str(n["id"]): idx for idx, n in enumerate(lite_nodes)}
        lite_compact_nodes = [[n.get(field) for field in node_fields] for n in lite_nodes]
        lite_edges = []
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source not in lite_ids or target not in lite_ids or source == target:
                continue
            lite_edges.append([lite_id_to_index[source], lite_id_to_index[target]])
        lite_details_rows = [
            [d.get(field) for field in details_fields]
            for d in details_rows
            if str(d.get("id", "")) in lite_ids
        ]
        lite_payload = {
            "version": 2,
            "generated_at_utc": generated_at_utc,
            "node_fields": node_fields,
            "nodes": lite_compact_nodes,
            "edges_are_indexed": True,
            "edges": lite_edges,
        }
        lite_details_payload = {
            "version": 2,
            "generated_at_utc": generated_at_utc,
            "fields": details_fields,
            "rows": lite_details_rows,
        }
    (assets_dir / "explorer_graph_lite.json").write_text(
        json.dumps(lite_payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    (assets_dir / "explorer_details_lite.json").write_text(
        json.dumps(lite_details_payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )

    mobile_payload = payload
    mobile_details_payload = details_payload
    if mobile_start_nodes > 0 and len(nodes) > mobile_start_nodes:
        mobile_nodes = sorted(
            nodes,
            key=lambda n: (float(n.get("core_score", 0.0)), float(n.get("importance", 0.0))),
            reverse=True,
        )[:mobile_start_nodes]
        mobile_ids = {str(n.get("id", "")) for n in mobile_nodes}
        mobile_id_to_index = {str(n["id"]): idx for idx, n in enumerate(mobile_nodes)}
        mobile_compact_nodes = [[n.get(field) for field in node_fields] for n in mobile_nodes]
        mobile_edges = []
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source not in mobile_ids or target not in mobile_ids or source == target:
                continue
            mobile_edges.append([mobile_id_to_index[source], mobile_id_to_index[target]])
        mobile_details_rows = [
            [d.get(field) for field in details_fields]
            for d in details_rows
            if str(d.get("id", "")) in mobile_ids
        ]
        mobile_payload = {
            "version": 2,
            "generated_at_utc": generated_at_utc,
            "node_fields": node_fields,
            "nodes": mobile_compact_nodes,
            "edges_are_indexed": True,
            "edges": mobile_edges,
        }
        mobile_details_payload = {
            "version": 2,
            "generated_at_utc": generated_at_utc,
            "fields": details_fields,
            "rows": mobile_details_rows,
        }
    (assets_dir / "explorer_graph_mobile.json").write_text(
        json.dumps(mobile_payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    (assets_dir / "explorer_details_mobile.json").write_text(
        json.dumps(mobile_details_payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    missing_source_links = sum(1 for node in nodes if not _clean_text(node.get("source_url", "")))
    print(
        f"Explorer nodes: {len(nodes)} (lite payload: {len(lite_payload['nodes'])}, mobile payload: {len(mobile_payload['nodes'])}), "
        f"missing source links: {missing_source_links}"
    )


def generate(config_path: str) -> None:
    root = Path(config_path).resolve().parent
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    topics_dir = root / cfg["output_dir"] / "topics"
    distilled_dir = root / cfg["output_dir"] / "distilled"
    graph_dir = root / cfg["output_dir"] / "graph"
    # Starlight content root (Astro). The pipeline writes directly into the
    # content collection so no second migration step is needed.
    site_docs = root / "site" / "src" / "content" / "docs"
    # Explorer JSON payloads are shipped from the Astro public/ directory.
    public_dir = root / "site" / "public"

    topics_out = site_docs / "topics"
    topics_out.mkdir(parents=True, exist_ok=True)
    for existing in topics_out.glob("*.md"):
        existing.unlink(missing_ok=True)

    topic_clusters = pd.DataFrame()
    paper_topics = pd.DataFrame()
    paper_summaries = pd.DataFrame()
    topic_overviews = pd.DataFrame()
    reading_paths = pd.DataFrame()
    scored_meta = pd.DataFrame()

    if (topics_dir / "topic_clusters.csv").exists():
        topic_clusters = pd.read_csv(topics_dir / "topic_clusters.csv")
    if (topics_dir / "paper_topics.csv").exists():
        paper_topics = pd.read_csv(topics_dir / "paper_topics.csv")
    if (distilled_dir / "paper_summaries.csv").exists():
        paper_summaries = pd.read_csv(distilled_dir / "paper_summaries.csv")
    if (distilled_dir / "topic_overviews.csv").exists():
        topic_overviews = pd.read_csv(distilled_dir / "topic_overviews.csv")
    if (distilled_dir / "reading_paths.csv").exists():
        reading_paths = pd.read_csv(distilled_dir / "reading_paths.csv")
    if (graph_dir / "scored_papers.csv").exists():
        scored_meta = pd.read_csv(
            graph_dir / "scored_papers.csv",
            usecols=lambda c: c in {
                "canonical_paper_id",
                "title",
                "year",
                "doi",
                "openalex_id",
                "all_openalex_ids",
                "abstract",
                "venue",
                "first_author",
            },
        )

    if topic_clusters.empty:
        print("No topic clusters found. Run the pipeline first.")
        return

    # Build summaries lookup
    summaries_map = {}
    metadata_map = {}
    if not scored_meta.empty:
        scored_meta["canonical_paper_id"] = scored_meta["canonical_paper_id"].astype(str)
        for _, row in scored_meta.iterrows():
            metadata_map[row["canonical_paper_id"]] = row.to_dict()
    if not paper_summaries.empty:
        paper_summaries["canonical_paper_id"] = paper_summaries["canonical_paper_id"].astype(str)
        for _, row in paper_summaries.iterrows():
            merged = metadata_map.get(row["canonical_paper_id"], {}).copy()
            merged.update(row.to_dict())
            summaries_map[row["canonical_paper_id"]] = merged

    # Build overview lookup
    overview_map = {}
    if not topic_overviews.empty:
        for _, row in topic_overviews.iterrows():
            overview_map[row["topic_id"]] = row.to_dict()

    # Categories aligned with ACTRIMS / CMSC / MSJ conference structure
    category_labels = {
        "pathogenesis_and_immunology": "Pathogenesis & Immunology",
        "imaging_and_biomarkers": "Imaging & Biomarkers",
        "clinical_trials_and_therapeutics": "Clinical Trials & Therapeutics",
        "clinical_care_and_management": "Clinical Care & Management",
        "epidemiology_and_population_health": "Epidemiology & Population Health",
    }
    category_descriptions = {
        "pathogenesis_and_immunology": "Mechanisms of demyelination, immune activation, and the cells and cytokines driving MS.",
        "imaging_and_biomarkers": "MRI, optical coherence tomography, and fluid biomarkers that track lesion burden and disease activity.",
        "clinical_trials_and_therapeutics": "Disease-modifying therapies, trial design, and emerging treatment targets.",
        "clinical_care_and_management": "Symptom management, rehabilitation, and the day-to-day care of people with MS.",
        "epidemiology_and_population_health": "Incidence, prevalence, environmental and genetic risk factors, and population-level outcomes.",
    }
    category_order = [
        "pathogenesis_and_immunology",
        "imaging_and_biomarkers",
        "clinical_trials_and_therapeutics",
        "clinical_care_and_management",
        "epidemiology_and_population_health",
    ]

    category_groups = {}
    for _, cluster in topic_clusters.iterrows():
        cat = cluster.get("dominant_category", "pathogenesis_and_immunology")
        category_groups.setdefault(cat, []).append(cluster)

    # Generate topics index — lead with the topic labels so readers can zoom in quickly.
    index_lines = [
        "---",
        "title: Citation topics",
        "description: " + _yaml_escape(
            "Research themes derived from the citation graph — each theme is a curated reading path with plain-English paper summaries."
        ),
        "sidebar:",
        "  label: All topics",
        "  order: 0",
        "---",
        "",
    ]
    index_lines.append('<div class="topic-landing-hero">')
    index_lines.append('<h2>Pick a topic, then zoom in.</h2>')
    index_lines.append(
        "<p>Each card below is a citation-derived research theme with a curated reading path, "
        "plain-English paper summaries, and the concepts you'll pick up along the way.</p>"
    )
    index_lines.append('<div class="topic-jump">')
    for cat in category_order:
        if not category_groups.get(cat):
            continue
        label = category_labels.get(cat, cat)
        anchor = _slug(label)
        index_lines.append(f'<a href="#{anchor}">{html.escape(label)}</a>')
    index_lines.append("</div>")
    index_lines.append("</div>")

    for cat in category_order:
        clusters = category_groups.get(cat, [])
        if not clusters:
            continue
        label = category_labels.get(cat, cat)
        description = category_descriptions.get(cat, "")
        anchor = _slug(label)
        index_lines.append(f'\n<div class="topic-category" id="{anchor}">')
        index_lines.append(f"\n## {label}\n")
        if description:
            index_lines.append(f"<p>{html.escape(description)}</p>")
        index_lines.append("</div>")
        index_lines.append('<div class="topic-grid">')
        for cluster in clusters:
            if isinstance(cluster, pd.Series):
                cluster = cluster.to_dict()
            tid = cluster["topic_id"]
            topic_label = cluster["auto_label"]
            n = cluster["n_papers"]
            diff = cluster.get("difficulty", 3)
            slug = _topic_slug(topic_label, tid)
            index_lines.append(
                f'<a class="topic-card" href="{slug}/">'
                f"<strong>{html.escape(topic_label)}</strong>"
                f"<span>{_safe_int(n)} papers</span>"
                f"<span>Difficulty {_safe_int(diff, 3)}/5</span>"
                "</a>"
            )
        index_lines.append("</div>")

    (topics_out / "index.md").write_text("\n".join(index_lines), encoding="utf-8")

    # Generate individual topic pages
    for _, cluster in topic_clusters.iterrows():
        tid = cluster["topic_id"]
        label = cluster["auto_label"]
        slug = _topic_slug(label, tid)
        diff = cluster.get("difficulty", 3)
        n = cluster["n_papers"]
        cat = cluster.get("dominant_category", "")

        cat_display = str(cat).replace("_", " ").title()
        description = (
            f"{cat_display} · {_safe_int(n)} papers · Difficulty {_safe_int(diff, 3)}/5"
        )
        sidebar_label = label.split(" / ")[0][:40]
        lines = [
            "---",
            "title: " + _yaml_escape(label),
            "description: " + _yaml_escape(description),
            "sidebar:",
            f"  label: {_yaml_escape(sidebar_label)}",
            "---",
            "",
        ]

        overview = overview_map.get(tid, {})
        if overview.get("overview"):
            lines.append("## Overview\n")
            lines.append(html.escape(_clean_text(overview["overview"])))
            lines.append("")

        # Reading path — render papers, and aggregate concepts/skills from their jargon.
        topic_paper_data: list[dict] = []
        if not reading_paths.empty:
            topic_reading = reading_paths[reading_paths["topic_id"] == tid].sort_values("position")
            for _, rp in topic_reading.iterrows():
                pid = str(rp["canonical_paper_id"])
                paper_data = metadata_map.get(pid, {}).copy()
                paper_data.update(summaries_map.get(pid, {}))
                if not paper_data:
                    paper_data = {"title": rp.get("title", "Untitled")}
                topic_paper_data.append(paper_data)

        concept_block = _topic_concepts_block(topic_paper_data)
        if concept_block:
            lines.append("## Concepts &amp; Skills You'll Learn\n")
            lines.append(concept_block)
            lines.append("")

        if topic_paper_data:
            lines.append("## Reading Path\n")
            lines.append("Papers ordered by importance and pedagogic progression.\n")
            lines.append('<div class="paper-stream">')
            for paper_data in topic_paper_data:
                lines.append(_paper_card(paper_data))
            lines.append("</div>")

        (topics_out / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")

    _build_explorer_assets(root, cfg, public_dir, paper_summaries, paper_topics, topic_clusters)
    # site/src/content/docs/explorer.mdx is hand-maintained; the vendor JS and
    # explorer.js live in site/public/javascripts/. The pipeline only refreshes
    # the explorer JSON payloads in site/public/assets/.

    # Starlight auto-generates the sidebar from directory contents (configured
    # in astro.config.mjs), so there is no nav file to rewrite.

    print(f"Generated {len(topic_clusters)} topic pages in {topics_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    generate(args.config)
