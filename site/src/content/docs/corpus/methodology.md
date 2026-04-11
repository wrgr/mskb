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

A governance checklist validates hand-curated T1 seeds against topic quotas (`TOPIC-##`), venue concentration caps, author concentration caps, and explicit MS relevance requirements. Seeds are committed to `seeds/core_seeds.csv`. Expert-signal T4 papers are curated by domain experts and documented in `data/t4_expert_signal.yaml` (the authoritative source for T4 retrieval and selection).

### Stage 1 — Corpus retrieval

Papers are retrieved from **OpenAlex** via five channels:
- **Seed channel**: direct DOI lookup for every T1 core seed, with one-hop reference expansion
- **Framing seed channel**: one-hop expansion from review-anchor seeds (R-series), providing additional candidate mass and anchor links for topic assignment
- **Lexical channel**: 20 structured keyword queries covering the five MS categories
- **Dataset channel**: 7 registry/cohort-level queries (MSBase, NARCOMS, Atlas of MS, GBD, etc.)
- **T4 expert channel**: DOI lookup + title search for every entry in `data/t4_expert_signal.yaml` (all 52 expert-signal papers)

Core seed papers are additionally enriched via CrossRef and Semantic Scholar (one-hop reference expansion, title-similarity matching at ≥ 88%). Framing seeds contribute to the candidate pool and topic assignment but are not counted as core seed evidence in topic scoring.

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
- connectivity rule: `in_degree >= 5 OR (cross_seed_score >= 1 AND review_anchor_link_count >= 1)`
- min k-core ≥ 4
- importance percentile ≥ 70% within category

Undersubscribed-topic expansion is allowed with softer within-topic ranking to preserve diversity while keeping structural/connectivity quality gates.

**T3 gate (emerging literature):**
- Publication year ≥ 2022
- Citations per year ≥ 20.0
- Per-topic cap: 20% of T2 topic count, with floor of 5 papers/topic

**Topic rebalance:** Bounds are derived from target corpus size:
- expected per topic = `target_corpus_size / n_topics`
- min = `0.5 * expected`
- max = `1.5 * expected`

After selection, tracked papers still missing abstracts can be put on hold and excluded from graph outputs (`governance.hold_missing_abstracts_from_graph`).

### Stage 6 — Distillation (AI summaries)

All T1+T2+T3+T4 papers are processed by the Claude API (Haiku model) to generate:
- **Basic summary** — plain-language, undergraduate level
- **Advanced summary** — specialist/clinical terminology

Summaries are cached per paper per reading level. A rules-based fallback generates summaries from the abstract when the full-text is unavailable. Every summary includes a certainty score (faithfulness overlap metric) and an explicit AI-generation disclaimer.

---

## Classification systems

MSKB uses three distinct classification systems with distinct roles. Understanding which system does what is important for interpreting corpus statistics and site navigation.

| System | Count | Role | Used in selection? |
|--------|-------|------|--------------------|
| **T-codes** (T00–T16 + T1b) | 19 topics | Drives corpus balance gate and topic assignment | **Yes** |
| **Leiden citation clusters** | 9 clusters | Bibliometric alternative view; available in explorer graph | No |
| **Learner concepts** | ~30 concepts | Pedagogical site navigation; T4 signal source | No |

### T-codes — primary corpus taxonomy

19 topics (T00–T16 plus T1b Natural History) manually defined in the MS Field Orientation Guide. Each core seed is assigned a `primary_topic` code; this assignment propagates to neighboring papers via the `assign_topic_evidence` pipeline stage. T-codes drive the corpus balance constraint (no topic may exceed 20% of the selected corpus) and are the authoritative topic labels in all pipeline provenance outputs.

### Leiden citation clusters — informational only

9 clusters produced by Louvain community detection on the full citation subgraph. These are a bibliometric view of how the literature groups by co-citation patterns — not a hand-curated taxonomy. Leiden clusters appear in `explorer_graph.json` as `topic_id` and power the **Citation Topics** sidebar section. They are **not used** in corpus selection, topic balance, or T-code assignment. They provide an alternative framing and are surfaced for transparency.

### Learner concepts — pedagogical navigation only

~30 concept pages (`site/src/content/docs/concepts/`) derived from literature review and learning science. Concepts are manually authored to guide learners through the knowledge base. They link to corpus papers and serve as the nomination source for T4 expert signals (each T4 paper is nominated because a concept page requires it as an anchor). Learner concepts are **not used** in corpus selection or balance.

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
- **Abstract availability**: Raw candidate pools can include papers without abstracts from upstream providers; unresolved papers can be held out of graph outputs per governance policy
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
