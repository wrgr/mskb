import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .utils import ensure_dir, load_config, load_downstream_corpus, save_json


def _rank_norm(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if numeric.empty:
        return pd.Series([], dtype=float)
    if float(numeric.max()) <= 0.0:
        return pd.Series(0.0, index=numeric.index, dtype=float)
    return numeric.rank(method="average", pct=True).fillna(0.0).astype(float)


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def _load_topic_mapping(root: Path, output_dir: str, papers: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    topics_dir = root / output_dir / "topics"
    paper_topics_path = topics_dir / "paper_topics.csv"
    topic_clusters_path = topics_dir / "topic_clusters.csv"

    paper_to_topic: dict[str, str] = {}
    topic_labels: dict[str, str] = {}

    if paper_topics_path.exists():
        paper_topics = pd.read_csv(paper_topics_path)
        for _, row in paper_topics.iterrows():
            pid = _safe_text(row.get("canonical_paper_id")).strip()
            tid_raw = _safe_text(row.get("topic_id")).strip()
            if not pid or not tid_raw:
                continue
            tid = f"topic::{tid_raw}"
            paper_to_topic[pid] = tid
        if topic_clusters_path.exists():
            clusters = pd.read_csv(topic_clusters_path)
            for _, row in clusters.iterrows():
                tid_raw = _safe_text(row.get("topic_id")).strip()
                if not tid_raw:
                    continue
                tid = f"topic::{tid_raw}"
                label = _safe_text(row.get("auto_label")).strip() or f"Topic {tid_raw}"
                topic_labels[tid] = label

    # Fallback: derive "topics" from citation community ids when explicit topic clusters are absent.
    if not paper_to_topic:
        for _, row in papers.iterrows():
            pid = _safe_text(row.get("canonical_paper_id")).strip()
            cid = _safe_text(row.get("community_id")).strip()
            if not pid or not cid:
                continue
            tid = f"community::{cid}"
            paper_to_topic[pid] = tid
            topic_labels[tid] = f"Community {cid}"

    for tid in set(paper_to_topic.values()):
        topic_labels.setdefault(tid, tid)

    return paper_to_topic, topic_labels


def _paper_priority(papers: pd.DataFrame) -> pd.Series:
    score_total = _rank_norm(papers.get("score_total", pd.Series(0.0, index=papers.index)))
    importance = _rank_norm(papers.get("paper_importance_score", pd.Series(0.0, index=papers.index)))
    indegree = _rank_norm(papers.get("in_degree", pd.Series(0.0, index=papers.index)))
    return 0.45 * score_total + 0.35 * importance + 0.20 * indegree


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    journey_cfg = cfg.get("learner_journey", {})
    max_next_papers = max(1, int(journey_cfg.get("max_next_papers", 5)))
    max_next_topics = max(1, int(journey_cfg.get("max_next_topics", 3)))
    min_topic_transition_edges = max(1, int(journey_cfg.get("min_topic_transition_edges", 2)))

    root = Path(config_path).resolve().parent
    output_dir = cfg["output_dir"]
    graph_dir = root / output_dir / "graph"
    website_dir = root / output_dir / "website"
    ensure_dir(graph_dir)
    ensure_dir(website_dir)

    papers, papers_path = load_downstream_corpus(graph_dir)
    papers["canonical_paper_id"] = papers["canonical_paper_id"].astype(str)

    paper_ids = set(papers["canonical_paper_id"].astype(str))
    if not paper_ids:
        # Emit empty artifacts to keep downstream behavior deterministic.
        empty_papers = pd.DataFrame(
            columns=[
                "from_paper_id", "to_paper_id", "journey_type", "rank",
                "journey_score", "reason", "from_topic_id", "to_topic_id",
            ]
        )
        empty_topics = pd.DataFrame(
            columns=[
                "from_topic_id", "to_topic_id", "from_topic_label",
                "to_topic_label", "rank", "transition_score", "evidence_edges",
            ]
        )
        empty_membership = pd.DataFrame(columns=["paper_id", "topic_id", "topic_label"])
        empty_papers.to_csv(graph_dir / "learner_journey_papers.csv", index=False)
        empty_topics.to_csv(graph_dir / "learner_journey_topics.csv", index=False)
        empty_membership.to_csv(graph_dir / "learner_topic_membership.csv", index=False)
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "paper_journey": [],
            "topic_journey": [],
        }
        save_json(payload, graph_dir / "learner_journey.json")
        save_json(payload, website_dir / "learner_journey.json")
        print("Stage LJ: No in-scope papers; wrote empty learner journey artifacts.")
        return

    citations_path = graph_dir / "corpus_citation_edges.csv"
    citations = pd.read_csv(citations_path) if citations_path.exists() else pd.DataFrame(
        columns=["source_paper_id", "target_paper_id"]
    )

    outgoing = defaultdict(set)
    incoming = defaultdict(set)
    for _, row in citations.iterrows():
        src = _safe_text(row.get("source_paper_id")).strip()
        dst = _safe_text(row.get("target_paper_id")).strip()
        if not src or not dst or src == dst:
            continue
        if src in paper_ids and dst in paper_ids:
            outgoing[src].add(dst)
            incoming[dst].add(src)

    papers = papers.set_index("canonical_paper_id", drop=False)
    priority = _paper_priority(papers)
    priority_map = priority.to_dict()
    year = pd.to_numeric(papers.get("year", pd.Series(index=papers.index)), errors="coerce").fillna(0.0)
    recency_map = _rank_norm(year).to_dict()
    foundation_map = {pid: 1.0 - recency_map.get(pid, 0.0) for pid in papers.index}

    paper_to_topic, topic_labels = _load_topic_mapping(root, output_dir, papers.reset_index(drop=True))
    topic_membership_rows = []
    for pid in sorted(paper_ids):
        tid = paper_to_topic.get(pid, "")
        if not tid:
            continue
        topic_membership_rows.append(
            {"paper_id": pid, "topic_id": tid, "topic_label": topic_labels.get(tid, tid)}
        )
    topic_membership_df = pd.DataFrame(topic_membership_rows).drop_duplicates()
    topic_membership_df.to_csv(graph_dir / "learner_topic_membership.csv", index=False)

    topic_priority = defaultdict(float)
    topic_counts = Counter()
    for pid in paper_ids:
        tid = paper_to_topic.get(pid)
        if not tid:
            continue
        topic_priority[tid] += float(priority_map.get(pid, 0.0))
        topic_counts[tid] += 1
    for tid, count in topic_counts.items():
        if count > 0:
            topic_priority[tid] /= count

    topic_edge_counts = Counter()
    for src in paper_ids:
        src_topic = paper_to_topic.get(src)
        if not src_topic:
            continue
        for dst in outgoing.get(src, set()):
            dst_topic = paper_to_topic.get(dst)
            if not dst_topic or dst_topic == src_topic:
                continue
            topic_edge_counts[(src_topic, dst_topic)] += 1

    topic_journey_rows = []
    topic_next_map: dict[str, list[dict]] = {}
    topic_transition_groups = defaultdict(list)
    for (src_topic, dst_topic), count in topic_edge_counts.items():
        if count < min_topic_transition_edges:
            continue
        score = 0.7 * float(count) + 0.3 * float(topic_priority.get(dst_topic, 0.0))
        topic_transition_groups[src_topic].append((dst_topic, score, count))

    for src_topic, transitions in topic_transition_groups.items():
        transitions.sort(key=lambda item: item[1], reverse=True)
        chosen = transitions[:max_next_topics]
        topic_next_map[src_topic] = []
        for rank, (dst_topic, score, count) in enumerate(chosen, start=1):
            topic_journey_rows.append(
                {
                    "from_topic_id": src_topic,
                    "to_topic_id": dst_topic,
                    "from_topic_label": topic_labels.get(src_topic, src_topic),
                    "to_topic_label": topic_labels.get(dst_topic, dst_topic),
                    "rank": rank,
                    "transition_score": round(float(score), 6),
                    "evidence_edges": int(count),
                }
            )
            topic_next_map[src_topic].append(
                {
                    "topic_id": dst_topic,
                    "topic_label": topic_labels.get(dst_topic, dst_topic),
                    "transition_score": round(float(score), 6),
                    "evidence_edges": int(count),
                }
            )

    paper_rows = []
    paper_payload = []

    sorted_papers = sorted(paper_ids, key=lambda pid: priority_map.get(pid, 0.0), reverse=True)
    for pid in sorted_papers:
        candidate_scores: dict[str, dict] = {}
        for target in outgoing.get(pid, set()):
            score = 0.70 * priority_map.get(target, 0.0) + 0.30 * foundation_map.get(target, 0.0)
            candidate_scores[target] = {
                "journey_type": "prerequisite",
                "journey_score": score,
                "reason": "Foundational paper cited by this paper.",
            }
        for target in incoming.get(pid, set()):
            score = 0.65 * priority_map.get(target, 0.0) + 0.35 * recency_map.get(target, 0.0)
            existing = candidate_scores.get(target)
            if existing is None or score > existing["journey_score"]:
                candidate_scores[target] = {
                    "journey_type": "followup",
                    "journey_score": score,
                    "reason": "Follow-up paper that cites this paper.",
                }

        ranked = sorted(
            candidate_scores.items(),
            key=lambda item: item[1]["journey_score"],
            reverse=True,
        )[:max_next_papers]

        topic_id = paper_to_topic.get(pid, "")
        next_topics = topic_next_map.get(topic_id, [])
        next_papers_payload = []
        for rank, (target, info) in enumerate(ranked, start=1):
            paper_rows.append(
                {
                    "from_paper_id": pid,
                    "to_paper_id": target,
                    "journey_type": info["journey_type"],
                    "rank": rank,
                    "journey_score": round(float(info["journey_score"]), 6),
                    "reason": info["reason"],
                    "from_topic_id": topic_id,
                    "to_topic_id": paper_to_topic.get(target, ""),
                }
            )
            next_papers_payload.append(
                {
                    "paper_id": target,
                    "title": _safe_text(papers.at[target, "title"]) if target in papers.index else "",
                    "journey_type": info["journey_type"],
                    "journey_score": round(float(info["journey_score"]), 6),
                    "reason": info["reason"],
                }
            )

        paper_payload.append(
            {
                "paper_id": pid,
                "title": _safe_text(papers.at[pid, "title"]) if pid in papers.index else "",
                "topic_id": topic_id,
                "topic_label": topic_labels.get(topic_id, topic_id),
                "next_papers": next_papers_payload,
                "next_topics": next_topics,
            }
        )

    paper_df = pd.DataFrame(paper_rows)
    if paper_df.empty:
        paper_df = pd.DataFrame(
            columns=[
                "from_paper_id", "to_paper_id", "journey_type", "rank",
                "journey_score", "reason", "from_topic_id", "to_topic_id",
            ]
        )
    paper_df.to_csv(graph_dir / "learner_journey_papers.csv", index=False)

    topic_df = pd.DataFrame(topic_journey_rows)
    if topic_df.empty:
        topic_df = pd.DataFrame(
            columns=[
                "from_topic_id", "to_topic_id", "from_topic_label",
                "to_topic_label", "rank", "transition_score", "evidence_edges",
            ]
        )
    topic_df.to_csv(graph_dir / "learner_journey_topics.csv", index=False)

    # Topic summaries include top starter papers to support "where to go next" onboarding.
    topic_to_papers = defaultdict(list)
    for pid in paper_ids:
        tid = paper_to_topic.get(pid, "")
        if not tid:
            continue
        topic_to_papers[tid].append(pid)

    topic_payload = []
    for tid in sorted(topic_to_papers):
        starter_ids = sorted(
            topic_to_papers[tid],
            key=lambda pid: priority_map.get(pid, 0.0),
            reverse=True,
        )[:3]
        starters = [
            {
                "paper_id": pid,
                "title": _safe_text(papers.at[pid, "title"]) if pid in papers.index else "",
                "priority": round(float(priority_map.get(pid, 0.0)), 6),
            }
            for pid in starter_ids
        ]
        topic_payload.append(
            {
                "topic_id": tid,
                "topic_label": topic_labels.get(tid, tid),
                "starter_papers": starters,
                "next_topics": topic_next_map.get(tid, []),
            }
        )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "src/build_learner_journey.py",
        "parameters": {
            "max_next_papers": max_next_papers,
            "max_next_topics": max_next_topics,
            "min_topic_transition_edges": min_topic_transition_edges,
        },
        "paper_journey": paper_payload,
        "topic_journey": topic_payload,
    }
    save_json(payload, graph_dir / "learner_journey.json")
    save_json(payload, website_dir / "learner_journey.json")

    print("Stage LJ: Learner journey complete.")
    print(f"  learner_journey_papers.csv: {graph_dir / 'learner_journey_papers.csv'}")
    print(f"  learner_journey_topics.csv: {graph_dir / 'learner_journey_topics.csv'}")
    print(f"  learner_journey.json: {website_dir / 'learner_journey.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
