
import argparse
import json
import time
from pathlib import Path

import pandas as pd

from .utils import ensure_dir, load_config


DISTILL_PROMPT = """You are helping undergraduate researchers understand a scientific paper about multiple sclerosis.

Paper title: {title}
Year: {year}
Venue: {venue}
Topic cluster: {topic_label}
Abstract: {abstract}

Please provide:
1. A 2-3 sentence plain-English summary suitable for an undergraduate student with basic biology knowledge.
2. Three key takeaways as bullet points.
3. A one-sentence "why this matters" statement connecting this paper to the broader understanding of MS.
4. A difficulty rating from 1 (introductory) to 5 (specialist), based on how much background knowledge is needed to understand this paper.
5. A list of up to 5 technical terms from the abstract that an undergraduate might not know, each with a brief definition.

Respond in JSON format:
{{
  "summary": "...",
  "key_takeaways": ["...", "...", "..."],
  "why_it_matters": "...",
  "difficulty": 3,
  "jargon": [{{"term": "...", "definition": "..."}}, ...]
}}"""

TOPIC_OVERVIEW_PROMPT = """You are creating an overview of a research topic cluster for undergraduate researchers studying multiple sclerosis.

Topic: {topic_label}
Dominant category: {dominant_category}
Number of papers: {n_papers}

Here are the titles and abstracts of the top papers in this cluster:

{paper_summaries}

Write a 2-3 paragraph overview of this topic cluster suitable for undergraduate students. Explain:
1. What this area of MS research is about
2. Why it matters for understanding or treating MS
3. What the key findings and open questions are

Keep the language accessible. Avoid jargon or define it when used."""


def _load_cache(cache_dir: Path, paper_id: str) -> dict | None:
    cache_path = cache_dir / f"{paper_id}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _save_cache(cache_dir: Path, paper_id: str, data: dict) -> None:
    ensure_dir(cache_dir)
    cache_path = cache_dir / f"{paper_id}.json"
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _distill_with_api(client, model: str, prompt: str) -> dict | None:
    try:
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return None
    except Exception as e:
        print(f"  API error: {e}")
        return None


