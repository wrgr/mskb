# MSKB Tech Note: KB Plan vs. Literature (Evidence-Grounded Assessment)

Date: 2026-04-07  
Repo: `wrgr/mskb`

## Executive verdict

The current MSKB architecture is directionally strong and consistent with established literature-mining practice:

- citation-network expansion + graph structure is well-grounded,
- algorithmic topic discovery is defensible,
- hybrid retrieval (seed + lexical + dataset) is appropriate for coverage.

The main weaknesses are not architectural; they are governance and quality-control risks:

1. modern-only seed bias can under-represent canonical foundational work,
2. citation-based ranking can amplify cumulative advantage and age effects,
3. LLM distillation needs explicit faithfulness guardrails and provenance checks.

## 1) How the current plan aligns with literature

### 1.1 Retrieval and graph construction

MSKB retrieval design (seed expansion + lexical + dataset channels) aligns with classic citation-network science:

- citation networks have long been used to map knowledge structure (Price, 1965),
- bibliographic coupling and co-citation are standard relatedness signals (Kessler, 1963; Small, 1973),
- community detection via Louvain remains a strong baseline for large graphs (Blondel et al., 2008).

Assessment: **Strong alignment**.

### 1.2 Open scholarly data foundation

Using OpenAlex as primary metadata/citation backbone is methodologically defensible:

- OpenAlex is explicitly designed as an open scholarly graph/API with works-authors-institutions-topics links.

Assessment: **Strong alignment**, with expected caveat that source coverage quality varies by venue/year.

### 1.3 Exploratory interface choice

A graph-first exploratory experience is supported by prior exploratory-search systems in scientific corpora:

- SciSight demonstrated value of blending faceted filtering with graph-aware exploration rather than keyword-only search.

Assessment: **Good alignment** for your undergrad/grad discovery goals.

### 1.4 MS domain framing

Your category framing (pathogenesis/immunology, imaging/biomarkers, therapeutics/trials, clinical care, epidemiology/pop health) is consistent with broad MS literature structure:

- disease-overview and management synthesis in major reviews (Lancet 2018, NEJM 2018, Nat Rev Disease Primers 2018),
- modern progression-oriented framing (Kuhlmann et al., 2023),
- modern diagnostic-biomarker integration (McDonald 2024 revisions, published 2025; MRI consensus updates; CVS/PRL/CL workups),
- mechanistic frontier (EBV-MS linkage and molecular mimicry evidence),
- population genetics signal (IMSGC genomic map).

Assessment: **Strong domain alignment**.

## 2) Where the plan conflicts with evidence (or needs hardening)

### 2.1 Citation-only salience bias

Bibliometric literature warns that citation totals are affected by age, field, and cumulative advantage effects, not only quality/relevance.

Risk to MSKB:

- older/high-visibility papers over-amplified,
- category skew if one subfield has denser citation culture.

Current mitigation in repo:

- core/context split and MS-focus weighting in `src/compute_scores.py`,
- downweighting generic biology without MS linkage.

Needed next:

- keep these controls enforced in every reseed run,
- report category entropy and age-normalized centrality side-by-side.

### 2.2 Seed recency bias

Current core seed set is intentionally modern-heavy (2021+), which improves “current-state” coverage but can miss landmark antecedents.

Risk to MSKB:

- under-representation of foundational mechanistic/diagnostic trial lineage,
- shallower “intellectual ancestry” for undergrads.

Needed next:

- retain modern core but add a bounded “landmark anchor” tranche (score-only or bridge seeds).

### 2.3 LLM distillation reliability

Evidence-synthesis literature on LLM workflows shows promise but still emphasizes evaluation pitfalls, error modes, and the need for rigorous validation.

Risk to MSKB:

- plausible but unfaithful summaries/takeaways,
- overconfident interpretations when abstract/full-text is sparse.

Needed next:

- keep deterministic fallback + caching (already present),
- add automatic faithfulness checks (claim-quote alignment or entailment checks),
- expose stronger provenance per summary (`abstract` vs `full_text` source + timestamp + hash).

## 3) Practical recommendations (priority order)

### P0 (immediate)

1. Add a strict “seed acceptance checklist”:
   - category quota,
   - venue/author caps,
   - MS lexical/concept minimum or explicit bridge justification.
2. Lock audit gates in CI-like step:
   - `% has_ms_focus`,
   - `biology_no_ms_link` in final,
   - category-mix bounds,
   - missing abstract/link rates.
3. Add summary faithfulness QA sample each run (human spot-check + automated sanity rules).

### P1 (next cycle)

