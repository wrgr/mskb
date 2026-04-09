# MS Knowledge Base: Corpus Design Decisions and Justification
## Domain-Specific Document

*Version 1.2 | April 2026*
*Companion to: Corpus Construction Methodology (Generic) and MS Corpus Specification v1.0 (Excel)*

---

## Purpose

This document records every significant design decision made in constructing the MS Knowledge Base corpus. It is the audit trail for the corpus specification — explaining not just what was decided but why, with citations where the decision draws on published literature or evidence.

Intended readers: anyone who needs to understand, replicate, challenge, or extend the corpus — including future team members, external reviewers, and the researchers whose work is included or excluded.

---

## 1. Scope and Target Size

**Decision:** Target corpus range of approximately 450–650 documents.

**Rationale:** A knowledge base needs sufficient depth for genuine coverage (too few documents produces thin, unreliable retrieval) but not so many that precision degrades (too many documents dilutes the signal-to-noise ratio in retrieval). The target range was selected based on:

- 18 topics in the orientation map, with estimated 15–35 documents per topic and controlled Tier 2/Tier 3 caps
- Practical review capacity and diversity tradeoff: enough documents for topic coverage without overwhelming manual review
- Manageable corpus size for initial knowledge base deployment and evaluation

No published literature directly specifies optimal corpus sizes for RAG knowledge bases; this remains an empirical question in the knowledge engineering literature. The target should be treated as a starting point subject to revision based on retrieval quality evaluation.

> **⚑ ENGINEERING JUDGMENT:** The 450–650 range and the 15–35 documents-per-topic estimate are derived from the 18-topic orientation map and practical review capacity, not from empirical evidence about optimal RAG corpus sizes. The 18-topic × ~25-doc-per-topic arithmetic is how the range was initially set; nothing in the literature validates this for retrieval quality. Calibration against retrieval evaluation is needed before the target is treated as fixed.

**Decision:** Documents organized into four tiers (T1 seeds, T2 cross-seed connected, T3 velocity/emerging, T4 expert signal).

**Rationale:** Different selection mechanisms are appropriate for different purposes. Seeds require human curation for conceptual coverage; established literature requires structural connectivity for quality filtering; emerging literature requires velocity as a leading indicator; expert-designated documents (conference awards, non-Western cohort studies) require explicit human identification because algorithmic methods miss them systematically.

---

## 2. Seed Selection

**Decision:** 40 seeds across 18 topics (plus Topic 1b, Natural History), with a baseline of 2 per topic and targeted augmentations for thin topics (T09, T13, T16).

**Rationale:** Two seeds per topic remains the baseline for triangulation, but strict uniformity produced under-coverage in patient-reported outcomes (T09), equity (T13), and research-priorities framing (T16). Additional seeds were added only where structural gaps were observed, preserving selectivity while improving topic balance.

> **⚑ ENGINEERING JUDGMENT:** "2 seeds per topic" is a practical minimum, not a statistically validated triangulation requirement. The augmentation decision for T09/T13/T16 was made post-hoc after observing structural gaps in the provisional corpus — the same gap-detection logic could justify augmentation for other thin topics in future iterations. No formal procedure exists for deciding when augmentation is warranted.

**Decision:** Seeds selected to cover document type diversity — not only review articles or trials.

**Rationale:** A corpus seeded only with review articles would have one-hop neighborhoods populated primarily by the sources reviews cite — heavily weighted toward foundational and established literature. A corpus seeded only with trials would miss the biological and methodological literature. The seed set intentionally includes consensus/guideline documents (McDonald criteria, Lublin phenotype definition), landmark trials (OPERA, ORATORIO, PARADIGMS), natural history studies (Confavreux Lyon cohort), mechanistic reviews (Lassmann, Khalil NfL), epidemiological studies (IMSGC GWAS, Bjornevik EBV), equity documents (Langer-Gould), patient/advocacy documents (NMSS Cures Roadmap), and clinical AI papers.

**Decision:** Seeds explicitly include foundational anchors that are intentionally old (pre-2010), flagged with ⚓ symbol.

