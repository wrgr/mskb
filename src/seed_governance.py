"""Validate seed papers against MS-focus criteria and write a governance checklist report."""

import argparse
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .openalex_client import OpenAlexClient
from .utils import ensure_dir, invert_abstract_index, load_config, save_json


MS_FOCUS_TERMS = [
    "multiple sclerosis",
    "relapsing-remitting",
    "progressive ms",
    "primary progressive",
    "secondary progressive",
    "clinically isolated syndrome",
    "mcdonald criteria",
    "ocrelizumab",
    "natalizumab",
    "fingolimod",
    "dimethyl fumarate",
    "teriflunomide",
    "interferon beta",
    "glatiramer",
    "oligoclonal band",
    "neurofilament light",
    "ms lesion",
]

MS_CONCEPT_TERMS = [
    "multiple sclerosis",
    "multiple sclerosis research studies",
    "experimental autoimmune encephalomyelitis",
    "disease-modifying therapy",
    "neurofilament light",
    "oligoclonal band",
    "mcdonald criteria",
]

BRIDGE_HINTS = ["bridge", "bridging", "context", "adjacent", "cross-disease", "mechanistic context"]
_TOPIC_CODE_RE = re.compile(r"^(T\d+b?)", re.IGNORECASE)

# Map canonical topic codes to the broad governance quota categories.
# Some topics contribute to more than one governance category by design.
TOPIC_CATEGORY_MAP: dict[str, list[str]] = {
    "T00": ["epidemiology_and_population_health"],
    "T01": ["clinical_care_and_management"],
    "T1b": ["epidemiology_and_population_health"],
    "T02": ["pathogenesis_and_immunology"],
    "T03": ["pathogenesis_and_immunology", "epidemiology_and_population_health"],
    "T04": ["pathogenesis_and_immunology", "epidemiology_and_population_health"],
    "T05": ["imaging_and_biomarkers"],
    "T06": ["imaging_and_biomarkers"],
    "T07": ["clinical_trials_and_therapeutics"],
    "T08": ["pathogenesis_and_immunology", "clinical_trials_and_therapeutics"],
    "T09": ["clinical_care_and_management"],
    "T10": ["clinical_care_and_management", "epidemiology_and_population_health"],
    "T11": ["clinical_trials_and_therapeutics", "clinical_care_and_management"],
    "T12": ["clinical_trials_and_therapeutics"],
    "T13": ["epidemiology_and_population_health"],
    "T14": ["imaging_and_biomarkers"],
    "T15": ["pathogenesis_and_immunology", "imaging_and_biomarkers"],
    "T16": ["clinical_trials_and_therapeutics"],
}


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _count_hits(text: str, terms: list[str]) -> int:
    t = _clean_text(text).lower()
    return int(sum(1 for term in terms if term in t))


def _extract_topic_code(value: object) -> str:
    text = _clean_text(value)
    match = _TOPIC_CODE_RE.match(text)
    return match.group(1) if match else ""


