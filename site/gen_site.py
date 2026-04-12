#!/usr/bin/env python3
"""Generate MkDocs site content from pipeline outputs."""

import argparse
import copy
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

import gen_site_taxonomy as taxonomy

CATEGORY_LABELS = {
    "pathogenesis_and_immunology": "Pathogenesis & Immunology",
    "imaging_and_biomarkers": "Imaging & Biomarkers",
    "clinical_trials_and_therapeutics": "Clinical Trials & Therapeutics",
    "clinical_care_and_management": "Clinical Care & Management",
    "epidemiology_and_population_health": "Epidemiology & Population Health",
}

CATEGORY_DESCRIPTIONS = {
    "pathogenesis_and_immunology": "Mechanisms of demyelination, immune activation, and the cells and cytokines driving MS.",
    "imaging_and_biomarkers": "MRI, optical coherence tomography, and fluid biomarkers that track lesion burden and disease activity.",
    "clinical_trials_and_therapeutics": "Disease-modifying therapies, trial design, and emerging treatment targets.",
    "clinical_care_and_management": "Symptom management, rehabilitation, and the day-to-day care of people with MS.",
    "epidemiology_and_population_health": "Incidence, prevalence, environmental and genetic risk factors, and population-level outcomes.",
}

# Maximum length of a URL slug (characters).
SLUG_MAX_CHARS = 60
# Maximum paper IDs stored per concept node in the explorer JSON.
CONCEPT_PAPER_IDS_LIMIT = 18
# Maximum characters for a sidebar navigation label.
SIDEBAR_LABEL_MAX_CHARS = 40

CLUSTER_LABEL_STOPWORDS = {
    "medicine",
    "biology",
    "internal medicine",
    "disease",
    "multiple sclerosis",
    "ms",
    "research",
    "studies",
    "multiple sclerosis research studies",
    "research studies",
    "general",
    "other",
}


def _slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())[:SLUG_MAX_CHARS]


def _topic_slug(label: str, topic_id: int) -> str:
    base = _slug(label) or "topic"
    return f"{base}-{int(topic_id)}"


def _prettify_topic_label(raw: str, fallback: str = "Research theme") -> str:
    text = _clean_text(raw)
    if not text:
        return fallback
    parts = [part.strip() for part in re.split(r"\s*[\/|]\s*", text) if _clean_text(part)]
    distinctive: list[str] = []
    seen_norm: set[str] = set()
    for part in parts:
        norm = re.sub(r"\s+", " ", part.lower()).strip()
        if norm in CLUSTER_LABEL_STOPWORDS or norm in seen_norm:
            continue
        duplicate = False
        for kept in distinctive:
            kept_norm = kept.lower()
            if kept_norm in norm or norm in kept_norm:
                duplicate = True
                break
        if duplicate:
            continue
        distinctive.append(part)
        seen_norm.add(norm)
    if not distinctive:
        chosen = sorted(parts, key=len, reverse=True)[0] if parts else text
    elif len(distinctive) == 1:
        chosen = distinctive[0]
    else:
        chosen = " · ".join(distinctive[:2])
    return chosen[:1].upper() + chosen[1:]


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

    labels = ["Opportunity", "Challenge", "Action", "Resolution"]
    return [f"{label}: {seed}." for label, seed in zip(labels, seeds[:4])]


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


