#!/usr/bin/env python3
"""
review_candidate_papers.py

Collects candidate papers listed in concept pages under "## Candidate papers for expert review",
matches them against the MSKB corpus (explorer_graph.json), computes corpus statistics,
and writes consolidated output to:
  - data/candidate_papers.yaml  (structured, machine-readable)
  - data/candidate_papers_review.md  (human-readable markdown table by concept)

Corpus statistics reported per matched paper:
  in_degree, out_degree, citation_count, pagerank (rank_pagerank %), kcore, core_score,
  topic_label, tier, seed_hops (BFS distance from any review-anchor seed paper)

Co-citation with seeds: count of how many seed papers share a citation neighbour with
the candidate paper (undirected, within the corpus graph).
"""

import json
import re
import sys
import yaml
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent
CONCEPTS_DIR = REPO / "site/src/content/docs/concepts"
EXPLORER_GRAPH = REPO / "site/public/assets/explorer_graph.json"
RESEARCH_MAP = REPO / "site/public/assets/research_map_graph.json"
OUT_YAML = REPO / "data/candidate_papers.yaml"
OUT_MD = REPO / "data/candidate_papers_review.md"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_title(t: str) -> str:
    """Lower-case, strip punctuation for fuzzy matching."""
    return re.sub(r"[^a-z0-9 ]", " ", t.lower()).split()


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _doi_key(doi_str: str) -> str:
    """Return bare DOI (10.xxx/...) from a full URL or bare DOI."""
    if not doi_str:
        return ""
    m = re.search(r"(10\.\d{4,}/\S+)", doi_str)
    return m.group(1).rstrip(".").lower() if m else doi_str.lower()


# ── 1. Parse candidate papers from concept markdown files ─────────────────────

CAND_RE = re.compile(
    r"^-\s+(.+?)\.\s+\"(.+?)[.\"]\s*\*(.+?)\*\s*(\d{4})[^—]*—\s*\*\*relevance:\s*(.+?)\*\*",
    re.MULTILINE,
)


