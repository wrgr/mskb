# Quick Reference Card

---

## Files You Created (6 Total)

| File | Purpose | When to Read | Action |
|------|---------|--------------|--------|
| `IMPLEMENTATION_SUMMARY.md` | Overview of what was built | **START HERE** | Read first (10 min) |
| `VISUAL_ARCHITECTURE.md` | Diagrams and visual layouts | Need to understand structure | Reference often |
| `EDUCATOR_INTEGRATION_GUIDE.md` | How to implement (phased roadmap) | Ready to start implementation | Follow step-by-step |
| `SEED_INTAKE_GOVERNANCE.md` | Checklist for unbiased seeding | Doing seed curation | Use as checklist |
| `LEARNING_CONCEPT_ONTOLOGY.md` | The 25 MS concepts + prerequisites | Designing concept ontology | Review + refine |
| `RESOURCE_CURATOR_TEMPLATE.md` | How to curate videos, tools, datasets | Curating resources | Use rubric + workflow |
| `seeds/landmark_seed_curator.py` | Script to find foundational papers | Running automated selection | Run command below |

---

## Commands You Need to Know

### **Generate Landmark Candidates** (5 minutes)
```bash
python seeds/landmark_seed_curator.py \
  --scored-papers outputs/graph/scored_papers.csv \
  --output-dir outputs/audit
# Output: outputs/audit/landmark_seed_candidates.csv + JSON report
```

### **Validate Seed Governance** (2 minutes)
```bash
python -m src.seed_governance --config config.yaml
# Output: outputs/audit/seed_checklist_report.json
# Check: "passed": true? (means no errors)
```

### **View Landmark Report** (1 minute)
```bash
cat outputs/audit/landmark_curation_report.json
# Shows: count, decade distribution, venue distribution, top 5 papers
```

---

## Three Layers Explained in 60 Seconds

### **Layer 1: Seed Governance** (Fix bias)
- Use `landmark_seed_curator.py` to find papers from 1995-2022
- Enforce quotas: <3 from any journal, <1 from any author
- Result: Balanced seed set (modern + historical, diverse)

### **Layer 2: Concept Ontology** (Scaffold learning)
- 25 MS concepts (demyelination, B cells, diagnosis, etc.)
- Each has prerequisites, learning objectives, key questions
- Links to papers (research landscape) + resources (how to learn)

### **Layer 3: Resource Curator** (Enrich with videos/tools)
- Videos, tools, datasets, registries attached to each concept
- Quality rubric: accuracy, clarity, utility, accessibility
- Multiple modalities: foundation level + advanced + applied

---

## This Week (Phase 1: Seeding)

```
MONDAY: Review IMPLEMENTATION_SUMMARY.md (20 min)
        Review VISUAL_ARCHITECTURE.md (20 min)

TUESDAY: Run landmark curator:
         python seeds/landmark_seed_curator.py ...
         Review outputs/audit/landmark_seed_candidates.csv

WEDNESDAY: Get domain expert (neurologist/educator)
           Start manually curating top 25-30 papers
           Check: Is each paper foundational? Canonical?

THURSDAY: Add curated papers to seeds/landmark_seeds.csv
          Format: doi, title, year, venue, first_author, rationale, role=landmark_anchor

FRIDAY: Run validation:
        python -m src.seed_governance --config config.yaml
        Check: seed_checklist_report.json shows "passed": true
        Done! Seed governance complete ✓
```

---

## Learning Objectives (Why You're Doing This)

### **Problem 1: Seeding Bias**
**Before**: All seeds 2021+ (no foundational papers)  
**After**: Seeds span 1995-2022 with decade balancing  
**Tool**: `landmark_seed_curator.py` + `SEED_INTAKE_GOVERNANCE.md`

### **Problem 2: KG Confusion**
**Before**: Unclear if KG meant papers or learning scaffold  
**After**: Three distinct layers (citation graph + concepts + resources)  
**Tool**: `LEARNING_CONCEPT_ONTOLOGY.md` + `VISUAL_ARCHITECTURE.md`

### **Problem 3: Resource Integration**
**Before**: No systematic way to bind videos/tools/datasets  
**After**: Templated workflow with quality rubric per concept  
**Tool**: `RESOURCE_CURATOR_TEMPLATE.md`

---

## Success Checklist (Phase 1: Seeding)

