"""Generate domain-expert review packets from v1.3 pipeline outputs.

Reads the audit report, the Stage 5c selected core corpus, topic labels, and
distilled summaries and writes a structured Markdown + JSON reviewer packet to
``outputs/expert_comms/``. Corpus, tier counts, and per-topic briefs are keyed
on the TOPIC-XX taxonomy rather than algorithmic cluster IDs.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .seed_governance import TOPIC_CATEGORY_MAP, _extract_topic_code
from .utils import ensure_dir, load_config, save_json


# Human-readable labels for each TOPIC-XX code used in the expert packet. These
# mirror the v1.3 MS Field Orientation Guide topic map so reviewers see the
# same names as in the seeds manifest.
TOPIC_LABELS: dict[str, str] = {
    "TOPIC-00": "Disease Overview",
    "TOPIC-01": "Genetics",
    "TOPIC-02": "Pathophysiology",
    "TOPIC-03": "Epidemiology",
    "TOPIC-04": "Natural History",
    "TOPIC-05": "Risk Factors & EBV",
    "TOPIC-06": "Diagnosis & Monitoring",
    "TOPIC-07": "Biomarkers",
    "TOPIC-08": "Disease-Modifying Therapies",
    "TOPIC-09": "Progressive MS & Smoldering",
    "TOPIC-10": "Patient-Reported Outcomes",
    "TOPIC-11": "Symptom Management",
    "TOPIC-12": "Comorbidities",
    "TOPIC-13": "Pregnancy & Family Planning",
    "TOPIC-14": "Pediatric MS",
    "TOPIC-15": "Equity & SDOH",
    "TOPIC-16": "Clinical AI",
    "TOPIC-17": "Remyelination & Neuroprotection",
}

# Ordered buckets used in the tier breakdown table. The priority order is
# applied in ``_tier_label`` so each paper lands in exactly one bucket.
TIER_ORDER: list[str] = ["T1", "T1-ref", "T2", "T3", "T4", "other"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_str(value: object) -> str:
    """Return string form of value, or '' for None/NaN."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _safe_int(value: object, default: int = 0) -> int:
    """Coerce value to int, returning default on failure."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    """Coerce value to float, returning default on failure."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _top_venues(papers: pd.DataFrame, k: int = 5) -> list[tuple[str, int]]:
    """Return top-k (venue, count) pairs sorted by count descending."""
    venue_col = "venue" if "venue" in papers.columns else "journal"
    if venue_col not in papers.columns:
        return []
    counts: Counter = Counter()
    for v in papers[venue_col]:
        s = _safe_str(v)
        if s and s.lower() != "nan":
            counts[s] += 1
    return counts.most_common(k)


def _year_span(papers: pd.DataFrame) -> tuple[int | None, int | None]:
    """Return (min_year, max_year) for a set of papers, or (None, None) if unavailable."""
    if "year" not in papers.columns or papers.empty:
        return None, None
    years = pd.to_numeric(papers["year"], errors="coerce").dropna().astype(int)
    if years.empty:
        return None, None
    return int(years.min()), int(years.max())


def _tier_label(row: pd.Series) -> str:
    """Return one of T1/T1-ref/T2/T3/T4/other for a corpus row.

    Priority order: T4 (expert signal) > T1 (core seeds) > T1-ref (one-hop
    references from seeds) > T2 > T3 > other. The canonical tier flag set at
    Stage 5c lives in ``core_selection_tier``; ``all_channels`` and
    ``tracked_source`` are consulted to split T1 from T1-ref.
    """
    selection_tier = _safe_str(row.get("core_selection_tier")).upper()
    tracked_source = _safe_str(row.get("tracked_source")).lower()
    all_channels = _safe_str(row.get("all_channels")).lower()

    is_t4 = (
        selection_tier == "T4"
        or _safe_int(row.get("in_t4_expert_signal"), 0) == 1
        or tracked_source.startswith("t4_")
    )
    if is_t4:
        return "T4"

    if selection_tier == "T1":
        return "T1"
    is_core_seed = bool(row.get("is_core_seed", False)) or "seed_resolution" in all_channels
    if is_core_seed:
        return "T1"

    # T1-ref: papers reached via one-hop expansion from seeds (seed_reference or
    # framing_seed_reference channels). These are not primary seeds but inherit
    # high provenance weight since they were cited by a seed.
    if "seed_reference" in all_channels or "framing_seed_reference" in all_channels:
        return "T1-ref"

    if selection_tier == "T2":
        return "T2"
    if selection_tier == "T3":
        return "T3"

    # Fall back to the legacy ``tier`` column for corpora built before
    # Stage 5c wrote core_selection_tier.
    legacy_tier = _safe_str(row.get("tier")).lower()
    if legacy_tier == "velocity":
        return "T3"
    return "other"