def _rules_based_distill(row: dict) -> dict:
    abstract = str(row.get("abstract", "") or "")
    title = str(row.get("title", "") or "")
    sentences = [s.strip() for s in abstract.replace(". ", ".\n").split("\n") if s.strip()]

    result_indicators = ["we found", "we show", "results demonstrate", "our findings",
                         "we demonstrate", "we report", "we identified", "our results",
                         "these data", "this study", "we observed"]
    key_sentence = sentences[-1] if sentences else ""
    for s in sentences:
        if any(ind in s.lower() for ind in result_indicators):
            key_sentence = s
            break

    summary = f"This paper investigates {title.lower().rstrip('.')}. {key_sentence}"

    takeaways = []
    for s in sentences:
        if any(ind in s.lower() for ind in result_indicators):
            takeaways.append(s)
        if len(takeaways) >= 3:
            break
    if not takeaways and sentences:
        takeaways = sentences[:3]

    year = row.get("year", "")
    venue = row.get("venue", "")
    why = f"This {year} paper in {venue} contributes to our understanding of multiple sclerosis."

    return {
        "summary": summary,
        "key_takeaways": takeaways[:3],
        "why_it_matters": why,
        "difficulty": 3,
        "jargon": [],
    }


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph_dir = root / cfg["output_dir"] / "graph"
    topics_dir = root / cfg["output_dir"] / "topics"
    outdir = root / cfg["output_dir"] / "distilled"
    ensure_dir(outdir)

    dist_cfg = cfg.get("distillation", {})
    cache_dir = root / dist_cfg.get("cache_dir", "outputs/distilled/llm_cache")
    ensure_dir(cache_dir)
    model = dist_cfg.get("model", "claude-haiku-4-5-20251001")
    max_papers = dist_cfg.get("max_papers_per_run", 500)
    batch_size = dist_cfg.get("batch_size", 10)

    scored = pd.read_csv(graph_dir / "scored_papers.csv")
    scored = scored[scored["tier"].isin(["included", "seed_neighbor"])].copy()
    scored = scored.sort_values("paper_importance_score", ascending=False).head(max_papers)

    topic_clusters = pd.DataFrame()
    paper_topics = pd.DataFrame()
    if (topics_dir / "topic_clusters.csv").exists():
        topic_clusters = pd.read_csv(topics_dir / "topic_clusters.csv")
    if (topics_dir / "paper_topics.csv").exists():
        paper_topics = pd.read_csv(topics_dir / "paper_topics.csv")

    topic_labels = {}
    if not topic_clusters.empty:
        topic_labels = dict(zip(topic_clusters["topic_id"], topic_clusters["auto_label"]))

    paper_topic_map = {}
    if not paper_topics.empty:
        paper_topic_map = dict(zip(paper_topics["canonical_paper_id"], paper_topics["topic_id"]))

    # Try to initialize Anthropic client
    api_client = None
    use_api = dist_cfg.get("provider") == "anthropic"
    if use_api:
        try:
            import anthropic
            api_client = anthropic.Anthropic()
            print("Using Claude API for paper distillation.")
        except Exception as e:
            print(f"Could not initialize Anthropic client ({e}). Falling back to rules-based distillation.")
            api_client = None

    summary_rows = []
    for idx, (_, row) in enumerate(scored.iterrows()):
        paper_id = row["canonical_paper_id"]

        cached = _load_cache(cache_dir, paper_id)
        if cached:
            summary_rows.append({
                "canonical_paper_id": paper_id,
                "title": row.get("title", ""),
                "year": row.get("year"),
                "doi": row.get("doi", ""),
                **cached,
            })
            continue

        topic_id = paper_topic_map.get(paper_id)
        topic_label = topic_labels.get(topic_id, "General MS")

        if api_client:
            prompt = DISTILL_PROMPT.format(
                title=row.get("title", ""),
                year=row.get("year", ""),
                venue=row.get("venue", ""),
                topic_label=topic_label,
                abstract=str(row.get("abstract", "") or "")[:3000],
            )
            result = _distill_with_api(api_client, model, prompt)
            if result is None:
                result = _rules_based_distill(row)
        else:
            result = _rules_based_distill(row)

        _save_cache(cache_dir, paper_id, result)
        summary_rows.append({
            "canonical_paper_id": paper_id,
            "title": row.get("title", ""),
            "year": row.get("year"),
            "doi": row.get("doi", ""),
            **result,
        })

        if api_client and (idx + 1) % batch_size == 0:
            time.sleep(1)

        if (idx + 1) % 50 == 0:
            print(f"  Distilled {idx + 1}/{len(scored)} papers")

    summaries_df = pd.DataFrame(summary_rows)
    # Serialize list/dict columns to JSON strings for CSV
    for col in ["key_takeaways", "jargon"]:
        if col in summaries_df.columns:
            summaries_df[col] = summaries_df[col].apply(lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x)
    summaries_df.to_csv(outdir / "paper_summaries.csv", index=False)

    # Generate topic overviews
    if not topic_clusters.empty:
        overview_rows = []
        for _, cluster in topic_clusters.iterrows():
            tid = cluster["topic_id"]
            cluster_papers = scored[scored["canonical_paper_id"].isin(
                paper_topics[paper_topics["topic_id"] == tid]["canonical_paper_id"]
            )].head(5)

            if api_client and not cluster_papers.empty:
                paper_summaries_text = ""
                for _, p in cluster_papers.iterrows():
                    paper_summaries_text += f"Title: {p.get('title', '')}\nAbstract: {str(p.get('abstract', '') or '')[:500]}\n\n"

                prompt = TOPIC_OVERVIEW_PROMPT.format(
                    topic_label=cluster["auto_label"],
                    dominant_category=cluster.get("dominant_category", ""),
                    n_papers=cluster["n_papers"],
                    paper_summaries=paper_summaries_text,
                )
                try:
                    message = api_client.messages.create(
                        model=model,
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    overview_text = message.content[0].text
                except Exception as e:
                    overview_text = f"This topic cluster covers {cluster['auto_label']} and contains {cluster['n_papers']} papers."
            else:
                overview_text = f"This topic cluster covers {cluster['auto_label']} and contains {cluster['n_papers']} papers."

            overview_rows.append({
                "topic_id": tid,
                "auto_label": cluster["auto_label"],
                "overview": overview_text,
                "n_papers": cluster["n_papers"],
                "difficulty": cluster.get("difficulty", 3),
                "dominant_category": cluster.get("dominant_category", ""),
            })

        pd.DataFrame(overview_rows).to_csv(outdir / "topic_overviews.csv", index=False)

    # Generate reading paths
    reading_rows = []
    if not paper_topics.empty:
        for tid in paper_topics["topic_id"].unique():
            topic_paper_ids = set(paper_topics[paper_topics["topic_id"] == tid]["canonical_paper_id"])
            topic_papers = scored[scored["canonical_paper_id"].isin(topic_paper_ids)].copy()
            topic_papers = topic_papers.sort_values("paper_importance_score", ascending=False)
            for pos, (_, p) in enumerate(topic_papers.iterrows()):
                reading_rows.append({
                    "topic_id": int(tid),
                    "position": pos + 1,
                    "canonical_paper_id": p["canonical_paper_id"],
                    "title": p.get("title", ""),
                    "paper_importance_score": p.get("paper_importance_score", 0.0),
                })

    if reading_rows:
        pd.DataFrame(reading_rows).to_csv(outdir / "reading_paths.csv", index=False)

    print(f"Distilled {len(summary_rows)} papers. Outputs in {outdir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
