# Handoff — Mobile usability + taxonomy refactor PR

**Branch:** `claude/mobile-usability-improvements-atbue`
**Goal PR scope:** mobile-usable Cytoscape explorer, clearer Add-to-list UX, removal of OCAR takeaway framing, and a companion taxonomy refactor that gives the site two side-by-side layered SVG graphs (Learning spine + Research map) backed by a committed LLM cache linking concepts → papers.

Full approved plan lives at `/root/.claude/plans/peppy-weaving-walrus.md` (sections §1–§10). This doc is the short, picked-up-where-we-left-off version.

---

## 1. Core architecture (decisions to honor)

### Three parallel taxonomies today → two loosely-linked graphs

The repo has three partially-aligned MS taxonomies:
- **Concepts** — 40 markdown files under `site/src/content/docs/concepts/{foundations,mechanisms,diagnosis,clinical,therapeutics}/*.md`. This is the **canonical ontology**, seeded from `LEARNING_CONCEPT_ONTOLOGY.md`. Every concept currently has `papers: []` (broken linkage).
- **Topic clusters** — Louvain communities in `outputs/topics/topic_clusters.csv` + `paper_topics.csv`. Raw, reproducible; its `dominant_category` column is produced by broken `SPECTRUM_ANCHORS` keyword bucketing (`src/discover_topics.py:21–55`).
- **Pathways** — three ordered concept walks under `site/src/content/docs/pathways/{clinical,mechanistic,emerging}.md`.

We **do not merge** these into one graph. We render two companion graphs with a shared visual language:
- **Learning spine** on `/journey/` — layers `pathway → category → concept` (3 / 5 / ~40 nodes). Pure ontology.
- **Research map** on `/topics/` — layers `category → topic → concept_bridge (overlay)`. Citation-derived but grouped under concept categories.

Both are hand-positioned SVGs (no force layout) rendered by one shared module, styled from the same palette, and wired to a shared reading list via a thin pub/sub.

### Concept → paper linkage (the missing edge)

Nothing else works without this. Solution: **one-off LLM pass, result committed to the repo**.

- Script: `src/link_concepts_to_papers.py` (to be written in §4).
- Output: `data/concept_papers.json` (committed). Schema per concept: `{ foundational: [...ids], advanced: [...ids], rationales: {id: "..."} }`.
- `gen_site.py` reads the cache at build time — **deterministic, no API key at build**. `--refresh` / `--only=<id>` flags regenerate.
- Candidate shortlist = keyword/TF-IDF overlap on concept title+description vs paper title+abstract, capped at 8 per topic id for diversity, ~60 per concept total. LLM call uses Haiku 4.5.

### Concept-derived topic categories (display override only)

- `src/discover_topics.py` and its CSVs are **untouched**. `dominant_category` stays as fallback in the raw CSV.
- Site layer computes a new `topic_category` mapping: each topic's display category = the category of its highest-overlap concept (by papers shared). Topics with no concept overlap keep the broken fallback but get flagged `category_source: "fallback"` so the UI can de-emphasize them.

### Shared reading list

- Single `localStorage` key: `mskb.explorer.selection.v1` (already in explorer.js).
- Exposed via `window.mskbJourney = { addIds, removeIds, has, subscribe }` — thin facade over existing `journeySelection` + `persistSelection` + `toggleJourneySelection`. Uses an internal `EventTarget` so graph renderers can refresh badges on selection changes without polling.
- Render on `/explorer/`, `/journey/`, `/topics/` with identical state.
- Export (JSON / BibTeX / Markdown) + Import (JSON / `.bib` / `.md`) on `/journey/` only.

### OCAR removal (site-wide)

Opportunity / Challenge / Action / Resolution framing for key takeaways doesn't map cleanly to every paper. Rendering is now plain bullets. Defensive stripping stays because cached JSON still has the prefixes until distillation is rerun.

---

## 2. Status — what's done vs. what's next

### Completed

1. **§1 OCAR removal** — `site/gen_site.py`, `site/public/javascripts/explorer.js`, `src/distill_papers.py`, `tests/test_distill_papers.py`. Tests green (3 passed). Defensive `^(opportunity|challenge|action|resolution)\s*:\s*` regex strip on render.
2. **§2 Cytoscape mobile fixes** in `explorer.js`:
   - Scoped error handlers (`isExplorerError` + `maybeShowFatalOverlay` with 1.5s debounce).
   - Mobile tap targets: `baseSize = isMobileView ? Math.max(12, raw*1.8) : Math.max(4, raw)`.
   - Cytoscape config: `minZoom: 0.15, maxZoom: 3, tapThreshold: 8, touchTapThreshold: 12, wheelSensitivity: 0.2`.
   - Finite-guard on cluster label `cx/cy`.
   - Coarse-pointer "nearest node within 20px" fallback on background tap.
   - `focusNode` zoom clamp to `[1.2, maxZoom]`.