**Rationale:** Some papers establish conceptual frameworks that all subsequent work builds on — Compston & Coles 2008, Trapp & Nave 2008, Confavreux 2000, Franklin & Ffrench-Constant 2008 — even though their treatment content is outdated. These papers generate large, well-documented forward citation neighborhoods that capture a significant portion of the field's subsequent development. Excluding them on grounds of age would impoverish the algorithmic expansion.

The ⚓ flag communicates to corpus users that these documents should be read for conceptual framing, not current guidance.

**Decision:** Natural History (Topic 1b) added as an explicit topic between Disease Overview and Pathophysiology, with Confavreux et al. *NEJM* 2000 (PMID: 11078767) and Confavreux & Vukusic *Brain* 2006 (PMID: 16415308) as seeds.

**Rationale:** The pre-DMT disease trajectory literature is the conceptual foundation for the entire progressive MS and smoldering disease research agenda. The Lyon cohort established that disability progression, once underway, proceeds independently of prior or concurrent relapse activity — a finding that directly challenged the assumption that suppressing relapses would prevent long-term disability (Confavreux et al. 2000). Without natural history seeds, the algorithmic expansion would underrepresent this foundational literature.

This gap was identified through a clinician-scientist persona review: Ellen Mowry (JHMI) would immediately notice the absence of the pre-treatment baseline that makes DMT trial effect sizes interpretable.

---

## 3. Expansion Source Design

**Decision:** 6 review articles added as expansion sources (R1–R6), distinct from seeds.

**Rationale:** Seeds are anchor documents representing canonical topics. Review articles are hub documents with large, expertly curated reference lists. They expand the candidate pool into areas not well-connected to the specific seeds chosen. Without review article expansion, papers in methodologically distinct subfields (equity, implementation science, global burden) that don't appear in the neighborhoods of clinical trial or biology seeds would be systematically missed.

The 6 review anchors were selected for:
- Comprehensive scope (field-wide rather than topic-specific)
- Recency (2018–2025)
- Institutional and geographic diversity of authorship

**Critical constraint documented explicitly:** Cross-seed connectivity is scored against the 40 seeds, with an explicit bridge clause: papers can satisfy effective Tier 2 via `cross_seed_score >= 2` or via `cross_seed_score >= 1` and `review_anchor_link_count >= 1`. Review anchors remain expansion sources rather than full quality anchors.

**Decision:** Keep the Reich/Lucchinetti/Calabresi 2018 *NEJM* review (R1) alongside the more recent Jakimovski 2024 *Lancet* review (R2), rather than replacing it.

**Rationale:** The 2018 paper has 7 years of forward citations that the 2024 paper has not yet accumulated. Papers published 2018–2024 that are important to the field will have cited Reich et al. as background. The 2024 paper captures what's current; the 2018 paper captures what accumulated between 2018 and the present. Together they bracket the citation mass of an important period. The 2018 paper also has distinctive emphasis on lesion heterogeneity and the Mayo Clinic pathology tradition (Lucchinetti) not replicated in the 2024 review.

**Decision:** Include Kuhlmann et al. 2023 *Lancet Neurology* progressive MS framework paper (R3) specifically because of its author list.

**Rationale:** The International Advisory Committee authorship includes Ellen Mowry, Jorge Correale (Latin America), Ruth Ann Marrie, and Jennifer Graves — researchers whose perspectives and the papers they treat as important are structurally embedded in the review's reference list. This paper is included partly for its intellectual content and partly for what its reference list will contribute to geographic and perspectival diversity in the expansion.

**Decision:** Include a dedicated equity review (R5: Amezcua et al. 2021 *JAMA Neurology*) as an expansion source.

**Rationale:** Equity papers are structurally disconnected from the basic science and clinical trial citation network. The cross-seed connectivity filter would systematically miss important equity literature because equity papers don't get cited by DMT trials or pathophysiology papers — and vice versa. A dedicated expansion source is the mechanism for capturing this structurally isolated but substantively important subfield. This is a principled use of expert knowledge to correct for a known limitation of algorithmic methods.

---

## 4. Cross-Seed Connectivity

**Decision:** Use an effective Tier 2 connectivity rule: `cross_seed_score ≥ 2` OR (`cross_seed_score ≥ 1` AND `review_anchor_link_count ≥ 1`).

