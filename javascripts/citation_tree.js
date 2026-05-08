// citation_tree.js — Step dendrogram of MS research citation lineage.
// Loads lineage_data.json, prunes a spanning tree (each paper keeps only its
// single most-important parent), then renders a horizontal cladogram:
// generation 0 (foundational) on the left, later generations stepping right,
// connected by right-angle elbow paths. Scroll vertically to explore.
(() => {
  "use strict";

  const DATA_URL = "../assets/lineage_data.json";

  const CAT_COLORS = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
    unknown: "#888888",
  };

  // Human-readable category labels for the tooltip domain chip.
  const CAT_LABELS = {
    pathogenesis_and_immunology: "Pathogenesis & Immunology",
    imaging_and_biomarkers: "Imaging & Biomarkers",
    clinical_trials_and_therapeutics: "Therapeutics",
    clinical_care_and_management: "Clinical Care",
    epidemiology_and_population_health: "Epidemiology",
    unknown: "Other",
  };

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const canvasEl = document.getElementById("ct-canvas");
  const tooltipEl = document.getElementById("ct-tooltip");
  const thresholdEl = document.getElementById("ct-threshold");
  const thresholdValEl = document.getElementById("ct-threshold-val");
  const countEl = document.getElementById("ct-count");

  let rawData = null;

  // ── helpers ───────────────────────────────────────────────────────────────

  function activeCats() {
    return new Set(
      [...document.querySelectorAll(".ct-cat-filter")]
        .filter(cb => cb.checked)
        .map(cb => cb.value)
    );
  }

  function esc(text) {
    return String(text || "").replace(/[&<>"']/g, ch =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
    );
  }

  function svgEl(tag, attrs = {}) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  }

  // ── spanning tree ─────────────────────────────────────────────────────────
  // links[i]: { source: citing_idx, target: cited_idx }
  // We want the dendrogram to flow LEFT (gen-0) → RIGHT (gen-N).
  // For each paper, its "parent" is the paper it cites with the highest
  // importance_score (i.e. among its outgoing citation edges in the corpus).

  function buildSpanningTree(nodes, links) {
    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    // parentOf[childId] = parentId (best parent = most-important cited paper)
    const parentOf = new Map();
    for (const l of links) {
      const child = l.source; // citing paper (newer, higher gen)
      const parent = l.target; // cited paper (older, lower gen)
      if (!nodeMap.has(child) || !nodeMap.has(parent)) continue;
      const prev = parentOf.get(child);
      if (prev === undefined ||
          nodeMap.get(prev).importance_score < nodeMap.get(parent).importance_score) {
        parentOf.set(child, parent);
      }
    }

    // childrenOf[parentId] = [childId, ...] sorted by year for stable layout
    const childrenOf = new Map();
    for (const [child, parent] of parentOf) {
      if (!childrenOf.has(parent)) childrenOf.set(parent, []);
      childrenOf.get(parent).push(child);
    }
    for (const kids of childrenOf.values()) {
      kids.sort((a, b) => (nodeMap.get(a)?.year || 0) - (nodeMap.get(b)?.year || 0));
    }

    // Roots = nodes with no parent (generation 0 or orphans not connected upward)
    const hasParent = new Set(parentOf.keys());
    const roots = nodes
      .filter(n => !hasParent.has(n.id))
      .sort((a, b) => a.year - b.year)
      .map(n => n.id);

    return { nodeMap, parentOf, childrenOf, roots };
  }

  // ── Reingold-Tilford-style layout ─────────────────────────────────────────
  // Post-order DFS: leaf nodes receive sequential integer y-slots;
  // internal nodes are centered vertically over their children's span.

  function layoutTree(nodes, childrenOf, roots, nodeMap) {
    const pos = new Map(); // nodeId -> { x: generation, y: slot }
    let nextSlot = 0;

    function visit(id) {
      const kids = childrenOf.get(id) || [];
      if (kids.length === 0) {
        pos.set(id, { x: nodeMap.get(id).generation, y: nextSlot++ });
      } else {
        kids.forEach(k => visit(k));
        const ys = kids.map(k => pos.get(k).y);
        pos.set(id, {
          x: nodeMap.get(id).generation,
          y: (Math.min(...ys) + Math.max(...ys)) / 2,
        });
      }
    }

    roots.forEach(r => visit(r));

    // Nodes unreachable from roots (detached orphans) get appended at the bottom.
    for (const n of nodes) {
      if (!pos.has(n.id)) pos.set(n.id, { x: n.generation, y: nextSlot++ });
    }

    return { pos, totalSlots: nextSlot };
  }

  // ── SVG render ────────────────────────────────────────────────────────────

  function render() {
    if (!canvasEl || !rawData) return;

    const cats = activeCats();
    const threshold = parseFloat(thresholdEl?.value ?? "5.2");

    const nodes = rawData.nodes.filter(
      n => cats.has(n.category) && n.importance_score >= threshold
    );
    const nodeIdSet = new Set(nodes.map(n => n.id));
    const links = rawData.links.filter(
      l => nodeIdSet.has(l.source) && nodeIdSet.has(l.target)
    );

    if (countEl) {
      countEl.textContent = `${nodes.length} papers · ${links.length} links`;
    }

    canvasEl.innerHTML = "";

    if (nodes.length === 0) {
      canvasEl.innerHTML = '<p class="chart-empty">No papers match the current filter — try lowering the importance threshold.</p>';
      return;
    }

    const { nodeMap, parentOf, childrenOf, roots } = buildSpanningTree(nodes, links);
    const { pos, totalSlots } = layoutTree(nodes, childrenOf, roots, nodeMap);

    const maxGen = Math.max(...nodes.map(n => n.generation), 0);
    const maxCite = Math.max(...nodes.map(n => n.cited_by_count), 1);

    // Layout constants
    const ROW = 18;    // px per y-slot
    const COL = 180;   // px per generation step
    const PAD = { top: 32, right: 24, bottom: 24, left: 16 };
    const W = PAD.left + (maxGen + 1) * COL + PAD.right;
    const H = PAD.top + totalSlots * ROW + PAD.bottom;

    const px = p => PAD.left + p.x * COL + COL / 2;
    const py = p => PAD.top + p.y * ROW;

    const svg = svgEl("svg", {
      viewBox: `0 0 ${W} ${H}`,
      width: W,
      height: H,
      role: "img",
      "aria-label": "Citation spanning-tree dendrogram",
    });

    // ── generation column headers ─────────────────────────────────────────
    const headerG = svgEl("g");
    for (let g = 0; g <= maxGen; g++) {
      const x = PAD.left + g * COL + COL / 2;
      const label = g === 0 ? "Gen 0 — foundational" : `Generation ${g}`;
      const t = svgEl("text", {
        x, y: 14, "text-anchor": "middle",
        "font-size": 9, fill: "#9ca3af",
      });
      t.textContent = label;
      headerG.appendChild(t);

      // Faint column stripe
      headerG.appendChild(svgEl("rect", {
        x: PAD.left + g * COL + 4, y: PAD.top - 10,
        width: COL - 8, height: H - PAD.top + 6,
        fill: g % 2 === 0 ? "rgba(243,244,246,0.5)" : "transparent",
        rx: 3,
      }));
    }
    svg.appendChild(headerG);

    // ── elbow edges ───────────────────────────────────────────────────────
    // Draw edges before nodes so circles appear on top.
    const edgeG = svgEl("g", { opacity: 0.55 });
    for (const [childId, parentId] of parentOf) {
      const pp = pos.get(parentId);
      const cp = pos.get(childId);
      if (!pp || !cp) continue;

      const x1 = px(pp), y1 = py(pp);
      const x2 = px(cp), y2 = py(cp);
      // Elbow: horizontal from parent to midpoint, vertical to child row, horizontal to child.
      const xMid = (x1 + x2) / 2;
      const path = svgEl("path", {
        d: `M${x1},${y1} H${xMid} V${y2} H${x2}`,
        fill: "none",
        stroke: "rgba(156,163,175,0.45)",
        "stroke-width": 0.9,
      });
      edgeG.appendChild(path);
    }
    svg.appendChild(edgeG);

    // ── nodes ─────────────────────────────────────────────────────────────
    const nodeG = svgEl("g");
    for (const n of nodes) {
      const p = pos.get(n.id);
      if (!p) continue;

      const cx = px(p);
      const cy = py(p);
      const r = Math.max(3.5, 3.5 + Math.sqrt(n.cited_by_count / maxCite) * 9);
      const color = CAT_COLORS[n.category] ?? "#aaaaaa";

      const circle = svgEl("circle", {
        cx, cy, r,
        fill: color,
        opacity: 0.85,
        stroke: "rgba(255,255,255,0.6)",
        "stroke-width": 1,
      });
      circle.style.cursor = "default";
      circle.addEventListener("mouseenter", evt => showTooltip(evt, n));
      circle.addEventListener("mousemove", evt => positionTooltip(evt.clientX, evt.clientY));
      circle.addEventListener("mouseleave", hideTooltip);
      nodeG.appendChild(circle);
    }
    svg.appendChild(nodeG);

    canvasEl.appendChild(svg);
  }

  // ── tooltip ───────────────────────────────────────────────────────────────
  // Position fixed so it works correctly in a scrollable container.

  function showTooltip(evt, n) {
    if (!tooltipEl) return;
    const gen = n.generation;
    const genLabel = gen === 0 ? "Generation 0 — foundational" : `Generation ${gen}`;
    const catColor = CAT_COLORS[n.category] ?? "#888888";
    const catLabel = CAT_LABELS[n.category] ?? "Other";
    const byline = [n.year, n.first_author ? esc(n.first_author) : null]
      .filter(Boolean)
      .join(" · ");
    tooltipEl.innerHTML =
      `<span class="ct-tt-cat" style="background:${catColor}">${esc(catLabel)}</span>` +
      `<strong>${esc(n.title)}</strong>` +
      `<div class="ct-tt-meta">${byline}</div>` +
      `<div class="ct-tt-meta">${n.cited_by_count.toLocaleString()} citations · importance ${n.importance_score.toFixed(2)}</div>` +
      `<em>${genLabel}</em>`;
    tooltipEl.hidden = false;
    positionTooltip(evt.clientX, evt.clientY);
  }

  // Anchor tooltip to cursor; flip left/up if it would overflow the viewport.
  function positionTooltip(cx, cy) {
    if (!tooltipEl || tooltipEl.hidden) return;
    const MARGIN = 8;
    const OFFSET = 14;
    // Start at the default bottom-right-of-cursor position so we can measure
    // actual rendered size, then flip as needed.
    tooltipEl.style.left = `${cx + OFFSET}px`;
    tooltipEl.style.top = `${cy + OFFSET}px`;
    const rect = tooltipEl.getBoundingClientRect();
    if (rect.right > window.innerWidth - MARGIN) {
      tooltipEl.style.left = `${Math.max(MARGIN, cx - rect.width - OFFSET)}px`;
    }
    if (rect.bottom > window.innerHeight - MARGIN) {
      tooltipEl.style.top = `${Math.max(MARGIN, cy - rect.height - OFFSET)}px`;
    }
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.hidden = true;
  }

  // ── init ──────────────────────────────────────────────────────────────────

  async function init() {
    const loadingEls = document.querySelectorAll(".chart-loading");
    try {
      const resp = await fetch(DATA_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      rawData = await resp.json();

      loadingEls.forEach(el => el.remove());
      render();

      document.querySelectorAll(".ct-cat-filter").forEach(cb => {
        cb.addEventListener("change", render);
      });

      if (thresholdEl) {
        thresholdEl.addEventListener("input", () => {
          if (thresholdValEl) thresholdValEl.textContent = thresholdEl.value;
          render();
        });
      }

    } catch (err) {
      console.error("Citation tree init error:", err);
      loadingEls.forEach(el => {
        el.textContent = `Could not load lineage data. Run the pipeline first. (${err.message})`;
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
