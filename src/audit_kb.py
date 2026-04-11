"""Run quality audit gates against the scored paper corpus and emit a report."""

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .utils import ensure_dir, load_config, load_downstream_corpus, save_json


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


def _normalize_topic_code(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper == "UNMAPPED":
        return "UNMAPPED"
    match_topic = re.match(r"^TOPIC-(\d{2})$", upper)
    if match_topic:
        return f"TOPIC-{match_topic.group(1)}"
    return ""


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
    lines.append(
        f"- Review cross-sectional cluster: "
        f"`{gm.get('review_cluster_count', 0)}` "
        f"(`{gm.get('review_cluster_pct', 0):.2f}%`)"
    )
    lines.append("")
    lines.append("## Category Mix")
    lines.append(f"- Normalized entropy: `{report.get('category_entropy_normalized', 0):.4f}`")
    lines.append(f"- Distribution: `{report.get('category_mix_pct', {})}`")
    lines.append("")
    lines.append("## Topic Mix")
    lines.append(f"- Distribution: `{report.get('topic_mix_pct', {})}`")
    topic_bounds = report.get("topic_bounds", {}) or {}
    if topic_bounds:
        lines.append(
            "- Topic bounds gate: "
            f"`enabled={topic_bounds.get('enabled', False)}`, "
            f"`min_pct={topic_bounds.get('min_pct', 0):.2f}`, "
            f"`max_pct={topic_bounds.get('max_pct', 0):.2f}`, "
            f"`include_unmapped={topic_bounds.get('include_unmapped', False)}`"
        )
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

    graph_dir = root / cfg["output_dir"] / "graph"
    final, source_path = load_downstream_corpus(graph_dir)
    if final.empty:
        raise RuntimeError("No papers in final corpus")

    gcfg = (cfg.get("governance", {}) or {}).get("audit_gates", {}) or {}
    fail_on_error = bool(gcfg.get("fail_on_error", True))
    min_ms_focus_pct = _safe_float(gcfg.get("min_ms_focus_pct", 75.0), 75.0)
    max_biology_no_ms_link = _safe_int(gcfg.get("max_biology_no_ms_link", 0), 0)
    max_missing_abstract_pct = _safe_float(gcfg.get("max_missing_abstract_pct", 25.0), 25.0)
    missing_abstract_policy = str(gcfg.get("missing_abstract_policy", "error") or "error").strip().lower()
    max_missing_source_link_pct = _safe_float(gcfg.get("max_missing_source_link_pct", 5.0), 5.0)
    enforce_category_bounds = bool(gcfg.get("enforce_category_bounds", True))
    enforce_topic_bounds = bool(gcfg.get("enforce_topic_bounds", False))
    topic_min_pct = _safe_float(gcfg.get("topic_min_pct", 1.0), 1.0)
    topic_max_pct = _safe_float(gcfg.get("topic_max_pct", 10.0), 10.0)
    topic_bounds_use_rebalance = bool(gcfg.get("topic_bounds_use_rebalance_from_selection_summary", True))
    topic_under_min_warn_if_observed_pct_at_least = _safe_float(
        gcfg.get("topic_under_min_warn_if_observed_pct_at_least", 2.0), 2.0
    )
    topic_bounds_include_unmapped = bool(gcfg.get("topic_bounds_include_unmapped", False))
    topic_expected_codes_raw = gcfg.get("topic_expected_codes", [])
    topic_expected_codes = []
    if isinstance(topic_expected_codes_raw, (list, tuple)):
        for code in topic_expected_codes_raw:
            if not str(code).strip():
                continue
            normalized = _normalize_topic_code(code)
            if not normalized:
                raise ValueError(
                    f"Invalid topic_expected_codes entry '{code}'. "
                    "Use TOPIC-## codes (or UNMAPPED) only."
                )
            topic_expected_codes.append(normalized)

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

    category_series = final.get("anchor_category", pd.Series("unmapped", index=final.index)).fillna("unmapped")
    category_counts = category_series.astype(str).value_counts().to_dict()
    category_mix_pct = {k: round(v * 100.0, 2) for k, v in _normalize_counter(category_counts).items()}
    category_entropy = _shannon_entropy(category_counts)
    category_entropy_normalized = _normalized_entropy(category_counts)

    topic_evidence_path = root / cfg["output_dir"] / "topics" / "paper_topic_evidence.csv"
    topic_counts: dict[str, int] = {}
    topic_mix_pct: dict[str, float] = {}
    topic_gap_notes: list[dict[str, object]] = []
    unmapped_topic_count = 0
    unmapped_topic_pct = 0.0
    review_cluster_count = 0
    review_cluster_pct = 0.0
    unmapped_topic_sample: list[dict] = []
    unmapped_path = outdir / "final_corpus_unmapped_topics.csv"
    if topic_evidence_path.exists():
        topic_evidence = pd.read_csv(
            topic_evidence_path,
            usecols=lambda c: c in {"canonical_paper_id", "primary_topic_code", "topic_assignment_method", "topic_cluster"},
            low_memory=False,
        )
        topic_evidence["canonical_paper_id"] = topic_evidence["canonical_paper_id"].astype(str)
        topic_evidence = topic_evidence.rename(
            columns={
                "primary_topic_code": "evidence_primary_topic_code",
                "topic_assignment_method": "evidence_topic_assignment_method",
                "topic_cluster": "evidence_topic_cluster",
            }
        )

        final_topic = final.copy()
        final_topic["canonical_paper_id"] = final_topic["canonical_paper_id"].astype(str)
        final_topic = final_topic.merge(topic_evidence, on="canonical_paper_id", how="left")
        final_topic["primary_topic_code"] = (
            final_topic.get("primary_topic_code", pd.Series("", index=final_topic.index))
            .fillna("")
            .astype(str)
            .str.strip()
        )
        final_topic["primary_topic_code"] = final_topic["primary_topic_code"].where(
            final_topic["primary_topic_code"] != "",
            final_topic.get("evidence_primary_topic_code", pd.Series("", index=final_topic.index)).fillna("").astype(str).str.strip(),
        )
        final_topic["topic_assignment_method"] = (
            final_topic.get("topic_assignment_method", pd.Series("", index=final_topic.index))
            .fillna("")
            .astype(str)
            .str.strip()
        )
        final_topic["topic_assignment_method"] = final_topic["topic_assignment_method"].where(
            final_topic["topic_assignment_method"] != "",
            final_topic.get("evidence_topic_assignment_method", pd.Series("", index=final_topic.index)).fillna("").astype(str).str.strip(),
        )
        final_topic["topic_cluster"] = (
            final_topic.get("topic_cluster", pd.Series("", index=final_topic.index))
            .fillna("")
            .astype(str)
            .str.strip()
        )
        final_topic["topic_cluster"] = final_topic["topic_cluster"].where(
            final_topic["topic_cluster"] != "",
            final_topic.get("evidence_topic_cluster", pd.Series("", index=final_topic.index)).fillna("").astype(str).str.strip(),
        )

        cluster_series = final_topic.get("topic_cluster", pd.Series("", index=final_topic.index)).fillna("").astype(str).str.upper()
        review_cluster_mask = cluster_series == "REVIEW_CLUSTER"
        topic_series = final_topic.get("primary_topic_code", pd.Series("", index=final_topic.index))
        topic_series = topic_series.fillna("").astype(str).str.strip().map(_normalize_topic_code)
        topic_series = topic_series.apply(lambda v: "UNMAPPED" if _is_unmapped_topic(v) else v)

        topic_series_for_mix = topic_series.copy()
        topic_series_for_mix.loc[review_cluster_mask] = "REVIEW_CLUSTER"
        topic_counts = topic_series_for_mix.value_counts().to_dict()
        topic_mix_pct = {k: round(v * 100.0, 2) for k, v in _normalize_counter(topic_counts).items()}
        unmapped_mask = topic_series.map(_is_unmapped_topic) & ~review_cluster_mask
        unmapped = final_topic[unmapped_mask].copy()
        unmapped_topic_count = int(len(unmapped))
        unmapped_topic_pct = float((unmapped_topic_count / max(1, len(final_topic))) * 100.0)
        review_cluster_count = int(review_cluster_mask.sum())
        review_cluster_pct = float((review_cluster_count / max(1, len(final_topic))) * 100.0)
        if not unmapped.empty:
            keep_cols = [
                "canonical_paper_id",
                "title",
                "year",
                "doi",
                "openalex_id",
                "topic_assignment_method",
                "anchor_category",
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
                f"{unmapped_topic_count} / {len(final_topic)} ({unmapped_topic_pct:.2f}%). "
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
                    "anchor_category",
                    "paper_importance_score",
                ]
            ).to_csv(unmapped_path, index=False)
    else:
        warnings.append(f"topic evidence missing: {topic_evidence_path} (cannot check unmapped topic assignments)")

    target_ranges = (((cfg.get("scoring", {}) or {}).get("topic_balance", {}) or {}).get("target_ranges", {}) or {})
    if enforce_category_bounds and target_ranges:
        total = max(1, len(final))
        for category, bounds in target_ranges.items():
            if not isinstance(bounds, dict):
                continue
            observed_pct = (category_counts.get(category, 0) / total) * 100.0
            min_pct = _safe_float(bounds.get("min_pct", 0.0), 0.0) * 100.0
            max_pct = _safe_float(bounds.get("max_pct", 1.0), 1.0) * 100.0
            if observed_pct < min_pct or observed_pct > max_pct:
                errors.append(
                    f"category '{category}' out of bounds: {observed_pct:.2f}% not in [{min_pct:.2f}%, {max_pct:.2f}%]"
                )

    if enforce_topic_bounds:
        if not topic_counts:
            errors.append(f"topic bounds enabled but topic evidence is unavailable: {topic_evidence_path}")
        else:
            topic_scope_size = max(1, len(final) - review_cluster_count)
            effective_topic_min_pct = float(topic_min_pct)
            effective_topic_max_pct = float(topic_max_pct)
            if topic_bounds_use_rebalance:
                selection_summary_path = graph_dir / "core_corpus_selection_summary.json"
                if selection_summary_path.exists():
                    try:
                        summary = json.loads(selection_summary_path.read_text(encoding="utf-8"))
                        rebalance = ((summary.get("rules", {}) or {}).get("rebalance", {}) or {})
                        min_count = _safe_int(rebalance.get("min_count", 0), 0)
                        max_count = _safe_int(rebalance.get("max_count", 0), 0)
                        if min_count > 0:
                            effective_topic_min_pct = (float(min_count) / float(topic_scope_size)) * 100.0
                        if max_count > 0:
                            effective_topic_max_pct = (float(max_count) / float(topic_scope_size)) * 100.0
                    except Exception as exc:
                        warnings.append(
                            f"failed to load rebalance bounds from {selection_summary_path}: {type(exc).__name__}"
                        )
            bounds_counts = {
                topic: count
                for topic, count in topic_counts.items()
                if topic != "REVIEW_CLUSTER"
            }
            if topic_expected_codes:
                topics_to_check = topic_expected_codes
            else:
                topics_to_check = sorted(bounds_counts.keys())
            for topic_code in topics_to_check:
                if not topic_bounds_include_unmapped and _is_unmapped_topic(topic_code):
                    continue
                observed_pct = (bounds_counts.get(topic_code, 0) / topic_scope_size) * 100.0
                if observed_pct < effective_topic_min_pct:
                    # Permissive floor policy: treat thin-literature topics as warnings
                    # when they still retain at least 2% share.
                    if observed_pct >= topic_under_min_warn_if_observed_pct_at_least:
                        warnings.append(
                            f"topic '{topic_code}' below minimum: {observed_pct:.2f}% < {effective_topic_min_pct:.2f}% "
                            f"(warning-only; literature appears thin for this topic)"
                        )
                        topic_gap_notes.append(
                            {
                                "topic_code": str(topic_code),
                                "status": "warning_thin_literature",
                                "observed_pct": round(observed_pct, 4),
                                "min_pct": round(effective_topic_min_pct, 4),
                                "note": "Topic appears undersupplied in current literature relative to balance target.",
                            }
                        )
                    else:
                        errors.append(
                            f"topic '{topic_code}' out of bounds: {observed_pct:.2f}% "
                            f"not in [{effective_topic_min_pct:.2f}%, {effective_topic_max_pct:.2f}%]"
                        )
                        topic_gap_notes.append(
                            {
                                "topic_code": str(topic_code),
                                "status": "error_under_min_literature_thin",
                                "observed_pct": round(observed_pct, 4),
                                "min_pct": round(effective_topic_min_pct, 4),
                                "note": (
                                    "Topic coverage is materially under target; available literature appears thin "
                                    "for this scope."
                                ),
                            }
                        )
                elif observed_pct > effective_topic_max_pct:
                    errors.append(
                        f"topic '{topic_code}' out of bounds: {observed_pct:.2f}% "
                        f"not in [{effective_topic_min_pct:.2f}%, {effective_topic_max_pct:.2f}%]"
                    )

    if "age_normalized_importance_score" not in final.columns:
        warnings.append("age_normalized_importance_score missing; side-by-side ranking is unavailable")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
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
            "review_cluster_count": int(review_cluster_count),
            "review_cluster_pct": round(review_cluster_pct, 4),
            "missing_abstract_policy": missing_abstract_policy,
        },
        "category_mix_pct": category_mix_pct,
        "topic_mix_pct": topic_mix_pct,
        "topic_bounds": {
            "enabled": enforce_topic_bounds,
            "min_pct": round(topic_min_pct, 4),
            "max_pct": round(topic_max_pct, 4),
            "use_rebalance_from_selection_summary": bool(topic_bounds_use_rebalance),
            "under_min_warn_if_observed_pct_at_least": round(
                topic_under_min_warn_if_observed_pct_at_least, 4
            ),
            "include_unmapped": topic_bounds_include_unmapped,
            "expected_topic_codes": topic_expected_codes,
        },
        "topic_gap_notes": topic_gap_notes,
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