**Rationale:** A paper appearing in the one-hop neighborhood of multiple seeds has demonstrated structural importance in the field's citation network, independent of which institution produced it or what its absolute citation count is. This directly addresses the goal of identifying important papers outside the well-known labs: structural centrality in the citation network is earned by the field's collective citation behavior, not by institutional prestige.

The `cross_seed_score ≥ 2` floor remains the default quality gate. The added `seed+anchor` bridge clause addresses a known structural failure mode in thin but important subfields (especially equity): papers can be strongly connected to one canonical seed and one dedicated expert review anchor while remaining disconnected from the dominant trial/pathophysiology backbone.

The "multi-topic bridge" signal (seeds from ≥2 different topic codes) is recorded but not used as a filter. These bridging papers often answer the most interesting cross-topic queries.

> **⚑ ENGINEERING JUDGMENT:** The specific numeric floors (cross_seed ≥ 2, or cross_seed ≥ 1 AND review_anchor_link_count ≥ 1) were calibrated by inspection of the provisional corpus, not derived analytically. Lowering the floor increases recall but risks including tangentially related papers; raising it increases precision but worsens structural bias against thin subfields. No sensitivity analysis of these thresholds against retrieval quality has been performed.

**Decision:** Preserve seed-anchored quality scoring while allowing anchor-informed bridge qualification.

**Rationale:** Direct seed connectivity remains the primary structural signal. Review anchors are not independent quality anchors, but their link count is allowed as a secondary bridge term to correct known structural disconnection in thin subfields (see Section 3).

---

## 5. Within-Subdomain Citation Score

**Decision:** Use max(citation_percentile, velocity_percentile) within each assigned topic rather than a combined score or citation count alone.

**Rationale for max() rather than average or product:**
- A classic paper with high historical citations but zero recent velocity (foundational but superseded) is valuable for a knowledge base
- A new paper with high velocity but modest total citations (emerging and important) is also valuable
- The max() captures both without requiring both simultaneously
- An average or product would systematically disadvantage either foundational papers or emerging papers

**Rationale for within-subdomain rather than cross-field normalization:**
Raw citation counts are ill-suited to compare the impact of papers from different scientific fields due to widely varying citation practices (Hicks et al. 2015; Brin & Page 1998). The MS equity literature generates far fewer citations per paper than the basic science or RCT literature — not because equity papers are less important but because citation volume differs systematically between subfields. Computing percentiles within the subdomain corrects for this: equity papers compete against equity papers, not against landmark trials.

**Decision:** Set topic-specific thresholds rather than a uniform threshold.

**Rationale:** Different topics have different-sized candidate pools after one-hop expansion. A uniform 90th percentile threshold would yield very different document counts for large subfields (DMTs, biomarkers) vs. small ones (pediatric MS, equity). Topic-specific thresholds are set to yield the target document counts from the orientation map. This is correct: different thresholds reflect different subdomain sizes, not differential quality standards.

> **⚑ ENGINEERING JUDGMENT:** Topic-specific thresholds are calibrated to yield document counts matching the orientation map targets (15–35 per topic). The calibration is not a documented reproducible procedure — it is judgment applied to provisional candidate counts. A topic with very few candidates above any reasonable threshold will require manual supplementation or T4 designation; no automated fallback exists for this failure mode.

---

## 6. Multi-Topic Assignment

**Decision:** Allow multi-topic assignment with the constraint that secondary topics require substantive content, not just citations.

**Rationale:** Many important papers genuinely bridge topics. A DMT trial reporting neurofilament light chain as a secondary endpoint is both a DMT paper (T07) and a biomarker paper (T06). Allowing only one topic would prevent this paper from competing in the biomarker subdomain, potentially causing it to be excluded if the DMT subdomain is already well-populated.

The content test ("Does this paper report findings on Topic X, or merely cite a Topic X paper?") prevents inflation: DMT trials that merely cite the Khalil NfL review in their introduction are not biomarker papers.

Maximum 3 secondary topics prevents over-assignment that would dilute the quality signal.

**Rationale for "any topic" rather than "primary topic only" for passing the threshold:**
Bridging papers — papers that connect multiple topics — are often the most valuable in a knowledge base because they enable cross-topic queries. Restricting passage to primary topic would systematically exclude precisely the papers most useful for complex questions.

