---
title: Methodology & Limitations
description: Full pipeline description, corpus statistics, transparency notes, and known limitations of the MSKB citation graph.
sidebar:
  label: Methodology & Limitations
  order: 2
---

import { Aside, Badge } from '@astrojs/starlight/components';

<Aside type="caution" title="Plain-language disclaimer">
MSKB is a **learning engineering experiment**, not a clinical reference or systematic review. The corpus was assembled semi-automatically; summaries are AI-generated. Verify critical clinical claims against primary sources and current guidelines before applying them.
</Aside>

## Corpus statistics (April 2026 build)

<div class="corpus-stats">
  <div class="stat-card"><span class="stat-value">649</span><span class="stat-label">papers (T1–T4 corpus)</span></div>
  <div class="stat-card"><span class="stat-value">5,103</span><span class="stat-label">citation edges</span></div>
  <div class="stat-card"><span class="stat-value">9</span><span class="stat-label">citation topic clusters</span></div>
  <div class="stat-card"><span class="stat-value">30</span><span class="stat-label">concept pages</span></div>
  <div class="stat-card"><span class="stat-value">1961–2026</span><span class="stat-label">publication span</span></div>
  <div class="stat-card"><span class="stat-value">649/649</span><span class="stat-label">with AI summaries (both levels)</span></div>
</div>

**Evidence-type breakdown:**

| Type | Count |
|------|-------|
| Review | 147 |
| Clinical trial | 104 |
| Observational | 53 |
| Guideline/Consensus | 50 |
| Preclinical | 25 |
| Systematic review / meta-analysis | 14 |
| Other / unclassified | 256 |

---

## How the corpus is built

MSKB uses a seven-stage bibliometric pipeline run entirely from publicly available data:

### Stage 0 — Seed governance

A governance checklist validates **40 hand-curated T1 seed papers** against quotas for five clinical categories, venue concentration caps, author concentration caps, and explicit MS relevance requirements. Seeds are committed to `seeds/core_seeds.csv`. An additional **52 expert-signal T4 papers** are curated by domain experts and committed to `seeds/t4_expert_signals.csv`.

### Stage 1 — Corpus retrieval

Papers are retrieved from **OpenAlex** via three channels:
- **Seed channel**: direct DOI lookup for every seed
- **Lexical channel**: 20 structured keyword queries covering the five MS categories
- **Dataset channel**: 7 registry/cohort-level queries (MSBase, NARCOMS, Atlas of MS, GBD, etc.)
- **T4 expert channel**: DOI lookup for each expert-signal paper

Seed papers are additionally enriched via CrossRef and Semantic Scholar (one-hop reference expansion, title-similarity matching at ≥ 88%).

### Stage 2 — Deduplication & merge

Papers are canonicalized on DOI, OpenAlex ID, and title similarity (auto-merge threshold 0.85). Surviving canonical records form the raw candidate pool.

### Stage 3 — Graph construction

Co-citation, bibliographic coupling, and co-authorship graphs are built from the candidate pool. Structural metrics (k-core, in-degree, PageRank) are computed on the citation subgraph.

### Stage 4 — Relevance scoring

Each paper receives a composite relevance score combining:
- Direct seed citation weight (3.0)
- Landmark anchor linkage (0.5)
- Lexical MS relevance (2.0)
- Dataset/method alignment (1.5)
- Co-citation and bibliographic coupling scores
- MS-focus boost (1.65×) for papers with both lexical and concept MS signals
- Downweight (0.35×) for generic biology papers without apparent MS link

### Stage 5 — Core corpus selection (T2 + T3)

A tiered structural gate selects the curated corpus:

**T2 gate (established literature):**
- min cross-seed score ≥ 2
- min k-core ≥ 4
- min in-degree ≥ 2
- importance percentile ≥ 70% within category

Underrepresented topics (< 2% topic share) relax the structural gate to preserve diversity.

**T3 gate (emerging literature):**
- Publication year ≥ 2022
- Citations per year ≥ 20.0
- Per-topic cap: 20% of T2 topic count, with floor of 5 papers/topic

**Topic balance:** No topic may exceed 20% of the final selected corpus.

### Stage 6 — Distillation (AI summaries)

All T1+T2+T3+T4 papers are processed by the Claude API (Haiku model) to generate:
- **Basic summary** — plain-language, undergraduate level
- **Advanced summary** — specialist/clinical terminology

Summaries are cached per paper per reading level. A rules-based fallback generates summaries from the abstract when the full-text is unavailable. Every summary includes a certainty score (faithfulness overlap metric) and an explicit AI-generation disclaimer.

---

## Transparency notes

### What we guarantee
- Every seed paper is documented with its selection rationale in `seeds/core_seeds.csv`
- Every design decision is logged in [`Corpus > Design Decisions`](/mskb/corpus/design-decisions/)
- All graph metrics (PageRank, k-core, in-degree) are computed from the citation subgraph, not hand-assigned
- AI summaries are clearly labeled and link to the source paper DOI

### What we do not guarantee
- **Completeness**: MSKB is not a systematic review. The corpus covers the high-centrality core of MS literature as of April 2026, not every published paper
- **Currency**: The build date is April 9, 2026. Papers published after this date are not included
- **Clinical correctness**: AI-generated summaries may contain errors or omissions. Do not use them for clinical decision-making
- **Abstract quality**: Approximately 15% of papers in the raw candidate pool lacked an abstract from OpenAlex; these may have lower-quality summaries
- **Language coverage**: The corpus is overwhelmingly English-language literature — a known gap (see [Gap Tracker](/mskb/corpus/gaps/))

---

## Known limitations

See the [Gap Tracker](/mskb/corpus/gaps/) for the full list. Key structural gaps:

1. **Global South underrepresentation** — epidemiology literature from Africa, Latin America, and Southeast Asia is sparse in the seed set
2. **English-language bias** — non-English papers are excluded by the OpenAlex query structure
3. **Recency lag** — T3 papers (2022+) are included, but the most recent preprints are not
4. **Qualitative and patient-experience research** — underweighted by citation-network methods; no qualitative papers currently in the corpus
5. **Gray literature** — guidelines and technical reports may be under-cited in the academic network
6. **Topic cluster labels** — auto-generated from OpenAlex concept tags; may not perfectly reflect MS subdiscipline boundaries

---

## Replication

The full pipeline is open source at [wrgr/mskb](https://github.com/wrgr/mskb). To reproduce the corpus:

```bash
git clone https://github.com/wrgr/mskb
cp config.example.yaml config.yaml
# Edit config.yaml (add your email for OpenAlex polite pool)
pip install -r requirements.txt
python run_pipeline.py --config config.yaml
```

The pipeline requires an OpenAlex API key (free) and a Claude API key (Anthropic) for distillation. All intermediate outputs are stored in `outputs/` and are gitignored by default.

---

## Citation

If you use MSKB in teaching or research, please cite:

```
Gray, W. (2026). MSKB: Multiple Sclerosis Knowledge Base.
Open educational resource. https://wrgr.github.io/mskb/
License: CC BY-NC 4.0
```

Questions, corrections, or contributions: [willgray@jhu.edu](mailto:willgray@jhu.edu)
