"""Distill included papers into structured plain-language summaries using rules or an LLM."""

import argparse
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .utils import ensure_dir, load_config, save_json


READING_LEVELS = ("basic", "advanced")
DEFAULT_READING_LEVEL = "basic"

# Maximum tokens to request from the LLM per distillation call.
LLM_MAX_TOKENS = 1024
# Maximum characters of source text sent to the LLM in the distillation prompt.
PROMPT_SOURCE_TEXT_MAX_CHARS = 3000
# Maximum abstract characters included per paper in topic-overview prompts.
TOPIC_ABSTRACT_PREVIEW_CHARS = 500

READING_LEVEL_GUIDE = {
    "basic": (
        "Write at the BASIC reading level (plain language for an undergraduate "
        "with basic biology background). Use short sentences, minimal jargon, "
        "and define any specialist term the first time it appears. Favor "
        "concrete, everyday wording over clinical terminology."
    ),
    "advanced": (
        "Write at the ADVANCED reading level (graduate student or practicing "
        "MS researcher/clinician). Use precise biomedical terminology, "
        "acronyms, and mechanism-level detail. Assume familiarity with common "
        "MS concepts (DMTs, EAE, NfL, OCBs, MRI metrics); do not gloss them."
    ),
}

# Numeric compatibility mapping for downstream code that still expects a 1-5
# "language_difficulty" integer. Basic ≈ level 2 (undergrad), advanced ≈ 4.
READING_LEVEL_NUMERIC = {"basic": 2, "advanced": 4}


def _normalize_reading_level(value, default: str = DEFAULT_READING_LEVEL) -> str:
    if value is None:
        return default
    try:
        text = str(value).strip().lower()
    except Exception:
        return default
    if not text:
        return default
    if text in READING_LEVELS:
        return text
    # Back-compat: accept 1-5 integers.
    try:
        n = int(float(text))
    except (TypeError, ValueError):
        return default
    return "basic" if n <= 3 else "advanced"


def _reading_level_guide(level: str) -> str:
    return READING_LEVEL_GUIDE[_normalize_reading_level(level)]


def _reading_level_numeric(level: str) -> int:
    return READING_LEVEL_NUMERIC[_normalize_reading_level(level)]


DISTILL_PROMPT = """You are helping readers understand a scientific paper about multiple sclerosis.

{reading_level_guide}

Paper title: {title}
Year: {year}
Venue: {venue}
Topic cluster: {topic_label}
Source text: {abstract}

Please provide:
1. A 2-3 sentence summary written at the reading level described above.
2. Three to four short key takeaways at the same reading level. Each takeaway should be a plain sentence — do NOT prefix with any label like Opportunity, Challenge, Action, or Resolution.
3. A one-sentence "why this matters" statement connecting this paper to the broader understanding of MS, at the same reading level.
4. A list of up to 5 technical terms from the abstract that a reader at this level might not know, each with a brief definition. Return an empty list if none would help the target reader.

Respond in JSON format:
{{
  "summary": "...",
  "key_takeaways": [
    "First takeaway sentence.",
    "Second takeaway sentence.",
    "Third takeaway sentence."
  ],
  "why_it_matters": "...",
  "jargon": [{{"term": "...", "definition": "..."}}, ...]
}}"""

TOPIC_OVERVIEW_PROMPT = """You are creating an overview of a research topic cluster for undergraduate researchers studying multiple sclerosis.

Topic: {topic_label}
Dominant category: {dominant_category}
Number of papers: {n_papers}

Here are the titles and abstracts of the top papers in this cluster:

{paper_summaries}

Write a 2-3 paragraph overview of this topic cluster suitable for undergraduate students. Explain:
1. What this area of MS research is about
2. Why it matters for understanding or treating MS
3. What the key findings and open questions are

Keep the language accessible. Avoid jargon or define it when used."""


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _parse_json_list(value: object) -> list[str]:
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
    out = []
    for item in raw:
        text = _clean_text(item)
        if text:
            out.append(text)
    return out


LANGUAGE_COMPLEXITY_TERMS = {
    "cytokine", "chemokine", "oligodendrocyte", "astrocyte", "microglia",
    "immunopathology", "neuropathology", "transcriptome", "proteome",
    "pharmacokinetics", "pharmacodynamics", "hazard ratio", "multivariate",
    "gadolinium", "neurofilament", "oligoclonal", "encephalomyelitis",
    "demyelination", "remyelination", "bayesian", "meta-analysis",
}

OVERLAP_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "were", "was", "are", "is", "be",
    "have", "has", "had", "its", "their", "there", "these", "those", "we", "our", "they", "you",
    "can", "could", "should", "would", "may", "might", "than", "then", "about", "through", "using",
    "study", "paper", "results", "methods", "background", "conclusion", "conclusions", "multiple",
    "sclerosis",
}


