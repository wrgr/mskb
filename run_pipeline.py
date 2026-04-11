"""Orchestrate all pipeline stages in sequence from seed governance to expert comms."""

import argparse
import subprocess
import sys
import time
from typing import Callable

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


def _fmt_duration(seconds: float) -> str:
    """Return a compact H:MM:SS / M:SS string for a duration in seconds."""
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _refresh_concept_links(config_path: str) -> None:
    """Refresh concept->paper cache after distillation.

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


def _run_stage(
    stage_num: int,
    total_stages: int,
    label: str,
    fn: Callable[[str], None],
    config_path: str,
    pipeline_start: float,
) -> None:
    """Run a single stage, printing start/finish headers with elapsed times."""
    stage_start = time.monotonic()
    elapsed_before = _fmt_duration(stage_start - pipeline_start)
    print(f"[stage {stage_num}/{total_stages}] {label}  (elapsed {elapsed_before})")
    fn(config_path)
    stage_elapsed = _fmt_duration(time.monotonic() - stage_start)
    total_elapsed = _fmt_duration(time.monotonic() - pipeline_start)
    print(
        f"[stage {stage_num}/{total_stages}] done  "
        f"stage={stage_elapsed}  total={total_elapsed}"
    )


def main(config_path: str) -> None:
    """Run all pipeline stages in sequence for the given config file."""
    pipeline_start = time.monotonic()

    # Stage list (label, callable). Keep the order authoritative here so that
    # the progress counter and total count stay in sync automatically.
    stages: list[tuple[str, Callable[[str], None]]] = [
        ("Seed governance checks", run_seed_governance),
        ("Retrieving corpora", run_retrieve),
        ("Deduplicating and merging", run_merge),
        ("Building graphs", run_graphs),
        ("Computing scores", run_scores),
        ("Discovering topics (Leiden clusters)", run_topics),
        ("Assigning topic evidence (T-codes)", run_topic_evidence),
        ("Selecting core corpus (T1+T2+T3+T4)", run_select_core_corpus),
        ("Backfilling abstracts for selected corpus", run_backfill_abstracts),
        ("Building learner journey", run_learner_journey),
        ("Distilling papers (AI summaries)", run_distill),
        ("Refreshing concept-paper links", _refresh_concept_links),
        ("Updating kid-friendly summaries and topic overviews", run_kid_journey),
        ("Building knowledge graph", run_kg),
        ("Running KB audit gates", run_audit),
        ("Computing visualization metrics", run_viz_metrics),
        ("Generating expert comms review packet", run_expert_comms),
    ]

    total = len(stages)
    for idx, (label, fn) in enumerate(stages, start=1):
        _run_stage(idx, total, label, fn, config_path, pipeline_start)

    total_elapsed = _fmt_duration(time.monotonic() - pipeline_start)
    print(
        f"Pipeline complete in {total_elapsed}.\n"
        "  - Site:          python site/build_site.py --config config.yaml\n"
        "  - Expert report: outputs/expert_comms/expert_comms_report.md"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    main(args.config)
