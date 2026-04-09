# TODO: Topic / Category Organization

## The Problem

The site currently exposes **two parallel classification systems** that are not reconciled:

### 1. Leiden citation clusters (9 clusters, IDs 0–8)
- Algorithmically derived by bibliometric community detection on the 649-paper T1–T4 corpus
- Used in `explorer_graph.json` (`topic_id` field on every paper node)
- Drives the current **Citation Topics** sidebar section (9 pages under `site/src/content/docs/topics/`)
- Drives `research_map_graph.json` (the interactive `/topics/` graph)

### 2. Seed governance T-codes (18 codes, T00–T16 + T1b)
- Human-curated knowledge taxonomy; used to classify the 40 T1 seed papers in `seeds/core_seeds.csv`
- Also used in `data/t4_expert_signal.yaml` (`topic_codes` field on each T4 paper)
- **Not currently surfaced anywhere on the site**

| T-code | Topic | Seeds |
|--------|-------|-------|
| T00 | Epidemiology | – |
| T01 | Disease Overview | – |
| T02 | Pathophysiology | – |
| T03 | Genetics | – |
| T04 | Risk Factors | – |
| T05 | Diagnosis & Monitoring | – |
| T06 | Biomarkers | – |
| T07 | DMTs | – |
| T08 | Progressive MS | – |
| T09 | PROs (Patient-Reported Outcomes) | – |
| T10 | Comorbidities | – |
| T11 | Pregnancy | – |
| T12 | Pediatric MS | – |
| T13 | Equity & SDOH | – |
| T14 | Clinical AI | – |
| T15 | Emerging Frontiers | – |
| T16 | Research Priorities | – |
| T1b | Natural History | – |

> To fill in the "Seeds" column: join `core_seeds.csv` on `primary_topic`.

---

## Options

### Option A — Surface both (recommended for transparency)
- Keep the 9 Leiden clusters under **Citation Topics** (bibliometric view)
- Add a new **Knowledge Areas** section (or tab on the `/topics/` page) organized by the 18 T-codes
- Each T-code page lists: seed papers, T4 anchors, and related concept pages
- Requires: new page template + script to build T-code → paper mapping from `core_seeds.csv` + `t4_expert_signal.yaml`

### Option B — Replace Leiden clusters with T-codes
- Retire the 9 Leiden cluster pages
- Create 18 T-code pages as the primary "Citation Topics" section
- Each page needs a paper list (filter `explorer_graph.json` by seed T-code, then expand to neighbors)
- Risk: the 649 papers don't have T-code assignments — only the 40 seeds do, so you'd need a propagation strategy

### Option C — Hybrid / merged view
- Map each of the 18 T-codes to its closest Leiden cluster(s)
- Display the T-code name as the human-readable label, backed by the Leiden cluster's full paper set
- Requires: explicit `T-code → Leiden cluster` mapping table (some T-codes will map to multiple clusters)
- Proposed mapping sketch:

| T-code | Best Leiden cluster(s) |
|--------|----------------------|
| T00 Epidemiology | 5 |
| T01 Disease Overview | 0, 3 |
| T02 Pathophysiology | 2, 6 |
| T03 Genetics | 1 |
| T04 Risk Factors | 5, 8 |
| T05 Diagnosis & Monitoring | 0, 3 |
| T06 Biomarkers | 8 |
| T07 DMTs | 7 |
| T08 Progressive MS | 4, 5 |
| T09 PROs | 3, 5 |
| T10 Comorbidities | 0, 3 |
| T11 Pregnancy | 5 |
| T12 Pediatric MS | 3 |
| T13 Equity & SDOH | 5 |
| T14 Clinical AI | 8 |
| T15 Emerging Frontiers | 8 |
| T16 Research Priorities | 3 |
| T1b Natural History | 3, 4 |

---

## Related gaps to fix at the same time

1. **`seeds/t4_expert_signals.csv` is empty** — the 52 T4 papers are fully documented in
   `data/t4_expert_signal.yaml` (with `topic_codes`, titles, authors, years, journals) but the
   CSV has only headers. Populating it would let the pipeline and breakdown scripts identify T4
   papers by DOI. Seven T4 papers are already in the corpus (matched by title fuzzy search);
   45 need to be retrieved in a future pipeline run.

2. **10 of 40 T1 seeds are missing from the graph** — the following DOIs are in `core_seeds.csv`
   but not in `explorer_graph.json` (likely failed OpenAlex retrieval or were deduplicated):
   - `10.1016/S0140-6736(08)61620-7` — Compston & Coles 2008 (Lancet MS seminar)
   - `10.1016/S1474-4422(17)30470-2` — Thompson 2018 (McDonald Criteria)
   - `10.1016/S1474-4422(21)00095-8` — 2021 MAGNIMS-CMSC-NAIMS MRI consensus
   - `10.1038/s41582-018-0058-z` — Neurofilaments as biomarkers
   - `10.1016/j.msard.2019.07.007` — Patient-reported outcomes in MS care
   - `10.1016/S1474-4422(08)70259-X` — Cognitive impairment in MS
   - `10.1016/S1474-4422(22)00426-4` — Family planning considerations in MS
   - `10.1038/nrn2480` — Remyelination in CNS
   - `10.1177/13524585241266483` — Refined Pathways to Cures Roadmap 2024
   - `10.1016/S0140-6736(16)31320-4` — Progressive MS (Coles 2017)
   These should be added back in the next pipeline run.

3. **`ebv-ms.md` concept has no T-code** — not in `CONCEPT_TOPIC_MAP`; if Option A or C is
   chosen, it needs a T-code assignment (probably T02 or T15).
