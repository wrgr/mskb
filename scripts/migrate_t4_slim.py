#!/usr/bin/env python3
"""
migrate_t4_slim.py

One-shot migration of data/t4_expert_signal.yaml from the verbose v1.x format
to the slim v2.0 format.

Changes applied:
  - Drops flat_list (was a verbatim duplicate of by_concept).
  - Moves concept_path to the concept-group level.
  - Replaces the boilerplate t4_signal with a short relevance field (just the
    editor's actual note, extracted from the template sentence).
  - Renames corpus_doi → doi, corpus_openalex_id → openalex_id.
  - Drops per-entry t4_source_type, concept, concept_path, corpus_status_note.
  - Drops boilerplate t4_note ("Paper is already structurally included…");
    keeps genuine correction/provenance notes as provenance.
  - Unifies equity-section fields (rationale → relevance, topics → topic_codes).
  - Removes YAML anchors/aliases (they were artifacts, not intentional links).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
SRC = REPO / "data" / "t4_expert_signal.yaml"

# Sentinel that marks auto-generated boilerplate t4_notes to discard.
_BOILERPLATE_NOTE_PREFIX = "Paper is already structurally included in corpus"

# Regex to extract the short editor note from the verbose t4_signal template:
#   "…Relevance documented by editor: <NOTE>. Concept covers thin-coverage…"
_RELEVANCE_RE = re.compile(
    r"Relevance documented by editor:\s*(.+?)\.\s*Concept covers thin-coverage",
    re.DOTALL,
)


def _extract_relevance(t4_signal: str) -> str:
    """Pull the editor's note out of the boilerplate t4_signal string."""
    m = _RELEVANCE_RE.search(t4_signal)
    if m:
        return " ".join(m.group(1).split())  # normalise internal whitespace
    # Fallback: return the whole string stripped of the leading boilerplate.
    for prefix in (
        "Nominated as required anchor for concept page",
        "Relevance documented by editor:",
    ):
        if t4_signal.startswith(prefix):
            return t4_signal[len(prefix):].strip().lstrip("'").strip()
    return t4_signal.strip()


def _slim_entry(entry: dict, concept_path: str) -> dict:
    """Return a new dict with only the fields needed in the slim format."""
    # --- relevance -----------------------------------------------------------
    if entry.get("t4_signal"):
        relevance = _extract_relevance(str(entry["t4_signal"]))
    elif entry.get("rationale"):
        relevance = str(entry["rationale"]).strip()
    else:
        relevance = ""

    # --- topic_codes ---------------------------------------------------------
    topic_codes = entry.get("topic_codes") or entry.get("topics") or []
    if not isinstance(topic_codes, list):
        topic_codes = [str(topic_codes)]

    # --- identifiers ---------------------------------------------------------
    doi = str(entry.get("corpus_doi") or entry.get("doi") or "").strip()
    openalex_id = str(
        entry.get("corpus_openalex_id") or entry.get("openalex_id") or ""
    ).strip()

    # --- provenance (only real notes, not auto-generated boilerplate) --------
    raw_note = str(entry.get("t4_note") or entry.get("provenance") or "").strip()
    provenance = "" if raw_note.startswith(_BOILERPLATE_NOTE_PREFIX) else raw_note

    # Build output in a deterministic, human-readable field order.
    out: dict = {"t4_id": entry["t4_id"]}
    out["title"] = str(entry.get("title") or "").strip()
    out["authors"] = str(entry.get("authors") or "").strip()
    out["year"] = entry.get("year")
    out["journal"] = str(entry.get("journal") or "").strip()
    if entry.get("pmid"):
        out["pmid"] = str(entry["pmid"]).strip()
    out["topic_codes"] = topic_codes
    out["relevance"] = relevance
    out["corpus_status"] = str(entry.get("corpus_status") or "not_found").strip()
    if entry.get("corpus_id"):
        out["corpus_id"] = str(entry["corpus_id"]).strip()
    if entry.get("corpus_stats"):
        out["corpus_stats"] = dict(entry["corpus_stats"])
    if doi:
        out["doi"] = doi
    if openalex_id:
        out["openalex_id"] = openalex_id
    if provenance:
        out["provenance"] = provenance
    return out


def migrate(src: Path) -> dict:
    """Read old YAML and return the slim payload dict (not yet written)."""
    payload = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    old_by_concept: dict = payload.get("by_concept", {}) or {}

    new_by_concept: dict = {}
    for concept_id, items in old_by_concept.items():
        if not isinstance(items, list) or not items:
            continue

        # Derive concept_path from the first standard entry that has one;
        # equity entries carry selection_source instead, so fall back gracefully.
        concept_path = ""
        for item in items:
            if isinstance(item, dict):
                cp = str(item.get("concept_path") or "").strip()
                if cp:
                    concept_path = cp
                    break
        if not concept_path:
            concept_path = f"concepts/???/{concept_id.replace('_', '-')}"

        slim_papers = [
            _slim_entry(item, concept_path)
            for item in items
            if isinstance(item, dict)
        ]
        new_by_concept[concept_id] = {
            "concept_path": concept_path,
            "papers": slim_papers,
        }

    total = sum(len(v["papers"]) for v in new_by_concept.values())
    not_found = sum(
        1
        for v in new_by_concept.values()
        for p in v["papers"]
        if p.get("corpus_status") == "not_found"
    )
    in_corpus = total - not_found

    new_payload = {
        "version": "2.0",
        "generated": str(payload.get("generated", "2026-04-10")),
        "t4_source_type": "concept_anchor_signal",
        "description": (
            "Papers explicitly nominated by editors as required anchors for MSKB "
            "educational concept pages. Each paper was identified as necessary to "
            "cover a thin-topic-area concept that is structurally under-served by "
            "the algorithmic corpus selection (T2/T3). "
            "Satisfies Tier 4 criteria (Section 8 of ms_corpus_design_decisions.md): "
            "explicit expert signal documented; cross_seed_score = 0 acceptable. "
            f"Total: {total} papers — {not_found} not yet in corpus (primary addition "
            f"targets), {in_corpus} already included (signal formalisation only)."
        ),
        "by_concept": new_by_concept,
    }
    return new_payload


def _dump(payload: dict, path: Path) -> None:
    """Write payload to path without YAML aliases."""
    class NoAliasDumper(yaml.Dumper):
        def ignore_aliases(self, data: object) -> bool:
            return True

    path.write_text(
        yaml.dump(
            payload,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Migrate SRC in-place after printing a summary."""
    new_payload = migrate(SRC)
    by_concept = new_payload["by_concept"]
    total = sum(len(v["papers"]) for v in by_concept.values())

    _dump(new_payload, SRC)

    print(f"Migrated {SRC}")
    print(f"  version: 2.0  |  {total} entries across {len(by_concept)} concepts")
    for cid, block in by_concept.items():
        print(f"  {cid}: {len(block['papers'])} papers  ({block['concept_path']})")


if __name__ == "__main__":
    sys.exit(main())