def _load_concept_papers(
    root: Path,
    concept_index: dict[str, dict],
    valid_paper_ids: set[str],
) -> dict[str, dict]:
    """Load and validate committed concept->paper cache.

    Failure mode is non-fatal by design: on cache mismatches, return an empty
    mapping per concept and let site generation continue.
    """
    cache_path = root / "data" / "concept_papers.json"
    default_payload = {"foundational": [], "advanced": [], "rationales": {}}
    empty = {concept_id: default_payload.copy() for concept_id in concept_index.keys()}

    if not cache_path.exists():
        print(f"[warn] Concept paper cache missing: {cache_path} (falling back to empty links)")
        return empty

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[warn] Invalid concept cache JSON ({exc}); falling back to empty links")
        return empty

    raw_concepts = data.get("concepts")
    if not isinstance(raw_concepts, dict):
        print("[warn] Concept cache missing object field 'concepts'; falling back to empty links")
        return empty

    concept_ids = set(concept_index.keys())
    cache_ids = set(raw_concepts.keys())
    missing = sorted(concept_ids - cache_ids)
    extra = sorted(cache_ids - concept_ids)
    if missing or extra:
        print(
            "[warn] Concept cache concept-set mismatch "
            f"(missing={len(missing)}, extra={len(extra)}); falling back to empty links"
        )
        return empty

    out: dict[str, dict] = {}
    for concept_id in sorted(concept_ids):
        payload = raw_concepts.get(concept_id)
        if not isinstance(payload, dict):
            print(f"[warn] Concept cache payload for {concept_id} is not an object; using empty links")
            out[concept_id] = default_payload.copy()
            continue

        valid = True
        selected: list[str] = []
        cleaned_lists: dict[str, list[str]] = {}
        for group_name in ("foundational", "advanced"):
            values = payload.get(group_name)
            if not isinstance(values, list):
                valid = False
                break
            deduped: list[str] = []
            seen_group: set[str] = set()
            for item in values:
                paper_id = _clean_text(item)
                if not paper_id or paper_id in seen_group:
                    continue
                if paper_id not in valid_paper_ids:
                    valid = False
                    break
                seen_group.add(paper_id)
                deduped.append(paper_id)
            if not valid:
                break
            cleaned_lists[group_name] = deduped
            selected.extend(deduped)

        if not valid:
            print(f"[warn] Concept cache contains unknown/invalid paper ids for {concept_id}; using empty links")
            out[concept_id] = default_payload.copy()
            continue

        if len(set(selected)) != len(selected):
            print(f"[warn] Concept cache has duplicate paper ids across lists for {concept_id}; using empty links")
            out[concept_id] = default_payload.copy()
            continue

        raw_rationales = payload.get("rationales")
        rationales: dict[str, str] = {}
        if isinstance(raw_rationales, dict):
            for pid, rationale in raw_rationales.items():
                pid_clean = _clean_text(pid)
                rationale_clean = _clean_text(rationale)
                if pid_clean in selected and rationale_clean:
                    rationales[pid_clean] = rationale_clean
        for pid in selected:
            if pid not in rationales:
                rationales[pid] = "Selected for concept relevance."

        out[concept_id] = {
            "foundational": cleaned_lists.get("foundational", []),
            "advanced": cleaned_lists.get("advanced", []),
            "rationales": rationales,
        }

    return out


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

    lines.append('<article class="paper-card">')
    lines.append(f"<h3>{html.escape(title)}</h3>")
    lines.append('<div class="paper-meta">')
    if year is not None:
        lines.append(f'<span class="kpi-pill">{year}</span>')
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
    explorer_cfg = (cfg.get("site", {}) or {}).get("explorer", {}) or {}
    source_csv = _clean_text(explorer_cfg.get("source_csv", ""))
    source_candidates: list[Path] = []
    if source_csv:
        source_path = Path(source_csv)
        source_candidates.append(source_path if source_path.is_absolute() else (root / source_path))
    source_candidates.extend(
        [
            graph_dir / "core_corpus_tracked_with_t4.csv",
            graph_dir / "core_corpus_selected.csv",
            graph_dir / "scored_papers.csv",
        ]
    )
    scored_path = next((path for path in source_candidates if path.exists()), None)
    edges_path = graph_dir / "corpus_citation_edges.csv"
    if scored_path is None or not edges_path.exists():
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
    for col, default in (
        ("canonical_paper_id", ""),
        ("title", ""),
        ("year", pd.NA),
        ("doi", ""),
        ("openalex_id", ""),
        ("all_openalex_ids", ""),
        ("venue", ""),
        ("first_author", ""),
        ("merged_cited_by_count", 0),
        ("paper_importance_score", 0.0),
        ("age_normalized_importance_score", 0.0),
        ("rank_age_normalized_importance", 0.0),
        ("citations_per_year_raw", 0.0),
        ("paper_age_years", 0.0),
        ("pagerank", 0.0),
        ("kcore", 0),
        ("in_degree", 0),
        ("out_degree", 0),
        ("evidence_type", "other"),
        ("evidence_strength", 2),
        ("tier", "included"),
        ("abstract", ""),
    ):
        if col not in scored.columns:
            scored[col] = default
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
    require_abstract = str(explorer_cfg.get("require_abstract", "false")).strip().lower() in {"1", "true", "yes", "y", "on"}
    candidate_pool = candidates[candidates["has_abstract"]].copy() if require_abstract else candidates.copy()
    start_metric = _clean_text(explorer_cfg.get("start_metric", "pagerank")).lower()
    if start_metric not in {"pagerank", "kcore", "in_degree", "paper_importance_score"}:
        start_metric = "pagerank"
    min_in_degree = max(0, _safe_int(explorer_cfg.get("min_in_degree", 1), 1))
    min_out_degree = max(0, _safe_int(explorer_cfg.get("min_out_degree", 1), 1))
    min_kcore = max(0, _safe_int(explorer_cfg.get("min_kcore", 1), 1))

    start_nodes = _safe_int(explorer_cfg.get("start_nodes", 0), 0)
    start_nodes = max(0, start_nodes)

    # Apply structural relevance thresholds before top-N truncation.
    candidates = candidate_pool[
        (candidate_pool["in_degree"] >= min_in_degree)
        & (candidate_pool["out_degree"] >= min_out_degree)
        & (candidate_pool["kcore"] >= min_kcore)
    ].copy()
    if candidates.empty:
        print(
            f"Explorer prefilter empty with min_in_degree={min_in_degree}, min_out_degree={min_out_degree}, min_kcore={min_kcore}; "
            f"falling back to {'abstract-filtered' if require_abstract else 'full'} pool."
        )
        candidates = candidate_pool.copy()

    candidates = candidates.sort_values(start_metric, ascending=False)
    if start_nodes > 0:
        candidates = candidates.head(start_nodes)
    print(f"Explorer source CSV: {scored_path}")

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
        # Per-level (kid/basic/advanced) variants. Fall back to the default
        # summary/why/takeaways if a level-specific variant is missing so the
        # frontend always has something to render.
        summary_kid = _clean_text(summary_row.get("summary_kid", "")) or summary
        summary_basic = _clean_text(summary_row.get("summary_basic", "")) or summary
        summary_advanced = _clean_text(summary_row.get("summary_advanced", "")) or summary
        why_kid = _clean_text(summary_row.get("why_it_matters_kid", "")) or why
        why_basic = _clean_text(summary_row.get("why_it_matters_basic", "")) or why
        why_advanced = _clean_text(summary_row.get("why_it_matters_advanced", "")) or why
        takeaways_kid = _structured_takeaways_for_display(
            _parse_json_list(summary_row.get("key_takeaways_kid", [])),
            summary=summary_kid,
            abstract=abstract,
        ) if _parse_json_list(summary_row.get("key_takeaways_kid", [])) else key_takeaways
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
                "summary_kid": summary_kid,
                "summary_basic": summary_basic,
                "summary_advanced": summary_advanced,
                "why_it_matters_kid": why_kid,
                "why_it_matters_basic": why_basic,
                "why_it_matters_advanced": why_advanced,
                "key_takeaways_kid": takeaways_kid,
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
        "summary_kid",
        "summary_basic",
        "summary_advanced",
        "why_it_matters_kid",
        "why_it_matters_basic",
        "why_it_matters_advanced",
        "key_takeaways_kid",
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


def _center_layered_coords(
    coords: dict[str, dict[str, float | int]],
    layers: list[list[str]],
    y_gap: float,
) -> dict[str, dict[str, float | int]]:
    if not coords or not layers:
        return coords
    max_len = max((len(layer) for layer in layers), default=1)
    out = copy.deepcopy(coords)
    for layer_idx, layer_nodes in enumerate(layers):
        if not layer_nodes:
            continue
        offset = (max_len - len(layer_nodes)) * y_gap / 2.0
        for node_id in layer_nodes:
            if node_id not in out:
                continue
            out[node_id]["y"] = round(float(out[node_id]["y"]) + offset, 4)
            out[node_id]["layer"] = layer_idx
    return out


