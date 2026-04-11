"""Run quality audit gates against the selected core corpus and emit a report.

Categories are binned by TOPIC-XX code (via TOPIC_CATEGORY_MAP) rather than
cluster-derived ``anchor_category`` so the audit reports on the same taxonomy
used by seed governance and the expert comms packet.
"""

import argparse
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .seed_governance import TOPIC_CATEGORY_MAP, _extract_topic_code
from .utils import ensure_dir, load_config, save_json


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_counter(values: dict[str, int]) -> dict[str, float]:
    total = float(sum(max(0, int(v)) for v in values.values()))
    if total <= 0:
        return {k: 0.0 for k in values}
    return {k: float(v) / total for k, v in values.items()}


def _shannon_entropy(counts: dict[str, int]) -> float:
    p = [v for v in _normalize_counter(counts).values() if v > 0]
    if not p:
        return 0.0
    return -sum(x * math.log(x) for x in p)


def _normalized_entropy(counts: dict[str, int]) -> float:
    k = len([v for v in counts.values() if int(v) > 0])
    if k <= 1:
        return 0.0
    return _shannon_entropy(counts) / math.log(k)


def _has_source_link(row: pd.Series) -> bool:
    doi = str(row.get("doi", "") or "").strip()
    if doi and doi.lower() != "nan":
        return True
    openalex_id = str(row.get("openalex_id", "") or "").strip()
    if openalex_id and openalex_id.lower() != "nan":
        return True
    all_openalex = str(row.get("all_openalex_ids", "") or "").strip()
    return bool(all_openalex and all_openalex.lower() != "nan")


def _is_unmapped_topic(value: object) -> bool:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return True
    return text.upper() == "UNMAPPED"


def _bin_by_topic_category(topic_codes: pd.Series) -> dict[str, int]:
    """Return category -> count by mapping each TOPIC-XX code through TOPIC_CATEGORY_MAP.

    A topic that maps to multiple categories contributes to each (like seed
    governance quotas). Unmapped or missing topic codes are bucketed under
    ``unmapped`` so reviewers can see them explicitly.
    """
    counts: dict[str, int] = {cat: 0 for cat in (
        "pathogenesis_and_immunology",
        "imaging_and_biomarkers",
        "clinical_trials_and_therapeutics",
        "clinical_care_and_management",
        "epidemiology_and_population_health",
    )}
    counts["unmapped"] = 0
    for value in topic_codes.fillna("").astype(str):
        code = _extract_topic_code(value)
        mapped = TOPIC_CATEGORY_MAP.get(code, [])
        if not mapped:
            counts["unmapped"] += 1
            continue
        for category in mapped:
            counts[category] = counts.get(category, 0) + 1
    return counts


def _top_records(df: pd.DataFrame, score_col: str, k: int = 15) -> list[dict]:
    if score_col not in df.columns or df.empty:
        return []
    d = df.copy()
    d[score_col] = pd.to_numeric(d[score_col], errors="coerce").fillna(0.0)
    d = d.sort_values(score_col, ascending=False).head(k)
    rows = []
    for _, row in d.iterrows():
        rows.append(
            {
                "canonical_paper_id": str(row.get("canonical_paper_id", "")),
                "title": str(row.get("title", "") or ""),
                "year": _safe_int(row.get("year"), 0),
                "score": round(_safe_float(row.get(score_col), 0.0), 6),
                "citation_count": _safe_int(row.get("merged_cited_by_count"), 0),
                "pagerank": round(_safe_float(row.get("pagerank"), 0.0), 9),
                "evidence_type": str(row.get("evidence_type", "") or ""),
            }
        )
    return rows


