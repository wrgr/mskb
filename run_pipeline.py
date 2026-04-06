
import argparse

from src.build_graphs import run as run_graphs
from src.build_knowledge_graph import run as run_kg
from src.compute_scores import run as run_scores
from src.deduplicate_and_merge import run as run_merge
from src.discover_topics import run as run_topics
from src.distill_papers import run as run_distill
from src.retrieve_corpora import run as run_retrieve


def main(config_path: str) -> None:
    print("Stage 1/7: Retrieving corpora...")
    run_retrieve(config_path)

    print("Stage 2/7: Deduplicating and merging...")
    run_merge(config_path)

    print("Stage 3/7: Building graphs...")
    run_graphs(config_path)

    print("Stage 4/7: Computing scores...")
    run_scores(config_path)

    print("Stage 5/7: Discovering topics...")
    run_topics(config_path)

    print("Stage 6/7: Distilling papers...")
    run_distill(config_path)

    print("Stage 7/7: Building knowledge graph...")
    run_kg(config_path)

    print("Pipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    main(args.config)