def _topic_seed_papers(
    reading_paths: pd.DataFrame,
    paper_topics: pd.DataFrame,
    *,
    max_per_topic: int = 14,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not reading_paths.empty:
        ordered = reading_paths.sort_values(["topic_id", "position"], ascending=[True, True])
        for _, row in ordered.iterrows():
            topic_key = taxonomy.normalize_topic_id(row.get("topic_id"))
            paper_id = _clean_text(row.get("canonical_paper_id"))
            if not topic_key or not paper_id:
                continue
            bucket = out.setdefault(topic_key, [])
            if paper_id not in bucket and len(bucket) < max_per_topic:
                bucket.append(paper_id)
    if not paper_topics.empty:
        for _, row in paper_topics.iterrows():
            topic_key = taxonomy.normalize_topic_id(row.get("topic_id"))
            paper_id = _clean_text(row.get("canonical_paper_id"))
            if not topic_key or not paper_id:
                continue
            bucket = out.setdefault(topic_key, [])
            if paper_id not in bucket and len(bucket) < max_per_topic:
                bucket.append(paper_id)
    return out


def _build_learning_spine(
    *,
    assets_dir: Path,
    concept_index: dict[str, dict],
    pathway_steps: dict[str, list[str]],
    concept_papers: dict[str, dict],
) -> None:
    pathway_order = ["clinical", "mechanistic", "emerging"]
    ordered_pathways = [pid for pid in pathway_order if pid in pathway_steps] + [
        pid for pid in sorted(pathway_steps.keys()) if pid not in pathway_order
    ]
    pathway_nodes = [f"pathway:{pid}" for pid in ordered_pathways]
    category_nodes = [f"category:{cat}" for cat in taxonomy.CATEGORY_ORDER]

    concepts = [
        (concept_id, meta)
        for concept_id, meta in concept_index.items()
        if not concept_id.startswith("__")
    ]
    concepts_sorted = sorted(concepts, key=lambda item: (_clean_text(item[1].get("title")), item[0]))
    concept_nodes = [f"concept:{concept_id}" for concept_id, _meta in concepts_sorted]

    edges: set[tuple[str, str]] = set()
    for pathway_id in ordered_pathways:
        seen_categories: set[str] = set()
        for concept_id in pathway_steps.get(pathway_id, []):
            concept_meta = concept_index.get(concept_id) or {}
            category = taxonomy.canonicalize_category(concept_meta.get("category"), taxonomy.CATEGORY_ORDER[0])
            if category:
                seen_categories.add(category)
        for category in seen_categories:
            edges.add((f"pathway:{pathway_id}", f"category:{category}"))

    for concept_id, concept_meta in concepts:
        category = taxonomy.canonicalize_category(concept_meta.get("category"), taxonomy.CATEGORY_ORDER[0])
        edges.add((f"category:{category}", f"concept:{concept_id}"))

    layers = [pathway_nodes, category_nodes, concept_nodes]
    coords = taxonomy.layout_layered(layers=layers, edges=sorted(edges), sweeps=6, x_gap=380.0, y_gap=86.0)
    coords = _center_layered_coords(coords, layers, y_gap=86.0)

    nodes: list[dict] = []
    for pathway_id in ordered_pathways:
        node_id = f"pathway:{pathway_id}"
        c = coords.get(node_id, {"x": 0.0, "y": 0.0, "layer": 0})
        steps = pathway_steps.get(pathway_id, [])
        label_map = {
            "clinical": "Clinical pathway",
            "mechanistic": "Mechanistic pathway",
            "emerging": "Emerging topics pathway",
        }
        label = label_map.get(pathway_id, pathway_id.replace("_", " ").title())
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "group": "Pathway",
                "summary": f"{len(steps)} concept steps in this pathway.",
                "href": f"/mskb/pathways/{pathway_id}/",
                "paper_ids": [],
                "x": round(float(c.get("x", 0.0)), 4),
                "y": round(float(c.get("y", 0.0)), 4),
                "layer": int(c.get("layer", 0)),
            }
        )

    for category in taxonomy.CATEGORY_ORDER:
        node_id = f"category:{category}"
        c = coords.get(node_id, {"x": 0.0, "y": 0.0, "layer": 1})
        nodes.append(
            {
                "id": node_id,
                "label": CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                "group": "Category",
                "summary": CATEGORY_DESCRIPTIONS.get(category, ""),
                "href": f"/mskb/topics/#{_slug(CATEGORY_LABELS.get(category, category))}",
                "paper_ids": [],
                "x": round(float(c.get("x", 0.0)), 4),
                "y": round(float(c.get("y", 0.0)), 4),
                "layer": int(c.get("layer", 1)),
            }
        )

    for concept_id, concept_meta in concepts_sorted:
        node_id = f"concept:{concept_id}"
        c = coords.get(node_id, {"x": 0.0, "y": 0.0, "layer": 2})
        concept_links = concept_papers.get(concept_id, {})
        paper_ids: list[str] = []
        for group in ("foundational", "advanced"):
            for paper_id in (concept_links.get(group) or []):
                pid = _clean_text(paper_id)
                if pid and pid not in paper_ids:
                    paper_ids.append(pid)
        nodes.append(
            {
                "id": node_id,
                "label": _clean_text(concept_meta.get("title")) or concept_id.replace("_", " ").title(),
                "group": "Concept",
                "summary": _clean_text(concept_meta.get("description")),
                "href": f"/mskb/concepts/{_clean_text(concept_meta.get('path'))}/",
                "paper_ids": paper_ids[:CONCEPT_PAPER_IDS_LIMIT],
                "paper_count": len(paper_ids),
                "x": round(float(c.get("x", 0.0)), 4),
                "y": round(float(c.get("y", 0.0)), 4),
                "layer": int(c.get("layer", 2)),
            }
        )

    edge_rows = [{"source": src, "target": dst} for src, dst in sorted(edges)]
    payload = {
        "version": 1,
        "graph_type": "learning_spine",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "layers": [
            {"id": "pathways", "label": "Pathways", "order": 0},
            {"id": "categories", "label": "Domains", "order": 1},
            {"id": "concepts", "label": "Concepts", "order": 2},
        ],
        "nodes": nodes,
        "edges": edge_rows,
    }
    (assets_dir / "learning_spine_graph.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _build_research_map(
    *,
    assets_dir: Path,
    topic_clusters: pd.DataFrame,
    topic_to_concepts: dict[str, dict[str, int]],
    concept_index: dict[str, dict],
    concept_papers: dict[str, dict],
    topic_slug_by_id: dict[str, str],
    topic_seed_papers: dict[str, list[str]],
) -> None:
    topic_rows = []
    for _, row in topic_clusters.iterrows():
        topic_id = taxonomy.normalize_topic_id(row.get("topic_id"))
        if not topic_id:
            continue
        topic_rows.append(
            {
                "topic_id": topic_id,
                "label_raw": _clean_text(row.get("auto_label")),
                "label_display": _prettify_topic_label(_clean_text(row.get("auto_label"))),
                "n_papers": _safe_int(row.get("n_papers"), 0),
                "category": taxonomy.canonicalize_category(row.get("topic_category"), taxonomy.CATEGORY_ORDER[0]),
            }
        )

    category_topics: dict[str, list[dict]] = defaultdict(list)
    for row in topic_rows:
        category_topics[row["category"]].append(row)

    categories = [cat for cat in taxonomy.CATEGORY_ORDER if category_topics.get(cat)]
    layers_category = [f"category:{cat}" for cat in categories]

    topic_rows_sorted = sorted(
        topic_rows,
        key=lambda row: (
            taxonomy.CATEGORY_ORDER.index(row["category"]) if row["category"] in taxonomy.CATEGORY_ORDER else 999,
            -row["n_papers"],
            row["topic_id"],
        ),
    )
    layers_topic = [f"topic:{row['topic_id']}" for row in topic_rows_sorted]

    concept_ids = sorted(
        {
            concept_id
            for overlap in topic_to_concepts.values()
            for concept_id, count in overlap.items()
            if int(count) > 0 and concept_id in concept_index
        },
        key=lambda concept_id: (_clean_text(concept_index.get(concept_id, {}).get("title")), concept_id),
    )
    layers_concept = [f"concept:{concept_id}" for concept_id in concept_ids]

    edges: set[tuple[str, str]] = set()
    for row in topic_rows_sorted:
        edges.add((f"category:{row['category']}", f"topic:{row['topic_id']}"))
        overlap = topic_to_concepts.get(row["topic_id"], {})
        for concept_id, _count in sorted(overlap.items(), key=lambda item: (-int(item[1]), item[0]))[:10]:
            if concept_id in concept_index:
                edges.add((f"topic:{row['topic_id']}", f"concept:{concept_id}"))

    layers = [layers_category, layers_topic, layers_concept]
    coords = taxonomy.layout_layered(layers=layers, edges=sorted(edges), sweeps=6, x_gap=360.0, y_gap=82.0)
    coords = _center_layered_coords(coords, layers, y_gap=82.0)

    nodes: list[dict] = []
    for category in categories:
        node_id = f"category:{category}"
        c = coords.get(node_id, {"x": 0.0, "y": 0.0, "layer": 0})
        nodes.append(
            {
                "id": node_id,
                "label": CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                "group": "Category",
                "summary": CATEGORY_DESCRIPTIONS.get(category, ""),
                "href": f"/mskb/topics/#{_slug(CATEGORY_LABELS.get(category, category))}",
                "paper_ids": [],
                "x": round(float(c.get("x", 0.0)), 4),
                "y": round(float(c.get("y", 0.0)), 4),
                "layer": int(c.get("layer", 0)),
            }
        )

    for row in topic_rows_sorted:
        topic_id = row["topic_id"]
        node_id = f"topic:{topic_id}"
        c = coords.get(node_id, {"x": 0.0, "y": 0.0, "layer": 1})
        topic_slug = topic_slug_by_id.get(topic_id, "")
        category = row["category"]
        nodes.append(
            {
                "id": node_id,
                "label": row["label_display"],
                "group": CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                "summary": (
                    f"{row['n_papers']} papers · "
                    f"Raw topic: {row['label_raw']}"
                ),
                "href": f"/mskb/topics/{topic_slug}/" if topic_slug else "/mskb/topics/",
                "paper_ids": topic_seed_papers.get(topic_id, []),
                "paper_count": row["n_papers"],
                "x": round(float(c.get("x", 0.0)), 4),
                "y": round(float(c.get("y", 0.0)), 4),
                "layer": int(c.get("layer", 1)),
            }
        )

    for concept_id in concept_ids:
        node_id = f"concept:{concept_id}"
        c = coords.get(node_id, {"x": 0.0, "y": 0.0, "layer": 2})
        concept = concept_index.get(concept_id) or {}
        paper_ids: list[str] = []
        concept_links = concept_papers.get(concept_id, {})
        for group in ("foundational", "advanced"):
            for pid in concept_links.get(group, []) or []:
                paper_id = _clean_text(pid)
                if paper_id and paper_id not in paper_ids:
                    paper_ids.append(paper_id)
        nodes.append(
            {
                "id": node_id,
                "label": _clean_text(concept.get("title")) or concept_id.replace("_", " ").title(),
                "group": "Concept",
                "summary": _clean_text(concept.get("description")),
                "href": f"/mskb/concepts/{_clean_text(concept.get('path'))}/",
                "paper_ids": paper_ids[:CONCEPT_PAPER_IDS_LIMIT],
                "paper_count": len(paper_ids),
                "x": round(float(c.get("x", 0.0)), 4),
                "y": round(float(c.get("y", 0.0)), 4),
                "layer": int(c.get("layer", 2)),
            }
        )

    concept_topics: dict[str, list[str]] = {}
    for topic_id, overlaps in topic_to_concepts.items():
        for concept_id, count in overlaps.items():
            if int(count) <= 0:
                continue
            concept_topics.setdefault(concept_id, [])
            if topic_id not in concept_topics[concept_id]:
                concept_topics[concept_id].append(topic_id)
    for concept_id in list(concept_topics.keys()):
        concept_topics[concept_id] = sorted(concept_topics[concept_id], key=lambda value: int(value) if value.isdigit() else value)

    edge_rows = [{"source": src, "target": dst} for src, dst in sorted(edges)]
    payload = {
        "version": 1,
        "graph_type": "research_map",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "layers": [
            {"id": "categories", "label": "Domains", "order": 0},
            {"id": "topics", "label": "Citation Topics", "order": 1},
            {"id": "concepts", "label": "Supported Concepts", "order": 2},
        ],
        "nodes": nodes,
        "edges": edge_rows,
        "seed_topic_papers": topic_seed_papers,
        "concept_topics": concept_topics,
    }
    (assets_dir / "research_map_graph.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _rewrite_concept_topic_crosslinks(
    *,
    concepts_root: Path,
    concept_index: dict[str, dict],
    concept_to_topics: dict[str, dict[str, int]],
    topic_meta_by_id: dict[str, dict],
) -> None:
    legacy_start_marker = "<!-- mskb:topic-links:start -->"
    legacy_end_marker = "<!-- mskb:topic-links:end -->"
    # Use markdown reference-comment syntax so markers are safe in both .md and .mdx
    start_marker = "[//]: # (mskb:topic-links:start)"
    end_marker = "[//]: # (mskb:topic-links:end)"
    section_re = re.compile(
        rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
        flags=re.DOTALL,
    )
    legacy_section_re = re.compile(
        rf"{re.escape(legacy_start_marker)}.*?{re.escape(legacy_end_marker)}",
        flags=re.DOTALL,
    )

    for concept_id, concept in concept_index.items():
        if concept_id.startswith("__"):
            continue
        source_path = Path(_clean_text(concept.get("source_path")))
        if not source_path.exists():
            continue
        overlaps = concept_to_topics.get(concept_id, {})
        ranked = sorted(overlaps.items(), key=lambda item: (-int(item[1]), item[0]))[:10]

        block_lines = [start_marker, "", "## Citation topics that feed this concept", ""]
        if ranked:
            block_lines.append(
                f'<p><a href="/mskb/topics/?concept={concept_id}"><strong>Open this concept in the research map →</strong></a></p>'
            )
            block_lines.append("<ul>")
            for topic_id, overlap in ranked:
                topic_meta = topic_meta_by_id.get(topic_id) or {}
                topic_label = _clean_text(topic_meta.get("display_label")) or f"Topic {topic_id}"
                topic_slug = _clean_text(topic_meta.get("slug"))
                topic_url = f"/mskb/topics/{topic_slug}/" if topic_slug else "/mskb/topics/"
                block_lines.append(
                    f'<li><a href="{topic_url}">{html.escape(topic_label)}</a> · '
                    f'<a href="/mskb/journey/?seed={topic_id}">Start journey from this topic</a> '
                    f"({int(overlap)} linked paper{'s' if int(overlap) != 1 else ''}).</li>"
                )
            block_lines.append("</ul>")
        else:
            block_lines.append(
                '<p><em>No topic overlap links available yet for this concept. '
                'Regenerate the taxonomy after refreshing concept-paper links.</em></p>'
            )
        block_lines.extend(["", end_marker, ""])
        block = "\n".join(block_lines)

        text = source_path.read_text(encoding="utf-8")
        # Remove any prior managed block (both current and legacy marker styles),
        # then append exactly one canonical managed block.
        stripped = section_re.sub("", text)
        stripped = legacy_section_re.sub("", stripped)
        updated = stripped.rstrip() + "\n\n" + block
        source_path.write_text(updated, encoding="utf-8")


