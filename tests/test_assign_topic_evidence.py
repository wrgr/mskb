"""Tests for topic-evidence assignment helpers."""

from src.assign_topic_evidence import (
    _extract_topic_code,
    _has_complete_assignment_metadata,
    _parse_topics_covered,
    _review_anchor_override_topic,
    _seed_topic_support_by_hops,
)


def test_extract_topic_code_supports_topic_prefix() -> None:
    assert _extract_topic_code("TOPIC-07 Risk Factors") == "TOPIC-07"
    assert _extract_topic_code("topic-16 Clinical AI") == "TOPIC-16"
    assert _extract_topic_code("T1b legacy code") == "T1b"
    assert _extract_topic_code("no topic here") == ""


def test_seed_topic_support_by_hops_collects_indirect_seed_evidence() -> None:
    neighbors = {
        "p0": {"p1"},
        "p1": {"p0", "p2"},
        "p2": {"p1"},
    }
    core_pid_topics = {"p2": {"TOPIC-04"}}
    anchor_pid_topics = {}

    (
        core_support,
        anchor_support,
        direct_core_support,
        direct_anchor_support,
        nearest_core_hop,
        nearest_anchor_hop,
    ) = _seed_topic_support_by_hops(
        "p0",
        neighbors,
        core_pid_topics,
        anchor_pid_topics,
        max_hops=3,
    )

    assert nearest_core_hop == 2
    assert nearest_anchor_hop == -1
    assert core_support["TOPIC-04"] > 0
    assert direct_core_support["TOPIC-04"] == 0
    assert len(direct_anchor_support) == 0
    assert len(anchor_support) == 0
    assert _parse_topics_covered("TOPIC-01, TOPIC-04, TOPIC-01") == ["TOPIC-01", "TOPIC-04"]


def test_review_anchor_override_topic_maps_r4_to_biomarker_topic() -> None:
    import pandas as pd

    row = pd.Series({"doi": "https://doi.org/10.1016/S1474-4422(25)00249-2"})
    assert _review_anchor_override_topic(row) == "TOPIC-07"


def test_has_complete_assignment_metadata_requires_title_doi_abstract() -> None:
    import pandas as pd

    assert _has_complete_assignment_metadata(
        pd.Series({"title": "Example", "doi": "https://doi.org/10.1000/xyz", "abstract": "A short abstract."})
    )
    assert not _has_complete_assignment_metadata(
        pd.Series({"title": "Example", "doi": "", "abstract": "A short abstract."})
    )
    assert not _has_complete_assignment_metadata(
        pd.Series({"title": "Example", "doi": "not-a-doi", "abstract": "A short abstract."})
    )
    assert not _has_complete_assignment_metadata(
        pd.Series({"title": "Example", "doi": "https://doi.org/10.1000/xyz", "abstract": ""})
    )