def _tier_counts(corpus: pd.DataFrame) -> dict[str, int]:
    """Return an ordered tier-count dict with zeros for unused buckets."""
    counts = Counter()
    for _, row in corpus.iterrows():
        counts[_tier_label(row)] += 1
    return {tier: int(counts.get(tier, 0)) for tier in TIER_ORDER}


def _top_papers(papers: pd.DataFrame, k: int = 10) -> list[dict[str, Any]]:
    """Return top-k paper records sorted by paper_importance_score."""
    if papers.empty:
        return []
    score_col = "paper_importance_score"
    if score_col not in papers.columns:
        score_col = "pagerank"
    df = papers.copy()
    df[score_col] = pd.to_numeric(df.get(score_col, pd.Series(0.0)), errors="coerce").fillna(0.0)
    df = df.sort_values(score_col, ascending=False).head(k)
    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "title": _safe_str(row.get("title")),
                "year": _safe_int(row.get("year")),
                "venue": _safe_str(row.get("venue") or row.get("journal")),
                "citations": _safe_int(row.get("merged_cited_by_count")),
                "importance": round(_safe_float(row.get("paper_importance_score")), 4),
                "tier": _tier_label(row),
                "doi": _safe_str(row.get("doi")),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-topic brief builder
# ---------------------------------------------------------------------------


