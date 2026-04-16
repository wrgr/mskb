// lineage.js — Citation lineage visualization using Sigma.js + Graphology.
// Papers are positioned by publication year (x) and rank within each year (y),
// colored by MS research domain, with hover highlighting and a detail panel.
(() => {
  "use strict";

  const DATA_URL = "../assets/lineage_data.json";

  const CAT_COLORS = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
    unknown: "#aaaaaa",
  };

  const EDGE_BASE = "rgba(66,84,102,0.10)";
  const EDGE_ACTIVE = "rgba(11,59,102,0.60)";
  const EDGE_DIM = "rgba(200,210,220,0.05)";
  const NODE_HOVER = "#ff6b35";
  const NODE_DIM = "rgba(200,210,220,0.35)";

  // DOM refs
  const stageEl = document.getElementById("lineage-stage");
  const loadingEl = document.getElementById("lineage-loading");
  const statusEl = document.getElementById("lineage-status");
  const panelEl = document.getElementById("lineage-paper-panel");
  const detailsEl = document.getElementById("lineage-paper-details");
  const closePanelEl = document.getElementById("lineage-panel-close");
  const resetEl = document.getElementById("lineage-reset");
  const fitEl = document.getElementById("lineage-fit");
  const yearMinEl = document.getElementById("lineage-year-min");
  const yearMaxEl = document.getElementById("lineage-year-max");
  const genMaxEl = document.getElementById("lineage-gen-max");
  const genLabelEl = document.getElementById("lineage-gen-label");
  const showEdgesEl = document.getElementById("lineage-show-edges");

  let renderer = null;
  let graphRef = null;
  let rawData = null;

  // ── helpers ─────────────────────────────────────────────────────────────

  function catFilters() {
    return [...document.querySelectorAll(".cat-filter")];
  }

  function activeFilters() {
    const yearMin = parseInt(yearMinEl?.value || "0", 10);
    const yearMax = parseInt(yearMaxEl?.value || "3000", 10);
    const genMax = genMaxEl ? parseInt(genMaxEl.value, 10) : Infinity;
    const activeCats = new Set(catFilters().filter(cb => cb.checked).map(cb => cb.value));
    return { yearMin, yearMax, genMax, activeCats };
  }

  function nodeColor(meta) {
    return CAT_COLORS[meta?.category] || CAT_COLORS.unknown;
  }

  function nodeSize(n) {
    // Map importance_score [0,1] to pixel radius [4,18].
    return 4 + Math.min(14, n.importance_score * 14);
  }

  function esc(text) {
    return String(text || "").replace(/[&<>"']/g, ch =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
    );
  }

  // ── layout ──────────────────────────────────────────────────────────────

  // Assign x = normalized year, y = sorted rank within year by importance.
  function computePositions(nodes, yearRange) {
    const [yrMin, yrMax] = yearRange;
    const span = yrMax - yrMin || 1;

    const byYear = {};
    for (const n of nodes) {
      (byYear[n.year] = byYear[n.year] || []).push(n);
    }
    // Sort each year bucket by importance descending (most important at y=0 center).
    for (const bucket of Object.values(byYear)) {
      bucket.sort((a, b) => b.importance_score - a.importance_score);
    }

    const positions = {};
    for (const [yr, bucket] of Object.entries(byYear)) {
      const x = ((Number(yr) - yrMin) / span) * 20 - 10;
      const count = bucket.length;
      const spread = Math.min(count * 0.55, 10);
      bucket.forEach((n, i) => {
        const y = count === 1 ? 0 : -spread / 2 + (i / (count - 1)) * spread;
        positions[n.paper_id] = { x, y };
      });
    }
    return positions;
  }

  // ── graph construction ───────────────────────────────────────────────────

  function buildGraph(Graph, data) {
    const graph = new Graph({ type: "directed", multi: false, allowSelfLoops: false });
    const positions = computePositions(data.nodes, data.metadata.year_range);

    for (const n of data.nodes) {
      const pos = positions[n.paper_id] || { x: 0, y: 0 };
      const label = n.title.length > 55 ? n.title.slice(0, 52) + "…" : n.title;
      graph.addNode(n.paper_id, {
        x: pos.x,
        y: pos.y,
        size: nodeSize(n),
        color: nodeColor(n),
        label,
        _meta: n,
      });
    }

    const nodeSet = new Set(graph.nodes());
    for (const lk of data.links) {
      const src = data.nodes[lk.source]?.paper_id;
      const tgt = data.nodes[lk.target]?.paper_id;
      if (src && tgt && nodeSet.has(src) && nodeSet.has(tgt)) {
        try {
          graph.addDirectedEdge(src, tgt, { color: EDGE_BASE, size: 0.5 });
        } catch (_) { /* skip duplicate */ }
      }
    }
    return graph;
  }

  // ── filtering ────────────────────────────────────────────────────────────

  function applyFilters(graph, data) {
    const { yearMin, yearMax, genMax, activeCats } = activeFilters();
    const showEdges = showEdgesEl?.checked !== false;

    const visibleIds = new Set(
      data.nodes
        .filter(n =>
          n.year >= yearMin && n.year <= yearMax &&
          n.generation <= genMax &&
          activeCats.has(n.category)
        )
        .map(n => n.paper_id)
    );

    graph.nodes().forEach(id => {
      graph.setNodeAttribute(id, "hidden", !visibleIds.has(id));
    });
    graph.edges().forEach(id => {
      const hide = !showEdges || !visibleIds.has(graph.source(id)) || !visibleIds.has(graph.target(id));
      graph.setEdgeAttribute(id, "hidden", hide);
    });

    const visCount = visibleIds.size;
    if (statusEl) statusEl.textContent = `Showing ${visCount.toLocaleString()} of ${data.nodes.length.toLocaleString()} papers`;
  }

  // ── paper panel ──────────────────────────────────────────────────────────

  // Build a mailto: link that lets a user flag a paper as incorrect. The
  // email carries the paper id (subject) plus title and current page URL
  // (body) so the recipient can locate the source of the complaint.
  function renderFlagLink(id, title) {
    const safeId = String(id || "");
    const safeTitle = String(title || "Untitled");
    const pageUrl = (typeof window !== "undefined" && window.location) ? window.location.href : "";
    const subject = `[MSKB Flag] ${safeId}`;
    const body = `Paper: ${safeTitle}\nID: ${safeId}\nURL: ${pageUrl}\n\nWhat's wrong:\n`;
    const href = `mailto:willgray@gmail.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    return `<a class="btn-flag" href="${href}" title="Flag this paper as incorrect or problematic">⚑ Flag</a>`;
  }

  function renderPaperPanel(n) {
    if (!panelEl || !detailsEl) return;
    const doiHref = n.doi ? `<a href="https://doi.org/${esc(n.doi)}" target="_blank" rel="noopener noreferrer">${esc(n.doi)}</a>` : "—";
    const author = n.first_author ? esc(n.first_author) + " et al." : "—";
    const flagLink = renderFlagLink(n.paper_id, n.title);
    detailsEl.innerHTML = `
      <p class="lineage-panel-title">${esc(n.title)}</p>
      <p class="lineage-panel-byline">${n.year} &nbsp;·&nbsp; ${author}</p>
      <table class="lineage-stats-table">
        <tr><th>Importance</th><td>${(n.importance_score * 100).toFixed(1)}%</td></tr>
        <tr><th>Total citations</th><td>${n.cited_by_count.toLocaleString()}</td></tr>
        <tr><th>Cites (out-degree)</th><td>${n.out_degree}</td></tr>
        <tr><th>Cited by (in-degree)</th><td>${n.in_degree}</td></tr>
        <tr><th>Generation</th><td>${n.generation}</td></tr>
        <tr><th>Domain</th><td>${esc(n.category.replace(/_/g, " "))}</td></tr>
        <tr><th>Tier</th><td>${esc(n.tier)}</td></tr>
        <tr><th>DOI</th><td>${doiHref}</td></tr>
      </table>
      <div class="lineage-panel-actions">${flagLink}</div>
    `;
    panelEl.hidden = false;
  }

  // ── hover highlight ──────────────────────────────────────────────────────

  function onEnterNode(graph, nodeId) {
    const neighbors = new Set(graph.neighbors(nodeId));
    graph.nodes().forEach(id => {
      graph.setNodeAttribute(id, "color",
        id === nodeId ? NODE_HOVER :
        neighbors.has(id) ? nodeColor(graph.getNodeAttribute(id, "_meta")) :
        NODE_DIM
      );
    });
    graph.edges().forEach(id => {
      const active = graph.source(id) === nodeId || graph.target(id) === nodeId;
      graph.setEdgeAttribute(id, "color", active ? EDGE_ACTIVE : EDGE_DIM);
    });
  }

  function onLeaveNode(graph) {
    graph.nodes().forEach(id => {
      graph.setNodeAttribute(id, "color", nodeColor(graph.getNodeAttribute(id, "_meta")));
    });
    graph.edges().forEach(id => {
      graph.setEdgeAttribute(id, "color", EDGE_BASE);
    });
  }

  // ── controls wiring ──────────────────────────────────────────────────────

  function wireControls(renderer, graph, data) {
    function refilter() {
      applyFilters(graph, data);
      renderer.refresh();
    }

    catFilters().forEach(cb => cb.addEventListener("change", refilter));
    yearMinEl?.addEventListener("change", refilter);
    yearMaxEl?.addEventListener("change", refilter);
    showEdgesEl?.addEventListener("change", refilter);

    genMaxEl?.addEventListener("input", () => {
      const v = parseInt(genMaxEl.value, 10);
      const maxGen = data.metadata.generation_count - 1;
      if (genLabelEl) genLabelEl.textContent = v >= maxGen ? "all" : `≤ ${v}`;
      refilter();
    });

    resetEl?.addEventListener("click", () => {
      renderer.getCamera().animatedReset({ duration: 300 });
    });

    fitEl?.addEventListener("click", () => {
      renderer.getCamera().animatedReset({ duration: 300 });
    });

    closePanelEl?.addEventListener("click", () => {
      if (panelEl) panelEl.hidden = true;
    });
  }

  // ── renderer setup ───────────────────────────────────────────────────────

  function setupRenderer(Sigma, graph) {
    const inst = new Sigma(graph, stageEl, {
      renderEdgeLabels: false,
      minCameraRatio: 0.03,
      maxCameraRatio: 8,
      defaultEdgeColor: EDGE_BASE,
      defaultNodeColor: CAT_COLORS.unknown,
      labelRenderedSizeThreshold: 8,
    });

    inst.on("clickNode", ({ node }) => {
      const meta = graph.getNodeAttribute(node, "_meta");
      if (meta) renderPaperPanel(meta);
    });

    inst.on("enterNode", ({ node }) => { onEnterNode(graph, node); inst.refresh(); });
    inst.on("leaveNode", () => { onLeaveNode(graph); inst.refresh(); });

    return inst;
  }

  // ── init ─────────────────────────────────────────────────────────────────

  async function init() {
    try {
      const Graph = window.graphology;
      const Sigma = typeof window.Sigma === "function" ? window.Sigma : window.Sigma?.default;
      if (!Graph || !Sigma) throw new Error("Sigma or Graphology unavailable — check vendor scripts.");

      const resp = await fetch(DATA_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching ${DATA_URL}`);
      rawData = await resp.json();

      if (loadingEl) loadingEl.remove();

      // Clamp controls to actual data range
      if (genMaxEl && rawData.metadata.generation_count) {
        genMaxEl.max = rawData.metadata.generation_count - 1;
        genMaxEl.value = genMaxEl.max;
        if (genLabelEl) genLabelEl.textContent = "all";
      }
      if (yearMinEl && rawData.metadata.year_range) {
        yearMinEl.value = rawData.metadata.year_range[0];
        yearMaxEl.value = rawData.metadata.year_range[1];
      }

      graphRef = buildGraph(Graph, rawData);
      applyFilters(graphRef, rawData);
      renderer = setupRenderer(Sigma, graphRef);
      wireControls(renderer, graphRef, rawData);

    } catch (err) {
      console.error("Lineage init error:", err);
      if (loadingEl) {
        loadingEl.textContent = `Could not load lineage data. Run the pipeline first to generate lineage_data.json. (${err.message})`;
        loadingEl.removeAttribute("aria-busy");
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