def _legacy_topic_grid_lines(
    *,
    category_order: list[str],
    category_groups: dict[str, list[dict]],
) -> list[str]:
    lines: list[str] = []
    for category in category_order:
        clusters = category_groups.get(category, [])
        if not clusters:
            continue
        label = CATEGORY_LABELS.get(category, category)
        description = CATEGORY_DESCRIPTIONS.get(category, "")
        anchor = _slug(label)
        lines.append(f'<div class="topic-category" id="{anchor}">')
        lines.append("")
        lines.append(f"## {label}")
        lines.append("")
        if description:
            lines.append(f"<p>{html.escape(description)}</p>")
        lines.append("</div>")
        lines.append('<div class="topic-grid">')
        for cluster in clusters:
            topic_label = _clean_text(cluster["display_label"] or cluster["auto_label"])
            n = _safe_int(cluster.get("n_papers"), 0)
            slug = _clean_text(cluster.get("slug"))
            lines.append(
                f'<a class="topic-card" href="{slug}/">'
                f"<strong>{html.escape(topic_label)}</strong>"
                f"<span>{n} papers</span>"
                "</a>"
            )
        lines.append("</div>")
        lines.append("")
    return lines


def _paper_card_kid(row: dict) -> str:
    """Render a kid-friendly paper card using the kid-level summary fields."""
    lines = []
    title = _clean_text(row.get("title", "Untitled")) or "Untitled"
    source_url = _source_url_from_row(row)
    year = _coerce_year(row.get("year", ""))
    abstract = _clean_text(row.get("abstract", ""))

    # Prefer kid-level summary; fall back to basic, then generic summary.
    summary = (
        _clean_text(row.get("summary_kid", ""))
        or _clean_text(row.get("summary_basic", ""))
        or _clean_text(row.get("summary", ""))
    )
    why = (
        _clean_text(row.get("why_it_matters_kid", ""))
        or _clean_text(row.get("why_it_matters_basic", ""))
        or _clean_text(row.get("why_it_matters", ""))
    )
    raw_takeaways = (
        _parse_json_list(row.get("key_takeaways_kid", []))
        or _parse_json_list(row.get("key_takeaways_basic", []))
        or _parse_json_list(row.get("key_takeaways", []))
    )
    takeaways = _structured_takeaways_for_display(raw_takeaways, summary=summary, abstract=abstract)

    # Kid-level jargon glossary uses the kid jargon if available, else standard.
    raw_jargon = row.get("jargon_kid", row.get("jargon", "[]"))
    if isinstance(raw_jargon, str):
        try:
            raw_jargon = json.loads(raw_jargon)
        except (json.JSONDecodeError, TypeError):
            raw_jargon = []
    jargon = [j for j in raw_jargon if isinstance(j, dict)] if raw_jargon else []

    # Plain-language abstract for the paper (original abstract shown under a disclosure).
    lines.append('<article class="paper-card paper-card--kid">')
    lines.append(f"<h3>{html.escape(title)}</h3>")
    lines.append('<div class="paper-meta">')
    if year is not None:
        lines.append(f'<span class="kpi-pill">{year}</span>')
    lines.append("</div>")

    if summary:
        lines.append("<h4>What did scientists find out?</h4>")
        lines.append(f'<p class="paper-summary">{html.escape(summary)}</p>')

    if why:
        lines.append(f'<p class="paper-why"><strong>Why it matters:</strong> {html.escape(why)}</p>')

    if takeaways:
        lines.append("<h4>Key ideas</h4>")
        lines.append("<ul>")
        for t in takeaways:
            lines.append(f"<li>{html.escape(t)}</li>")
        lines.append("</ul>")

    if jargon:
        lines.append("<h4>Words to know</h4>")
        lines.append("<ul>")
        for j in jargon:
            term = html.escape(_clean_text(j.get("term", "")))
            definition = html.escape(_clean_text(j.get("definition", "")))
            if term and definition:
                lines.append(f"<li><strong>{term}</strong>: {definition}</li>")
        lines.append("</ul>")

    if abstract:
        lines.append("<details>")
        lines.append("<summary><strong>Original abstract (for grown-ups)</strong></summary>")
        lines.append(f"<p>{html.escape(abstract)}</p>")
        lines.append("</details>")

    if source_url:
        lines.append(
            f'<p><a href="{html.escape(source_url)}" target="_blank" rel="noopener">Read the full paper</a></p>'
        )

    lines.append("</article>")
    lines.append("")
    return "\n".join(lines)


