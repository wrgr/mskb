"""Tests for the expert comms review packet builder.

Covers the T1/T1-ref/T2/T3/T4/other tier classification and the
post-selection corpus loading precedence (tracked_with_t4 > selected > scored).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src import expert_comms


def _row(**overrides: object) -> pd.Series:
    base: dict[str, object] = {
        "core_selection_tier": "",
        "tracked_source": "",
        "all_channels": "",
        "is_core_seed": False,
        "in_t4_expert_signal": 0,
        "tier": "",
    }
    base.update(overrides)
    return pd.Series(base)


def test_tier_label_prioritises_t4_over_everything() -> None:
    row = _row(core_selection_tier="T2", in_t4_expert_signal=1)
    assert expert_comms._tier_label(row) == "T4"


def test_tier_label_t1_uses_core_selection_tier() -> None:
    row = _row(core_selection_tier="T1", all_channels="seed_reference")
    assert expert_comms._tier_label(row) == "T1"


def test_tier_label_t1_ref_when_seed_reference_channel_but_not_t1() -> None:
    row = _row(core_selection_tier="T2", all_channels="seed_reference;lexical")
    assert expert_comms._tier_label(row) == "T1-ref"


def test_tier_label_framing_seed_reference_counts_as_t1_ref() -> None:
    row = _row(core_selection_tier="T2", all_channels="framing_seed_reference")
    assert expert_comms._tier_label(row) == "T1-ref"


def test_tier_label_plain_t2() -> None:
    row = _row(core_selection_tier="T2", all_channels="lexical")
    assert expert_comms._tier_label(row) == "T2"


def test_tier_label_plain_t3() -> None:
    row = _row(core_selection_tier="T3", all_channels="dataset")
    assert expert_comms._tier_label(row) == "T3"


def test_tier_label_other_when_no_signal() -> None:
    row = _row(core_selection_tier="", all_channels="")
    assert expert_comms._tier_label(row) == "other"


def test_tier_counts_returns_ordered_dict_with_zeroes() -> None:
    df = pd.DataFrame(
        [
            {"core_selection_tier": "T1", "all_channels": "seed_resolution"},
            {"core_selection_tier": "T2", "all_channels": "seed_reference"},
            {"core_selection_tier": "T2", "all_channels": "lexical"},
            {"core_selection_tier": "T4", "all_channels": "", "in_t4_expert_signal": 1},
        ]
    )
    counts = expert_comms._tier_counts(df)
    assert list(counts.keys()) == expert_comms.TIER_ORDER
    assert counts["T1"] == 1
    assert counts["T1-ref"] == 1
    assert counts["T2"] == 1
    assert counts["T3"] == 0
    assert counts["T4"] == 1
    assert counts["other"] == 0


def _minimal_audit_report(out_dir: Path) -> Path:
    """Write a minimal audit report that expert_comms can consume."""
    audit_dir = out_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_utc": "2026-01-01T00:00:00Z",
        "corpus_source": "core_corpus_tracked_with_t4.csv",
        "passed": True,
        "errors": [],
        "warnings": [],
        "gate_metrics": {
            "ms_focus_pct": 95.0,
            "missing_abstract_pct": 10.0,
        },
        "category_mix_pct": {"pathogenesis_and_immunology": 50.0, "imaging_and_biomarkers": 50.0},
        "category_entropy_normalized": 0.9,
    }
    (audit_dir / "kb_audit_report.json").write_text(json.dumps(report), encoding="utf-8")
    return audit_dir / "kb_audit_report.json"


def test_expert_comms_reads_tracked_with_t4(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text('output_dir: "outputs"\n', encoding="utf-8")

    out_dir = tmp_path / "outputs"
    graph_dir = out_dir / "graph"
    topics_dir = out_dir / "topics"
    graph_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)

    _minimal_audit_report(out_dir)

    pd.DataFrame(
        [
            {
                "canonical_paper_id": "p1",
                "title": "Seed",
                "year": 2020,
                "doi": "10.1/p1",
                "venue": "Journal X",
                "core_selection_tier": "T1",
                "all_channels": "seed_resolution",
                "primary_topic_code": "TOPIC-02",
                "paper_importance_score": 0.9,
                "merged_cited_by_count": 50,
            },
            {
                "canonical_paper_id": "p2",
                "title": "Seed Ref",
                "year": 2021,
                "doi": "10.1/p2",
                "venue": "Journal X",
                "core_selection_tier": "T2",
                "all_channels": "seed_reference",
                "primary_topic_code": "TOPIC-07",
                "paper_importance_score": 0.7,
                "merged_cited_by_count": 30,
            },
            {
                "canonical_paper_id": "p3",
                "title": "Velocity",
                "year": 2024,
                "doi": "10.1/p3",
                "venue": "Journal Y",
                "core_selection_tier": "T3",
                "all_channels": "lexical",
                "primary_topic_code": "TOPIC-07",
                "paper_importance_score": 0.5,
                "merged_cited_by_count": 12,
            },
        ]
    ).to_csv(graph_dir / "core_corpus_tracked_with_t4.csv", index=False)

    # scored_papers.csv intentionally populated with more rows so we can
    # verify expert_comms ignores it in favour of tracked_with_t4.
    pd.DataFrame(
        [{"canonical_paper_id": f"junk{i}", "in_final_corpus": 1, "title": f"j{i}"} for i in range(50)]
    ).to_csv(graph_dir / "scored_papers.csv", index=False)

    expert_comms.run(str(config_path))

    payload = json.loads((out_dir / "expert_comms" / "expert_comms_report.json").read_text(encoding="utf-8"))
    es = payload["executive_summary"]
    assert es["n_papers"] == 3, "must use tracked_with_t4, not scored_papers"
    assert es["corpus_source"] == "core_corpus_tracked_with_t4.csv"
    assert es["tier_breakdown"] == {"T1": 1, "T1-ref": 1, "T2": 0, "T3": 1, "T4": 0, "other": 0}
    topic_codes = {b["topic_code"] for b in payload["topic_briefs"]}
    assert topic_codes == {"TOPIC-02", "TOPIC-07"}


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0:00"), (59, "0:59"), (60, "1:00"), (3599, "59:59"), (3600, "1:00:00")],
)
def test_fmt_duration(seconds: int, expected: str) -> None:
    from run_pipeline import _fmt_duration

    assert _fmt_duration(seconds) == expected