def _build_topic_brief(
    topic_code: str,
    label: str,
    papers: pd.DataFrame,
    summaries: pd.DataFrame,
) -> dict[str, Any]:
    """Build an expert review dict for one TOPIC-XX bucket."""
    yr_min, yr_max = _year_span(papers)
    top_venues = _top_venues(papers, k=5)

    # Count low-confidence summaries for this topic
    low_conf = 0
    if not summaries.empty and not papers.empty:
        topic_ids = set(papers["canonical_paper_id"].astype(str))
        topic_sums = summaries[summaries["canonical_paper_id"].astype(str).isin(topic_ids)]
        low_conf = int(
            (topic_sums.get("summary_certainty_label", pd.Series()).astype(str).str.lower() == "low").sum()
        )

    # Flag topics with <3 papers newer than 2020
    recent_cut = 2020
    if "year" in papers.columns:
        n_recent = int((pd.to_numeric(papers["year"], errors="coerce") >= recent_cut).sum())
    else:
        n_recent = 0

    flags: list[str] = []
    if n_recent < 3:
        flags.append(f"Only {n_recent} paper(s) from {recent_cut}+ — consider adding recent literature.")
    if low_conf > 0:
        flags.append(f"{low_conf} paper(s) have low-confidence AI summaries — recommend manual review.")

    return {
        "topic_code": topic_code,
        "label": label,
        "n_papers": len(papers),
        "year_span": [yr_min, yr_max],
        "n_recent": n_recent,
        "tier_breakdown": _tier_counts(papers),
        "top_venues": [{"venue": v, "count": c} for v, c in top_venues],
        "top_papers": _top_papers(papers, k=10),
        "low_conf_summaries": low_conf,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Executive summary builder
# ---------------------------------------------------------------------------


def _build_executive_summary(
    corpus: pd.DataFrame,
    audit_report: dict[str, Any],
    topic_briefs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarise the corpus for the top-level executive section."""
    n_total = len(corpus)
    tier_breakdown = _tier_counts(corpus)

    yr_min, yr_max = _year_span(corpus)

    # Top venues across the whole corpus
    top_corpus_venues = _top_venues(corpus, k=8)

    # Flagged topics are reported by TOPIC-XX code (not cluster label) so
    # reviewers can cross-reference the seeds manifest directly.
    flagged_topic_codes = [b["topic_code"] for b in topic_briefs if b["flags"]]

    gm = audit_report.get("gate_metrics", {})
    return {
        "n_papers": n_total,
        "tier_breakdown": tier_breakdown,
        "year_range": [yr_min, yr_max],
        "top_venues": [{"venue": v, "count": c} for v, c in top_corpus_venues],
        "ms_focus_pct": round(_safe_float(gm.get("ms_focus_pct")), 2),
        "missing_abstract_pct": round(_safe_float(gm.get("missing_abstract_pct")), 2),
        "category_mix_pct": dict(audit_report.get("category_mix_pct", {})),
        "category_entropy_normalized": round(_safe_float(audit_report.get("category_entropy_normalized")), 4),
        "audit_passed": bool(audit_report.get("passed", False)),
        "n_audit_errors": len(audit_report.get("errors", [])),
        "n_audit_warnings": len(audit_report.get("warnings", [])),
        "n_topics": len(topic_briefs),
        "flagged_topic_codes": flagged_topic_codes,
        "corpus_source": str(audit_report.get("corpus_source", "unknown")),
    }


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------


def _render_topic_brief_md(brief: dict[str, Any]) -> str:
    """Render one topic brief as Markdown."""
    lines: list[str] = []
    yr = brief.get("year_span", [None, None])
    yr_str = f"{yr[0]}–{yr[1]}" if yr[0] else "n/a"
    lines.append(f"## {brief['label']} (`{brief['topic_code']}`)")
    lines.append("")
    tb = brief.get("tier_breakdown", {}) or {}
    tier_line = ", ".join(f"{t}={tb.get(t, 0)}" for t in TIER_ORDER if tb.get(t, 0) > 0) or "—"
    lines.append(
        f"**{brief['n_papers']} papers** | "
        f"Year span: {yr_str} | "
        f"Recent (≥2020): {brief.get('n_recent', 0)} | "
        f"Tiers: {tier_line}"
    )
    lines.append("")

    if brief.get("top_venues"):
        lines.append("**Top venues:**")
        for entry in brief["top_venues"][:5]:
            lines.append(f"- {entry['venue']} ({entry['count']})")
        lines.append("")

    if brief.get("top_papers"):
        lines.append("**Top papers by importance:**")
        lines.append("")
        lines.append("| # | Title | Year | Venue | Citations | Tier |")
        lines.append("|---|-------|------|-------|-----------|------|")
        for i, p in enumerate(brief["top_papers"], 1):
            title = p["title"][:80] + ("…" if len(p["title"]) > 80 else "")
            venue = p["venue"][:40] + ("…" if len(p["venue"]) > 40 else "")
            doi_link = f"[DOI](https://doi.org/{p['doi']})" if p.get("doi") else "—"
            lines.append(
                f"| {i} | {title} {doi_link} | {p['year'] or '—'} | {venue or '—'} | "
                f"{p['citations']} | {p['tier']} |"
            )
        lines.append("")

    if brief.get("flags"):
        lines.append("**Reviewer flags:**")
        for flag in brief["flags"]:
            lines.append(f"- {flag}")
        lines.append("")

    return "\n".join(lines)


def _render_full_report_md(
    exec_summary: dict[str, Any],
    topic_briefs: list[dict[str, Any]],
    audit_report: dict[str, Any],
    generated_at: str,
) -> str:
    """Render the complete expert comms review packet as Markdown."""
    lines: list[str] = []
    lines.append("# MS Knowledge Base — Expert Review Packet (v1.3)")
    lines.append("")
    lines.append(f"_Generated: {generated_at}_")
    lines.append("")

    # --- Executive Summary ---
    lines.append("## Executive Summary")
    lines.append("")
    es = exec_summary
    gate_badge = "**PASS**" if es["audit_passed"] else "**FAIL**"
    tb = es.get("tier_breakdown", {}) or {}
    tier_cells = " | ".join(f"{t}={tb.get(t, 0)}" for t in TIER_ORDER)
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Corpus source | `{es.get('corpus_source', 'unknown')}` |")
    lines.append(f"| Final corpus size | {es['n_papers']} papers |")
    lines.append(f"| Tier breakdown | {tier_cells} |")
    yr = es.get("year_range", [None, None])
    lines.append(f"| Year range | {yr[0]}–{yr[1]} |")
    lines.append(f"| MS focus rate | {es['ms_focus_pct']}% |")
    lines.append(f"| Missing abstract rate | {es['missing_abstract_pct']}% |")
    lines.append(f"| Category diversity (entropy) | {es['category_entropy_normalized']} |")
    lines.append(f"| QA gate status | {gate_badge} ({es['n_audit_errors']} errors, {es['n_audit_warnings']} warnings) |")
    lines.append(f"| Topics covered | {es['n_topics']} TOPIC-XX buckets |")
    lines.append("")

    # Explain the two metrics reviewers most often misread: "MS focus rate"
    # and "Category diversity (entropy)".
    lines.append("### How to read these numbers")
    lines.append("")
    lines.append(
        "- **Tier breakdown.** `T1` = curated core seeds (primary literature). "
        "`T1-ref` = papers reached via one-hop references from seeds (cited by "
        "or citing a seed). `T2` = graph-established literature that passes "
        "cross-seed, k-core, and in-degree gates in Stage 5c. `T3` = emerging "
        "velocity literature (recent years with high citations/year). `T4` = "
        "expert-curated signal papers. `other` = anything that slipped past "
        "these buckets."
    )
    lines.append(
        "- **MS focus rate.** Fraction of the selected corpus where either the "
        "title/abstract or OpenAlex concept set contains MS-specific terminology "
        "(e.g., \"multiple sclerosis\", \"MS lesion\", DMT names). T4 expert "
        "picks are exempt from the denominator because their inclusion is "
        "already justified manually. A value near 100% means nearly every "
        "auto-selected paper is explicitly about MS rather than adjacent biology."
    )
    lines.append(
        "- **Category diversity (entropy).** Shannon entropy of the corpus "
        "distribution across the five governance categories "
        "(pathogenesis_and_immunology, imaging_and_biomarkers, "
        "clinical_trials_and_therapeutics, clinical_care_and_management, "
        "epidemiology_and_population_health), binned from each paper's TOPIC-XX "
        "code via `TOPIC_CATEGORY_MAP`, then normalized to [0, 1]. `1.0` means "
        "a perfectly balanced corpus across all five categories; `0.0` means "
        "every paper fell into a single category. Topics that map to more than "
        "one category (e.g., TOPIC-09 Progressive MS) contribute to each."
    )
    lines.append("")

    if es.get("category_mix_pct"):
        lines.append("**Category mix (%):**")
        for category, pct in sorted(es["category_mix_pct"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {category}: {pct}%")
        lines.append("")

    if es.get("top_venues"):
        lines.append("**Top venues across corpus:**")
        for entry in es["top_venues"]:
            lines.append(f"- {entry['venue']} ({entry['count']} papers)")
        lines.append("")

    if es.get("flagged_topic_codes"):
        lines.append("**Topics requiring reviewer attention:**")
        for code in es["flagged_topic_codes"]:
            lines.append(f"- `{code}` {TOPIC_LABELS.get(code, '')}".rstrip())
        lines.append("")

    # --- QA/QC Digest ---
    lines.append("## QA / QC Digest")
    lines.append("")
    errors = audit_report.get("errors", [])
    warnings = audit_report.get("warnings", [])
    if errors:
        lines.append("### Gate Failures")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")
    if warnings:
        lines.append("### Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    if not errors and not warnings:
        lines.append("All gates passed. No warnings recorded.")
        lines.append("")

    # --- Per-Topic Briefs ---
    lines.append("## Per-Topic Expert Briefs")
    lines.append("")
    lines.append(
        "Each section covers one TOPIC-XX bucket from the v1.3 MS Field "
        "Orientation Guide taxonomy. Papers are grouped by their "
        "`primary_topic_code` as assigned in Stage 5b. The top-10 papers are "
        "ranked by composite importance score (PageRank + citation-age "
        "normalization). Reviewer flags highlight coverage or quality concerns "
        "that warrant a manual check."
    )
    lines.append("")
    for brief in sorted(topic_briefs, key=lambda b: b["topic_code"]):
        lines.append(_render_topic_brief_md(brief))

    # --- Action Items ---
    lines.append("## Action Items for Reviewers")
    lines.append("")
    lines.append(
        "1. Verify flagged topics above for coverage gaps — especially topics with fewer than 3 recent papers.\n"
        "2. Spot-check low-confidence AI summaries (listed per topic above).\n"
        "3. Review any QA gate failures or warnings in the QA/QC Digest.\n"
        "4. Confirm that T4 expert-signal papers are correctly attributed to their topic.\n"
        "5. Suggest additions via the seed intake governance checklist "
        "(`SEED_INTAKE_GOVERNANCE.md`) before the next pipeline run."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(config_path: str) -> None:
    """Generate expert review packets and write to outputs/expert_comms/."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    out_dir = root / cfg["output_dir"]
    comms_dir = out_dir / "expert_comms"
    ensure_dir(comms_dir)

    # Load audit report
    audit_path = out_dir / "audit" / "kb_audit_report.json"
    if not audit_path.exists():
        raise FileNotFoundError(
            f"Audit report not found: {audit_path}. Run stage 9 (audit_kb) first."
        )
    with open(audit_path, encoding="utf-8") as f:
        audit_report: dict[str, Any] = json.load(f)

    # Load the post-selection corpus written by Stage 5c. Prefer the T4-tracked
    # file so the tier breakdown sees curated picks. Fall back to the narrower
    # selected file, and only then to the raw scored corpus for dev debugging.
    graph_dir = out_dir / "graph"
    tracked_path = graph_dir / "core_corpus_tracked_with_t4.csv"
    selected_path = graph_dir / "core_corpus_selected.csv"
    scored_path = graph_dir / "scored_papers.csv"
    if tracked_path.exists():
        corpus_source = "core_corpus_tracked_with_t4.csv"
        corpus = pd.read_csv(tracked_path, low_memory=False)
    elif selected_path.exists():
        corpus_source = "core_corpus_selected.csv"
        corpus = pd.read_csv(selected_path, low_memory=False)
    elif scored_path.exists():
        corpus_source = "scored_papers.csv (pre-selection fallback)"
        scored = pd.read_csv(scored_path, low_memory=False)
        scored["in_final_corpus"] = scored.get("in_final_corpus", 0).fillna(0).astype(int)
        corpus = scored[scored["in_final_corpus"] == 1].copy()
    else:
        raise FileNotFoundError(
            f"No corpus CSV found in {graph_dir}. Run Stage 5c before Stage 10."
        )
    if corpus.empty:
        raise RuntimeError(f"No papers in final corpus ({corpus_source}) — cannot generate expert comms.")
    corpus["canonical_paper_id"] = corpus["canonical_paper_id"].astype(str)

    # Ensure primary_topic_code is present — tracked_with_t4 carries it from
    # Stage 5c, but the fallback files may not, so merge from topic_evidence.
    topics_dir = out_dir / "topics"
    topic_evidence_path = topics_dir / "paper_topic_evidence.csv"
    if "primary_topic_code" not in corpus.columns and topic_evidence_path.exists():
        topic_evidence = pd.read_csv(
            topic_evidence_path,
            usecols=["canonical_paper_id", "primary_topic_code"],
            low_memory=False,
        )
        topic_evidence["canonical_paper_id"] = topic_evidence["canonical_paper_id"].astype(str)
        corpus = corpus.merge(topic_evidence, on="canonical_paper_id", how="left")

    # Load distilled summaries if available
    summaries_path = out_dir / "distilled" / "paper_summaries.csv"
    summaries = pd.DataFrame()
    if summaries_path.exists():
        summaries = pd.read_csv(summaries_path, low_memory=False)
        summaries["canonical_paper_id"] = summaries["canonical_paper_id"].astype(str)

    # Group briefs by TOPIC-XX code (not by Leiden cluster ID). Each paper's
    # primary_topic_code comes from the topic_evidence CSV written at Stage 5b.
    topic_codes_series = corpus.get("primary_topic_code", pd.Series("", index=corpus.index)).fillna("")
    corpus["_topic_code"] = topic_codes_series.map(_extract_topic_code).fillna("")
    corpus.loc[corpus["_topic_code"] == "", "_topic_code"] = "UNMAPPED"

    topic_briefs: list[dict[str, Any]] = []
    for topic_code in sorted(corpus["_topic_code"].unique()):
        label = TOPIC_LABELS.get(topic_code, "Unmapped" if topic_code == "UNMAPPED" else topic_code)
        topic_papers = corpus[corpus["_topic_code"] == topic_code].copy()
        brief = _build_topic_brief(topic_code, label, topic_papers, summaries)
        topic_briefs.append(brief)

    # Thread the corpus source into the audit report so it appears verbatim in
    # the exec summary even when we fell through to a fallback CSV.
    audit_report.setdefault("corpus_source", corpus_source)

    exec_summary = _build_executive_summary(corpus, audit_report, topic_briefs)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Write JSON payload
    payload: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "executive_summary": exec_summary,
        "topic_briefs": topic_briefs,
        "audit_report": audit_report,
    }
    save_json(payload, comms_dir / "expert_comms_report.json")

    # Write Markdown report
    md = _render_full_report_md(exec_summary, topic_briefs, audit_report, generated_at)
    (comms_dir / "expert_comms_report.md").write_text(md, encoding="utf-8")

    n_flagged = len(exec_summary.get("flagged_topic_codes", []))
    gate = "PASS" if exec_summary["audit_passed"] else "FAIL"
    print(
        f"Expert comms report written to {comms_dir} "
        f"| Corpus: {exec_summary['n_papers']} papers "
        f"| Topics: {exec_summary['n_topics']} "
        f"| QA: {gate} "
        f"| Flagged topics: {n_flagged}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()
    run(args.config)