def _generate_kid_journey_page(
    *,
    site_docs: Path,
    topic_clusters: pd.DataFrame,
    paper_topics: pd.DataFrame,
    topic_overviews: pd.DataFrame,
    reading_paths: pd.DataFrame,
    summaries_map: dict,
    metadata_map: dict,
) -> None:
    """Generate site/src/content/docs/kid-journey.md — the companion learning journey for young readers."""
    out_path = site_docs / "kid-journey.md"

    overview_map: dict[int, dict] = {}
    if not topic_overviews.empty:
        for _, row in topic_overviews.iterrows():
            overview_map[row["topic_id"]] = row.to_dict()

    # Category display order: foundations first, then clinical, then emerging.
    category_friendly: dict[str, str] = {
        "pathogenesis_and_immunology": "How MS works inside the body",
        "imaging_and_biomarkers": "Seeing MS: scans, tests, and measurements",
        "clinical_trials_and_therapeutics": "Treatments and clinical trials",
        "clinical_care_and_management": "Living with MS: care and daily life",
        "epidemiology_and_population_health": "Who gets MS and why",
    }

    lines: list[str] = [
        "---",
        "title: MS Science for Curious Minds",
        'description: "A plain-language learning journey through MS research — written for curious 12-year-olds."',
        "sidebar:",
        "  label: For Curious Minds",
        "  order: 5",
        "---",
        "",
        '<div class="kid-journey-hero">',
        "",
        "## MS Science for Curious Minds",
        "",
        "Multiple sclerosis — or MS — is a condition where the body's own immune system "
        "accidentally attacks the brain and spinal cord.",
        "Thousands of scientists around the world are working every day to understand it, "
        "treat it, and one day cure it.",
        "",
        "This page takes you on a tour of what they've discovered, written in plain language "
        "so anyone can follow along.",
        "Each section covers a different part of the puzzle.",
        "",
        "</div>",
        "",
        "---",
        "",
    ]

    if topic_clusters.empty:
        lines.append(
            "*No topic data available yet. Run the pipeline and re-generate the site to populate this page.*"
        )
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return

    # Group topics by category for a logical narrative flow.
    category_groups: dict[str, list[dict]] = defaultdict(list)
    for _, cluster in topic_clusters.iterrows():
        cat = taxonomy.canonicalize_category(cluster.get("topic_category", ""), taxonomy.CATEGORY_ORDER[0])
        category_groups[cat].append(cluster.to_dict())

    for cat in taxonomy.CATEGORY_ORDER:
        clusters = category_groups.get(cat, [])
        if not clusters:
            continue
        friendly_label = category_friendly.get(cat, cat.replace("_", " ").title())
        lines.append(f"## {html.escape(friendly_label)}")
        lines.append("")

        for cluster in clusters:
            tid = cluster["topic_id"]
            topic_label = _prettify_topic_label(_clean_text(cluster.get("display_label") or cluster.get("auto_label", "")))
            n_papers = _safe_int(cluster.get("n_papers"), 0)
            overview_row = overview_map.get(tid, {})

            # Kid overview preferred; fall back to standard overview.
            kid_overview = (
                _clean_text(overview_row.get("overview_kid", ""))
                or _clean_text(overview_row.get("overview", ""))
            )

            lines.append(f"### {html.escape(topic_label)}")
            lines.append("")
            lines.append(f"*{n_papers} research paper{'s' if n_papers != 1 else ''} in this area.*")
            lines.append("")
            if kid_overview:
                lines.append(kid_overview)
                lines.append("")

            # Include up to 5 papers from the reading path for this topic.
            topic_paper_data: list[dict] = []
            if not reading_paths.empty:
                topic_reading = reading_paths[reading_paths["topic_id"] == tid].sort_values("position")
                for _, rp in topic_reading.head(5).iterrows():
                    paper_id = str(rp["canonical_paper_id"])
                    paper_data = metadata_map.get(paper_id, {}).copy()
                    paper_data.update(summaries_map.get(paper_id, {}))
                    if not paper_data:
                        paper_data = {"title": rp.get("title", "Untitled")}
                    topic_paper_data.append(paper_data)

            if topic_paper_data:
                lines.append('<div class="paper-stream paper-stream--kid">')
                for paper_data in topic_paper_data:
                    lines.append(_paper_card_kid(paper_data))
                lines.append("</div>")
                lines.append("")

    lines.extend([
        "---",
        "",
        "## Want to explore more?",
        "",
        "- [Learning Journey](/mskb/journey/) — build your own reading path through the full research graph.",
        "- [Citation Topics](/mskb/topics/) — browse all research areas by category.",
        "- [Concept Map](/mskb/concepts/) — explore the big ideas behind MS research.",
        "",
        '<p><em>All summaries on this page are generated from peer-reviewed research papers. '
        'They are simplified for younger readers but remain grounded in the evidence. '
        'Always check the original papers before drawing scientific conclusions.</em></p>',
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Kid journey page written to {out_path}")


def _build_viz_assets(*, outputs_dir: Path, assets_dir: Path) -> None:
    """Copy lineage and field-development JSON from pipeline outputs to site assets."""
    web_dir = outputs_dir / "website"
    for name in ("lineage_data.json", "field_development.json", "corpus_stats.json"):
        src = web_dir / name
        if not src.exists():
            print(f"[warn] {name} not found in {web_dir}; run compute_viz_metrics first.")
            continue
        dst = assets_dir / name
        dst.write_bytes(src.read_bytes())
        print(f"Viz asset: {dst}")


def generate(config_path: str) -> None:
    """Generate all MkDocs site content from pipeline outputs under the configured output directory."""
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
    for pattern in ("*.md", "*.mdx"):
        for existing in topics_out.glob(pattern):
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

    # Filter topic_clusters to only those with ≥1 paper from the selected corpus.
    # Leiden clustering runs on the full scored graph and can produce off-topic
    # clusters (e.g. cardiac, glioma, EEG) that contain no MS-relevant selected
    # papers. Only clusters with selected-corpus papers get their own topic page.
    if not topic_clusters.empty and not paper_topics.empty:
        tracked_csv = graph_dir / "core_corpus_tracked_with_t4.csv"
        _ref_csv = graph_dir / "core_corpus_selected.csv" if not tracked_csv.exists() else None
        _corpus_csv = tracked_csv if tracked_csv.exists() else _ref_csv
        if _corpus_csv and _corpus_csv.exists():
            _selected_ids = set(
                pd.read_csv(_corpus_csv, usecols=["canonical_paper_id"], low_memory=False)[
                    "canonical_paper_id"
                ].astype(str)
            )
            _active_cluster_ids = set(
                paper_topics[paper_topics["canonical_paper_id"].isin(_selected_ids)]["topic_id"]
            )
            _before = len(topic_clusters)
            topic_clusters = topic_clusters[topic_clusters["topic_id"].isin(_active_cluster_ids)].copy()
            _dropped = _before - len(topic_clusters)
            if _dropped:
                print(f"Topic filter: dropped {_dropped} off-topic cluster(s) with no selected-corpus papers.")

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

    concepts_root = site_docs / "concepts"
    pathways_root = site_docs / "pathways"
    concept_index_with_routes = taxonomy.load_concept_index(concepts_root)
    route_map = concept_index_with_routes.pop("__route_map__", {})
    concept_index = concept_index_with_routes
    pathway_steps = taxonomy.build_pathway_steps(
        pathways_root,
        {**concept_index, "__route_map__": route_map},
    )
    valid_paper_ids: set[str] = set()
    if not scored_meta.empty and "canonical_paper_id" in scored_meta.columns:
        valid_paper_ids = {
            str(pid).strip()
            for pid in scored_meta["canonical_paper_id"].astype(str).tolist()
            if str(pid).strip()
        }
    concept_papers = _load_concept_papers(
        root=root,
        concept_index=concept_index,
        valid_paper_ids=valid_paper_ids,
    )
    paper_topic_rows = paper_topics.to_dict(orient="records") if not paper_topics.empty else []
    concept_to_topics, topic_to_concepts = taxonomy.build_concept_topic_links(
        concept_papers=concept_papers,
        paper_topics_rows=paper_topic_rows,
    )
    topic_category_map = taxonomy.derive_topic_categories(
        topic_clusters_rows=topic_clusters.to_dict(orient="records"),
        concept_index=concept_index,
        topic_to_concepts=topic_to_concepts,
    )

    topic_categories: list[str] = []
    topic_category_sources: list[str] = []
    topic_category_concepts: list[str] = []
    topic_category_overlaps: list[int] = []
    for _, cluster in topic_clusters.iterrows():
        topic_key = taxonomy.normalize_topic_id(cluster.get("topic_id"))
        fallback = taxonomy.canonicalize_category(
            cluster.get("dominant_category", ""),
            taxonomy.CATEGORY_ORDER[0],
        ) or taxonomy.CATEGORY_ORDER[0]
        info = topic_category_map.get(topic_key) or {
            "topic_category": fallback,
            "category_source": "fallback",
            "top_concept_id": "",
            "overlap_count": 0,
        }
        topic_categories.append(taxonomy.canonicalize_category(info.get("topic_category"), fallback) or fallback)
        topic_category_sources.append(_clean_text(info.get("category_source")) or "fallback")
        topic_category_concepts.append(_clean_text(info.get("top_concept_id")))
        topic_category_overlaps.append(_safe_int(info.get("overlap_count"), 0))
    topic_clusters = topic_clusters.copy()
    topic_clusters["topic_category"] = topic_categories
    topic_clusters["category_source"] = topic_category_sources
    topic_clusters["category_concept_id"] = topic_category_concepts
    topic_clusters["category_overlap_count"] = topic_category_overlaps

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

    topic_seed_papers = _topic_seed_papers(reading_paths, paper_topics)
    topic_clusters = topic_clusters.copy()
    topic_clusters["topic_key"] = topic_clusters["topic_id"].apply(taxonomy.normalize_topic_id)
    topic_clusters["display_label"] = topic_clusters["auto_label"].apply(_prettify_topic_label)
    topic_clusters["slug"] = topic_clusters.apply(
        lambda row: _topic_slug(_clean_text(row.get("display_label")) or _clean_text(row.get("auto_label")), row["topic_id"]),
        axis=1,
    )
    topic_slug_by_id = {
        taxonomy.normalize_topic_id(row["topic_id"]): _clean_text(row["slug"])
        for _, row in topic_clusters.iterrows()
    }
    topic_meta_by_id = {
        taxonomy.normalize_topic_id(row["topic_id"]): {
            "topic_id": taxonomy.normalize_topic_id(row["topic_id"]),
            "raw_label": _clean_text(row.get("auto_label")),
            "display_label": _clean_text(row.get("display_label")),
            "slug": _clean_text(row.get("slug")),
            "category": taxonomy.canonicalize_category(row.get("topic_category"), taxonomy.CATEGORY_ORDER[0]),
            "n_papers": _safe_int(row.get("n_papers"), 0),
            "difficulty": _safe_int(row.get("difficulty"), 3),
        }
        for _, row in topic_clusters.iterrows()
    }

    category_order = list(taxonomy.CATEGORY_ORDER)
    category_groups: dict[str, list[dict]] = defaultdict(list)
    for _, cluster in topic_clusters.iterrows():
        category = taxonomy.canonicalize_category(cluster.get("topic_category"), taxonomy.CATEGORY_ORDER[0])
        category_groups[category].append(cluster.to_dict())

    index_lines = [
        "---",
        "title: Citation topics",
        "description: " + _yaml_escape(
            "Research themes derived from the citation graph with concept links and journey seeding."
        ),
        "template: splash",
        "sidebar:",
        "  label: All topics",
        "  order: 0",
        "---",
        "",
        "import '../../../styles/custom.css';",
        "",
        '<div class="topic-landing-hero">',
        "<h2>Research map by topic, concept, and domain.</h2>",
        "<p>Use the graph to jump between citation topics and the learning concepts they support. "
        "If JavaScript is disabled, expand the fallback list below.</p>",
        '<div class="topic-jump">',
    ]
    for category in category_order:
        if not category_groups.get(category):
            continue
        label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
        index_lines.append(f'<a href="#{_slug(label)}">{html.escape(label)}</a>')
    index_lines.extend(
        [
            "</div>",
            "</div>",
            "",
            '<div id="mskb-graph-research" class="mskb-graph-root"></div>',
            "",
            "<details>",
            "<summary><strong>Fallback topic list (non-JS)</strong></summary>",
        ]
    )
    index_lines.extend(_legacy_topic_grid_lines(category_order=category_order, category_groups=category_groups))
    index_lines.extend(
        [
            "</details>",
            "",
            '<script is:inline src="/mskb/javascripts/mskb_graph_renderer.js"></script>',
            '<script is:inline src="/mskb/javascripts/explorer.js"></script>',
        ]
    )
    (topics_out / "index.mdx").write_text("\n".join(index_lines), encoding="utf-8")

    for _, cluster in topic_clusters.iterrows():
        topic_id = cluster["topic_id"]
        topic_key = taxonomy.normalize_topic_id(topic_id)
        label_raw = _clean_text(cluster.get("auto_label"))
        label_display = _clean_text(cluster.get("display_label")) or label_raw
        slug = _clean_text(cluster.get("slug"))
        paper_count = _safe_int(cluster.get("n_papers"), 0)
        category = taxonomy.canonicalize_category(cluster.get("topic_category"), taxonomy.CATEGORY_ORDER[0])
        category_source = _clean_text(cluster.get("category_source", "fallback"))
        category_concept_id = _clean_text(cluster.get("category_concept_id", ""))

        category_display = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
        page_description = f"{category_display} · {paper_count} papers"
        sidebar_label = label_display[:SIDEBAR_LABEL_MAX_CHARS]
        lines = [
            "---",
            "title: " + _yaml_escape(label_display),
            "description: " + _yaml_escape(page_description),
            "sidebar:",
            f"  label: {_yaml_escape(sidebar_label)}",
            "topic_taxonomy:",
            f"  category: {_yaml_escape(category)}",
            f"  category_source: {_yaml_escape(category_source)}",
            f"  category_concept_id: {_yaml_escape(category_concept_id)}",
            "---",
            "",
        ]

        overview = overview_map.get(topic_id, {})
        if overview.get("overview"):
            lines.append("## Overview")
            lines.append("")
            lines.append(html.escape(_clean_text(overview["overview"])))
            lines.append("")
        if label_display and label_display != label_raw:
            lines.append(f"<p><em>Raw cluster label:</em> {html.escape(label_raw)}</p>")
            lines.append("")

        related_concepts = sorted(
            (topic_to_concepts.get(topic_key) or {}).items(),
            key=lambda item: (-int(item[1]), item[0]),
        )[:10]
        lines.append("## Concepts this topic supports")
        lines.append("")
        if related_concepts:
            lines.append("<ul>")
            for concept_id, overlap in related_concepts:
                concept_meta = concept_index.get(concept_id) or {}
                concept_title = _clean_text(concept_meta.get("title")) or concept_id.replace("_", " ").title()
                concept_href = f"/mskb/concepts/{_clean_text(concept_meta.get('path'))}/"
                lines.append(
                    "<li>"
                    f'<a href="/mskb/journey/?concept={concept_id}">{html.escape(concept_title)}</a> '
                    f"({int(overlap)} linked paper{'s' if int(overlap) != 1 else ''}) · "
                    f'<a href="{concept_href}">open concept page</a>'
                    "</li>"
                )
            lines.append("</ul>")
        else:
            lines.append("<p><em>No linked concepts available yet for this topic.</em></p>")
        lines.append("")

        topic_paper_data: list[dict] = []
        if not reading_paths.empty:
            topic_reading = reading_paths[reading_paths["topic_id"] == topic_id].sort_values("position")
            for _, rp in topic_reading.iterrows():
                paper_id = str(rp["canonical_paper_id"])
                paper_data = metadata_map.get(paper_id, {}).copy()
                paper_data.update(summaries_map.get(paper_id, {}))
                if not paper_data:
                    paper_data = {"title": rp.get("title", "Untitled")}
                topic_paper_data.append(paper_data)

        concept_block = _topic_concepts_block(topic_paper_data)
        if concept_block:
            lines.append("## Concepts &amp; Skills You'll Learn")
            lines.append("")
            lines.append(concept_block)
            lines.append("")

        if topic_paper_data:
            lines.append("## Reading Path")
            lines.append("")
            lines.append("Papers ordered by importance and pedagogic progression.")
            lines.append("")
            lines.append('<div class="paper-stream">')
            for paper_data in topic_paper_data:
                lines.append(_paper_card(paper_data))
            lines.append("</div>")
            lines.append("")

        lines.append("## Turn this topic into a learning journey")
        lines.append("")
        lines.append(
            f'<p><a href="/mskb/journey/?seed={topic_key}"><strong>Turn this topic into a learning journey →</strong></a></p>'
        )
        lines.append("")

        if related_concepts:
            lines.append("## Related concepts")
            lines.append("")
            lines.append("<ul>")
            for concept_id, _overlap in related_concepts[:6]:
                concept_meta = concept_index.get(concept_id) or {}
                concept_title = _clean_text(concept_meta.get("title")) or concept_id.replace("_", " ").title()
                lines.append(f'<li><a href="/mskb/journey/?concept={concept_id}">{html.escape(concept_title)}</a></li>')
            lines.append("</ul>")
            lines.append("")

        (topics_out / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")

    assets_dir = public_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    _build_learning_spine(
        assets_dir=assets_dir,
        concept_index=concept_index,
        pathway_steps=pathway_steps,
        concept_papers=concept_papers,
    )
    _build_research_map(
        assets_dir=assets_dir,
        topic_clusters=topic_clusters,
        topic_to_concepts=topic_to_concepts,
        concept_index=concept_index,
        concept_papers=concept_papers,
        topic_slug_by_id=topic_slug_by_id,
        topic_seed_papers=topic_seed_papers,
    )
    _rewrite_concept_topic_crosslinks(
        concepts_root=concepts_root,
        concept_index=concept_index,
        concept_to_topics=concept_to_topics,
        topic_meta_by_id=topic_meta_by_id,
    )
    _build_explorer_assets(root, cfg, public_dir, paper_summaries, paper_topics, topic_clusters)
    # site/src/content/docs/explorer.mdx is hand-maintained; the vendor JS and
    # explorer.js live in site/public/javascripts/. The pipeline only refreshes
    # the explorer JSON payloads in site/public/assets/.
    _build_viz_assets(outputs_dir=root / cfg["output_dir"], assets_dir=assets_dir)

    # Starlight auto-generates the sidebar from directory contents (configured
    # in astro.config.mjs), so there is no nav file to rewrite.

    _generate_kid_journey_page(
        site_docs=site_docs,
        topic_clusters=topic_clusters,
        paper_topics=paper_topics,
        topic_overviews=topic_overviews,
        reading_paths=reading_paths,
        summaries_map=summaries_map,
        metadata_map=metadata_map,
    )

    pathway_step_count = sum(len(steps) for steps in pathway_steps.values())
    concept_topic_links = sum(len(topics) for topics in concept_to_topics.values())
    print(
        f"Taxonomy derivation: {len(concept_index)} concepts, {pathway_step_count} pathway steps, "
        f"{concept_topic_links} concept-topic links"
    )
    print(f"Generated {len(topic_clusters)} topic pages in {topics_out}")
    print(f"Learning spine asset: {assets_dir / 'learning_spine_graph.json'}")
    print(f"Research map asset: {assets_dir / 'research_map_graph.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    generate(args.config)
