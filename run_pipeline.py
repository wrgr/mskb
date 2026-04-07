
import argparse

from src.audit_kb import run as run_audit
from src.backfill_abstracts import run as run_backfill_abstracts
from src.build_graphs import run as run_graphs
from src.build_knowledge_graph import run as run_kg
from src.build_learner_journey import run as run_learner_journey
from src.compute_scores import run as run_scores
from src.deduplicate_and_merge import run as run_merge
from src.discover_topics import run as run_topics
from src.distill_papers import run as run_distill
from src.retrieve_corpora import run as run_retrieve
from src.seed_governance import run as run_seed_governance


def main(config_path: str) -> None:
    print("Stage 0/8: Seed governance checks...")
    run_seed_governance(config_path)

    print("Stage 1/8: Retrieving corpora...")
    run_retrieve(config_path)

    print("Stage 2/8: Deduplicating and merging...")
    run_merge(config_path)

    print("Stage 2b/8: Backfilling missing abstracts...")
    run_backfill_abstracts(config_path)

    print("Stage 3/8: Building graphs...")
    run_graphs(config_path)

    print("Stage 4/8: Computing scores...")
    run_scores(config_path)

    print("Stage 5/8: Discovering topics...")
    run_topics(config_path)

    print("Stage 6/9: Building learner journey...")
    run_learner_journey(config_path)

    print("Stage 7/9: Distilling papers...")
    run_distill(config_path)

    print("Stage 8/9: Building knowledge graph...")
    run_kg(config_path)

    print("Stage 9/9: Running KB audit gates...")
    run_audit(config_path)

    print("Pipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    main(args.config)