def _split_sentences(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    chunks = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for chunk in chunks:
        chunk = _clean_text(chunk).strip().strip('"')
        if chunk:
            out.append(chunk)
    return out


def _structured_takeaways(candidates: list[str], summary: str, abstract: str) -> list[str]:
    cleaned = []
    for value in candidates:
        text = _clean_text(value)
        if not text:
            continue
        text = re.sub(r"^(opportunity|challenge|action|resolution)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
        if text and text.lower() != "nan":
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


def _strip_takeaway_label(text: str) -> str:
    return re.sub(
        r"^(opportunity|challenge|action|resolution)\s*:\s*",
        "",
        _clean_text(text),
        flags=re.IGNORECASE,
    ).strip()


def _estimate_language_difficulty(summary: str, takeaways: list[str] | None = None) -> int:
    parts = [_clean_text(summary)]
    for value in (takeaways or []):
        plain = _strip_takeaway_label(value)
        if plain:
            parts.append(plain)
    text = " ".join(parts).strip().lower()
    if not text:
        return 3

    words = re.findall(r"[a-z]+", text)
    if not words:
        return 3
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    avg_sentence_len = len(words) / max(1, len(sentences))
    long_ratio = sum(1 for w in words if len(w) >= 10) / len(words)
    complexity_hits = sum(1 for term in LANGUAGE_COMPLEXITY_TERMS if term in text)

    score = 1
    if avg_sentence_len >= 14:
        score += 1
    if avg_sentence_len >= 20:
        score += 1
    if long_ratio >= 0.16:
        score += 1
    if long_ratio >= 0.24:
        score += 1
    if complexity_hits >= 3:
        score += 1
    if complexity_hits >= 6:
        score += 1
    return min(max(score, 1), 5)


def _tokenize_for_overlap(text: str) -> set[str]:
    text = _clean_text(text).lower()
    tokens = re.findall(r"[a-z]{3,}", text)
    return {tok for tok in tokens if tok not in OVERLAP_STOPWORDS}


def _faithfulness_overlap(summary: str, takeaways: list[str], source_text: str) -> float:
    summary_tokens = _tokenize_for_overlap(
        f"{_clean_text(summary)} {' '.join(_strip_takeaway_label(t) for t in (takeaways or []))}"
    )
    source_tokens = _tokenize_for_overlap(source_text)
    if not summary_tokens or not source_tokens:
        return 0.0
    overlap = len(summary_tokens & source_tokens) / max(1, len(summary_tokens))
    return float(min(max(overlap, 0.0), 1.0))


def _certainty_from_signals(
    source_type: str,
    source_chars: int,
    method: str,
    overlap: float,
) -> tuple[float, str]:
    base = 0.55
    s_type = _clean_text(source_type).lower()
    m = _clean_text(method).lower()
    if "fulltext" in s_type or s_type.startswith("row_"):
        base += 0.2
    elif s_type == "abstract":
        base += 0.1
    elif s_type == "none":
        base -= 0.15

    if int(source_chars) >= 2000:
        base += 0.08
    elif int(source_chars) >= 800:
        base += 0.04
    elif int(source_chars) < 250:
        base -= 0.08

    if m == "rules_based":
        base -= 0.08

    base += (float(overlap) - 0.35) * 0.35
    score = float(min(max(base, 0.05), 0.98))
    if score >= 0.82:
        label = "high"
    elif score >= 0.62:
        label = "medium"
    else:
        label = "low"
    return score, label


def _disclaimer_for_source(source_type: str, certainty_label: str) -> str:
    s_type = _clean_text(source_type).lower()
    if "fulltext" in s_type or s_type.startswith("row_"):
        source_clause = "This summary is generated from available full text"
    elif s_type == "abstract":
        source_clause = "This summary is generated from abstract-level text"
    else:
        source_clause = "This summary is generated from limited source text"
    return (
        f"{source_clause} and may omit study details; certainty is {certainty_label}. "
        "Verify critical claims against the original paper before reuse."
    )


def _serialize_json_cell(value: object) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value) if value is not None else ""


def _generate_faithfulness_qa_outputs(
    summaries_df: pd.DataFrame,
    outdir: Path,
    sample_size: int,
    random_seed: int = 13,
) -> None:
    if summaries_df.empty:
        pd.DataFrame().to_csv(outdir / "faithfulness_qa_sample.csv", index=False)
        save_json(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "n_summaries": 0,
                "n_sampled": 0,
                "automated_pass_rate_pct": 0.0,
            },
            outdir / "faithfulness_qa_report.json",
        )
        return

    qa = summaries_df.copy()
    for col in ["summary", "why_it_matters", "summary_source"]:
        if col in qa.columns:
            qa[col] = qa[col].apply(_clean_text)
    for col in ["key_takeaways", "jargon"]:
        if col in qa.columns:
            qa[col] = qa[col].apply(_parse_json_list if col == "key_takeaways" else _parse_json_list)
    qa["takeaway_count"] = qa["key_takeaways"].apply(lambda x: len(x) if isinstance(x, list) else 0)
    qa["summary_has_nan"] = qa["summary"].str.contains(r"\bnan\b", case=False, na=False)
    qa["overlap"] = pd.to_numeric(qa.get("faithfulness_overlap", 0.0), errors="coerce").fillna(0.0)
    qa["certainty"] = pd.to_numeric(qa.get("summary_certainty_score", 0.0), errors="coerce").fillna(0.0)
    qa["source_chars"] = pd.to_numeric(qa.get("source_text_chars", 0), errors="coerce").fillna(0).astype(int)
    qa["summary_non_empty"] = qa["summary"].str.len().fillna(0) >= 40
    qa["takeaways_ok"] = qa["takeaway_count"] == 4
    qa["source_ok"] = qa["source_chars"] >= 200
    qa["overlap_ok"] = qa["overlap"] >= 0.10
    qa["certainty_ok"] = qa["certainty"] >= 0.45
    qa["automated_pass"] = (
        qa["summary_non_empty"]
        & (~qa["summary_has_nan"])
        & qa["takeaways_ok"]
        & qa["source_ok"]
        & qa["overlap_ok"]
        & qa["certainty_ok"]
    )
    qa["automated_flags"] = qa.apply(
        lambda r: ";".join(
            [
                flag
                for flag, ok in [
                    ("summary_too_short", bool(r["summary_non_empty"])),
                    ("summary_contains_nan", not bool(r["summary_has_nan"])),
                    ("takeaways_not_4", bool(r["takeaways_ok"])),
                    ("source_text_too_short", bool(r["source_ok"])),
                    ("low_source_overlap", bool(r["overlap_ok"])),
                    ("low_certainty", bool(r["certainty_ok"])),
                ]
                if not ok
            ]
        )
        or "none",
        axis=1,
    )

    rnd = random.Random(int(random_seed))
    sample_size = max(1, int(sample_size))
    idx = list(qa.index)
    rnd.shuffle(idx)
    sampled = qa.loc[idx[: min(sample_size, len(idx))]].copy()
    sampled["reviewer_status"] = ""
    sampled["reviewer_notes"] = ""

    keep_cols = [
        "canonical_paper_id",
        "title",
        "year",
        "doi",
        "summary_source",
        "source_text_hash",
        "source_text_chars",
        "summary_generated_at_utc",
        "distill_method",
        "summary_certainty_score",
        "summary_certainty_label",
        "faithfulness_overlap",
        "automated_pass",
        "automated_flags",
        "summary",
        "key_takeaways",
        "why_it_matters",
        "summary_disclaimer",
        "reviewer_status",
        "reviewer_notes",
    ]
    for col in keep_cols:
        if col not in sampled.columns:
            sampled[col] = ""
    sampled = sampled[keep_cols]
    sampled["key_takeaways"] = sampled["key_takeaways"].apply(_serialize_json_cell)
    sampled.to_csv(outdir / "faithfulness_qa_sample.csv", index=False)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_summaries": int(len(qa)),
        "n_sampled": int(len(sampled)),
        "automated_pass_rate_pct": round(float(qa["automated_pass"].mean() * 100.0), 2),
        "automated_fail_count": int((~qa["automated_pass"]).sum()),
        "sample_path": str(outdir / "faithfulness_qa_sample.csv"),
    }
    save_json(report, outdir / "faithfulness_qa_report.json")


