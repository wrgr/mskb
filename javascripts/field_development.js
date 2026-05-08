// field_development.js — Field development charts for the MSKB site.
// Renders a stacked-bar timeline (annual paper output by domain), a
// scatter/bubble chart (year vs importance, sized by citations), and a
// citation genealogy graph (concentric rings by generation) from
// field_development.json and lineage_data.json produced by the pipeline.
(() => {
  "use strict";

  const DATA_URL = "../assets/field_development.json";
  const LINEAGE_URL = "../assets/lineage_data.json";

  const CAT_COLORS = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
    unknown: "#aaaaaa",
  };

  // Margin constants for both SVG charts
  const M = { top: 18, right: 20, bottom: 44, left: 44 };

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const timelineEl = document.getElementById("fd-timeline");
  const scatterEl = document.getElementById("fd-scatter");
  const tooltipEl = document.getElementById("fd-tooltip");
  const statsEl = document.getElementById("fd-stats");
  const ancestryEl = document.getElementById("fd-ancestry");
  const ancestryTooltipEl = document.getElementById("fd-ancestry-tooltip");
  const ancestryThresholdEl = document.getElementById("fd-ancestry-threshold");
  const ancestryThresholdValEl = document.getElementById("fd-ancestry-threshold-val");
  const ancestryCountEl = document.getElementById("fd-ancestry-count");

  let rawData = null;
  let lineageData = null;
  let cyInstance = null; // active Cytoscape instance
  let selectedYear = null; // click-to-filter on timeline bar

  // ── helpers ──────────────────────────────────────────────────────────────

  function activeCats() {
    return new Set(
      [...document.querySelectorAll(".fd-cat-filter")]
        .filter(cb => cb.checked)
        .map(cb => cb.value)
    );
  }

  function esc(text) {
    return String(text || "").replace(/[&<>"']/g, ch =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
    );
  }

  function svgNS(tag, attrs = {}) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  }

  function svgText(txt, attrs = {}) {
    const el = svgNS("text", attrs);
    el.textContent = txt;
    return el;
  }

  function linearScale(domainMin, domainMax, rangeMin, rangeMax) {
    const dSpan = domainMax - domainMin || 1;
    const rSpan = rangeMax - rangeMin;
    return v => rangeMin + ((v - domainMin) / dSpan) * rSpan;
  }

  // ── stats strip ──────────────────────────────────────────────────────────

  function renderStats(data) {
    if (!statsEl) return;
    const { total_papers, year_range } = data.metadata;
    const yearSpan = year_range[1] - year_range[0];
    const topYear = data.timeline.reduce((a, b) => b.total > a.total ? b : a, data.timeline[0] || { year: "—", total: 0 });
    const pills = [
      ["Papers", total_papers.toLocaleString()],
      ["Year span", `${year_range[0]}–${year_range[1]} (${yearSpan} yrs)`],
      ["Peak year", `${topYear.year} (${topYear.total} papers)`],
      ["Domains", Object.keys(data.categories).length],
    ];
    statsEl.innerHTML = pills.map(([label, val]) =>
      `<div class="fd-stat-pill"><span class="fd-stat-label">${esc(label)}</span><strong class="fd-stat-value">${esc(val)}</strong></div>`
    ).join("");
  }

  // ── stacked bar timeline ─────────────────────────────────────────────────

  function renderTimeline(data, cats) {
    if (!timelineEl) return;
    timelineEl.innerHTML = "";

    const rows = data.timeline.filter(r => selectedYear === null || r.year === selectedYear);
    const visRows = data.timeline; // always draw full x-axis

    const W = timelineEl.clientWidth || 840;
    const H = 280;
    const innerW = W - M.left - M.right;
    const innerH = H - M.top - M.bottom;

    const maxTotal = Math.max(...visRows.map(r => {
      let t = 0;
      for (const c of cats) t += r[c] || 0;
      return t;
    }), 1);

    const years = visRows.map(r => r.year);
    const xScale = linearScale(0, years.length - 1, 0, innerW);
    const yScale = linearScale(0, maxTotal, innerH, 0);
    const barW = Math.max(2, (innerW / years.length) * 0.8);

    const svg = svgNS("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img", "aria-label": "Annual paper output stacked bar chart" });
    const g = svgNS("g", { transform: `translate(${M.left},${M.top})` });
    svg.appendChild(g);

    // Y gridlines
    const yTicks = 5;
    for (let i = 0; i <= yTicks; i++) {
      const val = (maxTotal / yTicks) * i;
      const y = yScale(val);
      g.appendChild(svgNS("line", { x1: 0, y1: y, x2: innerW, y2: y, stroke: "#e5e7eb", "stroke-width": 1 }));
      g.appendChild(svgText(Math.round(val), { x: -6, y: y + 4, "text-anchor": "end", "font-size": 10, fill: "#6b7280" }));
    }

    // Stacked bars
    years.forEach((year, i) => {
      const row = visRows[i];
      const cx = xScale(i);
      let yOff = innerH;
      const isHighlight = selectedYear === year;

      for (const cat of cats) {
        const count = row[cat] || 0;
        if (count === 0) continue;
        const bH = innerH - yScale(count);
        yOff -= bH;
        const rect = svgNS("rect", {
          x: cx - barW / 2,
          y: yOff,
          width: barW,
          height: bH,
          fill: CAT_COLORS[cat] || "#aaa",
          opacity: isHighlight ? 1 : (selectedYear !== null ? 0.4 : 0.85),
          rx: 1,
        });
        rect.style.cursor = "pointer";
        rect.addEventListener("click", () => {
          selectedYear = selectedYear === year ? null : year;
          renderAll(rawData);
        });
        rect.addEventListener("mouseenter", e => showTooltip(e, `${year}: ${count} ${(data.categories[cat] || cat)} papers`));
        rect.addEventListener("mouseleave", hideTooltip);
        g.appendChild(rect);
      }

      // X tick label — every 5 years
      if (year % 5 === 0) {
        g.appendChild(svgText(year, {
          x: cx, y: innerH + 16, "text-anchor": "middle", "font-size": 10, fill: "#6b7280",
        }));
      }
    });

    // Axes
    g.appendChild(svgNS("line", { x1: 0, y1: innerH, x2: innerW, y2: innerH, stroke: "#9ca3af", "stroke-width": 1 }));
    g.appendChild(svgNS("line", { x1: 0, y1: 0, x2: 0, y2: innerH, stroke: "#9ca3af", "stroke-width": 1 }));

    if (selectedYear !== null) {
      g.appendChild(svgText(`Filtered to ${selectedYear} — click bar to clear`, {
        x: innerW, y: -4, "text-anchor": "end", "font-size": 10, fill: "#0e8f85",
      }));
    }

    timelineEl.appendChild(svg);
  }

  // ── scatter chart ────────────────────────────────────────────────────────

  function renderScatter(data, cats) {
    if (!scatterEl) return;
    scatterEl.innerHTML = "";

    const points = data.scatter.filter(p =>
      cats.has(p.category) && (selectedYear === null || p.year === selectedYear)
    );
    if (points.length === 0) {
      scatterEl.innerHTML = '<p class="chart-empty">No papers match the current filter.</p>';
      return;
    }

    const W = scatterEl.clientWidth || 840;
    const H = 360;
    const innerW = W - M.left - M.right;
    const innerH = H - M.top - M.bottom;

    const years = points.map(p => p.year);
    const xScale = linearScale(Math.min(...years) - 1, Math.max(...years) + 1, 0, innerW);
    const yScale = linearScale(0, Math.max(...points.map(p => p.importance_score), 0.01), innerH, 0);
    const maxCite = Math.max(...points.map(p => p.cited_by_count), 1);
    const rScale = v => 3 + Math.sqrt(v / maxCite) * 14;

    const svg = svgNS("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img", "aria-label": "Research landscape scatter plot" });
    const g = svgNS("g", { transform: `translate(${M.left},${M.top})` });
    svg.appendChild(g);

    // Y gridlines and axis labels
    const yTicks = 5;
    for (let i = 0; i <= yTicks; i++) {
      const val = i / yTicks;
      const y = yScale(val);
      g.appendChild(svgNS("line", { x1: 0, y1: y, x2: innerW, y2: y, stroke: "#e5e7eb", "stroke-width": 1 }));
      g.appendChild(svgText(`${Math.round(val * 100)}%`, { x: -6, y: y + 4, "text-anchor": "end", "font-size": 10, fill: "#6b7280" }));
    }

    // X axis ticks
    const xMin = Math.min(...years);
    const xMax = Math.max(...years);
    for (let yr = Math.ceil(xMin / 5) * 5; yr <= xMax; yr += 5) {
      const x = xScale(yr);
      g.appendChild(svgNS("line", { x1: x, y1: innerH, x2: x, y2: innerH + 4, stroke: "#9ca3af" }));
      g.appendChild(svgText(yr, { x, y: innerH + 16, "text-anchor": "middle", "font-size": 10, fill: "#6b7280" }));
    }

    // Axes
    g.appendChild(svgNS("line", { x1: 0, y1: innerH, x2: innerW, y2: innerH, stroke: "#9ca3af" }));
    g.appendChild(svgNS("line", { x1: 0, y1: 0, x2: 0, y2: innerH, stroke: "#9ca3af" }));

    // Axis labels
    g.appendChild(svgText("Importance score", { x: -innerH / 2, y: -30, "text-anchor": "middle", "font-size": 11, fill: "#374151", transform: `rotate(-90)` }));
    g.appendChild(svgText("Publication year", { x: innerW / 2, y: innerH + 36, "text-anchor": "middle", "font-size": 11, fill: "#374151" }));

    // Circles — draw smallest on top
    const sorted = [...points].sort((a, b) => b.cited_by_count - a.cited_by_count);
    for (const p of sorted) {
      const cx = xScale(p.year);
      const cy = yScale(p.importance_score);
      const r = rScale(p.cited_by_count);
      const circle = svgNS("circle", {
        cx, cy, r,
        fill: CAT_COLORS[p.category] || "#aaa",
        opacity: 0.72,
        stroke: "rgba(255,255,255,0.4)",
        "stroke-width": 0.5,
      });
      circle.style.cursor = "default";
      circle.addEventListener("mouseenter", e => showTooltip(e,
        `<strong>${esc(p.title)}</strong><br/>${p.year} &nbsp;·&nbsp; ${p.cited_by_count.toLocaleString()} citations<br/>Importance: ${(p.importance_score * 100).toFixed(1)}%`
      ));
      circle.addEventListener("mouseleave", hideTooltip);
      g.appendChild(circle);
    }

    scatterEl.appendChild(svg);
  }

  // ── tooltip ──────────────────────────────────────────────────────────────

  function showTooltip(e, html) {
    if (!tooltipEl) return;
    tooltipEl.innerHTML = html;
    tooltipEl.hidden = false;
    const rect = (scatterEl || timelineEl).getBoundingClientRect();
    const ex = e.clientX - rect.left + 12;
    const ey = e.clientY - rect.top - 8;
    tooltipEl.style.left = `${ex}px`;
    tooltipEl.style.top = `${ey}px`;
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.hidden = true;
  }

  // ── citation genealogy (Cytoscape) ───────────────────────────────────────

  function renderAncestry() {
    if (!ancestryEl || !lineageData) return;
    if (typeof cytoscape === "undefined") {
      ancestryEl.innerHTML = '<p class="chart-empty">Graph library not loaded — reload the page.</p>';
      return;
    }

    const cats = activeCats();
    const threshold = parseFloat(ancestryThresholdEl ? ancestryThresholdEl.value : "0.5");

    const filteredNodes = lineageData.nodes.filter(
      n => cats.has(n.category) && n.importance_score >= threshold
    );
    const nodeIdSet = new Set(filteredNodes.map(n => n.id));
    const filteredLinks = lineageData.links.filter(
      l => nodeIdSet.has(l.source) && nodeIdSet.has(l.target)
    );

    if (ancestryCountEl) {
      ancestryCountEl.textContent = `${filteredNodes.length} papers · ${filteredLinks.length} citation links`;
    }

    if (filteredNodes.length === 0) {
      ancestryEl.innerHTML = '<p class="chart-empty">No papers match the current filter — try lowering the importance threshold.</p>';
      return;
    }

    const maxGen = Math.max(...filteredNodes.map(n => n.generation), 0);
    const maxCite = Math.max(...filteredNodes.map(n => n.cited_by_count), 1);

    // Destroy previous instance before re-creating to free memory.
    if (cyInstance) {
      cyInstance.destroy();
      cyInstance = null;
    }
    ancestryEl.innerHTML = "";

    // Edges in lineage_data: source CITES target (newer → older).
    // Reverse them so arrows flow FROM foundational papers OUTWARD to descendants.
    const elements = [
      ...filteredNodes.map(n => ({
        data: {
          id: String(n.id),
          category: n.category,
          generation: n.generation,
          year: n.year,
          importance: n.importance_score,
          citations: n.cited_by_count,
          fullTitle: n.title,
          author: n.first_author || "",
        },
      })),
      ...filteredLinks.map((l, i) => ({
        data: {
          id: `e${i}`,
          source: String(l.target), // cited paper → ancestor
          target: String(l.source), // citing paper → descendant
        },
      })),
    ];

    cyInstance = cytoscape({
      container: ancestryEl,
      elements,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(category)",
            "width": "mapData(citations, 0, " + maxCite + ", 10, 40)",
            "height": "mapData(citations, 0, " + maxCite + ", 10, 40)",
            "border-width": 1.2,
            "border-color": "rgba(255,255,255,0.55)",
            "label": "",
          },
        },
        {
          selector: "node[category = 'pathogenesis_and_immunology']",
          style: { "background-color": "#1f77b4" },
        },
        {
          selector: "node[category = 'imaging_and_biomarkers']",
          style: { "background-color": "#17a2b8" },
        },
        {
          selector: "node[category = 'clinical_trials_and_therapeutics']",
          style: { "background-color": "#d62728" },
        },
        {
          selector: "node[category = 'clinical_care_and_management']",
          style: { "background-color": "#2ca02c" },
        },
        {
          selector: "node[category = 'epidemiology_and_population_health']",
          style: { "background-color": "#9467bd" },
        },
        {
          selector: "node[category = 'unknown']",
          style: { "background-color": "#aaaaaa" },
        },
        {
          selector: "edge",
          style: {
            "width": 0.9,
            "line-color": "rgba(100,120,140,0.18)",
            "target-arrow-color": "rgba(100,120,140,0.22)",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.55,
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "border-width": 3,
            "border-color": "#0e8f85",
          },
        },
        {
          selector: "node.dimmed",
          style: { "opacity": 0.25 },
        },
        {
          selector: "edge.dimmed",
          style: { "opacity": 0.08 },
        },
      ],
      layout: {
        name: "concentric",
        // gen-0 papers (foundational) sit at centre; higher gens radiate outward.
        concentric: node => Math.max(0, maxGen - node.data("generation") + 1),
        levelWidth: () => 1,
        minNodeSpacing: 14,
        padding: 28,
        startAngle: (3 * Math.PI) / 2,
        clockwise: true,
        animate: false,
      },
      wheelSensitivity: 0.35,
      minZoom: 0.08,
      maxZoom: 6,
    });

    // Tooltip and highlight on hover.
    cyInstance.on("mouseover", "node", evt => {
      const n = evt.target;
      const pos = n.renderedPosition();

      if (ancestryTooltipEl) {
        const gen = n.data("generation");
        const genLabel = gen === 0
          ? "Foundational (generation 0)"
          : `Generation ${gen}`;
        ancestryTooltipEl.innerHTML =
          `<strong>${esc(n.data("fullTitle"))}</strong><br/>` +
          `${n.data("year")}` +
          (n.data("author") ? ` · ${esc(n.data("author"))}` : "") +
          `<br/>${n.data("citations").toLocaleString()} citations` +
          ` · importance ${n.data("importance").toFixed(2)}` +
          `<br/><em>${genLabel}</em>`;
        ancestryTooltipEl.hidden = false;
        ancestryTooltipEl.style.left = `${pos.x + 14}px`;
        ancestryTooltipEl.style.top = `${pos.y - 10}px`;
      }

      // Dim everything except this node and its direct neighbours.
      const neighbourhood = n.closedNeighborhood();
      cyInstance.elements().addClass("dimmed");
      neighbourhood.removeClass("dimmed");
      n.addClass("highlighted");
    });

    cyInstance.on("mouseout", "node", () => {
      if (ancestryTooltipEl) ancestryTooltipEl.hidden = true;
      cyInstance.elements().removeClass("dimmed highlighted");
    });
  }

  // ── render all charts ────────────────────────────────────────────────────

  function renderAll(data) {
    const cats = activeCats();
    renderTimeline(data, cats);
    renderScatter(data, cats);
    if (lineageData) renderAncestry();
  }

  // ── init ─────────────────────────────────────────────────────────────────

  async function init() {
    const loadingEls = document.querySelectorAll(".chart-loading");

    try {
      // Fetch both data sources in parallel; lineage may 404 on first run.
      const [fdResp, lineageResp] = await Promise.all([
        fetch(DATA_URL),
        fetch(LINEAGE_URL).catch(() => null),
      ]);

      if (!fdResp.ok) throw new Error(`HTTP ${fdResp.status}`);
      rawData = await fdResp.json();

      if (lineageResp && lineageResp.ok) {
        lineageData = await lineageResp.json();
      }

      loadingEls.forEach(el => el.remove());

      renderStats(rawData);
      renderTimeline(rawData, activeCats());
      renderScatter(rawData, activeCats());

      if (lineageData) {
        renderAncestry();
      } else if (ancestryEl) {
        ancestryEl.innerHTML = '<p class="chart-empty">Lineage data not found — run the pipeline first.</p>';
      }

      document.querySelectorAll(".fd-cat-filter").forEach(cb => {
        cb.addEventListener("change", () => {
          renderTimeline(rawData, activeCats());
          renderScatter(rawData, activeCats());
          if (lineageData) renderAncestry();
        });
      });

      if (ancestryThresholdEl) {
        ancestryThresholdEl.addEventListener("input", () => {
          if (ancestryThresholdValEl) {
            ancestryThresholdValEl.textContent = ancestryThresholdEl.value;
          }
          if (lineageData) renderAncestry();
        });
      }

      // Re-render SVG charts on resize; Cytoscape handles its own responsiveness.
      let resizeTimer;
      window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          renderTimeline(rawData, activeCats());
          renderScatter(rawData, activeCats());
        }, 120);
      });

    } catch (err) {
      console.error("Field development init error:", err);
      loadingEls.forEach(el => {
        el.textContent = `Could not load field development data. Run the pipeline first. (${err.message})`;
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
