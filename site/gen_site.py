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


TAKEAWAY_LABELS = ["Opportunity", "Challenge", "Action", "Resolution"]


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

    defaults = {
        "Opportunity": "This paper points to a practical opportunity for MS research or care",
        "Challenge": "A key challenge is uncertainty in mechanism, measurement, or generalization",
        "Action": "A practical action is to test or replicate the approach in focused cohorts",
        "Resolution": "The paper offers partial resolution and clarifies what evidence should come next",
    }

    out = []
    for idx, label in enumerate(TAKEAWAY_LABELS):
        text = seeds[idx] if idx < len(seeds) else defaults[label]
        out.append(f"{label}: {text}.")
    return out


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

    lines.append('<article class="paper-card reveal">')
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
    if summary_source:
        lines.append(f"<p><strong>Summary basis:</strong> {html.escape(summary_source)}</p>")
    if summary_generated_at_utc or distill_method:
        lines.append(
            f"<p><strong>Summary provenance:</strong> method={html.escape(distill_method or 'unknown')}; "
            f"generated={html.escape(summary_generated_at_utc or 'unknown')}; overlap={faithfulness_overlap:.2f}</p>"
        )

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
    site_docs: Path,
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
        details_rows.append(
            {
                "id": pid,
                "abstract": abstract,
                "summary": summary,
                "summary_source": summary_source,
                "key_takeaways": key_takeaways,
                "why_it_matters": why,
                "jargon": _parse_json_list(summary_row.get("jargon", [])),
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

    assets_dir = site_docs / "assets"
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
    lite_start_nodes = max(0, _safe_int(explorer_cfg.get("lite_start_nodes", 2500), 2500))
    mobile_start_nodes = max(0, _safe_int(explorer_cfg.get("mobile_start_nodes", 2500), 2500))
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


def _write_explorer_page(site_docs: Path) -> None:
    explorer_md = """# Explorer

Use this graph to inspect papers, follow citation paths, and turn a short research note into parent/child/related paper choices.

<script src="../javascripts/vendor/graphology.umd.min.js"></script>
<script src="../javascripts/vendor/sigma.min.js"></script>

<div class="top-idea reveal">
  <h3>Explore the MS Knowledge Graph</h3>
  <p>Use this view to inspect citation structure, read paper summaries, and plan literature exploration from core papers out to related work.</p>
  <div class="explorer-guide">
    <div class="guide-card"><strong>Undergrad flow:</strong> start with lower language level, then branch through related papers.</div>
    <div class="guide-card"><strong>Grad flow:</strong> raise structural filters (in/out degree and k-core) for denser, high-signal papers.</div>
    <div class="guide-card"><strong>Node semantics:</strong> size is log(citations), color is k-core tier, arrows are citations.</div>
  </div>
</div>

<details id="parameters" class="param-tray reveal" open>
  <summary><strong>Parameters</strong> (expand/collapse)</summary>
  <div class="explorer-presets">
    <span class="preset-label">Preset views</span>
    <button id="preset-undergrad" type="button">Undergrad Starter</button>
    <button id="preset-balanced" type="button">Balanced Survey</button>
    <button id="preset-grad" type="button">Grad Deep Dive</button>
  </div>
  <div class="explorer-toolbar">
    <label for="core-metric">Core metric</label>
    <select id="core-metric">
      <option value="composite" selected>Composite (recommended)</option>
      <option value="pagerank">PageRank</option>
      <option value="kcore">k-core</option>
      <option value="in_degree">In-degree</option>
      <option value="age_normalized">Age-normalized centrality</option>
    </select>
    <label for="difficulty-max">Max language level</label>
    <select id="difficulty-max">
      <option value="5" selected>All (1-5)</option>
      <option value="2">1-2 Plain language</option>
      <option value="3">1-3 Moderate technicality</option>
      <option value="4">1-4 Advanced language</option>
    </select>
    <label for="min-in-degree">Min in-degree</label>
    <input id="min-in-degree" type="number" min="0" step="1" value="5" />
    <label for="min-out-degree">Min out-degree</label>
    <input id="min-out-degree" type="number" min="0" step="1" value="5" />
    <label for="min-kcore">Min k-core</label>
    <input id="min-kcore" type="number" min="0" step="1" value="10" />
    <label for="core-percentile">Percentile cutoff</label>
    <input id="core-percentile" type="range" min="0" max="95" step="5" value="40" />
    <span id="core-percentile-value">40%</span>
    <label><input id="require-abstract" type="checkbox" checked /> Require abstract</label>
  </div>
  <p><strong>Language scale:</strong> 1-2 plain wording, 3 moderate technical wording, 4-5 specialist terminology density.</p>
  <div class="explorer-actions">
    <button id="core-apply">Apply Core Filter</button>
    <button id="load-full-corpus" type="button">Load Full Corpus</button>
    <button id="node-drag-toggle" type="button">Enable Node Drag</button>
    <button id="graph-relayout">Re-Layout Graph</button>
  </div>
  <div id="graph-status"></div>
  <div class="explorer-legend">
    <span><strong>Direction:</strong> <i class="legend-swatch swatch-in"></i>incoming <i class="legend-swatch swatch-out"></i>outgoing</span>
    <span><strong>k-core tier:</strong> <i class="legend-swatch swatch-high"></i>core <i class="legend-swatch swatch-mid"></i>middle <i class="legend-swatch swatch-low"></i>peripheral</span>
    <span><strong>Node size:</strong> log(total citations); click a node to emphasize induced subgraph</span>
  </div>
  </details>

<div id="paper-graph" class="reveal"></div>

<div class="panel reveal">
  <h3>Selected Paper</h3>
  <div id="paper-details">Select a node to view summary, source link, and relationship choices.</div>
  <h3>Relationship Navigator</h3>
  <div class="rel-section">
    <h4>Parents (papers this one cites)</h4>
    <div id="parent-links"></div>
  </div>
  <div class="rel-section">
    <h4>Children (papers that cite this one)</h4>
    <div id="child-links"></div>
  </div>
  <div class="rel-section">
    <h4>Related (nearby in citation neighborhood)</h4>
    <div id="related-links"></div>
  </div>
</div>

<div class="tools-panel reveal">
  <h3>Tools</h3>
  <div class="tool-grid">
    <section class="tool-card">
      <h4>Direct Search</h4>
      <p>Search directly by author, title, or abstract text.</p>
      <div class="explorer-search">
        <label for="direct-search-mode">Search in</label>
        <select id="direct-search-mode">
          <option value="all" selected>All fields</option>
          <option value="author">Author</option>
          <option value="title">Title</option>
          <option value="abstract">Abstract</option>
        </select>
        <label for="direct-search-input">Query</label>
        <input id="direct-search-input" type="text" placeholder="Example: Giovannoni OR neurofilament OR remyelination" />
        <button id="direct-search-run" type="button">Run Search</button>
      </div>
      <div id="direct-search-results"></div>
    </section>

    <section class="tool-card">
      <h4>Find Research Like...</h4>
      <p>Write a brief research idea and retrieve relevant papers in the current filtered corpus.</p>
      <textarea id="idea-input" placeholder="Example: EBV-linked immune mechanisms that connect to progression biomarkers in MS"></textarea>
      <div class="explorer-actions">
        <button id="idea-run" type="button">Find Relevant Papers</button>
      </div>
      <div id="idea-results"></div>
    </section>

    <section class="tool-card">
      <h4>Learning Journey Builder</h4>
      <p>Add papers from the graph or tool results, then generate a staged learning journey.</p>
      <div id="journey-selected"></div>
      <div class="explorer-actions">
        <button id="journey-generate" type="button">Generate Learning Journey</button>
        <button id="journey-clear" type="button">Clear Selection</button>
      </div>
      <div id="journey-results"></div>
    </section>
  </div>
</div>

<script>
(() => {
  const graphEl = document.getElementById("paper-graph");
  const detailsEl = document.getElementById("paper-details");
  const parentEl = document.getElementById("parent-links");
  const childEl = document.getElementById("child-links");
  const relatedEl = document.getElementById("related-links");
  const directSearchModeEl = document.getElementById("direct-search-mode");
  const directSearchInputEl = document.getElementById("direct-search-input");
  const directSearchRunEl = document.getElementById("direct-search-run");
  const directSearchResultsEl = document.getElementById("direct-search-results");
  const ideaInputEl = document.getElementById("idea-input");
  const ideaResultsEl = document.getElementById("idea-results");
  const journeySelectedEl = document.getElementById("journey-selected");
  const journeyResultsEl = document.getElementById("journey-results");
  const journeyGenerateEl = document.getElementById("journey-generate");
  const journeyClearEl = document.getElementById("journey-clear");
  const ideaRunEl = document.getElementById("idea-run");
  const relayoutEl = document.getElementById("graph-relayout");
  const nodeDragToggleEl = document.getElementById("node-drag-toggle");
  const graphStatusEl = document.getElementById("graph-status");
  const coreMetricEl = document.getElementById("core-metric");
  const difficultyMaxEl = document.getElementById("difficulty-max");
  const minInDegreeEl = document.getElementById("min-in-degree");
  const minOutDegreeEl = document.getElementById("min-out-degree");
  const minKcoreEl = document.getElementById("min-kcore");
  const corePctEl = document.getElementById("core-percentile");
  const corePctValueEl = document.getElementById("core-percentile-value");
  const coreApplyEl = document.getElementById("core-apply");
  const loadFullCorpusEl = document.getElementById("load-full-corpus");
  const requireAbstractEl = document.getElementById("require-abstract");
  const presetUndergradEl = document.getElementById("preset-undergrad");
  const presetBalancedEl = document.getElementById("preset-balanced");
  const presetGradEl = document.getElementById("preset-grad");
  const isMobileView = window.matchMedia("(max-width: 1000px), (pointer: coarse)").matches;
  const fullDataUrl = "../assets/explorer_graph.json";
  const fullDetailsUrl = "../assets/explorer_details.json";
  const initialPayloadCandidates = isMobileView
    ? [
        { url: "../assets/explorer_graph_mobile.json", detailsUrl: "../assets/explorer_details_mobile.json", mode: "mobile", label: "mobile" },
        { url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" },
      ]
    : [
        { url: "../assets/explorer_graph_lite.json", detailsUrl: "../assets/explorer_details_lite.json", mode: "lite", label: "lite" },
        { url: "../assets/explorer_graph_mobile.json", detailsUrl: "../assets/explorer_details_mobile.json", mode: "mobile", label: "mobile" },
        { url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" },
      ];
  const categoryColors = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
  };
  const stopWords = new Set([
    "a","an","the","and","or","but","for","with","from","that","this","into","about","using","through","between",
    "their","they","are","was","were","how","what","when","where","which","who","our","your","you","can","could",
    "should","would","will","may","might","have","has","had","been","being","its","it's","it","as","at","by","to",
    "in","on","of","if","than","then","also","we","i","he","she","them","these","those","there","here","do","does",
    "did","done","not","no","yes","up","down","over","under","new","study","paper"
  ]);
  const FIELD_WEIGHTS = {
    title: 3.4,
    abstract: 2.2,
    summary: 1.6,
    topic: 1.3,
    why: 1.0,
  };
  const QUERY_EXPANSIONS = {
    ms: ["multiple", "sclerosis", "demyelination", "neuroinflammation"],
    rrms: ["relapsing", "remitting", "multiple", "sclerosis"],
    spms: ["secondary", "progressive", "multiple", "sclerosis"],
    ppms: ["primary", "progressive", "multiple", "sclerosis"],
    dmt: ["disease", "modifying", "therapy", "therapeutic"],
    dmts: ["disease", "modifying", "therapy", "therapeutic"],
    nfl: ["neurofilament", "biomarker"],
    ocb: ["oligoclonal", "bands", "csf"],
    ocbcsf: ["oligoclonal", "bands", "csf"],
    mri: ["magnetic", "resonance", "imaging", "lesion"],
    oct: ["optical", "coherence", "tomography", "retinal"],
    btk: ["brutons", "tyrosine", "kinase", "inhibitor"],
    eae: ["experimental", "autoimmune", "encephalomyelitis", "model"],
    ebv: ["epstein", "barr", "virus"],
    bbb: ["blood", "brain", "barrier"],
    gwas: ["genome", "wide", "association", "genetic"],
    cd20: ["b", "cell", "depletion", "ocrelizumab", "rituximab"],
  };

  let renderer = null;
  let sigmaGraph = null;
  let selectedNodeId = null;
  let rawNodes = [];
  let rawEdges = [];
  let visibleNodes = [];
  let visibleEdges = [];
  let nodeById = new Map();
  let undirected = new Map();
  let incoming = new Map();
  let outgoing = new Map();
  let kcoreThresholds = { lowMax: 0, midMax: 0 };
  let selectedIncoming = new Set();
  let selectedOutgoing = new Set();
  let selectedIncident = new Set();
  let dragEnabled = false;
  let draggingNode = null;
  let payloadMode = isMobileView ? "mobile" : "lite";
  let detailsUrlActive = initialPayloadCandidates[0].detailsUrl;
  let isLoadingCorpus = false;
  let detailsById = null;
  let detailsLoadPromise = null;
  let detailsLoadError = "";
  const loadStats = {
    payloadBytes: 0,
    fetchMs: 0,
    parseMs: 0,
    detailsBytes: 0,
    detailsFetchMs: 0,
    detailsParseMs: 0,
  };
  let journeySelection = [];
  let paperRankMap = new Map();
  let paperAgeRankMap = new Map();
  let authorStatsMap = new Map();
  let searchIndexCache = { signature: "", index: null };

  function setGraphStatus(text, strong = false) {
    if (!graphStatusEl) return;
    const safe = escapeHtml(String(text || ""));
    graphStatusEl.innerHTML = strong ? `<p><strong>${safe}</strong></p>` : `<p><em>${safe}</em></p>`;
  }

  async function fetchTextWithTimeout(url, timeoutMs = 20000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error("timeout")), timeoutMs);
    try {
      const response = await fetch(url, { signal: controller.signal });
      return response;
    } finally {
      clearTimeout(timer);
    }
  }

  window.addEventListener("error", (event) => {
    const msg = event?.error?.message || event?.message || "Unknown script error";
    setGraphStatus(`Explorer runtime error: ${msg}`, true);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event?.reason;
    const msg = typeof reason === "string" ? reason : (reason?.message || String(reason || "Unknown promise rejection"));
    setGraphStatus(`Explorer async error: ${msg}`, true);
  });

  function escapeHtml(text) {
    return (text || "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function cleanNarrativeText(text) {
    let t = String(text || "").trim();
    if (!t) return "";
    t = t.replace(/\\bnan\\b/gi, "").replace(/\\s{2,}/g, " ").trim();
    const genericPatterns = [
      /^this\\s+\\d{4}(?:\\.0)?\\s+paper\\s+in\\s+.+?contributes\\s+to\\s+our\\s+understanding\\s+of\\s+multiple\\s+sclerosis\\.?$/i,
      /^this\\s+paper\\s+in\\s+.+?contributes\\s+to\\s+our\\s+understanding\\s+of\\s+multiple\\s+sclerosis\\.?$/i,
    ];
    if (genericPatterns.some((rx) => rx.test(t))) {
      return "";
    }
    return t;
  }

  function formatMB(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "n/a";
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function normalizeNode(node) {
    const n = { ...(node || {}) };
    n.id = String(n.id || "");
    n.title = String(n.title || "Untitled");
    n.year = Number.isFinite(Number(n.year)) ? Math.trunc(Number(n.year)) : null;
    n.source_url = String(n.source_url || "").trim();
    n.doi = String(n.doi || "").trim();
    n.first_author = String(n.first_author || "").trim();
    n.venue = String(n.venue || "").trim();
    n.topic_label = String(n.topic_label || "").trim();
    n.importance = Number(n.importance || 0);
    n.age_normalized_importance = Number(n.age_normalized_importance || 0);
    n.rank_age_normalized_importance = Number(n.rank_age_normalized_importance || 0);
    n.citations_per_year = Number(n.citations_per_year || 0);
    n.paper_age_years = Number(n.paper_age_years || 0);
    n.citation_count = Math.max(0, Math.trunc(Number(n.citation_count || 0)));
    n.pagerank = Number(n.pagerank || 0);
    n.kcore = Math.max(0, Math.trunc(Number(n.kcore || 0)));
    n.in_degree = Math.max(0, Math.trunc(Number(n.in_degree || 0)));
    n.out_degree = Math.max(0, Math.trunc(Number(n.out_degree || 0)));
    n.rank_pagerank = Number(n.rank_pagerank || 0);
    n.rank_kcore = Number(n.rank_kcore || 0);
    n.rank_in_degree = Number(n.rank_in_degree || 0);
    n.core_score = Number(n.core_score || 0);
    n.difficulty = Math.max(1, Math.min(5, Math.trunc(Number(n.difficulty || 3))));
    n.has_abstract = Boolean(n.has_abstract);
    n.tier = String(n.tier || "");
    n.evidence_type = String(n.evidence_type || "other");
    n.evidence_strength = Math.max(1, Math.min(5, Math.trunc(Number(n.evidence_strength || 2))));
    n.abstract = String(n.abstract || "");
    n.summary = String(n.summary || "");
    n.summary_source = String(n.summary_source || "");
    n.why_it_matters = String(n.why_it_matters || "");
    n.key_takeaways = Array.isArray(n.key_takeaways) ? n.key_takeaways : [];
    n.summary_generated_at_utc = String(n.summary_generated_at_utc || "");
    n.distill_method = String(n.distill_method || "");
    n.summary_certainty_score = Number(n.summary_certainty_score || 0);
    n.summary_certainty_label = String(n.summary_certainty_label || "");
    n.summary_disclaimer = String(n.summary_disclaimer || "");
    n.faithfulness_overlap = Number(n.faithfulness_overlap || 0);
    n.source_text_hash = String(n.source_text_hash || "");
    n.source_text_chars = Math.max(0, Math.trunc(Number(n.source_text_chars || 0)));
    n._detailsLoaded = Boolean(n._detailsLoaded);
    return n;
  }

  function decodeGraphPayload(payload) {
    if (payload && Array.isArray(payload.node_fields) && Array.isArray(payload.nodes)) {
      const fields = payload.node_fields;
      const nodes = payload.nodes.map((row) => {
        const obj = {};
        fields.forEach((field, idx) => {
          obj[field] = Array.isArray(row) ? row[idx] : undefined;
        });
        return normalizeNode(obj);
      });
      let edges = [];
      if (Array.isArray(payload.edges)) {
        if (payload.edges_are_indexed) {
          edges = payload.edges
            .map((entry) => {
              if (!Array.isArray(entry) || entry.length < 2) return null;
              const sourceNode = nodes[Number(entry[0])];
              const targetNode = nodes[Number(entry[1])];
              if (!sourceNode || !targetNode || !sourceNode.id || !targetNode.id || sourceNode.id === targetNode.id) {
                return null;
              }
              return { source: sourceNode.id, target: targetNode.id, type: "CITES" };
            })
            .filter(Boolean);
        } else {
          edges = payload.edges
            .map((entry) => {
              if (!entry) return null;
              if (Array.isArray(entry) && entry.length >= 2) {
                return { source: String(entry[0] || ""), target: String(entry[1] || ""), type: "CITES" };
              }
              if (typeof entry === "object") {
                return {
                  source: String(entry.source || ""),
                  target: String(entry.target || ""),
                  type: String(entry.type || "CITES"),
                };
              }
              return null;
            })
            .filter((e) => e && e.source && e.target && e.source !== e.target);
        }
      }
      return { nodes, edges };
    }

    const nodes = (payload?.nodes || []).map((node) => normalizeNode(node));
    const edges = (payload?.edges || [])
      .map((edge) => ({
        source: String(edge?.source || ""),
        target: String(edge?.target || ""),
        type: String(edge?.type || "CITES"),
      }))
      .filter((e) => e.source && e.target && e.source !== e.target);
    return { nodes, edges };
  }

  function decodeDetailsPayload(payload) {
    const map = new Map();
    if (payload && Array.isArray(payload.fields) && Array.isArray(payload.rows)) {
      const fields = payload.fields;
      payload.rows.forEach((row) => {
        if (!Array.isArray(row)) return;
        const obj = {};
        fields.forEach((field, idx) => {
          obj[field] = row[idx];
        });
        const id = String(obj.id || "");
        if (!id) return;
        map.set(id, {
          abstract: String(obj.abstract || ""),
          summary: String(obj.summary || ""),
          summary_source: String(obj.summary_source || ""),
          why_it_matters: String(obj.why_it_matters || ""),
          key_takeaways: Array.isArray(obj.key_takeaways) ? obj.key_takeaways : [],
          summary_generated_at_utc: String(obj.summary_generated_at_utc || ""),
          distill_method: String(obj.distill_method || ""),
          summary_certainty_score: Number(obj.summary_certainty_score || 0),
          summary_certainty_label: String(obj.summary_certainty_label || ""),
          summary_disclaimer: String(obj.summary_disclaimer || ""),
          faithfulness_overlap: Number(obj.faithfulness_overlap || 0),
          source_text_hash: String(obj.source_text_hash || ""),
          source_text_chars: Number(obj.source_text_chars || 0),
        });
      });
      return map;
    }
    const detailsObj = (payload && typeof payload.details === "object") ? payload.details : {};
    Object.entries(detailsObj || {}).forEach(([id, obj]) => {
      if (!id) return;
      map.set(String(id), {
        abstract: String(obj?.abstract || ""),
        summary: String(obj?.summary || ""),
        summary_source: String(obj?.summary_source || ""),
        why_it_matters: String(obj?.why_it_matters || ""),
        key_takeaways: Array.isArray(obj?.key_takeaways) ? obj.key_takeaways : [],
        summary_generated_at_utc: String(obj?.summary_generated_at_utc || ""),
        distill_method: String(obj?.distill_method || ""),
        summary_certainty_score: Number(obj?.summary_certainty_score || 0),
        summary_certainty_label: String(obj?.summary_certainty_label || ""),
        summary_disclaimer: String(obj?.summary_disclaimer || ""),
        faithfulness_overlap: Number(obj?.faithfulness_overlap || 0),
        source_text_hash: String(obj?.source_text_hash || ""),
        source_text_chars: Number(obj?.source_text_chars || 0),
      });
    });
    return map;
  }

  function mergeNodeDetails(detailMap) {
    detailsById = detailMap instanceof Map ? detailMap : new Map();
    rawNodes = rawNodes.map((node) => {
      const details = detailsById.get(node.id);
      if (!details) {
        return { ...node, _detailsLoaded: true };
      }
      return {
        ...node,
        abstract: String(details.abstract || ""),
        summary: String(details.summary || ""),
        summary_source: String(details.summary_source || ""),
        why_it_matters: String(details.why_it_matters || ""),
        key_takeaways: Array.isArray(details.key_takeaways) ? details.key_takeaways : [],
        summary_generated_at_utc: String(details.summary_generated_at_utc || ""),
        distill_method: String(details.distill_method || ""),
        summary_certainty_score: Number(details.summary_certainty_score || 0),
        summary_certainty_label: String(details.summary_certainty_label || ""),
        summary_disclaimer: String(details.summary_disclaimer || ""),
        faithfulness_overlap: Number(details.faithfulness_overlap || 0),
        source_text_hash: String(details.source_text_hash || ""),
        source_text_chars: Number(details.source_text_chars || 0),
        _detailsLoaded: true,
      };
    });
    searchIndexCache = { signature: "", index: null };
  }

  function ensureDetailsLoaded() {
    if (detailsById instanceof Map) return Promise.resolve(detailsById);
    if (detailsLoadPromise) return detailsLoadPromise;
    const detailsStart = performance.now();
    detailsLoadPromise = fetch(detailsUrlActive)
      .then(async (r) => {
        const text = await r.text();
        const parseStart = performance.now();
        loadStats.detailsFetchMs = parseStart - detailsStart;
        loadStats.detailsBytes = Number(r.headers.get("content-length")) || (text.length * 2);
        const payload = JSON.parse(text);
        loadStats.detailsParseMs = performance.now() - parseStart;
        const detailMap = decodeDetailsPayload(payload);
        mergeNodeDetails(detailMap);
        return detailsById;
      })
      .catch((err) => {
        detailsLoadError = String(err || "unknown error");
        detailsById = new Map();
        rawNodes = rawNodes.map((node) => ({ ...node, _detailsLoaded: true }));
        return detailsById;
      })
      .finally(() => {
        detailsLoadPromise = null;
      });
    return detailsLoadPromise;
  }

  function cleanDoi(doi) {
    const value = String(doi || "").trim();
    if (!value) return "";
    return value.replace(/^https?:\\/\\/doi\\.org\\//i, "");
  }

  function citationPlaintextForNode(node) {
    const author = String(node?.first_author || "").trim() || "Unknown author";
    const year = Number.isFinite(Number(node?.year)) ? Math.trunc(Number(node.year)) : "n.d.";
    const title = String(node?.title || "Untitled").trim();
    const venue = String(node?.venue || "").trim();
    const source = String(node?.source_url || "").trim();
    const pieces = [`${author}. (${year}). ${title}.`];
    if (venue) pieces.push(`${venue}.`);
    if (source) pieces.push(source);
    return pieces.join(" ").trim();
  }

  function citationBibtexForNode(node) {
    const id = String(node?.id || "paper").replace(/[^a-zA-Z0-9]/g, "").slice(0, 12);
    const year = Number.isFinite(Number(node?.year)) ? String(Math.trunc(Number(node.year))) : "0000";
    const key = `mskb_${id}_${year}`;
    const esc = (s) => String(s || "").replace(/\\\\/g, "\\\\\\\\").replace(/\\{/g, "\\\\{").replace(/\\}/g, "\\\\}");
    const lines = [
      `@article{${key},`,
      `  title = {${esc(node?.title || "Untitled")}},`,
      `  author = {${esc(node?.first_author || "Unknown")}},`,
      `  year = {${year}},`,
    ];
    if (node?.venue) lines.push(`  journal = {${esc(node.venue)}},`);
    const doi = cleanDoi(node?.doi || "");
    if (doi) lines.push(`  doi = {${esc(doi)}},`);
    if (node?.source_url) lines.push(`  url = {${esc(node.source_url)}},`);
    lines.push("}");
    return lines.join("\\n");
  }

  function normalizeText(text) {
    return (text || "")
      .toLowerCase()
      .replace(/[^a-z0-9\\s]/g, " ")
      .replace(/\\s+/g, " ")
      .trim();
  }

  function stemToken(token) {
    let t = token;
    if (t.length > 6 && t.endsWith("ation")) t = t.slice(0, -5);
    else if (t.length > 5 && t.endsWith("ing")) t = t.slice(0, -3);
    else if (t.length > 4 && t.endsWith("ed")) t = t.slice(0, -2);
    else if (t.length > 4 && t.endsWith("ly")) t = t.slice(0, -2);
    else if (t.length > 5 && t.endsWith("ment")) t = t.slice(0, -4);
    else if (t.length > 4 && t.endsWith("ies")) t = `${t.slice(0, -3)}y`;
    else if (t.length > 4 && t.endsWith("s")) t = t.slice(0, -1);
    return t;
  }

  function tokenize(text) {
    return normalizeText(text)
      .split(/\\s+/)
      .filter(t => t && t.length > 1 && !stopWords.has(t))
      .map(stemToken)
      .filter(t => t.length > 1 && !stopWords.has(t));
  }

  function tokenCounts(tokens) {
    const m = new Map();
    for (const t of tokens) {
      m.set(t, (m.get(t) || 0) + 1);
    }
    return m;
  }

  function nodeSetSignature(nodes) {
    if (!nodes || !nodes.length) return "0";
    const first = nodes[0]?.id || "";
    const last = nodes[nodes.length - 1]?.id || "";
    return `${nodes.length}:${first}:${last}`;
  }

  function prepareSearchIndex(nodes) {
    const signature = nodeSetSignature(nodes);
    if (searchIndexCache.signature === signature && searchIndexCache.index) {
      return searchIndexCache.index;
    }
    const docs = [];
    const totals = { title: 0, abstract: 0, summary: 0, topic: 0, why: 0 };
    for (const node of nodes) {
      const titleNorm = normalizeText(node.title || "");
      const abstractNorm = normalizeText(node.abstract || "");
      const summaryNorm = normalizeText(node.summary || "");
      const topicNorm = normalizeText(node.topic_label || "");
      const whyNorm = normalizeText(node.why_it_matters || "");

      const fieldTokens = {
        title: tokenize(titleNorm),
        abstract: tokenize(abstractNorm),
        summary: tokenize(summaryNorm),
        topic: tokenize(topicNorm),
        why: tokenize(whyNorm),
      };

      totals.title += Math.max(1, fieldTokens.title.length);
      totals.abstract += Math.max(1, fieldTokens.abstract.length);
      totals.summary += Math.max(1, fieldTokens.summary.length);
      totals.topic += Math.max(1, fieldTokens.topic.length);
      totals.why += Math.max(1, fieldTokens.why.length);

      const fieldCounts = {
        title: tokenCounts(fieldTokens.title),
        abstract: tokenCounts(fieldTokens.abstract),
        summary: tokenCounts(fieldTokens.summary),
        topic: tokenCounts(fieldTokens.topic),
        why: tokenCounts(fieldTokens.why),
      };
      const allTerms = new Set([
        ...fieldCounts.title.keys(),
        ...fieldCounts.abstract.keys(),
        ...fieldCounts.summary.keys(),
        ...fieldCounts.topic.keys(),
        ...fieldCounts.why.keys(),
      ]);
      docs.push({
        node,
        allTerms,
        combinedNorm: `${titleNorm} ${abstractNorm} ${summaryNorm} ${topicNorm} ${whyNorm}`.trim(),
        titleNorm,
        fieldCounts,
        fieldLengths: {
          title: Math.max(1, fieldTokens.title.length),
          abstract: Math.max(1, fieldTokens.abstract.length),
          summary: Math.max(1, fieldTokens.summary.length),
          topic: Math.max(1, fieldTokens.topic.length),
          why: Math.max(1, fieldTokens.why.length),
        },
      });
    }

    const n = Math.max(1, docs.length);
    const index = {
      docs,
      avgLens: {
        title: totals.title / n,
        abstract: totals.abstract / n,
        summary: totals.summary / n,
        topic: totals.topic / n,
        why: totals.why / n,
      },
    };
    searchIndexCache = { signature, index };
    return index;
  }

  function expandQueryTokens(tokens, queryNorm) {
    const expanded = [...tokens];
    const raw = queryNorm.split(/\\s+/).filter(Boolean);
    for (const t of raw) {
      if (QUERY_EXPANSIONS[t]) {
        expanded.push(...QUERY_EXPANSIONS[t]);
      }
    }
    return expanded.map(stemToken).filter(t => t.length > 1 && !stopWords.has(t));
  }

  function buildQueryModel(queryText, index) {
    const queryNorm = normalizeText(queryText);
    const rawTokens = tokenize(queryNorm);
    const terms = Array.from(new Set(expandQueryTokens(rawTokens, queryNorm)));
    const df = new Map();
    for (const term of terms) df.set(term, 0);
    for (const doc of index.docs) {
      for (const term of terms) {
        if (doc.allTerms.has(term)) df.set(term, (df.get(term) || 0) + 1);
      }
    }
    const totalDocs = Math.max(1, index.docs.length);
    const idf = new Map();
    for (const term of terms) {
      const d = df.get(term) || 0;
      idf.set(term, Math.log(1 + (totalDocs - d + 0.5) / (d + 0.5)));
    }

    const bigrams = [];
    for (let i = 0; i < rawTokens.length - 1; i += 1) {
      bigrams.push(`${rawTokens[i]} ${rawTokens[i + 1]}`);
    }
    return { queryNorm, rawTokens, terms, idf, bigrams };
  }

  function bm25(tf, len, avgLen, idf, k1 = 1.35, b = 0.72) {
    if (!tf) return 0;
    const denom = tf + k1 * (1 - b + b * (len / Math.max(1e-9, avgLen)));
    return idf * ((tf * (k1 + 1)) / denom);
  }

  function colorFor(node) {
    if (!node || !node.topic_label) return "#4c78a8";
    const key = (node.topic_label || "").toLowerCase();
    for (const [cat, color] of Object.entries(categoryColors)) {
      if (key.includes(cat.replaceAll("_", " ").split(" ")[0])) return color;
    }
    return "#4c78a8";
  }

  function nodeSizeFromCitations(node) {
    const cites = Math.max(0, Number(node?.citation_count || 0));
    return Math.max(4, Math.log1p(cites) * 3.2);
  }

  function quantile(sorted, q) {
    if (!sorted.length) return 0;
    const pos = (sorted.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    if (sorted[base + 1] !== undefined) {
      return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
    }
    return sorted[base];
  }

  function computeKcoreThresholds(nodes) {
    const values = nodes
      .map((n) => Number(n.kcore || 0))
      .filter((v) => Number.isFinite(v))
      .sort((a, b) => a - b);
    if (!values.length) return { lowMax: 0, midMax: 0 };
    return {
      lowMax: quantile(values, 0.33),
      midMax: quantile(values, 0.66),
    };
  }

  function kcoreTier(node) {
    const v = Number(node?.kcore || 0);
    if (v <= kcoreThresholds.lowMax) return "low";
    if (v <= kcoreThresholds.midMax) return "mid";
    return "high";
  }

  function kcoreBorderColor(node) {
    const tier = kcoreTier(node);
    if (tier === "high") return "#1c9b43";
    if (tier === "mid") return "#d4a72c";
    return "#c84e4e";
  }

  function buildBaseNodeStyle(node) {
    const tierColor = kcoreBorderColor(node);
    return {
      id: node.id,
      label: (node.title || "Untitled").slice(0, 55),
      title: node.title || "Untitled",
      size: nodeSizeFromCitations(node),
      color: tierColor,
      topicColor: colorFor(node),
      kcoreColor: tierColor,
    };
  }

  function getSigmaCtor() {
    return window.Sigma || (window.sigma && (window.sigma.Sigma || window.sigma.default)) || null;
  }

  function getGraphCtor() {
    if (window.graphology && window.graphology.DirectedGraph) return window.graphology.DirectedGraph;
    if (window.graphology && window.graphology.Graph) return window.graphology.Graph;
    return null;
  }

  function killRenderer() {
    if (renderer && typeof renderer.kill === "function") {
      renderer.kill();
    }
    renderer = null;
    sigmaGraph = null;
  }

  function refreshNodeDragToggleLabel() {
    if (!nodeDragToggleEl) return;
    if (isMobileView) {
      nodeDragToggleEl.textContent = "Node Drag (desktop only)";
      nodeDragToggleEl.disabled = true;
      return;
    }
    nodeDragToggleEl.disabled = false;
    nodeDragToggleEl.textContent = dragEnabled ? "Disable Node Drag" : "Enable Node Drag";
  }

  function refreshFullCorpusButton() {
    if (!loadFullCorpusEl) return;
    if (isMobileView) {
      loadFullCorpusEl.disabled = true;
      loadFullCorpusEl.textContent = "Full Corpus (desktop only)";
      return;
    }
    if (payloadMode === "full") {
      loadFullCorpusEl.disabled = true;
      loadFullCorpusEl.textContent = "Full Corpus Loaded";
      return;
    }
    loadFullCorpusEl.disabled = isLoadingCorpus;
    loadFullCorpusEl.textContent = isLoadingCorpus ? "Loading Full Corpus..." : "Load Full Corpus";
  }

  function communityKey(node) {
    const tid = Number(node?.topic_id);
    if (Number.isFinite(tid)) return `topic:${Math.trunc(tid)}`;
    const label = normalizeText(node?.topic_label || "");
    return label ? `label:${label}` : "unassigned";
  }

  function buildCommunityPositions(nodes) {
    const groups = new Map();
    nodes.forEach((n) => {
      const key = communityKey(n);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    });

    const ordered = Array.from(groups.entries()).sort((a, b) => {
      const sizeCmp = b[1].length - a[1].length;
      if (sizeCmp !== 0) return sizeCmp;
      return String(a[0]).localeCompare(String(b[0]));
    });
    if (!ordered.length) return new Map();

    const cols = Math.max(1, Math.ceil(Math.sqrt(ordered.length)));
    const rows = Math.max(1, Math.ceil(ordered.length / cols));
    const spacingX = 620;
    const spacingY = 540;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const positions = new Map();

    ordered.forEach(([_, members], idx) => {
      const col = idx % cols;
      const row = Math.floor(idx / cols);
      const cx = (col - (cols - 1) / 2) * spacingX;
      const cy = (row - (rows - 1) / 2) * spacingY;
      members.sort((a, b) => ((b.citation_count || 0) - (a.citation_count || 0)) || String(a.id).localeCompare(String(b.id)));
      const radialStep = Math.max(18, Math.min(32, 16 + Math.sqrt(members.length)));
      members.forEach((node, i) => {
        if (i === 0) {
          positions.set(node.id, { x: cx, y: cy });
          return;
        }
        const radius = Math.sqrt(i) * radialStep;
        const angle = i * goldenAngle;
        positions.set(node.id, {
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });
    });
    return positions;
  }

  function buildRankIndexes(nodes) {
    const rankedPapers = [...nodes].sort((a, b) => ((b.core_score || 0) - (a.core_score || 0)) || ((b.importance || 0) - (a.importance || 0)));
    paperRankMap = new Map();
    rankedPapers.forEach((n, idx) => paperRankMap.set(n.id, idx + 1));
    const rankedAgeNorm = [...nodes].sort((a, b) => ((b.age_normalized_importance || 0) - (a.age_normalized_importance || 0)) || ((b.importance || 0) - (a.importance || 0)));
    paperAgeRankMap = new Map();
    rankedAgeNorm.forEach((n, idx) => paperAgeRankMap.set(n.id, idx + 1));

    const tempAuthors = new Map();
    nodes.forEach((n) => {
      const name = String(n.first_author || "").trim();
      if (!name) return;
      if (!tempAuthors.has(name)) {
        tempAuthors.set(name, { name, papers: 0, citations: 0, coreScore: 0, topPaperId: n.id, topPaperImportance: Number(n.importance || 0) });
      }
      const a = tempAuthors.get(name);
      a.papers += 1;
      a.citations += Number(n.citation_count || 0);
      a.coreScore += Number(n.core_score || 0);
      const imp = Number(n.importance || 0);
      if (imp > a.topPaperImportance) {
        a.topPaperImportance = imp;
        a.topPaperId = n.id;
      }
    });

    const authors = Array.from(tempAuthors.values()).map((a) => ({
      ...a,
      avgCoreScore: a.papers ? (a.coreScore / a.papers) : 0,
    }));
    authors.sort((a, b) => {
      const sa = Math.log1p(a.citations) * 0.62 + a.avgCoreScore * 2.4 + a.papers * 0.24;
      const sb = Math.log1p(b.citations) * 0.62 + b.avgCoreScore * 2.4 + b.papers * 0.24;
      return sb - sa || a.name.localeCompare(b.name);
    });
    authorStatsMap = new Map();
    authors.forEach((a, idx) => {
      authorStatsMap.set(a.name, { ...a, rank: idx + 1, score: Math.log1p(a.citations) * 0.62 + a.avgCoreScore * 2.4 + a.papers * 0.24 });
    });
  }

  function buildSigmaGraph(positionById) {
    const SigmaCtor = getSigmaCtor();
    const GraphCtor = getGraphCtor();
    if (!SigmaCtor || !GraphCtor) {
      const msg = "Explorer renderer failed to initialize (Sigma/Graphology not loaded).";
      detailsEl.innerHTML = msg;
      graphStatusEl.innerHTML = `<p><strong>${msg}</strong></p>`;
      return false;
    }

    try {
      killRenderer();
      sigmaGraph = (window.graphology && GraphCtor === window.graphology.Graph)
        ? new GraphCtor({ type: "directed", multi: false })
        : new GraphCtor();

      visibleNodes.forEach((n) => {
        const style = buildBaseNodeStyle(n);
        const pos = positionById.get(n.id) || { x: (Math.random() - 0.5) * 2, y: (Math.random() - 0.5) * 2 };
        sigmaGraph.addNode(n.id, {
          label: style.label,
          x: Number(pos.x) || 0,
          y: Number(pos.y) || 0,
          size: Math.max(1.5, Number(style.size) || 2),
          color: style.color,
          topicColor: style.topicColor,
          kcoreColor: style.kcoreColor,
        });
      });

      visibleEdges.forEach((e, idx) => {
        if (!sigmaGraph.hasNode(e.source) || !sigmaGraph.hasNode(e.target)) return;
        const key = `${e.source}->${e.target}-${idx}`;
        if (sigmaGraph.hasEdge(key)) return;
        sigmaGraph.addDirectedEdgeWithKey(key, e.source, e.target, {
          color: "rgba(125,138,150,0.18)",
          size: 1.0,
        });
      });

      renderer = new SigmaCtor(sigmaGraph, graphEl, {
        renderLabels: true,
        labelRenderedSizeThreshold: 14,
        defaultEdgeType: "arrow",
        allowInvalidContainer: true,
      });

      renderer.setSetting("nodeReducer", (node, data) => {
        const reduced = { ...data };

        if (!selectedNodeId) {
          reduced.color = data.kcoreColor || data.color;
          reduced.size = data.size;
          return reduced;
        }

        if (node === selectedNodeId) {
          reduced.color = "#0a3f5c";
          reduced.size = (data.size || 3) * 1.4;
          return reduced;
        }
        if (selectedIncoming.has(node) && selectedOutgoing.has(node)) {
          reduced.color = "#b97e1d";
          reduced.size = (data.size || 3) * 1.18;
          return reduced;
        }
        if (selectedIncoming.has(node)) {
          reduced.color = "#25a16d";
          reduced.size = (data.size || 3) * 1.12;
          return reduced;
        }
        if (selectedOutgoing.has(node)) {
          reduced.color = "#cf5b2f";
          reduced.size = (data.size || 3) * 1.12;
          return reduced;
        }
        reduced.color = "rgba(150,160,170,0.18)";
        reduced.label = "";
        reduced.size = Math.max(1.2, (data.size || 2) * 0.8);
        return reduced;
      });

      renderer.setSetting("edgeReducer", (edge, data) => {
        const reduced = { ...data, color: "rgba(125,138,150,0.18)", size: 1.0 };
        if (!selectedNodeId) return reduced;

        const source = sigmaGraph.source(edge);
        const target = sigmaGraph.target(edge);

        if (source === selectedNodeId) return { ...reduced, color: "#cf5b2f", size: 2.4 };
        if (target === selectedNodeId) return { ...reduced, color: "#25a16d", size: 2.4 };
        if (selectedIncident.has(source) && selectedIncident.has(target)) return { ...reduced, color: "rgba(76,111,138,0.42)", size: 1.2 };
        return { ...reduced, color: "rgba(154,166,178,0.06)", size: 0.6 };
      });

      renderer.on("clickNode", ({ node }) => {
        if (draggingNode) return;
        focusNode(node);
      });
      renderer.on("clickStage", () => {
        selectedNodeId = null;
        styleSelectedSubgraph(null);
      });

      const captor = renderer.getMouseCaptor && renderer.getMouseCaptor();
      if (captor) {
        renderer.on("downNode", ({ node, event }) => {
          if (!dragEnabled || isMobileView) return;
          draggingNode = node;
          if (event && typeof event.preventSigmaDefault === "function") {
            event.preventSigmaDefault();
          }
          if (event && event.original && typeof event.original.preventDefault === "function") {
            event.original.preventDefault();
          }
        });

        captor.on("mousemovebody", (e) => {
          if (!dragEnabled || !draggingNode || !renderer || !sigmaGraph || !sigmaGraph.hasNode(draggingNode)) return;
          const coords = renderer.viewportToGraph ? renderer.viewportToGraph({ x: e.x, y: e.y }) : null;
          if (!coords) return;
          sigmaGraph.setNodeAttribute(draggingNode, "x", coords.x);
          sigmaGraph.setNodeAttribute(draggingNode, "y", coords.y);
          renderer.refresh();
          if (typeof e.preventSigmaDefault === "function") {
            e.preventSigmaDefault();
          }
        });

        const stopDrag = () => {
          draggingNode = null;
        };
        captor.on("mouseup", stopDrag);
        captor.on("mousedown", () => {
          if (!dragEnabled) draggingNode = null;
        });
        captor.on("mouseleave", stopDrag);
      }

      return true;
    } catch (err) {
      const msg = `Explorer renderer failed during graph construction: ${err}`;
      detailsEl.innerHTML = msg;
      graphStatusEl.innerHTML = `<p><strong>${escapeHtml(String(msg))}</strong></p>`;
      return false;
    }
  }

  function journeyButtonLabel(id) {
    return journeySelection.includes(id) ? "Remove" : "Add";
  }

  function renderActionButtons(node) {
    return `<button data-focus="${node.id}">Focus</button> <button data-journey-toggle="${node.id}">${journeyButtonLabel(node.id)}</button>`;
  }

  async function runDirectSearch() {
    const mode = String(directSearchModeEl.value || "all");
    const qRaw = String(directSearchInputEl.value || "").trim();
    const q = normalizeText(qRaw);
    if (!q) {
      directSearchResultsEl.innerHTML = "<p>Enter a query and choose a field scope.</p>";
      return;
    }
    if ((mode === "abstract" || mode === "all") && !(detailsById instanceof Map) && !detailsLoadError) {
      directSearchResultsEl.innerHTML = "<p>Loading text details for search...</p>";
      await ensureDetailsLoaded();
    }

    const corpus = visibleNodes.length ? visibleNodes : rawNodes;
    const rows = corpus
      .filter((n) => {
        const author = normalizeText(n.first_author || "");
        const title = normalizeText(n.title || "");
        const abstract = normalizeText(n.abstract || "");
        if (mode === "author") return author.includes(q);
        if (mode === "title") return title.includes(q);
        if (mode === "abstract") return abstract.includes(q);
        return author.includes(q) || title.includes(q) || abstract.includes(q);
      })
      .map((n) => {
        const author = normalizeText(n.first_author || "");
        const title = normalizeText(n.title || "");
        const abstract = normalizeText(n.abstract || "");
        let exact = false;
        let starts = false;
        if (mode === "author") {
          exact = author === q;
          starts = author.startsWith(q);
        } else if (mode === "title") {
          exact = title === q;
          starts = title.startsWith(q);
        } else if (mode === "abstract") {
          exact = abstract === q;
          starts = abstract.startsWith(q);
        } else {
          exact = author === q || title === q || abstract === q;
          starts = author.startsWith(q) || title.startsWith(q) || abstract.startsWith(q);
        }
        return { n, exact, starts };
      })
      .sort((a, b) =>
        Number(b.exact) - Number(a.exact)
        || Number(b.starts) - Number(a.starts)
        || ((paperRankMap.get(a.n.id) || 10**9) - (paperRankMap.get(b.n.id) || 10**9))
        || ((b.n.citation_count || 0) - (a.n.citation_count || 0))
      )
      .slice(0, 20);

    if (!rows.length) {
      directSearchResultsEl.innerHTML = "<p>No matches found.</p>";
      return;
    }
    directSearchResultsEl.innerHTML = `
      <p><strong>Matches</strong></p>
      <ol>
        ${rows.map(({ n }) => {
          const rank = paperRankMap.get(n.id) || "?";
          const total = corpus.length || 1;
          const author = escapeHtml(String(n.first_author || "Unknown"));
          return `<li>${renderActionButtons(n)} ${escapeHtml(n.title || "Untitled")} <em>(author: ${author}; paper rank ${rank}/${total})</em></li>`;
        }).join("")}
      </ol>
    `;
  }

  function scoreIdeaDoc(doc, model, index) {
    let score = 0;
    for (const term of model.terms) {
      const idf = model.idf.get(term) || 0;
      if (!idf) continue;
      for (const [field, weight] of Object.entries(FIELD_WEIGHTS)) {
        const tf = doc.fieldCounts[field].get(term) || 0;
        if (!tf) continue;
        score += weight * bm25(tf, doc.fieldLengths[field], index.avgLens[field], idf);
      }
    }

    if (model.queryNorm && model.queryNorm.length > 5) {
      if (doc.titleNorm.includes(model.queryNorm)) score += 4.5;
      if (doc.combinedNorm.includes(model.queryNorm)) score += 2.4;
    }
    for (const bg of model.bigrams) {
      if (doc.titleNorm.includes(bg)) score += 1.4;
      else if (doc.combinedNorm.includes(bg)) score += 0.8;
    }

    const citationPrior = Math.log1p(doc.node.citation_count || 0);
    const centralityPrior = (doc.node.core_score || 0) * 2.2 + (doc.node.rank_pagerank || 0);
    score += 0.18 * citationPrior + 0.45 * centralityPrior;
    return score;
  }

  function rebuildAdjacency(nodes, edges) {
    nodeById = new Map(nodes.map(n => [n.id, n]));
    undirected = new Map(nodes.map(n => [n.id, new Set()]));
    incoming = new Map(nodes.map(n => [n.id, new Set()]));
    outgoing = new Map(nodes.map(n => [n.id, new Set()]));
    edges.forEach(e => {
      if (!undirected.has(e.source) || !undirected.has(e.target)) return;
      undirected.get(e.source).add(e.target);
      undirected.get(e.target).add(e.source);
      outgoing.get(e.source).add(e.target);
      incoming.get(e.target).add(e.source);
    });
  }

  function styleSelectedSubgraph(focusId) {
    selectedNodeId = focusId || null;
    selectedIncoming = new Set(selectedNodeId ? Array.from(incoming.get(selectedNodeId) || []) : []);
    selectedOutgoing = new Set(selectedNodeId ? Array.from(outgoing.get(selectedNodeId) || []) : []);
    selectedIncident = new Set(selectedNodeId ? [selectedNodeId, ...selectedIncoming, ...selectedOutgoing] : []);
    if (renderer) renderer.refresh();
  }

  function setPreset(mode) {
    if (mode === "undergrad") {
      coreMetricEl.value = "composite";
      difficultyMaxEl.value = "3";
      minInDegreeEl.value = "3";
      minOutDegreeEl.value = "3";
      minKcoreEl.value = "6";
      corePctEl.value = "20";
      requireAbstractEl.checked = true;
    } else if (mode === "grad") {
      coreMetricEl.value = "pagerank";
      difficultyMaxEl.value = "5";
      minInDegreeEl.value = "8";
      minOutDegreeEl.value = "8";
      minKcoreEl.value = "12";
      corePctEl.value = "60";
      requireAbstractEl.checked = true;
    } else {
      coreMetricEl.value = "composite";
      difficultyMaxEl.value = "4";
      minInDegreeEl.value = "5";
      minOutDegreeEl.value = "5";
      minKcoreEl.value = "10";
      corePctEl.value = "40";
      requireAbstractEl.checked = true;
    }
    corePctValueEl.textContent = `${corePctEl.value}%`;
    applyCoreFilter();
  }

  function applyCoreFilter() {
    const metric = coreMetricEl.value || "composite";
    const maxDifficulty = Number(difficultyMaxEl.value || 5);
    const minInDegree = Math.max(0, Number(minInDegreeEl.value || 0));
    const minOutDegree = Math.max(0, Number(minOutDegreeEl.value || 0));
    const minKcore = Math.max(0, Number(minKcoreEl.value || 0));
    const cutoff = Number(corePctEl.value || 0) / 100;
    const requireAbstract = !!requireAbstractEl.checked;
    corePctValueEl.textContent = `${Math.round(cutoff * 100)}%`;

    const matchedNodes = rawNodes
        .filter(n => !requireAbstract || !!n.has_abstract)
        .filter(n => Number(n.difficulty || 3) <= maxDifficulty)
        .filter(n => Number(n.in_degree || 0) >= minInDegree)
        .filter(n => Number(n.out_degree || 0) >= minOutDegree)
        .filter(n => Number(n.kcore || 0) >= minKcore)
        .filter(n => {
          if (metric === "pagerank") return (n.rank_pagerank || 0) >= cutoff;
          if (metric === "kcore") return (n.rank_kcore || 0) >= cutoff;
          if (metric === "in_degree") return (n.rank_in_degree || 0) >= cutoff;
          if (metric === "age_normalized") return (n.rank_age_normalized_importance || 0) >= cutoff;
          return (n.core_score || 0) >= cutoff;
        });

    const renderNodes = matchedNodes;

    const nodeIds = new Set(
      renderNodes
        .map(n => n.id)
    );

    if (graphStatusEl) {
      const communities = new Set(renderNodes.map(n => communityKey(n))).size;
      const edgesCount = rawEdges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target)).length;
      const heapBytes = (performance && performance.memory && performance.memory.usedJSHeapSize)
        ? Number(performance.memory.usedJSHeapSize)
        : 0;
      const detailsState = (detailsById instanceof Map)
        ? `Details: loaded ${formatMB(loadStats.detailsBytes)} (fetch ${Math.round(loadStats.detailsFetchMs)} ms + parse ${Math.round(loadStats.detailsParseMs)} ms).`
        : (detailsLoadError ? `Details: failed (${escapeHtml(detailsLoadError)}).` : "Details: lazy (load on first node/details search).");
      const sourceLabel = payloadMode === "full" ? "full payload" : (payloadMode === "mobile" ? "mobile payload" : "lite payload");
      graphStatusEl.innerHTML = `<p><em>Rendering ${matchedNodes.length.toLocaleString()} papers (${edgesCount.toLocaleString()} citations, ${communities.toLocaleString()} communities). Source: ${sourceLabel}. Base payload: ${formatMB(loadStats.payloadBytes)}. Load: fetch ${Math.round(loadStats.fetchMs)} ms + parse ${Math.round(loadStats.parseMs)} ms. ${detailsState}${heapBytes ? ` Heap: ${formatMB(heapBytes)}.` : ""}</em></p>`;
    }

    visibleNodes = renderNodes.filter(n => nodeIds.has(n.id));
    visibleEdges = rawEdges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    rebuildAdjacency(visibleNodes, visibleEdges);
    journeySelection = journeySelection.filter((id) => nodeById.has(id));
    renderJourneySelection();
    const positionById = buildCommunityPositions(visibleNodes);
    kcoreThresholds = computeKcoreThresholds(visibleNodes);
    const ready = buildSigmaGraph(positionById);
    if (ready) {
      styleSelectedSubgraph(null);
      stabilizeThenSettle(0);
    }

    if (visibleNodes.length) {
      const top = [...visibleNodes].sort((a, b) => (b.importance || 0) - (a.importance || 0))[0];
      focusNode(top.id);
    } else {
      detailsEl.innerHTML = "No papers match the current core/language filter.";
      parentEl.innerHTML = "";
      childEl.innerHTML = "";
      relatedEl.innerHTML = "";
      selectedNodeId = null;
      selectedIncoming = new Set();
      selectedOutgoing = new Set();
      selectedIncident = new Set();
      killRenderer();
      if (graphStatusEl) {
        graphStatusEl.innerHTML = "<p><em>No papers matched current filters.</em></p>";
      }
    }
  }

  function rankedNodes(ids, limit = 10, mode = "importance") {
    return Array.from(ids || [])
      .map(id => nodeById.get(id))
      .filter(Boolean)
      .sort((a, b) => {
        if (mode === "citation_count") {
          return ((b.citation_count || 0) - (a.citation_count || 0))
            || ((b.importance || 0) - (a.importance || 0));
        }
        return (b.importance || 0) - (a.importance || 0);
      })
      .slice(0, limit);
  }

  function parentsOf(id) {
    return rankedNodes(outgoing.get(id), 10, "citation_count");
  }

  function childrenOf(id) {
    return rankedNodes(incoming.get(id), 10, "citation_count");
  }

  function relatedOf(id) {
    const direct = new Set([...(incoming.get(id) || []), ...(outgoing.get(id) || [])]);
    const scoreMap = new Map();
    for (const n of direct) {
      for (const nn of (undirected.get(n) || [])) {
        if (nn === id || direct.has(nn)) continue;
        scoreMap.set(nn, (scoreMap.get(nn) || 0) + 1);
      }
    }
    const ranked = Array.from(scoreMap.entries())
      .map(([nid, overlap]) => ({ node: nodeById.get(nid), overlap }))
      .filter(x => x.node)
      .sort((a, b) => (b.overlap - a.overlap) || ((b.node.importance || 0) - (a.node.importance || 0)))
      .slice(0, 10)
      .map(x => x.node);
    if (ranked.length) return ranked;
    return rankedNodes(direct, 10);
  }

  function renderButtons(targetEl, nodes, emptyText) {
    if (!nodes.length) {
      targetEl.innerHTML = `<p>${emptyText}</p>`;
      return;
    }
    targetEl.innerHTML = nodes
      .map(n => `${renderActionButtons(n)} <span>${escapeHtml((n.title || "Untitled").slice(0, 85))}</span>`)
      .join("");
  }

  function renderRelationshipNavigator(id) {
    renderButtons(parentEl, parentsOf(id), "No parent links in current view.");
    renderButtons(childEl, childrenOf(id), "No child links in current view.");
    renderButtons(relatedEl, relatedOf(id), "No related links in current view.");
  }

  function renderPaper(id) {
    const node = nodeById.get(id);
    if (!node) return;
    if (!node._detailsLoaded && !detailsLoadError) {
      detailsEl.innerHTML = `
        <strong>${escapeHtml(node.title || "Untitled")}</strong><br />
        <div>Loading summary and abstract details...</div>
      `;
      ensureDetailsLoaded().then(() => {
        const latest = nodeById.get(id);
        if (latest) renderPaper(id);
      });
      return;
    }
    const sourceLink = node.source_url ? `<a href="${node.source_url}" target="_blank" rel="noopener">Open source paper</a>` : "No source link";
    const citationPlaintext = citationPlaintextForNode(node);
    const bibtex = citationBibtexForNode(node);
    const bibHref = `data:text/plain;charset=utf-8,${encodeURIComponent(bibtex)}`;
    const bibLink = `<a href="${bibHref}" download="${node.id}.bib">Download .bib</a>`;
    const yearInt = Number.isFinite(Number(node.year)) ? Math.trunc(Number(node.year)) : null;
    const year = yearInt ? ` (${yearInt})` : "";
    const summary = cleanNarrativeText(node.summary || "");
    const topic = node.topic_label ? `<span class="pill">${escapeHtml(node.topic_label)}</span>` : "";
    const difficultyLevel = Number(node.difficulty || 3);
    const difficultyLabel = (
      difficultyLevel <= 2 ? "plain language" :
      difficultyLevel === 3 ? "moderately technical" :
      difficultyLevel === 4 ? "advanced technical" : "specialist technical"
    );
    const diff = `<span class="pill">Language level ${difficultyLevel}/5 (${difficultyLabel})</span>`;
    const inLinks = Number(node.in_degree || 0);
    const outLinks = Number(node.out_degree || 0);
    const visibleIn = (incoming.get(id) || new Set()).size;
    const visibleOut = (outgoing.get(id) || new Set()).size;
    const linkCounts = `<span class="pill">Links in/out (corpus): ${inLinks}/${outLinks}</span><span class="pill">Links in/out (visible): ${visibleIn}/${visibleOut}</span>`;
    const kTierRaw = kcoreTier(node);
    const kTier = (kTierRaw === "high") ? "core" : (kTierRaw === "mid" ? "middle" : "peripheral");
    const kTierPill = `<span class="pill">k-core tier: ${kTier}</span>`;
    const paperRank = paperRankMap.get(node.id);
    const ageRank = paperAgeRankMap.get(node.id);
    const paperRankPill = paperRank ? `<span class="pill">Paper rank (raw): ${paperRank}/${Math.max(1, rawNodes.length)}</span>` : "";
    const paperAgeRankPill = ageRank ? `<span class="pill">Paper rank (age-norm): ${ageRank}/${Math.max(1, rawNodes.length)}</span>` : "";
    const authorName = String(node.first_author || "").trim();
    const authorStats = authorName ? authorStatsMap.get(authorName) : null;
    const authorRankPill = authorStats ? `<span class="pill">Author rank: ${authorStats.rank}/${Math.max(1, authorStatsMap.size)}</span>` : "";
    const evidenceType = String(node.evidence_type || "other").replaceAll("_", " ");
    const evidenceStrength = Number(node.evidence_strength || 2);
    const evidencePill = `<span class="pill">Evidence: ${escapeHtml(evidenceType)} (${evidenceStrength}/5)</span>`;
    const certaintyPct = Math.round(Math.max(0, Math.min(1, Number(node.summary_certainty_score || 0))) * 100);
    const certaintyLabel = escapeHtml(String(node.summary_certainty_label || "unknown"));
    const certaintyPill = `<span class="pill">Summary certainty: ${certaintyLabel} (${certaintyPct}%)</span>`;
    const ageNormScorePill = `<span class="pill">Age-normalized score: ${Number(node.age_normalized_importance || 0).toFixed(3)}</span>`;
    const cpyPill = `<span class="pill">Citations/year: ${Number(node.citations_per_year || 0).toFixed(2)}</span>`;
    const provenance = `<strong>Summary provenance:</strong> source=${escapeHtml(node.summary_source || "unknown")}; method=${escapeHtml(node.distill_method || "unknown")}; generated=${escapeHtml(node.summary_generated_at_utc || "unknown")}; hash=${escapeHtml(String(node.source_text_hash || "").slice(0, 12) || "n/a")}; overlap=${Number(node.faithfulness_overlap || 0).toFixed(2)}`;
    const journeyToggle = `<button data-journey-toggle="${node.id}">${journeyButtonLabel(node.id)} ${journeySelection.includes(node.id) ? "from" : "to"} Journey</button>`;
    const takeaways = Array.isArray(node.key_takeaways) ? node.key_takeaways : [];
    const takeawayHtml = takeaways.length
      ? `<ul>${takeaways.map(t => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`
      : "<p>No key takeaways available.</p>";
    const abstractText = cleanNarrativeText(node.abstract || "");
    detailsEl.innerHTML = `
      <strong>${escapeHtml(node.title || "Untitled")}</strong>${year}<br />
      ${topic}${diff}${kTierPill}${evidencePill}${certaintyPill}${ageNormScorePill}${cpyPill}${linkCounts}${paperRankPill}${paperAgeRankPill}${authorRankPill}<br />
      <div><strong>Lead author:</strong> ${escapeHtml(authorName || "Unknown")}</div><br />
      <div><strong>Abstract</strong><br />${escapeHtml(abstractText || "No abstract available.")}</div><br />
      <div>${escapeHtml(summary || "No summary available.")}</div><br />
      <div>${provenance}</div>
      <div><strong>Key takeaways</strong>${takeawayHtml}</div>
      <div><strong>Paper link:</strong> ${sourceLink}</div>
      <div><strong>Bibliography (plain text):</strong> ${escapeHtml(citationPlaintext)}</div>
      <div>${bibLink}</div>
      <div><em>${escapeHtml(String(node.summary_disclaimer || ""))}</em></div>
      <div class="explorer-actions">${journeyToggle}</div>
    `;
    renderRelationshipNavigator(id);
  }

  function focusNode(id) {
    if (!nodeById.has(id) || !renderer || !sigmaGraph) return;
    styleSelectedSubgraph(id);
    if (sigmaGraph.hasNode(id)) {
      const x = sigmaGraph.getNodeAttribute(id, "x");
      const y = sigmaGraph.getNodeAttribute(id, "y");
      const camera = renderer.getCamera && renderer.getCamera();
      if (camera && Number.isFinite(x) && Number.isFinite(y)) {
        camera.animate({ x, y, ratio: 0.22 }, { duration: 280 });
      }
    }
    renderPaper(id);
  }

  function toggleJourneySelection(id) {
    const idx = journeySelection.indexOf(id);
    if (idx >= 0) {
      journeySelection.splice(idx, 1);
    } else {
      journeySelection.push(id);
    }
    renderJourneySelection();
    if (selectedNodeId === id) {
      renderPaper(id);
    }
    if ((directSearchInputEl.value || "").trim()) {
      runDirectSearch();
    }
    if ((ideaInputEl.value || "").trim()) {
      runIdeaMatch();
    }
  }

  function clearJourneySelection() {
    journeySelection = [];
    renderJourneySelection();
  }

  function renderJourneySelection() {
    if (!journeySelection.length) {
      journeySelectedEl.innerHTML = "<p>No papers selected yet. Use Add buttons from graph results or tools.</p>";
      return;
    }
    journeySelectedEl.innerHTML = `
      <p><strong>Selected papers (${journeySelection.length})</strong></p>
      <ol>
        ${journeySelection.map((id) => {
          const node = nodeById.get(id);
          if (!node) return "";
          return `<li>${renderActionButtons(node)} ${escapeHtml(node.title || "Untitled")}</li>`;
        }).join("")}
      </ol>
    `;
  }

  function neighborOverlapWithSeeds(nodeId, seedSet) {
    const inSet = incoming.get(nodeId) || new Set();
    const outSet = outgoing.get(nodeId) || new Set();
    let overlap = 0;
    for (const n of inSet) if (seedSet.has(n)) overlap += 1;
    for (const n of outSet) if (seedSet.has(n)) overlap += 1;
    return overlap;
  }

  function renderJourneyList(nodes, emptyText) {
    if (!nodes.length) return `<p>${emptyText}</p>`;
    return `<ol>${nodes.map((node) => `<li>${renderActionButtons(node)} ${escapeHtml(node.title || "Untitled")}</li>`).join("")}</ol>`;
  }

  async function generateLearningJourney() {
    const selected = journeySelection.map((id) => nodeById.get(id)).filter(Boolean);
    if (!selected.length) {
      journeyResultsEl.innerHTML = "<p>Select at least one paper to generate a journey.</p>";
      return;
    }
    if (!(detailsById instanceof Map) && !detailsLoadError) {
      journeyResultsEl.innerHTML = "<p>Loading text details for journey generation...</p>";
      await ensureDetailsLoaded();
    }

    const selectedSet = new Set(selected.map((n) => n.id));
    const corpus = visibleNodes.length ? visibleNodes : rawNodes;
    const index = prepareSearchIndex(corpus);
    const queryText = selected.map((n) => `${n.title || ""} ${n.summary || ""} ${n.abstract || ""} ${n.topic_label || ""}`).join(" ");
    const model = buildQueryModel(queryText, index);
    const docsById = new Map(index.docs.map((doc) => [doc.node.id, doc]));

    const candidateIds = new Set();
    selected.forEach((node) => {
      (incoming.get(node.id) || new Set()).forEach((id) => candidateIds.add(id));
      (outgoing.get(node.id) || new Set()).forEach((id) => candidateIds.add(id));
      (undirected.get(node.id) || new Set()).forEach((id) => candidateIds.add(id));
    });

    const candidates = Array.from(candidateIds)
      .filter((id) => !selectedSet.has(id))
      .map((id) => nodeById.get(id))
      .filter(Boolean)
      .map((node) => {
        const doc = docsById.get(node.id);
        const relevance = doc ? scoreIdeaDoc(doc, model, index) : 0;
        const overlap = neighborOverlapWithSeeds(node.id, selectedSet);
        const score = relevance + (overlap * 2.0) + (node.core_score || 0) * 1.4 + Math.log1p(node.citation_count || 0) * 0.2;
        return { node, score, overlap };
      })
      .sort((a, b) => (b.score - a.score) || ((b.node.importance || 0) - (a.node.importance || 0)));

    const foundations = [...selected].sort((a, b) =>
      (Number(a.difficulty || 3) - Number(b.difficulty || 3))
      || ((b.citation_count || 0) - (a.citation_count || 0))
    );
    const bridges = candidates.filter((x) => x.overlap > 0).slice(0, 5).map((x) => x.node);
    const deepDives = candidates.slice(0, 8).map((x) => x.node);

    journeyResultsEl.innerHTML = `
      <p><strong>Generated learning journey</strong></p>
      <h5>1. Foundations (start here)</h5>
      ${renderJourneyList(foundations, "No foundation papers found.")}
      <h5>2. Bridges (connect mechanisms to applications)</h5>
      ${renderJourneyList(bridges, "No bridge papers found from selected set.")}
      <h5>3. Deep Dives (advanced extensions)</h5>
      ${renderJourneyList(deepDives, "No deep-dive recommendations found.")}
    `;
  }

  async function runIdeaMatch() {
    const idea = (ideaInputEl.value || "").trim();
    if (!idea) {
      ideaResultsEl.innerHTML = "<p>Add a brief note first.</p>";
      return;
    }
    if (!(detailsById instanceof Map) && !detailsLoadError) {
      ideaResultsEl.innerHTML = "<p>Loading text details for idea matching...</p>";
      await ensureDetailsLoaded();
    }
    const baseNodes = rawNodes.filter(n => {
      const metric = coreMetricEl.value || "composite";
      const maxDifficulty = Number(difficultyMaxEl.value || 5);
      const minInDegree = Math.max(0, Number(minInDegreeEl.value || 0));
      const minOutDegree = Math.max(0, Number(minOutDegreeEl.value || 0));
      const minKcore = Math.max(0, Number(minKcoreEl.value || 0));
      const cutoff = Number(corePctEl.value || 0) / 100;
      const requireAbstract = !!requireAbstractEl.checked;
      if (requireAbstract && !n.has_abstract) return false;
      if (Number(n.difficulty || 3) > maxDifficulty) return false;
      if (Number(n.in_degree || 0) < minInDegree) return false;
      if (Number(n.out_degree || 0) < minOutDegree) return false;
      if (Number(n.kcore || 0) < minKcore) return false;
      if (metric === "pagerank") return (n.rank_pagerank || 0) >= cutoff;
      if (metric === "kcore") return (n.rank_kcore || 0) >= cutoff;
      if (metric === "in_degree") return (n.rank_in_degree || 0) >= cutoff;
      if (metric === "age_normalized") return (n.rank_age_normalized_importance || 0) >= cutoff;
      return (n.core_score || 0) >= cutoff;
    });
    const index = prepareSearchIndex(baseNodes);
    const model = buildQueryModel(idea, index);
    if (!model.terms.length) {
      ideaResultsEl.innerHTML = "<p>Add more specific terms (for example: EBV, NfL, RRMS, MRI lesions).</p>";
      return;
    }
    let scored = index.docs
      .map(doc => ({ node: doc.node, score: scoreIdeaDoc(doc, model, index) }))
      .filter(x => x.score > 0);
    scored.sort((a, b) => (b.score - a.score) || ((b.node.importance || 0) - (a.node.importance || 0)));

    if (scored.length) {
      const best = scored[0].score;
      const minKeep = Math.max(1.2, best * 0.16);
      scored = scored.filter(x => x.score >= minKeep);
    }
    scored = scored.slice(0, 12);

    if (!scored.length) {
      ideaResultsEl.innerHTML = "<p>No strong matches in this explorer subset. Try adding modality (MRI/OCT), phenotype (RRMS/SPMS), or mechanism terms.</p>";
      return;
    }
    ideaResultsEl.innerHTML = `
      <p><strong>Top matches:</strong></p>
      <p><em>Hybrid ranker: field-weighted BM25 + phrase boosts + graph-prior.</em></p>
      <ol>
        ${scored.map(({ node, score }) => `
          <li>
            ${renderActionButtons(node)}
            ${escapeHtml(node.title)} (relevance ${score.toFixed(2)})
          </li>
        `).join("")}
      </ol>
    `;
  }

  function stabilizeThenSettle(amplitude = 0) {
    if (!renderer || !sigmaGraph) return;
    const positionById = buildCommunityPositions(visibleNodes);
    const jitter = Math.max(0, Number(amplitude) || 0);
    visibleNodes.forEach((node) => {
      if (!sigmaGraph.hasNode(node.id)) return;
      const base = positionById.get(node.id) || { x: 0, y: 0 };
      sigmaGraph.setNodeAttribute(node.id, "x", (Number(base.x) || 0) + (Math.random() - 0.5) * jitter);
      sigmaGraph.setNodeAttribute(node.id, "y", (Number(base.y) || 0) + (Math.random() - 0.5) * jitter);
    });
    renderer.refresh();
  }

  async function loadCorpusPayload(candidates) {
    if (isLoadingCorpus) return;
    isLoadingCorpus = true;
    refreshFullCorpusButton();
    const candidateList = Array.isArray(candidates) ? candidates : [candidates];
    let lastErr = null;
    const candidateErrors = [];
    try {
      for (const candidate of candidateList) {
        const loadStart = performance.now();
        try {
          setGraphStatus(`Loading ${candidate.label || candidate.mode || "payload"} payload...`);
          const r = await fetchTextWithTimeout(candidate.url, 20000);
          if (!r.ok) throw new Error(`${candidate.label || candidate.mode || "payload"} request failed (${r.status})`);
          const text = await r.text();
          const parseStart = performance.now();
          loadStats.fetchMs = parseStart - loadStart;
          loadStats.payloadBytes = Number(r.headers.get("content-length")) || (text.length * 2);
          const payload = JSON.parse(text);
          loadStats.parseMs = performance.now() - parseStart;
          const decoded = decodeGraphPayload(payload);
          payloadMode = candidate.mode;
          detailsUrlActive = candidate.detailsUrl;
          detailsById = null;
          detailsLoadPromise = null;
          detailsLoadError = "";
          loadStats.detailsBytes = 0;
          loadStats.detailsFetchMs = 0;
          loadStats.detailsParseMs = 0;
          rawNodes = (decoded.nodes || []).map((node) => ({ ...normalizeNode(node), _detailsLoaded: false }));
          rawEdges = decoded.edges || [];
          buildRankIndexes(rawNodes);
          visibleNodes = [];
          visibleEdges = [];
          rebuildAdjacency(visibleNodes, visibleEdges);
          corePctValueEl.textContent = `${corePctEl.value}%`;
          applyCoreFilter();
          lastErr = null;
          break;
        } catch (err) {
          lastErr = err;
          candidateErrors.push(`${candidate.label || candidate.mode || "payload"}: ${err}`);
        }
      }
      if (lastErr) {
        const msg = `Could not load explorer data: ${lastErr}`;
        detailsEl.innerHTML = msg;
        setGraphStatus(`Explorer load failed. Attempts: ${candidateErrors.join(" | ")}`, true);
      }
    } finally {
      isLoadingCorpus = false;
      refreshFullCorpusButton();
    }
  }

  setGraphStatus("Loading explorer graph...");
  loadCorpusPayload(initialPayloadCandidates);

  [parentEl, childEl, relatedEl, directSearchResultsEl, ideaResultsEl, journeySelectedEl, journeyResultsEl, detailsEl].forEach(container => {
    container.addEventListener("click", (ev) => {
      const focusBtn = ev.target.closest("button[data-focus]");
      if (focusBtn) {
        focusNode(focusBtn.dataset.focus);
        return;
      }
      const toggleBtn = ev.target.closest("button[data-journey-toggle]");
      if (toggleBtn) {
        toggleJourneySelection(toggleBtn.dataset.journeyToggle);
      }
    });
  });

  directSearchRunEl.addEventListener("click", runDirectSearch);
  directSearchInputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      runDirectSearch();
    }
  });

  journeyGenerateEl.addEventListener("click", generateLearningJourney);
  journeyClearEl.addEventListener("click", clearJourneySelection);

  ideaRunEl.addEventListener("click", runIdeaMatch);
  coreApplyEl.addEventListener("click", applyCoreFilter);
  presetUndergradEl.addEventListener("click", () => setPreset("undergrad"));
  presetBalancedEl.addEventListener("click", () => setPreset("balanced"));
  presetGradEl.addEventListener("click", () => setPreset("grad"));
  ideaInputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      runIdeaMatch();
    }
  });
  corePctEl.addEventListener("input", () => {
    corePctValueEl.textContent = `${corePctEl.value}%`;
  });
  loadFullCorpusEl.addEventListener("click", () => {
    if (isMobileView || payloadMode === "full") return;
    loadCorpusPayload([{ url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" }]);
  });
  relayoutEl.addEventListener("click", () => {
    if (isMobileView) return;
    stabilizeThenSettle(18);
  });
  nodeDragToggleEl.addEventListener("click", () => {
    if (isMobileView) return;
    dragEnabled = !dragEnabled;
    draggingNode = null;
    refreshNodeDragToggleLabel();
  });
  if (isMobileView) {
    relayoutEl.disabled = true;
    relayoutEl.title = "Re-layout disabled on mobile";
  }
  refreshFullCorpusButton();
  refreshNodeDragToggleLabel();
  renderJourneySelection();
})();
</script>
"""
    (site_docs / "explorer.md").write_text(explorer_md, encoding="utf-8")


def generate(config_path: str) -> None:
    root = Path(config_path).resolve().parent
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    topics_dir = root / cfg["output_dir"] / "topics"
    distilled_dir = root / cfg["output_dir"] / "distilled"
    graph_dir = root / cfg["output_dir"] / "graph"
    site_docs = root / "site" / "docs"

    topics_out = site_docs / "topics"
    topics_out.mkdir(parents=True, exist_ok=True)
    for existing in topics_out.glob("*.md"):
        if existing.name != "index.md":
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

    # Generate topics index
    index_lines = ["# Topics\n"]
    index_lines.append('<div class="landing-hero">')
    index_lines.append("<p>Browse the citation-derived topic atlas and jump directly into guided reading paths.</p>")
    index_lines.append('<div class="landing-kpis">')
    index_lines.append(f'<span class="kpi-pill">{len(topic_clusters)} discovered clusters</span>')
    index_lines.append('<span class="kpi-pill">Algorithmic taxonomy</span>')
    index_lines.append('<span class="kpi-pill">Language-level paper filters</span>')
    index_lines.append("</div>")
    index_lines.append("</div>")

    category_groups = {}
    for _, cluster in topic_clusters.iterrows():
        cat = cluster.get("dominant_category", "pathogenesis_and_immunology")
        category_groups.setdefault(cat, []).append(cluster)

    # Categories aligned with ACTRIMS / CMSC / MSJ conference structure
    category_labels = {
        "pathogenesis_and_immunology": "Pathogenesis & Immunology",
        "imaging_and_biomarkers": "Imaging & Biomarkers",
        "clinical_trials_and_therapeutics": "Clinical Trials & Therapeutics",
        "clinical_care_and_management": "Clinical Care & Management",
        "epidemiology_and_population_health": "Epidemiology & Population Health",
    }

    for cat in [
        "pathogenesis_and_immunology",
        "imaging_and_biomarkers",
        "clinical_trials_and_therapeutics",
        "clinical_care_and_management",
        "epidemiology_and_population_health",
    ]:
        clusters = category_groups.get(cat, [])
        if not clusters:
            continue
        index_lines.append(f"\n## {category_labels.get(cat, cat)}\n")
        index_lines.append('<div class="topic-grid">')
        for cluster in clusters:
            if isinstance(cluster, pd.Series):
                cluster = cluster.to_dict()
            tid = cluster["topic_id"]
            label = cluster["auto_label"]
            n = cluster["n_papers"]
            diff = cluster.get("difficulty", 3)
            slug = _topic_slug(label, tid)
            index_lines.append(
                f'<a class="topic-card" href="{slug}/">'
                f"<strong>{html.escape(label)}</strong>"
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

        lines = [f"# {label}\n"]
        lines.append('<div class="topic-hero reveal">')
        lines.append('<div class="landing-kpis">')
        lines.append(f'<span class="kpi-pill">Difficulty {_safe_int(diff, 3)}/5</span>')
        lines.append(f'<span class="kpi-pill">{_safe_int(n)} papers</span>')
        lines.append(f'<span class="kpi-pill">{html.escape(str(cat).replace("_", " ").title())}</span>')
        lines.append("</div>")
        lines.append("</div>\n")

        overview = overview_map.get(tid, {})
        if overview.get("overview"):
            lines.append("## Overview\n")
            lines.append(f'<div class="info-panel reveal"><p>{html.escape(_clean_text(overview["overview"]))}</p></div>')
            lines.append("")

        # Reading path
        if not reading_paths.empty:
            topic_reading = reading_paths[reading_paths["topic_id"] == tid].sort_values("position")
            if not topic_reading.empty:
                lines.append("## Reading Path\n")
                lines.append("Papers ordered by importance and pedagogic progression.\n")
                for _, rp in topic_reading.iterrows():
                    pid = str(rp["canonical_paper_id"])
                    paper_data = metadata_map.get(pid, {}).copy()
                    paper_data.update(summaries_map.get(pid, {}))
                    if not paper_data:
                        paper_data = {"title": rp.get("title", "Untitled")}
                    lines.append(_paper_card(paper_data))

        (topics_out / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")

    _build_explorer_assets(root, cfg, site_docs, paper_summaries, paper_topics, topic_clusters)
    _write_explorer_page(site_docs)

    # Update nav in mkdocs.yml
    mkdocs_path = root / "site" / "mkdocs.yml"
    if mkdocs_path.exists():
        with open(mkdocs_path, "r") as f:
            mkdocs_cfg = yaml.safe_load(f)

        topic_nav = [{"Overview": "topics/index.md"}]
        for _, cluster in topic_clusters.iterrows():
            label = cluster["auto_label"]
            slug = _topic_slug(label, cluster["topic_id"])
            topic_nav.append({label: f"topics/{slug}.md"})

        mkdocs_cfg["nav"] = [
            {"Home": "index.md"},
            {"Getting Started": "getting-started.md"},
            {"Topics": topic_nav},
            {"Explorer": "explorer.md"},
            {"Glossary": "glossary.md"},
        ]
        mkdocs_cfg["use_directory_urls"] = True

        with open(mkdocs_path, "w") as f:
            yaml.dump(mkdocs_cfg, f, default_flow_style=False, sort_keys=False)

    print(f"Generated {len(topic_clusters)} topic pages in {topics_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    generate(args.config)
