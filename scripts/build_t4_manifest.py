#!/usr/bin/env python3
"""
build_t4_manifest.py

Generates data/t4_expert_signal.yaml from the candidate papers surfaced in
concept pages and matched against the corpus by review_candidate_papers.py.

All 52 papers are added as Tier 4 (Expert Signal) items with:
  - t4_source_type: concept_anchor_signal
  - Full expert signal documentation (concept page path + relevance note)
  - Corpus status and stats for the 7 papers already in the corpus
  - Topic code alignment read directly from concept frontmatter
"""

import json
import re
import yaml
from pathlib import Path

REPO = Path(__file__).parent.parent
CONCEPTS_DIR = REPO / "site/src/content/docs/concepts"
CANDIDATE_YAML = REPO / "data/candidate_papers.yaml"
DESIGN_DECISIONS = REPO / "data/ms_corpus_design_decisions.md"
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
    slug = concept_id.replace("_", "-")
    for md in CONCEPTS_DIR.rglob(f"{slug}.md"):
        # Return path relative to docs/
        parts = md.relative_to(CONCEPTS_DIR.parent).parts
        return "/".join(parts).removesuffix(".md")
    return f"concepts/???/{slug}"


def main():
    with open(CANDIDATE_YAML) as f:
        candidate_data = yaml.safe_load(f)

    papers = []
    seq = 0

    for concept_block in candidate_data:
        concept_id = concept_block["concept"]
        topic_codes = get_topic_codes(concept_id)
        concept_title = get_concept_title(concept_id)
        cpath = concept_path(concept_id)

        for cand in concept_block["candidates"]:
            seq += 1
            entry: dict = {
                "t4_id": f"T4-{seq:03d}",
                "t4_source_type": "concept_anchor_signal",
                "t4_signal": (
                    f"Nominated as required anchor for concept page '{concept_title}' "
                    f"({cpath}). "
                    f"Relevance documented by editor: {cand['relevance']}. "
                    f"Concept covers thin-coverage topic area(s): {', '.join(topic_codes) or 'see concept page'}."
                ),
                "concept": concept_id,
                "concept_path": cpath,
                "title": cand["title"],
                "authors": cand["authors"],
                "year": cand["year"],
                "journal": cand["journal"],
                "topic_codes": topic_codes,
                "corpus_status": cand["corpus_status"],
            }

            if cand["corpus_status"] != "not_found":
                stats = cand.get("corpus_stats", {})
                entry["corpus_id"] = cand.get("corpus_id")
                entry["corpus_doi"] = cand.get("corpus_doi") or None
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
                entry["t4_note"] = (
                    "Paper is already structurally included in corpus "
                    f"(tier={stats.get('tier')}). T4 designation formalises the "
                    "concept-anchor expert signal and links this paper to its "
                    "educational concept page."
                )

            papers.append(entry)

    in_corpus = sum(1 for p in papers if p["corpus_status"] != "not_found")
    not_in = len(papers) - in_corpus

    manifest = {
        "version": "1.0",
        "generated": "2026-04-09",
        "t4_source_type": "concept_anchor_signal",
        "description": (
            "Papers explicitly nominated by editors as required anchors for MSKB "
            "educational concept pages. Each paper was identified as necessary to "
            "cover a thin-topic-area concept that is structurally under-served by "
            "the algorithmic corpus selection (T2/T3). "
            "Satisfies Tier 4 criteria (Section 8 of ms_corpus_design_decisions.md): "
            "explicit expert signal documented; cross_seed_score = 0 acceptable. "
            f"Total: {len(papers)} papers — {not_in} not yet in corpus (primary addition "
            f"targets), {in_corpus} already included (signal formalisation only)."
        ),
        "by_concept": {},
    }

    # Group by concept for the nested output
    by_concept: dict[str, list] = {}
    for p in papers:
        by_concept.setdefault(p["concept"], []).append(p)

    manifest["by_concept"] = by_concept
    manifest["flat_list"] = papers

    # Use a plain representer to avoid YAML anchors/aliases on repeated lists
    class NoAliasDumper(yaml.Dumper):
        def ignore_aliases(self, data):
            return True

    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, Dumper=NoAliasDumper, allow_unicode=True,
                  sort_keys=False, default_flow_style=False)

    print(f"Written: {OUT_YAML}")
    print(f"  {len(papers)} T4 entries ({not_in} not-in-corpus, {in_corpus} already-included)")
    print()
    for cid, cpapers in by_concept.items():
        n_new = sum(1 for p in cpapers if p["corpus_status"] == "not_found")
        print(f"  {cid}: {len(cpapers)} papers ({n_new} new)")


if __name__ == "__main__":
    main()
