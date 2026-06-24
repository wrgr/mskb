// corpus_stats.js — Corpus statistics page: top papers, top authors, venues & domains.
// Renders from corpus_stats.json produced by the pipeline's compute_viz_metrics stage.
(() => {
  "use strict";

  const DATA_URL = "../../assets/corpus_stats.json";

  const CAT_COLORS = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
    unknown: "#aaaaaa",
  };

  const CAT_LABELS = {
    pathogenesis_and_immunology: "Pathogenesis & Immunology",
    imaging_and_biomarkers: "Imaging & Biomarkers",
    clinical_trials_and_therapeutics: "Therapeutics",
    clinical_care_and_management: "Clinical Care",
    epidemiology_and_population_health: "Epidemiology",
    unknown: "Other",
  };

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const statsEl = document.getElementById("cs-stats");
  const papersTableEl = document.getElementById("cs-papers-table");
  const authorsTableEl = document.getElementById("cs-authors-table");
  const venuesChartEl = document.getElementById("cs-venues-chart");
  const domainsChartEl = document.getElementById("cs-domains-chart");

  let rawData = null;
  let currentSort = "global_citations";

  // ── helpers ────────────────────────────────────────────────────────────────

  function esc(text) {
    return String(text || "").replace(/[&<>"']/g, ch =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
    );
  }

  function fmt(n) {
    return Number(n).toLocaleString();
  }

  function doiLink(doi, title) {
    const clean = String(doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
    if (!clean || clean === "nan" || clean === "none") return esc(title);
    return `<a href="https://doi.org/${esc(clean)}" target="_blank" rel="noopener" class="cs-paper-link">${esc(title)}</a>`;
  }

  // ── SVG helpers ────────────────────────────────────────────────────────────

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

  // ── stats strip ───────────────────────────────────────────────────────────

  function renderStats(data) {
    if (!statsEl) return;
    const m = data.metadata;
    const pills = [
      ["Papers", fmt(m.total_papers)],
      ["Year span", `${m.year_range[0]}–${m.year_range[1]}`],
      ["Total citations", fmt(m.total_global_citations)],
      ["Journals", fmt(m.n_venues)],
      ["Top journal", m.peak_venue],
    ];
    statsEl.innerHTML = pills
      .map(([label, val]) =>
        `<div class="fd-stat-pill"><span class="fd-stat-label">${esc(label)}</span><strong class="fd-stat-value">${esc(val)}</strong></div>`
      )
      .join("");
  }

  // ── papers table ──────────────────────────────────────────────────────────

  function renderPapersTable(data) {
    if (!papersTableEl) return;

    const keyMap = {
      global_citations: "top_papers_by_global_citations",
      corpus_citations: "top_papers_by_corpus_citations",
      importance_score: "top_papers_by_importance",
    };
    const papers = data[keyMap[currentSort]] || [];

    const colHeaders = {
      global_citations: ["#", "Paper", "Year", "First author", "Journal", "Global citations", "Corpus citations", "Importance"],
      corpus_citations: ["#", "Paper", "Year", "First author", "Journal", "Corpus citations", "Global citations", "Importance"],
      importance_score: ["#", "Paper", "Year", "First author", "Journal", "Importance", "Global citations", "Corpus citations"],
    };
    const headers = colHeaders[currentSort];

    const rows = papers.map((p, i) => {
      const catColor = CAT_COLORS[p.category] || "#aaa";
      const dot = `<span class="cs-cat-dot" style="background:${catColor}" title="${esc(CAT_LABELS[p.category] || p.category)}"></span>`;
      const cols = currentSort === "importance_score"
        ? [p.importance_score.toFixed(2), fmt(p.global_citations), fmt(p.corpus_citations)]
        : currentSort === "corpus_citations"
        ? [fmt(p.corpus_citations), fmt(p.global_citations), p.importance_score.toFixed(2)]
        : [fmt(p.global_citations), fmt(p.corpus_citations), p.importance_score.toFixed(2)];

      return `<tr>
        <td class="cs-rank">${i + 1}</td>
        <td class="cs-paper-title">${dot}${doiLink(p.doi, p.title)}</td>
        <td class="cs-num">${p.year}</td>
        <td class="cs-author">${esc(p.first_author)}</td>
        <td class="cs-venue">${esc(p.venue)}</td>
        <td class="cs-num cs-primary">${cols[0]}</td>
        <td class="cs-num">${cols[1]}</td>
        <td class="cs-num">${cols[2]}</td>
      </tr>`;
    }).join("");

    papersTableEl.innerHTML = `
      <table class="cs-table">
        <thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  // ── authors table ─────────────────────────────────────────────────────────

  function renderAuthorsTable(data) {
    if (!authorsTableEl) return;
    const authors = data.top_authors || [];

    const rows = authors.map((a, i) =>
      `<tr>
        <td class="cs-rank">${i + 1}</td>
        <td class="cs-author-name">${esc(a.name)}</td>
        <td class="cs-num">${fmt(a.papers)}</td>
        <td class="cs-num cs-primary">${a.importance_score.toFixed(3)}</td>
        <td class="cs-num">${fmt(a.corpus_citations)}</td>
        <td class="cs-num">${fmt(a.global_citations)}</td>
      </tr>`
    ).join("");

    authorsTableEl.innerHTML = `
      <table class="cs-table">
        <thead><tr>
          <th>#</th><th>Author</th><th>Papers in corpus</th>
          <th>Importance score</th><th>Corpus citations received</th><th>Global citations</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  // ── horizontal bar chart ──────────────────────────────────────────────────

  function renderHBar(container, items, colorFn) {
    if (!container) return;
    container.innerHTML = "";

    const maxVal = Math.max(...items.map(d => d.value), 1);
    const W = container.clientWidth || 520;
    const barH = 22;
    const labelW = Math.min(200, Math.round(W * 0.42));
    const numW = 48;
    const trackW = W - labelW - numW - 8;
    const H = items.length * (barH + 4) + 10;

    const svg = svgNS("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H });

    items.forEach((d, i) => {
      const y = i * (barH + 4);
      const barLen = Math.max(2, (d.value / maxVal) * trackW);

      // Label
      const label = svgText(d.label, {
        x: labelW - 6,
        y: y + barH / 2 + 4,
        "text-anchor": "end",
        "font-size": 11,
        fill: "#374151",
      });
      label.style.overflow = "hidden";
      svg.appendChild(label);

      // Track
      svg.appendChild(svgNS("rect", {
        x: labelW, y: y + 2, width: trackW, height: barH - 4,
        fill: "#f3f4f6", rx: 3,
      }));

      // Bar
      svg.appendChild(svgNS("rect", {
        x: labelW, y: y + 2, width: barLen, height: barH - 4,
        fill: colorFn(d, i), rx: 3, opacity: 0.88,
      }));

      // Count
      svg.appendChild(svgText(fmt(d.value), {
        x: labelW + trackW + 6,
        y: y + barH / 2 + 4,
        "font-size": 11,
        fill: "#6b7280",
      }));
    });

    container.appendChild(svg);
  }

  function renderVenues(data) {
    const items = (data.venues || []).slice(0, 20).map(v => ({ label: v.name, value: v.count }));
    renderHBar(venuesChartEl, items, (_d, i) => {
      const hue = (210 + i * 7) % 360;
      return `hsl(${hue},52%,48%)`;
    });
  }

  function renderDomains(data) {
    const domains = data.metadata.domains || {};
    const items = Object.entries(domains)
      .filter(([k]) => k !== "unknown")
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ label: CAT_LABELS[k] || k, value: v, key: k }));
    // Add unknown at end if present
    if (domains.unknown) items.push({ label: "Other", value: domains.unknown, key: "unknown" });
    renderHBar(domainsChartEl, items, d => CAT_COLORS[d.key] || "#aaa");
  }

  // ── tab switching ──────────────────────────────────────────────────────────

  function activateTab(tabName) {
    document.querySelectorAll(".cs-tab").forEach(btn => {
      const active = btn.dataset.tab === tabName;
      btn.classList.toggle("cs-tab-active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".cs-panel").forEach(panel => {
      panel.classList.toggle("cs-panel-hidden", !panel.id.endsWith(tabName));
    });

    // Lazy-render charts when their tab becomes visible (SVG needs clientWidth).
    if (tabName === "venues" && rawData) {
      renderVenues(rawData);
      renderDomains(rawData);
    }
  }

  // ── sort buttons ───────────────────────────────────────────────────────────

  function initSortButtons() {
    document.querySelectorAll(".cs-sort-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        if (!rawData) return;
        currentSort = btn.dataset.sort;
        document.querySelectorAll(".cs-sort-btn").forEach(b =>
          b.classList.toggle("cs-sort-active", b === btn)
        );
        renderPapersTable(rawData);
      });
    });
  }

  // ── init ───────────────────────────────────────────────────────────────────

  async function init() {
    const loadingEls = document.querySelectorAll(".chart-loading");
    try {
      const resp = await fetch(DATA_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      rawData = await resp.json();

      loadingEls.forEach(el => el.remove());

      renderStats(rawData);
      renderPapersTable(rawData);
      renderAuthorsTable(rawData);
      // venues/domains render lazily when that tab is opened

      document.querySelectorAll(".cs-tab").forEach(btn => {
        btn.addEventListener("click", () => activateTab(btn.dataset.tab));
      });

      initSortButtons();

    } catch (err) {
      console.error("Corpus stats init error:", err);
      loadingEls.forEach(el => {
        el.textContent = `Could not load corpus statistics. Run the pipeline first. (${err.message})`;
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