---

## 7. Tier 3 (Velocity/Emerging) Design

**Decision:** Tier 3 uses a recency plus accumulation rule: publication year ≥ 2022 and citations_per_year ≥ 20, with optional minimum connectivity (`cross_seed_score` floor configurable; default 0).

**Rationale:** Very new papers may not yet have accumulated multi-seed connectivity, so a strict Tier 2-style graph gate will under-select emerging work. Using a direct accumulation threshold ("accumulating citations in general") is easier to audit than percentile-only velocity rules and avoids cross-topic denominator effects. Citation rate is computed over observed paper age (i.e., divide by available years, not a fixed full window for newer papers).

The manual check requirement is essential: velocity alone can be gamed or inflated in thin subfields where a small number of papers cite each other rapidly. Human judgment is the safeguard.

> **⚑ ENGINEERING JUDGMENT:** The citations/year ≥ 20 floor (≈ 2 citations/month) was set by inspection to exclude papers not demonstrably gaining broad field uptake. No sensitivity analysis has been performed. Tightening to 25 or loosening to 15 would materially change T3 candidate pools; the right value likely varies by subfield and should be calibrated post-retrieval-evaluation.

**Decision:** Tier 3 selection remains capped and manually reviewed; recency/accumulation is a screening signal, not automatic inclusion.

**Decision (April 2026 update):** Tier 3 cap is now topic-coupled rather than global:  
`T3_cap(topic) = max(5, ceil(0.20 × T2_count(topic)))`.

**Rationale:** A topic-coupled cap preserves proportionality between established and emerging literature while preventing dominant topics from monopolizing Tier 3 capacity. The floor of 5 preserves minimal forward-looking coverage for sparse topics.

> **⚑ ENGINEERING JUDGMENT:** The 20% fraction (`T3_cap = max(5, ceil(0.20 × T2_count))`) encodes a target T3:T2 ratio of approximately 1:5. The floor of 5 ensures emerging-literature coverage even for very small topics. Both values were set by inspection of provisional corpus proportions, not by empirical modeling of learner needs or retrieval quality. The cap is implemented in `select_core_corpus.py:_select_t3_ids` and is configurable via `config.yaml:core_corpus_selection.t3.cap_fraction_of_t2_per_topic` and `floor_per_topic`.

**Decision (April 2026 update):** Tier 2 structural rule is now explicit:
- `cross_seed_score >= 2`
- `kcore >= 4`
- `in_degree >= 2`
- `paper_importance_score > P70(anchor_category)`

For topics contributing `<2%` of the strict-pass provisional corpus, `kcore` and `in_degree` are relaxed while retaining cross-seed and category-relative importance requirements.

**Rationale:** Structural gates improve precision in large topics, but can over-penalize thin topics with sparse citation graphs. The `<2%` relaxation is a controlled fairness correction that preserves relevance gates while reducing systematic underrepresentation.

> **⚑ ENGINEERING JUDGMENT:** The 2% threshold identifies topics that fall below a minimum viable representation in the strict-pass provisional corpus. At a 450-document target, 2% ≈ 9 papers — chosen as a rough floor for a topic to be query-answerable. This threshold is corpus-size-sensitive: for a 600-document corpus the equivalent floor would be ~1.5%. The relaxation is implemented as a two-pass approach in `select_core_corpus.py`: strict-pass first, then identify under-threshold topics, then re-evaluate those topics with structure gates removed.

**Decision (April 2026 update):** Final corpus balancing applies a hard concentration constraint: no topic may exceed 20% of the selected corpus.

**Rationale:** Without an explicit concentration cap, broad foundational topics dominate by volume even after Tier gates. A hard ceiling enforces minimum topical diversity and improves downstream retrieval balance for learners.

> **⚑ ENGINEERING JUDGMENT:** The 20% cap ensures at least 5 topics are represented in any 100-paper sample. The value was chosen by inspection — no evidence base exists for this specific ceiling. The cap is enforced iteratively in `select_core_corpus.py:_apply_topic_cap`, which trims the lowest-tier, lowest-importance papers from over-represented topics. This trimming order (T3 before T2, lower importance before higher) is one reasonable policy; alternatives (proportional trimming, recency-preserving) would yield different tradeoffs and have not been evaluated.

