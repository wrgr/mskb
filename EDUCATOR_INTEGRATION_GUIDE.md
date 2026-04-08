# Educator Integration Guide: From Seeding to Scaffolding

**Version**: 1.0  
**Date**: 2026-04-08  
**Audience**: Knowledge base builders, educators, curators  
**Goal**: Build an MS knowledge graph that teaches AND explores

---

## I. The Three-Layer Vision

Your MSKB system now has **three interconnected layers**:

### **Layer 1: Seed Governance (Foundation)**
**Files**: `SEED_INTAKE_GOVERNANCE.md`, `seeds/landmark_seed_curator.py`  
**Purpose**: Systematic, unbiased paper selection to prevent recency bias and ensure coverage

**Key idea**:
- Modern expansion seeds (2018+) keep knowledge current
- Landmark anchors (pre-2020) provide historical context and mechanistic depth
- Quota enforcement prevents single-journal/author/topic dominance

### **Layer 2: Learning Concept Ontology (Scaffolding)**
**File**: `LEARNING_CONCEPT_ONTOLOGY.md`  
**Purpose**: Organize MS research into learner-centered concepts with prerequisites

**Key idea**:
- 20+ concepts map the MS landscape (diagnosis → mechanism → treatment)
- Bloom's taxonomy guides learning levels (Remember → Understand → Apply → Analyze)
- Prerequisites show what students must learn first (cognitive load theory)
- Three sample pathways (clinical, mechanistic, cutting-edge)

### **Layer 3: Resource Curator (Support)**
**File**: `RESOURCE_CURATOR_TEMPLATE.md`  
**Purpose**: Bind videos, tools, products, and datasets to concepts

**Key idea**:
- Each concept links to multi-modal resources (papers, videos, tools, datasets)
- Rubric ensures quality (accuracy, clarity, utility)
- Curators work methodically, not ad-hoc

---

## II. How These Three Layers Work Together

### **Scenario: Undergraduate Learning "B Cell-Targeted Therapies"**

```
┌─────────────────────────────────────────────────────────┐
│ Student clicks: "I want to learn about B cell therapies" │
└────────────────────┬────────────────────────────────────┘
                     ↓
    ┌────────────────────────────────────────┐
    │ LAYER 2: Learning Concept Ontology      │
    │ "B Cell-Targeted Therapies"            │
    │ ├─ Bloom's level: Understand, Apply    │
    │ ├─ Prerequisites:                       │
    │ │  • T Cell and B Cell Biology (link)   │
    │ │  • Neuroinflammation (link)           │
    │ └─ Related: BTK inhibitors, monitoring  │
    └────────────────────┬───────────────────┘
                         ↓
        ┌────────────────────────────────┐
        │ LAYER 3: Curated Resources      │
        │ (Foundation)                    │
        ├─ Video: "B Cell Biology..." (MIT)   (8 min, Understand)
        ├─ Video: "Anti-CD20 Mechanisms"      (15 min, Apply)
        │ (Advanced)                          │
        ├─ Paper: "B cells in MS..." (2021)   (Review, deep dive)
        ├─ Paper: "ASCLEPIOS Trial" (2022)    (Trial, efficacy)
        ├─ Paper: "EBV-B cell mimicry"        (Mechanistic, advanced)
        │ (Tools & Products)                  │
        ├─ DMT comparison calculator          (Apply, decision aid)
        ├─ Infection risk tracker             (Apply, safety)
        │ (Datasets & Research)               │
        └─ Real-world outcomes (MSBase)       (Analyze, context)
                     ↓
         ┌──────────────────────────────┐
         │ LAYER 1: Seeded Papers        │
         │ Underpins all resources       │
         │ ├─ Modern papers (efficacy)   │
         │ ├─ Landmark papers (mechanism)│
         │ ├─ Diverse authors/venues     │
         │ └─ No single-lab dominance    │
         └──────────────────────────────┘
```

---

## III. Implementation Roadmap (Phased)

### **Phase 1: Formalize Seeding (Weeks 1-2)** ✓ **COMPLETE**

**What you did**:
1. Created `SEED_INTAKE_GOVERNANCE.md` (checklist for unbiased seed selection)
2. Created `seeds/landmark_seed_curator.py` (automated landmark detection)
3. Documented bias detection (recency, venue, author, topic, method)

**Action items**:
```bash
# Run landmark curator on current corpus
python seeds/landmark_seed_curator.py \
  --scored-papers outputs/graph/scored_papers.csv \
  --output-dir outputs/audit

# Review landmark_seed_candidates.csv
# Manually curate top 25-30 for landmark set
# Add to seeds/landmark_seeds.csv with role='landmark_anchor'

# Validate with governance checklist
python -m src.seed_governance --config config.yaml
```

