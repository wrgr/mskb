#!/usr/bin/env python3
"""One-pass script to generate or refresh kid-friendly (age-12) summaries.

Run this whenever the underlying corpus advances to regenerate kid-level plain
language abstracts for all papers and topic overviews.

Usage
-----
    python update_kid_journey.py --config config.yaml            # skip already-cached
    python update_kid_journey.py --config config.yaml --force    # regenerate all

Outputs updated in place
------------------------
- outputs/distilled/paper_summaries.csv   (adds/updates summary_kid, key_takeaways_kid,
                                            why_it_matters_kid, jargon_kid columns)
- outputs/distilled/topic_overviews.csv   (adds/updates overview_kid column)
- outputs/distilled/llm_cache/            (per-paper kid-level JSON cache files)

After running this script, re-run site generation to publish the changes:
    cd site && python gen_site.py --config ../config.yaml && npm run build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Re-use helpers from the main distillation module so behaviour is identical.
from src.distill_papers import (
    DISTILL_PROMPT,
    TOPIC_ABSTRACT_PREVIEW_CHARS,
    TOPIC_OVERVIEW_PROMPT_KID,
    _cache_path,
    _clean_text,
    _clean_jargon_list,
    _coerce_int,
    _context_from_row,
    _disclaimer_for_source,
    _distill_with_api,
    _faithfulness_overlap,
    _GeminiClientShim,
    _init_api_client,
    _load_cache,
    _load_fulltext_maps,
    _normalize_reading_level,
    _parse_json_list,
    _reading_level_guide,
    _reading_level_numeric,
    _repair_why_it_matters,
    _rules_based_distill,
    _safe_float,
    _sanitize_distill_result,
    _save_cache,
    _certainty_from_signals,
    LLM_MAX_TOKENS,
    PROMPT_SOURCE_TEXT_MAX_CHARS,
)
from src.utils import ensure_dir, load_config


KID_LEVEL = "kid"


def _distill_kid(
    *,
    api_client,
    model: str,
    cache_dir: Path,
    paper_row: dict,
    paper_id: str,
    topic_label: str,
    source_text: str,
    source_type: str,
    source_hash: str,
    generated_at_utc: str,
    force: bool = False,
) -> dict:
    """Return a sanitised kid-level distillation result, using the cache when available."""
    if not force:
        cached = _load_cache(cache_dir, paper_id, KID_LEVEL)
        if cached and cached.get("source_text_hash") == source_hash and _normalize_reading_level(
            cached.get("reading_level_target"), default=KID_LEVEL
        ) == KID_LEVEL:
            cached = _sanitize_distill_result(cached, reading_level=KID_LEVEL)
            cached["distill_method"] = _clean_text(cached.get("distill_method", "")) or "cache"
            overlap = _faithfulness_overlap(
                _clean_text(cached.get("summary", "")),
                _parse_json_list(cached.get("key_takeaways", [])),
                source_text,
            )
            certainty_score, certainty_label = _certainty_from_signals(
                source_type=source_type,
                source_chars=len(source_text),
                method=str(cached.get("distill_method", "cache")),
                overlap=overlap,
            )
            cached.update({
                "summary_source": source_type,
                "source_text_hash": source_hash,
                "source_text_chars": len(source_text),
                "summary_generated_at_utc": _clean_text(cached.get("summary_generated_at_utc", "")) or generated_at_utc,
                "faithfulness_overlap": overlap,
                "summary_certainty_score": certainty_score,
                "summary_certainty_label": certainty_label,
                "summary_disclaimer": _disclaimer_for_source(source_type, certainty_label),
            })
            return cached

    distill_method = "rules_based"
    if api_client:
        prompt = DISTILL_PROMPT.format(
            reading_level_guide=_reading_level_guide(KID_LEVEL),
            title=paper_row.get("title", ""),
            year=paper_row.get("year", ""),
            venue=paper_row.get("venue", ""),
            topic_label=topic_label,
            abstract=f"[{source_type}] {source_text[:PROMPT_SOURCE_TEXT_MAX_CHARS]}",
        )
        api_result = _distill_with_api(api_client, model, prompt)
        if api_result is not None:
            result = api_result
            distill_method = "gemini_api" if isinstance(api_client, _GeminiClientShim) else "claude_api"
        else:
            result = _rules_based_distill(paper_row, source_text=source_text, reading_level=KID_LEVEL)
            distill_method = "rules_based"
    else:
        result = _rules_based_distill(paper_row, source_text=source_text, reading_level=KID_LEVEL)
        distill_method = "rules_based"

    result = _sanitize_distill_result(result, reading_level=KID_LEVEL)
    overlap = _faithfulness_overlap(
        _clean_text(result.get("summary", "")),
        _parse_json_list(result.get("key_takeaways", [])),
        source_text,
    )
    certainty_score, certainty_label = _certainty_from_signals(
        source_type=source_type,
        source_chars=len(source_text),
        method=distill_method,
        overlap=overlap,
    )
    result.update({
        "summary_source": source_type,
        "source_text_hash": source_hash,
        "source_text_chars": len(source_text),
        "summary_generated_at_utc": generated_at_utc,
        "distill_method": distill_method,
        "faithfulness_overlap": overlap,
        "summary_certainty_score": certainty_score,
        "summary_certainty_label": certainty_label,
        "summary_disclaimer": _disclaimer_for_source(source_type, certainty_label),
    })
    _save_cache(cache_dir, paper_id, KID_LEVEL, result)
    return result


def _update_paper_summaries(
    *,
    api_client,
    model: str,
    cache_dir: Path,
    summaries_path: Path,
    scored_path: Path,
    topics_dir: Path,
    fulltext_by_id: dict,
    fulltext_source_by_id: dict,
    batch_size: int,
    force: bool,
) -> None:
    """Update paper_summaries.csv with kid-level columns."""
    if not scored_path.exists():
        print(f"[warn] scored_papers.csv not found at {scored_path}; skipping paper summaries.")
        return

    scored = pd.read_csv(scored_path, low_memory=False)
    scored = scored[scored["tier"].isin(["included", "seed_neighbor"])].copy()
    scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)
    has_abstract = ~(scored["abstract"].isna() | scored["abstract"].astype(str).str.strip().str.lower().isin(["", "nan"]))
    has_fulltext = scored["canonical_paper_id"].isin(set(fulltext_by_id))
    scored = scored[has_abstract | has_fulltext].copy()

    # Load existing summaries if present.
    existing: dict[str, dict] = {}
    if summaries_path.exists():
        df = pd.read_csv(summaries_path)
        df["canonical_paper_id"] = df["canonical_paper_id"].astype(str)
        existing = {row["canonical_paper_id"]: row.to_dict() for _, row in df.iterrows()}

    # Topic label lookup.
    topic_labels: dict = {}
    paper_topic_map: dict = {}
    topic_clusters_path = topics_dir / "topic_clusters.csv"
    paper_topics_path = topics_dir / "paper_topics.csv"
    if topic_clusters_path.exists() and paper_topics_path.exists():
        tc = pd.read_csv(topic_clusters_path)
        pt = pd.read_csv(paper_topics_path)
        topic_labels = dict(zip(tc["topic_id"], tc["auto_label"]))
        paper_topic_map = dict(zip(pt["canonical_paper_id"].astype(str), pt["topic_id"]))

    api_call_counter = 0
    updated = 0
    skipped = 0
    for idx, (_, row) in enumerate(scored.iterrows()):
        paper_id = row["canonical_paper_id"]
        existing_row = existing.get(paper_id, {})

        # Skip if kid summary already exists and not forcing.
        if not force and _clean_text(existing_row.get("summary_kid", "")):
            skipped += 1
            continue

        source_text, source_type = _context_from_row(row.to_dict(), fulltext_by_id, fulltext_source_by_id)
        if not source_text:
            continue

        source_hash = hashlib.sha1(source_text.encode("utf-8")).hexdigest()
        generated_at_utc = datetime.now(timezone.utc).isoformat()
        topic_label = topic_labels.get(paper_topic_map.get(paper_id), "General MS")

        kid_result = _distill_kid(
            api_client=api_client,
            model=model,
            cache_dir=cache_dir,
            paper_row=row.to_dict(),
            paper_id=paper_id,
            topic_label=topic_label,
            source_text=source_text,
            source_type=source_type,
            source_hash=source_hash,
            generated_at_utc=generated_at_utc,
            force=force,
        )

        # Merge kid fields into the existing row (or create a stub row).
        merged = existing_row.copy() if existing_row else {
            "canonical_paper_id": paper_id,
            "title": _clean_text(row.get("title", "")),
            "year": _coerce_int(row.get("year"), default=None),
            "doi": _clean_text(row.get("doi", "")),
        }
        merged["summary_kid"] = _clean_text(kid_result.get("summary", ""))
        merged["why_it_matters_kid"] = _clean_text(kid_result.get("why_it_matters", ""))
        merged["key_takeaways_kid"] = json.dumps(kid_result.get("key_takeaways", []))
        merged["jargon_kid"] = json.dumps(kid_result.get("jargon", []))
        existing[paper_id] = merged
        updated += 1

        if api_client and kid_result.get("distill_method") in ("claude_api", "gemini_api"):
            api_call_counter += 1
            if api_call_counter % batch_size == 0:
                time.sleep(1)

        if (idx + 1) % 50 == 0:
            print(f"  Processed {idx + 1}/{len(scored)} papers  (updated={updated}, skipped={skipped})")

    # Write back.
    if existing:
        out_df = pd.DataFrame(list(existing.values()))
        out_df.to_csv(summaries_path, index=False)
        print(f"Wrote {len(out_df)} rows to {summaries_path}  (kid summaries updated={updated}, skipped={skipped})")
    else:
        print("[warn] No rows to write; paper_summaries.csv unchanged.")


def _update_topic_overviews(
    *,
    api_client,
    model: str,
    topics_dir: Path,
    scored_path: Path,
    overviews_path: Path,
    force: bool,
) -> None:
    """Regenerate the overview_kid column in topic_overviews.csv."""
    if not overviews_path.exists():
        print(f"[warn] topic_overviews.csv not found at {overviews_path}; skipping.")
        return

    overviews = pd.read_csv(overviews_path)
    paper_topics_path = topics_dir / "paper_topics.csv"
    scored: pd.DataFrame = pd.DataFrame()
    if scored_path.exists():
        scored = pd.read_csv(scored_path, low_memory=False)
        scored["canonical_paper_id"] = scored["canonical_paper_id"].astype(str)

    updated = 0
    rows_out = []
    for _, row in overviews.iterrows():
        row = row.to_dict()
        existing_kid = _clean_text(row.get("overview_kid", ""))
        if not force and existing_kid:
            rows_out.append(row)
            continue

        tid = row.get("topic_id")
        label = _clean_text(row.get("auto_label", ""))
        n_papers = int(row.get("n_papers", 0))

        kid_overview = ""
        if api_client and not scored.empty and paper_topics_path.exists():
            pt = pd.read_csv(paper_topics_path)
            cluster_ids = set(pt[pt["topic_id"] == tid]["canonical_paper_id"].astype(str))
            cluster_papers = scored[scored["canonical_paper_id"].isin(cluster_ids)].head(5)
            if not cluster_papers.empty:
                paper_text = "".join(
                    f"Title: {p.get('title', '')}\nAbstract: {str(p.get('abstract', '') or '')[:TOPIC_ABSTRACT_PREVIEW_CHARS]}\n\n"
                    for _, p in cluster_papers.iterrows()
                )
                kid_prompt = TOPIC_OVERVIEW_PROMPT_KID.format(
                    topic_label=label,
                    n_papers=n_papers,
                    paper_summaries=paper_text,
                )
                try:
                    resp = api_client.messages.create(
                        model=model,
                        max_tokens=LLM_MAX_TOKENS,
                        messages=[{"role": "user", "content": kid_prompt}],
                    )
                    kid_overview = resp.content[0].text
                    updated += 1
                except Exception as exc:
                    print(f"  [warn] Topic {tid} kid overview failed: {exc}")

        row["overview_kid"] = kid_overview
        rows_out.append(row)

    pd.DataFrame(rows_out).to_csv(overviews_path, index=False)
    print(f"Updated topic_overviews.csv with kid overviews (regenerated={updated})")


def run(config_path: str, force: bool = False) -> None:
    """Update kid-friendly summaries and topic overviews from the pipeline."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    graph_dir = root / cfg["output_dir"] / "graph"
    topics_dir = root / cfg["output_dir"] / "topics"
    distilled_dir = root / cfg["output_dir"] / "distilled"
    ensure_dir(distilled_dir)

    dist_cfg = cfg.get("distillation", {})
    cache_dir = root / dist_cfg.get("cache_dir", "outputs/distilled/llm_cache")
    ensure_dir(cache_dir)
    model = dist_cfg.get("model", "claude-haiku-4-5-20251001")
    batch_size = int(dist_cfg.get("batch_size", 10))

    fulltext_by_id, fulltext_source_by_id = _load_fulltext_maps(root, cfg["output_dir"])
    api_client, _provider = _init_api_client(dist_cfg)

    print(f"Updating kid-friendly summaries (force={force}) ...")
    _update_paper_summaries(
        api_client=api_client,
        model=model,
        cache_dir=cache_dir,
        summaries_path=distilled_dir / "paper_summaries.csv",
        scored_path=graph_dir / "scored_papers.csv",
        topics_dir=topics_dir,
        fulltext_by_id=fulltext_by_id,
        fulltext_source_by_id=fulltext_source_by_id,
        batch_size=batch_size,
        force=force,
    )

    print("Updating kid-friendly topic overviews ...")
    _update_topic_overviews(
        api_client=api_client,
        model=model,
        topics_dir=topics_dir,
        scored_path=graph_dir / "scored_papers.csv",
        overviews_path=distilled_dir / "topic_overviews.csv",
        force=force,
    )

    print(
        "\nDone. Re-run site generation to publish the updated kid journey:\n"
        "  cd site && python gen_site.py --config ../config.yaml && npm run build"
    )


def main() -> None:
    """CLI entry point for standalone execution."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate kid summaries for all papers, ignoring the cache",
    )
    args = parser.parse_args()
    run(args.config, force=args.force)


if __name__ == "__main__":
    main()
