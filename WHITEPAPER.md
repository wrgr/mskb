# MSKB: A Bibliometric Knowledge Engineering Framework for MS Research Navigation

**Multiple Sclerosis Knowledge Base — Technical Whitepaper**

*Version 1.0 | April 2026*

---

## Abstract

The Multiple Sclerosis Knowledge Base (MSKB) is an open-source knowledge engineering framework that transforms the MS research literature into a structured, pedagogically scaffolded knowledge base navigable by undergraduate researchers. MSKB combines bibliometric graph analysis, multi-signal relevance scoring, expert-curated ontology design, and large language model summarization to select, organize, and present approximately 500–650 peer-reviewed MS papers. Unlike prior literature aggregation tools, MSKB (1) makes corpus construction decisions explicit and auditable, (2) embeds pedagogical scaffolding through a learner-centered concept ontology grounded in Bloom's taxonomy, (3) corrects for known structural biases in citation networks that systematically exclude equity and emerging subfield literature, and (4) exposes heterogeneous knowledge graph edges that connect papers, topics, biomedical entities, and learner journey paths in a single browsable static site.

---

## 1. Introduction

Multiple sclerosis (MS) is a complex autoimmune neurological disease affecting approximately 2.8 million people worldwide. Its research literature spans basic immunology and genetics, clinical trial methodology, neuroimaging, neurorehabilitation, epidemiology, health equity, and patient-reported outcomes. A student entering the field faces a body of literature that is simultaneously vast (hundreds of thousands of papers indexed in PubMed), structurally heterogeneous (the citation network connecting basic science to clinical practice is sparse and domain-siloed), and rapidly evolving (the last decade saw approval of over 20 disease-modifying therapies and the identification of Epstein-Barr virus as a near-necessary cause).

Existing tools—PubMed search, Google Scholar, OpenAlex—are retrieval systems, not learning systems. They answer specific queries but do not help a learner understand what they need to know before they can ask the right queries, which papers are foundational versus confirmatory, or how the research landscape has evolved over time. Systematic reviews reduce the literature but require significant domain expertise to read. Textbooks provide pedagogical scaffolding but are years out of date.

MSKB addresses this gap through a multi-stage pipeline that outputs a curated, navigable knowledge base designed specifically for undergraduate researchers moving from basic biology through clinical science to population health.

### 1.1 Design Philosophy

Three principles govern all MSKB design decisions:

**Transparency over automation.** Every significant corpus construction decision—seed selection rationale, connectivity thresholds, equity correction mechanisms, tier rules—is documented in human-readable audit trail files alongside the code that implements it. Algorithmic methods are used where they add value, but their limitations are explicitly flagged and corrected through principled expert judgment.

**Structural over prestige.** Corpus selection relies on citation network structure (cross-seed connectivity, PageRank, k-core) rather than journal impact factors or institution prestige. This approach identifies important papers through the field's collective citation behavior rather than through proxies that correlate with institutional resources.

**Pedagogy as a first-class concern.** The corpus is not an end in itself. Every design decision—scope, tier rules, concept ontology structure, learner journey edges—is evaluated against whether it helps an undergraduate researcher build genuine understanding, not merely access information.

---

## 2. System Architecture

MSKB is organized as an 18-stage reproducible pipeline (Figure 1) that transforms raw OpenAlex data into a static, client-rendered knowledge base site.

```
Stage 0:  Seed governance
Stage 1:  Corpus retrieval (OpenAlex)
Stage 2:  Deduplication and version merging
Stage 3:  Graph construction (citation, co-citation, bibliographic coupling, co-authorship)
Stage 4:  Multi-signal relevance scoring
Stage 5:  Topic discovery (Leiden community detection)
Stage 5b: Topic evidence assignment
Stage 5c: Core corpus selection (T1–T4 tier rules)
Stage 6:  Abstract backfill (PubMed)
Stage 7:  Learner journey construction
Stage 8:  Paper distillation (Claude API)
Stage 9:  Concept–paper linking (Gemini / Anthropic)
Stage 10: Kid journey and topic overview generation
Stage 11: Knowledge graph construction
Stage 12: Corpus audit (automated quality gates)
Stage 13: Visualization metric export
Stage 14: Expert communications packet
Stage 15: Corpus export (CSV / JSON / README)
Stage 16: Static site generation (Astro)
```

All stages are configured through a single `config.yaml` and are individually re-runnable. Outputs are versioned with provenance snapshots recording artifact paths and content hashes.

---

## 3. Data Collection

### 3.1 Primary Source: OpenAlex

