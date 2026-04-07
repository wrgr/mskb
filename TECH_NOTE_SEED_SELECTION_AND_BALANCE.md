# MSKB Tech Note: Seed Selection, Balance, and Corpus Control

Date: 2026-04-07  
Repo: `wrgr/mskb`

## 1. Why seed strategy is critical

In this pipeline, seeds control three high-leverage decisions:

1. What gets retrieved in the seed-expansion channel (`seed_resolution`, `seed_reference`, `seed_cited_by`).
2. What gets high field-membership scores (direct and structural affinity to seed neighborhood).
3. What the final corpus topology looks like (topic/community dominance, bridge papers, and off-topic contamination risk).

If seeds are skewed, the graph, topic discovery, and explorer recommendations inherit that skew.

## 2. Current seed architecture

Seed files:

- `seeds/core_seeds.csv` (used for expansion/retrieval)
- `seeds/framing_seeds.csv` (`score_only` framing list)

Current retrieval behavior (`src/retrieve_corpora.py`):

- Core seeds are resolved by DOI, then expanded via:
  - references (`seed_reference`)
  - citing papers (`seed_cited_by`)
- Lexical and dataset channels run in parallel to seed expansion.
- Framing seeds are currently loaded for stats only (`n_framing_seeds`), not used as expansion roots in Stage 1.

## 3. How core seeds were selected (current run)

### 3.1 Strata design

The current core seed list is intentionally balanced by category:

- `clinical_care_and_management`: 10
- `clinical_trials_and_therapeutics`: 10
- `epidemiology_and_population_health`: 10
- `imaging_and_biomarkers`: 10
- `pathogenesis_and_immunology`: 10

Total core seeds: 50.

### 3.2 Recency policy

Core seeds are modern-heavy (from rationale metadata):

- Year range: 2021-2025
- Distribution: 2021 (23), 2022 (15), 2023 (7), 2024 (4), 2025 (1)

Framing seeds (15) are also modern:

- Year range: 2021-2025
- Distribution: 2021 (4), 2022 (4), 2023 (3), 2024 (3), 2025 (1)

### 3.3 Venue targeting

Core seeds were sampled from target MS venues with strong representation:

- Multiple Sclerosis Journal (8)
- Neurology (8)
- The Lancet Neurology (7)
- JAMA Neurology (7)
- Annals of Neurology (5)
- Brain (4)
- Nature Reviews Neurology (3)
- Neurology Neuroimmunology & Neuroinflammation (3)

This helps keep retrieval tied to clinically and methodologically current literature.

## 4. Retrieval impact from current seeds

From `outputs/raw/retrieval_stats.json` and `outputs/raw/candidate_papers.csv`:

- Candidates: 16,542
- Seed citation edges: 10,463
- Channel mix:
  - lexical: 6,292
  - seed_cited_by: 5,215
  - seed_reference: 2,560
  - dataset: 2,425
  - seed_resolution: 50

MS mention in raw candidates:

- Title contains `multiple sclerosis`: 8,842
- Abstract contains `multiple sclerosis`: 5,901

Interpretation: lexical + seed expansion both contribute substantially; seed expansion is not a minor side channel.

## 5. Downstream corpus controls now in place

Recent scoring refactor (`src/compute_scores.py`) adds explicit corpus controls:

- `core_vs_context` split:
  - `in_core_corpus`: explicit MS focus
  - `in_context_corpus`: bridge papers with structural linkage
- major MS upweight:
  - lexical and concept minimums + multiplicative boosts
- downweight:
  - generic biology papers with no MS signal and weak seed linkage
- optional category rebalance using `topic_balance.target_ranges`

Current scored corpus snapshot (`outputs/graph/scored_papers.csv`):

- Final corpus: 10,757
- Core: 8,922
- Context: 1,835
- MS focus in final: 82.94%
- Biology-without-MS-link in final: 0

## 6. Known issues / risks

1. Framing seeds are not yet active retrieval roots in Stage 1.
2. Framing list is clinically weighted (12/15 in `clinical_care_and_management`), so if activated without controls it can over-steer retrieval.
3. Modern-only seed policy (2021+) can under-represent landmark foundational papers unless explicitly retained as a small “landmark anchor” set.
4. A few seed candidates may still be biologically adjacent rather than MS-specific and should be periodically pruned/replaced.

## 7. Recommended seed governance process

### 7.1 Two-list policy

Maintain two explicit lists with different behaviors:

1. Expansion Seeds (`role=expand`): active retrieval roots.
2. Framing/Anchor Seeds (`role=score_only`): scoring/topic-shaping only unless explicitly enabled.

### 7.2 Hard constraints at refresh time

When reseeding:

- Category quotas (fixed min/max per category).
- Venue caps (avoid single-journal dominance).
- Author caps (avoid single-lab/topic lock-in).
- Recency mix: modern core + small landmark floor.
- MS-specificity gate: must pass lexical/concept threshold or be manually justified as bridge.

### 7.3 Audit gates before accepting new seeds

Require:

- Balanced seed distribution across categories.
- Off-topic contamination checks (ALS/Parkinson/Alzheimer collisions).
- Final corpus MS-focus threshold.
- Context/core ratio within expected range.

## 8. Practical commands for seed audits

```bash
# Seed and retrieval sanity
.venv/bin/python - <<'PY'
import pandas as pd
core = pd.read_csv("seeds/core_seeds.csv")
fr = pd.read_csv("seeds/framing_seeds.csv")
print("core by category:", core["category"].value_counts().to_dict())
print("framing by category:", fr["category"].value_counts().to_dict())
PY

# Corpus focus sanity
.venv/bin/python - <<'PY'
import pandas as pd
sp = pd.read_csv("outputs/graph/scored_papers.csv", low_memory=False)
final = sp[sp["in_final_corpus"].fillna(0).astype(int)==1]
print("final", len(final))
print("core", int(sp["in_core_corpus"].fillna(0).astype(int).sum()))
print("context", int(sp["in_context_corpus"].fillna(0).astype(int).sum()))
print("ms_focus_pct", round(final["has_ms_focus"].mean()*100, 2))
PY
```

## 9. Bottom line

The current strategy is a modern, category-balanced seed set with explicit corpus controls to preserve MS focus while retaining biologically authentic context. The main remaining structural improvement is to formalize whether/how framing seeds participate in retrieval and to keep a small deliberate landmark anchor set so recency does not erase canonical foundational papers.