---

## 8. Tier 4 (Expert Signal) Design

**Decision:** Tier 4 is kept deliberately small (target ~50–60 documents, 10–12% of corpus).

**Rationale:** A small, high-precision Tier 4 where every document has a documented expert signal is more defensible than a large one requiring criteria that are harder to apply consistently. If Tier 4 is too large, it becomes a catch-all that undermines the algorithmic rigor of Tiers 2 and 3.

> **⚑ ENGINEERING JUDGMENT:** The 10–12% ceiling was set to prevent T4 from exceeding the typical size of a large T2 topic cluster. It was not derived from analysis of how many expert-signal documents a corpus of this size requires. At the April 2026 count (52 concept-anchor papers, 45 new additions), T4 sits at roughly 7–10% of a 450–650 document corpus — within the guard but close to the lower bound. Any additional T4 source types should be evaluated against this ceiling before inclusion.

Specific Tier 4 source types were selected to address known algorithmic blind spots:
- **Conference best papers (ECTRIMS, ACTRIMS, AAN):** Conference program committees perform expert selection that identifies emerging important work before publication or citation accumulation. This is explicitly expert curation without algorithmic mediation.
- **NMSS-funded research outputs:** The primary funder of MS research in North America shapes the field's development. Their supported outputs represent the field's strategic priorities.
- **Cures Roadmap reference lists:** Papers cited in the field's own strategic planning document are treated as foundational by the community itself — the highest form of expert endorsement.
- **Explicitly non-Western cohort studies:** The one-hop expansion from US and European seeds systematically underrepresents non-Western literature. Tier 4 is the correction mechanism.
- **Concept-anchor signal (April 2026):** Papers explicitly nominated by editors as required anchors for MSKB educational concept pages covering thin-coverage topic areas. These papers were identified via systematic review of JLA priorities, AAN Quality Measures, and MSIF PROMS framework — areas where the algorithmic T2/T3 selection is structurally thin. Documented in `data/t4_expert_signal.yaml` (52 papers across 8 concept groups, generated 2026-04-09).

  **Coverage by concept group (T4-001 – T4-052):**

  | Concept group | T4 IDs | Count | Primary topic(s) |
  |---|---|---|---|
  | Bladder and bowel dysfunction | T4-001 – T4-006 | 6 | T10 (symptom mgmt) |
  | Depression and anxiety in MS | T4-007 – T4-013 | 7 | T10 |
  | Equity, SDOH, and access | T4-014 – T4-021 | 8 | T13 (equity/SDOH) |
  | Fatigue in MS | T4-022 – T4-028 | 7 | T09 (PROs), T10 |
  | Pediatric MS | T4-029 – T4-034 | 6 | T12 (pediatric) |
  | Rehabilitation and exercise | T4-035 – T4-041 | 7 | T10 |
  | Sex and gender differences | T4-042 – T4-046 | 5 | T14 (special populations) |
  | Shared decision-making | T4-047 – T4-052 | 6 | T09, T16 (research priorities) |

  **Outcome split:** 7 of 52 were already structurally included in the corpus (identified via `corpus_status: title_fuzzy(p)` or `doi_match` in the YAML). For these papers the T4 record formalises the educational expert signal and links the paper to its concept page. 45 are new additions not reached by T2/T3 graph selection.

  **Implementation pathways:** Papers matched to existing corpus entries (via `corpus_id` or `corpus_doi`) are added as `T4_mapped` rows annotated with T4 concept metadata (`tracked_source = T1_T2_T3_plus_T4`). Papers not found in the scored corpus (`corpus_status: not_found`) are added as forced stub entries with synthetic IDs (`canonical_paper_id = t4::<t4_id>`), `paper_importance_score = 0`, and `tracked_source = T4_forced_not_found`. Forced stubs carry no bibliometric signals; they appear in `core_corpus_tracked_with_t4.csv` and the separate `t4_forced_not_found.csv` for manual review and OpenAlex ID resolution in future pipeline runs.

**Decision:** cross_seed_score = 0 is acceptable for Tier 4 documents if an explicit expert signal is documented.

