"""Assign topic codes using an evidence ladder: seed links, anchor links, then lexical prototype match."""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from .utils import ensure_dir, load_config, save_json

_TOPIC_CODE_RE = re.compile(r"^(T\d+b?)")


def _normalize_doi(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text or text == "nan":
        return ""
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    return text.strip()


def _extract_topic_code(value: object) -> str:
    text = str(value or "").strip()
    match = _TOPIC_CODE_RE.match(text)
    return match.group(1) if match else ""


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
    for _, row in core_seeds.iterrows():
        for pid in doi_to_pid.get(row["doi_norm"], set()):
            code = str(row.get("topic_code", "") or "").strip()
            if code:
                core_pid_topics[pid].add(code)

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
        linked = neighbors.get(pid, set())

        seed_support: Counter = Counter()
        for sid in linked:
            for code in core_pid_topics.get(sid, set()):
                seed_support[code] += 1

        anchor_support: Counter = Counter()
        for aid in linked:
            for code in anchor_pid_topics.get(aid, set()):
                anchor_support[code] += 1

        method = ""
        confidence = 0.0
        primary = ""
        secondary: list[str] = []
        lexical_scores: dict[str, float] = {}

        # T1 is explicit.
        if bool(row.get("is_core_seed", False)) and core_pid_topics.get(pid):
            method = "core_seed"
            primary, secondary = _choose_primary_secondary(seed_support or Counter({next(iter(core_pid_topics[pid])): 1}))
            confidence = 1.0
        elif seed_support:
            method = "seed_link"
            primary, secondary = _choose_primary_secondary(seed_support)
            confidence = min(0.98, 0.55 + 0.15 * max(seed_support.values()) + 0.03 * sum(seed_support.values()))
        elif anchor_support:
            method = "review_anchor_link"
            primary, secondary = _choose_primary_secondary(anchor_support)
            confidence = min(0.85, 0.45 + 0.10 * max(anchor_support.values()) + 0.03 * sum(anchor_support.values()))
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
                "n_core_seed_links": int(sum(seed_support.values())),
                "n_review_anchor_links": int(sum(anchor_support.values())),
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