def _build_markdown_report(report: dict) -> str:
    lines = []
    lines.append("# KB Audit Report")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at_utc']}`")
    lines.append(f"- Corpus source: `{report.get('corpus_source', 'unknown')}`")
    lines.append(f"- Final corpus size: `{report['n_final_corpus']}`")
    lines.append(f"- Gates passed: `{report['passed']}`")
    lines.append("")
    lines.append("## Gate Metrics")
    gm = report.get("gate_metrics", {})
    lines.append(f"- `% has_ms_focus`: `{gm.get('ms_focus_pct', 0):.2f}%`")
    lines.append(
        f"- `ms_focus` denominator: `{gm.get('ms_focus_eval_count', 0)}` "
        f"(T4-exempt count: `{gm.get('ms_focus_exempt_t4_count', 0)}`)"
    )
    lines.append(f"- `biology_no_ms_link` (final count): `{gm.get('biology_no_ms_link_count', 0)}`")
    lines.append(f"- Missing abstract rate: `{gm.get('missing_abstract_pct', 0):.2f}%`")
    lines.append(f"- Missing source-link rate: `{gm.get('missing_source_link_pct', 0):.2f}%`")
    lines.append(
        f"- Missing topic assignment (screened corpus): "
        f"`{gm.get('unmapped_topic_count', 0)}` "
        f"(`{gm.get('unmapped_topic_pct', 0):.2f}%`)"
    )
    lines.append("")
    lines.append("## Category Mix")
    lines.append(f"- Normalized entropy: `{report.get('category_entropy_normalized', 0):.4f}`")
    lines.append(f"- Distribution: `{report.get('category_mix_pct', {})}`")
    lines.append("")
    lines.append("## Centrality Views")
    lines.append("- Top papers by `paper_importance_score` and `age_normalized_importance_score` are both written to JSON.")
    lines.append("")
    if report.get("errors"):
        lines.append("## Gate Failures")
        for err in report["errors"]:
            lines.append(f"- {err}")
        lines.append("")
    if report.get("warnings"):
        lines.append("## Warnings")
        for w in report["warnings"]:
            lines.append(f"- {w}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def run(config_path: str) -> None:
    """Run KB quality audit gates and write a JSON and Markdown report to the audit directory."""
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    outdir = root / cfg["output_dir"] / "audit"
    ensure_dir(outdir)

    # Prefer the post-selection core corpus (T1+T2+T3+T4 from Stage 5c) over the
    # raw scored output. Fall back to the scored file only if Stage 5c hasn't run,
    # so the audit still runs for developers debugging earlier stages.
    graph_dir = root / cfg["output_dir"] / "graph"
    tracked_path = graph_dir / "core_corpus_tracked_with_t4.csv"
    selected_path = graph_dir / "core_corpus_selected.csv"
    scored_path = graph_dir / "scored_papers.csv"
    if tracked_path.exists():
        corpus_source = "core_corpus_tracked_with_t4.csv"
        final = pd.read_csv(tracked_path, low_memory=False)
    elif selected_path.exists():
        corpus_source = "core_corpus_selected.csv"
        final = pd.read_csv(selected_path, low_memory=False)
    elif scored_path.exists():
        corpus_source = "scored_papers.csv (pre-selection fallback)"
        scored = pd.read_csv(scored_path, low_memory=False)
        scored["in_final_corpus"] = scored.get("in_final_corpus", 0).fillna(0).astype(int)
        final = scored[scored["in_final_corpus"] == 1].copy()
    else:
        raise FileNotFoundError(
            f"No corpus CSV found in {graph_dir}. Run Stages 4/5c before Stage 9."
        )
    if final.empty:
        raise RuntimeError(f"No papers in final corpus ({corpus_source})")
    final = final.copy()

    gcfg = (cfg.get("governance", {}) or {}).get("audit_gates", {}) or {}
    fail_on_error = bool(gcfg.get("fail_on_error", True))
    min_ms_focus_pct = _safe_float(gcfg.get("min_ms_focus_pct", 75.0), 75.0)
    max_biology_no_ms_link = _safe_int(gcfg.get("max_biology_no_ms_link", 0), 0)
    max_missing_abstract_pct = _safe_float(gcfg.get("max_missing_abstract_pct", 25.0), 25.0)
    missing_abstract_policy = str(gcfg.get("missing_abstract_policy", "error") or "error").strip().lower()
    max_missing_source_link_pct = _safe_float(gcfg.get("max_missing_source_link_pct", 5.0), 5.0)
    enforce_category_bounds = bool(gcfg.get("enforce_category_bounds", True))

    errors: list[str] = []
    warnings: list[str] = []

    t4_exempt_mask = final.get("ms_focus_exempt_t4", pd.Series(False, index=final.index)).fillna(False).astype(bool)
    if not t4_exempt_mask.any() and "in_t4_expert_signal" in final.columns:
        t4_exempt_mask = final["in_t4_expert_signal"].fillna(False).astype(bool)

    focus_eval = final[~t4_exempt_mask].copy()
    has_ms_focus = focus_eval.get("has_ms_focus", pd.Series(False, index=focus_eval.index)).fillna(False).astype(bool)
    ms_focus_eval_count = int(len(focus_eval))
    ms_focus_exempt_count = int(t4_exempt_mask.sum())
    ms_focus_pct = float(has_ms_focus.mean() * 100.0) if ms_focus_eval_count > 0 else 100.0
    if ms_focus_pct < min_ms_focus_pct:
        errors.append(
            f"ms_focus_pct below threshold: {ms_focus_pct:.2f}% < {min_ms_focus_pct:.2f}% "
            f"(evaluated on non-exempt papers: {ms_focus_eval_count}, exempt_t4={ms_focus_exempt_count})"
        )

    biology_no_ms_link_count = int(
        final.get("biology_no_ms_link", pd.Series(False, index=final.index)).fillna(False).astype(bool).sum()
    )
    if biology_no_ms_link_count > max_biology_no_ms_link:
        errors.append(
            f"biology_no_ms_link count above threshold: {biology_no_ms_link_count} > {max_biology_no_ms_link}"
        )

    abstract_present = ~(
        final.get("abstract", pd.Series("", index=final.index)).isna()
        | final.get("abstract", pd.Series("", index=final.index)).astype(str).str.strip().str.lower().isin(["", "nan"])
    )
    missing_abstract_pct = float((1.0 - abstract_present.mean()) * 100.0)
    if missing_abstract_pct > max_missing_abstract_pct:
        message = f"missing abstract rate above threshold: {missing_abstract_pct:.2f}% > {max_missing_abstract_pct:.2f}%"
        if missing_abstract_policy == "todo":
            warnings.append(f"{message} (tracked as TODO, not a hard failure)")
        else:
            errors.append(message)

    has_link = final.apply(_has_source_link, axis=1)
    missing_source_link_pct = float((1.0 - has_link.mean()) * 100.0)
    if missing_source_link_pct > max_missing_source_link_pct:
        errors.append(
            f"missing source-link rate above threshold: {missing_source_link_pct:.2f}% > {max_missing_source_link_pct:.2f}%"
        )

    # Merge topic evidence so we can bin by TOPIC-XX (the taxonomy used by seed
    # governance and expert comms) rather than the cluster-derived anchor_category.
    topic_evidence_path = root / cfg["output_dir"] / "topics" / "paper_topic_evidence.csv"
    unmapped_topic_count = 0
    unmapped_topic_pct = 0.0
    unmapped_topic_sample: list[dict] = []
    unmapped_path = outdir / "final_corpus_unmapped_topics.csv"
    unmapped_mask: pd.Series = pd.Series(False, index=final.index)
    final["canonical_paper_id"] = final["canonical_paper_id"].astype(str)
    if topic_evidence_path.exists():
        topic_evidence = pd.read_csv(
            topic_evidence_path,
            usecols=["canonical_paper_id", "primary_topic_code", "topic_assignment_method"],
            low_memory=False,
        )
        topic_evidence["canonical_paper_id"] = topic_evidence["canonical_paper_id"].astype(str)
        # Only merge columns the tracked corpus doesn't already carry so we
        # preserve any primary_topic_code that was written at Stage 5c.
        merge_cols = ["canonical_paper_id"]
        if "primary_topic_code" not in final.columns:
            merge_cols.append("primary_topic_code")
        if "topic_assignment_method" not in final.columns:
            merge_cols.append("topic_assignment_method")
        if len(merge_cols) > 1:
            final = final.merge(topic_evidence[merge_cols], on="canonical_paper_id", how="left")

        topic_series = final.get("primary_topic_code", pd.Series("", index=final.index))
        unmapped_mask = topic_series.map(_is_unmapped_topic)
        unmapped = final[unmapped_mask].copy()
        unmapped_topic_count = int(len(unmapped))
        unmapped_topic_pct = float((unmapped_topic_count / max(1, len(final))) * 100.0)
        if not unmapped.empty:
            keep_cols = [
                "canonical_paper_id",
                "title",
                "year",
                "doi",
                "openalex_id",
                "topic_assignment_method",
                "primary_topic_code",
                "paper_importance_score",
            ]
            existing_cols = [c for c in keep_cols if c in unmapped.columns]
            unmapped[existing_cols].to_csv(unmapped_path, index=False)
            unmapped_topic_sample = [
                {
                    "canonical_paper_id": str(row.get("canonical_paper_id", "")),
                    "title": str(row.get("title", "") or ""),
                    "topic_assignment_method": str(row.get("topic_assignment_method", "") or ""),
                }
                for _, row in unmapped.head(15).iterrows()
            ]
            warnings.append(
                "papers pass screening but are missing topic assignment: "
                f"{unmapped_topic_count} / {len(final)} ({unmapped_topic_pct:.2f}%). "
                f"See {unmapped_path}"
            )
        else:
            pd.DataFrame(
                columns=[
                    "canonical_paper_id",
                    "title",
                    "year",
                    "doi",
                    "openalex_id",
                    "topic_assignment_method",
                    "primary_topic_code",
                    "paper_importance_score",
                ]
            ).to_csv(unmapped_path, index=False)
    else:
        warnings.append(f"topic evidence missing: {topic_evidence_path} (cannot check unmapped topic assignments)")

    # Bin the final corpus by TOPIC-XX via TOPIC_CATEGORY_MAP. Topics mapped to
    # multiple categories contribute to each (consistent with seed governance),
    # so category_counts can total more than n_final_corpus — we normalize by
    # the cross-category total so percentages still sum to ~100%.
    topic_code_series = final.get("primary_topic_code", pd.Series("", index=final.index))
    category_counts = _bin_by_topic_category(topic_code_series)
    category_mix_pct = {k: round(v * 100.0, 2) for k, v in _normalize_counter(category_counts).items()}
    category_entropy = _shannon_entropy(category_counts)
    category_entropy_normalized = _normalized_entropy(category_counts)

    target_ranges = (((cfg.get("scoring", {}) or {}).get("topic_balance", {}) or {}).get("target_ranges", {}) or {})
    if enforce_category_bounds and target_ranges:
        # Percentages are taken over the cross-category total (counts may double-
        # assign a paper whose TOPIC-XX maps to multiple governance categories),
        # matching category_mix_pct so reviewers see the same numbers in both places.
        total_cat_count = max(1, sum(int(v) for v in category_counts.values()))
        for category, bounds in target_ranges.items():
            if not isinstance(bounds, dict):
                continue
            observed_pct = (category_counts.get(category, 0) / total_cat_count) * 100.0
            min_pct = _safe_float(bounds.get("min_pct", 0.0), 0.0) * 100.0
            max_pct = _safe_float(bounds.get("max_pct", 1.0), 1.0) * 100.0
            if observed_pct < min_pct or observed_pct > max_pct:
                errors.append(
                    f"category '{category}' out of bounds: {observed_pct:.2f}% not in [{min_pct:.2f}%, {max_pct:.2f}%]"
                )

    if "age_normalized_importance_score" not in final.columns:
        warnings.append("age_normalized_importance_score missing; side-by-side ranking is unavailable")

    # Build a per-paper hold list: papers that flagged at least one soft issue.
    # These pass through all gates so the pipeline can complete; reviewers can
    # inspect held_papers.csv after the run before promoting the corpus.
    hold_reasons: dict[str, list[str]] = {}

    bio_no_ms_mask = final.get("biology_no_ms_link", pd.Series(False, index=final.index)).fillna(False).astype(bool)
    for pid in final.loc[bio_no_ms_mask, "canonical_paper_id"].tolist():
        hold_reasons.setdefault(str(pid), []).append("biology_no_ms_link")

    no_link_mask = ~final.apply(_has_source_link, axis=1)
    for pid in final.loc[no_link_mask, "canonical_paper_id"].tolist():
        hold_reasons.setdefault(str(pid), []).append("missing_source_link")

    no_abstract_mask = ~abstract_present
    for pid in final.loc[no_abstract_mask, "canonical_paper_id"].tolist():
        hold_reasons.setdefault(str(pid), []).append("missing_abstract")

    for pid in final.loc[unmapped_mask, "canonical_paper_id"].tolist():
        hold_reasons.setdefault(str(pid), []).append("unmapped_topic")

    held_papers_path = outdir / "held_papers.csv"
    if hold_reasons:
        hold_rows = [
            {"canonical_paper_id": pid, "hold_reasons": "; ".join(reasons)}
            for pid, reasons in sorted(hold_reasons.items())
        ]
        pd.DataFrame(hold_rows).to_csv(held_papers_path, index=False)
        warnings.append(
            f"{len(hold_reasons)} paper(s) flagged for manual review — see {held_papers_path}"
        )
    else:
        pd.DataFrame(columns=["canonical_paper_id", "hold_reasons"]).to_csv(held_papers_path, index=False)

    held_paper_count = len(hold_reasons)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_source": corpus_source,
        "n_final_corpus": int(len(final)),
        "gate_metrics": {
            "ms_focus_pct": round(ms_focus_pct, 4),
            "ms_focus_eval_count": ms_focus_eval_count,
            "ms_focus_exempt_t4_count": ms_focus_exempt_count,
            "biology_no_ms_link_count": int(biology_no_ms_link_count),
            "missing_abstract_pct": round(missing_abstract_pct, 4),
            "missing_source_link_pct": round(missing_source_link_pct, 4),
            "unmapped_topic_count": int(unmapped_topic_count),
            "unmapped_topic_pct": round(unmapped_topic_pct, 4),
            "missing_abstract_policy": missing_abstract_policy,
            "held_paper_count": int(held_paper_count),
        },
        "category_mix_pct": category_mix_pct,
        "category_counts": {k: int(v) for k, v in category_counts.items()},
        "category_entropy": round(category_entropy, 6),
        "category_entropy_normalized": round(category_entropy_normalized, 6),
        "unmapped_topic_sample": unmapped_topic_sample,
        "top_by_paper_importance": _top_records(final, "paper_importance_score", k=15),
        "top_by_age_normalized_importance": _top_records(final, "age_normalized_importance_score", k=15),
        "errors": errors,
        "warnings": warnings,
        "passed": len(errors) == 0,
    }

    save_json(report, outdir / "kb_audit_report.json")
    (outdir / "kb_audit_report.md").write_text(_build_markdown_report(report), encoding="utf-8")

    status = "PASS" if report["passed"] else "FAIL"
    print(f"KB audit gates: {status} ({len(errors)} errors, {len(warnings)} warnings)")
    if errors:
        for err in errors:
            print(f"  - {err}")
    if fail_on_error and errors:
        raise RuntimeError("KB audit gates failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
