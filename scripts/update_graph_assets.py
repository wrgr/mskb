#!/usr/bin/env python3
"""One-shot script to patch pre-built graph JSON assets with:
  1. paper_count on every node (parsed from summary or paper_ids length)
  2. node_color on concept nodes (per-section palette)
  3. Concept nodes in research_map_graph.json (with concept-topic edges and concept_topics map)
  4. Concept + pathway nodes in learning_spine_graph.json

Concept selection is anchored to:
  - James Lind Alliance MS Priority Setting Partnership (JLA 2022)
  - AAN Multiple Sclerosis Quality Measurement Set (2020)
  - MSIF Global PROMS Initiative (28 patient-priority domains)
  - ECTRIMS educational curriculum
  - MSKB topic_map.json (TOPIC-00 through TOPIC-15 + TOPIC-1b)
  - Bloom's taxonomy / cognitive load theory for sequencing

Run from the repo root:
  python scripts/update_graph_assets.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

ASSETS = Path("site/public/assets")
RESEARCH_MAP = ASSETS / "research_map_graph.json"
LEARNING_SPINE = ASSETS / "learning_spine_graph.json"

# ---------------------------------------------------------------------------
# Section color palette — gives each concept section a distinct visual identity
# ---------------------------------------------------------------------------
SECTION_COLORS = {
    "foundations":   "#d97706",  # amber   — foundational knowledge
    "mechanisms":    "#0891b2",  # cyan    — biology & science
    "diagnosis":     "#2563eb",  # blue    — clinical science
    "therapeutics":  "#7c3aed",  # violet  — treatment
    "clinical":      "#dc2626",  # red     — patient care & management
    "populations":   "#16a34a",  # green   — population health & equity
}

# ---------------------------------------------------------------------------
# Concept metadata
# Each tuple: (id, title, description, path, section)
# Selection anchors documented in each concept file's frontmatter.
# ---------------------------------------------------------------------------
CONCEPTS = [
    # ── FOUNDATIONS ─────────────────────────────────────────────────────────
    ("what_is_ms",
     "What is Multiple Sclerosis?",
     "Definition and classification of MS as a CNS autoimmune demyelinating disease.",
     "foundations/what-is-ms", "foundations"),

    ("ms_epidemiology",
     "MS Epidemiology and Natural History",
     "Who gets MS, where, and why — incidence, prevalence, and the natural disease trajectory.",
     "foundations/ms-epidemiology", "foundations"),

    ("immune_system_basics",
     "Immune System Basics for MS",
     "T cells, B cells, antigen presentation, and the breakdown of self-tolerance in MS.",
     "foundations/immune-system-basics", "foundations"),

    # ── MECHANISMS ──────────────────────────────────────────────────────────
    ("demyelination_remyelination",
     "Demyelination and Remyelination",
     "How inflammatory demyelination destroys myelin, why remyelination fails, and how axonal damage accumulates.",
     "mechanisms/demyelination-remyelination", "mechanisms"),

    ("blood_brain_barrier",
     "Blood-Brain Barrier Dysfunction",
     "Tight-junction disruption, immune cell transmigration, and gadolinium enhancement as a BBB biomarker.",
     "mechanisms/blood-brain-barrier", "mechanisms"),

    ("genetic_susceptibility",
     "Genetic Susceptibility in MS",
     "HLA-DRB1*15:01, GWAS findings, and gene-environment interactions shaping MS risk.",
     "mechanisms/genetic-susceptibility", "mechanisms"),

    ("environmental_risk_factors",
     "Environmental Risk Factors",
     "EBV as a near-necessary cause of MS, vitamin D, smoking, and the molecular mimicry model.",
     "mechanisms/environmental-risk-factors", "mechanisms"),

    ("ebv_ms",
     "Epstein-Barr Virus and MS",
     "EBV as a near-necessary environmental cause — molecular mimicry, EBNA1/GlialCAM, and the prevention agenda.",
     "mechanisms/ebv-ms", "mechanisms"),

    ("neuroinflammation",
     "Neuroinflammation Pathways",
     "From peripheral T/B-cell activation to CNS lesion formation and compartmentalized chronic inflammation.",
     "mechanisms/neuroinflammation", "mechanisms"),

    # ── DIAGNOSIS ───────────────────────────────────────────────────────────
    ("mcdonald_criteria",
     "McDonald Criteria",
     "DIS, DIT, and the 2024 revision incorporating central vein sign and paramagnetic rim lesions.",
     "diagnosis/mcdonald-criteria", "diagnosis"),

    ("mri_patterns",
     "MRI Patterns in MS",
     "T2 lesions, gadolinium enhancement, black holes, central vein sign, and paramagnetic rim lesions.",
     "diagnosis/mri-patterns", "diagnosis"),

    ("csf_biomarkers",
     "CSF and Blood Biomarkers",
     "Oligoclonal bands, kappa free light chains, serum NfL, and GFAP in MS diagnosis and monitoring.",
     "diagnosis/csf-biomarkers", "diagnosis"),

    ("ms_phenotypes",
     "MS Phenotypes and Classification",
     "RRMS, PPMS, SPMS, CIS, and RIS — definitions, clinical course, and treatment implications.",
     "diagnosis/ms-phenotypes", "diagnosis"),

    ("paramagnetic_rim_lesions",
     "Paramagnetic Rim Lesions",
     "Chronic active lesions with an iron-laden microglial rim — imaging biomarkers of smoldering neuroinflammation.",
     "diagnosis/paramagnetic-rim-lesions", "diagnosis"),

    # ── THERAPEUTICS ────────────────────────────────────────────────────────
    ("dmt_overview",
     "Disease-Modifying Therapies — Overview",
     "All approved DMT classes, efficacy tiers, and the shift toward early high-efficacy treatment.",
     "therapeutics/dmt-overview", "therapeutics"),

    ("b_cell_therapies",
     "B Cell–Targeted Therapies",
     "Anti-CD20 agents (ocrelizumab, ofatumumab), mechanism, pivotal trials, and long-term safety.",
     "therapeutics/b-cell-therapies", "therapeutics"),

    ("btk_inhibitors",
     "BTK Inhibitors",
     "CNS-penetrant BTK inhibitors targeting B cells and microglia in smoldering and progressive MS.",
     "therapeutics/btk-inhibitors", "therapeutics"),

    ("treatment_monitoring",
     "Treatment Monitoring and Switches",
     "NEDA, serum NfL monitoring, treatment failure criteria, and extended interval dosing.",
     "therapeutics/treatment-monitoring", "therapeutics"),

    # ── CLINICAL ────────────────────────────────────────────────────────────
    ("disease_course",
     "Disease Course and Disability Progression",
     "Natural history, EDSS, disability trajectories, and transition from relapsing to progressive MS.",
     "clinical/disease-course", "clinical"),

    ("pira_smoldering_ms",
     "PIRA and Smoldering MS",
     "Progression independent of relapse activity, chronic active lesions, and compartmentalized neurodegeneration.",
     "clinical/pira-smoldering-ms", "clinical"),

    ("cognition_ms",
     "Cognition in MS",
     "Prevalence of cognitive dysfunction, affected domains, imaging correlates, and assessment tools.",
     "clinical/cognition-ms", "clinical"),

    ("pregnancy_ms",
     "Pregnancy and MS",
     "DMT safety in pregnancy, postpartum relapse risk, and family planning counselling.",
     "clinical/pregnancy-ms", "clinical"),

    # patient-priority additions (anchored to JLA, AAN QM, PROMS)
    ("fatigue_ms",
     "Fatigue in MS",
     "The most prevalent MS symptom — mechanisms, validated scales, QoL impact, and management.",
     "clinical/fatigue-ms", "clinical"),

    ("bladder_bowel_dysfunction",
     "Bladder and Bowel Dysfunction",
     "Neurogenic bladder and bowel — mechanisms, prevalence, AAN-mandated screening, and management.",
     "clinical/bladder-bowel-dysfunction", "clinical"),

    ("depression_anxiety_ms",
     "Depression and Anxiety in MS",
     "50% lifetime prevalence, bidirectional link with disease activity, and evidence-based management.",
     "clinical/depression-anxiety-ms", "clinical"),

    ("rehabilitation_exercise",
     "Exercise and Rehabilitation",
     "Exercise as medicine — RCT evidence across fatigue, cognition, and mood; multidisciplinary care.",
     "clinical/rehabilitation-exercise", "clinical"),

    ("shared_decision_making",
     "Shared Decision-Making and Patient Partnership",
     "SDM frameworks for DMT choice, patient priorities, and the role of MS specialist nurses.",
     "clinical/shared-decision-making", "clinical"),

    # ── POPULATIONS ─────────────────────────────────────────────────────────
    ("pediatric_ms",
     "Pediatric-Onset Multiple Sclerosis",
     "IPMSSG criteria, ADEM differential, neurodevelopmental consequences, and DMT considerations in children.",
     "populations/pediatric-ms", "populations"),

    ("equity_sdoh",
     "Equity and Social Determinants of Health",
     "Racial/ethnic disparities in MS outcomes, DMT access, structural racism, and socioeconomic barriers.",
     "populations/equity-sdoh", "populations"),

    ("sex_gender_ms",
     "Sex and Gender Differences in MS",
     "Why MS preferentially affects women, hormonal modulation of disease activity, and gender in MS care.",
     "populations/sex-gender-ms", "populations"),
]

# ---------------------------------------------------------------------------
# Concept → topic_ids mapping
# Based on thematic alignment with existing citation topic cluster content.
# Topics: 0=MS general (4181p), 1=Immunology (2318p), 2=Neuroscience (3452p),
#         3=MS Research Studies (3666p), 4=MS Research Studies (826p),
#         5=MS Research Studies (3393p), 6=Pathology (1471p),
#         7=MS Research Studies/Clinical Trials (815p), 8=MS Research Studies (905p),
#         113=Genetics/Neurodevelopmental (14p), 153=Osteoarthritis (8p),
#         161=Epidemiology/population (5p)
# ---------------------------------------------------------------------------
CONCEPT_TOPIC_MAP: dict[str, list[str]] = {
    "what_is_ms":                   ["0", "3", "5"],
    "ms_epidemiology":              ["0", "5", "161"],
    "immune_system_basics":         ["1", "113"],
    "demyelination_remyelination":  ["2", "6"],
    "blood_brain_barrier":          ["2", "6"],
    "genetic_susceptibility":       ["1", "113"],
    "environmental_risk_factors":   ["5", "8"],
    "mcdonald_criteria":            ["0", "3"],
    "mri_patterns":                 ["0", "3", "8"],
    "csf_biomarkers":               ["0", "2"],
    "ms_phenotypes":                ["0", "3", "4"],
    "dmt_overview":                 ["7"],
    "b_cell_therapies":             ["1", "7"],
    "btk_inhibitors":               ["7"],
    "treatment_monitoring":         ["7"],
    "disease_course":               ["3", "4", "5"],
    "pira_smoldering_ms":           ["3", "5", "8"],
    "cognition_ms":                 ["2", "3", "8"],
    "pregnancy_ms":                 ["3", "5"],
    "fatigue_ms":                   ["3", "5", "8"],
    "bladder_bowel_dysfunction":    ["0", "3", "8"],
    "depression_anxiety_ms":        ["3", "5", "8"],
    "rehabilitation_exercise":      ["3", "5", "8"],
    "shared_decision_making":       ["0", "3", "7"],
    "pediatric_ms":                 ["0", "3", "113"],
    "ebv_ms":                        ["5", "8"],
    "equity_sdoh":                  ["0", "5", "161"],
    "sex_gender_ms":                ["0", "5"],
}

# Section → canonical MSKB category
SECTION_TO_CATEGORY = {
    "foundations":   "clinical_care_and_management",   # overridden per concept
    "mechanisms":    "pathogenesis_and_immunology",
    "diagnosis":     "imaging_and_biomarkers",
    "therapeutics":  "clinical_trials_and_therapeutics",
    "clinical":      "clinical_care_and_management",
    "populations":   "epidemiology_and_population_health",
}

# Concept-level category overrides (where section default is wrong)
CONCEPT_CATEGORY_OVERRIDE = {
    "ms_epidemiology":    "epidemiology_and_population_health",
    "immune_system_basics": "pathogenesis_and_immunology",
}

# Pathway metadata: (id, label, href, ordered concept_ids)
PATHWAYS = [
    ("clinical", "Clinical pathway", "/mskb/pathways/clinical/",
     ["what_is_ms", "ms_phenotypes", "mcdonald_criteria", "mri_patterns",
      "csf_biomarkers", "disease_course", "pira_smoldering_ms",
      "dmt_overview", "treatment_monitoring", "shared_decision_making",
      "fatigue_ms", "bladder_bowel_dysfunction", "depression_anxiety_ms",
      "cognition_ms", "pregnancy_ms"]),
    ("mechanistic", "Mechanistic pathway", "/mskb/pathways/mechanistic/",
     ["immune_system_basics", "genetic_susceptibility", "environmental_risk_factors",
      "blood_brain_barrier", "demyelination_remyelination", "mri_patterns",
      "csf_biomarkers", "b_cell_therapies", "btk_inhibitors"]),
    ("emerging", "Emerging topics pathway", "/mskb/pathways/emerging/",
     ["pira_smoldering_ms", "mri_patterns", "csf_biomarkers",
      "btk_inhibitors", "b_cell_therapies", "cognition_ms", "disease_course",
      "equity_sdoh", "shared_decision_making"]),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_paper_count(node: dict) -> int:
    summary = node.get("summary", "")
    if " papers · " in summary:
        try:
            return int(summary.split(" papers · ")[0])
        except (ValueError, IndexError):
            pass
    return len(node.get("paper_ids", []))


def concept_meta(cid: str) -> dict | None:
    for row in CONCEPTS:
        if row[0] == cid:
            return {"id": row[0], "title": row[1], "description": row[2],
                    "path": row[3], "section": row[4]}
    return None


def concept_category(cid: str, section: str) -> str:
    if cid in CONCEPT_CATEGORY_OVERRIDE:
        return CONCEPT_CATEGORY_OVERRIDE[cid]
    return SECTION_TO_CATEGORY.get(section, "clinical_care_and_management")


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def layout_research_map_concepts(
    concept_ids: list[str],
    topic_nodes: list[dict],
) -> dict[str, tuple[float, float]]:
    if not concept_ids:
        return {}
    topic_ys = [n["y"] for n in topic_nodes if n.get("layer") == 1]
    y_min = min(topic_ys) if topic_ys else 0.0
    y_max = max(topic_ys) if topic_ys else 82.0 * len(concept_ids)
    topic_xs = [n["x"] for n in topic_nodes if n.get("layer") == 1]
    concept_x = (max(topic_xs) if topic_xs else 360.0) + 360.0

    n = len(concept_ids)
    return {
        cid: (round(concept_x, 4), round(y_min + (y_max - y_min) * i / max(n - 1, 1), 4))
        for i, cid in enumerate(concept_ids)
    }


def layout_learning_spine(
    pathway_ids: list[str],
    category_nodes: list[dict],
    concept_ids: list[str],
) -> dict[str, dict]:
    cat_xs = [n["x"] for n in category_nodes]
    cat_ys = [n["y"] for n in category_nodes]
    cat_x = min(cat_xs) if cat_xs else 380.0
    pathway_x = cat_x - 380.0
    concept_x = (max(cat_xs) if cat_xs else 380.0) + 380.0
    y_min = min(cat_ys) if cat_ys else 0.0
    y_max = max(cat_ys) if cat_ys else 86.0 * 4

    coords: dict[str, dict] = {}
    n_paths = len(pathway_ids)
    for i, pid in enumerate(pathway_ids):
        y = y_min + (y_max - y_min) * i / max(n_paths - 1, 1)
        coords[f"pathway:{pid}"] = {"x": round(pathway_x, 4), "y": round(y, 4), "layer": 0}

    n_concepts = len(concept_ids)
    for i, cid in enumerate(concept_ids):
        y = y_min + (y_max - y_min) * i / max(n_concepts - 1, 1)
        coords[f"concept:{cid}"] = {"x": round(concept_x, 4), "y": round(y, 4), "layer": 2}

    return coords


# ---------------------------------------------------------------------------
# research_map_graph.json
# ---------------------------------------------------------------------------

def update_research_map():
    data = json.loads(RESEARCH_MAP.read_text(encoding="utf-8"))

    existing_topic_ids: set[str] = set()
    for node in data["nodes"]:
        node["paper_count"] = parse_paper_count(node)
        if node.get("id", "").startswith("topic:"):
            existing_topic_ids.add(node["id"].split(":", 1)[1])

    # Build concept_topics and topic_to_concepts from manual map
    concept_topics: dict[str, list[str]] = {}
    topic_to_concepts: dict[str, dict[str, int]] = {}
    for cid, topic_ids in CONCEPT_TOPIC_MAP.items():
        valid_tids = [t for t in topic_ids if t in existing_topic_ids]
        if valid_tids:
            concept_topics[cid] = sorted(valid_tids, key=lambda v: int(v) if v.isdigit() else v)
        for tid in valid_tids:
            topic_to_concepts.setdefault(tid, {})[cid] = topic_to_concepts.get(tid, {}).get(cid, 0) + 1

    concept_ids_in_graph = sorted(
        concept_topics.keys(),
        key=lambda cid: (concept_meta(cid) or {}).get("title", cid)
    )

    topic_nodes = [n for n in data["nodes"] if n.get("id", "").startswith("topic:")]
    positions = layout_research_map_concepts(concept_ids_in_graph, topic_nodes)

    # Remove stale concept nodes
    data["nodes"] = [n for n in data["nodes"] if not n.get("id", "").startswith("concept:")]

    for cid in concept_ids_in_graph:
        meta = concept_meta(cid)
        if not meta:
            continue
        xy = positions.get(cid, (720.0, 0.0))
        section = meta["section"]
        data["nodes"].append({
            "id": f"concept:{cid}",
            "label": meta["title"],
            "group": "Concept",
            "node_color": SECTION_COLORS.get(section, "#6d28d9"),
            "summary": meta["description"],
            "href": f"/mskb/concepts/{meta['path']}/",
            "paper_ids": [],
            "paper_count": 0,
            "x": xy[0],
            "y": xy[1],
            "layer": 2,
        })

    # Rebuild edges (keep category→topic, add topic→concept)
    edges_set: set[tuple[str, str]] = {
        (e["source"], e["target"])
        for e in data.get("edges", [])
        if not e.get("source", "").startswith("concept:")
        and not e.get("target", "").startswith("concept:")
    }
    for tid, overlaps in topic_to_concepts.items():
        for cid in sorted(overlaps, key=lambda c: -overlaps[c])[:10]:
            edges_set.add((f"topic:{tid}", f"concept:{cid}"))

    data["edges"] = [{"source": s, "target": t} for s, t in sorted(edges_set)]
    data["concept_topics"] = concept_topics
    data["generated_at_utc"] = datetime.now(timezone.utc).isoformat()

    RESEARCH_MAP.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Updated {RESEARCH_MAP}: {len(data['nodes'])} nodes, {len(data['edges'])} edges, "
          f"{len(concept_topics)} concept_topic entries")


# ---------------------------------------------------------------------------
# learning_spine_graph.json
# ---------------------------------------------------------------------------

def update_learning_spine():
    data = json.loads(LEARNING_SPINE.read_text(encoding="utf-8"))

    for node in data["nodes"]:
        if "paper_count" not in node:
            node["paper_count"] = len(node.get("paper_ids", []))

    category_nodes = [n for n in data["nodes"] if n.get("id", "").startswith("category:")]
    existing_category_ids = {n["id"].split(":", 1)[1] for n in category_nodes}

    all_concept_ids = [c[0] for c in CONCEPTS]
    pathway_ids = [p[0] for p in PATHWAYS]
    new_coords = layout_learning_spine(pathway_ids, category_nodes, all_concept_ids)

    # Remove stale pathway/concept nodes
    data["nodes"] = [n for n in data["nodes"]
                     if not n.get("id", "").startswith("pathway:")
                     and not n.get("id", "").startswith("concept:")]

    # Add pathway nodes
    for pid, plabel, phref, psteps in PATHWAYS:
        c = new_coords.get(f"pathway:{pid}", {"x": 0.0, "y": 0.0, "layer": 0})
        data["nodes"].append({
            "id": f"pathway:{pid}",
            "label": plabel,
            "group": "Pathway",
            "summary": f"{len(psteps)} concept steps.",
            "href": phref,
            "paper_ids": [],
            "paper_count": 0,
            "x": c["x"],
            "y": c["y"],
            "layer": c["layer"],
        })

    # Add concept nodes with section colors
    for cid, ctitle, cdesc, cpath, csection in CONCEPTS:
        c = new_coords.get(f"concept:{cid}", {"x": 760.0, "y": 0.0, "layer": 2})
        data["nodes"].append({
            "id": f"concept:{cid}",
            "label": ctitle,
            "group": "Concept",
            "node_color": SECTION_COLORS.get(csection, "#6d28d9"),
            "summary": cdesc,
            "href": f"/mskb/concepts/{cpath}/",
            "paper_ids": [],
            "paper_count": 0,
            "x": c["x"],
            "y": c["y"],
            "layer": c["layer"],
        })

    # Rebuild edges
    edges_set: set[tuple[str, str]] = set()

    for pid, _label, _href, psteps in PATHWAYS:
        seen_cats: set[str] = set()
        for cid in psteps:
            meta = concept_meta(cid)
            if not meta:
                continue
            cat = concept_category(cid, meta["section"])
            if cat in existing_category_ids:
                seen_cats.add(cat)
        for cat in seen_cats:
            edges_set.add((f"pathway:{pid}", f"category:{cat}"))

    for cid, _title, _desc, _path, section in CONCEPTS:
        cat = concept_category(cid, section)
        if cat in existing_category_ids:
            edges_set.add((f"category:{cat}", f"concept:{cid}"))

    data["edges"] = [{"source": s, "target": t} for s, t in sorted(edges_set)]
    data["generated_at_utc"] = datetime.now(timezone.utc).isoformat()

    LEARNING_SPINE.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Updated {LEARNING_SPINE}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")


if __name__ == "__main__":
    update_research_map()
    update_learning_spine()
    print("Done.")