def _count_seed_categories_from_primary_topic(core: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, row in core.iterrows():
        code = _extract_topic_code(row.get("primary_topic", ""))
        for category in TOPIC_CATEGORY_MAP.get(code, []):
            counts[category] = int(counts.get(category, 0)) + 1
    return counts


def _extract_seed_metadata(seed_row: pd.Series, work: dict | None) -> dict:
    doi = _clean_text(seed_row.get("doi", ""))
    title = _clean_text(seed_row.get("title", ""))
    category = _clean_text(seed_row.get("category", ""))
    role = _clean_text(seed_row.get("role", ""))
    rationale = _clean_text(seed_row.get("rationale", ""))

    bridge_justification = (
        _clean_text(seed_row.get("bridge_justification", ""))
        or _clean_text(seed_row.get("bridge_reason", ""))
        or _clean_text(seed_row.get("justification", ""))
    )
    if not bridge_justification and any(h in rationale.lower() for h in BRIDGE_HINTS):
        bridge_justification = rationale

    if not work:
        text = f"{title} {rationale}"
        return {
            "doi": doi,
            "title": title,
            "category": category,
            "role": role,
            "rationale": rationale,
            "year": None,
            "venue": "",
            "first_author": "",
            "abstract": "",
            "concepts": "",
            "topics": "",
            "ms_lexical_hits": _count_hits(text, MS_FOCUS_TERMS),
            "ms_concept_hits": 0,
            "bridge_justification": bridge_justification,
            "metadata_resolved": False,
        }

    oa_title = _clean_text(work.get("title", "")) or title
    abstract = invert_abstract_index(work.get("abstract_inverted_index", {}) or {})
    concepts = ";".join(
        _clean_text((c or {}).get("display_name", ""))
        for c in (work.get("concepts", []) or [])
        if _clean_text((c or {}).get("display_name", ""))
    )
    topics = ";".join(
        _clean_text((t or {}).get("display_name", ""))
        for t in (work.get("topics", []) or [])
        if _clean_text((t or {}).get("display_name", ""))
    )
    venue = _clean_text((((work.get("primary_location") or {}).get("source") or {}).get("display_name", "")))
    authorships = work.get("authorships", []) or []
    first_author = ""
    if authorships:
        first_author = _clean_text(((authorships[0].get("author") or {}).get("display_name", "")))

    combined = f"{oa_title} {abstract} {concepts} {topics}"
    return {
        "doi": doi,
        "title": oa_title,
        "category": category,
        "role": role,
        "rationale": rationale,
        "year": work.get("publication_year"),
        "venue": venue,
        "first_author": first_author,
        "abstract": abstract,
        "concepts": concepts,
        "topics": topics,
        "ms_lexical_hits": _count_hits(combined, MS_FOCUS_TERMS),
        "ms_concept_hits": _count_hits(combined, MS_CONCEPT_TERMS),
        "bridge_justification": bridge_justification,
        "metadata_resolved": True,
    }


def _evaluate_category_quotas(core: pd.DataFrame, quota_cfg: dict) -> tuple[list[str], dict, dict, dict]:
    errors = []
    mapped_counts = _count_seed_categories_from_primary_topic(core)
    doc_type_counts = core["category"].fillna("uncategorized").value_counts().to_dict()
    effective_counts: dict[str, int] = {}
    count_sources: dict[str, str] = {}
    for category, bounds in (quota_cfg or {}).items():
        if not isinstance(bounds, dict):
            continue
        if category in mapped_counts:
            observed = int(mapped_counts.get(category, 0))
            count_sources[category] = "primary_topic_map"
        else:
            observed = int(doc_type_counts.get(category, 0))
            count_sources[category] = "seed_category_column"
        effective_counts[category] = observed
        min_allowed = int(bounds.get("min", 0))
        max_allowed = int(bounds.get("max", 10**9))
        if observed < min_allowed:
            errors.append(f"category '{category}' below minimum: {observed} < {min_allowed}")
        if observed > max_allowed:
            errors.append(f"category '{category}' above maximum: {observed} > {max_allowed}")
    return errors, effective_counts, mapped_counts, count_sources


def _evaluate_caps(values: pd.Series, cap: int, label: str) -> tuple[list[str], dict]:
    if cap <= 0:
        return [], {}
    counts = values.fillna("").astype(str).str.strip()
    counts = counts[counts != ""].value_counts().to_dict()
    errors = []
    for key, count in counts.items():
        if int(count) > cap:
            errors.append(f"{label} cap exceeded: '{key}' appears {int(count)} times (cap={cap})")
    return errors, counts


def _rank_percentile(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if len(values) == 0:
        return pd.Series(dtype=float)
    return values.rank(method="average", pct=True).fillna(0.0).astype(float)


def _build_landmark_candidates(root: Path, cfg: dict, outdir: Path) -> dict:
    scored_path = root / cfg["output_dir"] / "graph" / "scored_papers.csv"
    if not scored_path.exists():
        return {"generated": False, "reason": "scored_papers.csv not found"}

    lcfg = ((cfg.get("governance", {}) or {}).get("landmark_anchors", {}) or {})
    if not bool(lcfg.get("enabled", True)):
        return {"generated": False, "reason": "landmark_anchors disabled"}

    df = pd.read_csv(scored_path, low_memory=False)
    if df.empty:
        return {"generated": False, "reason": "scored_papers.csv empty"}

    current_year = datetime.now(timezone.utc).year
    min_year = int(lcfg.get("min_year", 1980))
    max_year = int(lcfg.get("max_year", current_year - 2))
    top_k = max(1, int(lcfg.get("output_top_k", 25)))
    per_decade_cap = max(1, int(lcfg.get("per_decade_cap", 5)))

    df["year"] = pd.to_numeric(df.get("year"), errors="coerce")
    df = df[df["year"].notna()].copy()
    df["year"] = df["year"].astype(int)
    df = df[(df["year"] >= min_year) & (df["year"] <= max_year)].copy()
    if "has_ms_focus" in df.columns:
        df = df[df["has_ms_focus"].fillna(False).astype(bool)].copy()
    if df.empty:
        return {"generated": False, "reason": "no eligible papers in year window"}

    df["merged_cited_by_count"] = pd.to_numeric(df.get("merged_cited_by_count"), errors="coerce").fillna(0.0)
    df["pagerank"] = pd.to_numeric(df.get("pagerank"), errors="coerce").fillna(0.0)
    df["in_degree"] = pd.to_numeric(df.get("in_degree"), errors="coerce").fillna(0.0)
    df["paper_age_years"] = (current_year - df["year"] + 1).clip(lower=1)
    df["citations_per_year"] = df["merged_cited_by_count"] / df["paper_age_years"]
    df["rank_pagerank_global"] = _rank_percentile(df["pagerank"])
    df["rank_in_degree_global"] = _rank_percentile(df["in_degree"])
    df["rank_cpy_global"] = _rank_percentile(df["citations_per_year"])

    if "age_normalized_importance_score" in df.columns:
        df["age_normalized_importance_score"] = pd.to_numeric(
            df["age_normalized_importance_score"], errors="coerce"
        ).fillna(0.0)
    else:
        df["age_normalized_importance_score"] = (
            0.45 * df["rank_cpy_global"]
            + 0.35 * df["rank_pagerank_global"]
            + 0.20 * df["rank_in_degree_global"]
        )

    df["decade"] = (df["year"] // 10) * 10
    df = df.sort_values(
        ["age_normalized_importance_score", "citations_per_year", "pagerank", "in_degree"],
        ascending=False,
    )

    selected = []
    decade_counts: dict[int, int] = {}
    for _, row in df.iterrows():
        decade = int(row["decade"])
        if decade_counts.get(decade, 0) >= per_decade_cap:
            continue
        decade_counts[decade] = decade_counts.get(decade, 0) + 1
        selected.append(row)
        if len(selected) >= top_k:
            break

    out = pd.DataFrame(selected)
    if out.empty:
        return {"generated": False, "reason": "no landmark candidates selected"}

    keep_cols = [
        "canonical_paper_id",
        "title",
        "year",
        "venue",
        "doi",
        "first_author",
        "merged_cited_by_count",
        "paper_importance_score",
        "age_normalized_importance_score",
        "citations_per_year",
        "decade",
    ]
    existing_cols = [c for c in keep_cols if c in out.columns]
    out = out[existing_cols].copy()
    out.rename(columns={"merged_cited_by_count": "citation_count"}, inplace=True)
    out["selection_rationale"] = "High age-normalized structural centrality within decade"
    out_path = outdir / "landmark_anchor_candidates.csv"
    out.to_csv(out_path, index=False)

    return {
        "generated": True,
        "count": int(len(out)),
        "output_path": str(out_path),
        "decade_counts": {str(k): int(v) for k, v in sorted(decade_counts.items())},
    }


def run(config_path: str) -> None:
    """Run seed governance checks and write the seed checklist report to the audit directory."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    outdir = root / cfg["output_dir"] / "audit"
    ensure_dir(outdir)

    gcfg = (cfg.get("governance", {}) or {}).get("seed_checklist", {}) or {}
    enabled = bool(gcfg.get("enabled", True))
    if not enabled:
        save_json(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "enabled": False,
                "status": "skipped",
            },
            outdir / "seed_checklist_report.json",
        )
        print("Seed governance checks disabled.")
        return

    core_path = root / "seeds" / "core_seeds.csv"
    framing_path = root / "seeds" / "framing_seeds.csv"
    core = pd.read_csv(core_path)
    framing = pd.read_csv(framing_path) if framing_path.exists() else pd.DataFrame()

    raw_dir = root / cfg["output_dir"] / "raw"
    ensure_dir(raw_dir)
    client = OpenAlexClient(
        base_url=cfg["openalex_base_url"],
        email=cfg["email"],
        per_page=int(cfg.get("retrieval", {}).get("per_page", 200)),
        cache_dir=raw_dir / "openalex_cache",
    )

    lexical_min = max(1, int(gcfg.get("ms_lexical_min_hits", 1)))
    concept_min = max(1, int(gcfg.get("ms_concept_min_hits", 1)))
    allow_bridge = bool(gcfg.get("allow_bridge_justification", True))
    fail_on_error = bool(gcfg.get("fail_on_error", True))
    fail_on_unresolved_metadata = bool(gcfg.get("fail_on_unresolved_metadata", False))

    errors: list[str] = []
    warnings: list[str] = []
    metadata_rows: list[dict] = []

    for _, seed in core.iterrows():
        doi = _clean_text(seed.get("doi", ""))
        if not doi:
            errors.append(f"core seed missing DOI: '{_clean_text(seed.get('title', 'Untitled'))}'")
            metadata_rows.append(_extract_seed_metadata(seed, work=None))
            continue
        try:
            work = client.get_work_by_doi(doi)
        except Exception as exc:
            work = None
            warnings.append(f"OpenAlex lookup error for DOI {doi}: {exc}")
        if not work:
            msg = f"could not resolve seed DOI in OpenAlex: {doi}"
            if fail_on_unresolved_metadata:
                errors.append(msg)
            else:
                warnings.append(msg)
        metadata_rows.append(_extract_seed_metadata(seed, work))

    meta = pd.DataFrame(metadata_rows)
    if not meta.empty:
        meta["category"] = meta["category"].fillna("uncategorized").astype(str)
    meta.to_csv(outdir / "seed_metadata.csv", index=False)

    quota_errors, category_counts, topic_mapped_counts, category_count_sources = _evaluate_category_quotas(
        core, gcfg.get("category_quotas", {})
    )
    errors.extend(quota_errors)

    venue_cap = max(0, int(gcfg.get("venue_cap", 0)))
    venue_errors, venue_counts = _evaluate_caps(meta.get("venue", pd.Series(dtype=str)), venue_cap, "venue")
    errors.extend(venue_errors)

    author_cap = max(0, int(gcfg.get("author_cap", 0)))
    author_errors, author_counts = _evaluate_caps(meta.get("first_author", pd.Series(dtype=str)), author_cap, "author")
    errors.extend(author_errors)

    if not meta.empty:
        for _, row in meta.iterrows():
            lexical_hits = int(row.get("ms_lexical_hits", 0) or 0)
            concept_hits = int(row.get("ms_concept_hits", 0) or 0)
            has_ms_focus = (lexical_hits >= lexical_min) or (concept_hits >= concept_min)
            has_bridge = bool(_clean_text(row.get("bridge_justification", "")))
            if not has_ms_focus:
                if allow_bridge and has_bridge:
                    continue
                errors.append(
                    f"seed fails MS minimum without bridge justification: doi={row.get('doi', '')}, "
                    f"lexical_hits={lexical_hits}, concept_hits={concept_hits}"
                )

    landmark_info = _build_landmark_candidates(root, cfg, outdir)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "enabled": enabled,
        "n_core_seeds": int(len(core)),
        "n_framing_seeds": int(len(framing)),
        "n_resolved_metadata": int(meta["metadata_resolved"].fillna(False).astype(bool).sum()) if not meta.empty else 0,
        "category_counts": {str(k): int(v) for k, v in category_counts.items()},
        "category_count_sources": {str(k): str(v) for k, v in category_count_sources.items()},
        "topic_mapped_category_counts": {str(k): int(v) for k, v in topic_mapped_counts.items()},
        "seed_doc_type_counts": {str(k): int(v) for k, v in core["category"].fillna("uncategorized").value_counts().to_dict().items()},
        "venue_counts": {str(k): int(v) for k, v in venue_counts.items()},
        "author_counts": {str(k): int(v) for k, v in author_counts.items()},
        "errors": errors,
        "warnings": warnings,
        "passed": len(errors) == 0,
        "landmark_candidates": landmark_info,
    }
    save_json(report, outdir / "seed_checklist_report.json")

    status = "PASS" if report["passed"] else "FAIL"
    print(f"Seed governance checklist: {status} ({len(errors)} errors, {len(warnings)} warnings)")
    if errors:
        for err in errors[:20]:
            print(f"  - {err}")
    if fail_on_error and errors:
        raise RuntimeError("Seed governance checklist failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