def _load_fulltext_maps(root: Path, output_dir: str) -> tuple[dict[str, str], dict[str, str]]:
    fulltext_dir = root / output_dir / "fulltext"
    if not fulltext_dir.exists():
        return {}, {}

    text_cols = ["full_text", "fulltext", "text", "content", "body_text"]
    id_cols = ["canonical_paper_id", "paper_id", "id"]
    source_cols = ["source", "text_source", "provider"]

    text_by_id: dict[str, str] = {}
    source_by_id: dict[str, str] = {}

    for path in sorted(list(fulltext_dir.glob("*.csv")) + list(fulltext_dir.glob("*.parquet"))):
        try:
            if path.suffix.lower() == ".csv":
                df = pd.read_csv(path)
            else:
                df = pd.read_parquet(path)
        except Exception:
            continue
        if df.empty:
            continue

        id_col = next((c for c in id_cols if c in df.columns), None)
        text_col = next((c for c in text_cols if c in df.columns), None)
        source_col = next((c for c in source_cols if c in df.columns), None)
        if not id_col or not text_col:
            continue

        for _, row in df.iterrows():
            pid = _clean_text(row.get(id_col))
            text = _clean_text(row.get(text_col))
            if not pid or not text:
                continue
            # Keep the longest text we see for the same paper id.
            if len(text) > len(text_by_id.get(pid, "")):
                text_by_id[pid] = text
                source_by_id[pid] = _clean_text(row.get(source_col)) if source_col else path.name

    return text_by_id, source_by_id


def _context_from_row(
    row: dict,
    fulltext_by_id: dict[str, str],
    fulltext_source_by_id: dict[str, str],
) -> tuple[str, str]:
    pid = _clean_text(row.get("canonical_paper_id"))

    row_fulltext = ""
    for key in ["full_text", "fulltext", "body_text", "content"]:
        row_fulltext = _clean_text(row.get(key))
        if row_fulltext:
            return row_fulltext, f"row_{key}"

    if pid and pid in fulltext_by_id and _clean_text(fulltext_by_id[pid]):
        source = _clean_text(fulltext_source_by_id.get(pid)) or "fulltext_file"
        return fulltext_by_id[pid], source

    abstract = _clean_text(row.get("abstract"))
    if abstract:
        return abstract, "abstract"

    return "", "none"


