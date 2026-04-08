# Seed Intake Governance Checklist

**Version**: 1.0  
**Date**: 2026-04-08  
**Purpose**: Ensure seed selection is systematic, unbiased, and justified; prevent modern-only bias

---

## I. Overview

This checklist enforces a **two-list seed strategy**:

1. **Expansion Seeds** (`role=expand`): Active retrieval roots; must pass all checklist items
2. **Landmark Anchor Seeds** (`role=landmark_anchor`): Foundational papers; pass checklist items 1-3 + historical justification
3. **Framing Seeds** (`role=score_only`): For scoring/topic shaping only; lighter governance

---

## II. Pre-Intake Checklist (Before Adding Any Seed)

### **A. Metadata Completeness** ✓

- [ ] **DOI present and resolvable** in OpenAlex?
  - If no OpenAlex match: requires strong manual justification + bridge category flag
  - Test: `curl https://api.openalex.org/works/doi:10.1016/...` returns valid work object

- [ ] **Title** populated? (non-empty, matches DOI work)

- [ ] **Author** information available? (first author at minimum)

- [ ] **Publication year** in valid range?
  - For expansion seeds: 2018+ (recent enough for active knowledge)
  - For landmarks: 1995+ (foundational work)

- [ ] **Publication venue** identified?
  - Journal/conference name documented
  - Impact factor or recognition status noted

### **B. MS Relevance** ✓

Pass **one** of the following:

- [ ] **Lexical MS focus**: Title + abstract contain ≥2 MS-specific terms
  - Examples: "multiple sclerosis", "relapsing-remitting", "demyelination", "oligoclonal bands", "natalizumab"
  - **Action**: Check MS_FOCUS_TERMS list in `seed_governance.py`

- [ ] **Concept-level MS focus**: OpenAlex concepts include ≥1 MS-specific concept
  - Examples: "multiple sclerosis research studies", "experimental autoimmune encephalomyelitis"
  - **Action**: Query OpenAlex concepts for work

- [ ] **Bridge justification** (if no lexical/concept MS focus):
  - [ ] Explicitly document why this paper matters to MS despite lacking direct MS mention
  - [ ] Examples: foundational immunology (T cells), mechanistic insight (remyelination biology), methodological exemplar
  - [ ] Fill `bridge_justification` field with >50 characters of reasoning
  - [ ] Require curator sign-off

### **C. Category Assignment** ✓

Assign to **exactly one** primary category:

- [ ] `clinical_care_and_management` – Diagnosis, prognosis, symptom management
- [ ] `clinical_trials_and_therapeutics` – DMT trials, efficacy/safety evidence
- [ ] `epidemiology_and_population_health` – Prevalence, incidence, outcomes, health systems
- [ ] `imaging_and_biomarkers` – MRI, CSF, blood biomarkers, imaging biomarkers
- [ ] `pathogenesis_and_immunology` – Mechanisms, immune biology, genetics, environment

**Action**: If paper spans multiple categories, assign primary (most central) category; document secondary in notes

### **D. Venue Credibility** ✓

Check venue prestige:

- [ ] **High-impact journals** (Strong automatic approval):
  - Nature, Nature Reviews, Science, Cell
  - Lancet, Lancet Neurology, JAMA, JAMA Neurology, Neurology, Brain
  - New England Journal of Medicine

- [ ] **Specialized/field journals** (Moderate, pass relevance check):
  - Multiple Sclerosis Journal, MS Reports, Neuroimmunology & Neuroinflammation
  - Annals of Neurology, Neurology Today
  - Immunology, Journal of Neuroimmunology

- [ ] **Lower-impact/niche journals** (Requires strong justification):
  - Frontiers, PloS, Archives, minor society journals
  - **Action**: Require manual justification for inclusion