MSKB uses [OpenAlex](https://openalex.org/) as its primary bibliographic data source. OpenAlex is a freely accessible, CC0-licensed database of over 250 million scholarly works with rich metadata including abstracts, citation relationships, author affiliations, and concept tags. All retrieval is performed through the OpenAlex REST API with polite-rate-limited requests.

### 3.2 Retrieval Channels

Candidate papers are retrieved through four complementary channels:

**Seed expansion.** A hand-curated set of 40 seed papers and 6 review anchors covering all 18 MS research topics are used as starting points. One-hop citation neighborhoods (papers citing or cited by each seed) are retrieved. This channel captures the established, well-connected literature directly adjacent to canonical topic-defining papers.

**Lexical queries.** Topic-specific query strings are issued against OpenAlex title+abstract search. These capture papers that are MS-relevant but not well-connected to the seed citation network—particularly important for emerging topics and methodological subfields.

**Dataset-anchored search.** Queries anchored to named MS datasets (UK Biobank MS cohort, Swedish MS Registry, Italian MS Register, etc.) capture cohort and registry science that may not be highly cited by basic science seeds.

**Reference list expansion.** The six review anchors (R1–R6) provide expert-curated reference lists that extend coverage into structurally isolated subfields, particularly health equity and global MS epidemiology.

### 3.3 Seed Design Rationale

The 40 seeds are selected to cover document type diversity rather than concentrating on a single document class:

- **Consensus/guideline documents**: McDonald Criteria (2024 revisions), Lublin phenotype definition (2014)
- **Landmark trials**: OPERA I/II (ocrelizumab RRMS), ORATORIO (ocrelizumab PPMS), PARADIGMS (siponimod pediatric)
- **Natural history studies**: Confavreux Lyon cohort (*NEJM* 2000, *Brain* 2006)
- **Mechanistic reviews**: Lassmann (inflammation/neurodegeneration), Khalil (NfL biomarker)
- **Epidemiological studies**: IMSGC GWAS, Bjornevik EBV (*Science* 2022)
- **Equity documents**: Langer-Gould racial disparities, Amezcua disparities in DMT access
- **Patient/advocacy documents**: NMSS Cures Roadmap
- **Clinical AI papers**: AI-assisted diagnosis and prognostication

Seeds explicitly include foundational anchors (flagged with [anchor] in the seed list) that are intentionally older (pre-2010). Papers such as Compston & Coles (*Lancet* 2008), Trapp & Nave (*Annual Review* 2008), and Confavreux et al. (*NEJM* 2000) define conceptual frameworks that subsequent work builds on and generate large, well-documented forward citation neighborhoods. Excluding them on grounds of age would systematically impoverish algorithmic expansion.

### 3.4 Version Merging and Deduplication

Preprint versions, early-access publications, and final journal articles are identified by DOI overlap and fuzzy title matching, then merged into single canonical records. Author name disambiguation is performed using OpenAlex author identifiers. The merged record retains the maximum citation count across versions and the earliest available date of public dissemination.

---

## 4. Corpus Construction

### 4.1 Four-Tier Architecture

Papers are assigned to one of four tiers based on how they enter the corpus:

| Tier | Name | Selection Mechanism | Typical Count |
|------|------|---------------------|---------------|
| T1 | Seeds | Human curation: topic coverage, document type diversity, conceptual importance | 40 |
| T2 | Cross-seed connected | Algorithmic: structural centrality in the seed citation network | ~350–450 |
| T3 | Velocity / Emerging | Algorithmic: high velocity (recent citation growth) relative to within-topic peers | ~50–100 |
| T4 | Expert signal | Human: conference awards, non-Western cohort studies, papers with structural barriers to algorithmic inclusion | ~30–50 |

The four-tier design reflects an explicit position: different selection mechanisms are appropriate for different purposes. Seeds require human curation for conceptual coverage; established literature requires structural connectivity for quality filtering; emerging literature requires velocity as a leading indicator; expert-designated papers require direct human identification because algorithmic methods miss them systematically.

### 4.2 Cross-Seed Connectivity Scoring

The primary quality gate for T2 papers is cross-seed connectivity, defined as the number of distinct seed papers to which a candidate paper is connected by citation edges (citing or cited-by). A candidate achieves effective T2 status under either of two conditions:

```
cross_seed_score ≥ 2
    OR
(cross_seed_score ≥ 1 AND review_anchor_link_count ≥ 1)
```

The bridge clause (`cross_seed ≥ 1 AND anchor ≥ 1`) was added to address a known structural failure mode: papers in structurally isolated but substantively important subfields (particularly health equity) can be strongly connected to one canonical seed and one dedicated expert review anchor while remaining disconnected from the dominant trial/pathophysiology backbone. Requiring `cross_seed ≥ 2` alone would systematically exclude this literature. The bridge clause is a principled correction for a known limitation of purely algorithmic methods.

The "multi-topic bridge" signal—papers connected to seeds from ≥2 different topic codes—is computed and recorded but not used as a filter. These bridging papers often answer the most interesting cross-topic queries and are flagged for the knowledge graph.

### 4.3 Within-Subdomain Importance Scoring

Raw citation counts are ill-suited to compare papers across MS subfields because citation volume differs systematically between subdisciplines: a landmark trial in RRMS accumulates 5–10× more citations than an important equity or registry paper. MSKB addresses this through within-subdomain normalization:

**Importance score** = blend of PageRank (from the corpus citation graph), k-core membership, total citations, and within-corpus in-degree, each normalized to percentile ranks within the paper's assigned topic.

**Age-normalized importance** = for each paper, the within-year percentile rank of citations/year, PageRank, and in-degree, combined and re-normalized. This corrects for the compounding advantage of older papers without discarding historical impact.

**Within-topic citation/velocity max score** = `max(citation_percentile_within_topic, velocity_percentile_within_topic)`. The `max()` rather than `average` or `product` captures both classic foundational papers (high historical citation, zero recent velocity) and newly important emerging papers (high velocity, modest total citations) without requiring both signals simultaneously.

### 4.4 MS Focus Scoring

Not all papers in the citation neighborhoods of MS seeds are MS-focused. A paper on general T cell biology that happens to be cited by an MS immunology review may be important background but is not MS-specific. MSKB computes a focus score from:

- Positive lexical signal: presence of MS-specific terminology in title+abstract
- Negative lexical signal: generic biology terms with no MS context
- T4 exemption: expert-nominated papers bypass focus thresholds, as T4 nomination is itself a focus signal

Papers with high generic biology signal and low seed affinity receive a downweight that prevents the corpus from drifting into general neuroscience or immunology. T4 papers can override this rule explicitly.

### 4.5 Equity Correction Mechanisms

MSKB incorporates four explicit mechanisms to correct for structural biases in the citation network that systematically disadvantage equity and emerging-subfield literature:

1. **Dedicated equity review anchor (R5)**: Amezcua et al. 2021 *JAMA Neurology* provides a reference list that reaches equity papers not connected to the trial/biology backbone.
2. **Bridge clause in cross-seed connectivity**: Allows papers connected to one seed and one review anchor to qualify for T2 without the full `cross_seed ≥ 2` threshold.
3. **Within-subdomain citation normalization**: Equity papers compete against equity papers for percentile ranks, not against landmark trials.
4. **T4 expert channel**: Conference awards, non-Western cohort studies, and papers from underrepresented geographic or institutional origins can be directly nominated.

These mechanisms are documented as explicit design decisions with engineering judgment callouts, not as implicit choices embedded in code.

### 4.6 Corpus Audit Gates

An automated audit (`src/audit_kb.py`) runs as the final pre-export stage and enforces hard gates:

- MS focus distribution: minimum fraction of high-focus papers
- Contamination rate: maximum fraction of non-MS papers
- Category coverage: minimum paper count per anchor category
- Missing data: flagging of papers with no abstract, no author, or no topic assignment

Audit failures block site generation in `--strict` mode, ensuring that corpus degradation is surfaced before publication.

---

## 5. Bibliometric Graph Construction

### 5.1 Graph Types

MSKB builds four bibliometric graph types from the candidate corpus:

| Graph | Nodes | Edges | Information |
|-------|-------|-------|-------------|
| Citation | Papers | A cites B | Direct influence relationships |
| Co-citation | Papers | A and B both cited by C | Shared intellectual context |
| Bibliographic coupling | Papers | A and B both cite C | Shared intellectual foundation |
| Co-authorship | Authors | A and B co-authored | Collaboration structure |

### 5.2 Graph Metrics

For each paper in the corpus, MSKB computes:

- **PageRank**: Probability of reaching the paper via random walk on the citation graph; captures recursive importance (important papers cite it).
- **k-core membership**: Maximum k such that the paper belongs to a subgraph where every node has at least k edges; captures membership in the dense citation core.
- **Betweenness centrality**: Fraction of shortest paths between other papers that pass through this paper; captures bridging between communities.
- **In-degree / out-degree**: Raw citation counts within the corpus.
- **Louvain community**: Community detected by the Louvain modularity optimization algorithm; used as a first-pass topic signal.

### 5.3 Leiden Topic Discovery

Final topic discovery uses the Leiden algorithm (Traag et al. 2019), which produces communities with guaranteed connectivity properties that the Louvain algorithm does not guarantee. Communities are labeled by their dominant OpenAlex concept tags and mapped to the 18 MSKB topic taxonomy. The Leiden partition is used alongside seed-assigned topic codes in the evidence system, with seed assignment taking precedence over algorithmic community detection for topic definition.

---

## 6. Knowledge Graph Construction

### 6.1 Heterogeneous Graph Structure

The MSKB knowledge graph is a heterogeneous property graph with typed nodes and typed edges:

**Node types:**
- `Paper`: bibliographic metadata, scores, tier, topic, distilled summary
- `Author`: name, ORCID, institution
- `Topic`: label, description, anchor category
- `Drug`: normalized drug name (INN where available)
- `Gene`: HGNC symbol
- `Pathology`: MS pathological entity (lesion types, cell types)
- `Biomarker`: fluid or imaging biomarker
- `AnimalModel`: EAE variants, transgenic models

**Edge types:**
- `CITES`: within-corpus citation
- `AUTHORED_BY`: paper–author
- `BELONGS_TO_TOPIC`: paper–topic
- `MENTIONS_DRUG`: paper–drug (regex extraction from title+abstract)
- `MENTIONS_GENE`: paper–gene
- `STUDIES_PATHOLOGY`: paper–pathology
- `USES_BIOMARKER`: paper–biomarker
- `USES_MODEL`: paper–animal model
- `NEXT_PAPER_TO_LEARN`: learner journey edge with rank and score
- `NEXT_TOPIC_TO_LEARN`: learner journey edge for topic-level navigation

### 6.2 MS Entity Extraction

Entity tagging uses curated pattern dictionaries against concatenated title+abstract text. Pattern sets cover:

- **Drugs**: generic names and common brand names for all approved MS DMTs (interferons, glatiramer, natalizumab, fingolimod, siponimod, cladribine, dimethyl fumarate, ocrelizumab, ofatumumab, ublituximab, ozanimod, ponesimod, alemtuzumab, rituximab, teriflunomide) plus experimental agents in late-stage trials
- **Genes**: MS GWAS hits (HLA-DRB1, IL7R, IL2RA, TNFRSF1A, CLEC16A, plus ~200 additional GWAS loci), remyelination genes (Olig1/2, Sox10, LINGO1)
- **Pathology**: lesion types (T2, T1 black hole, paramagnetic rim, cortical, subpial), cell types (oligodendrocyte, microglia, astrocyte, T cell, B cell, plasma cell), pathological processes (demyelination, remyelination, axonal loss, cortical atrophy)
- **Biomarkers**: NfL, GFAP, CHI3L1, sCD163, MBP, IgG index, OCB, MRI volumetrics
- **Animal models**: EAE variants (MOG35-55, PLP139-151, MBP-induced), cuprizone model, lysolecithin model, specific transgenic lines

---

## 7. Learner Journey Construction

### 7.1 Design Rationale

Standard bibliometric tools recommend papers by relevance or citation count. MSKB constructs learner journeys—ordered reading sequences optimized for conceptual understanding rather than relevance alone. The key distinction is that a journey recommendation answers "what should I read *next*, given what I have already read?" rather than "what is most related to this query?"

### 7.2 Journey Edge Construction

`NEXT_PAPER_TO_LEARN` edges are computed for each paper by combining:

- **Citation structure**: Papers that the current paper cites (intellectual prerequisites) and papers that cite it (intellectual consequences) within the corpus
- **Topic adjacency**: Papers in topically adjacent communities as defined by the knowledge graph
- **Bloom's level**: The concept ontology assigns each paper a Bloom's level based on which concept's foundational or advanced list it occupies; journey edges prefer progressions from lower to higher Bloom's levels
- **Score and importance**: Within-topic importance score as a tiebreaker

`NEXT_TOPIC_TO_LEARN` edges are similarly constructed at the topic level, using the prerequisite relationships defined in the Learning Concept Ontology and the density of cross-topic citation connections.

### 7.3 Kid Journey

A separate plain-language reading path (`site/src/content/docs/kid-journey.md`) presents MS research through narrative framing accessible to curious lay readers and classroom settings. Each paper card in the kid journey is accompanied by a plain-language summary generated via the Claude API and quality-checked against a faithfulness rubric.

---

## 8. The MS Learning Concept Ontology (MS-LCO)

### 8.1 Overview

The MS Learning Concept Ontology (MS-LCO, version 2.0) is a learner-centered structured vocabulary for the MS research domain. It is not a formal ontology in the OWL/RDF sense but a pedagogically grounded concept map that specifies what an undergraduate researcher needs to understand at each stage of their learning, what they need to know first, and what evidence best supports each concept.

The MS-LCO is informed by Bloom's taxonomy (Bloom et al. 1956; Anderson & Krathwohl 2001) for hierarchical learning objectives, cognitive load theory (Sweller 1988) for prerequisite scaffolding, and active learning theory (Chi 2009) for concept mapping methodology.

### 8.2 Concept Structure

Each concept in the MS-LCO specifies:

```
Name
├── Definition (what it is; why it matters for MS)
├── Learning Objectives (Bloom's level: Remember → Understand → Apply → Analyze)
├── Prerequisites (concepts that must be understood first)
├── Related Concepts (alternative entry points)
├── Key Questions (self-assessment questions)
├── Primary Evidence Type (review / trial / observational / mechanistic)
├── Recommended Paper Count (3–7 foundational, 2–4 advanced)
└── Resources (papers with DOI, videos, clinical tools, datasets)
```

### 8.3 Concept Hierarchy

The MS-LCO is organized into six major domains:

| Domain | Example Concepts |
|--------|-----------------|
| **MS Fundamentals** | What is MS, Epidemiology and Natural History, Historical Context |
| **Disease Mechanisms** | Demyelination/Remyelination, Blood-Brain Barrier, Genetic Susceptibility, EBV and MS |
| **Clinical Diagnosis** | McDonald Criteria, MRI Patterns, CSF Biomarkers, MS Phenotypes |
| **Disease-Modifying Therapies** | Mechanism Classes, High-Efficacy Therapies, Treatment Sequencing, Monitoring |
| **Progressive MS and Smoldering Disease** | Progression Biology, PIRA, Paramagnetic Rim Lesions, Neuroprotection |
| **Population and Equity** | Health Disparities, Access to Care, Global Epidemiology, Pediatric MS |

The hierarchy encodes prerequisite relationships: understanding B cell depletion (mechanism class) requires prior understanding of B cell biology (immune fundamentals), which requires understanding autoimmunity mechanisms (disease mechanisms). These prerequisite relationships are used directly in learner journey construction.

### 8.4 Novelty of the MS-LCO

Prior MS educational resources (textbooks, review articles, patient organization websites) describe the disease but do not structure knowledge for pedagogical navigation. The MS-LCO is, to our knowledge, the first formalized concept ontology for MS designed specifically to:

1. Map the research literature to learner-centered concepts (not just disease categories)
2. Encode explicit prerequisite relationships for scaffolded progression
3. Directly bind concepts to curated sets of supporting papers with evidence type and Bloom's level annotations
4. Distinguish foundational evidence (conceptual frameworks) from advanced evidence (current research frontiers)

---

## 9. Concept–Paper Linking

### 9.1 The Linking Problem

Each concept in the MS-LCO should be supported by 3–7 foundational papers and 2–4 advanced papers. With ~150 concepts and ~600 corpus papers, manual assignment of all concept–paper pairs is tractable for one iteration but would not be maintainable as the corpus updates. MSKB implements an automated linking pipeline that is refreshable with each corpus update.

### 9.2 Candidate Shortlisting

For each concept, a candidate shortlist is generated using TF-IDF-style ranking of the concept's definition, learning objectives, and key questions against all corpus paper title+abstract texts. Candidate lists are capped per topic to prevent one well-represented topic from monopolizing recommendations for concepts that touch multiple domains.

### 9.3 LLM-Assisted Assignment

The shortlisted candidates are passed to a large language model (Gemini or Anthropic Claude, configurable) with:

- The full concept specification (definition, objectives, prerequisites, evidence type)
- The candidate paper metadata (title, abstract, year, topic, tier)
- A structured JSON output schema specifying `foundational_paper_ids` and `advanced_paper_ids` with `rationale` fields

LLM outputs are validated against the allowed corpus paper IDs (no hallucination of non-corpus papers is permitted) and cached in `data/concept_papers.json` with version provenance.

### 9.4 Heuristic Fallback

When LLM assignment is not available or is deferred, a heuristic path splits candidates into foundational (older, higher importance, review/mechanistic evidence type) and advanced (newer, higher velocity, trial/emerging evidence type) using importance, velocity, and year signals from the scoring stage.

### 9.5 Bidirectional Export

The concept–paper mapping is bidirectional: the site displays which papers support each concept, and the corpus export includes which concepts each paper supports (`concepts_foundational`, `concepts_advanced` fields), enabling external consumers to use the MSKB corpus as a training set for educational retrieval systems.

---

## 10. Site and Visualization

### 10.1 Static Site Architecture

The MSKB site is generated as a static site (Astro framework) deployed to GitHub Pages. Static generation provides zero-infrastructure hosting, full client-side rendering of interactive visualizations, and no server-side attack surface. The pipeline generates MDX content files, JSON data files, and JavaScript visualization assets that are bundled at build time.

### 10.2 Interactive Visualizations

**Field Development View** (`field-development.mdx`): Two coordinated interactive charts—(1) stacked annual publication counts by research domain, showing how the field has grown and how different domains' relative contributions have shifted; (2) a research landscape scatter plot with year on the x-axis, age-normalized importance on the y-axis, and circle size proportional to citation count. Domain checkboxes enable filtering. This view answers: "How has the MS research field evolved, and where is attention currently concentrated?"

**Citation Tree** (`citation_tree.js`): An interactive directed acyclic graph rendering the citation lineage from seed papers forward to contemporary literature, organized by generation depth (BFS layers from seeds). This view answers: "How did knowledge accumulate from foundational papers to current work?"

**Corpus Statistics** (`corpus_stats.js`): Summary statistics dashboard (corpus size, tier distribution, topic coverage, date range, source distribution). Intended for research consumers evaluating the corpus for external use.

**Knowledge Graph Explorer** (`mskb_graph_renderer.js`): Interactive graph rendered with Sigma.js/Graphology, displaying the heterogeneous paper–entity–topic graph. Nodes are sized by importance, colored by type, with configurable edge type filtering. This view answers: "How are papers, topics, drugs, genes, and biomarkers interconnected?"

**Paper Explorer**: Filterable table of corpus papers with facets for topic, tier, domain, year range, and importance score. Each paper links to its distilled summary, concept connections, and citation neighborhood.

### 10.3 Learner Navigation

The site surfaces two primary learner entry points:

**Concept pages**: Each MS-LCO concept has a page showing its definition, learning objectives, prerequisites, and the supporting paper cards (foundational and advanced), each with its distilled summary. Concept pages are cross-linked via prerequisite relationships.

**Topic pages**: Each of the 18 research topics has a page with its paper list, ordered by learner journey recommendation rank, plus links to topically adjacent concepts and topics.

**Learner journeys**: Pre-built paths (e.g., "Start with MS fundamentals", "Jump in at therapeutics", "Focus on progressive disease") provide curated entry points for learners at different stages and with different backgrounds.

---

## 11. Novel Contributions

### 11.1 Auditable Corpus Construction

Most curated literature resources do not document how inclusion/exclusion decisions were made. MSKB treats corpus construction as a first-class engineering artifact: every significant decision—seed selection rationale, connectivity thresholds, equity correction mechanisms, tier rules, engineering judgment callouts—is recorded in a companion audit trail document (`data/ms_corpus_design_decisions.md`) that is version-controlled alongside the code. This enables:

- External replication and challenge of specific design decisions
- Future maintainers to understand not just what was decided but why
- Reviewers to identify potential biases and assess correction mechanisms

We are not aware of prior work in biomedical knowledge base construction that treats corpus design decisions as first-class publishable artifacts with explicit engineering judgment callouts.

### 11.2 Structural Equity Correction

Prior bibliometric corpus construction methods select papers based on citation count, journal prestige, or seed proximity—all signals that systematically correlate with institutional resources and geographic origin. MSKB implements explicit structural corrections for known biases:

- Within-subdomain citation normalization so that equity and global MS papers compete within their own peer group, not against landmark clinical trials
- Dedicated expansion anchors for structurally isolated subfields
- Bridge qualification rules that lower the connectivity threshold for papers connected to equity review anchors
- Expert T4 nomination channel for papers that are important but algorithmically invisible

These corrections are principled (documented rationale) rather than ad hoc (undocumented threshold tuning).

### 11.3 Pedagogical Ontology Bound to Corpus

The MS-LCO binds a formally structured pedagogical ontology to a curated, scored corpus through an automated and refreshable concept–paper linking pipeline. The ontology is not a standalone document but a live specification that (1) generates concept pages on the site, (2) drives learner journey edge construction in the knowledge graph, and (3) exports per-paper concept annotations in the corpus export. This binding between pedagogical structure and bibliometric corpus is, to our knowledge, novel in the MS literature navigation space.

### 11.4 Heterogeneous Learner Knowledge Graph

The MSKB knowledge graph combines three types of information that are typically maintained in separate systems:

- Bibliometric relationships (citation, co-citation, authorship)
- Biomedical entity mentions (drugs, genes, pathology, biomarkers, models)
- Pedagogical relationships (concept prerequisites, learner journey next-paper edges)

Unifying these in a single heterogeneous graph enables queries that span all three types: "What drugs are studied in papers on progressive MS that a learner in Topic 5 should read next?" The graph is exported in both CSV and Parquet formats for downstream use.

### 11.5 Transparent Multi-Signal Scoring

MS relevance scoring in MSKB uses eight signals with documented weights and explicit correction rules:

| Signal | Type | Rationale |
|--------|------|-----------|
| Seed channel membership | Binary | Direct human curation |
| Cross-seed citation connectivity | Structural | Field's collective judgment |
| Review anchor connectivity | Structural | Expert expansion reach |
| Lexical MS relevance | Semantic | Content-based filter |
| Dataset anchor membership | Thematic | Registry/cohort coverage |
| Co-citation affinity to seeds | Structural | Shared intellectual context |
| Bibliographic coupling to seeds | Structural | Shared intellectual foundation |
| Core author overlap | Social | Researcher community membership |

Each signal's weight is configurable and documented. The combination rule (weighted sum with MS-focus corrections and T4 exemptions) is explicit. This contrasts with black-box relevance scoring in commercial literature tools.

---

## 12. Limitations and Future Work

### 12.1 Known Limitations

**OpenAlex coverage gaps.** OpenAlex does not index all journals uniformly, and some MS-relevant conference proceedings and gray literature (ECTRIMS abstracts, clinical guidelines) are not available. The backfill mechanisms (PubMed abstract supplementation, T4 expert nomination) partially address this but do not close the gap.

**Regex entity extraction.** MS entity tagging uses pattern matching rather than neural named entity recognition. This produces false positives (drug name mentioned in a different context) and false negatives (novel entity names, non-standard abbreviations). A future iteration should incorporate a fine-tuned biomedical NER model.

**LLM faithfulness in distillation.** Paper distillations generated by the Claude API are spot-checked using a faithfulness rubric but are not systematically evaluated for accuracy or comprehensiveness. Hallucinations in distillations are a known risk. Users should be advised that distillations are reading aids, not substitutes for primary sources.

**Static corpus update cycle.** The corpus is a snapshot. New MS papers—including major trial results—are not automatically incorporated. A continuous update pipeline with incremental corpus refresh and re-scoring would improve currency.

**Threshold calibration without retrieval evaluation.** The numeric thresholds for cross-seed connectivity (`≥ 2`), MS focus, and tier selection were calibrated by inspection rather than against retrieval quality metrics. Sensitivity analysis of thresholds against downstream retrieval performance (e.g., how well does the corpus answer student queries?) remains undone.

**Single-disease scope.** MSKB is built for MS. The pipeline architecture is disease-agnostic, but the seed lists, concept ontology, entity dictionaries, and topic taxonomy are all MS-specific. Extending to other neurological diseases would require substantial domain expert effort in seed curation and ontology construction.

### 12.2 Future Work

**Retrieval quality evaluation.** The most important near-term priority is evaluating corpus quality against retrieval benchmarks—does the corpus answer the questions that undergraduate MS researchers actually ask? This requires a question set, a retrieval system (e.g., RAG over distilled summaries), and human expert annotation of answer quality.

**Automated threshold sensitivity analysis.** Running the pipeline with varied threshold values (cross-seed floor, MS focus gate, tier caps) and measuring downstream corpus statistics would enable principled threshold selection rather than inspection-based calibration.

**Incremental corpus update.** Implementing a monthly or quarterly update cycle with change tracking (new papers added, papers re-tiered, concept assignments updated) would improve currency and enable longitudinal analysis of how the corpus evolves.

**Neural entity extraction.** Replacing regex entity tagging with a fine-tuned biomedical NER model (e.g., PubMedBERT-NER or BioMedLM) would improve entity recall and precision, particularly for novel agents and genetic variants.

**Multi-disease extension.** The pipeline architecture is a candidate template for other disease areas with similar structure—a large, heterogeneous literature with an undergraduate educational gap. Extension to neuromyelitis optica spectrum disorder or myelin oligodendrocyte glycoprotein antibody disease (conditions closely related to MS) would be a natural first test of generalizability.

---

## 13. Implementation

### 13.1 Technology Stack

| Component | Technology |
|-----------|------------|
| Data retrieval | Python, OpenAlex REST API |
| Graph construction | NetworkX, iGraph |
| Community detection | Leiden (leidenalg), Louvain (python-louvain) |
| LLM distillation | Anthropic Claude API |
| LLM concept linking | Anthropic / Google Gemini API (configurable) |
| Site generation | Astro, MDX |
| Graph visualization | Sigma.js, Graphology, Cytoscape.js |
| Data export | Pandas, Parquet (PyArrow) |
| Testing | pytest |
| CI/CD | GitHub Actions, GitHub Pages |

### 13.2 Reproducibility

The full pipeline is reproducible from the seed list and a valid OpenAlex API key. Configuration is managed through a single `config.yaml`. All pipeline stages write versioned outputs with provenance snapshots. The corpus export includes a `README.md` documenting all fields and their derivation. The `data/ms_corpus_design_decisions.md` audit trail documents all non-algorithmic decisions.

### 13.3 Open Source

MSKB is released as an open-source project. The pipeline code, concept ontology, corpus design audit trail, and site source are all publicly available. The corpus export (paper metadata, scores, concept assignments) is published under a CC BY 4.0 license. The OpenAlex source data is CC0.

---

## 14. Conclusion

MSKB demonstrates that a curated, pedagogically scaffolded knowledge base for a complex research domain can be built from open bibliographic data through a combination of bibliometric graph analysis, multi-signal relevance scoring, explicit equity correction, expert-curated pedagogical ontology, and LLM-assisted summarization—with all significant decisions documented as auditable engineering artifacts.

The system's primary novelty is not any individual algorithm but the integration of methods into a pipeline where bibliometric rigor, pedagogical scaffolding, and equity correction are treated as co-equal engineering requirements rather than afterthoughts. The result is a knowledge base that is simultaneously useful for undergraduate learners (navigable concept-to-paper paths), useful for domain experts (reproducible, auditable corpus with documented design decisions), and useful for knowledge engineering researchers (a worked example of principled bibliometric corpus construction with explicit bias correction mechanisms).

The MSKB pipeline architecture is disease-agnostic and could serve as a template for knowledge base construction in other complex research domains where a large, structurally heterogeneous literature presents barriers to entry for new learners.

---

## References

Anderson, L. W., & Krathwohl, D. R. (Eds.). (2001). *A taxonomy for learning, teaching, and assessing: A revision of Bloom's educational objectives*. Longman.

Bjornevik, K., et al. (2022). Longitudinal analysis reveals high prevalence of Epstein-Barr virus associated with multiple sclerosis. *Science*, 375(6578), 296–301.

Bloom, B. S. (Ed.). (1956). *Taxonomy of educational objectives: The classification of educational goals. Handbook I: Cognitive domain*. David McKay Company.

Brin, S., & Page, L. (1998). The anatomy of a large-scale hypertextual web search engine. *Computer Networks and ISDN Systems*, 30(1–7), 107–117.

Chi, M. T. H. (2009). Active-constructive-interactive: A conceptual framework for differentiating learning activities. *Topics in Cognitive Science*, 1(1), 73–105.

Compston, A., & Coles, A. (2008). Multiple sclerosis. *Lancet*, 372(9648), 1502–1517.

Confavreux, C., et al. (2000). Relapses and progression of disability in multiple sclerosis. *New England Journal of Medicine*, 343(20), 1430–1438.

Hicks, D., et al. (2015). Bibliometrics: The Leiden Manifesto for research metrics. *Nature*, 520(7548), 429–431.

Pringsheim, T., et al. (2020). The incidence and prevalence of multiple sclerosis in Canada. *Multiple Sclerosis Journal*, 26(13), 1830–1837.

Reich, D. S., Lucchinetti, C. F., & Calabresi, P. A. (2018). Multiple sclerosis. *New England Journal of Medicine*, 378(2), 169–180.

Sweller, J. (1988). Cognitive load during problem solving: Effects on learning. *Cognitive Science*, 12(2), 257–285.

Traag, V. A., Waltman, L., & van Eck, N. J. (2019). From Louvain to Leiden: Guaranteeing well-connected communities. *Scientific Reports*, 9(1), 5233.

Trapp, B. D., & Nave, K. A. (2008). Multiple sclerosis: An immune or neurodegenerative disorder? *Annual Review of Neuroscience*, 31, 247–269.

---

*Document maintained alongside the MSKB codebase. For the current corpus specification, see `data/ms_corpus_design_decisions.md`. For the learning concept ontology, see `LEARNING_CONCEPT_ONTOLOGY.md`. For pipeline implementation, see `README.md`.*