3. **§3 Add-to-list button — JS side** (mostly done):
   - `journeyButtonLabel` deleted.
   - `renderJourneyButton(id)` + `refreshJourneyButtons()` helpers added.
   - All known call sites (`renderActionButtons`, sidebar card, toggle/clear) wired.
   - **Stub** `notifyJourneyChange()` added as a no-op `EventTarget` dispatcher (full facade lands with §6).
4. **File sanity**: `node --check explorer.js` passes.

### In progress (leave a clean checkpoint before resuming)

- **§3 CSS** — still need to add `.btn-add` / `.btn-in-list` styles in `site/src/styles/custom.css`, with `@media (pointer: coarse) { min-height: 44px }` for tap targets. Reference: plan §3 last bullet.

### Not started

5. **§4 Concept → paper linker**
   - Write `src/link_concepts_to_papers.py` (CLI: default = read-only validate; `--refresh`, `--dry-run`, `--only=<id>`).
   - Build candidate shortlist via keyword/TF-IDF overlap; cap 8 per topic id; ~60 per concept.
   - Call Claude Haiku 4.5 with structured JSON output (foundational + advanced + rationales).
   - Output `data/concept_papers.json` with `version`, `generated_at_utc`, `model`, `prompt_hash`, `concepts`.
   - Run `--refresh` once (needs `ANTHROPIC_API_KEY`), commit the cache.
6. **§5 Unified taxonomy derivation**
   - New module `site/gen_site_taxonomy.py` imported from `gen_site.py`.
   - Steps: concept_index → pathway_steps → concept_to_topics / topic_to_concepts → topic_category (concept-derived) → `layout_layered` helper (barycenter sweep L→R then R→L).
   - `gen_site.py` grows a `_load_concept_papers()` that validates ids against corpus, warns + falls back to empty on mismatch.
7. **§6 `/journey/` page + learning spine**
   - Write `site/src/content/docs/journey.mdx` (template `splash`): hero, `<div id="mskb-graph-spine">`, selection panel (mirrored from explorer.mdx), Learning path card (moved from explorer.mdx), Community reading list (moved), Import/Export section.
   - `gen_site.py` adds `build_learning_spine(...)` → `site/public/assets/learning_spine_graph.json`. Schema in plan §6.
   - Trim `explorer.mdx`: remove learning-path and community cards; add "Open in Learning Journey →" link; add explanatory hero line.
   - `explorer.js`: implement `exportJourneyJSON/Bibtex/Markdown`, `importJourneyFile`, `wireJourneyIO`, and replace the stub `notifyJourneyChange` with the real `window.mskbJourney` facade (addIds/removeIds/has/subscribe).
   - `site/astro.config.mjs`: add sidebar entry "Learning Journey" and reorder to `Concepts → Pathways → Learning Journey → Topics → Explorer`.
   - `index.mdx`: swap one CTA card.
8. **§7 `/topics/` research map**
   - `gen_site.py` rewrites `site/src/content/docs/topics/index.mdx` (was `.md`) with hero, `<div id="mskb-graph-research">`, and a collapsed `<details>` block with the legacy grid (non-JS fallback + SEO).
   - Build `build_research_map(...)` → `site/public/assets/research_map_graph.json`.
   - Each topic page gets a **Concepts this topic supports** block linking `/journey/?concept=<id>`.
9. **§8 Shared SVG renderer**
   - New `site/public/javascripts/mskb_graph_renderer.js` (~350 LoC).
   - Public API: `MSKBGraph.render(rootEl, { dataUrl, onNodeClick, initialId })`.
   - Renders: layer bands → edges → nodes → labels. Controls: search input + filter pills (`All / <groups> / Neighbors`). Detail side panel on click with group chip, summary, href, connected-nodes chips, **"Add papers to list"** button hitting `window.mskbJourney.addIds(...)`.
   - Mobile: pure SVG, `viewBox="0 0 1200 <h>"`, `overflow-x: auto` wrapper, min circle radius 12px, labels hide below ~600px wide, tap → detail panel.
   - Distinct palette from explorer Cytoscape colors.
   - a11y: `role="img"`, aria-labelled nodes, arrow-key layer navigation.
10. **§9 Topic framing + cross-linking**
    - Port `prettifyClusterLabel` (explorer.js:869) to Python `_prettify_topic_label` in `gen_site.py`; apply to topic titles/descriptions.
    - Topic page footer: **"Turn this topic into a learning journey →"** → `/journey/?seed=<topic_id>`, plus **"Related concepts"** block.
    - Concept page footer: **"Citation topics that feed this concept →"** block.
    - `wireJourneyIO` reads `?seed=`, `?concept=`, `?topic=` and passes to the respective graph renderer (`initialId`) or preloads topic foundational papers into selection.
