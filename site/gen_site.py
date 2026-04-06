#!/usr/bin/env python3
"""Generate MkDocs site content from pipeline outputs."""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yaml


def _slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())[:60]


def _difficulty_badge(level: int) -> str:
    labels = {1: "Introductory", 2: "Beginner", 3: "Intermediate", 4: "Advanced", 5: "Specialist"}
    return f"**Difficulty: {labels.get(level, 'Unknown')} ({level}/5)**"


def _paper_card(row: dict) -> str:
    lines = []
    title = row.get("title", "Untitled")
    doi = row.get("doi", "")
    year = row.get("year", "")
    summary = row.get("summary", "")
    why = row.get("why_it_matters", "")
    difficulty = row.get("difficulty", 3)

    lines.append(f"### {title}")
    lines.append("")
    if year:
        lines.append(f"*{year}*")
    lines.append(_difficulty_badge(int(difficulty) if difficulty else 3))
    lines.append("")

    if summary:
        lines.append(f"> {summary}")
        lines.append("")

    takeaways = row.get("key_takeaways", "[]")
    if isinstance(takeaways, str):
        try:
            takeaways = json.loads(takeaways)
        except (json.JSONDecodeError, TypeError):
            takeaways = []
    if takeaways:
        lines.append("**Key takeaways:**")
        lines.append("")
        for t in takeaways:
            lines.append(f"- {t}")
        lines.append("")

    if why:
        lines.append(f"**Why it matters:** {why}")
        lines.append("")

    jargon = row.get("jargon", "[]")
    if isinstance(jargon, str):
        try:
            jargon = json.loads(jargon)
        except (json.JSONDecodeError, TypeError):
            jargon = []
    if jargon:
        lines.append("**Technical terms:**")
        lines.append("")
        for j in jargon:
            if isinstance(j, dict):
                lines.append(f"- **{j.get('term', '')}**: {j.get('definition', '')}")
        lines.append("")

    if doi:
        doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        lines.append(f"[Read the paper]({doi_url})")
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def generate(config_path: str) -> None:
    root = Path(config_path).resolve().parent
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    topics_dir = root / cfg["output_dir"] / "topics"
    distilled_dir = root / cfg["output_dir"] / "distilled"
    site_docs = root / "site" / "docs"

    topics_out = site_docs / "topics"
    topics_out.mkdir(parents=True, exist_ok=True)

    topic_clusters = pd.DataFrame()
    paper_topics = pd.DataFrame()
    paper_summaries = pd.DataFrame()
    topic_overviews = pd.DataFrame()
    reading_paths = pd.DataFrame()

    if (topics_dir / "topic_clusters.csv").exists():
        topic_clusters = pd.read_csv(topics_dir / "topic_clusters.csv")
    if (topics_dir / "paper_topics.csv").exists():
        paper_topics = pd.read_csv(topics_dir / "paper_topics.csv")
    if (distilled_dir / "paper_summaries.csv").exists():
        paper_summaries = pd.read_csv(distilled_dir / "paper_summaries.csv")
    if (distilled_dir / "topic_overviews.csv").exists():
        topic_overviews = pd.read_csv(distilled_dir / "topic_overviews.csv")
    if (distilled_dir / "reading_paths.csv").exists():
        reading_paths = pd.read_csv(distilled_dir / "reading_paths.csv")

    if topic_clusters.empty:
        print("No topic clusters found. Run the pipeline first.")
        return

    # Build summaries lookup
    summaries_map = {}
    if not paper_summaries.empty:
        for _, row in paper_summaries.iterrows():
            summaries_map[row["canonical_paper_id"]] = row.to_dict()

    # Build overview lookup
    overview_map = {}
    if not topic_overviews.empty:
        for _, row in topic_overviews.iterrows():
            overview_map[row["topic_id"]] = row.to_dict()

    # Generate topics index
    index_lines = ["# Topics\n"]
    index_lines.append("Browse the topic clusters discovered from the MS literature.\n")

    category_groups = {}
    for _, cluster in topic_clusters.iterrows():
        cat = cluster.get("dominant_category", "pathogenesis_and_immunology")
        category_groups.setdefault(cat, []).append(cluster)

    # Categories aligned with ACTRIMS / CMSC / MSJ conference structure
    category_labels = {
        "pathogenesis_and_immunology": "Pathogenesis & Immunology",
        "imaging_and_biomarkers": "Imaging & Biomarkers",
        "clinical_trials_and_therapeutics": "Clinical Trials & Therapeutics",
        "clinical_care_and_management": "Clinical Care & Management",
        "epidemiology_and_population_health": "Epidemiology & Population Health",
    }

    for cat in ["pathogenesis_and_immunology", "imaging_and_biomarkers",
                "clinical_trials_and_therapeutics", "clinical_care_and_management",
                "epidemiology_and_population_health"]:
        clusters = category_groups.get(cat, [])
        if not clusters:
            continue
        index_lines.append(f"\n## {category_labels.get(cat, cat)}\n")
        for cluster in clusters:
            if isinstance(cluster, pd.Series):
                cluster = cluster.to_dict()
            tid = cluster["topic_id"]
            label = cluster["auto_label"]
            n = cluster["n_papers"]
            diff = cluster.get("difficulty", 3)
            slug = _slug(label) or f"topic-{tid}"
            index_lines.append(f"- [{label}]({slug}.md) -- {n} papers, difficulty {diff}/5")

    (topics_out / "index.md").write_text("\n".join(index_lines), encoding="utf-8")

    # Generate individual topic pages
    for _, cluster in topic_clusters.iterrows():
        tid = cluster["topic_id"]
        label = cluster["auto_label"]
        slug = _slug(label) or f"topic-{tid}"
        diff = cluster.get("difficulty", 3)
        n = cluster["n_papers"]
        cat = cluster.get("dominant_category", "")

        lines = [f"# {label}\n"]
        lines.append(_difficulty_badge(int(diff)))
        lines.append(f"  |  {n} papers  |  Category: {cat}\n")

        overview = overview_map.get(tid, {})
        if overview.get("overview"):
            lines.append("## Overview\n")
            lines.append(overview["overview"])
            lines.append("")

        # Reading path
        if not reading_paths.empty:
            topic_reading = reading_paths[reading_paths["topic_id"] == tid].sort_values("position")
            if not topic_reading.empty:
                lines.append("## Reading Path\n")
                lines.append("Papers ordered by importance:\n")
                for _, rp in topic_reading.iterrows():
                    pid = rp["canonical_paper_id"]
                    paper_data = summaries_map.get(pid, {"title": rp.get("title", "Untitled")})
                    lines.append(_paper_card(paper_data))

        (topics_out / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")

    # Update nav in mkdocs.yml
    mkdocs_path = root / "site" / "mkdocs.yml"
    if mkdocs_path.exists():
        with open(mkdocs_path, "r") as f:
            mkdocs_cfg = yaml.safe_load(f)

        topic_nav = [{"Overview": "topics/index.md"}]
        for _, cluster in topic_clusters.iterrows():
            label = cluster["auto_label"]
            slug = _slug(label) or f"topic-{cluster['topic_id']}"
            topic_nav.append({label: f"topics/{slug}.md"})

        mkdocs_cfg["nav"] = [
            {"Home": "index.md"},
            {"Getting Started": "getting-started.md"},
            {"Topics": topic_nav},
            {"Glossary": "glossary.md"},
        ]

        with open(mkdocs_path, "w") as f:
            yaml.dump(mkdocs_cfg, f, default_flow_style=False, sort_keys=False)

    print(f"Generated {len(topic_clusters)} topic pages in {topics_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    generate(args.config)