**Rationale:** Some of the most important documents for certain purposes — patient advocacy documents, non-Western cohort studies, emerging conference abstracts — may have minimal citation connectivity to the core literature but are substantively important. The expert signal documentation substitutes for algorithmic quality evidence.

---

## 9. Topic Map Design

**Decision:** 18 topics (plus Topic 1b) organized in three layers: Foundation, Clinical, Context/Future.

**Rationale:** The layering reflects genuine epistemological dependencies. Clinical topics (diagnosis, treatment, monitoring) presuppose the biological vocabulary established in Foundation topics. Contextual topics (equity, pediatrics, AI, research priorities) are most meaningful when read against the clinical baseline. The layering guides reading order and helps corpus users understand which topics are prerequisite to others.

**Decision:** Topic 1b (Natural History) is numbered 1b rather than a new integer to preserve backward compatibility with earlier versions of the orientation guide.

**Decision:** Topic 16 (Research Priorities & Cures Roadmap) was added to represent the field's collective strategic agenda.

**Rationale:** The NMSS Pathways to Cures Roadmap is the only document in the seed list that: (a) explicitly incorporates patient priorities in its methodology (input from 300+ people living with MS), (b) provides a cross-cutting research agenda rather than domain-specific evidence, and (c) has been endorsed by 30+ MS societies globally. Treating it as a standalone topic elevates it to the status it deserves for corpus users working at the intersection of research, advocacy, and funding.

---

## 10. Equity and Source Diversity Decisions

**Decision:** Equity and SDOH (Topic 13) is assigned to the Context/Future layer rather than the Foundation or Clinical layer.

**Rationale:** The layering is a reading recommendation reflecting epistemological dependencies, not a value judgment about importance. Equity research is most meaningful when read against the Clinical baseline — it critically interrogates the assumptions baked into the clinical literature. Placing equity in Layer 3 is not a statement that it matters less; it is a statement that its critical function is best understood after the baseline it is critiquing has been established.

**Decision:** Topic 13 seed set was rebalanced from a single-author concentration to a mixed anchor set (Wallin 2023 prevalence, Langer-Gould 2022 prevalence disparities, Langer-Gould 2013 incidence).

**Rationale:** The 2025 structural-racism review was conceptually strong but too new to provide structural pull in the graph. Replacing it with Wallin 2023 and adding Langer-Gould 2013 increased T13 neighborhood depth while preserving equity framing through review anchor R5 and retaining structurally connected disparities epidemiology seeds.

**Decision:** The patient voice is acknowledged as an explicit gap in the seed list, not papered over.

**Rationale:** The corpus is research-oriented, and the qualitative and lived-experience literature is structurally outside the scope of a corpus anchored in peer-reviewed medical research. Acknowledging this gap explicitly — rather than pretending it doesn't exist — is honest and allows corpus users to know what the knowledge base cannot tell them. The Cures Roadmap is identified as the closest bridge because it explicitly incorporated patient priorities in its methodology.

---

## 11. QA Overlap Check Design

**Decision:** The QA overlap check uses per-anchor overlap percentages rather than a single global metric.

**Rationale:** A high global overlap could mask low overlap for specific topics. Per-anchor overlap with topic annotations allows targeted diagnosis: low overlap for the equity review anchor (R5) signals underrepresentation of equity literature specifically, prompting targeted remediation rather than general expansion.

**Decision:** The threshold of 70% as the target for "seeds well-chosen" is an operational heuristic, not a validated threshold.

> **⚑ ENGINEERING JUDGMENT:** The 70% floor was set by expectation reasoning (roughly 30% of review references are topic-specific or tangential), not by empirical calibration. Per-anchor tracking is the meaningful diagnostic — a low overlap on the equity anchor (R5) specifically signals a structural gap, not a general seed weakness. The threshold should be revisited after end-to-end retrieval quality evaluation.

**Transparency:** This is documented explicitly because stating it as validated would be misleading. The threshold is set based on the expectation that ~70% of review article references should be field-canonical enough to appear in seed neighborhoods; ~30% represents topic-specific, methodological, or tangential citations that the seeds appropriately don't capture. Future corpus iterations should empirically calibrate this threshold based on retrieval quality evaluation.

---

## 12. Decisions Explicitly Not Made (Exclusions)

