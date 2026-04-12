"""Unit tests for topic evidence assignment helpers."""

import pandas as pd

from src.assign_topic_evidence import _extract_topic_code, _graph_distance_support


def test_extract_topic_code_supports_topic_prefix() -> None:
    assert _extract_topic_code("TOPIC-00 Disease Overview") == "TOPIC-00"
    assert _extract_topic_code("topic-17") == "TOPIC-17"


def test_extract_topic_code_supports_legacy_t_prefix() -> None:
    assert _extract_topic_code("T4") == "TOPIC-04"
    assert _extract_topic_code("T12b advanced") == "T12b"


def test_graph_distance_support_prefers_nearest_seed() -> None:
    # A -- B -- C, with A labeled TOPIC-00 and C labeled TOPIC-01
    neighbors = {
        "A": {"B"},
        "B": {"A", "C"},
        "C": {"B"},
    }
    topic_seed_nodes = {
        "TOPIC-00": {"A"},
        "TOPIC-01": {"C"},
    }
    support, hops = _graph_distance_support(neighbors, topic_seed_nodes, max_hops=3, decay=0.5)

    # Middle node receives equal support from both sides at hop 1.
    assert support["B"]["TOPIC-00"] == 1.0
    assert support["B"]["TOPIC-01"] == 1.0
    assert hops["B"]["TOPIC-00"] == 1
    assert hops["B"]["TOPIC-01"] == 1

    # Endpoint A should see TOPIC-01 two hops away only (excluding self-distance 0).
    assert support["A"]["TOPIC-01"] == 0.5
    assert hops["A"]["TOPIC-01"] == 2