def _cache_path(cache_dir: Path, paper_id: str, level: str) -> Path:
    return cache_dir / f"{paper_id}__{_normalize_reading_level(level)}.json"


def _load_cache(cache_dir: Path, paper_id: str, level: str) -> dict | None:
    primary = _cache_path(cache_dir, paper_id, level)
    if primary.exists():
        try:
            return json.loads(primary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    # Back-compat: accept the pre-level cache filename for the default level
    # so prior runs are not discarded on upgrade.
    if _normalize_reading_level(level) == DEFAULT_READING_LEVEL:
        legacy = cache_dir / f"{paper_id}.json"
        if legacy.exists():
            try:
                return json.loads(legacy.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _save_cache(cache_dir: Path, paper_id: str, level: str, data: dict) -> None:
    ensure_dir(cache_dir)
    path = _cache_path(cache_dir, paper_id, level)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _distill_with_api(client, model: str, prompt: str) -> dict | None:
    try:
        message = client.messages.create(
            model=model,
            max_tokens=LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return None
    except Exception as e:
        print(f"  API error: {e}")
        return None


_RESULT_INDICATORS = [
    "we found", "we show", "results demonstrate", "our findings",
    "we demonstrate", "we report", "we identified", "our results",
    "these data", "this study", "we observed",
]

_WHY_PREFIX_RE = re.compile(
    r"^(this paper investigates|this study (shows|finds|reports)|we (found|show|report) that)\s+",
    flags=re.IGNORECASE,
)


def _extract_key_sentence_and_takeaways(sentences: list[str]) -> tuple[str, list[str]]:
    """Return the most result-bearing sentence and up to 3 result takeaways from abstract sentences."""
    key_sentence = sentences[-1] if sentences else ""
    for s in sentences:
        if any(ind in s.lower() for ind in _RESULT_INDICATORS):
            key_sentence = s
            break
    takeaways: list[str] = []
    for s in sentences:
        if any(ind in s.lower() for ind in _RESULT_INDICATORS):
            takeaways.append(s)
        if len(takeaways) >= 3:
            break
    if not takeaways and sentences:
        takeaways = sentences[:4]
    return key_sentence, takeaways


def _build_why_it_matters(takeaways: list[str], key_sentence: str, title: str, row: dict) -> str:
    """Compose the 'why it matters for MS' sentence from available signals."""
    if takeaways:
        why_seed = str(takeaways[0]).strip().rstrip(".")
    elif key_sentence:
        why_seed = str(key_sentence).strip().rstrip(".")
    else:
        why_seed = title.lower().rstrip(".")
    why_seed = _WHY_PREFIX_RE.sub("", why_seed)
    if why_seed:
        if why_seed[0].isupper():
            why_seed = why_seed[0].lower() + why_seed[1:]
        return f"This matters for MS because {why_seed}."
    year = _coerce_int(row.get("year"), default=None)
    venue_txt = str(row.get("venue", "") or "").strip()
    year_txt = str(year) if year is not None else ""
    context = " ".join(x for x in [year_txt, venue_txt] if x).strip()
    return f"This matters for MS because it adds evidence about disease mechanisms and care{f' ({context})' if context else ''}."


def _rules_based_distill(row: dict, source_text: str = "", reading_level: str = DEFAULT_READING_LEVEL) -> dict:
    """Build a structured distillation result using heuristic sentence extraction (no LLM)."""
    abstract = _clean_text(source_text) or _clean_text(row.get("abstract", ""))
    title = str(row.get("title", "") or "")
    sentences = [s.strip() for s in abstract.replace(". ", ".\n").split("\n") if s.strip()]
    key_sentence, takeaways = _extract_key_sentence_and_takeaways(sentences)
    summary = f"This paper investigates {title.lower().rstrip('.')}. {key_sentence}"
    why = _build_why_it_matters(takeaways, key_sentence, title, row)
    structured_takeaways = _structured_takeaways(takeaways, summary=summary, abstract=abstract)
    # Rules-based distillation can't actually rewrite at a target reading
    # level; it extracts sentences verbatim from the source. Stamp the
    # configured target so downstream consumers know which slot this result
    # fills, and keep the text-level estimate for transparency.
    target_level = _normalize_reading_level(reading_level)
    numeric_level = _reading_level_numeric(target_level)
    estimated_level = _estimate_language_difficulty(summary, structured_takeaways)
    return {
        "summary": summary,
        "key_takeaways": structured_takeaways,
        "why_it_matters": why,
        "difficulty": numeric_level,
        "language_difficulty": numeric_level,
        "reading_level_target": target_level,
        "reading_level_estimated": estimated_level,
        "jargon": [],
    }


def _coerce_int(value, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


_GENERIC_WHY_RE = re.compile(
    r"^this\s+\d{4}(?:\.0)?\s+paper\s+in\s+.+?contributes\s+to\s+our\s+understanding\s+of\s+multiple\s+sclerosis\.?$",
    flags=re.IGNORECASE,
)


def _repair_why_it_matters(why: str, key_takeaways: list[str], summary: str) -> str:
    """Replace generic or empty 'why it matters' text with a more informative fallback."""
    generic = (
        "contributes to our understanding of multiple sclerosis" in why.lower()
        or bool(_GENERIC_WHY_RE.match(why))
    )
    if why and not generic:
        return why
    fallback = key_takeaways[0] if key_takeaways else summary
    fallback = _WHY_PREFIX_RE.sub("", str(fallback).strip().rstrip("."))
    if fallback:
        if fallback[0].isupper():
            fallback = fallback[0].lower() + fallback[1:]
        return f"This matters for MS because {fallback}."
    return "This matters for MS because it adds actionable evidence for understanding or managing the disease."


def _clean_jargon_list(raw: list) -> list[dict]:
    """Return a cleaned list of {term, definition} dicts, dropping blank or NaN terms."""
    clean: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            term = str(item.get("term", "")).strip()
            definition = str(item.get("definition", "")).strip()
            if term and term.lower() != "nan":
                clean.append({"term": term, "definition": definition})
    return clean


def _resolve_reading_level(result: dict, reading_level: str | None) -> str:
    """Determine the authoritative target reading level for a sanitised result."""
    if reading_level is not None:
        return _normalize_reading_level(reading_level)
    return _normalize_reading_level(result.get("reading_level_target"), default=DEFAULT_READING_LEVEL)


def _sanitize_distill_result(result: dict | None, reading_level: str | None = None) -> dict:
    """Sanitise and normalise a raw distillation result dict, filling in missing fields."""
    result = result or {}

    raw_takeaways = result.get("key_takeaways", [])
    if not isinstance(raw_takeaways, list):
        raw_takeaways = []
    key_takeaways = _structured_takeaways(
        [str(x).strip() for x in raw_takeaways if str(x).strip() and str(x).lower() != "nan"],
        summary=_clean_text(result.get("summary", "")),
        abstract=_clean_text(result.get("abstract", "")),
    )
    clean_jargon = _clean_jargon_list(result.get("jargon", []) if isinstance(result.get("jargon", []), list) else [])

    summary = re.sub(r"\s{2,}", " ", re.sub(r"\bnan\b", "", _clean_text(result.get("summary", "")), flags=re.IGNORECASE)).strip()
    why = re.sub(r"\s{2,}", " ", re.sub(r"\bnan\b", "", _clean_text(result.get("why_it_matters", "")), flags=re.IGNORECASE)).strip()
    why = _repair_why_it_matters(why, key_takeaways, summary)

    # Drop low-information boilerplate summaries.
    if re.match(r"^this paper investigates .+\.$", summary, flags=re.IGNORECASE) and len(summary.split()) <= 8:
        summary = ""

    key_takeaways = _structured_takeaways(key_takeaways, summary=summary, abstract=_clean_text(result.get("abstract", "")))
    estimated_level = _estimate_language_difficulty(summary, key_takeaways)
    target_level = _resolve_reading_level(result, reading_level)
    language_difficulty = _reading_level_numeric(target_level)

    return {
        "summary": summary,
        "key_takeaways": key_takeaways,
        "why_it_matters": why,
        "difficulty": language_difficulty,
        "language_difficulty": language_difficulty,
        "reading_level_target": target_level,
        "reading_level_estimated": int(estimated_level),
        "jargon": clean_jargon,
        "summary_source": _clean_text(result.get("summary_source", "")),
        "source_text_hash": _clean_text(result.get("source_text_hash", "")),
        "source_text_chars": _coerce_int(result.get("source_text_chars"), default=0) or 0,
        "summary_generated_at_utc": _clean_text(result.get("summary_generated_at_utc", "")) or datetime.now(timezone.utc).isoformat(),
        "distill_method": _clean_text(result.get("distill_method", "")) or "rules_based",
        "summary_certainty_score": float(min(max(_safe_float(result.get("summary_certainty_score"), 0.0), 0.0), 1.0)),
        "summary_certainty_label": _clean_text(result.get("summary_certainty_label", "")),
        "summary_disclaimer": _clean_text(result.get("summary_disclaimer", "")),
        "faithfulness_overlap": _safe_float(result.get("faithfulness_overlap", 0.0), 0.0),
    }


class _GeminiClientShim:
    """Calls the Gemini REST API directly (no SDK) to expose the same
    ``client.messages.create(model, max_tokens, messages)`` interface used by
    the Anthropic SDK, so the rest of the distillation pipeline is unchanged."""

    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str) -> None:
        import requests as _requests  # noqa: F401 — confirm requests is available
        self._api_key = api_key

    class _MessagesNamespace:
        def __init__(self, api_key: str, base_url: str) -> None:
            self._api_key = api_key
            self._base_url = base_url

        def create(self, model: str, max_tokens: int, messages: list) -> object:
            import requests

            prompt = ""
            for msg in messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    prompt = content if isinstance(content, str) else str(content)
                    break

            url = f"{self._base_url}/{model}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
            }
            resp = requests.post(
                url,
                params={"key": self._api_key},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )

            class _Content:
                def __init__(self, t: str) -> None:
                    self.text = t
            class _Msg:
                def __init__(self, t: str) -> None:
                    self.content = [_Content(t)]
            return _Msg(text)

    @property
    def messages(self):
        return self._MessagesNamespace(self._api_key, self._BASE_URL)


def _init_api_client(dist_cfg: dict) -> object | None:
    """Return an initialised API client for distillation, or None (rules-based fallback).

    Priority:
      1. provider=anthropic  — uses ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN
      2. provider=gemini     — uses GEMINI_API_KEY or GOOGLE_API_KEY
      3. provider unset/other — try Anthropic, then Gemini, then fall back
    """
    provider = (dist_cfg.get("provider") or "").lower()

    # --- Anthropic ---
    if provider in ("anthropic", ""):
        try:
            import anthropic
            if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
                print("Using Claude API for paper distillation.")
                return anthropic.Anthropic()
        except Exception as exc:
            print(f"Could not initialize Anthropic client ({exc}).")
        if provider == "anthropic":
            print("Anthropic credentials not found. Falling back to rules-based distillation.")
            return None

    # --- Gemini ---
    if provider in ("gemini", ""):
        gemini_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GOOGLE_GEMINI_API_KEY")
        )
        if gemini_key:
            try:
                client = _GeminiClientShim(gemini_key)
                print("Using Gemini API for paper distillation.")
                return client
            except Exception as exc:
                print(f"Could not initialize Gemini client ({exc}).")
        if provider == "gemini":
            print("Gemini credentials not found. Falling back to rules-based distillation.")
            return None

    print("No LLM credentials found. Falling back to rules-based distillation.")
    return None


def _load_distill_corpus(
    graph_dir: Path, max_papers: int, fulltext_by_id: dict
) -> pd.DataFrame:
    """Load scored papers, filter to those with usable text, and return the top max_papers by importance."""
    scored = pd.read_csv(graph_dir / "scored_papers.csv")
    scored = scored[scored["tier"].isin(["included", "seed_neighbor"])].copy()
    scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
    has_abstract = ~(scored["abstract"].isna() | scored["abstract"].astype(str).str.strip().str.lower().isin(["", "nan"]))
    has_fulltext = scored["canonical_paper_id"].isin(set(fulltext_by_id))
    scored = scored[has_abstract | has_fulltext].copy()
    return scored.sort_values("paper_importance_score", ascending=False).head(max_papers)


def _load_topic_lookups(topics_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """Load topic clusters and paper-topic mappings; return DataFrames and lookup dicts."""
    topic_clusters = pd.read_csv(topics_dir / "topic_clusters.csv") if (topics_dir / "topic_clusters.csv").exists() else pd.DataFrame()
    paper_topics = pd.read_csv(topics_dir / "paper_topics.csv") if (topics_dir / "paper_topics.csv").exists() else pd.DataFrame()
    topic_labels = dict(zip(topic_clusters["topic_id"], topic_clusters["auto_label"])) if not topic_clusters.empty else {}
    paper_topic_map = dict(zip(paper_topics["canonical_paper_id"], paper_topics["topic_id"])) if not paper_topics.empty else {}
    return topic_clusters, paper_topics, topic_labels, paper_topic_map


def _configure_reading_levels(dist_cfg: dict) -> tuple[str, list[str]]:
    """Return (default_level, active_levels) from distillation config."""
    default_level = _normalize_reading_level(dist_cfg.get("default_reading_level", DEFAULT_READING_LEVEL))
    configured = dist_cfg.get("reading_levels") or list(READING_LEVELS)
    if isinstance(configured, str):
        configured = [configured]
    active_levels: list[str] = []
    for lvl in configured:
        n = _normalize_reading_level(lvl)
        if n not in active_levels:
            active_levels.append(n)
    if not active_levels:
        active_levels = list(READING_LEVELS)
    if default_level not in active_levels:
        default_level = active_levels[0]
    return default_level, active_levels


def _write_summaries_csv(
    summary_rows: list[dict], active_levels: list[str], outdir: Path,
    qa_sample_size: int, qa_random_seed: int,
) -> None:
    """Serialize summary rows to CSV, encoding list columns as JSON strings."""
    summaries_df = pd.DataFrame(summary_rows)
    _generate_faithfulness_qa_outputs(summaries_df=summaries_df, outdir=outdir, sample_size=qa_sample_size, random_seed=qa_random_seed)
    list_cols = ["key_takeaways", "jargon"] + [f"key_takeaways_{lvl}" for lvl in active_levels] + [f"jargon_{lvl}" for lvl in active_levels]
    for col in list_cols:
        if col in summaries_df.columns:
            summaries_df[col] = summaries_df[col].apply(lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x)
    summaries_df.to_csv(outdir / "paper_summaries.csv", index=False)


def _generate_topic_overviews(
    topic_clusters: pd.DataFrame,
    scored: pd.DataFrame,
    paper_topics: pd.DataFrame,
    api_client: object | None,
    model: str,
    outdir: Path,
) -> None:
    """Generate a plain-language overview for each topic cluster and write topic_overviews.csv."""
    if topic_clusters.empty:
        return
    overview_rows = []
    for _, cluster in topic_clusters.iterrows():
        tid = cluster["topic_id"]
        cluster_papers = scored[scored["canonical_paper_id"].isin(
            paper_topics[paper_topics["topic_id"] == tid]["canonical_paper_id"]
        )].head(5)
        if api_client and not cluster_papers.empty:
            paper_summaries_text = "".join(
                f"Title: {p.get('title', '')}\nAbstract: {str(p.get('abstract', '') or '')[:TOPIC_ABSTRACT_PREVIEW_CHARS]}\n\n"
                for _, p in cluster_papers.iterrows()
            )
            prompt = TOPIC_OVERVIEW_PROMPT.format(
                topic_label=cluster["auto_label"],
                dominant_category=cluster.get("dominant_category", ""),
                n_papers=cluster["n_papers"],
                paper_summaries=paper_summaries_text,
            )
            try:
                resp = api_client.messages.create(model=model, max_tokens=LLM_MAX_TOKENS, messages=[{"role": "user", "content": prompt}])
                overview_text = resp.content[0].text
            except Exception:
                overview_text = f"This topic cluster covers {cluster['auto_label']} and contains {cluster['n_papers']} papers."
        else:
            overview_text = f"This topic cluster covers {cluster['auto_label']} and contains {cluster['n_papers']} papers."
        overview_rows.append({
            "topic_id": tid, "auto_label": cluster["auto_label"], "overview": overview_text,
            "n_papers": cluster["n_papers"], "difficulty": cluster.get("difficulty", 3),
            "dominant_category": cluster.get("dominant_category", ""),
        })
    pd.DataFrame(overview_rows).to_csv(outdir / "topic_overviews.csv", index=False)


def _generate_reading_paths(paper_topics: pd.DataFrame, scored: pd.DataFrame, outdir: Path) -> None:
    """Build ordered reading paths per topic and write reading_paths.csv."""
    if paper_topics.empty:
        return
    reading_rows = []
    for tid in paper_topics["topic_id"].unique():
        topic_paper_ids = set(paper_topics[paper_topics["topic_id"] == tid]["canonical_paper_id"])
        topic_papers = scored[scored["canonical_paper_id"].isin(topic_paper_ids)].copy()
        topic_papers = topic_papers.sort_values("paper_importance_score", ascending=False)
        for pos, (_, p) in enumerate(topic_papers.iterrows()):
            reading_rows.append({
                "topic_id": int(tid), "position": pos + 1,
                "canonical_paper_id": p["canonical_paper_id"],
                "title": p.get("title", ""), "paper_importance_score": p.get("paper_importance_score", 0.0),
            })
    if reading_rows:
        pd.DataFrame(reading_rows).to_csv(outdir / "reading_paths.csv", index=False)


def run(config_path: str) -> None:
    """Distill included papers into plain-language summaries and write paper_summaries.csv."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph_dir = root / cfg["output_dir"] / "graph"
    topics_dir = root / cfg["output_dir"] / "topics"
    outdir = root / cfg["output_dir"] / "distilled"
    ensure_dir(outdir)

    dist_cfg = cfg.get("distillation", {})
    cache_dir = root / dist_cfg.get("cache_dir", "outputs/distilled/llm_cache")
    ensure_dir(cache_dir)
    model = dist_cfg.get("model", "claude-haiku-4-5-20251001")
    batch_size = dist_cfg.get("batch_size", 10)
    qa_sample_size = max(1, int(dist_cfg.get("qa_sample_size", 25)))
    qa_random_seed = int(dist_cfg.get("qa_random_seed", 13))

    fulltext_by_id, fulltext_source_by_id = _load_fulltext_maps(root, cfg["output_dir"])
    scored = _load_distill_corpus(graph_dir, dist_cfg.get("max_papers_per_run", 500), fulltext_by_id)
    topic_clusters, paper_topics, topic_labels, paper_topic_map = _load_topic_lookups(topics_dir)
    api_client = _init_api_client(dist_cfg)
    default_level, active_levels = _configure_reading_levels(dist_cfg)

    def _distill_one_level(
        paper_row: dict,
        paper_id: str,
        topic_label: str,
        source_text: str,
        source_type: str,
        source_hash: str,
        generated_at_utc: str,
        level: str,
    ) -> dict:
        """Return a sanitized distill result for one paper at one reading level.

        Uses a per-level cache keyed by source_hash + level, so the cache is
        invalidated only when the source text or the target level changes.
        """
        cached = _load_cache(cache_dir, paper_id, level)
        if cached and cached.get("source_text_hash") == source_hash and _normalize_reading_level(
            cached.get("reading_level_target"), default=level
        ) == level:
            cached = _sanitize_distill_result(cached, reading_level=level)
            cached["distill_method"] = _clean_text(cached.get("distill_method", "")) or "cache"
            overlap = _faithfulness_overlap(
                _clean_text(cached.get("summary", "")),
                _parse_json_list(cached.get("key_takeaways", [])),
                source_text,
            )
            certainty_score, certainty_label = _certainty_from_signals(
                source_type=source_type,
                source_chars=len(source_text),
                method=str(cached.get("distill_method", "cache")),
                overlap=overlap,
            )
            cached["summary_source"] = source_type
            cached["source_text_hash"] = source_hash
            cached["source_text_chars"] = len(source_text)
            cached["summary_generated_at_utc"] = _clean_text(cached.get("summary_generated_at_utc", "")) or generated_at_utc
            cached["faithfulness_overlap"] = overlap
            cached["summary_certainty_score"] = certainty_score
            cached["summary_certainty_label"] = certainty_label
            cached["summary_disclaimer"] = _disclaimer_for_source(source_type, certainty_label)
            return cached

        distill_method = "rules_based"
        if api_client:
            prompt = DISTILL_PROMPT.format(
                reading_level_guide=_reading_level_guide(level),
                title=paper_row.get("title", ""),
                year=paper_row.get("year", ""),
                venue=paper_row.get("venue", ""),
                topic_label=topic_label,
                abstract=f"[{source_type}] {source_text[:PROMPT_SOURCE_TEXT_MAX_CHARS]}",
            )
            api_result = _distill_with_api(api_client, model, prompt)
            if api_result is None:
                result = _rules_based_distill(paper_row, source_text=source_text, reading_level=level)
                distill_method = "rules_based"
            else:
                result = api_result
                distill_method = "gemini_api" if isinstance(api_client, _GeminiClientShim) else "claude_api"
        else:
            result = _rules_based_distill(paper_row, source_text=source_text, reading_level=level)
            distill_method = "rules_based"

        result = _sanitize_distill_result(result, reading_level=level)
        result["summary_source"] = source_type
        result["source_text_hash"] = source_hash
        result["source_text_chars"] = len(source_text)
        result["summary_generated_at_utc"] = generated_at_utc
        result["distill_method"] = distill_method
        result["faithfulness_overlap"] = _faithfulness_overlap(
            _clean_text(result.get("summary", "")),
            _parse_json_list(result.get("key_takeaways", [])),
            source_text,
        )
        certainty_score, certainty_label = _certainty_from_signals(
            source_type=source_type,
            source_chars=len(source_text),
            method=distill_method,
            overlap=float(result.get("faithfulness_overlap", 0.0)),
        )
        result["summary_certainty_score"] = certainty_score
        result["summary_certainty_label"] = certainty_label
        result["summary_disclaimer"] = _disclaimer_for_source(source_type, certainty_label)
        _save_cache(cache_dir, paper_id, level, result)
        return result

    summary_rows = []
    api_call_counter = 0
    for idx, (_, row) in enumerate(scored.iterrows()):
        paper_id = row["canonical_paper_id"]
        source_text, source_type = _context_from_row(row.to_dict(), fulltext_by_id, fulltext_source_by_id)
        if not source_text:
            continue
        source_hash = hashlib.sha1(source_text.encode("utf-8")).hexdigest()
        generated_at_utc = datetime.now(timezone.utc).isoformat()

        topic_label = topic_labels.get(paper_topic_map.get(paper_id), "General MS")
        paper_row_dict = row.to_dict()

        variants: dict[str, dict] = {}
        for level in active_levels:
            variants[level] = _distill_one_level(
                paper_row=paper_row_dict, paper_id=paper_id, topic_label=topic_label,
                source_text=source_text, source_type=source_type, source_hash=source_hash,
                generated_at_utc=generated_at_utc, level=level,
            )
            if api_client and variants[level].get("distill_method") == "claude_api":
                api_call_counter += 1
                if api_call_counter % batch_size == 0:
                    time.sleep(1)

        default_variant = variants.get(default_level) or next(iter(variants.values()))
        combined: dict = {
            "canonical_paper_id": paper_id, "title": row.get("title", ""),
            "year": _coerce_int(row.get("year"), default=None), "doi": row.get("doi", ""),
            **default_variant,
            "reading_level_target": default_level,
            "language_difficulty": _reading_level_numeric(default_level),
            "difficulty": _reading_level_numeric(default_level),
        }
        # Emit per-level variant fields so the frontend can switch between
        # basic/advanced without another pipeline run.
        for level, variant in variants.items():
            combined[f"summary_{level}"] = _clean_text(variant.get("summary", ""))
            combined[f"why_it_matters_{level}"] = _clean_text(variant.get("why_it_matters", ""))
            combined[f"key_takeaways_{level}"] = variant.get("key_takeaways", [])
            combined[f"jargon_{level}"] = variant.get("jargon", [])
        summary_rows.append(combined)

        if (idx + 1) % 50 == 0:
            print(f"  Distilled {idx + 1}/{len(scored)} papers (levels: {', '.join(active_levels)})")

    _write_summaries_csv(summary_rows, active_levels, outdir, qa_sample_size, qa_random_seed)
    _generate_topic_overviews(topic_clusters, scored, paper_topics, api_client, model, outdir)
    _generate_reading_paths(paper_topics, scored, outdir)
    print(f"Distilled {len(summary_rows)} papers. Outputs in {outdir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
