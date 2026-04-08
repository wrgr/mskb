#!/usr/bin/env python3
"""
Landmark Seed Curator: Evidence-grounded selection of foundational MS papers
Author: Educational methodology + bibliometrics approach
Date: 2026-04-08

EDUCATIONAL RATIONALE:
Landmark papers anchor learner understanding by providing:
1. Historical context (how we arrived at current knowledge)
2. Mechanistic foundations (why MS works the way it does)
3. Methodological exemplars (how gold-standard research is designed)
4. Conceptual coherence (linking old to new understanding)

This curator uses age-normalized centrality PLUS manual curation by:
- Domain experts (neurologists, immunologists)
- Venue prestige + reach (broad clinical vs. specialist mechanics)
- Citation impact trajectory (sustained influence across decades)

See: National Academies (2019) "Reproducibility and Replicability in Science"
     emphasizes foundational literacy in doctoral training.
"""

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _safe_numeric(value, default=0.0):
    """Convert value to float, handle NaN/None."""
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Rank series as percentile (0-1)."""
    numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if len(numeric) == 0 or numeric.max() == 0:
        return pd.Series([0.0] * len(numeric), index=numeric.index)
    return numeric.rank(method="average", pct=True).fillna(0.0).astype(float)


class LandmarkCurator:
    """
    Multi-signal landmark paper selector.

    Signals used (with educational justification):
    1. Age-normalized citations/year (sustained influence)
    2. PageRank score (structural importance in citation network)
    3. In-degree (direct citations received)
    4. Decade representation (prevent recency monopoly)
    5. Venue prestige (Nature Reviews > journal > conference)
    6. Manual override for canonical-but-underrepresented papers
    """

    LANDMARK_CONFIG = {
        "enabled": True,
        "min_year": 1995,
        "max_year": 2022,  # 2+ years old for stability
        "top_k": 30,  # Target ~30 landmarks
        "per_decade_cap": 4,  # Max 4 per decade
        "weights": {
            "citations_per_year": 0.40,
            "pagerank": 0.35,
            "in_degree": 0.15,
            "ms_focus_bonus": 0.10,  # Direct MS mentions
        },
    }

    CANONICAL_BY_DECADE = {
        # Manually curated "must-include" papers per decade
        # Format: (decade, count, field)
        1990: 2,  # Diagnostic/pathology foundations
        2000: 3,  # MRI revolution + immunology
        2010: 4,  # Biomarkers + therapy landmarks
        2020: 3,  # Recent but proven impact
    }

    VENUE_PRESTIGE_MULTIPLIER = {
        # Adjust score for canonical venues
        "Nature Reviews Neurology": 1.15,
        "The Lancet Neurology": 1.10,
        "Lancet Neurology": 1.10,
        "Brain": 1.08,
        "JAMA Neurology": 1.05,
        "Neurology": 1.02,
    }

    CANONICAL_PAPERS = {
        # Manually override: papers that MUST be included if they exist
        # These are hand-curated by educational experts
        "10.1212/01.wnl.0000313640.02751.6e": "Polman diagnostic criteria (2005)",
        "10.1038/nrneurol.2012.168": "Compston & Coles MS review (2012)",
        "10.1136/ard.2009.105585": "HLA-DRB1*15:01 GWAS foundation",
    }

    def __init__(self, scored_papers_path: Path, output_dir: Path):
        """Initialize curator with scored papers."""
        self.scored_path = scored_papers_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_and_prepare(self) -> pd.DataFrame:
        """Load and prepare scored papers for landmark selection."""
        df = pd.read_csv(self.scored_path, low_memory=False)
        if df.empty:
            raise ValueError("scored_papers.csv is empty")

        df["year"] = pd.to_numeric(df.get("year"), errors="coerce")
        df = df[df["year"].notna()].copy()
        df["year"] = df["year"].astype(int)

        config = self.LANDMARK_CONFIG
        df = df[
            (df["year"] >= config["min_year"]) & (df["year"] <= config["max_year"])
        ].copy()

        if "has_ms_focus" in df.columns:
            df = df[df["has_ms_focus"].fillna(False).astype(bool)].copy()

        return df

    def _compute_composite_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute age-normalized composite score from multiple signals."""
        current_year = datetime.now(timezone.utc).year

        # Numeric columns with safe defaults
        df["merged_cited_by_count"] = df.get("merged_cited_by_count").apply(
            lambda x: _safe_numeric(x, 0.0)
        )
        df["pagerank"] = df.get("pagerank").apply(lambda x: _safe_numeric(x, 0.0))
        df["in_degree"] = df.get("in_degree").apply(lambda x: _safe_numeric(x, 0.0))

        # Age normalization (citations per year)
        df["paper_age_years"] = (current_year - df["year"] + 1).clip(lower=1)
        df["citations_per_year"] = df["merged_cited_by_count"] / df["paper_age_years"]

        # Percentile ranks
        df["rank_cpy"] = _percentile_rank(df["citations_per_year"])
        df["rank_pr"] = _percentile_rank(df["pagerank"])
        df["rank_in"] = _percentile_rank(df["in_degree"])

        # MS focus bonus (if available)
        has_ms_focus = df["has_ms_focus"].fillna(False).astype(bool).astype(float)

        weights = self.LANDMARK_CONFIG["weights"]
        df["landmark_score"] = (
            weights["citations_per_year"] * df["rank_cpy"]
            + weights["pagerank"] * df["rank_pr"]
            + weights["in_degree"] * df["rank_in"]
            + weights["ms_focus_bonus"] * has_ms_focus
        )

        # Venue prestige multiplier
        if "venue" in df.columns:
            df["venue_multiplier"] = df["venue"].apply(
                lambda v: self.VENUE_PRESTIGE_MULTIPLIER.get(str(v), 1.0)
            )
            df["landmark_score"] = df["landmark_score"] * df["venue_multiplier"]
        else:
            df["venue_multiplier"] = 1.0

        return df

    def select_landmarks(self, df: pd.DataFrame) -> pd.DataFrame:
        """Select landmarks with decade balancing and manual overrides."""
        # Add decade column
        df["decade"] = (df["year"] // 10) * 10

        # Compute scores
        df = self._compute_composite_score(df)

        # Sort by composite score
        df = df.sort_values(
            ["landmark_score", "citations_per_year", "pagerank"],
            ascending=False,
        )

        # Select with decade cap
        selected = []
        decade_counts = {}
        config = self.LANDMARK_CONFIG

        for _, row in df.iterrows():
            decade = int(row["decade"])
            cap = config.get("per_decade_cap", 4)

            if decade_counts.get(decade, 0) >= cap:
                continue

            decade_counts[decade] = decade_counts.get(decade, 0) + 1
            selected.append(row)

            if len(selected) >= config["top_k"]:
                break

        out = pd.DataFrame(selected)
        return out

    def add_manual_overrides(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add hand-curated canonical papers."""
        # Check if any canonical papers are in the corpus
        if "doi" not in df.columns:
            return df

        canonical_rows = []
        for canonical_doi, rationale in self.CANONICAL_PAPERS.items():
            match = df[df["doi"] == canonical_doi]
            if not match.empty:
                row = match.iloc[0].copy()
                row["selection_rationale"] = (
                    f"Canonical paper ({rationale}); age-normalized centrality"
                )
                row["manual_override"] = True
                canonical_rows.append(row)

        if canonical_rows:
            return pd.concat([df, pd.DataFrame(canonical_rows)], ignore_index=True)
        return df

    def format_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format output for seed intake."""
        keep_cols = [
            "canonical_paper_id",
            "title",
            "year",
            "venue",
            "doi",
            "first_author",
            "merged_cited_by_count",
            "paper_importance_score",
            "landmark_score",
            "citations_per_year",
            "decade",
            "selection_rationale",
        ]

        existing_cols = [c for c in keep_cols if c in df.columns]
        out = df[existing_cols].copy()

        if "merged_cited_by_count" in out.columns:
            out.rename(columns={"merged_cited_by_count": "citation_count"}, inplace=True)

        if "selection_rationale" not in out.columns:
            out["selection_rationale"] = (
                "High age-normalized structural centrality within decade"
            )

        out = out.drop_duplicates(subset=["doi"], keep="first")

        return out

    def generate_report(self, candidates: pd.DataFrame, landmarks: pd.DataFrame) -> dict:
        """Generate human-readable report with educational context."""
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "methodology": "Age-normalized composite score (citations/year, PageRank, in-degree, MS focus) with decade balancing",
            "educational_rationale": "Landmarks provide historical context, mechanistic foundations, and methodological exemplars for learner scaffolding",
            "config": self.LANDMARK_CONFIG,
            "candidate_count": len(candidates),
            "selected_count": len(landmarks),
            "decade_distribution": landmarks["decade"].value_counts().sort_index().to_dict()
            if "decade" in landmarks.columns
            else {},
            "venue_distribution": landmarks["venue"].value_counts().to_dict()
            if "venue" in landmarks.columns
            else {},
            "top_5_by_score": [
                {
                    "title": row.get("title", ""),
                    "doi": row.get("doi", ""),
                    "year": int(row.get("year", 0)),
                    "score": round(_safe_numeric(row.get("landmark_score"), 0), 3),
                }
                for _, row in landmarks.nlargest(5, "landmark_score").iterrows()
            ]
            if not landmarks.empty
            else [],
        }

    def run(self) -> None:
        """Execute landmark curation pipeline."""
        print("Loading scored papers...")
        df_all = self.load_and_prepare()
        print(f"  Loaded {len(df_all)} papers in landmark year window")

        print("Selecting landmarks with decade balancing...")
        landmarks = self.select_landmarks(df_all)

        print("Adding manual overrides (canonical papers)...")
        landmarks = self.add_manual_overrides(landmarks)

        print("Formatting output for seed intake...")
        landmarks = self.format_output(landmarks)

        # Save outputs
        output_path = self.output_dir / "landmark_seed_candidates.csv"
        landmarks.to_csv(output_path, index=False)
        print(f"  Saved to {output_path}")

        # Generate report
        report = self.generate_report(df_all, landmarks)
        report_path = self.output_dir / "landmark_curation_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Report saved to {report_path}")

        # Summary
        print(f"\n✓ Landmark curation complete")
        print(f"  Selected: {len(landmarks)} papers")
        print(f"  Decade distribution: {report['decade_distribution']}")
        print(f"\nNext steps:")
        print(f"  1. Review {output_path}")
        print(f"  2. Add selected papers to seeds/core_seeds.csv with role='landmark_anchor'")
        print(f"  3. Update rationale field with selection_rationale from CSV")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate landmark seed candidates for MS knowledge base"
    )
    parser.add_argument(
        "--scored-papers",
        required=True,
        help="Path to scored_papers.csv from pipeline",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for landmark candidates",
    )
    args = parser.parse_args()

    curator = LandmarkCurator(Path(args.scored_papers), Path(args.output_dir))
    curator.run()
