"""Orchestrate all pipeline stages in sequence from seed governance to expert comms."""

import argparse
import subprocess
import sys

from src.audit_kb import run as run_audit
from src.assign_topic_evidence import run as run_topic_evidence
from src.backfill_abstracts import run as run_backfill_abstracts
from src.build_graphs import run as run_graphs
from src.build_knowledge_graph import run as run_kg
from src.build_learner_journey import run as run_learner_journey
from src.compute_scores import run as run_scores
from src.compute_viz_metrics import run as run_viz_metrics
from src.deduplicate_and_merge import run as run_merge
from src.discover_topics import run as run_topics
from src.distill_papers import run as run_distill
from src.expert_comms import run as run_expert_comms
from src.retrieve_corpora import run as run_retrieve
from src.select_core_corpus import run as run_select_core_corpus
from src.seed_governance import run as run_seed_governance
from update_kid_journey import run as run_kid_journey


def _refresh_concept_links(config_path: str) -> None:
    """Refresh concept→paper cache after distillation.

    link_concepts_to_papers.py expects to run from the repo root and uses
    relative paths for concept files and corpus outputs, so it is invoked
    as a subprocess rather than imported directly.
    """
    result = subprocess.run(
        [
            sys.executable,
            "src/link_concepts_to_papers.py",
            "--config",
            config_path,
            "--refresh",
        ],
        check=False,
    )
    if result.returncode != 0:
        print(
            f"[warn] link_concepts_to_papers exited with code {result.returncode}; "
            "concept-paper cache may be stale. Re-run manually: "
            "python src/link_concepts_to_papers.py --config config.yaml --refresh"
        )


def main(config_path: str) -> None:
    """Run all pipeline stages in sequence for the given config file."""
    print("Stage 0/10: Seed governance checks...")
    run_seed_governance(config_path)

    print("Stage 1/10: Retrieving corpora...")
    run_retrieve(config_path)

    print("Stage 2/10: Deduplicating and merging...")
    run_merge(config_path)

    print("Stage 3/10: Building graphs...")
    run_graphs(config_path)

    print("Stage 4/10: Computing scores...")
    run_scores(config_path)

    print("Stage 5/10: Discovering topics (Leiden clusters)...")
    run_topics(config_path)

    print("Stage 5b/10: Assigning topic evidence (T-codes)...")
    run_topic_evidence(config_path)

    print("Stage 5c/10: Selecting core corpus (T1+T2+T3+T4)...")
    run_select_core_corpus(config_path)

    print("Stage 5d/10: Backfilling abstracts for selected corpus...")
    run_backfill_abstracts(config_path)

    print("Stage 6/10: Building learner journey...")
    run_learner_journey(config_path)

    print("Stage 7/10: Distilling papers (AI summaries)...")
    run_distill(config_path)

    print("Stage 7b/10: Refreshing concept-paper links...")
    _refresh_concept_links(config_path)

    print("Stage 7c/10: Updating kid-friendly summaries and topic overviews...")
    run_kid_journey(config_path)

    print("Stage 8/10: Building knowledge graph...")
    run_kg(config_path)

    print("Stage 9/10: Running KB audit gates...")
    run_audit(config_path)

    print("Stage 9b/10: Computing visualization metrics...")
    run_viz_metrics(config_path)

    print("Stage 10/10: Generating expert comms review packet...")
    run_expert_comms(config_path)

    print(
        "Pipeline complete.\n"
        "  - Site:          python site/build_site.py --config config.yaml\n"
        "  - Expert report: outputs/expert_comms/expert_comms_report.md"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    main(args.config)