**Output**: 
- `seeds/landmark_seeds.csv` (~30 papers from 1995-2022)
- `outputs/audit/seed_checklist_report.json` (validation report)

---

### **Phase 2: Design Concept Ontology (Weeks 3-4)** ✓ **COMPLETE**

**What you did**:
1. Created `LEARNING_CONCEPT_ONTOLOGY.md` with:
   - 20+ core concepts (organized hierarchically)
   - Educational rationale (Bloom's, cognitive load theory)
   - Learning objectives, prerequisites, key questions
   - Sample pathways (clinical, mechanistic, cutting-edge)

**Action items**:
1. **Populate concept taxonomy**:
   - Copy the 20-concept hierarchy from LEARNING_CONCEPT_ONTOLOGY.md
   - For each concept, create a JSON/YAML node:
   ```json
   {
     "id": "b_cell_targeted_therapy",
     "title": "B Cell-Targeted Therapies",
     "bloom_level": ["Understand", "Apply"],
     "prerequisites": ["t_cell_b_cell_biology", "neuroinflammation"],
     "learning_objectives": [
       "Explain B cell role in MS pathogenesis",
       "Describe anti-CD20 mechanism of action",
       "Compare efficacy/safety across agents"
     ],
     "key_questions": [
       "Why target B cells instead of T cells?",
       "What infection risks exist with depletion?"
     ],
     "related_concepts": ["btk_inhibitors", "treatment_monitoring"]
   }
   ```

2. **Map to existing papers**:
   - For each concept, identify 3-7 foundational papers already in corpus
   - Check `outputs/graph/scored_papers.csv` for:
     - Papers with concept matches (OpenAlex concepts)
     - Papers with keyword matches (title/abstract)

3. **Build concept graph**:
   - Create edges for prerequisites (→) and related (↔)
   - Visualize with graphviz or similar
   - Detect missing concepts (gaps in prerequisites)

**Output**: 
- `concepts/ms_concept_ontology.json` (formal schema)
- `concepts/concept_prerequisite_graph.graphml` (visual graph)
- `concepts/concept_to_papers.csv` (mapping)

---

### **Phase 3: Curate Resources (Weeks 5-8)** ✓ **COMPLETE (Template)**

**What you did**:
1. Created `RESOURCE_CURATOR_TEMPLATE.md` with:
   - Resource types (videos, tools, products, datasets)
   - Selection criteria and rubrics
   - Curation workflow (5 steps)
   - Integration schema
   - Maintenance schedule

**Action items**:

1. **For each concept, search for resources**:
   ```bash
   # Example: B Cell Biology
   # Search: YouTube, NEJM Knowledge+, institutional channels
   # Search: GitHub, NIH/CDC for tools
   # Search: DrugBank, MSBase for registries
   # Search: Zenodo, figshare for datasets
   ```

2. **Evaluate 5-10 candidates per concept** using rubric:
   ```
   Accuracy: ___/5
   Clarity: ___/5
   Completeness: ___/5
   Engagement: ___/5
   Currency: ___/5
   Accessibility: ___/5
   ─────────────
   TOTAL: ___/30 (threshold: 20+)
   ```

3. **Document in spreadsheet**:
   ```csv
   concept_id,resource_id,type,title,url,creator,year,
   bloom_level,score,curated_by,curation_date,notes
   ```

4. **Create resource JSON**:
   ```json
   {
     "concept_id": "b_cell_targeted_therapy",
     "resources": [
       {
         "id": "vid_chakraborty_2023",
         "type": "video",
         "title": "B Cell Biology...",
         "url": "https://...",
         "creator": "Arup Chakraborty",
         "year": 2023,
         "bloom_level": "Understand",
         "score": 38/50,
         "rationale": "Clear animations of germinal centers + CD20 mechanisms"
       }
     ]
   }
   ```

**Scope**: Start with 3-4 high-priority concepts (e.g., "B Cell Therapies", "Demyelination", "Diagnosis"); expand monthly

**Output**:
- `resources/concept_resources.json` (all curated resources)
- `resources/curation_log.csv` (audit trail)
- Dashboard (future): visualize coverage gaps

---

### **Phase 4: Integration & Launch (Weeks 9-12)**

**What to build**:

1. **Concept-Paper Binding**:
   - For each concept, annotate current papers:
   ```json
   {
     "concept_id": "b_cell_targeted_therapy",
     "papers": [
       {"doi": "10.1038/s41582-021-00498-5", "paper_role": "foundational_mechanism"},
       {"doi": "10.1177/13524585221078825", "paper_role": "trial_efficacy"},
       {"doi": "10.1093/brain/awb231", "paper_role": "mechanistic_detail"}
     ]
   }
   ```

2. **Concept-Resource Binding**:
   - Link resources to concepts (already done in Phase 3)

3. **Concept Explorer Web Interface** (Optional, Phase 2):
   - Sidebar: Concept hierarchy (collapsible tree)
   - Center: Concept details (objectives, prerequisites, key questions)
   - Right panel: Resources (papers, videos, tools, datasets)
   - Interactive prerequisite checker: "Ready to learn this concept?"

4. **Learning Pathway Builder** (Future):
   - Suggest sequence: "Start here → learn prerequisites → explore related"
   - Learner progress tracking (future)
   - Personalized recommendations (future)

---

## IV. How to Handle the Three Problems

### **Problem 1: Seeding Bias (Missing Foundational Papers)**

**Root cause**: 2021+ recency bias in current core seeds

**Solution** (implemented):
1. Run landmark curator script → identifies papers 1995-2022 with high age-normalized centrality
2. Manually curate top 25-30 for landmark set
3. Add to `seeds/landmark_seeds.csv` with explicit rationale
4. Enforce quota (4 papers per decade, covering 1995+)
5. Run seed governance checklist to validate

**Validation**:
```bash
# Check for balance
python -c "
import pandas as pd
core = pd.read_csv('seeds/core_seeds.csv')
landmarks = pd.read_csv('seeds/landmark_seeds.csv')
print('Core by year:', core['year'].min(), '-', core['year'].max())
print('Landmarks by year:', landmarks['year'].min(), '-', landmarks['year'].max())
print('Core by category:', core['category'].value_counts().to_dict())
print('Landmarks by decade:', (landmarks['year']//10*10).value_counts().to_dict())
"
```

---

### **Problem 2: Two Incompatible Systems (KG vs. Learning)?**

**Root cause**: Confusion between "citation graph" and "learning scaffold"

**Solution** (implemented):

They're **NOT incompatible**—they're **complementary layers**:

```
Citation Graph (Papers, topics, citations)
        ↓ annotate with concepts ↓
Learning Ontology (Concepts, prerequisites, learning objectives)
        ↓ bind resources to concepts ↓
Resource Curator (Videos, tools, datasets per concept)
```

**Both systems coexist**:
- **Citation graph** answers: "What papers cite this? What's the research landscape?"
- **Learning scaffold** answers: "What should I learn next? How do concepts relate?"
- **Resources** answer: "How do I learn this concept (papers, videos, tools)?"

**In practice**:
- Student pathway 1: "I found a cool paper → follow citations → explore related topics" (Citation-first)
- Student pathway 2: "I want to learn about B cells → here's the concept → here are the best resources" (Learning-first)
- Student pathway 3: Hybrid (jump between both)

---

### **Problem 3: How to Avoid Bias in Everything?**

**Multi-level defense**:

1. **Seed level** (SEED_INTAKE_GOVERNANCE.md):
   - Category quotas prevent clinical-only bias
   - Venue caps prevent single-journal dominance
   - Author caps prevent single-lab lock-in
   - Landmark anchor prevents recency bias

2. **Concept level** (LEARNING_CONCEPT_ONTOLOGY.md):
   - 20+ concepts cover all MS domains (genetics → trial → population health)
   - Prerequisites ensure prerequisites aren't biased (can start from multiple entry points)
   - Pathways show multiple ways to learn (clinical, mechanistic, cutting-edge)

3. **Resource level** (RESOURCE_CURATOR_TEMPLATE.md):
   - Methodological diversity (mechanisms + trials + observational)
   - Author diversity (no single-author dominance)
   - Geographic diversity (papers from >5 countries)
   - Modality diversity (papers + videos + tools + datasets)

**Audit trail**:
```bash
# After seed intake
python -m src.seed_governance --config config.yaml
→ seed_checklist_report.json (quota checks, bias detection)

# After concept mapping
python scripts/concept_coverage_audit.py
→ Reports: Missing concepts? Overrepresented topics? Prerequisite issues?

# After resource curation
python scripts/resource_diversity_audit.py
→ Reports: Author diversity? Geographic spread? Modality balance?
```

---

## V. Quick Start Checklist

### **This Week (Week 1-2): Seed Governance**

- [ ] Run landmark curator: `python seeds/landmark_seed_curator.py --scored-papers ... --output-dir ...`
- [ ] Review `outputs/audit/landmark_seed_candidates.csv`
- [ ] Manually curate top 25-30 papers (work with a domain expert)
- [ ] Add landmark set to `seeds/landmark_seeds.csv` with rationale
- [ ] Run governance validation: `python -m src.seed_governance --config config.yaml`
- [ ] Document decisions in `SEED_INTAKE_LOG.md`

### **Next 2-4 Weeks: Concept Ontology**

- [ ] Review and refine `LEARNING_CONCEPT_ONTOLOGY.md` (25 concepts provided as starting point)
- [ ] Create `concepts/ms_concept_ontology.json` (structured JSON)
- [ ] Build concept prerequisite graph (graphviz or similar)
- [ ] Map existing papers to concepts (check OpenAlex concepts + keyword match)
- [ ] Identify gaps (missing concepts, orphaned papers)

### **Following 4-8 Weeks: Resource Curation**

- [ ] Start with 3-4 high-priority concepts (e.g., B cell therapies, demyelination, diagnosis)
- [ ] For each concept, search for 5-10 candidate resources (videos, tools, datasets)
- [ ] Evaluate with rubric (accuracy, clarity, utility, accessibility)
- [ ] Document in `resources/concept_resources.json`
- [ ] Create curation audit trail

### **Final 4 Weeks: Integration**

- [ ] Bind concepts to papers (annotate in `concepts/concept_to_papers.csv`)
- [ ] Bind concepts to resources (already done in curation phase)
- [ ] Create simple web views (or update existing explorer)
- [ ] Test learner pathways with sample students
- [ ] Document feedback and iterate

---

## VI. Tools You Now Have

| Tool | Purpose | When to use |
|------|---------|-------------|
| `seeds/landmark_seed_curator.py` | Automated landmark detection | Phase 1: Find candidate foundational papers |
| `SEED_INTAKE_GOVERNANCE.md` | Bias prevention checklist | Phase 1: Validate new seeds |
| `LEARNING_CONCEPT_ONTOLOGY.md` | Concept hierarchy + learning objectives | Phase 2: Design scaffold |
| `RESOURCE_CURATOR_TEMPLATE.md` | Resource quality rubric + workflow | Phase 3: Curate videos/tools/datasets |
| `EDUCATOR_INTEGRATION_GUIDE.md` | This file: tying it all together | All phases: Understand the vision |

---

## VII. Success Metrics

**How to know you've succeeded**:

### **Seed Quality**:
- ✓ Landmark papers span 1995-2022 (not 2021+)
- ✓ <30% from any single journal
- ✓ >5 countries represented
- ✓ <2% of core seeds from same author
- ✓ Seed governance checklist passes

### **Concept Coverage**:
- ✓ 20-25 core concepts defined
- ✓ All major MS domains covered (genetics, immune, imaging, diagnosis, treatment, epidemiology)
- ✓ Prerequisite relationships documented
- ✓ Each concept has 3-5 foundational papers identified

### **Resource Diversity**:
- ✓ ≥1 video per concept (or clear reason why none exist)
- ✓ ≥1 tool/dataset per concept (or clear reason why none exist)
- ✓ Multiple authors represented (no single-person dominance)
- ✓ Mix of resource types (foundation + advanced + applied)

### **Learner Experience**:
- ✓ Student can start from multiple entry points (clinical, mechanistic, cutting-edge pathways)
- ✓ Student has clear prerequisite chain
- ✓ Student can find papers, videos, tools for each concept
- ✓ Student can follow "next learning steps" recommendations

---

## VIII. FAQ

**Q: Should landmark seeds participate in retrieval (Stage 1)?**
A: No, not yet. Use them as `role=score_only` or `role=landmark_anchor` to shape scoring/topic discovery without biasing retrieval. In future, could enable selective retrieval from landmark set.

**Q: How often should I reseed?**
A: Quarterly (as new papers accumulate) or annually (full audit). Each reseed should re-validate landmark set, quotas, and bias metrics.

**Q: Can I use ChatGPT to create concept descriptions?**
A: No. Use expert humans (neurologists, educators). LLM descriptions risk hallucination on technical details. Use LLMs only for editing/polishing expert-written text.

**Q: What if I have 100 papers to seed at once?**
A: Use the `landmark_seed_curator.py` to pre-filter (automated scoring). Then manually curate top 50-80 using the governance checklist. Don't shortcut the human review.

**Q: Should resources be in the KG or separate?**
A: Separate. Resources (videos, tools, products) are **attached to concepts**, not in the citation graph. The graph is papers only; resources are concept-level metadata.

---

## IX. Questions? Next Steps?

1. **Try landmark curator**:
   ```bash
   python seeds/landmark_seed_curator.py --scored-papers outputs/graph/scored_papers.csv --output-dir outputs/audit
   ```

2. **Review candidate landmark papers** from `outputs/audit/landmark_seed_candidates.csv`

3. **Refine concept ontology** with a domain expert (neurology faculty, postdoc)

4. **Start resource curation** with one concept as a pilot

5. **Get feedback** from actual learners (undergrads, residents, patients)

---

**Document version**: 1.0  
**Last updated**: 2026-04-08  
**Next review**: 2026-07-08 (3 months)
