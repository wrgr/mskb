# Pending Work

## Open

### 1. Concept pages rebuild (requires live API key)
**Status:** Code fix is merged. Rebuild deferred — needs a live Anthropic API key.

`src/link_concepts_to_papers.py::_load_papers()` now sources papers from
`core_corpus_tracked_with_t4.csv` (falls back to `scored_papers.csv`).
To publish the fix, regenerate `concept_papers.json`:
```
python src/link_concepts_to_papers.py --refresh
```
After rebuilding, `tests/test_concept_papers_cache.py::test_all_cached_paper_ids_exist_in_corpus`
should pass with the explorer graph as the sole valid-ID source.

---

### 2. Topic page quality review
**Status:** TOPIC-XX filter added to `site/gen_site.py` (off-topic Leiden clusters
with zero selected-corpus papers are now suppressed). Review still needed:

- Confirm MS-relevant topics in `site/src/content/docs/topics/index.mdx` are labelled correctly
- Verify no off-topic clusters (cardiac, EEG, glioma) appear in the regenerated index
- Check `kid-journey.md` looks coherent after the corpus refresh

---

### 3. E2E pipeline smoke test
Run the full pipeline (`python run_pipeline.py config.yaml`) on a small controlled
seed set to confirm all stages pass clean, especially:
- Stage 1 retrieval with two-tier title similarity thresholds (90% DOI / 98% title-only)
- Stage 2 dedup with year-delta guard and short-title guard
- Stage 9 audit with `held_papers.csv` output
- Stage 10 expert_comms with TOPIC-XX tier breakdown

---

### 4. Title similarity threshold validation
**Status:** Thresholds are in config (`min_title_similarity_doi_match: 90.0`,
`min_title_similarity: 98.0`) and retrieval stats from existing run show
99.9% DOI-resolved / 0.1% title-only — thresholds appear safe. Confirm
with one Stage 1 run post-dedup-fix; check `n_resolved_via_doi` and
`n_resolved_via_search` in the retrieval log.

---

## Done (this branch)

- [x] Paper hold gate — `held_papers.csv` written by `src/audit_kb.py` after all gates
- [x] Two-tier title similarity thresholds in `src/retrieve_corpora.py` + `config.yaml`
- [x] TOPIC-XX filtering in `site/gen_site.py` (suppress off-topic Leiden clusters)
- [x] Concept page corpus fix in `src/link_concepts_to_papers.py` (code only; rebuild pending)
- [x] Abstract backfill sync to tracked/selected CSVs in `src/backfill_abstracts.py`
- [x] `update_kid_journey.py` — unpack `_init_api_client` tuple correctly
- [x] Dedup NaN-doi false-grouping bug (`str(NaN or "")` → `"nan"` truthy)
- [x] Dedup self-cluster duplication (`j == i` processed before `used.add(i)`)
- [x] `tests/test_deduplicate_and_merge.py` — 5 tests, all passing