**One-hop from review anchors only:** Not pursued because it would have produced a corpus anchored in expert-curated review article reference lists rather than the field's structural citation network. Reference list harvesting is a legitimate approach but produces a different kind of corpus — one reflecting review authors' judgments rather than the field's collective citation behavior.

**Venue filter as primary pre-filter:** Proposed and rejected. The claim that "important MS papers overwhelmingly appear in a small set of venues" with high cutoff efficiency is not empirically verified for this domain, and a venue filter would systematically harm equity, implementation science, and non-Western literature which publish in different venues. Venue is retained as one signal in the manual review pass, not an algorithmic gate.

**Pure PageRank on the full academic graph:** Not used because PageRank on the full literature is dominated by high-volume fields and famous labs. PageRank computed on a domain-specific subgraph (one-hop neighborhood from seeds) is structurally meaningful; on the full graph it replicates institutional prestige rather than within-domain importance.

---

## 13. Bibliometric References

| Reference | Methodology Element |
|-----------|-------------------|
| Small H. *JASIS* 1973;24:265–269 | Foundation: co-citation as knowledge organization |
| Kessler MM. *American Documentation* 1963;14:10–25 | Foundation: bibliographic coupling |
| Boyack KW, Klavans R. *JASIST* 2010;61:2389–2404 | Comparative citation approaches; hybrid basis |
| Brin S, Page L. *Computer Networks* 1998;30:107–117 | PageRank / structural importance in citation networks |
| Hicks D et al. *Nature* 2015;520:429–431 | Leiden Manifesto; within-field normalization; responsible metrics |
| Priem J et al. *arXiv* 2022:2205.01833 | OpenAlex API — implementation platform |

---

## 14. Known Limitations and Future Work

**Citation API coverage:** OpenAlex has good but not complete coverage. Older papers and non-English publications are underrepresented. The cross-seed connectivity scores for papers from under-indexed venues will be artificially low.

**Threshold validation:** The effective Tier 2 rule (`2` seeds or `1+anchor`) and the Tier 3 accumulation threshold (`≥20 citations/year`, year ≥ 2022) are operational heuristics that should be empirically calibrated through retrieval quality evaluation of the resulting knowledge base.

**Temporal decay:** The corpus will age. Review anchors should be updated to include newer comprehensive reviews as the field evolves. Seeds from 2017 (the two NEJM DMT seeds) and 2018–2019 should be reviewed for replacement in corpus v2.0.

**Equity gap:** The structural disconnection between equity literature and the main MS citation network is a known limitation of all citation-based corpus construction approaches. Tier 4 mechanisms partially address this but do not fully resolve it. Future iterations should consider whether equity research merits a separate, parallel selection pipeline with different parameters.

---

## 15. Concept-Paper Linkage Heuristics

The `link_concepts_to_papers.py` module maps each educational concept page to a ranked shortlist of corpus papers, then selects foundational and advanced paper sets — either via LLM or a deterministic fallback. The following heuristics govern that process.

**Shortlist construction:**

- **MAX_CANDIDATES_PER_CONCEPT = 60:** The TF-IDF-ranked candidate list is capped at 60 papers per concept before LLM or heuristic selection. This prevents oversized prompts while retaining sufficient diversity for the LLM to select from.

  > **⚑ ENGINEERING JUDGMENT:** 60 was chosen to fit within typical LLM context budgets and to provide ~8–10× the number of papers that will ultimately be selected. No analysis was done to verify that the 60th-ranked paper is meaningfully different from no-cap.

- **MAX_PER_TOPIC = 8:** Within the shortlist, no more than 8 papers from the same bibliometric topic cluster are included, regardless of their TF-IDF scores.

  > **⚑ ENGINEERING JUDGMENT:** This cap enforces topical diversity in the shortlist so the LLM (or heuristic) isn't presented with 20 near-identical papers from one cluster. The value 8 is arbitrary; it could be reduced to 5 for finer diversity or raised to 10 without substantially changing most selections.

**Heuristic fallback selection (used when no LLM is available):**

