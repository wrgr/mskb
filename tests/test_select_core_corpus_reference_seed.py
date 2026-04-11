"""Tests for reference-seed tier tracking in core selection outputs."""

import pandas as pd

from src.select_core_corpus import _annotate_reference_seed_tier, _apply_topic_cap


def test_annotate_reference_seed_tier_relabels_non_core_reference_rows() -> None:
    df = pd.DataFrame(
        {
            "canonical_paper_id": ["p1", "p2", "p3", "p4"],
            "core_selection_tier": ["T2", "T3", "T1", "T4"],
            "is_reference_seed": [True, True, True, True],
            "is_core_seed": [False, False, True, False],
        }
    )

    out = _annotate_reference_seed_tier(df)
    tiers = dict(zip(out["canonical_paper_id"], out["core_selection_tier"]))

    assert tiers["p1"] == "T1_REF"
    assert tiers["p2"] == "T1_REF"
    assert tiers["p3"] == "T1"
    assert tiers["p4"] == "T4"


def test_apply_topic_cap_preserves_recent_reserve_when_dropping() -> None:
    selected = pd.DataFrame(
        {
            "canonical_paper_id": ["a", "b", "c", "d", "e", "f"],
            "primary_topic_code": ["TOPIC-01"] * 6,
            "core_selection_tier": ["T3", "T3", "T2", "T2", "T2", "T2"],
            "paper_importance_score": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "citations_per_year_raw": [30.0, 25.0, 5.0, 4.0, 3.0, 2.0],
            "is_recent_velocity": [True, True, False, False, False, False],
        }
    )

    capped, removed, blocked = _apply_topic_cap(
        selected,
        max_topic_share=1.0,
        max_topic_count=4,
        recent_reserve_fraction=0.20,
        recent_reserve_floor=2,
    )

    assert len(capped) == 4
    assert int(capped["is_recent_velocity"].sum()) >= 2
    removed_ids = {row["canonical_paper_id"] for row in removed}
    assert removed_ids.isdisjoint({"a", "b"})
    assert blocked == {}
