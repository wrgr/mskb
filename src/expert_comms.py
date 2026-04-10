"""Generate domain-expert review packets from v1.3 pipeline outputs.

Reads the audit report, scored corpus, topic clusters, and distilled summaries
and writes a structured Markdown + JSON reviewer packet to outputs/expert_comms/.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import ensure_dir, load_config, save_json


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
    """Derive a human-readable tier label from row flags."""
    if _safe_int(row.get("in_t4_expert_signal"), 0):
        return "T4"
    if _safe_int(row.get("is_seed"), 0):
        return "T1"
    tier = _safe_str(row.get("tier"))
    if tier == "velocity":
        return "T3"
    return "T2"


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
    topic_id: str,
    label: str,
    papers: pd.DataFrame,
    summaries: pd.DataFrame,
) -> dict[str, Any]:
    """Build an expert review dict for one topic cluster."""
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
        "topic_id": topic_id,
        "label": label,
        "n_papers": len(papers),
        "year_span": [yr_min, yr_max],
        "n_recent": n_recent,
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

    # Tier breakdown
    tier_counts: Counter = Counter()
    for _, row in corpus.iterrows():
        tier_counts[_tier_label(row)] += 1

    yr_min, yr_max = _year_span(corpus)

    # Top venues across the whole corpus
    top_corpus_venues = _top_venues(corpus, k=8)

    # Topics flagged with issues
    flagged_topics = [b["label"] for b in topic_briefs if b["flags"]]

    gm = audit_report.get("gate_metrics", {})
    return {
        "n_papers": n_total,
        "tier_breakdown": dict(tier_counts),
        "year_range": [yr_min, yr_max],
        "top_venues": [{"venue": v, "count": c} for v, c in top_corpus_venues],
        "ms_focus_pct": round(_safe_float(gm.get("ms_focus_pct")), 2),
        "missing_abstract_pct": round(_safe_float(gm.get("missing_abstract_pct")), 2),
        "category_entropy_normalized": round(_safe_float(audit_report.get("category_entropy_normalized")), 4),
        "audit_passed": bool(audit_report.get("passed", False)),
        "n_audit_errors": len(audit_report.get("errors", [])),
        "n_audit_warnings": len(audit_report.get("warnings", [])),
        "n_topics": len(topic_briefs),
        "flagged_topics": flagged_topics,
    }


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------


def _render_topic_brief_md(brief: dict[str, Any]) -> str:
    """Render one topic brief as Markdown."""
    lines: list[str] = []
    yr = brief.get("year_span", [None, None])
    yr_str = f"{yr[0]}–{yr[1]}" if yr[0] else "n/a"
    lines.append(f"## {brief['label']} (`{brief['topic_id']}`)")
    lines.append("")
    lines.append(
        f"**{brief['n_papers']} papers** | "
        f"Year span: {yr_str} | "
        f"Recent (≥2020): {brief.get('n_recent', 0)}"
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
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Final corpus size | {es['n_papers']} papers |")
    lines.append(f"| Tier breakdown | {es['tier_breakdown']} |")
    yr = es.get("year_range", [None, None])
    lines.append(f"| Year range | {yr[0]}–{yr[1]} |")
    lines.append(f"| MS focus rate | {es['ms_focus_pct']}% |")
    lines.append(f"| Missing abstract rate | {es['missing_abstract_pct']}% |")
    lines.append(f"| Category diversity (entropy) | {es['category_entropy_normalized']} |")
    lines.append(f"| QA gate status | {gate_badge} ({es['n_audit_errors']} errors, {es['n_audit_warnings']} warnings) |")
    lines.append(f"| Topics | {es['n_topics']} clusters |")
    lines.append("")

    if es.get("top_venues"):
        lines.append("**Top venues across corpus:**")
        for entry in es["top_venues"]:
            lines.append(f"- {entry['venue']} ({entry['count']} papers)")
        lines.append("")

    if es.get("flagged_topics"):
        lines.append("**Topics requiring reviewer attention:**")
        for t in es["flagged_topics"]:
            lines.append(f"- {t}")
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
        "Each section covers one algorithmically derived topic cluster. "
        "The top-10 papers are ranked by composite importance score (PageRank + citation-age normalization). "
        "Reviewer flags highlight coverage or quality concerns that warrant a manual check."
    )
    lines.append("")
    for brief in sorted(topic_briefs, key=lambda b: b["label"]):
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

    # Load scored corpus (final papers only)
    scored_path = out_dir / "graph" / "scored_papers.csv"
    if not scored_path.exists():
        raise FileNotFoundError(f"scored_papers.csv not found: {scored_path}")
    scored = pd.read_csv(scored_path, low_memory=False)
    scored["in_final_corpus"] = scored.get("in_final_corpus", 0).fillna(0).astype(int)
    corpus = scored[scored["in_final_corpus"] == 1].copy()
    if corpus.empty:
        raise RuntimeError("No papers in final corpus — cannot generate expert comms.")
    corpus["canonical_paper_id"] = corpus["canonical_paper_id"].astype(str)

    # Load topic assignments
    topics_dir = out_dir / "topics"
    topic_labels: dict[str, str] = {}
    paper_to_topic: dict[str, str] = {}
    topic_clusters_path = topics_dir / "topic_clusters.csv"
    paper_topics_path = topics_dir / "paper_topics.csv"
    if topic_clusters_path.exists():
        tc = pd.read_csv(topic_clusters_path)
        topic_labels = dict(
            zip(tc["topic_id"].astype(str), tc.get("auto_label", tc["topic_id"]).astype(str))
        )
    if paper_topics_path.exists():
        pt = pd.read_csv(paper_topics_path)
        paper_to_topic = dict(
            zip(pt["canonical_paper_id"].astype(str), pt["topic_id"].astype(str))
        )

    # Load distilled summaries if available
    summaries_path = out_dir / "distilled" / "paper_summaries.csv"
    summaries = pd.DataFrame()
    if summaries_path.exists():
        summaries = pd.read_csv(summaries_path, low_memory=False)
        summaries["canonical_paper_id"] = summaries["canonical_paper_id"].astype(str)

    # Build per-topic briefs
    corpus["_topic_id"] = corpus["canonical_paper_id"].map(paper_to_topic).fillna("unmapped")
    topic_ids = sorted(corpus["_topic_id"].unique())
    topic_briefs: list[dict[str, Any]] = []
    for tid in topic_ids:
        label = topic_labels.get(tid, f"Topic {tid}")
        topic_papers = corpus[corpus["_topic_id"] == tid].copy()
        brief = _build_topic_brief(tid, label, topic_papers, summaries)
        topic_briefs.append(brief)

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

    n_flagged = len(exec_summary.get("flagged_topics", []))
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
