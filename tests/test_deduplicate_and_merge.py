"""Tests for src/deduplicate_and_merge: year-delta guard and short-title guard."""

from __future__ import annotations

import pandas as pd
import pytest

from src.deduplicate_and_merge import run as run_dedup
from src.utils import normalize_title


def _write_candidates(tmp_path, rows):
    raw_dir = tmp_path / "outputs" / "raw"
    raw_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(raw_dir / "candidate_papers.csv", index=False)
    return tmp_path


def _run(tmp_path, threshold=0.85, max_year_delta=2):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'output_dir: "outputs"\n'
        f"dedup:\n"
        f"  auto_merge_threshold: {threshold}\n"
        f"  max_merge_year_delta: {max_year_delta}\n",
        encoding="utf-8",
    )
    run_dedup(str(config_path))
    return pd.read_csv(tmp_path / "outputs" / "normalized" / "canonical_papers.csv")


def _candidate(doi="", title="", year=2020, author="Smith J", channel="seed"):
    return {
        "candidate_id": f"cand-{doi or title[:10]}-{year}",
        "doi": doi,
        "title": title,
        "year": year,
        "first_author": author,
        "abstract": "",
        "venue": "Journal",
        "cited_by_count": 0,
        "openalex_id": "",
        "channel": channel,
        "query": "",
        "seed_title": "",
        "seed_doi": "",
    }


def test_same_doi_always_merges(tmp_path):
    """Papers with the same DOI merge regardless of year gap or title."""
    rows = [
        _candidate(doi="10.1/abc", title="First version", year=2010, channel="seed"),
        _candidate(doi="10.1/abc", title="Second version", year=2018, channel="lexical"),
    ]
    _write_candidates(tmp_path, rows)
    canon = _run(tmp_path)
    assert len(canon) == 1, "same DOI must always merge"
    assert canon.iloc[0]["version_count"] == 2


def test_year_delta_guard_prevents_false_merge(tmp_path):
    """Two papers with identical short titles but 6-year gap must NOT merge under delta=2."""
    rows = [
        _candidate(title="Multiple sclerosis review", year=2002, author="Compston A", channel="seed"),
        _candidate(title="Multiple sclerosis review", year=2008, author="Compston A", channel="lexical"),
    ]
    _write_candidates(tmp_path, rows)
    canon = _run(tmp_path, max_year_delta=2)
    assert len(canon) == 2, "6-year gap must not merge under max_merge_year_delta=2"


def test_year_delta_allows_preprint_published(tmp_path):
    """A preprint and its published version within 2 years should merge."""
    rows = [
        _candidate(title="Ocrelizumab reduces relapse rate in multiple sclerosis", year=2016, author="Hauser S", channel="seed"),
        _candidate(title="Ocrelizumab reduces relapse rate in multiple sclerosis", year=2017, author="Hauser S", channel="lexical"),
    ]
    _write_candidates(tmp_path, rows)
    canon = _run(tmp_path, max_year_delta=2)
    assert len(canon) == 1, "1-year gap with identical title must merge"


def test_short_title_guard_requires_doi(tmp_path):
    """Papers with < 4 title tokens must not merge on title alone even with same author/year."""
    rows = [
        _candidate(doi="10.1/a1", title="Multiple sclerosis", year=2018, author="Filippi M", channel="seed"),
        _candidate(doi="10.1/a2", title="Multiple sclerosis", year=2018, author="Filippi M", channel="lexical"),
    ]
    _write_candidates(tmp_path, rows)
    canon = _run(tmp_path)
    assert len(canon) == 2, "short titles (<4 tokens) with different DOIs must not merge"


def test_long_title_fuzzy_merge_works(tmp_path):
    """Papers with long similar titles, same author, and year gap ≤ delta should merge."""
    rows = [
        _candidate(
            title="Diagnostic criteria for multiple sclerosis 2010 revisions to the McDonald criteria",
            year=2010,
            author="Polman C",
            channel="seed",
        ),
        _candidate(
            title="Diagnostic criteria for multiple sclerosis 2010 revisions McDonald criteria update",
            year=2010,
            author="Polman C",
            channel="lexical",
        ),
    ]
    _write_candidates(tmp_path, rows)
    canon = _run(tmp_path, threshold=0.85)
    assert len(canon) == 1, "long similar titles with same author/year should merge"
