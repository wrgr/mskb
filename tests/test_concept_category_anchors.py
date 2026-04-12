"""Validation tests for category-level concept anchors and justification coverage."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR_REGISTRY_PATH = REPO_ROOT / "data" / "concept_category_anchors.yaml"
CONCEPTS_ROOT = REPO_ROOT / "site" / "src" / "content" / "docs" / "concepts"
SITE_DIR = REPO_ROOT / "site"
sys.path.insert(0, str(SITE_DIR))

import gen_site_taxonomy as taxonomy  # noqa: E402


def _load_registry() -> dict[str, Any]:
    assert ANCHOR_REGISTRY_PATH.exists(), f"missing {ANCHOR_REGISTRY_PATH}"
    payload = yaml.safe_load(ANCHOR_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    assert isinstance(payload, dict), "concept anchor registry must be a mapping"
    return payload


def _load_concepts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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
        if not concept_id:
            continue
        category = str(concept.get("category", "")).strip()
        anchors = concept.get("anchors") or {}
        if not isinstance(anchors, dict):
            anchors = {}
        out.append(
            {
                "id": concept_id,
                "category": category,
                "anchors": anchors,
                "path": str(path.relative_to(REPO_ROOT)),
            }
        )
    return out


def test_registry_shape_and_category_alignment() -> None:
    payload = _load_registry()
    sources = payload.get("sources")
    categories = payload.get("categories")
    assert isinstance(sources, list), "registry sources must be a list"
    assert isinstance(categories, dict), "registry categories must be a mapping"

    source_ids = [str(item.get("id", "")).strip() for item in sources if isinstance(item, dict)]
    assert source_ids and all(source_ids), "every source must define a non-empty id"
    assert len(source_ids) == len(set(source_ids)), "source ids must be unique"

    expected_categories = set(taxonomy.CATEGORY_ORDER)
    assert set(categories.keys()) == expected_categories, (
        "registry category set must exactly match canonical category order"
    )

    for category, entry in categories.items():
        assert isinstance(entry, dict), f"category {category} must be a mapping"
        source_refs = entry.get("source_ids")
        assert isinstance(source_refs, list) and source_refs, f"{category} must list source_ids"
        for ref in source_refs:
            rid = str(ref).strip()
            assert rid in set(source_ids), f"{category} references unknown source id: {rid}"


def test_each_concept_has_anchor_metadata_for_justification() -> None:
    concepts = _load_concepts()
    assert concepts, "expected non-empty concept set"

    for concept in concepts:
        cid = concept["id"]
        anchors = concept["anchors"]
        topic_map = anchors.get("topic_map")
        assert isinstance(topic_map, list) and topic_map, f"{cid} missing non-empty anchors.topic_map"

        has_jla = anchors.get("jla_priority") not in (None, "", False)
        has_aan = bool(anchors.get("aan_quality_measure"))
        has_proms = bool(anchors.get("proms"))
        has_rationale = bool(str(anchors.get("edu_rationale", "")).strip())
        assert has_jla or has_aan or has_proms or has_rationale, (
            f"{cid} must provide at least one anchor justification signal"
        )


def test_category_registry_covers_observed_marker_usage() -> None:
    payload = _load_registry()
    categories = payload.get("categories") or {}
    concepts = _load_concepts()

    by_category: dict[str, list[dict[str, Any]]] = {}
    for concept in concepts:
        by_category.setdefault(concept["category"], []).append(concept)

    marker_to_source = {
        "jla": "jla_ms_priority_setting_partnership_2022",
        "aan": "aan_ms_quality_measure_set_2020",
        "proms": "msif_global_proms_initiative",
    }

    for category in taxonomy.CATEGORY_ORDER:
        category_concepts = by_category.get(category, [])
        assert category_concepts, f"no concepts found for category {category}"
        source_ids = set((categories.get(category) or {}).get("source_ids") or [])

        has_jla = any(c["anchors"].get("jla_priority") not in (None, "", False) for c in category_concepts)
        has_aan = any(bool(c["anchors"].get("aan_quality_measure")) for c in category_concepts)
        has_proms = any(bool(c["anchors"].get("proms")) for c in category_concepts)

        if has_jla:
            assert marker_to_source["jla"] in source_ids, (
                f"{category} includes jla-tagged concepts but registry is missing JLA source"
            )
        if has_aan:
            assert marker_to_source["aan"] in source_ids, (
                f"{category} includes AAN-tagged concepts but registry is missing AAN source"
            )
        if has_proms:
            assert marker_to_source["proms"] in source_ids, (
                f"{category} includes PROMS-tagged concepts but registry is missing MSIF PROMS source"
            )