11. **§10 Tests**
    - Extend `tests/test_explorer_assets.py`: add `#journey-import`, `#journey-export-json`, `#mskb-graph-spine`, `#mskb-graph-research` DOM id checks; negative OCAR assertion on generated topic md.
    - New `tests/test_concept_papers_cache.py` — cache parses, every concept id matches a file, every paper id exists, set equality vs disk.
    - New `tests/test_taxonomy_derivation.py` — every pathway step resolves; every topic category is in the 5-set or flagged fallback; ≥30/40 concepts have concept_to_topics entries.
    - New `tests/test_journey_graphs.py` — both JSON files exist; no dangling edge ids; finite x/y; spine has 3 pathways + 5 categories + ≥30 concepts; research map has ≥1 topic per non-empty category.

### Final steps
- `python site/gen_site.py` (regenerate concept + topic pages + both graph JSONs)
- `cd site && npm run build` (Astro build green)
- `pytest tests/` (all green)
- Manual smoke on desktop + mobile (see plan §11 Verification)
- Commit + push to `claude/mobile-usability-improvements-atbue`

---

## 3. Critical files cheat-sheet

| Purpose | Path |
|---|---|
| Explorer page shell | `site/src/content/docs/explorer.mdx` |
| Explorer logic | `site/public/javascripts/explorer.js` |
| Site CSS | `site/src/styles/custom.css` |
| Site generator | `site/gen_site.py` |
| Distillation script (prompt updated) | `src/distill_papers.py` |
| Broken topic categorizer (leave alone) | `src/discover_topics.py` |
| Paper corpus (LLM candidate pool) | `site/public/assets/explorer_details_lite.json` |
| Concept ontology source of truth | `LEARNING_CONCEPT_ONTOLOGY.md` |
| Concept pages (40 files, `papers: []`) | `site/src/content/docs/concepts/**/*.md` |
| Pathways (3 files, ordered concept lists) | `site/src/content/docs/pathways/*.md` |
| Topic clusters CSV | `outputs/topics/topic_clusters.csv` |
| Paper ↔ topic CSV | `outputs/topics/paper_topics.csv` |
| Astro nav config | `site/astro.config.mjs` |
| Index page CTAs | `site/src/content/docs/index.mdx` |

### Files to be created (don't exist yet)

- `src/link_concepts_to_papers.py`
- `data/concept_papers.json`
- `site/gen_site_taxonomy.py`
- `site/src/content/docs/journey.mdx`
- `site/public/javascripts/mskb_graph_renderer.js`
- `site/public/assets/learning_spine_graph.json` (generated)
- `site/public/assets/research_map_graph.json` (generated)
- `tests/test_concept_papers_cache.py`
- `tests/test_taxonomy_derivation.py`
- `tests/test_journey_graphs.py`

---

## 4. Known gotchas

- **Cached OCAR prefixes persist** in `site/public/assets/explorer_details_lite.json` until `src/distill_papers.py` is rerun against the corpus. The render-time regex strip in `explorer.js` and `gen_site.py` is the guard. Don't remove it just because the prompt changed.
- **`window.mskbJourney` facade is still a stub.** Right now `notifyJourneyChange()` only fires a local `EventTarget` change event. The real facade (addIds/removeIds/has/subscribe) lands with §6. Keep the internal `journeyEventTarget` when fleshing it out.
- **Astro/Starlight page created for the first time** — `journey.mdx` needs both the Starlight `splash` template and script tags for `cytoscape.min.js` + `explorer.js` + `mskb_graph_renderer.js`. The existing explorer-only helpers already feature-gate on element presence, so loading them on journey.mdx is safe.
- **Do not merge the two graphs.** Earlier plan iteration did; user rejected it. Keep them side-by-side with a shared palette + shared reading list.
- **Do not touch `src/discover_topics.py` or the CSVs** — the concept-derived category is a site-layer override only.
- **Concept cache must be deterministic at build time.** Default CLI mode is read-only. Only `--refresh` calls the API. CI must never need an API key.
- **Concept linker cache failure mode:** on concept-set mismatch, log warning + fall back to empty per concept — do NOT fail the build. Tests enforce cache freshness loudly.

---

## 5. Suggested resume sequence

1. Finish §3 CSS in `site/src/styles/custom.css` (small, self-contained).
2. Write `src/link_concepts_to_papers.py` (§4). Test with `--dry-run` before `--refresh`.
3. Run `--refresh` once, commit `data/concept_papers.json`.
4. Create `site/gen_site_taxonomy.py` (§5) and wire into `gen_site.py`. Unit test the helper independent of the full site build.
5. Build out `journey.mdx` + `build_learning_spine` (§6) and the renderer shell (§8) together — they're tightly coupled.
6. Research map (§7) is a near-clone of spine once the renderer + taxonomy exist.
7. Cross-linking (§9), tests (§10), full verification.

Each of 2–5 is a good commit boundary on the branch.
