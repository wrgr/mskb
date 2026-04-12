"""Produce a clean, key-fields corpus export for external reuse.

Reads the authoritative post-selection corpus (``core_corpus_tracked_with_t4.csv``),
joins the concept–paper linkage cache, and writes three artefacts to
``outputs/corpus_export/``:

* ``ms_corpus_export.csv``  – flat CSV with a curated subset of columns
* ``ms_corpus_export.json`` – same rows in JSON with concept arrays attached
* ``README.md``             – field-by-field documentation

Only papers that are ``in_final_corpus == True`` are included.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import ensure_dir, load_config, save_json

# ---------------------------------------------------------------------------
# Field selection
# ---------------------------------------------------------------------------

# Columns to pull from the corpus CSV, in display order.
EXPORT_COLUMNS: list[str] = [
    # --- identifiers ---
    "canonical_paper_id",
    "openalex_id",
    "doi",
    "all_dois",
    "all_openalex_ids",
    # --- bibliographic ---
    "title",
    "year",
    "venue",
    "first_author",
    "is_preprint",
    "merged_cited_by_count",
    "abstract",
    "abstract_backfill_source",
    # --- corpus membership ---
    "tier",
    "corpus_role",
    "in_core_corpus",
    "in_final_corpus",
    "in_t4_expert_signal",
    "is_core_seed",
    # --- topic & category ---
    "primary_topic_code",
    "anchor_category",
    "evidence_type",
    "evidence_strength",
    # --- quality signals ---
    "score_total",
    "paper_importance_score",
    "n_independent_signals",
]

# Boolean columns that should be normalised to plain true/false strings.
_BOOL_COLS: set[str] = {
    "is_preprint",
    "in_core_corpus",
    "in_final_corpus",
    "in_t4_expert_signal",
    "is_core_seed",
}

# ---------------------------------------------------------------------------
# Field documentation for the generated README
# ---------------------------------------------------------------------------

_FIELD_DOCS: dict[str, str] = {
    "canonical_paper_id": "Stable internal identifier (MD5 of normalised title+author). Use for deduplication.",
    "openalex_id": "OpenAlex work URL (https://openalex.org/W…).",
    "doi": "Primary DOI (lowercased, https://doi.org/… form). May be empty for pre-prints.",
    "all_dois": "Semicolon-separated list of all DOIs found across merged versions.",
    "all_openalex_ids": "Semicolon-separated list of all OpenAlex IDs found across merged versions.",
    "title": "Paper title as retrieved from OpenAlex.",
    "year": "Publication year (integer).",
    "venue": "Journal or conference name.",
    "first_author": "Surname + initials of the first author.",
    "is_preprint": "True if the paper was identified as a pre-print.",
    "merged_cited_by_count": "Total citations aggregated across all merged versions.",
    "abstract": "Full abstract text. May be backfilled from PubMed/Crossref.",
    "abstract_backfill_source": "Source of backfilled abstract (e.g. 'pubmed_pmid:12345678'), empty if from OpenAlex.",
    "tier": (
        "Selection tier: T1 = core seed, T2 = structured expansion, "
        "T3 = topic-balanced fill, T4 = expert-nominated."
    ),
    "corpus_role": "Role in the corpus: 'core' (final corpus) or 'context' (supporting, not in final set).",
    "in_core_corpus": "True if the paper is in the core corpus.",
    "in_final_corpus": "True if the paper is included in the final published corpus (core ∪ T4).",
    "in_t4_expert_signal": "True if this paper was nominated by a domain expert (T4 signal).",
    "is_core_seed": "True if this paper was used as a retrieval seed.",
    "primary_topic_code": "Primary TOPIC-XX code from the MS field taxonomy (see README for label map).",
    "anchor_category": "Thematic category of the paper's anchor concept (e.g. 'pathogenesis_and_immunology').",
    "evidence_type": "Nature of the evidence the paper provides (e.g. 'clinical_trial', 'review', 'other').",
    "evidence_strength": "Ordinal evidence strength score (1 = weakest, 4 = strongest).",
    "score_total": "Composite relevance score used for T2/T3 selection (higher = more relevant).",
    "paper_importance_score": "Age-normalised importance score combining citations, graph centrality, and recency.",
    "n_independent_signals": "Number of independent retrieval signals that included this paper.",
    "concepts_foundational": "(JSON only) Concept IDs for which this paper is a foundational reference.",
    "concepts_advanced": "(JSON only) Concept IDs for which this paper is an advanced reference.",
}

_TOPIC_LABELS: dict[str, str] = {
    "TOPIC-00": "Disease Overview",
    "TOPIC-01": "Genetics",
    "TOPIC-02": "Pathophysiology",
    "TOPIC-03": "Epidemiology",
    "TOPIC-04": "Natural History",
    "TOPIC-05": "Risk Factors & EBV",
    "TOPIC-06": "Diagnosis & Monitoring",
    "TOPIC-07": "Biomarkers",
    "TOPIC-08": "Disease-Modifying Therapies",
    "TOPIC-09": "Progressive MS & Smoldering",
    "TOPIC-10": "Patient-Reported Outcomes",
    "TOPIC-11": "Symptom Management",
    "TOPIC-12": "Comorbidities",
    "TOPIC-13": "Pregnancy & Family Planning",
    "TOPIC-14": "Pediatric MS",
    "TOPIC-15": "Equity & SDOH",
    "TOPIC-16": "Clinical AI",
    "TOPIC-17": "Remyelination & Neuroprotection",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_bool(value: Any) -> bool:
    """Normalise varied truthy representations to a Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and not math.isnan(value) if isinstance(value, float) else bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _safe_str(value: Any) -> str:
    """Return string representation, collapsing NaN/None to empty string."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _safe_int(value: Any) -> int | None:
    """Return integer, or None if not convertible."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any, precision: int = 6) -> float | None:
    """Return rounded float, or None if not convertible."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return round(float(value), precision)
    except (ValueError, TypeError):
        return None


def _build_concept_index(cache_path: Path) -> dict[str, dict[str, list[str]]]:
    """Return a dict mapping canonical_paper_id -> {foundational: [...], advanced: [...]}.

    If the cache file does not exist, returns an empty dict.
    """
    if not cache_path.exists():
        return {}

    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    index: dict[str, dict[str, list[str]]] = {}

    for concept_id, data in raw.get("concepts", {}).items():
        for level in ("foundational", "advanced"):
            for paper_id in data.get(level, []):
                entry = index.setdefault(paper_id, {"foundational": [], "advanced": []})
                entry[level].append(concept_id)

    return index


def _load_corpus(corpus_path: Path) -> pd.DataFrame:
    """Load the tracked corpus CSV and return only in_final_corpus rows."""
    df = pd.read_csv(corpus_path, low_memory=False)

    # Normalise the flag column robustly (it may be bool, int, or string).
    df["in_final_corpus"] = df["in_final_corpus"].apply(_coerce_bool)
    return df[df["in_final_corpus"]].copy()


def _row_to_csv_record(row: pd.Series) -> dict[str, str]:
    """Convert a DataFrame row to a flat string dict for CSV output."""
    record: dict[str, str] = {}
    for col in EXPORT_COLUMNS:
        raw = row.get(col, "")
        if col in _BOOL_COLS:
            record[col] = str(_coerce_bool(raw)).lower()
        else:
            record[col] = _safe_str(raw)
    return record


def _row_to_json_record(
    row: pd.Series, concept_index: dict[str, dict[str, list[str]]]
) -> dict[str, Any]:
    """Convert a DataFrame row to a typed dict for JSON output, with concept arrays."""
    paper_id = _safe_str(row.get("canonical_paper_id", ""))
    record: dict[str, Any] = {}

    for col in EXPORT_COLUMNS:
        raw = row.get(col, None)
        if col in _BOOL_COLS:
            record[col] = _coerce_bool(raw)
        elif col in {"score_total", "paper_importance_score"}:
            record[col] = _safe_float(raw)
        elif col in {"merged_cited_by_count", "n_independent_signals", "evidence_strength", "year"}:
            record[col] = _safe_int(raw)
        else:
            record[col] = _safe_str(raw)

    concept_entry = concept_index.get(paper_id, {"foundational": [], "advanced": []})
    record["concepts_foundational"] = sorted(concept_entry["foundational"])
    record["concepts_advanced"] = sorted(concept_entry["advanced"])

    return record


def _write_readme(output_dir: Path, n_papers: int, generated_at: str) -> None:
    """Write a human-readable field documentation README to the export directory."""
    lines: list[str] = [
        "# MS Knowledge Base – Corpus Export",
        "",
        f"Generated: {generated_at}",
        f"Papers: {n_papers}",
        "",
        "This export contains papers from the final MS Knowledge Base corpus.",
        "Only papers with `in_final_corpus = true` are included.",
        "",
        "## Files",
        "",
        "| File | Format | Description |",
        "|------|--------|-------------|",
        "| `ms_corpus_export.csv` | CSV | Flat export with key fields. |",
        "| `ms_corpus_export.json` | JSON | Same records with typed values and concept arrays. |",
        "| `README.md` | Markdown | This file. |",
        "",
        "## Field Descriptions",
        "",
        "| Field | Description |",
        "|-------|-------------|",
    ]
    for field, doc in _FIELD_DOCS.items():
        lines.append(f"| `{field}` | {doc} |")

    lines += [
        "",
        "## Topic Code Reference",
        "",
        "| Code | Label |",
        "|------|-------|",
    ]
    for code, label in _TOPIC_LABELS.items():
        lines += [f"| `{code}` | {label} |"]

    lines += [
        "",
        "## Tier Definitions",
        "",
        "| Tier | Meaning |",
        "|------|---------|",
        "| T1 | Core seed papers identified by domain experts as foundational to the field. |",
        "| T2 | Structured expansion: papers meeting multiple relevance criteria around seeds. |",
        "| T3 | Topic-balanced fill: top-ranked papers per topic after T1/T2 selection. |",
        "| T4 | Expert-nominated additions: papers identified by domain experts outside the automated pipeline. |",
        "",
        "## Licence / Citation",
        "",
        "If you use this corpus in research, please cite the MS Knowledge Base project.",
        "Individual papers are subject to their own licences.",
    ]

    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(config_path: str) -> None:
    """Export the final corpus with key fields to outputs/corpus_export/."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    output_dir = root / cfg["output_dir"]

    corpus_path = output_dir / "graph" / "core_corpus_tracked_with_t4.csv"
    concept_cache_path = root / "data" / "concept_papers.json"
    export_dir = output_dir / "corpus_export"

    if not corpus_path.exists():
        print(
            f"[export_corpus] corpus file not found: {corpus_path}  "
            "— skipping export."
        )
        return

    ensure_dir(export_dir)

    df = _load_corpus(corpus_path)
    concept_index = _build_concept_index(concept_cache_path)
    n_papers = len(df)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"[export_corpus] exporting {n_papers} papers → {export_dir}")

    # --- CSV ---
    csv_path = export_dir / "ms_corpus_export.csv"
    csv_records = [_row_to_csv_record(row) for _, row in df.iterrows()]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_records)

    # --- JSON ---
    json_records = [_row_to_json_record(row, concept_index) for _, row in df.iterrows()]
    export_payload: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "n_papers": n_papers,
        "fields": EXPORT_COLUMNS + ["concepts_foundational", "concepts_advanced"],
        "papers": json_records,
    }
    json_path = export_dir / "ms_corpus_export.json"
    save_json(export_payload, json_path)

    # --- README ---
    _write_readme(export_dir, n_papers, generated_at)

    print(
        f"[export_corpus] wrote:\n"
        f"  {csv_path}\n"
        f"  {json_path}\n"
        f"  {export_dir / 'README.md'}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export corpus key fields.")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
