# Pending Work

## Immediate (next session)

### 1. Paper hold / manual review gate
**Context:** "the paper hold happens at the end so that we can move through all the gates and manually review"

Clarify and implement a "hold" mechanism so papers that fail soft governance gates can be flagged for manual review rather than dropped silently. Expected behaviour:
- Papers proceed through all pipeline stages regardless of soft-gate failures
- At the end of the pipeline, any paper with a soft-gate flag is written to a `held_papers.csv` (or similar) for manual inspection
- Hard gates (e.g. `fail_on_error: true` audit gates) remain blocking
- The audit report and expert_comms report should note the held count

Files likely involved: `src/audit_kb.py`, `src/select_core_corpus.py`, `run_pipeline.py`

---

### 2. Title similarity thresholds — validate with a pipeline run
**Context:** Changed `min_title_similarity` from 88.0 → 98.0 (title-only) and added `min_title_similarity_doi_match: 90.0` in `config.yaml`.

- Run Stage 1 (retrieval) on a small seed subset to confirm the new thresholds are not over-restrictive (i.e. legitimate references are still resolved)
- Check `n_resolved_via_doi` and `n_resolved_via_search` stats in the retrieval log after a run
- If 98% title-only is too strict for some abbreviated or subtitle-varying references, consider 95%

---

### 3. Concept pages → only reference explorer-visible papers
**Context:** `concept_papers.json` is generated from `scored_papers.csv (in_final_corpus=True)` which has ~18 k papers, but the explorer shows only the ~919-paper tracked corpus. Concept page links to papers outside the explorer will silently 404 on the site.

Fix: update `src/link_concepts_to_papers.py::_load_papers()` to use `core_corpus_tracked_with_t4.csv` as its source (falling back to `scored_papers.csv` if the tracked file is absent), then rebuild `concept_papers.json` via:
```
python src/link_concepts_to_papers.py --refresh
```
This requires a live Anthropic API key.

After rebuilding, `tests/test_concept_papers_cache.py::test_all_cached_paper_ids_exist_in_corpus` should pass with the explorer graph as the sole valid-ID source (stricter check).

---

### 4. Topic page quality review
**Context:** gen_site.py regenerated 15 topic pages from the updated 919-paper corpus. Several old topic pages were deleted (`multiple-sclerosis-0.md`, `neuroscience-2.md`, `pathology-6.md`, etc.) and new ones were created (cardiac, glioma, EEG — off-topic clusters from the scorer).

- Review the new topic index (`site/src/content/docs/topics/index.mdx`) to confirm MS-relevant topics are labelled correctly
- Off-topic clusters (cardiac valvular disease, EEG/BCI, glioma, neuroendocrine) may indicate that the Leiden clustering is picking up noise from the broader scored graph — consider raising `min_cluster_size` in config or filtering topic pages by topic code prefix
- Confirm the `kid-journey.md` regeneration looks coherent

---

## Backlog

### 5. E2E pipeline smoke test
Run the full pipeline end-to-end (`python run_pipeline.py config.yaml`) on a small controlled seed set to validate all stages pass without errors, particularly:
- Stage 1 retrieval with new title similarity thresholds
- Stage 9 audit with tracked_with_t4 corpus source
- Stage 10 expert_comms with TOPIC-XX tier breakdown

### 6. Deduplication auto-merge threshold review
Current `dedup.auto_merge_threshold: 0.85`. Verify this is still appropriate given the tighter title similarity rules in retrieval (88 → 98). The dedup step uses a different similarity metric (Levenshtein/Jaro) than the retrieval title check, but they interact — overly liberal dedup may merge papers the stricter title filter would have separately resolved.

### 7. Abstract backfill scope
`abstract_backfill.selected_scope.enabled: true` runs backfill only on the selected corpus (~867 papers). Confirm this is working correctly after the post-selection pipeline ordering fix from the previous session.
