"""Tests for src/export_corpus.py.

Covers field selection, bool normalisation, concept index building,
and end-to-end CSV/JSON output against a minimal in-memory fixture.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from src import export_corpus


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_coerce_bool_from_string() -> None:
    assert export_corpus._coerce_bool("True") is True
    assert export_corpus._coerce_bool("false") is False
    assert export_corpus._coerce_bool("1") is True
    assert export_corpus._coerce_bool("0") is False


def test_coerce_bool_from_numeric() -> None:
    assert export_corpus._coerce_bool(1) is True
    assert export_corpus._coerce_bool(0) is False
    assert export_corpus._coerce_bool(1.0) is True


def test_safe_str_collapses_nan() -> None:
    assert export_corpus._safe_str(float("nan")) == ""
    assert export_corpus._safe_str(None) == ""
    assert export_corpus._safe_str("hello") == "hello"


def test_safe_int_returns_none_for_nan() -> None:
    assert export_corpus._safe_int(float("nan")) is None
    assert export_corpus._safe_int(None) is None
    assert export_corpus._safe_int(3.7) == 3


def test_safe_float_rounds_and_handles_nan() -> None:
    assert export_corpus._safe_float(float("nan")) is None
    assert export_corpus._safe_float(None) is None
    assert export_corpus._safe_float(3.123456789) == pytest.approx(3.123457)


# ---------------------------------------------------------------------------
# build_concept_index
# ---------------------------------------------------------------------------


def test_build_concept_index_maps_papers(tmp_path: Path) -> None:
    cache = {
        "concepts": {
            "b_cell_therapies": {
                "foundational": ["paper_aaa", "paper_bbb"],
                "advanced": ["paper_ccc"],
                "rationales": {},
            },
            "remyelination": {
                "foundational": ["paper_aaa"],
                "advanced": [],
                "rationales": {},
            },
        }
    }
    cache_file = tmp_path / "concept_papers.json"
    cache_file.write_text(json.dumps(cache), encoding="utf-8")

    index = export_corpus._build_concept_index(cache_file)

    assert set(index["paper_aaa"]["foundational"]) == {"b_cell_therapies", "remyelination"}
    assert index["paper_bbb"]["foundational"] == ["b_cell_therapies"]
    assert index["paper_ccc"]["advanced"] == ["b_cell_therapies"]
    assert index["paper_ccc"]["foundational"] == []


def test_build_concept_index_missing_file(tmp_path: Path) -> None:
    index = export_corpus._build_concept_index(tmp_path / "nonexistent.json")
    assert index == {}


# ---------------------------------------------------------------------------
# End-to-end: run() writes CSV and JSON
# ---------------------------------------------------------------------------


def _make_corpus_csv(path: Path) -> None:
    """Write a minimal corpus CSV with two papers, one in final corpus."""
    rows = [
        {
            "canonical_paper_id": "aaaa",
            "openalex_id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/test1",
            "all_dois": "https://doi.org/10.1000/test1",
            "all_openalex_ids": "https://openalex.org/W1",
            "title": "Test Paper One",
            "year": "2020",
            "venue": "Test Journal",
            "first_author": "Smith J",
            "is_preprint": "False",
            "merged_cited_by_count": "100",
            "abstract": "Abstract one.",
            "abstract_backfill_source": "",
            "tier": "T1",
            "corpus_role": "core",
            "in_core_corpus": "True",
            "in_final_corpus": "True",
            "in_t4_expert_signal": "0",
            "is_core_seed": "True",
            "primary_topic_code": "TOPIC-00",
            "anchor_category": "pathogenesis_and_immunology",
            "evidence_type": "review",
            "evidence_strength": "4",
            "score_total": "10.5",
            "paper_importance_score": "7.2",
            "n_independent_signals": "3",
        },
        {
            "canonical_paper_id": "bbbb",
            "openalex_id": "https://openalex.org/W2",
            "doi": "https://doi.org/10.1000/test2",
            "all_dois": "https://doi.org/10.1000/test2",
            "all_openalex_ids": "https://openalex.org/W2",
            "title": "Test Paper Two",
            "year": "2019",
            "venue": "Another Journal",
            "first_author": "Jones A",
            "is_preprint": "False",
            "merged_cited_by_count": "50",
            "abstract": "Abstract two.",
            "abstract_backfill_source": "pubmed_pmid:999",
            "tier": "T2",
            "corpus_role": "context",
            "in_core_corpus": "False",
            "in_final_corpus": "False",  # excluded from export
            "in_t4_expert_signal": "0",
            "is_core_seed": "False",
            "primary_topic_code": "TOPIC-01",
            "anchor_category": "genetics",
            "evidence_type": "other",
            "evidence_strength": "2",
            "score_total": "5.0",
            "paper_importance_score": "3.1",
            "n_independent_signals": "1",
        },
    ]
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _make_concept_cache(path: Path) -> None:
    cache = {
        "concepts": {
            "b_cell_therapies": {
                "foundational": ["aaaa"],
                "advanced": [],
                "rationales": {},
            }
        }
    }
    path.write_text(json.dumps(cache), encoding="utf-8")


def _make_config(tmp_path: Path, output_subdir: str = "outputs") -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"output_dir: {output_subdir}\n", encoding="utf-8")
    return cfg_path


def test_run_writes_csv_and_json(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    graph_dir = output_dir / "graph"
    graph_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _make_corpus_csv(graph_dir / "core_corpus_tracked_with_t4.csv")
    _make_concept_cache(data_dir / "concept_papers.json")
    cfg_path = _make_config(tmp_path)

    export_corpus.run(str(cfg_path))

    export_dir = output_dir / "corpus_export"
    csv_path = export_dir / "ms_corpus_export.csv"
    json_path = export_dir / "ms_corpus_export.json"
    readme_path = export_dir / "README.md"

    assert csv_path.exists(), "CSV not created"
    assert json_path.exists(), "JSON not created"
    assert readme_path.exists(), "README not created"

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Only the in_final_corpus=True paper should be exported.
    assert len(rows) == 1
    assert rows[0]["canonical_paper_id"] == "aaaa"
    assert rows[0]["in_final_corpus"] == "true"
    assert rows[0]["title"] == "Test Paper One"


def test_run_json_has_concept_arrays(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    graph_dir = output_dir / "graph"
    graph_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _make_corpus_csv(graph_dir / "core_corpus_tracked_with_t4.csv")
    _make_concept_cache(data_dir / "concept_papers.json")
    cfg_path = _make_config(tmp_path)

    export_corpus.run(str(cfg_path))

    payload = json.loads((output_dir / "corpus_export" / "ms_corpus_export.json").read_text())
    assert payload["n_papers"] == 1
    paper = payload["papers"][0]
    assert "concepts_foundational" in paper
    assert "b_cell_therapies" in paper["concepts_foundational"]
    assert paper["concepts_advanced"] == []


def test_run_skips_gracefully_when_corpus_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True)
    cfg_path = _make_config(tmp_path)

    # Should not raise — just print a warning.
    export_corpus.run(str(cfg_path))

    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_export_columns_are_documented() -> None:
    """Every EXPORT_COLUMNS entry must have a field doc."""
    for col in export_corpus.EXPORT_COLUMNS:
        assert col in export_corpus._FIELD_DOCS, f"Missing docs for column: {col}"
