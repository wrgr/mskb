# MSKB: Multiple Sclerosis Knowledge Base

A bibliometric pipeline and knowledge base for multiple sclerosis research, designed to help undergraduate researchers navigate MS literature from basic biology through clinical science to population health.

## Overview

MSKB builds a curated, navigable knowledge base from the MS literature by:

1. **Retrieving** candidate papers from [OpenAlex](https://openalex.org/) via seed expansion, lexical queries, and dataset-anchored searches
2. **Deduplicating** and merging paper versions (preprints, journal articles)
3. **Building graphs** -- citation, co-citation, bibliographic coupling, and co-authorship networks with PageRank, k-core, betweenness centrality, and Louvain community detection
4. **Scoring** papers for MS relevance using multi-signal agreement
5. **Discovering topics** algorithmically from citation communities and OpenAlex concepts
6. **Building learner journey paths** that suggest the next paper or topic to study
7. **Distilling papers** into undergraduate-accessible summaries using the Claude API
8. **Building a knowledge graph** with MS-specific entities (drugs, genes, pathology, biomarkers, animal models) plus learner-journey edges

The final output is a **static MkDocs site** where students can browse topics, read distilled paper summaries, follow structured reading paths, and explore the MS research landscape.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# Edit config.yaml: set your email and (optionally) Anthropic API key

python run_pipeline.py --config config.yaml
```

## Pipeline Stages

| Stage | Module | Description |
|-------|--------|-------------|
| 0 | `src/seed_governance.py` | Enforce seed acceptance checklist + emit landmark-anchor candidates |
| 1 | `src/retrieve_corpora.py` | Fetch candidate papers from OpenAlex |
| 2 | `src/deduplicate_and_merge.py` | Merge duplicate papers and resolve authors |
| 3 | `src/build_graphs.py` | Build bibliometric networks and compute graph metrics |
| 4 | `src/compute_scores.py` | Score papers for MS relevance + age-normalized centrality + evidence strength |
| 5 | `src/discover_topics.py` | Discover topic clusters from citation structure |
| 5b | `src/assign_topic_evidence.py` | Assign per-paper topic evidence with seed/anchor provenance |
| 5c | `src/select_core_corpus.py` | Apply explicit T1/T2/T3 balancing rules and export selected core corpus |
| 6 | `src/build_learner_journey.py` | Recommend next papers/topics from citation + topic structure |
| 7 | `src/distill_papers.py` | Generate accessible summaries with provenance/certainty + faithfulness QA sample |
| 8 | `src/build_knowledge_graph.py` | Extract MS entities and build heterogeneous KG |
| 9 | `src/audit_kb.py` | Run CI-like corpus audit gates (`ms_focus`, contamination, category bounds, missing data) |

Run individual stages:
```bash
python -m src.retrieve_corpora --config config.yaml
python -m src.assign_topic_evidence --config config.yaml
python -m src.select_core_corpus --config config.yaml
python -m src.discover_topics --config config.yaml
python -m src.distill_papers --config config.yaml
python -m src.seed_governance --config config.yaml
python -m src.audit_kb --config config.yaml
```

## Static Site

Use the guarded site build command (sequential, lock-protected):
```bash
.venv/bin/python site/build_site.py --config config.yaml --strict
.venv/bin/python site/build_site.py --config config.yaml --strict --serve
```

This avoids race conditions from running `site/gen_site.py` and `mkdocs build` concurrently.

## GitHub Pages (`gh-pages` branch)

This repo includes a workflow at `.github/workflows/deploy-gh-pages.yml` that:

1. Builds MkDocs from `site/mkdocs.yml`
2. Publishes the built output (`site/site`) to the `gh-pages` branch

To enable hosting:

1. Open **GitHub -> Settings -> Pages**
2. Set **Source** to **Deploy from a branch**
3. Select **Branch**: `gh-pages` and folder: `/ (root)`

After that, every push to `main` that touches `site/**` (or manual run via **Actions -> Deploy MkDocs to gh-pages**) updates the live site.

Manual publish (recommended when iterating locally):
```bash
./site/publish_gh_pages.sh
```

This builds with the project venv, validates required explorer assets, and force-pushes the rendered site to `gh-pages`.

## Project Structure

```
mskb/
├── seeds/              # Seed papers and holdout sets
├── src/                # Pipeline modules
├── site/               # MkDocs static site
│   ├── docs/           # Generated markdown pages
│   └── gen_site.py     # Site generator script
├── tests/              # Test suite
└── outputs/            # Pipeline outputs (gitignored)
```

## Acknowledgments

Pipeline architecture adapted from [connectome-kb](https://github.com/wrgr/connectome-kb).
