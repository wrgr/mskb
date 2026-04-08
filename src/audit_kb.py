"""Run quality audit gates against the scored paper corpus and emit a report."""

import argparse
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

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
    lines.append(f"- `biology_no_ms_link` (final count): `{gm.get('biology_no_ms_link_count', 0)}`")
    lines.append(f"- Missing abstract rate: `{gm.get('missing_abstract_pct', 0):.2f}%`")
    lines.append(f"- Missing source-link rate: `{gm.get('missing_source_link_pct', 0):.2f}%`")
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

    scored_path = root / cfg["output_dir"] / "graph" / "scored_papers.csv"
    if not scored_path.exists():
        raise FileNotFoundError(f"Missing scored papers file: {scored_path}")

    scored = pd.read_csv(scored_path, low_memory=False)
    if scored.empty:
        raise RuntimeError("scored_papers.csv is empty")

    scored["in_final_corpus"] = scored.get("in_final_corpus", 0).fillna(0).astype(int)
    final = scored[scored["in_final_corpus"] == 1].copy()
    if final.empty:
        raise RuntimeError("No papers in final corpus")

    gcfg = (cfg.get("governance", {}) or {}).get("audit_gates", {}) or {}
    fail_on_error = bool(gcfg.get("fail_on_error", True))
    min_ms_focus_pct = _safe_float(gcfg.get("min_ms_focus_pct", 75.0), 75.0)
    max_biology_no_ms_link = _safe_int(gcfg.get("max_biology_no_ms_link", 0), 0)
    max_missing_abstract_pct = _safe_float(gcfg.get("max_missing_abstract_pct", 25.0), 25.0)
    max_missing_source_link_pct = _safe_float(gcfg.get("max_missing_source_link_pct", 5.0), 5.0)
    enforce_category_bounds = bool(gcfg.get("enforce_category_bounds", True))

    errors: list[str] = []
    warnings: list[str] = []

    has_ms_focus = final.get("has_ms_focus", pd.Series(False, index=final.index)).fillna(False).astype(bool)
    ms_focus_pct = float(has_ms_focus.mean() * 100.0)
    if ms_focus_pct < min_ms_focus_pct:
        errors.append(f"ms_focus_pct below threshold: {ms_focus_pct:.2f}% < {min_ms_focus_pct:.2f}%")

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
        errors.append(
            f"missing abstract rate above threshold: {missing_abstract_pct:.2f}% > {max_missing_abstract_pct:.2f}%"
        )

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

    if "age_normalized_importance_score" not in final.columns:
        warnings.append("age_normalized_importance_score missing; side-by-side ranking is unavailable")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_final_corpus": int(len(final)),
        "gate_metrics": {
            "ms_focus_pct": round(ms_focus_pct, 4),
            "biology_no_ms_link_count": int(biology_no_ms_link_count),
            "missing_abstract_pct": round(missing_abstract_pct, 4),
            "missing_source_link_pct": round(missing_source_link_pct, 4),
        },
        "category_mix_pct": category_mix_pct,
        "category_entropy": round(category_entropy, 6),
        "category_entropy_normalized": round(category_entropy_normalized, 6),
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
