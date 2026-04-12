#!/usr/bin/env python3
"""Build and validate the concept->paper linkage cache.

Default mode is read-only cache validation (no API calls).
Use ``--refresh`` to regenerate concept links from the current corpus.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml


CONCEPTS_DIR = Path("site/src/content/docs/concepts")
SCORED_PAPERS_CSV = Path("outputs/graph/scored_papers.csv")
# Preferred corpus source: post-selection tracked CSV (~900 papers) so concept
# pages only reference papers visible in the explorer. Falls back to scored_papers
# when the tracked file is absent (e.g. early pipeline stages).
CORE_CORPUS_TRACKED_CSV = Path("outputs/graph/core_corpus_tracked_with_t4.csv")
PAPER_TOPICS_CSV = Path("outputs/topics/paper_topics.csv")
TOPIC_CLUSTERS_CSV = Path("outputs/topics/topic_clusters.csv")
DEFAULT_CACHE_PATH = Path("data/concept_papers.json")

CACHE_VERSION = 1
MAX_CANDIDATES_PER_CONCEPT = 60
MAX_PER_TOPIC = 8
DEFAULT_FOUNDATIONAL_COUNT = 8
DEFAULT_ADVANCED_COUNT = 8
# Maximum tokens to request from the LLM per concept-linking call.
LLM_MAX_TOKENS = 1200
# Maximum characters of abstract included in the concept-linking payload.
ABSTRACT_SNIPPET_CHARS = 400

# Compact stopword list for lexical overlap scoring.
STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

SELECTION_PROMPT = """You are selecting papers for a concept page in a multiple sclerosis learning site.

Task:
- Choose foundational papers (core orientation papers) and advanced papers (deeper/specialized papers).
- Use only ids from the provided shortlist.
- Keep each list to at most 8 ids, no duplicates, no overlap.
- Prefer conceptual coverage, methodological diversity, and relevance to the concept description.
- Avoid redundant papers with near-identical scope.

Output format:
Return JSON only with exactly these keys:
{
  "foundational": ["paper_id_1", "..."],
  "advanced": ["paper_id_a", "..."],
  "rationales": {
    "paper_id_1": "One short sentence.",
    "paper_id_a": "One short sentence."
  }
}

