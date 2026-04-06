# MSKB: Multiple Sclerosis Knowledge Base

A bibliometric pipeline and knowledge base for multiple sclerosis research, designed to help undergraduate researchers navigate MS literature from basic biology through clinical science to population health.

## Overview

MSKB builds a curated, navigable knowledge base from the MS literature by:

1. **Retrieving** candidate papers from [OpenAlex](https://openalex.org/) via seed expansion, lexical queries, and dataset-anchored searches
2. **Deduplicating** and merging paper versions (preprints, journal articles)
3. **Building graphs** -- citation, co-citation, bibliographic coupling, and co-authorship networks with PageRank, k-core, betweenness centrality, and Louvain community detection
4. **Scoring** papers for MS relevance using multi-signal agreement
5. **Discovering topics** algorithmically from citation communities and OpenAlex concepts
6. **Distilling papers** into undergraduate-accessible summaries using the Claude API
7. **Building a knowledge graph** with MS-specific entities (drugs, genes, pathology, biomarkers, animal models)

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
| 1 | `src/retrieve_corpora.py` | Fetch candidate papers from OpenAlex |
| 2 | `src/deduplicate_and_merge.py` | Merge duplicate papers and resolve authors |
| 3 | `src/build_graphs.py` | Build bibliometric networks and compute graph metrics |
| 4 | `src/compute_scores.py` | Score papers for MS relevance |
| 5 | `src/discover_topics.py` | Discover topic clusters from citation structure |
| 6 | `src/distill_papers.py` | Generate accessible paper summaries via Claude API |
| 7 | `src/build_knowledge_graph.py` | Extract MS entities and build heterogeneous KG |

Run individual stages:
```bash
python -m src.retrieve_corpora --config config.yaml
python -m src.discover_topics --config config.yaml
python -m src.distill_papers --config config.yaml
```

## Static Site

Generate and serve the knowledge base site:
```bash
python site/gen_site.py --config config.yaml
cd site && mkdocs serve
```

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