- **Foundational selection key:** Papers are sorted by `(-importance, year_ascending, -score, paper_id)`. This prioritises high-importance (citation-based) papers and, among ties, older papers — on the theory that foundational papers are typically older and highly cited.

  > **⚑ ENGINEERING JUDGMENT:** Sorting foundational by importance-first then age reflects the assumption that classic, heavily cited papers are the best orientation anchors. For fast-moving concepts (BTK inhibitors, PIRA) this heuristic will select older, less relevant papers over newer pivotal ones. The LLM selection is preferred for such concepts; the heuristic is a degraded fallback.

- **Advanced selection key:** Papers are sorted by `(-score, -year, -importance, paper_id)`. This prioritises high lexical relevance and, among ties, newer papers — on the theory that advanced papers are typically recent and concept-specific.

  > **⚑ ENGINEERING JUDGMENT:** Sorting advanced by score-first then recency embeds a bias toward newer specialist papers. For concepts where the most important specialist work is a decade old (e.g., CSF oligoclonal bands), this heuristic may deprioritise it in favour of newer but shallower papers.

- **DEFAULT_FOUNDATIONAL_COUNT = DEFAULT_ADVANCED_COUNT = 8:** Both selection lists are capped at 8 papers each.

  > **⚑ ENGINEERING JUDGMENT:** The 8-paper caps were chosen to match the SELECTION_PROMPT instruction and to ensure concept pages have sufficient breadth without overwhelming learners. No learning-science evidence was consulted for this specific number.

---

## 16. Engineering Judgment Heuristics — Summary Register

This register lists every decision in the corpus construction methodology that was made by inspection or practical reasoning rather than derived from published evidence or empirical calibration. Each entry links to the section where the decision is documented and annotated.

| # | Decision | Value(s) | Section | Sensitivity |
|---|---|---|---|---|
| EJ-01 | Target corpus size | 450–650 docs | §1 | Adjust based on retrieval quality evaluation |
| EJ-02 | Documents per topic target | 15–35 | §1 | Drives topic-specific threshold calibration |
| EJ-03 | Baseline seeds per topic | 2 (augmented to 3–4 for thin topics) | §2 | Lower → more concentration risk; higher → over-seeding |
| EJ-04 | Tier 2 cross-seed floor | ≥ 2 (or ≥1 + anchor ≥1) | §4 | Controls precision/recall tradeoff for T2 |
| EJ-05 | Topic-specific citation thresholds | Calibrated to yield 15–35 docs/topic | §5 | Undocumented procedure; hard to reproduce exactly |
| EJ-06 | T3 citations/year floor | ≥ 20 | §7 | Tightening to 25 reduces T3; loosening to 15 expands it |
| EJ-07 | T3 cap fraction of T2 | 20% (floor: 5 per topic) | §7 | Changes T3:T2 ratio; floor controls sparse-topic coverage |
| EJ-08 | T2 structure relaxation threshold | < 2% of strict-pass corpus | §7 | Corpus-size-sensitive; ~9 papers at 450-doc target |
| EJ-09 | Hard topic concentration cap | 20% of selected corpus | §7 | Trimming order (T3 before T2) is one of several policies |
| EJ-10 | T4 size ceiling | 10–12% of corpus | §8 | At 52 papers / 450-doc corpus ≈ 7–10% — near lower bound |
| EJ-11 | QA overlap threshold | 70% | §11 | Per-anchor tracking is more diagnostic than global threshold |
| EJ-12 | Concept shortlist cap | 60 candidates/concept | §15 | Controls LLM prompt size |
| EJ-13 | Per-topic shortlist cap | 8 papers/topic cluster | §15 | Controls topical diversity in shortlist |
| EJ-14 | Foundational paper sort order | Importance-first, then age-ascending | §15 | Biases toward classics; wrong for fast-moving concepts |
| EJ-15 | Advanced paper sort order | Score-first, then recency-descending | §15 | Biases toward recency; may miss older specialist papers |
| EJ-16 | Papers per selection list | 8 foundational + 8 advanced | §15 | No learning-science validation for this number |

**How to use this register:** Before changing any of these values, (a) check whether a retrieval quality evaluation has been run since the value was set, (b) run the pipeline with the proposed value and compare corpus statistics, and (c) update this table and the corresponding section with the new value and rationale.

---

*Document version 1.2 — April 2026. Update version number and Update Log in the corpus specification workbook when methodology changes.*
