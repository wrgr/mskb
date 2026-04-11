"""Assign topic codes using an evidence ladder with graph-neighborhood seed support."""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from .utils import ensure_dir, load_config, save_json

_TOPIC_CODE_RE = re.compile(r"^(TOPIC-\d{2}|T\d+b?)", re.IGNORECASE)
_REVIEW_ANCHOR_TOPIC_OVERRIDES = {
    # R4 biomarker framing review should map to the biomarker topic rather than REVIEW_CLUSTER.
    "10.1016/s1474-4422(25)00249-2": "TOPIC-07",
}


def _normalize_doi(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text or text == "nan":
        return ""
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    return text.strip()


def _normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _extract_topic_code(value: object) -> str:
    text = str(value or "").strip()
    match = _TOPIC_CODE_RE.match(text)
    if not match:
        return ""
    code = match.group(1).strip()
    # Normalize to canonical style used by topic_map/seeds.
    if code.upper().startswith("TOPIC-"):
        return code.upper()
    return code


def _parse_topics_covered(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return []
    parts = [p.strip() for p in text.split(",")]
    out: list[str] = []
    for part in parts:
        code = _extract_topic_code(part)
        if code and code not in out:
            out.append(code)
    return out


def _review_anchor_override_topic(row: pd.Series) -> str:
    doi_norm = _normalize_doi(row.get("doi", ""))
    return str(_REVIEW_ANCHOR_TOPIC_OVERRIDES.get(doi_norm, "")).strip().upper()


def _has_complete_assignment_metadata(row: pd.Series) -> bool:
    title = str(row.get("title", "") or "").strip()
    abstract = str(row.get("abstract", "") or "").strip()
    doi_norm = _normalize_doi(row.get("doi", ""))
    if not title or title.lower() == "nan":
        return False
    if not abstract or abstract.lower() == "nan":
        return False
    if not doi_norm or not doi_norm.startswith("10.") or "/" not in doi_norm:
        return False
    return True


def _build_bidirectional_adjacency(edges: pd.DataFrame) -> dict[str, set[str]]:
    neighbors: dict[str, set[str]] = defaultdict(set)
    for _, row in edges.iterrows():
        src = str(row.get("source_paper_id", "") or "").strip()
        dst = str(row.get("target_paper_id", "") or "").strip()
        if not src or not dst or src == dst:
            continue
        neighbors[src].add(dst)
        neighbors[dst].add(src)
    return neighbors


def _topic_codes_from_map(topic_map_path: Path) -> list[str]:
    if not topic_map_path.exists():
        return []
    try:
        data = json.loads(topic_map_path.read_text())
    except Exception:
        return []
    out: list[str] = []
    for row in data.get("topics", []):
        code = str(row.get("topic_code", "") or "").strip()
        if code and code not in out:
            out.append(code)
    return out


def _topic_prototypes(topic_map_path: Path, core_seeds: pd.DataFrame) -> dict[str, str]:
    prototypes: dict[str, list[str]] = defaultdict(list)
    if topic_map_path.exists():
        try:
            data = json.loads(topic_map_path.read_text())
            for row in data.get("topics", []):
                code = str(row.get("topic_code", "") or "").strip()
                if not code:
                    continue
                name = str(row.get("topic_name", "") or "").strip()
                why = str(row.get("why_it_matters", "") or "").strip()
                if name:
                    prototypes[code].append(name)
                if why:
                    prototypes[code].append(why)
        except Exception:
            pass
    for _, row in core_seeds.iterrows():
        code = _extract_topic_code(row.get("primary_topic", ""))
        title = str(row.get("title", "") or "").strip()
        rationale = str(row.get("rationale", "") or "").strip()
        if not code:
            continue
        if title:
            prototypes[code].append(title)
        if rationale:
            prototypes[code].append(rationale)
    return {code: " ".join(parts).strip().lower() for code, parts in prototypes.items() if parts}


def _choose_primary_secondary(topic_scores: Counter) -> tuple[str, list[str]]:
    if not topic_scores:
        return "", []
    ranked = sorted(topic_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    primary = ranked[0][0]
    best = float(ranked[0][1])
    secondary = [topic for topic, score in ranked[1:] if score >= 0.7 * best and score > 0]
    return primary, secondary


def _seed_topic_support_by_hops(
    pid: str,
    neighbors: dict[str, set[str]],
    core_pid_topics: dict[str, set[str]],
    anchor_pid_topics: dict[str, set[str]],
    max_hops: int = 3,
) -> tuple[Counter, Counter, Counter, Counter, int, int]:
    """Accumulate topic support from graph neighborhood around a paper.

    Returns:
      - weighted core-seed topic support (all hops <= max_hops)
      - weighted framing-anchor topic support (all hops <= max_hops)
      - direct (1-hop) core-seed topic support
      - direct (1-hop) framing-anchor topic support
      - nearest hop distance to any core-seed topic
      - nearest hop distance to any anchor topic
    """
    if max_hops <= 0:
        return Counter(), Counter(), Counter(), Counter(), -1, -1

    # Strong local signal, progressively weaker with distance.
    core_hop_weights = {1: 1.0, 2: 0.65, 3: 0.40}
    anchor_hop_weights = {1: 0.85, 2: 0.50, 3: 0.30}

    core_support: Counter = Counter()
    anchor_support: Counter = Counter()
    direct_core_support: Counter = Counter()
    direct_anchor_support: Counter = Counter()
    nearest_core_hop = -1
    nearest_anchor_hop = -1

    visited = {pid}
    frontier = {pid}
    for hop in range(1, max_hops + 1):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for node in frontier:
            for nbr in neighbors.get(node, set()):
                if nbr in visited:
                    continue
                visited.add(nbr)
                next_frontier.add(nbr)
                core_topics = core_pid_topics.get(nbr, set())
                if core_topics:
                    weight = core_hop_weights.get(hop, core_hop_weights[max(core_hop_weights)])
                    for code in core_topics:
                        core_support[code] += weight
                        if hop == 1:
                            direct_core_support[code] += 1
                    if nearest_core_hop < 0:
                        nearest_core_hop = hop
                anchor_topics = anchor_pid_topics.get(nbr, set())
                if anchor_topics:
                    weight = anchor_hop_weights.get(hop, anchor_hop_weights[max(anchor_hop_weights)])
                    for code in anchor_topics:
                        anchor_support[code] += weight
                        if hop == 1:
                            direct_anchor_support[code] += 1
                    if nearest_anchor_hop < 0:
                        nearest_anchor_hop = hop
        frontier = next_frontier
    return (
        core_support,
        anchor_support,
        direct_core_support,
        direct_anchor_support,
        nearest_core_hop,
        nearest_anchor_hop,
    )


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph_dir = root / cfg["output_dir"] / "graph"
    topics_dir = root / cfg["output_dir"] / "topics"
    ensure_dir(topics_dir)

    scored_path = graph_dir / "scored_papers.csv"
    edges_path = graph_dir / "corpus_citation_edges.csv"
    if not scored_path.exists() or not edges_path.exists():
        raise FileNotFoundError("Missing scored_papers.csv or corpus_citation_edges.csv")

    scored = pd.read_csv(scored_path, low_memory=False)
    scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
    scoped = scored[scored["tier"].astype(str).isin(["included", "seed_neighbor"])].copy()
    scoped["doi_norm"] = scoped.get("doi", pd.Series("", index=scoped.index)).apply(_normalize_doi)
    scoped["is_core_seed"] = scoped.get("is_core_seed", pd.Series(False, index=scoped.index)).fillna(False).astype(bool)
    edges = pd.read_csv(edges_path)
    neighbors = _build_bidirectional_adjacency(edges)

    core_seeds = pd.read_csv(root / "seeds" / "core_seeds.csv")
    core_seeds["doi_norm"] = core_seeds["doi"].apply(_normalize_doi)
    core_seeds["topic_code"] = core_seeds["primary_topic"].apply(_extract_topic_code)
    core_seeds["title_norm"] = core_seeds["title"].apply(_normalize_text)
    core_seeds = core_seeds[core_seeds["doi_norm"] != ""].copy()

    framing = pd.read_csv(root / "seeds" / "framing_seeds.csv")
    framing["doi_norm"] = framing["doi"].apply(_normalize_doi)
    framing["topic_codes"] = framing["topics_covered"].apply(_parse_topics_covered)
    framing = framing[framing["doi_norm"] != ""].copy()

    doi_to_pid: dict[str, set[str]] = defaultdict(set)
    for _, row in scoped.iterrows():
        doi_norm = row["doi_norm"]
        pid = str(row["canonical_paper_id"])
        if doi_norm:
            doi_to_pid[doi_norm].add(pid)

    core_pid_topics: dict[str, set[str]] = defaultdict(set)
    doi_seed_topics: dict[str, set[str]] = defaultdict(set)
    core_doi_topics: dict[str, set[str]] = defaultdict(set)
    core_title_topics: dict[str, set[str]] = defaultdict(set)
    for _, row in core_seeds.iterrows():
        for pid in doi_to_pid.get(row["doi_norm"], set()):
            code = str(row.get("topic_code", "") or "").strip()
            if code:
                core_pid_topics[pid].add(code)
        code = str(row.get("topic_code", "") or "").strip()
        doi_norm = str(row.get("doi_norm", "") or "").strip()
        if code and doi_norm:
            doi_seed_topics[doi_norm].add(code)
            core_doi_topics[doi_norm].add(code)
        title_norm = str(row.get("title_norm", "") or "").strip()
        if code and title_norm:
            core_title_topics[title_norm].add(code)

    anchor_pid_topics: dict[str, set[str]] = defaultdict(set)
    for _, row in framing.iterrows():
        for pid in doi_to_pid.get(row["doi_norm"], set()):
            for code in row.get("topic_codes", []) or []:
                if code:
                    anchor_pid_topics[pid].add(code)

    topic_map_path = root / "data" / "topic_map.json"
    prototypes = _topic_prototypes(topic_map_path, core_seeds)
    known_topic_codes = _topic_codes_from_map(topic_map_path)

    assignments: list[dict] = []
    method_counts: Counter = Counter()

    for _, row in scoped.iterrows():
        pid = str(row["canonical_paper_id"])
        title = str(row.get("title", "") or "")
        abstract = str(row.get("abstract", "") or "")
        concepts = str(row.get("concepts", "") or "")
        topics = str(row.get("topics", "") or "")
        text = f"{title} {abstract} {concepts} {topics}".strip().lower()
        (
            seed_support,
            anchor_support,
            direct_seed_support,
            direct_anchor_support,
            nearest_seed_hop,
            nearest_anchor_hop,
        ) = _seed_topic_support_by_hops(
            pid,
            neighbors,
            core_pid_topics,
            anchor_pid_topics,
            max_hops=3,
        )

        method = ""
        confidence = 0.0
        primary = ""
        secondary: list[str] = []
        lexical_scores: dict[str, float] = {}
        weak_assignment = False
        weak_reason = ""
        topic_cluster = "TOPIC_DOMAIN"
        t4_codes = _parse_topics_covered(row.get("t4_topic_code", ""))
        is_t4 = _boolish(row.get("in_t4_expert_signal", False))
        is_core_seed = _boolish(row.get("is_core_seed", False))
        is_review_anchor_source = _boolish(row.get("is_review_anchor_source", False))
        review_anchor_override_topic = _review_anchor_override_topic(row)

        # T1 is explicit and should always retain its mapped topic.
        explicit_core_topics = set(core_pid_topics.get(pid, set()))
        if is_core_seed and not explicit_core_topics:
            # Fallback: recover from seed DOI lineage when canonical-DOI join is incomplete.
            for doi in str(row.get("seed_doi", "") or "").split(";"):
                doi_norm = _normalize_doi(doi)
                explicit_core_topics.update(core_doi_topics.get(doi_norm, set()))
            if not explicit_core_topics:
                explicit_core_topics.update(core_title_topics.get(_normalize_text(title), set()))

        if is_core_seed and explicit_core_topics:
            method = "core_seed"
            primary, secondary = _choose_primary_secondary(Counter({code: 1.0 for code in explicit_core_topics}))
            confidence = 1.0
        elif is_t4 and t4_codes:
            # T4 has explicit topic links in curation metadata; preserve these assignments.
            method = "t4_explicit_topic"
            primary = t4_codes[0]
            secondary = t4_codes[1:]
            confidence = 0.9
        elif is_review_anchor_source and review_anchor_override_topic:
            # Targeted override for review anchors that should resolve to a specific topic.
            method = "review_anchor_seed_topic"
            primary = review_anchor_override_topic
            ranked = Counter(seed_support or direct_seed_support)
            ranked.pop(primary, None)
            secondary = [topic for topic, _ in sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]
            if direct_seed_support.get(primary, 0) > 0:
                confidence = 0.9
            elif seed_support.get(primary, 0) > 0:
                confidence = 0.75
            else:
                confidence = 0.6
            topic_cluster = "TOPIC_DOMAIN"
        elif is_review_anchor_source:
            # Review-anchor source papers are cross-sectional by design; keep in review cluster.
            method = "review_cross_sectional"
            primary = ""
            secondary = []
            confidence = 0.0
            topic_cluster = "REVIEW_CLUSTER"
        elif direct_seed_support:
            method = "seed_link"
            primary, secondary = _choose_primary_secondary(direct_seed_support)
            confidence = min(
                0.98,
                0.55 + 0.15 * max(direct_seed_support.values()) + 0.03 * sum(direct_seed_support.values()),
            )
        elif seed_support:
            method = "graph_seed_neighborhood"
            primary, secondary = _choose_primary_secondary(seed_support)
            # Indirect seed evidence is useful but weaker than direct links.
            confidence = min(0.80, 0.40 + 0.12 * max(seed_support.values()) + 0.03 * sum(seed_support.values()))
        else:
            for code, proto in prototypes.items():
                if not proto or not text:
                    continue
                lexical_scores[code] = float(fuzz.token_set_ratio(text, proto)) / 100.0
            if lexical_scores:
                ranked = sorted(lexical_scores.items(), key=lambda kv: (-kv[1], kv[0]))
                top_code, top_score = ranked[0]
                if top_score >= 0.36:
                    method = "lexical_prototype"
                    primary = top_code
                    secondary = [code for code, score in ranked[1:] if score >= 0.95 * top_score and score >= 0.36]
                    confidence = min(0.72, top_score)
                else:
                    method = "unassigned"
            else:
                method = "unassigned"

        # If still unresolved, fall back to seeded hints and flag weak assignment.
        if method == "unassigned":
            seeded_hint_scores: Counter = Counter()
            for doi in str(row.get("seed_doi", "") or "").split(";"):
                doi_norm = _normalize_doi(doi)
                for code in doi_seed_topics.get(doi_norm, set()):
                    seeded_hint_scores[code] += 1.0

            t4_codes = _parse_topics_covered(row.get("t4_topic_code", ""))
            for code in t4_codes:
                seeded_hint_scores[code] += 0.8

            if seeded_hint_scores:
                method = "seeded_hint_weak"
                primary, secondary = _choose_primary_secondary(seeded_hint_scores)
                confidence = 0.25
                weak_assignment = True
                weak_reason = "seeded_topic_hint_only"

        # Last-resort weak assignment: preserve topic coverage when metadata is complete.
        if method == "unassigned" and lexical_scores and _has_complete_assignment_metadata(row):
            ranked = sorted(lexical_scores.items(), key=lambda kv: (-kv[1], kv[0]))
            top_code, top_score = ranked[0]
            method = "lexical_prototype_weak"
            primary = top_code
            secondary = [code for code, score in ranked[1:] if score >= 0.95 * top_score and score >= 0.30]
            confidence = min(0.35, max(0.2, top_score * 0.75))
            weak_assignment = True
            weak_reason = "lexical_below_threshold_metadata_complete"

        method_counts[method] += 1
        if method == "unassigned":
            primary = ""
            secondary = []
            confidence = 0.0

        assignments.append(
            {
                "canonical_paper_id": pid,
                "primary_topic_code": primary,
                "secondary_topic_codes": json.dumps(secondary),
                "topic_assignment_method": method,
                "topic_assignment_confidence": round(float(confidence), 4),
                "topic_assignment_weak": bool(weak_assignment),
                "topic_assignment_weak_reason": weak_reason,
                "topic_cluster": topic_cluster,
                "n_core_seed_links": int(sum(direct_seed_support.values())),
                "n_review_anchor_links": int(sum(direct_anchor_support.values())),
                "nearest_core_seed_hop": int(nearest_seed_hop),
                "nearest_review_anchor_hop": int(nearest_anchor_hop),
                "direct_seed_support_by_topic": json.dumps(dict(direct_seed_support)),
                "direct_anchor_support_by_topic": json.dumps(dict(direct_anchor_support)),
                "seed_support_by_topic": json.dumps(dict(seed_support)),
                "anchor_support_by_topic": json.dumps(dict(anchor_support)),
                "lexical_scores_by_topic": json.dumps({k: round(v, 4) for k, v in lexical_scores.items()}),
            }
        )

    out = pd.DataFrame(assignments)
    out.to_csv(topics_dir / "paper_topic_evidence.csv", index=False)

    summary = {
        "n_scoped_papers": int(len(scoped)),
        "n_assigned_primary": int((out["primary_topic_code"].astype(str) != "").sum()),
        "n_unassigned": int((out["topic_assignment_method"] == "unassigned").sum()),
        "n_review_cluster": int((out.get("topic_cluster", pd.Series("", index=out.index)) == "REVIEW_CLUSTER").sum()),
        "n_weak_assigned": int(out.get("topic_assignment_weak", pd.Series(False, index=out.index)).fillna(False).astype(bool).sum()),
        "topic_code_format": "TOPIC-## only",
        "method_counts": {k: int(v) for k, v in method_counts.items()},
        "known_topic_codes": known_topic_codes,
    }
    save_json(summary, topics_dir / "paper_topic_evidence_summary.json")
    print(f"paper_topic_evidence.csv: {topics_dir / 'paper_topic_evidence.csv'}")
    print(f"paper_topic_evidence_summary.json: {topics_dir / 'paper_topic_evidence_summary.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