- [ ] Ran landmark curator script
- [ ] Reviewed outputs/audit/landmark_seed_candidates.csv
- [ ] Manually curated top 25-30 papers with domain expert
- [ ] Created seeds/landmark_seeds.csv with role=landmark_anchor
- [ ] Ran governance checklist: `python -m src.seed_governance --config config.yaml`
- [ ] seed_checklist_report.json shows "passed": true
- [ ] Decade distribution is balanced (not 100% recent)
- [ ] <3 papers from any single journal

**All checks pass? → Phase 1 complete!** ✓

---

## FAQ (Most Common Questions)

**Q: Should I add ALL 25-30 landmarks right away?**  
A: No. Start with 15-20 (safest). Validate with governance checklist. Add rest in next reseed cycle.

**Q: My scores don't have PageRank. Can I still run the curator?**  
A: Yes! Script uses citations/year + in-degree. PageRank is bonus. Run with what you have.

**Q: How long does landmark curation take?**  
A: 10 hours (4-5 per paper: read abstract, check metrics, write rationale). Spread over 1 week.

**Q: Should framing seeds also be validated?**  
A: Not yet. Use `SEED_INTAKE_GOVERNANCE.md` only for expansion + landmark seeds.

**Q: When do I do concept ontology + resources?**  
A: After Phase 1 (seed governance) is done and validated. Week 3 starts Phase 2.

---

## Files to Reference While Working

### **For Seeding (Phase 1)**
- **Checklist**: `SEED_INTAKE_GOVERNANCE.md` (Pre-intake section, A-E)
- **Script**: `seeds/landmark_seed_curator.py`
- **Example output**: Review the script's generate_report() function

### **For Concepts (Phase 2)**
- **Template**: `LEARNING_CONCEPT_ONTOLOGY.md` (25 concepts provided)
- **Structure**: Each concept = ID + objectives + prerequisites + papers
- **Entry point**: Review "Core Concept Structure" section

### **For Resources (Phase 3)**
- **Workflow**: `RESOURCE_CURATOR_TEMPLATE.md` (5-step process)
- **Rubric**: Quality scoring (accuracy, clarity, completeness, etc.)
- **Format**: JSON schema with type, title, URL, Bloom's level, score

---

## Educational Theory Backing (Why This Works)

- **Bloom's taxonomy**: Hierarchical learning (Remember → Understand → Apply)
- **Cognitive load**: Prerequisites prevent overload (scaffolding)
- **Concept mapping**: Explicit relationships deepen understanding
- **Foundational literacy**: Landmarks show intellectual ancestry

All backed by peer-reviewed learning science literature (see references in LEARNING_CONCEPT_ONTOLOGY.md).

---

## Key Insights

1. **Citation graph ≠ Learning scaffold**: Both exist. Don't confuse them.
   - Graph: "What papers cite what?"
   - Scaffold: "How should I learn this systematically?"
   - Resources: "What videos/tools support this concept?"

2. **Bias is multi-level**: Fix at seed time, not later.
   - Seed governance catches bias before it spreads
   - Quota enforcement prevents single-journal/author dominance
   - Landmark anchors prevent recency bias

3. **Three entry points beat one**: Learners are different.
   - Citation-first: "I found a cool paper"
   - Learning-first: "I want to learn about B cells"
   - Hybrid: Jump between both

4. **Resources are NOT papers**: Keep separate architecturally.
   - Papers live in citation graph
   - Videos, tools, datasets attached to concepts
   - Cleaner, more maintainable

---

## Next Week (Phase 2: Concept Ontology)

After Phase 1 is complete:

1. Review `LEARNING_CONCEPT_ONTOLOGY.md` (25 concepts provided as template)
2. Refine with domain expert (neurologist/educator)
3. Create `concepts/ms_concept_ontology.json` (structured format)
4. Map existing papers to concepts
5. Identify gaps (missing concepts, orphaned papers)

**Deliverable**: Concept hierarchy ready for resource curation

---

## What NOT to Do

❌ Don't add all 25+ landmarks at once (spread over 2 reseed cycles)  
❌ Don't skip the governance checklist validation (catches errors)  
❌ Don't use LLMs to write concept descriptions (use humans + LLM polish)  
❌ Don't mix papers into the resource curator (keep separate)  
❌ Don't curate resources without a quality rubric (ensures consistency)  
❌ Don't assume bias is fixed (audit quarterly)

---

## Contact / Questions

See **EDUCATOR_INTEGRATION_GUIDE.md** section "Questions? Next Steps?"

---

**Version**: 1.0  
**Last updated**: 2026-04-08  
**Next review**: 2026-07-08 (quarterly)