1. Add landmark anchor seeds (small set) without sacrificing modern emphasis.
2. Surface age-normalized importance views in explorer (not only raw citation-derived rank).
3. Promote explicit “evidence strength” metadata in paper cards (trial/guideline/review/observational).

### P2 (later)

1. Add active-learning feedback loop:
   - users flag off-topic/low-quality summaries,
   - feedback updates scoring and seed refresh policy.
2. Track retrieval drift over time:
   - channel contribution changes,
   - category drift,
   - topic stability across reruns.

## 4) Bottom line

Your KB plan is well-chosen relative to both bibliometric methods and contemporary MS science. The highest-impact improvements now are governance controls and reliability checks, not major architectural changes.

---

## References (primary or near-primary sources)

1. Price DJD. *Networks of Scientific Papers* (Science, 1965).  
   https://pubmed.ncbi.nlm.nih.gov/14325149/
2. Kessler MM. *Bibliographic coupling between scientific papers* (1963). DOI metadata:  
   https://cir.nii.ac.jp/crid/1360574094366898176
3. Small H. *Co-citation in the scientific literature* (1973).  
   https://www.semanticscholar.org/paper/Co-citation-in-the-scientific-literature%3A-A-new-of-Small/da30b84925764b550b55c7d00596f8f1b9608fe2
4. Blondel VD et al. *Fast unfolding of communities in large networks* (2008).  
   https://doi.org/10.1088/1742-5468/2008/10/P10008  
   (metadata mirror: https://researchportal.unamur.be/en/publications/fast-unfolding-of-communities-in-large-networks/)
5. Priem J, Piwowar H, Orr R. *OpenAlex* (arXiv, 2022).  
   https://arxiv.org/abs/2205.01833  
   OpenAlex docs: https://docs.openalex.org/how-to-use-the-api/api-overview
6. Hope T et al. *SciSight* (EMNLP Demos, 2020).  
   https://aclanthology.org/2020.emnlp-demos.18/
7. Hicks D et al. *Leiden Manifesto for research metrics* (Nature, 2015).  
   https://www.nature.com/articles/520429a
8. Belter CW. *Bibliometric indicators: opportunities and limits* (JMLA, 2015).  
   https://pubmed.ncbi.nlm.nih.gov/26512227/
9. Thompson AJ et al. *Multiple sclerosis* (Lancet, 2018).  
   https://pubmed.ncbi.nlm.nih.gov/29576504/
10. Reich DS, Lucchinetti CF, Calabresi PA. *Multiple Sclerosis* (NEJM, 2018).  
    https://pubmed.ncbi.nlm.nih.gov/29320652/
11. Filippi M et al. *Multiple sclerosis* (Nat Rev Dis Primers, 2018).  
    https://www.nature.com/articles/s41572-018-0041-4
12. Bjornevik K et al. *Longitudinal analysis... EBV associated with MS* (Science, 2022).  
    https://pubmed.ncbi.nlm.nih.gov/35025605/
13. Lanz TV et al. *Clonally expanded B cells... EBNA1 and GlialCAM* (Nature, 2022).  
    https://pubmed.ncbi.nlm.nih.gov/35073561/
14. International MS Genetics Consortium. *MS genomic map...* (Science, 2019).  
    https://pubmed.ncbi.nlm.nih.gov/31604244/
15. Wattjes MP et al. *2021 MAGNIMS-CMSC-NAIMS MRI recommendations* (Lancet Neurol, 2021).  
    https://pubmed.ncbi.nlm.nih.gov/34139157/
16. Benkert P et al. *Serum NfL for individual prognostication* (Lancet Neurol, 2022).  
    https://pubmed.ncbi.nlm.nih.gov/35182510/
17. Kuhlmann T et al. *MS progression: mechanism-driven framework* (Lancet Neurol, 2023).  
    https://pubmed.ncbi.nlm.nih.gov/36410373/
18. Borrelli S et al. *CVS/PRL/CL for diagnostic/prognostic workup* (NNI, 2024).  
    https://pubmed.ncbi.nlm.nih.gov/38788180/
19. Montalban X et al. *Diagnosis of MS: 2024 McDonald revisions* (Lancet Neurol, 2025).  
    bibliographic record (PMID 40975101):  
    https://discovery.ucl.ac.uk/id/eprint/10211287
20. Gartlehner G et al. *Challenges/pitfalls in LLM evaluation for evidence synthesis* (BMJ EBM, 2025).  
    https://pubmed.ncbi.nlm.nih.gov/39797673/
21. Hasan B et al. *Integrating LLMs in systematic reviews* (BMJ EBM, 2024).  
    https://ebm.bmj.com/content/29/6/394