def parse_candidate_papers(md_path: Path) -> list[dict]:
    """Return list of candidate paper dicts from a concept markdown file."""
    text = md_path.read_text(encoding="utf-8")
    # Only look inside the candidate papers section
    m = re.search(r"##\s+Candidate papers.*?\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    results = []
    for match in CAND_RE.finditer(block):
        authors_raw, title, journal, year, relevance = match.groups()
        results.append(
            {
                "authors_raw": authors_raw.strip(),
                "title": title.strip(),
                "journal": journal.strip(),
                "year": int(year),
                "relevance": relevance.strip(),
                "doi_candidate": None,  # no DOIs in the markdown lines
            }
        )
    return results


def collect_all_candidates() -> dict[str, list[dict]]:
    """Returns {concept_id: [candidate_dict, ...]} for all concept files."""
    result = {}
    for md in sorted(CONCEPTS_DIR.rglob("*.md")):
        papers = parse_candidate_papers(md)
        if not papers:
            continue
        # Derive concept_id from filename
        concept_id = md.stem.replace("-", "_")
        result[concept_id] = papers
    return result


# ── 2. Build corpus look-ups from explorer_graph.json ─────────────────────────

def load_corpus() -> tuple[dict, dict, list, list]:
    """
    Returns:
        doi_index:   bare_doi → node_dict
        title_index: normalised_title_str → node_dict
        nodes:       list of node dicts (all 15k+)
        adj:         adjacency list (list of sets) indexed by node position
    """
    with open(EXPLORER_GRAPH, encoding="utf-8") as f:
        g = json.load(f)

    fields = g["node_fields"]
    raw_nodes = g["nodes"]
    raw_edges = g["edges"]  # [[src_idx, tgt_idx], ...]

    nodes = [dict(zip(fields, n)) for n in raw_nodes]

    doi_index: dict[str, dict] = {}
    title_index: dict[str, dict] = {}
    for nd in nodes:
        if nd.get("doi"):
            k = _doi_key(nd["doi"])
            if k:
                doi_index[k] = nd
        title_key = nd.get("title", "").lower().strip()
        if title_key:
            title_index[title_key] = nd

    # Build undirected adjacency list (index → set of neighbour indices)
    n = len(nodes)
    adj: list[set] = [set() for _ in range(n)]
    # Build id → index mapping for BFS
    id_to_idx = {nd["id"]: i for i, nd in enumerate(nodes)}

    for src_i, tgt_i in raw_edges:
        if 0 <= src_i < n and 0 <= tgt_i < n:
            adj[src_i].add(tgt_i)
            adj[tgt_i].add(src_i)

    return doi_index, title_index, nodes, adj, id_to_idx


# ── 3. BFS seed distances ─────────────────────────────────────────────────────

def compute_seed_distances(
    adj: list[set],
    id_to_idx: dict[str, int],
    seed_topic_papers: dict[str, list[str]],
    max_hops: int = 4,
) -> dict[int, int]:
    """
    BFS from all seed papers simultaneously (multi-source BFS).
    Returns {node_index: min_hop_distance} for nodes within max_hops.
    """
    dist: dict[int, int] = {}
    queue: deque[tuple[int, int]] = deque()

    for papers in seed_topic_papers.values():
        for pid in papers:
            idx = id_to_idx.get(pid)
            if idx is not None and idx not in dist:
                dist[idx] = 0
                queue.append((idx, 0))

    while queue:
        node, d = queue.popleft()
        if d >= max_hops:
            continue
        for neighbour in adj[node]:
            if neighbour not in dist:
                dist[neighbour] = d + 1
                queue.append((neighbour, d + 1))

    return dist


# ── 4. Match candidate papers to corpus ───────────────────────────────────────

FUZZY_THRESHOLD = 0.82  # SequenceMatcher ratio


def match_paper(
    cand: dict,
    doi_index: dict,
    title_index: dict,
) -> tuple[dict | None, str]:
    """
    Try to find cand in corpus.
    Returns (node_dict_or_None, match_method_str).
    """
    # 1. DOI match (rare — candidate entries don't have DOIs in markdown)
    if cand.get("doi_candidate"):
        k = _doi_key(cand["doi_candidate"])
        nd = doi_index.get(k)
        if nd:
            return nd, "doi"

    # 2. Exact title match
    title_low = cand["title"].lower().strip()
    nd = title_index.get(title_low)
    if nd:
        return nd, "title_exact"

    # 3. Fuzzy title match — only check entries from same approximate year ±3
    year = cand.get("year", 0)
    best_score = 0.0
    best_nd = None
    for corpus_title, corpus_nd in title_index.items():
        cy = corpus_nd.get("year", 0)
        if year and cy and abs(year - cy) > 3:
            continue
        score = _title_similarity(title_low, corpus_title)
        if score > best_score:
            best_score = score
            best_nd = corpus_nd

    if best_score >= FUZZY_THRESHOLD and best_nd is not None:
        return best_nd, f"title_fuzzy({best_score:.2f})"

    return None, "not_found"


# ── 5. Compute co-citation with seeds ─────────────────────────────────────────

def cocitation_with_seeds(
    node_idx: int,
    adj: list[set],
    seed_indices: set[int],
) -> int:
    """
    Count how many seed papers share at least one undirected neighbour with node_idx
    (i.e. papers that co-cite both the candidate and a seed, or that both candidate
    and seed cite).
    """
    if node_idx not in range(len(adj)):
        return 0
    neighbours = adj[node_idx]
    count = 0
    for seed_idx in seed_indices:
        if seed_idx == node_idx:
            continue
        seed_neighbours = adj[seed_idx]
        if neighbours & seed_neighbours:
            count += 1
    return count


# ── 6. Main ───────────────────────────────────────────────────────────────────

def main():
    print("Loading corpus…", file=sys.stderr)
    doi_index, title_index, nodes, adj, id_to_idx = load_corpus()
    print(f"  {len(nodes):,} nodes, {sum(len(s) for s in adj)//2:,} undirected edges", file=sys.stderr)

    print("Loading seed papers…", file=sys.stderr)
    with open(RESEARCH_MAP, encoding="utf-8") as f:
        rm = json.load(f)
    seed_topic_papers: dict[str, list[str]] = rm.get("seed_topic_papers", {})

    print("Running multi-source BFS from seeds…", file=sys.stderr)
    seed_distances = compute_seed_distances(adj, id_to_idx, seed_topic_papers, max_hops=4)
    print(f"  {len(seed_distances):,} nodes reachable within 4 hops", file=sys.stderr)

    seed_indices: set[int] = set()
    for papers in seed_topic_papers.values():
        for pid in papers:
            idx = id_to_idx.get(pid)
            if idx is not None:
                seed_indices.add(idx)
    print(f"  {len(seed_indices)} seed nodes", file=sys.stderr)

    print("Parsing candidate papers from concept files…", file=sys.stderr)
    candidates_by_concept = collect_all_candidates()
    total = sum(len(v) for v in candidates_by_concept.values())
    print(f"  {total} candidate papers across {len(candidates_by_concept)} concepts", file=sys.stderr)

    # Match and annotate
    print("Matching papers to corpus…", file=sys.stderr)
    yaml_output = []
    md_sections = []

    for concept_id, papers in sorted(candidates_by_concept.items()):
        concept_entries = []
        md_rows = []

        for cand in papers:
            matched_nd, match_method = match_paper(cand, doi_index, title_index)

            entry = {
                "title": cand["title"],
                "authors": cand["authors_raw"],
                "journal": cand["journal"],
                "year": cand["year"],
                "relevance": cand["relevance"],
                "corpus_status": match_method,
            }

            if matched_nd is not None:
                nd = matched_nd
                nd_idx = id_to_idx.get(nd["id"])
                seed_hops = seed_distances.get(nd_idx, None) if nd_idx is not None else None
                cocite = (
                    cocitation_with_seeds(nd_idx, adj, seed_indices)
                    if nd_idx is not None
                    else 0
                )

                entry["corpus_id"] = nd["id"]
                entry["corpus_doi"] = nd.get("doi", "")
                entry["corpus_stats"] = {
                    "citation_count": nd.get("citation_count"),
                    "in_degree": nd.get("in_degree"),
                    "out_degree": nd.get("out_degree"),
                    "pagerank_pct": round(float(nd.get("rank_pagerank", 0)) * 100, 1),
                    "kcore": nd.get("kcore"),
                    "core_score": round(float(nd.get("core_score", 0)), 3),
                    "tier": nd.get("tier"),
                    "topic_label": (nd.get("topic_label") or "")[:60],
                    "seed_hops": seed_hops,
                    "cocite_seeds": cocite,
                }

                # Markdown row
                status_icon = "✓" if "exact" in match_method else "~"
                hops_str = str(seed_hops) if seed_hops is not None else "—"
                md_rows.append(
                    f"| {status_icon} | {cand['year']} | {cand['authors_raw'][:30]} | "
                    f"{cand['title'][:55]} | {nd.get('citation_count', '?')} | "
                    f"{nd.get('in_degree', '?')} | {nd.get('out_degree', '?')} | "
                    f"{round(float(nd.get('rank_pagerank', 0)) * 100, 1)}% | "
                    f"{nd.get('kcore', '?')} | {round(float(nd.get('core_score', 0)), 3)} | "
                    f"{hops_str} | {cocite} | {cand['relevance'][:40]} |"
                )
            else:
                md_rows.append(
                    f"| ✗ | {cand['year']} | {cand['authors_raw'][:30]} | "
                    f"{cand['title'][:55]} | — | — | — | — | — | — | — | — | "
                    f"{cand['relevance'][:40]} |"
                )

            concept_entries.append(entry)

        yaml_output.append({"concept": concept_id, "candidates": concept_entries})

        # Build markdown section
        table_header = (
            "| In | Year | Authors | Title | Cites | InDeg | OutDeg | PR% | kcore | CoreScore | "
            "SeedHops | CoSeed | Relevance |\n"
            "|:--:|:----:|:--------|:------|------:|------:|------:|----:|------:|----------:|"
            "---------:|-------:|:----------|\n"
        )
        md_sections.append(
            f"## {concept_id}\n\n" + table_header + "\n".join(md_rows)
        )

    # Write YAML
    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml.dump(
            yaml_output,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    print(f"Written: {OUT_YAML}", file=sys.stderr)

    # Write Markdown
    matched = sum(
        1
        for concept in yaml_output
        for c in concept["candidates"]
        if c["corpus_status"] != "not_found"
    )
    md_content = f"""# Candidate Papers for Expert Review

Generated: 2026-04-09
Corpus: {len(nodes):,} papers · {sum(len(s) for s in adj)//2:,} undirected citation edges
Seed papers: {len(seed_indices)} (review anchors from research_map_graph.json)
Candidate papers: {total} across {len(candidates_by_concept)} concepts
Matched to corpus: {matched}/{total} ({100*matched//total}%)

**Column legend:**
- **In** — corpus match: ✓ exact title, ~ fuzzy match (≥0.82), ✗ not found
- **Cites** — total citation count from metadata
- **InDeg / OutDeg** — within-corpus in/out degree
- **PR%** — PageRank percentile within corpus
- **kcore** — k-core shell number
- **CoreScore** — composite core score (0–1)
- **SeedHops** — BFS hops from nearest seed paper (undirected, max 4)
- **CoSeed** — number of seed papers sharing a citation neighbour

---

"""
    md_content += "\n\n---\n\n".join(md_sections)

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Written: {OUT_MD}", file=sys.stderr)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Candidate paper corpus coverage: {matched}/{total}")
    for concept in yaml_output:
        found = [c for c in concept["candidates"] if c["corpus_status"] != "not_found"]
        print(f"  {concept['concept']}: {len(found)}/{len(concept['candidates'])} matched")


if __name__ == "__main__":
    main()