- [ ] **NOT acceptable without override**:
  - Predatory journals (check BEALL's list, Journal Citation Reports)
  - Non-peer-reviewed preprints (unless landmark early release)
  - Theses/dissertations (archival only, not expansion seeds)

### **E. Recency Policy** ✓

**For Expansion Seeds**:
- [ ] Publication year ≥ 2018 (last 6-8 years)
  - Rationale: Ensures modern knowledge, current evidence, active research trends

**For Landmark Anchors**:
- [ ] Publication year: 1995-2022 (2+ years old for stability, pre-modern era for foundations)
- [ ] Override: May include 1985+ if citation impact is exceptional (>1000 citations, landmark venue)

**Action**: If paper is outside year window, flag as "historical interest" and require manual override

---

## III. Quota Checks (Per Reseed Cycle)

### **Category Quotas** ✓

**Target distribution** (for 50-60 core expansion seeds):

| Category | Min | Max | Rationale |
|----------|-----|-----|-----------|
| clinical_care_and_management | 8 | 12 | Core learning objective: diagnosis & management |
| clinical_trials_and_therapeutics | 8 | 12 | DMT evidence & clinical trials |
| epidemiology_and_population_health | 8 | 12 | Population outcomes, health equity |
| imaging_and_biomarkers | 8 | 12 | Diagnostic & prognostic tools |
| pathogenesis_and_immunology | 8 | 12 | Mechanistic understanding |

**Pre-intake check**:
- [ ] Count current seeds by category
- [ ] Identify under-represented category
- [ ] Bias check: Is any single category >40% of total?

**Landmark anchors** (separate quota, ~25-30 papers):
- [ ] Decade distribution: 1990s (2), 2000s (4), 2010s (4), 2020s (3)
- [ ] No single decade >25% of landmark set

### **Venue Cap** ✓

**Maximum seeds from single journal**: **≤3**

- [ ] Count papers by venue in proposed new seed set
- [ ] Identify over-represented journals
- [ ] If Lancet Neurology has 4+ papers, either:
  - Remove excess papers, or
  - Document why concentration is justified (e.g., "MAGNIMS consensus papers are foundational")

**Rationale**: Prevents single-journal dominance; ensures diverse perspectives

### **Author Cap** ✓

**Maximum seeds with same first author**: **≤1**

- [ ] Count papers by first author in proposed new seed set
- [ ] If same author appears 2+ times:
  - Keep only highest-quality/most-relevant paper by that author, or
  - Document why multiple papers by same author are necessary (different subfields)

**Rationale**: Prevents single-lab lock-in; encourages intellectual diversity

---

## IV. Landmark Anchor Special Criteria

**In addition to A-E above**:

### **Age-Normalized Impact** ✓

- [ ] **Citations per year ≥ 2** (controlled for publication year)
  - Formula: `total_citations / (2026 - publication_year + 1) ≥ 2`
  - Example: 2010 paper with 30 citations → 30/(2026-2010+1) = 1.76 (borderline, but OK if high PageRank)

- [ ] **PageRank percentile ≥ 50th** (within MS citation network)
  - Computed by `src/compute_scores.py`

### **Canonical Status** ✓

**One or more**:
- [ ] Cited by all or most major reviews in field (check review papers for inclusion)
- [ ] Established diagnostic/therapeutic standard (e.g., McDonald criteria papers, pivotal drug trials)
- [ ] Foundational mechanistic work (widely recognized as "must-know")
- [ ] Hand-curated by experts (neurologists, immunologists) as essential reading

### **Decade Representation** ✓

- [ ] No decade over-represented (max 4 papers per decade in landmark set)
- [ ] Each major era covered:
  - 1990s: Diagnostic criteria evolution (Poser → Barkhof → McDonald)
  - 2000s: MRI revolution, immunology foundations, first DMTs
  - 2010s: Biomarker emergence, B cell targeting, genetics
  - 2020s: Recent trials, EBV evidence, progression definitions

---

## V. Bias Detection & Mitigation

### **Recency Bias** ✗

**Problem**: Over-weighting recent papers, missing foundational knowledge

**Checks**:
- [ ] % papers from 2021+ in expansion seeds: Should be 60-70% (not 100%)
- [ ] % papers from 1990-2015 in expansion seeds: Should be 15-25%
- [ ] Landmark anchor set MUST include pre-2020 papers (2+ per decade, min 1990)

**Remediation**: If recency bias detected, manually add landmark anchors and rebalance

### **Venue Bias** ✗

**Problem**: Over-representation of high-impact journals; under-representation of specialist venues

**Checks**:
- [ ] % papers from Nature/Lancet/JAMA/NEJM: Should be <30%
- [ ] % papers from specialist MS/neuro venues: Should be ≥25%
- [ ] Are there well-known papers in "mid-tier" venues missing?

**Remediation**: Actively search specialist venues; check "cited by" relationships for venue diversity

### **Author/Lab Bias** ✗

**Problem**: Over-representation of leading labs; under-representation of underrepresented researchers

**Checks**:
- [ ] No single author >1 seed paper (unless Landmark anchor + justification)
- [ ] Geographic diversity: Are seeds from >5 countries?
- [ ] Gender diversity: Can you identify gender of first authors? Is distribution skewed?
- [ ] Early-career researcher representation: Are any seeds from researchers <10 years post-PhD?

**Remediation**: When selecting between papers of similar quality, prefer underrepresented authors/institutions

### **Methodological Bias** ✗

**Problem**: Over-weighting RCTs; under-weighting observational studies, mechanistic work

**Checks**:
- [ ] Trial papers: 20-25%
- [ ] Review/consensus: 10-15%
- [ ] Mechanistic (bench): 20-25%
- [ ] Observational/epidemiology: 15-20%
- [ ] Method diversity balanced across categories

**Remediation**: Explicitly target methodological diversity when adding new seeds

### **Topic Bias** ✗

**Problem**: Clustering around one mechanism (e.g., B cells) at expense of other pathways

**Checks**:
- [ ] Does seed set mention all major mechanisms: T cells, B cells, BBB, remyelination, genetics, environment?
- [ ] Are there any mechanisms mentioned in <3 papers in expansion seeds?
- [ ] Is any mechanism >30% of seeds?

**Remediation**: Explicitly search for under-represented mechanisms; add landmark anchors to balance

---

## VI. Intake Workflow (Step-by-Step)

### **Phase 1: Candidate Assembly** (2 weeks)

1. **Identify source**:
   - Expert nominations (domain experts, MS society)
   - Citation analysis (most-cited papers in major reviews)
   - Landmark generator script (`seeds/landmark_seed_curator.py`)
   - Randomized sampling (avoid just picking "obvious" papers)

2. **Create candidate pool**: 80-100 candidate papers

3. **Pre-screen** (automated):
   - Run OpenAlex resolution
   - Check for duplicates (same DOI, different articles)
   - Filter for year range, venue credibility
   - Result: 40-60 candidates → Phase 2

### **Phase 2: Deep Curation** (2-3 weeks)

**For each candidate**:

1. **Read abstract** (5 min)
   - [ ] Assess MS relevance (lexical, concept, bridge)
   - [ ] Identify primary category
   - [ ] Confirm publication quality (venue, peer review)

2. **Assign category and role**:
   - [ ] `expand` (add to expansion seeds if ≤ quota for category) or
   - [ ] `landmark_anchor` (strong candidate for foundational set) or
   - [ ] `score_only` (useful for scoring but not expansion) or
   - [ ] `reject` (doesn't meet criteria)

3. **Document rationale** (1-2 sentences):
   - **Example**: "Modern seed (2022) from Annals of Neurology; demonstrates progressive MS pathology; directly cited in recent consensus"
   - **Example landmark**: "Foundational GWAS paper (2007); established HLA-DRB1*15:01 association; still cited in 90% of MS genetics papers"

### **Phase 3: Validation & Balancing** (1-2 weeks)

1. **Run quota checks**:
   - [ ] Execute: `python -m src.seed_governance --config config.yaml`
   - [ ] Review category counts, venue distribution, author distribution
   - [ ] Flag imbalances

2. **Bias detection**:
   - [ ] Visual inspection of approved list for:
     - Geographic diversity (>5 countries?)
     - Venue diversity (specialist venues included?)
     - Methodological diversity (RCTs + observations + mechanistic?)
   - [ ] Run automated bias check script (Python)

3. **Rebalance**:
   - [ ] If any quota violated, manually select replacements from candidate pool
   - [ ] If bias detected, add seeds to correct (e.g., add international authors, underrepresented mechanisms)

4. **Finalize and document**:
   - [ ] Save approved seeds to `seeds/core_seeds.csv`
   - [ ] Save landmark anchors to `seeds/landmark_seeds.csv`
   - [ ] Save curation report with:
     - Candidate pool size
     - Final seed count by category
     - Venue/author/decade distribution
     - Bias checks passed/failed
     - Outliers/overrides documented

### **Phase 4: CI/CD Validation** (Pipeline run)

1. **Run seed governance checklist**:
   ```bash
   python -m src.seed_governance --config config.yaml
   ```
   - [ ] All errors resolved (exit code 0)
   - [ ] Review seed_checklist_report.json
   - [ ] Check warnings (document if acceptable)

2. **Run full pipeline**:
   ```bash
   python run_pipeline.py --config config.yaml
   ```
   - [ ] Monitor Stage 1 (retrieval stats)
   - [ ] Check final corpus stats:
     - % has_ms_focus
     - core vs. context ratio
     - Missing categories or anomalies

3. **Audit results**:
   - [ ] Run: `python -m src.audit_kb --config config.yaml`
   - [ ] All audit gates pass (or acceptable fail reasons documented)

---

## VII. Appendix: Checklist Template (CSV Format)

```csv
doi,title,category,role,venue,year,first_author,has_ms_focus,bridge_justification,
citation_count,pagerank_percentile,curation_notes,approved_by,curation_date,category_quota_check,
venue_cap_check,author_cap_check,bias_check_passed

10.1016/s1474-4422(21)00095-8,"2021 MAGNIMS–CMSC–NAIMS consensus...",imaging_and_biomarkers,expand,
Lancet Neurology,2021,Wattjes MP,1,"",8000,85,"Modern seed from high-impact consensus",
Dr. X,2026-04-08,✓,✓,✓,✓

10.1038/nrneurol.2012.168,"Compston & Coles MS Review",pathogenesis_and_immunology,landmark_anchor,
Nature Reviews Neurology,2012,Compston A,1,"Foundational immunology + clinical integration; cited in 95% of major reviews",
12000,92,"Landmark anchor - disease understanding exemplar",Dr. Y,2026-04-08,✓,✓,✓,✓
```

---

## VIII. Sign-Off

**Seed set intake requires approval from**:

- [ ] **Domain Expert** (Neurologist or MS researcher): MS relevance, clinical utility
- [ ] **Methodologist** (Bibliometrician): Balance, bias, quota compliance
- [ ] **Data Curator**: Metadata completeness, OpenAlex resolution

**Final Approval**: All three must sign off before merge to main seed files

---

## Questions? Need Help?

- Check `TECH_NOTE_SEED_SELECTION_AND_BALANCE.md` for historical context
- Run `seeds/landmark_seed_curator.py --help` for landmark automation
- See `src/seed_governance.py` for technical implementation details
