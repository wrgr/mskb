#!/usr/bin/env python3
"""
build_t4_manifest.py

Generates data/t4_expert_signal.yaml (v2 slim format) from the candidate papers
surfaced in concept pages and matched against the corpus by review_candidate_papers.py.

All papers are added as Tier 4 (Expert Signal) items with:
  - A short relevance note (editor's rationale for inclusion).
  - Corpus status and stats for papers already in the corpus.
  - Topic code alignment read directly from concept frontmatter.

Output format (v2):
  by_concept:
    <concept_id>:
      concept_path: concepts/...
      papers:
        - t4_id, title, authors, year, journal, topic_codes, relevance,
          corpus_status, [corpus_id, corpus_stats,] doi, [openalex_id]
"""

import re
import yaml
from pathlib import Path

REPO = Path(__file__).parent.parent
CONCEPTS_DIR = REPO / "site/src/content/docs/concepts"
CANDIDATE_YAML = REPO / "data/candidate_papers.yaml"
OUT_YAML = REPO / "data/t4_expert_signal.yaml"


def get_topic_codes(concept_id: str) -> list[str]:
    """Read topic_map anchor codes from concept frontmatter."""
    slug = concept_id.replace("_", "-")
    for md in CONCEPTS_DIR.rglob(f"{slug}.md"):
        text = md.read_text()
        m = re.search(r"topic_map:\s*\[([^\]]+)\]", text)
        if m:
            return [t.strip().strip('"').strip("'") for t in m.group(1).split(",")]
    return []


def get_concept_title(concept_id: str) -> str:
    """Read title from concept frontmatter."""
    slug = concept_id.replace("_", "-")
    for md in CONCEPTS_DIR.rglob(f"{slug}.md"):
        text = md.read_text()
        m = re.search(r"^title:\s*(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return concept_id


def concept_path(concept_id: str) -> str:
    """Return the docs-relative path for a concept page."""
    slug = concept_id.replace("_", "-")
    for md in CONCEPTS_DIR.rglob(f"{slug}.md"):
        parts = md.relative_to(CONCEPTS_DIR.parent).parts
        return "/".join(parts).removesuffix(".md")
    return f"concepts/???/{slug}"


def _build_entry(seq: int, concept_id: str, cpath: str, topic_codes: list[str], cand: dict) -> dict:
    """Build a single slim T4 entry dict."""
    entry: dict = {
        "t4_id": f"T4-{seq:03d}",
        "title": cand["title"],
        "authors": cand["authors"],
        "year": cand["year"],
        "journal": cand["journal"],
        "topic_codes": topic_codes,
        "relevance": cand["relevance"],
        "corpus_status": cand["corpus_status"],
    }

    if cand["corpus_status"] != "not_found":
        stats = cand.get("corpus_stats", {})
        if cand.get("corpus_id"):
            entry["corpus_id"] = cand["corpus_id"]
        entry["corpus_stats"] = {
            k: v for k, v in {
                "citation_count": stats.get("citation_count"),
                "in_degree": stats.get("in_degree"),
                "out_degree": stats.get("out_degree"),
                "pagerank_pct": stats.get("pagerank_pct"),
                "kcore": stats.get("kcore"),
                "core_score": stats.get("core_score"),
                "existing_tier": stats.get("tier"),
                "seed_hops": stats.get("seed_hops"),
                "cocite_seeds": stats.get("cocite_seeds"),
            }.items() if v is not None
        }

    if cand.get("corpus_doi"):
        entry["doi"] = cand["corpus_doi"]

    return entry


def main() -> None:
    """Generate the slim v2 T4 manifest from candidate_papers.yaml."""
    with open(CANDIDATE_YAML) as f:
        candidate_data = yaml.safe_load(f)

    seq = 0
    by_concept: dict[str, dict] = {}

    for concept_block in candidate_data:
        concept_id = concept_block["concept"]
        topic_codes = get_topic_codes(concept_id)
        cpath = concept_path(concept_id)
        papers: list[dict] = []

        for cand in concept_block["candidates"]:
            seq += 1
            papers.append(_build_entry(seq, concept_id, cpath, topic_codes, cand))

        by_concept[concept_id] = {
            "concept_path": cpath,
            "papers": papers,
        }

    total = sum(len(v["papers"]) for v in by_concept.values())
    not_in = sum(
        1
        for v in by_concept.values()
        for p in v["papers"]
        if p["corpus_status"] == "not_found"
    )
    in_corpus = total - not_in

    manifest = {
        "version": "2.0",
        "generated": "2026-04-10",
        "t4_source_type": "concept_anchor_signal",
        "description": (
            "Papers explicitly nominated by editors as required anchors for MSKB "
            "educational concept pages. Each paper was identified as necessary to "
            "cover a thin-topic-area concept that is structurally under-served by "
            "the algorithmic corpus selection (T2/T3). "
            "Satisfies Tier 4 criteria (Section 8 of ms_corpus_design_decisions.md): "
            "explicit expert signal documented; cross_seed_score = 0 acceptable. "
            f"Total: {total} papers — {not_in} not yet in corpus (primary addition "
            f"targets), {in_corpus} already included (signal formalisation only)."
        ),
        "by_concept": by_concept,
    }

    class NoAliasDumper(yaml.Dumper):
        def ignore_aliases(self, data: object) -> bool:
            return True

    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, Dumper=NoAliasDumper, allow_unicode=True,
                  sort_keys=False, default_flow_style=False)

    print(f"Written: {OUT_YAML}")
    print(f"  {total} T4 entries ({not_in} not-in-corpus, {in_corpus} already-included)")
    for cid, block in by_concept.items():
        n_new = sum(1 for p in block["papers"] if p["corpus_status"] == "not_found")
        print(f"  {cid}: {len(block['papers'])} papers ({n_new} new)")


if __name__ == "__main__":
    main()