Rules:
- Every paper id in foundational/advanced must appear in shortlist ids.
- Every selected id must have a rationale entry.
- Rationale sentences must be concise and specific to the concept.
"""


@dataclass(frozen=True)
class ConceptDoc:
    concept_id: str
    category: str
    title: str
    description: str
    objectives: tuple[str, ...]
    source_path: Path

    @property
    def query_text(self) -> str:
        objective_text = " ".join(self.objectives)
        return " ".join(
            [
                self.concept_id.replace("_", " "),
                self.category,
                self.title,
                self.description,
                objective_text,
            ]
        )


@dataclass(frozen=True)
class PaperDoc:
    paper_id: str
    title: str
    abstract: str
    year: int | None
    importance: float
    topic_id: str
    topic_label: str
    tokens: Counter[str]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _clean_int(value: Any) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _clean_float(value: Any, default: float = 0.0) -> float:
    text = _clean_text(value)
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _is_truthy(value: Any) -> bool:
    text = _clean_text(value).lower()
    return text in {"1", "true", "yes", "y", "t"}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9\-]{1,}", text.lower())
    out = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        if len(token) < 3:
            continue
        out.append(token)
    return out


def _load_dotenv(root: Path) -> None:
    candidates = [root / ".env", Path.home() / ".env"]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("export "):
                raw = raw[7:].strip()
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.DOTALL)
    if not m:
        return {}, text
    frontmatter = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def _load_concepts(root: Path) -> list[ConceptDoc]:
    concepts: list[ConceptDoc] = []
    concepts_root = root / CONCEPTS_DIR
    if not concepts_root.exists():
        raise FileNotFoundError(f"Concept directory not found: {concepts_root}")

    for path in sorted(concepts_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        if path.name == "index.mdx":
            continue

        frontmatter, body = _parse_frontmatter(path)
        concept_meta = frontmatter.get("concept")
        if not isinstance(concept_meta, dict):
            continue

        concept_id = _clean_text(concept_meta.get("id"))
        category = _clean_text(concept_meta.get("category"))
        title = _clean_text(frontmatter.get("title"))
        description = _clean_text(frontmatter.get("description"))
        raw_objectives = concept_meta.get("objectives") or []
        objectives = tuple(_clean_text(item) for item in raw_objectives if _clean_text(item))
        if not concept_id:
            continue
        if not title:
            title = concept_id.replace("_", " ").title()
        if not description:
            # Fallback to the first prose line from the body.
            description = _clean_text(next((ln for ln in body.splitlines() if ln.strip()), ""))

        concepts.append(
            ConceptDoc(
                concept_id=concept_id,
                category=category,
                title=title,
                description=description,
                objectives=objectives,
                source_path=path,
            )
        )

    concepts.sort(key=lambda c: c.concept_id)
    if not concepts:
        raise RuntimeError("No concept files with concept.id metadata found.")
    return concepts


def _load_topic_labels(root: Path) -> dict[str, str]:
    path = root / TOPIC_CLUSTERS_CSV
    if not path.exists():
        return {}
    labels: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = _clean_text(row.get("topic_id"))
            if not tid:
                continue
            labels[tid] = _clean_text(row.get("auto_label"))
    return labels


def _load_primary_topic_per_paper(root: Path) -> dict[str, str]:
    path = root / PAPER_TOPICS_CSV
    if not path.exists():
        return {}

    best_topic: dict[str, tuple[float, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = _clean_text(row.get("canonical_paper_id"))
            tid = _clean_text(row.get("topic_id"))
            if not pid or not tid:
                continue
            conf = _clean_float(row.get("confidence"), 0.0)
            prev = best_topic.get(pid)
            if prev is None or conf > prev[0]:
                best_topic[pid] = (conf, tid)
    return {pid: topic for pid, (_conf, topic) in best_topic.items()}


def _load_papers(root: Path, topic_by_paper: dict[str, str], topic_label_by_id: dict[str, str]) -> list[PaperDoc]:
    """Load the candidate paper pool for concept linking.

    Prefers core_corpus_tracked_with_t4.csv (the post-selection ~900-paper corpus)
    so concept pages only reference papers visible in the explorer. Falls back to
    scored_papers.csv filtered by in_final_corpus when the tracked file is absent.
    """
    tracked = root / CORE_CORPUS_TRACKED_CSV
    scored = root / SCORED_PAPERS_CSV
    if tracked.exists():
        path = tracked
        is_tracked = True
    elif scored.exists():
        path = scored
        is_tracked = False
    else:
        raise FileNotFoundError(
            f"Corpus file not found: tried {tracked} and {scored}"
        )

    papers: list[PaperDoc] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            paper_id = _clean_text(row.get("canonical_paper_id"))
            if not paper_id:
                continue

            if not is_tracked:
                # scored_papers.csv fallback: filter to final-corpus rows only.
                if "in_final_corpus" in row and not _is_truthy(row.get("in_final_corpus")):
                    continue
                if "tier" in row:
                    tier = _clean_text(row.get("tier")).lower()
                    if tier and tier not in {"included", "seed_neighbor"}:
                        continue

            title = _clean_text(row.get("title"))
            abstract = _clean_text(row.get("abstract"))
            if not title and not abstract:
                continue

            tokens = Counter(_tokenize(f"{title} {abstract}"))
            if not tokens:
                continue

            topic_id = topic_by_paper.get(paper_id, "")
            papers.append(
                PaperDoc(
                    paper_id=paper_id,
                    title=title or "Untitled",
                    abstract=abstract,
                    year=_clean_int(row.get("year")),
                    importance=_clean_float(row.get("paper_importance_score"), 0.0),
                    topic_id=topic_id,
                    topic_label=topic_label_by_id.get(topic_id, ""),
                    tokens=tokens,
                )
            )
    source_name = path.name
    if not papers:
        raise RuntimeError(f"No candidate papers available after filtering {source_name}.")
    return papers


def _build_idf(papers: list[PaperDoc]) -> dict[str, float]:
    doc_freq: Counter[str] = Counter()
    for paper in papers:
        doc_freq.update(paper.tokens.keys())
    n_docs = len(papers)
    return {token: math.log((n_docs + 1) / (freq + 1)) + 1.0 for token, freq in doc_freq.items()}


def _build_postings(papers: list[PaperDoc]) -> dict[str, list[tuple[int, int]]]:
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for idx, paper in enumerate(papers):
        for token, tf in paper.tokens.items():
            postings[token].append((idx, tf))
    return postings


def _rank_shortlist(
    concept: ConceptDoc,
    papers: list[PaperDoc],
    idf: dict[str, float],
    postings: dict[str, list[tuple[int, int]]],
    max_per_topic: int = MAX_PER_TOPIC,
    max_candidates: int = MAX_CANDIDATES_PER_CONCEPT,
) -> list[tuple[PaperDoc, float]]:
    query_tf = Counter(_tokenize(concept.query_text))
    query_weights: dict[str, float] = {}
    for token, tf in query_tf.items():
        token_idf = idf.get(token)
        if token_idf is None:
            continue
        query_weights[token] = (1.0 + math.log(tf)) * token_idf

    if not query_weights:
        return []

    scores: dict[int, float] = defaultdict(float)
    for token, q_weight in query_weights.items():
        for paper_idx, paper_tf in postings.get(token, []):
            scores[paper_idx] += q_weight * (1.0 + math.log(max(1, paper_tf)))

    ranked = sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            -papers[item[0]].importance,
            papers[item[0]].year if papers[item[0]].year is not None else 9999,
            papers[item[0]].paper_id,
        ),
    )
    if not ranked:
        return []

    selected: list[tuple[PaperDoc, float]] = []
    topic_counts: Counter[str] = Counter()
    for paper_idx, score in ranked:
        paper = papers[paper_idx]
        if paper.topic_id and topic_counts[paper.topic_id] >= max_per_topic:
            continue
        selected.append((paper, score))
        if paper.topic_id:
            topic_counts[paper.topic_id] += 1
        if len(selected) >= max_candidates:
            break
    return selected


def _shortlist_payload(shortlist: list[tuple[PaperDoc, float]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for paper, score in shortlist:
        payload.append(
            {
                "id": paper.paper_id,
                "title": paper.title,
                "year": paper.year,
                "topic_id": paper.topic_id,
                "topic_label": paper.topic_label,
                "importance": round(paper.importance, 6),
                "score": round(score, 6),
                "abstract_snippet": _clean_text(paper.abstract)[:ABSTRACT_SNIPPET_CHARS],
            }
        )
    return payload


def _heuristic_selection(
    concept: ConceptDoc,
    shortlist: list[dict[str, Any]],
    foundational_limit: int = DEFAULT_FOUNDATIONAL_COUNT,
    advanced_limit: int = DEFAULT_ADVANCED_COUNT,
) -> dict[str, Any]:
    def foundational_key(row: dict[str, Any]) -> tuple:
        year = row.get("year")
        year_val = int(year) if isinstance(year, int) else 9999
        return (-float(row.get("importance", 0.0)), year_val, -float(row.get("score", 0.0)), row["id"])

    def advanced_key(row: dict[str, Any]) -> tuple:
        year = row.get("year")
        year_val = int(year) if isinstance(year, int) else 0
        return (-float(row.get("score", 0.0)), -year_val, -float(row.get("importance", 0.0)), row["id"])

    ranked_for_foundational = sorted(shortlist, key=foundational_key)
    foundational = [row["id"] for row in ranked_for_foundational[:foundational_limit]]

    ranked_for_advanced = sorted(shortlist, key=advanced_key)
    advanced: list[str] = []
    for row in ranked_for_advanced:
        paper_id = row["id"]
        if paper_id in foundational:
            continue
        advanced.append(paper_id)
        if len(advanced) >= advanced_limit:
            break

    rationales: dict[str, str] = {}
    by_id = {row["id"]: row for row in shortlist}
    for paper_id in foundational:
        rationales[paper_id] = (
            f"Foundational anchor for {concept.title.lower()} with broad relevance and strong corpus importance."
        )
    for paper_id in advanced:
        row = by_id[paper_id]
        topic_text = _clean_text(row.get("topic_label")) or "a specialized topic"
        rationales[paper_id] = (
            f"Advanced extension of {concept.title.lower()} focused on {topic_text.lower()}."
        )

    return {
        "foundational": foundational,
        "advanced": advanced,
        "rationales": rationales,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = _clean_text(text)
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        parsed = json.loads(snippet)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _validate_selection(
    selection: dict[str, Any] | None,
    allowed_ids: set[str],
    foundational_limit: int = DEFAULT_FOUNDATIONAL_COUNT,
    advanced_limit: int = DEFAULT_ADVANCED_COUNT,
) -> dict[str, Any] | None:
    if not isinstance(selection, dict):
        return None

    def normalize_id_list(values: Any, limit: int) -> list[str]:
        if not isinstance(values, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            pid = _clean_text(item)
            if not pid or pid not in allowed_ids or pid in seen:
                continue
            seen.add(pid)
            out.append(pid)
            if len(out) >= limit:
                break
        return out

    foundational = normalize_id_list(selection.get("foundational"), foundational_limit)
    advanced = normalize_id_list(selection.get("advanced"), advanced_limit)
    advanced = [pid for pid in advanced if pid not in set(foundational)]

    if not foundational and not advanced:
        return None

    raw_rationales = selection.get("rationales")
    rationales: dict[str, str] = {}
    if isinstance(raw_rationales, dict):
        for pid, rationale in raw_rationales.items():
            clean_id = _clean_text(pid)
            clean_rationale = _clean_text(rationale)
            if clean_id in allowed_ids and clean_rationale:
                rationales[clean_id] = clean_rationale

    for pid in foundational + advanced:
        if pid not in rationales:
            rationales[pid] = "Selected for direct relevance to the concept scope."

    return {
        "foundational": foundational,
        "advanced": advanced,
        "rationales": rationales,
    }


def _gemini_select(model: str, prompt: str, api_key: str, timeout_seconds: int = 90) -> dict[str, Any] | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    raw_verify = _clean_text(os.environ.get("MSKB_SSL_VERIFY", "true")).lower()
    verify_ssl = raw_verify not in {"0", "false", "no", "off"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=timeout_seconds,
        verify=verify_ssl,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return None
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    text = ""
    for part in parts:
        chunk = _clean_text(part.get("text"))
        if chunk:
            text += chunk
    return _extract_json_object(text)


def _anthropic_select(model: str, prompt: str, timeout_seconds: int = 90) -> dict[str, Any] | None:
    try:
        import anthropic
    except Exception:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        return None

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
    msg = client.messages.create(
        model=model,
        temperature=0,
        max_tokens=LLM_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    chunks = []
    for item in msg.content:
        text = getattr(item, "text", "")
        if text:
            chunks.append(text)
    return _extract_json_object("\n".join(chunks))


def _build_selection_prompt(concept: ConceptDoc, shortlist_payload: list[dict[str, Any]]) -> str:
    concept_block = {
        "concept_id": concept.concept_id,
        "category": concept.category,
        "title": concept.title,
        "description": concept.description,
        "objectives": list(concept.objectives),
    }
    return (
        SELECTION_PROMPT
        + "\n\nConcept:\n"
        + json.dumps(concept_block, indent=2, ensure_ascii=False)
        + "\n\nShortlist:\n"
        + json.dumps(shortlist_payload, indent=2, ensure_ascii=False)
    )


def _run_selection_llm(
    provider: str,
    model: str,
    concept: ConceptDoc,
    shortlist_payload: list[dict[str, Any]],
) -> dict[str, Any] | None:
    prompt = _build_selection_prompt(concept, shortlist_payload)
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            return None
        try:
            return _gemini_select(model=model, prompt=prompt, api_key=key)
        except Exception as exc:
            print(f"[warn] Gemini selection failed for {concept.concept_id}: {type(exc).__name__}")
            return None
    if provider == "anthropic":
        try:
            return _anthropic_select(model=model, prompt=prompt)
        except Exception as exc:
            print(f"[warn] Anthropic selection failed for {concept.concept_id}: {type(exc).__name__}")
            return None
    return None


def _prompt_hash() -> str:
    return hashlib.sha256(SELECTION_PROMPT.encode("utf-8")).hexdigest()


def _validate_cache_structure(
    cache_data: dict[str, Any],
    concept_ids: set[str],
    paper_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(cache_data, dict):
        return ["Cache root must be a JSON object."]

    concepts = cache_data.get("concepts")
    if not isinstance(concepts, dict):
        return ["Cache field 'concepts' must be an object."]

    cache_concept_ids = set(concepts.keys())
    missing_concepts = sorted(concept_ids - cache_concept_ids)
    extra_concepts = sorted(cache_concept_ids - concept_ids)
    if missing_concepts:
        errors.append(f"Missing concept ids in cache ({len(missing_concepts)}): {missing_concepts[:6]}")
    if extra_concepts:
        errors.append(f"Unknown concept ids in cache ({len(extra_concepts)}): {extra_concepts[:6]}")

    for concept_id in sorted(concept_ids & cache_concept_ids):
        payload = concepts.get(concept_id)
        if not isinstance(payload, dict):
            errors.append(f"{concept_id}: payload must be an object.")
            continue
        foundational = payload.get("foundational")
        advanced = payload.get("advanced")
        rationales = payload.get("rationales")
        if not isinstance(foundational, list):
            errors.append(f"{concept_id}: foundational must be a list.")
            foundational = []
        if not isinstance(advanced, list):
            errors.append(f"{concept_id}: advanced must be a list.")
            advanced = []
        if not isinstance(rationales, dict):
            errors.append(f"{concept_id}: rationales must be an object.")
            rationales = {}

        seen: set[str] = set()
        for group_name, ids in (("foundational", foundational), ("advanced", advanced)):
            for item in ids:
                pid = _clean_text(item)
                if not pid:
                    errors.append(f"{concept_id}: empty id in {group_name}.")
                    continue
                if pid in seen:
                    errors.append(f"{concept_id}: duplicate id across lists: {pid}")
                    continue
                seen.add(pid)
                if pid not in paper_ids:
                    errors.append(f"{concept_id}: unknown paper id in {group_name}: {pid}")
                    continue
                rationale = _clean_text(rationales.get(pid))
                if not rationale:
                    errors.append(f"{concept_id}: missing rationale for {pid}")
    return errors


def _load_existing_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _determine_provider_and_model(args: argparse.Namespace) -> tuple[str, str]:
    provider = args.provider
    model = _clean_text(args.model)
    if provider == "auto":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            provider = "anthropic"
        else:
            provider = "none"

    if provider == "gemini":
        if not model:
            model = "gemini-2.5-flash"
    elif provider == "anthropic":
        if not model:
            model = "claude-haiku-4-5-20251001"
    else:
        model = "heuristic"
    return provider, model


def _parse_only_ids(raw_value: str) -> set[str]:
    parts = [chunk.strip() for chunk in raw_value.split(",")]
    return {part for part in parts if part}


def _refresh_cache(
    *,
    root: Path,
    concepts: list[ConceptDoc],
    papers: list[PaperDoc],
    cache_path: Path,
    dry_run: bool,
    only_ids: set[str] | None,
    provider: str,
    model: str,
) -> int:
    idf = _build_idf(papers)
    postings = _build_postings(papers)
    paper_ids = {paper.paper_id for paper in papers}

    concept_by_id = {concept.concept_id: concept for concept in concepts}
    selected_ids = set(concept_by_id.keys()) if not only_ids else set(only_ids)
    unknown_only_ids = sorted(selected_ids - set(concept_by_id.keys()))
    if unknown_only_ids:
        print(f"[error] Unknown concept ids passed to --only: {unknown_only_ids}")
        return 2

    existing_cache = _load_existing_cache(cache_path) or {}
    merged_concepts = {}
    if isinstance(existing_cache.get("concepts"), dict):
        merged_concepts.update(existing_cache["concepts"])

    llm_used = provider in {"gemini", "anthropic"}
    for idx, concept_id in enumerate(sorted(selected_ids), start=1):
        concept = concept_by_id[concept_id]
        shortlist = _rank_shortlist(concept=concept, papers=papers, idf=idf, postings=postings)
        shortlist_payload = _shortlist_payload(shortlist)
        if not shortlist_payload:
            print(f"[warn] No shortlist candidates for {concept_id}; storing empty lists.")
            merged_concepts[concept_id] = {"foundational": [], "advanced": [], "rationales": {}}
            continue

        selection = None
        if llm_used:
            raw_selection = _run_selection_llm(
                provider=provider,
                model=model,
                concept=concept,
                shortlist_payload=shortlist_payload,
            )
            selection = _validate_selection(raw_selection, allowed_ids={item["id"] for item in shortlist_payload})

        if selection is None:
            selection = _heuristic_selection(concept=concept, shortlist=shortlist_payload)
            selection = _validate_selection(selection, allowed_ids={item["id"] for item in shortlist_payload})

        if selection is None:
            # Should be unreachable due heuristic fallback, but keep defensive.
            selection = {"foundational": [], "advanced": [], "rationales": {}}

        merged_concepts[concept_id] = selection
        print(
            f"  [{idx}/{len(selected_ids)}] {concept_id}: "
            f"{len(selection['foundational'])} foundational, {len(selection['advanced'])} advanced"
        )

    # If only refreshing a subset, keep untouched concepts from existing cache.
    if only_ids:
        for concept_id in concept_by_id:
            if concept_id not in merged_concepts:
                merged_concepts[concept_id] = {"foundational": [], "advanced": [], "rationales": {}}

    cache_data = {
        "version": CACHE_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model if llm_used else "heuristic-fallback",
        "prompt_hash": _prompt_hash(),
        "concepts": {cid: merged_concepts[cid] for cid in sorted(merged_concepts)},
    }

    errors = _validate_cache_structure(cache_data, set(concept_by_id.keys()), paper_ids)
    if errors:
        print("[error] Refreshed cache failed validation:")
        for error in errors:
            print(f"  - {error}")
        return 2

    if dry_run:
        print(f"[dry-run] Cache validation passed. Would write {len(cache_data['concepts'])} concepts to {cache_path}")
        return 0

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {cache_path} with {len(cache_data['concepts'])} concepts.")
    return 0


def _validate_existing_cache(cache_path: Path, concepts: list[ConceptDoc], papers: list[PaperDoc]) -> int:
    cache_data = _load_existing_cache(cache_path)
    if cache_data is None:
        print(f"[error] Cache file not found or invalid JSON: {cache_path}")
        return 2
    concept_ids = {concept.concept_id for concept in concepts}
    paper_ids = {paper.paper_id for paper in papers}
    errors = _validate_cache_structure(cache_data, concept_ids, paper_ids)
    if errors:
        print(f"[error] Cache validation failed for {cache_path}:")
        for error in errors:
            print(f"  - {error}")
        return 2
    print(f"Cache validation passed: {cache_path} ({len(concept_ids)} concepts)")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser for the concept-to-paper linking tool."""
    parser = argparse.ArgumentParser(description="Link concepts to papers and maintain data/concept_papers.json cache.")
    parser.add_argument("--config", default="config.yaml", help="Config path (used only for resolving repo root).")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH), help="Cache output path.")
    parser.add_argument(
        "--provider",
        choices=["auto", "none", "gemini", "anthropic"],
        default="auto",
        help="LLM provider for --refresh mode. Default auto-detects available keys.",
    )
    parser.add_argument("--model", default="", help="LLM model name override.")
    parser.add_argument("--refresh", action="store_true", help="Regenerate cache entries.")
    parser.add_argument("--dry-run", action="store_true", help="Run refresh logic without writing cache.")
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated concept ids to refresh (e.g., --only b_cell_targeted_therapies,neuroinflammation).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate or refresh the concept-paper cache; return an exit code."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config).resolve()
    root = config_path.parent
    _load_dotenv(root)

    try:
        concepts = _load_concepts(root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 1
    topic_by_paper = _load_primary_topic_per_paper(root)
    topic_label_by_id = _load_topic_labels(root)
    papers = _load_papers(root, topic_by_paper=topic_by_paper, topic_label_by_id=topic_label_by_id)

    cache_path = (root / args.cache).resolve() if not Path(args.cache).is_absolute() else Path(args.cache)
    only_ids = _parse_only_ids(args.only) if args.only else None

    if args.refresh:
        provider, model = _determine_provider_and_model(args)
        if provider == "none":
            print("[warn] No LLM provider configured; using deterministic heuristic selection.")
        else:
            print(f"Using provider={provider}, model={model}")
        return _refresh_cache(
            root=root,
            concepts=concepts,
            papers=papers,
            cache_path=cache_path,
            dry_run=bool(args.dry_run),
            only_ids=only_ids,
            provider=provider,
            model=model,
        )

    # Default mode: read-only validation.
    return _validate_existing_cache(cache_path=cache_path, concepts=concepts, papers=papers)


if __name__ == "__main__":
    raise SystemExit(main())
