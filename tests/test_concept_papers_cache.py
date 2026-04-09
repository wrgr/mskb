"""Validation tests for data/concept_papers.json cache integrity."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "data" / "concept_papers.json"
CONCEPTS_ROOT = REPO_ROOT / "site" / "src" / "content" / "docs" / "concepts"
SCORED_PAPERS_PATH = REPO_ROOT / "outputs" / "graph" / "scored_papers.csv"


def _load_concept_ids_from_disk() -> set[str]:
    ids: set[str] = set()
    fm_re = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
    for path in sorted(CONCEPTS_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".mdx"}:
            continue
        if path.name == "index.mdx":
            continue
        text = path.read_text(encoding="utf-8")
        match = fm_re.match(text)
        if not match:
            continue
        frontmatter = yaml.safe_load(match.group(1)) or {}
        concept = frontmatter.get("concept") or {}
        concept_id = str(concept.get("id", "")).strip()
        if concept_id:
            ids.add(concept_id)
    return ids


def _load_valid_paper_ids() -> set[str]:
    assert SCORED_PAPERS_PATH.exists(), f"missing {SCORED_PAPERS_PATH}"
    frame = pd.read_csv(SCORED_PAPERS_PATH, usecols=["canonical_paper_id"])
    return {str(value).strip() for value in frame["canonical_paper_id"].tolist() if str(value).strip()}


def test_concept_papers_cache_schema_and_set_equality() -> None:
    assert CACHE_PATH.exists(), f"missing {CACHE_PATH}"
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload.get("concepts"), dict)

    cache_ids = set(payload["concepts"].keys())
    disk_ids = _load_concept_ids_from_disk()
    assert cache_ids == disk_ids, (
        f"concept id mismatch between cache and concept files: "
        f"missing={sorted(disk_ids - cache_ids)[:5]} extra={sorted(cache_ids - disk_ids)[:5]}"
    )


def test_all_cached_paper_ids_exist_in_corpus() -> None:
    if not SCORED_PAPERS_PATH.exists():
        import pytest
        pytest.skip(f"pipeline output not present: {SCORED_PAPERS_PATH}")
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    concepts = payload.get("concepts") or {}
    valid_paper_ids = _load_valid_paper_ids()

    for concept_id, links in concepts.items():
        assert isinstance(links, dict), f"cache payload for {concept_id} must be an object"
        for bucket in ("foundational", "advanced"):
            values = links.get(bucket)
            assert isinstance(values, list), f"{concept_id}.{bucket} must be a list"
            for paper_id in values:
                pid = str(paper_id).strip()
                assert pid in valid_paper_ids, f"unknown paper id in cache: {concept_id}.{bucket} -> {pid}"
