# Explorer

Use this graph to inspect papers, follow citation paths, and turn a short research note into parent/child/related paper choices.

<script src="../javascripts/vendor/graphology.umd.min.js"></script>
<script src="../javascripts/vendor/sigma.min.js"></script>

<div class="top-idea reveal">
  <h3>Explore the MS Knowledge Graph</h3>
  <p>Use this view to inspect citation structure, read paper summaries, and plan literature exploration from core papers out to related work.</p>
  <div class="explorer-guide">
    <div class="guide-card"><strong>Undergrad flow:</strong> start with lower language level, then branch through related papers.</div>
    <div class="guide-card"><strong>Grad flow:</strong> raise structural filters (in/out degree and k-core) for denser, high-signal papers.</div>
    <div class="guide-card"><strong>Node semantics:</strong> size is log(citations), color is k-core tier, arrows are citations.</div>
  </div>
</div>

<details id="parameters" class="param-tray reveal" open>
  <summary><strong>Parameters</strong> (expand/collapse)</summary>
  <div class="explorer-presets">
    <span class="preset-label">Preset views</span>
    <button id="preset-undergrad" type="button">Undergrad Starter</button>
    <button id="preset-balanced" type="button">Balanced Survey</button>
    <button id="preset-grad" type="button">Grad Deep Dive</button>
  </div>
  <div class="explorer-toolbar">
    <label for="core-metric">Core metric</label>
    <select id="core-metric">
      <option value="composite" selected>Composite (recommended)</option>
      <option value="pagerank">PageRank</option>
      <option value="kcore">k-core</option>
      <option value="in_degree">In-degree</option>
      <option value="age_normalized">Age-normalized centrality</option>
    </select>
    <label for="difficulty-max">Max language level</label>
    <select id="difficulty-max">
      <option value="5" selected>All (1-5)</option>
      <option value="2">1-2 Plain language</option>
      <option value="3">1-3 Moderate technicality</option>
      <option value="4">1-4 Advanced language</option>
    </select>
    <label for="min-in-degree">Min in-degree</label>
    <input id="min-in-degree" type="number" min="0" step="1" value="5" />
    <label for="min-out-degree">Min out-degree</label>
    <input id="min-out-degree" type="number" min="0" step="1" value="5" />
    <label for="min-kcore">Min k-core</label>
    <input id="min-kcore" type="number" min="0" step="1" value="10" />
    <label for="core-percentile">Percentile cutoff</label>
    <input id="core-percentile" type="range" min="0" max="95" step="5" value="40" />
    <span id="core-percentile-value">40%</span>
    <label><input id="require-abstract" type="checkbox" checked /> Require abstract</label>
  </div>
  <p><strong>Language scale:</strong> 1-2 plain wording, 3 moderate technical wording, 4-5 specialist terminology density.</p>
  <div class="explorer-actions">
    <button id="core-apply">Apply Core Filter</button>
    <button id="load-full-corpus" type="button">Load Full Corpus</button>
    <button id="node-drag-toggle" type="button">Enable Node Drag</button>
    <button id="graph-relayout">Re-Layout Graph</button>
  </div>
  <div id="graph-status"></div>
  <div class="explorer-legend">
    <span><strong>Direction:</strong> <i class="legend-swatch swatch-in"></i>incoming <i class="legend-swatch swatch-out"></i>outgoing</span>
    <span><strong>k-core tier:</strong> <i class="legend-swatch swatch-high"></i>core <i class="legend-swatch swatch-mid"></i>middle <i class="legend-swatch swatch-low"></i>peripheral</span>
    <span><strong>Node size:</strong> log(total citations); click a node to emphasize induced subgraph</span>
  </div>
  </details>

<div id="paper-graph" class="reveal"></div>

<div class="panel reveal">
  <h3>Selected Paper</h3>
  <div id="paper-details">Select a node to view summary, source link, and relationship choices.</div>
  <h3>Relationship Navigator</h3>
  <div class="rel-section">
    <h4>Parents (papers this one cites)</h4>
    <div id="parent-links"></div>
  </div>
  <div class="rel-section">
    <h4>Children (papers that cite this one)</h4>
    <div id="child-links"></div>
  </div>
  <div class="rel-section">
    <h4>Related (nearby in citation neighborhood)</h4>
    <div id="related-links"></div>
  </div>
</div>

<div class="tools-panel reveal">
  <h3>Tools</h3>
  <div class="tool-grid">
    <section class="tool-card">
      <h4>Direct Search</h4>
      <p>Search directly by author, title, or abstract text.</p>
      <div class="explorer-search">
        <label for="direct-search-mode">Search in</label>
        <select id="direct-search-mode">
          <option value="all" selected>All fields</option>
          <option value="author">Author</option>
          <option value="title">Title</option>
          <option value="abstract">Abstract</option>
        </select>
        <label for="direct-search-input">Query</label>
        <input id="direct-search-input" type="text" placeholder="Example: Giovannoni OR neurofilament OR remyelination" />
        <button id="direct-search-run" type="button">Run Search</button>
      </div>
      <div id="direct-search-results"></div>
    </section>

    <section class="tool-card">
      <h4>Find Research Like...</h4>
      <p>Write a brief research idea and retrieve relevant papers in the current filtered corpus.</p>
      <textarea id="idea-input" placeholder="Example: EBV-linked immune mechanisms that connect to progression biomarkers in MS"></textarea>
      <div class="explorer-actions">
        <button id="idea-run" type="button">Find Relevant Papers</button>
      </div>
      <div id="idea-results"></div>
    </section>

    <section class="tool-card">
      <h4>Learning Journey Builder</h4>
      <p>Add papers from the graph or tool results, then generate a staged learning journey.</p>
      <div id="journey-selected"></div>
      <div class="explorer-actions">
        <button id="journey-generate" type="button">Generate Learning Journey</button>
        <button id="journey-clear" type="button">Clear Selection</button>
      </div>
      <div id="journey-results"></div>
    </section>
  </div>
</div>

<script>
// ---- explorer boot diagnostics (must run before anything else) ----
window.__mskbDebug = function (msg) {
  try {
    var panel = document.getElementById("mskb-debug-panel");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "mskb-debug-panel";
      panel.style.cssText = "position:fixed;left:8px;bottom:8px;z-index:999999;max-width:46vw;max-height:40vh;overflow:auto;background:#111;color:#0f0;font:11px/1.35 ui-monospace,Menlo,Consolas,monospace;padding:8px 10px;border:1px solid #0f0;border-radius:6px;white-space:pre-wrap;box-shadow:0 4px 12px rgba(0,0,0,0.4);";
      panel.innerHTML = '<strong style="color:#fff;">mskb debug</strong> <a href="#" id="mskb-debug-close" style="color:#0ff;float:right;">close</a><br>';
      (document.body || document.documentElement).appendChild(panel);
      var closer = document.getElementById("mskb-debug-close");
      if (closer) closer.addEventListener("click", function (e) { e.preventDefault(); panel.style.display = "none"; });
    }
    var line = document.createElement("div");
    var t = new Date().toISOString().slice(11, 23);
    line.textContent = "[" + t + "] " + String(msg);
    panel.appendChild(line);
    if (window.console && console.log) console.log("[mskb]", msg);
  } catch (_) { /* swallow */ }
};
(function explorerBootDiagnostics() {
  try {
    window.__mskbDebug("boot: inline script reached");
    window.__mskbDebug("vendors: Sigma=" + (typeof window.Sigma) + " graphology=" + (typeof window.graphology));
    var dimsEl = document.getElementById("paper-graph");
    if (dimsEl) {
      var r = dimsEl.getBoundingClientRect();
      window.__mskbDebug("paper-graph rect: " + Math.round(r.width) + "x" + Math.round(r.height) + " at " + Math.round(r.top));
    } else {
      window.__mskbDebug("paper-graph: NOT FOUND in DOM");
    }
    window.addEventListener("error", function (event) {
      var msg = (event && event.error && event.error.message) || (event && event.message) || "Unknown script error";
      var stack = (event && event.error && event.error.stack) || "";
      window.__mskbDebug("ERROR: " + String(msg) + "\n" + String(stack));
      if (window.console && console.error) console.error("[explorer-boot]", msg, stack);
    });
    window.addEventListener("unhandledrejection", function (event) {
      var reason = event && event.reason;
      var msg = (reason && reason.message) || String(reason || "Unknown rejection");
      window.__mskbDebug("REJECTION: " + String(msg));
      if (window.console && console.error) console.error("[explorer-boot-rejection]", reason);
    });
  } catch (e) {
    if (window.console && console.error) console.error("[explorer-boot-diag]", e);
  }
})();
(() => {
  const graphEl = document.getElementById("paper-graph");
  const detailsEl = document.getElementById("paper-details");
  const parentEl = document.getElementById("parent-links");
  const childEl = document.getElementById("child-links");
  const relatedEl = document.getElementById("related-links");
  const directSearchModeEl = document.getElementById("direct-search-mode");
  const directSearchInputEl = document.getElementById("direct-search-input");
  const directSearchRunEl = document.getElementById("direct-search-run");
  const directSearchResultsEl = document.getElementById("direct-search-results");
  const ideaInputEl = document.getElementById("idea-input");
  const ideaResultsEl = document.getElementById("idea-results");
  const journeySelectedEl = document.getElementById("journey-selected");
  const journeyResultsEl = document.getElementById("journey-results");
  const journeyGenerateEl = document.getElementById("journey-generate");
  const journeyClearEl = document.getElementById("journey-clear");
  const ideaRunEl = document.getElementById("idea-run");
  const relayoutEl = document.getElementById("graph-relayout");
  const nodeDragToggleEl = document.getElementById("node-drag-toggle");
  const graphStatusEl = document.getElementById("graph-status");
  const coreMetricEl = document.getElementById("core-metric");
  const difficultyMaxEl = document.getElementById("difficulty-max");
  const minInDegreeEl = document.getElementById("min-in-degree");
  const minOutDegreeEl = document.getElementById("min-out-degree");
  const minKcoreEl = document.getElementById("min-kcore");
  const corePctEl = document.getElementById("core-percentile");
  const corePctValueEl = document.getElementById("core-percentile-value");
  const coreApplyEl = document.getElementById("core-apply");
  const loadFullCorpusEl = document.getElementById("load-full-corpus");
  const requireAbstractEl = document.getElementById("require-abstract");
  const presetUndergradEl = document.getElementById("preset-undergrad");
  const presetBalancedEl = document.getElementById("preset-balanced");
  const presetGradEl = document.getElementById("preset-grad");
  const isMobileView = window.matchMedia("(max-width: 1000px), (pointer: coarse)").matches;
  const fullDataUrl = "../assets/explorer_graph.json";
  const fullDetailsUrl = "../assets/explorer_details.json";
  const initialPayloadCandidates = isMobileView
    ? [
        { url: "../assets/explorer_graph_mobile.json", detailsUrl: "../assets/explorer_details_mobile.json", mode: "mobile", label: "mobile" },
        { url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" },
      ]
    : [
        { url: "../assets/explorer_graph_lite.json", detailsUrl: "../assets/explorer_details_lite.json", mode: "lite", label: "lite" },
        { url: "../assets/explorer_graph_mobile.json", detailsUrl: "../assets/explorer_details_mobile.json", mode: "mobile", label: "mobile" },
        { url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" },
      ];
  const categoryColors = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
  };
  const stopWords = new Set([
    "a","an","the","and","or","but","for","with","from","that","this","into","about","using","through","between",
    "their","they","are","was","were","how","what","when","where","which","who","our","your","you","can","could",
    "should","would","will","may","might","have","has","had","been","being","its","it's","it","as","at","by","to",
    "in","on","of","if","than","then","also","we","i","he","she","them","these","those","there","here","do","does",
    "did","done","not","no","yes","up","down","over","under","new","study","paper"
  ]);
  const FIELD_WEIGHTS = {
    title: 3.4,
    abstract: 2.2,
    summary: 1.6,
    topic: 1.3,
    why: 1.0,
  };
  const QUERY_EXPANSIONS = {
    ms: ["multiple", "sclerosis", "demyelination", "neuroinflammation"],
    rrms: ["relapsing", "remitting", "multiple", "sclerosis"],
    spms: ["secondary", "progressive", "multiple", "sclerosis"],
    ppms: ["primary", "progressive", "multiple", "sclerosis"],
    dmt: ["disease", "modifying", "therapy", "therapeutic"],
    dmts: ["disease", "modifying", "therapy", "therapeutic"],
    nfl: ["neurofilament", "biomarker"],
    ocb: ["oligoclonal", "bands", "csf"],
    ocbcsf: ["oligoclonal", "bands", "csf"],
    mri: ["magnetic", "resonance", "imaging", "lesion"],
    oct: ["optical", "coherence", "tomography", "retinal"],
    btk: ["brutons", "tyrosine", "kinase", "inhibitor"],
    eae: ["experimental", "autoimmune", "encephalomyelitis", "model"],
    ebv: ["epstein", "barr", "virus"],
    bbb: ["blood", "brain", "barrier"],
    gwas: ["genome", "wide", "association", "genetic"],
    cd20: ["b", "cell", "depletion", "ocrelizumab", "rituximab"],
  };

  let renderer = null;
  let sigmaGraph = null;
  let selectedNodeId = null;
  let rawNodes = [];
  let rawEdges = [];
  let visibleNodes = [];
  let visibleEdges = [];
  let nodeById = new Map();
  let undirected = new Map();
  let incoming = new Map();
  let outgoing = new Map();
  let kcoreThresholds = { lowMax: 0, midMax: 0 };
  let selectedIncoming = new Set();
  let selectedOutgoing = new Set();
  let selectedIncident = new Set();
  let dragEnabled = false;
  let draggingNode = null;
  let payloadMode = isMobileView ? "mobile" : "lite";
  let detailsUrlActive = initialPayloadCandidates[0].detailsUrl;
  let isLoadingCorpus = false;
  let detailsById = null;
  let detailsLoadPromise = null;
  let detailsLoadError = "";
  const loadStats = {
    payloadBytes: 0,
    fetchMs: 0,
    parseMs: 0,
    detailsBytes: 0,
    detailsFetchMs: 0,
    detailsParseMs: 0,
  };
  let journeySelection = [];
  let paperRankMap = new Map();
  let paperAgeRankMap = new Map();
  let authorStatsMap = new Map();
  let searchIndexCache = { signature: "", index: null };

  function setGraphStatus(text, strong = false) {
    if (!graphStatusEl) return;
    const safe = escapeHtml(String(text || ""));
    graphStatusEl.innerHTML = strong ? `<p><strong>${safe}</strong></p>` : `<p><em>${safe}</em></p>`;
  }

  async function fetchTextWithTimeout(url, timeoutMs = 20000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error("timeout")), timeoutMs);
    try {
      const response = await fetch(url, { signal: controller.signal });
      return response;
    } finally {
      clearTimeout(timer);
    }
  }

  function showFatalOverlay(label, detail) {
    try {
      const safeLabel = escapeHtml(String(label || "Explorer error"));
      const safeDetail = escapeHtml(String(detail || ""));
      if (graphEl) {
        graphEl.innerHTML = `
          <div style="padding:1.25rem 1.5rem;font-family:ui-monospace,Menlo,Consolas,monospace;color:#7a1f1f;background:#fff5f5;border:2px solid #d33;border-radius:12px;height:100%;overflow:auto;white-space:pre-wrap;">
            <strong style="font-size:1.05rem;display:block;margin-bottom:0.4rem;">${safeLabel}</strong>
            <div>${safeDetail}</div>
            <div style="margin-top:0.6rem;color:#555;font-size:0.85rem;">See browser DevTools console for the full stack trace.</div>
          </div>`;
      }
      setGraphStatus(`${label}: ${detail}`, true);
      if (typeof console !== "undefined" && console.error) {
        console.error("[explorer]", label, detail);
      }
    } catch (_) { /* swallow */ }
  }

  window.addEventListener("error", (event) => {
    const msg = event?.error?.message || event?.message || "Unknown script error";
    const stack = event?.error?.stack || "";
    showFatalOverlay("Explorer runtime error", `${msg}\n${stack}`);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event?.reason;
    const msg = typeof reason === "string" ? reason : (reason?.message || String(reason || "Unknown promise rejection"));
    const stack = reason && reason.stack ? `\n${reason.stack}` : "";
    showFatalOverlay("Explorer async error", `${msg}${stack}`);
  });

  function escapeHtml(text) {
    return (text || "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function cleanNarrativeText(text) {
    let t = String(text || "").trim();
    if (!t) return "";
    t = t.replace(/\bnan\b/gi, "").replace(/\s{2,}/g, " ").trim();
    const genericPatterns = [
      /^this\s+\d{4}(?:\.0)?\s+paper\s+in\s+.+?contributes\s+to\s+our\s+understanding\s+of\s+multiple\s+sclerosis\.?$/i,
      /^this\s+paper\s+in\s+.+?contributes\s+to\s+our\s+understanding\s+of\s+multiple\s+sclerosis\.?$/i,
    ];
    if (genericPatterns.some((rx) => rx.test(t))) {
      return "";
    }
    return t;
  }

  function formatMB(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "n/a";
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function normalizeNode(node) {
    const n = { ...(node || {}) };
    n.id = String(n.id || "");
    n.title = String(n.title || "Untitled");
    n.year = Number.isFinite(Number(n.year)) ? Math.trunc(Number(n.year)) : null;
    n.source_url = String(n.source_url || "").trim();
    n.doi = String(n.doi || "").trim();
    n.first_author = String(n.first_author || "").trim();
    n.venue = String(n.venue || "").trim();
    n.topic_label = String(n.topic_label || "").trim();
    n.importance = Number(n.importance || 0);
    n.age_normalized_importance = Number(n.age_normalized_importance || 0);
    n.rank_age_normalized_importance = Number(n.rank_age_normalized_importance || 0);
    n.citations_per_year = Number(n.citations_per_year || 0);
    n.paper_age_years = Number(n.paper_age_years || 0);
    n.citation_count = Math.max(0, Math.trunc(Number(n.citation_count || 0)));
    n.pagerank = Number(n.pagerank || 0);
    n.kcore = Math.max(0, Math.trunc(Number(n.kcore || 0)));
    n.in_degree = Math.max(0, Math.trunc(Number(n.in_degree || 0)));
    n.out_degree = Math.max(0, Math.trunc(Number(n.out_degree || 0)));
    n.rank_pagerank = Number(n.rank_pagerank || 0);
    n.rank_kcore = Number(n.rank_kcore || 0);
    n.rank_in_degree = Number(n.rank_in_degree || 0);
    n.core_score = Number(n.core_score || 0);
    n.difficulty = Math.max(1, Math.min(5, Math.trunc(Number(n.difficulty || 3))));
    n.has_abstract = Boolean(n.has_abstract);
    n.tier = String(n.tier || "");
    n.evidence_type = String(n.evidence_type || "other");
    n.evidence_strength = Math.max(1, Math.min(5, Math.trunc(Number(n.evidence_strength || 2))));
    n.abstract = String(n.abstract || "");
    n.summary = String(n.summary || "");
    n.summary_source = String(n.summary_source || "");
    n.why_it_matters = String(n.why_it_matters || "");
    n.key_takeaways = Array.isArray(n.key_takeaways) ? n.key_takeaways : [];
    n.summary_generated_at_utc = String(n.summary_generated_at_utc || "");
    n.distill_method = String(n.distill_method || "");
    n.summary_certainty_score = Number(n.summary_certainty_score || 0);
    n.summary_certainty_label = String(n.summary_certainty_label || "");
    n.summary_disclaimer = String(n.summary_disclaimer || "");
    n.faithfulness_overlap = Number(n.faithfulness_overlap || 0);
    n.source_text_hash = String(n.source_text_hash || "");
    n.source_text_chars = Math.max(0, Math.trunc(Number(n.source_text_chars || 0)));
    n._detailsLoaded = Boolean(n._detailsLoaded);
    return n;
  }

  function decodeGraphPayload(payload) {
    if (payload && Array.isArray(payload.node_fields) && Array.isArray(payload.nodes)) {
      const fields = payload.node_fields;
      const nodes = payload.nodes.map((row) => {
        const obj = {};
        fields.forEach((field, idx) => {
          obj[field] = Array.isArray(row) ? row[idx] : undefined;
        });
        return normalizeNode(obj);
      });
      let edges = [];
      if (Array.isArray(payload.edges)) {
        if (payload.edges_are_indexed) {
          edges = payload.edges
            .map((entry) => {
              if (!Array.isArray(entry) || entry.length < 2) return null;
              const sourceNode = nodes[Number(entry[0])];
              const targetNode = nodes[Number(entry[1])];
              if (!sourceNode || !targetNode || !sourceNode.id || !targetNode.id || sourceNode.id === targetNode.id) {
                return null;
              }
              return { source: sourceNode.id, target: targetNode.id, type: "CITES" };
            })
            .filter(Boolean);
        } else {
          edges = payload.edges
            .map((entry) => {
              if (!entry) return null;
              if (Array.isArray(entry) && entry.length >= 2) {
                return { source: String(entry[0] || ""), target: String(entry[1] || ""), type: "CITES" };
              }
              if (typeof entry === "object") {
                return {
                  source: String(entry.source || ""),
                  target: String(entry.target || ""),
                  type: String(entry.type || "CITES"),
                };
              }
              return null;
            })
            .filter((e) => e && e.source && e.target && e.source !== e.target);
        }
      }
      return { nodes, edges };
    }

    const nodes = (payload?.nodes || []).map((node) => normalizeNode(node));
    const edges = (payload?.edges || [])
      .map((edge) => ({
        source: String(edge?.source || ""),
        target: String(edge?.target || ""),
        type: String(edge?.type || "CITES"),
      }))
      .filter((e) => e.source && e.target && e.source !== e.target);
    return { nodes, edges };
  }

  function decodeDetailsPayload(payload) {
    const map = new Map();
    if (payload && Array.isArray(payload.fields) && Array.isArray(payload.rows)) {
      const fields = payload.fields;
      payload.rows.forEach((row) => {
        if (!Array.isArray(row)) return;
        const obj = {};
        fields.forEach((field, idx) => {
          obj[field] = row[idx];
        });
        const id = String(obj.id || "");
        if (!id) return;
        map.set(id, {
          abstract: String(obj.abstract || ""),
          summary: String(obj.summary || ""),
          summary_source: String(obj.summary_source || ""),
          why_it_matters: String(obj.why_it_matters || ""),
          key_takeaways: Array.isArray(obj.key_takeaways) ? obj.key_takeaways : [],
          summary_generated_at_utc: String(obj.summary_generated_at_utc || ""),
          distill_method: String(obj.distill_method || ""),
          summary_certainty_score: Number(obj.summary_certainty_score || 0),
          summary_certainty_label: String(obj.summary_certainty_label || ""),
          summary_disclaimer: String(obj.summary_disclaimer || ""),
          faithfulness_overlap: Number(obj.faithfulness_overlap || 0),
          source_text_hash: String(obj.source_text_hash || ""),
          source_text_chars: Number(obj.source_text_chars || 0),
        });
      });
      return map;
    }
    const detailsObj = (payload && typeof payload.details === "object") ? payload.details : {};
    Object.entries(detailsObj || {}).forEach(([id, obj]) => {
      if (!id) return;
      map.set(String(id), {
        abstract: String(obj?.abstract || ""),
        summary: String(obj?.summary || ""),
        summary_source: String(obj?.summary_source || ""),
        why_it_matters: String(obj?.why_it_matters || ""),
        key_takeaways: Array.isArray(obj?.key_takeaways) ? obj.key_takeaways : [],
        summary_generated_at_utc: String(obj?.summary_generated_at_utc || ""),
        distill_method: String(obj?.distill_method || ""),
        summary_certainty_score: Number(obj?.summary_certainty_score || 0),
        summary_certainty_label: String(obj?.summary_certainty_label || ""),
        summary_disclaimer: String(obj?.summary_disclaimer || ""),
        faithfulness_overlap: Number(obj?.faithfulness_overlap || 0),
        source_text_hash: String(obj?.source_text_hash || ""),
        source_text_chars: Number(obj?.source_text_chars || 0),
      });
    });
    return map;
  }

  function mergeNodeDetails(detailMap) {
    detailsById = detailMap instanceof Map ? detailMap : new Map();
    rawNodes = rawNodes.map((node) => {
      const details = detailsById.get(node.id);
      if (!details) {
        return { ...node, _detailsLoaded: true };
      }
      return {
        ...node,
        abstract: String(details.abstract || ""),
        summary: String(details.summary || ""),
        summary_source: String(details.summary_source || ""),
        why_it_matters: String(details.why_it_matters || ""),
        key_takeaways: Array.isArray(details.key_takeaways) ? details.key_takeaways : [],
        summary_generated_at_utc: String(details.summary_generated_at_utc || ""),
        distill_method: String(details.distill_method || ""),
        summary_certainty_score: Number(details.summary_certainty_score || 0),
        summary_certainty_label: String(details.summary_certainty_label || ""),
        summary_disclaimer: String(details.summary_disclaimer || ""),
        faithfulness_overlap: Number(details.faithfulness_overlap || 0),
        source_text_hash: String(details.source_text_hash || ""),
        source_text_chars: Number(details.source_text_chars || 0),
        _detailsLoaded: true,
      };
    });
    searchIndexCache = { signature: "", index: null };
  }

  function ensureDetailsLoaded() {
    if (detailsById instanceof Map) return Promise.resolve(detailsById);
    if (detailsLoadPromise) return detailsLoadPromise;
    const detailsStart = performance.now();
    detailsLoadPromise = fetch(detailsUrlActive)
      .then(async (r) => {
        const text = await r.text();
        const parseStart = performance.now();
        loadStats.detailsFetchMs = parseStart - detailsStart;
        loadStats.detailsBytes = Number(r.headers.get("content-length")) || (text.length * 2);
        const payload = JSON.parse(text);
        loadStats.detailsParseMs = performance.now() - parseStart;
        const detailMap = decodeDetailsPayload(payload);
        mergeNodeDetails(detailMap);
        return detailsById;
      })
      .catch((err) => {
        detailsLoadError = String(err || "unknown error");
        detailsById = new Map();
        rawNodes = rawNodes.map((node) => ({ ...node, _detailsLoaded: true }));
        return detailsById;
      })
      .finally(() => {
        detailsLoadPromise = null;
      });
    return detailsLoadPromise;
  }

  function cleanDoi(doi) {
    const value = String(doi || "").trim();
    if (!value) return "";
    return value.replace(/^https?:\/\/doi\.org\//i, "");
  }

  function citationPlaintextForNode(node) {
    const author = String(node?.first_author || "").trim() || "Unknown author";
    const year = Number.isFinite(Number(node?.year)) ? Math.trunc(Number(node.year)) : "n.d.";
    const title = String(node?.title || "Untitled").trim();
    const venue = String(node?.venue || "").trim();
    const source = String(node?.source_url || "").trim();
    const pieces = [`${author}. (${year}). ${title}.`];
    if (venue) pieces.push(`${venue}.`);
    if (source) pieces.push(source);
    return pieces.join(" ").trim();
  }

  function citationBibtexForNode(node) {
    const id = String(node?.id || "paper").replace(/[^a-zA-Z0-9]/g, "").slice(0, 12);
    const year = Number.isFinite(Number(node?.year)) ? String(Math.trunc(Number(node.year))) : "0000";
    const key = `mskb_${id}_${year}`;
    const esc = (s) => String(s || "").replace(/\\/g, "\\\\").replace(/\{/g, "\\{").replace(/\}/g, "\\}");
    const lines = [
      `@article{${key},`,
      `  title = {${esc(node?.title || "Untitled")}},`,
      `  author = {${esc(node?.first_author || "Unknown")}},`,
      `  year = {${year}},`,
    ];
    if (node?.venue) lines.push(`  journal = {${esc(node.venue)}},`);
    const doi = cleanDoi(node?.doi || "");
    if (doi) lines.push(`  doi = {${esc(doi)}},`);
    if (node?.source_url) lines.push(`  url = {${esc(node.source_url)}},`);
    lines.push("}");
    return lines.join("\n");
  }

  function normalizeText(text) {
    return (text || "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function stemToken(token) {
    let t = token;
    if (t.length > 6 && t.endsWith("ation")) t = t.slice(0, -5);
    else if (t.length > 5 && t.endsWith("ing")) t = t.slice(0, -3);
    else if (t.length > 4 && t.endsWith("ed")) t = t.slice(0, -2);
    else if (t.length > 4 && t.endsWith("ly")) t = t.slice(0, -2);
    else if (t.length > 5 && t.endsWith("ment")) t = t.slice(0, -4);
    else if (t.length > 4 && t.endsWith("ies")) t = `${t.slice(0, -3)}y`;
    else if (t.length > 4 && t.endsWith("s")) t = t.slice(0, -1);
    return t;
  }

  function tokenize(text) {
    return normalizeText(text)
      .split(/\s+/)
      .filter(t => t && t.length > 1 && !stopWords.has(t))
      .map(stemToken)
      .filter(t => t.length > 1 && !stopWords.has(t));
  }

  function tokenCounts(tokens) {
    const m = new Map();
    for (const t of tokens) {
      m.set(t, (m.get(t) || 0) + 1);
    }
    return m;
  }

  function nodeSetSignature(nodes) {
    if (!nodes || !nodes.length) return "0";
    const first = nodes[0]?.id || "";
    const last = nodes[nodes.length - 1]?.id || "";
    return `${nodes.length}:${first}:${last}`;
  }

  function prepareSearchIndex(nodes) {
    const signature = nodeSetSignature(nodes);
    if (searchIndexCache.signature === signature && searchIndexCache.index) {
      return searchIndexCache.index;
    }
    const docs = [];
    const totals = { title: 0, abstract: 0, summary: 0, topic: 0, why: 0 };
    for (const node of nodes) {
      const titleNorm = normalizeText(node.title || "");
      const abstractNorm = normalizeText(node.abstract || "");
      const summaryNorm = normalizeText(node.summary || "");
      const topicNorm = normalizeText(node.topic_label || "");
      const whyNorm = normalizeText(node.why_it_matters || "");

      const fieldTokens = {
        title: tokenize(titleNorm),
        abstract: tokenize(abstractNorm),
        summary: tokenize(summaryNorm),
        topic: tokenize(topicNorm),
        why: tokenize(whyNorm),
      };

      totals.title += Math.max(1, fieldTokens.title.length);
      totals.abstract += Math.max(1, fieldTokens.abstract.length);
      totals.summary += Math.max(1, fieldTokens.summary.length);
      totals.topic += Math.max(1, fieldTokens.topic.length);
      totals.why += Math.max(1, fieldTokens.why.length);

      const fieldCounts = {
        title: tokenCounts(fieldTokens.title),
        abstract: tokenCounts(fieldTokens.abstract),
        summary: tokenCounts(fieldTokens.summary),
        topic: tokenCounts(fieldTokens.topic),
        why: tokenCounts(fieldTokens.why),
      };
      const allTerms = new Set([
        ...fieldCounts.title.keys(),
        ...fieldCounts.abstract.keys(),
        ...fieldCounts.summary.keys(),
        ...fieldCounts.topic.keys(),
        ...fieldCounts.why.keys(),
      ]);
      docs.push({
        node,
        allTerms,
        combinedNorm: `${titleNorm} ${abstractNorm} ${summaryNorm} ${topicNorm} ${whyNorm}`.trim(),
        titleNorm,
        fieldCounts,
        fieldLengths: {
          title: Math.max(1, fieldTokens.title.length),
          abstract: Math.max(1, fieldTokens.abstract.length),
          summary: Math.max(1, fieldTokens.summary.length),
          topic: Math.max(1, fieldTokens.topic.length),
          why: Math.max(1, fieldTokens.why.length),
        },
      });
    }

    const n = Math.max(1, docs.length);
    const index = {
      docs,
      avgLens: {
        title: totals.title / n,
        abstract: totals.abstract / n,
        summary: totals.summary / n,
        topic: totals.topic / n,
        why: totals.why / n,
      },
    };
    searchIndexCache = { signature, index };
    return index;
  }

  function expandQueryTokens(tokens, queryNorm) {
    const expanded = [...tokens];
    const raw = queryNorm.split(/\s+/).filter(Boolean);
    for (const t of raw) {
      if (QUERY_EXPANSIONS[t]) {
        expanded.push(...QUERY_EXPANSIONS[t]);
      }
    }
    return expanded.map(stemToken).filter(t => t.length > 1 && !stopWords.has(t));
  }

  function buildQueryModel(queryText, index) {
    const queryNorm = normalizeText(queryText);
    const rawTokens = tokenize(queryNorm);
    const terms = Array.from(new Set(expandQueryTokens(rawTokens, queryNorm)));
    const df = new Map();
    for (const term of terms) df.set(term, 0);
    for (const doc of index.docs) {
      for (const term of terms) {
        if (doc.allTerms.has(term)) df.set(term, (df.get(term) || 0) + 1);
      }
    }
    const totalDocs = Math.max(1, index.docs.length);
    const idf = new Map();
    for (const term of terms) {
      const d = df.get(term) || 0;
      idf.set(term, Math.log(1 + (totalDocs - d + 0.5) / (d + 0.5)));
    }

    const bigrams = [];
    for (let i = 0; i < rawTokens.length - 1; i += 1) {
      bigrams.push(`${rawTokens[i]} ${rawTokens[i + 1]}`);
    }
    return { queryNorm, rawTokens, terms, idf, bigrams };
  }

  function bm25(tf, len, avgLen, idf, k1 = 1.35, b = 0.72) {
    if (!tf) return 0;
    const denom = tf + k1 * (1 - b + b * (len / Math.max(1e-9, avgLen)));
    return idf * ((tf * (k1 + 1)) / denom);
  }

  function colorFor(node) {
    if (!node || !node.topic_label) return "#4c78a8";
    const key = (node.topic_label || "").toLowerCase();
    for (const [cat, color] of Object.entries(categoryColors)) {
      if (key.includes(cat.replaceAll("_", " ").split(" ")[0])) return color;
    }
    return "#4c78a8";
  }

  function nodeSizeFromCitations(node) {
    const cites = Math.max(0, Number(node?.citation_count || 0));
    return Math.max(4, Math.log1p(cites) * 3.2);
  }

  function quantile(sorted, q) {
    if (!sorted.length) return 0;
    const pos = (sorted.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    if (sorted[base + 1] !== undefined) {
      return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
    }
    return sorted[base];
  }

  function computeKcoreThresholds(nodes) {
    const values = nodes
      .map((n) => Number(n.kcore || 0))
      .filter((v) => Number.isFinite(v))
      .sort((a, b) => a - b);
    if (!values.length) return { lowMax: 0, midMax: 0 };
    return {
      lowMax: quantile(values, 0.33),
      midMax: quantile(values, 0.66),
    };
  }

  function kcoreTier(node) {
    const v = Number(node?.kcore || 0);
    if (v <= kcoreThresholds.lowMax) return "low";
    if (v <= kcoreThresholds.midMax) return "mid";
    return "high";
  }

  function kcoreBorderColor(node) {
    const tier = kcoreTier(node);
    if (tier === "high") return "#1c9b43";
    if (tier === "mid") return "#d4a72c";
    return "#c84e4e";
  }

  function buildBaseNodeStyle(node) {
    const tierColor = kcoreBorderColor(node);
    return {
      id: node.id,
      label: (node.title || "Untitled").slice(0, 55),
      title: node.title || "Untitled",
      size: nodeSizeFromCitations(node),
      color: tierColor,
      topicColor: colorFor(node),
      kcoreColor: tierColor,
    };
  }

  function getSigmaCtor() {
    return window.Sigma || (window.sigma && (window.sigma.Sigma || window.sigma.default)) || null;
  }

  function getGraphCtor() {
    if (window.graphology && window.graphology.DirectedGraph) return window.graphology.DirectedGraph;
    if (window.graphology && window.graphology.Graph) return window.graphology.Graph;
    return null;
  }

  function killRenderer() {
    if (renderer && typeof renderer.kill === "function") {
      renderer.kill();
    }
    renderer = null;
    sigmaGraph = null;
  }

  function refreshNodeDragToggleLabel() {
    if (!nodeDragToggleEl) return;
    if (isMobileView) {
      nodeDragToggleEl.textContent = "Node Drag (desktop only)";
      nodeDragToggleEl.disabled = true;
      return;
    }
    nodeDragToggleEl.disabled = false;
    nodeDragToggleEl.textContent = dragEnabled ? "Disable Node Drag" : "Enable Node Drag";
  }

  function refreshFullCorpusButton() {
    if (!loadFullCorpusEl) return;
    if (isMobileView) {
      loadFullCorpusEl.disabled = true;
      loadFullCorpusEl.textContent = "Full Corpus (desktop only)";
      return;
    }
    if (payloadMode === "full") {
      loadFullCorpusEl.disabled = true;
      loadFullCorpusEl.textContent = "Full Corpus Loaded";
      return;
    }
    loadFullCorpusEl.disabled = isLoadingCorpus;
    loadFullCorpusEl.textContent = isLoadingCorpus ? "Loading Full Corpus..." : "Load Full Corpus";
  }

  function communityKey(node) {
    const tid = Number(node?.topic_id);
    if (Number.isFinite(tid)) return `topic:${Math.trunc(tid)}`;
    const label = normalizeText(node?.topic_label || "");
    return label ? `label:${label}` : "unassigned";
  }

  function buildCommunityPositions(nodes) {
    const groups = new Map();
    nodes.forEach((n) => {
      const key = communityKey(n);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    });

    const ordered = Array.from(groups.entries()).sort((a, b) => {
      const sizeCmp = b[1].length - a[1].length;
      if (sizeCmp !== 0) return sizeCmp;
      return String(a[0]).localeCompare(String(b[0]));
    });
    if (!ordered.length) return new Map();

    const cols = Math.max(1, Math.ceil(Math.sqrt(ordered.length)));
    const rows = Math.max(1, Math.ceil(ordered.length / cols));
    const spacingX = 620;
    const spacingY = 540;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const positions = new Map();

    ordered.forEach(([_, members], idx) => {
      const col = idx % cols;
      const row = Math.floor(idx / cols);
      const cx = (col - (cols - 1) / 2) * spacingX;
      const cy = (row - (rows - 1) / 2) * spacingY;
      members.sort((a, b) => ((b.citation_count || 0) - (a.citation_count || 0)) || String(a.id).localeCompare(String(b.id)));
      const radialStep = Math.max(18, Math.min(32, 16 + Math.sqrt(members.length)));
      members.forEach((node, i) => {
        if (i === 0) {
          positions.set(node.id, { x: cx, y: cy });
          return;
        }
        const radius = Math.sqrt(i) * radialStep;
        const angle = i * goldenAngle;
        positions.set(node.id, {
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });
    });
    return positions;
  }

  function buildRankIndexes(nodes) {
    const rankedPapers = [...nodes].sort((a, b) => ((b.core_score || 0) - (a.core_score || 0)) || ((b.importance || 0) - (a.importance || 0)));
    paperRankMap = new Map();
    rankedPapers.forEach((n, idx) => paperRankMap.set(n.id, idx + 1));
    const rankedAgeNorm = [...nodes].sort((a, b) => ((b.age_normalized_importance || 0) - (a.age_normalized_importance || 0)) || ((b.importance || 0) - (a.importance || 0)));
    paperAgeRankMap = new Map();
    rankedAgeNorm.forEach((n, idx) => paperAgeRankMap.set(n.id, idx + 1));

    const tempAuthors = new Map();
    nodes.forEach((n) => {
      const name = String(n.first_author || "").trim();
      if (!name) return;
      if (!tempAuthors.has(name)) {
        tempAuthors.set(name, { name, papers: 0, citations: 0, coreScore: 0, topPaperId: n.id, topPaperImportance: Number(n.importance || 0) });
      }
      const a = tempAuthors.get(name);
      a.papers += 1;
      a.citations += Number(n.citation_count || 0);
      a.coreScore += Number(n.core_score || 0);
      const imp = Number(n.importance || 0);
      if (imp > a.topPaperImportance) {
        a.topPaperImportance = imp;
        a.topPaperId = n.id;
      }
    });

    const authors = Array.from(tempAuthors.values()).map((a) => ({
      ...a,
      avgCoreScore: a.papers ? (a.coreScore / a.papers) : 0,
    }));
    authors.sort((a, b) => {
      const sa = Math.log1p(a.citations) * 0.62 + a.avgCoreScore * 2.4 + a.papers * 0.24;
      const sb = Math.log1p(b.citations) * 0.62 + b.avgCoreScore * 2.4 + b.papers * 0.24;
      return sb - sa || a.name.localeCompare(b.name);
    });
    authorStatsMap = new Map();
    authors.forEach((a, idx) => {
      authorStatsMap.set(a.name, { ...a, rank: idx + 1, score: Math.log1p(a.citations) * 0.62 + a.avgCoreScore * 2.4 + a.papers * 0.24 });
    });
  }

  function buildSigmaGraph(positionById) {
    const SigmaCtor = getSigmaCtor();
    const GraphCtor = getGraphCtor();
    if (!SigmaCtor || !GraphCtor) {
      const detail = `Sigma=${typeof window.Sigma}, sigma=${typeof window.sigma}, graphology=${typeof window.graphology}. Vendor scripts at /javascripts/vendor/ may have failed to load.`;
      showFatalOverlay("Explorer renderer failed to initialize", detail);
      return false;
    }

    try {
      killRenderer();
      sigmaGraph = (window.graphology && GraphCtor === window.graphology.Graph)
        ? new GraphCtor({ type: "directed", multi: false })
        : new GraphCtor();

      visibleNodes.forEach((n) => {
        const style = buildBaseNodeStyle(n);
        const pos = positionById.get(n.id) || { x: (Math.random() - 0.5) * 2, y: (Math.random() - 0.5) * 2 };
        sigmaGraph.addNode(n.id, {
          label: style.label,
          x: Number(pos.x) || 0,
          y: Number(pos.y) || 0,
          size: Math.max(1.5, Number(style.size) || 2),
          color: style.color,
          topicColor: style.topicColor,
          kcoreColor: style.kcoreColor,
        });
      });

      visibleEdges.forEach((e, idx) => {
        if (!sigmaGraph.hasNode(e.source) || !sigmaGraph.hasNode(e.target)) return;
        const key = `${e.source}->${e.target}-${idx}`;
        if (sigmaGraph.hasEdge(key)) return;
        sigmaGraph.addDirectedEdgeWithKey(key, e.source, e.target, {
          color: "rgba(125,138,150,0.18)",
          size: 1.0,
        });
      });

      if (window.__mskbDebug) {
        var rr2 = graphEl.getBoundingClientRect();
        window.__mskbDebug("buildSigmaGraph: ctor=" + (typeof SigmaCtor) + " nodes=" + sigmaGraph.order + " edges=" + sigmaGraph.size + " container=" + Math.round(rr2.width) + "x" + Math.round(rr2.height));
      }
      renderer = new SigmaCtor(sigmaGraph, graphEl, {
        renderLabels: true,
        labelRenderedSizeThreshold: 14,
        defaultEdgeType: "arrow",
        allowInvalidContainer: true,
      });

      renderer.setSetting("nodeReducer", (node, data) => {
        const reduced = { ...data };

        if (!selectedNodeId) {
          reduced.color = data.kcoreColor || data.color;
          reduced.size = data.size;
          return reduced;
        }

        if (node === selectedNodeId) {
          reduced.color = "#0a3f5c";
          reduced.size = (data.size || 3) * 1.4;
          return reduced;
        }
        if (selectedIncoming.has(node) && selectedOutgoing.has(node)) {
          reduced.color = "#b97e1d";
          reduced.size = (data.size || 3) * 1.18;
          return reduced;
        }
        if (selectedIncoming.has(node)) {
          reduced.color = "#25a16d";
          reduced.size = (data.size || 3) * 1.12;
          return reduced;
        }
        if (selectedOutgoing.has(node)) {
          reduced.color = "#cf5b2f";
          reduced.size = (data.size || 3) * 1.12;
          return reduced;
        }
        reduced.color = "rgba(150,160,170,0.18)";
        reduced.label = "";
        reduced.size = Math.max(1.2, (data.size || 2) * 0.8);
        return reduced;
      });

      renderer.setSetting("edgeReducer", (edge, data) => {
        const reduced = { ...data, color: "rgba(125,138,150,0.18)", size: 1.0 };
        if (!selectedNodeId) return reduced;

        const source = sigmaGraph.source(edge);
        const target = sigmaGraph.target(edge);

        if (source === selectedNodeId) return { ...reduced, color: "#cf5b2f", size: 2.4 };
        if (target === selectedNodeId) return { ...reduced, color: "#25a16d", size: 2.4 };
        if (selectedIncident.has(source) && selectedIncident.has(target)) return { ...reduced, color: "rgba(76,111,138,0.42)", size: 1.2 };
        return { ...reduced, color: "rgba(154,166,178,0.06)", size: 0.6 };
      });

      renderer.on("clickNode", ({ node }) => {
        if (draggingNode) return;
        focusNode(node);
      });
      renderer.on("clickStage", () => {
        selectedNodeId = null;
        styleSelectedSubgraph(null);
      });

      const captor = renderer.getMouseCaptor && renderer.getMouseCaptor();
      if (captor) {
        renderer.on("downNode", ({ node, event }) => {
          if (!dragEnabled || isMobileView) return;
          draggingNode = node;
          if (event && typeof event.preventSigmaDefault === "function") {
            event.preventSigmaDefault();
          }
          if (event && event.original && typeof event.original.preventDefault === "function") {
            event.original.preventDefault();
          }
        });

        captor.on("mousemovebody", (e) => {
          if (!dragEnabled || !draggingNode || !renderer || !sigmaGraph || !sigmaGraph.hasNode(draggingNode)) return;
          const coords = renderer.viewportToGraph ? renderer.viewportToGraph({ x: e.x, y: e.y }) : null;
          if (!coords) return;
          sigmaGraph.setNodeAttribute(draggingNode, "x", coords.x);
          sigmaGraph.setNodeAttribute(draggingNode, "y", coords.y);
          renderer.refresh();
          if (typeof e.preventSigmaDefault === "function") {
            e.preventSigmaDefault();
          }
        });

        const stopDrag = () => {
          draggingNode = null;
        };
        captor.on("mouseup", stopDrag);
        captor.on("mousedown", () => {
          if (!dragEnabled) draggingNode = null;
        });
        captor.on("mouseleave", stopDrag);
      }

      return true;
    } catch (err) {
      showFatalOverlay("Explorer renderer crashed during graph construction", `${err && err.message ? err.message : err}\n${err && err.stack ? err.stack : ""}`);
      return false;
    }
  }

  function journeyButtonLabel(id) {
    return journeySelection.includes(id) ? "Remove" : "Add";
  }

  function renderActionButtons(node) {
    return `<button data-focus="${node.id}">Focus</button> <button data-journey-toggle="${node.id}">${journeyButtonLabel(node.id)}</button>`;
  }

  async function runDirectSearch() {
    const mode = String(directSearchModeEl.value || "all");
    const qRaw = String(directSearchInputEl.value || "").trim();
    const q = normalizeText(qRaw);
    if (!q) {
      directSearchResultsEl.innerHTML = "<p>Enter a query and choose a field scope.</p>";
      return;
    }
    if ((mode === "abstract" || mode === "all") && !(detailsById instanceof Map) && !detailsLoadError) {
      directSearchResultsEl.innerHTML = "<p>Loading text details for search...</p>";
      await ensureDetailsLoaded();
    }

    const corpus = visibleNodes.length ? visibleNodes : rawNodes;
    const rows = corpus
      .filter((n) => {
        const author = normalizeText(n.first_author || "");
        const title = normalizeText(n.title || "");
        const abstract = normalizeText(n.abstract || "");
        if (mode === "author") return author.includes(q);
        if (mode === "title") return title.includes(q);
        if (mode === "abstract") return abstract.includes(q);
        return author.includes(q) || title.includes(q) || abstract.includes(q);
      })
      .map((n) => {
        const author = normalizeText(n.first_author || "");
        const title = normalizeText(n.title || "");
        const abstract = normalizeText(n.abstract || "");
        let exact = false;
        let starts = false;
        if (mode === "author") {
          exact = author === q;
          starts = author.startsWith(q);
        } else if (mode === "title") {
          exact = title === q;
          starts = title.startsWith(q);
        } else if (mode === "abstract") {
          exact = abstract === q;
          starts = abstract.startsWith(q);
        } else {
          exact = author === q || title === q || abstract === q;
          starts = author.startsWith(q) || title.startsWith(q) || abstract.startsWith(q);
        }
        return { n, exact, starts };
      })
      .sort((a, b) =>
        Number(b.exact) - Number(a.exact)
        || Number(b.starts) - Number(a.starts)
        || ((paperRankMap.get(a.n.id) || 10**9) - (paperRankMap.get(b.n.id) || 10**9))
        || ((b.n.citation_count || 0) - (a.n.citation_count || 0))
      )
      .slice(0, 20);

    if (!rows.length) {
      directSearchResultsEl.innerHTML = "<p>No matches found.</p>";
      return;
    }
    directSearchResultsEl.innerHTML = `
      <p><strong>Matches</strong></p>
      <ol>
        ${rows.map(({ n }) => {
          const rank = paperRankMap.get(n.id) || "?";
          const total = corpus.length || 1;
          const author = escapeHtml(String(n.first_author || "Unknown"));
          return `<li>${renderActionButtons(n)} ${escapeHtml(n.title || "Untitled")} <em>(author: ${author}; paper rank ${rank}/${total})</em></li>`;
        }).join("")}
      </ol>
    `;
  }

  function scoreIdeaDoc(doc, model, index) {
    let score = 0;
    for (const term of model.terms) {
      const idf = model.idf.get(term) || 0;
      if (!idf) continue;
      for (const [field, weight] of Object.entries(FIELD_WEIGHTS)) {
        const tf = doc.fieldCounts[field].get(term) || 0;
        if (!tf) continue;
        score += weight * bm25(tf, doc.fieldLengths[field], index.avgLens[field], idf);
      }
    }

    if (model.queryNorm && model.queryNorm.length > 5) {
      if (doc.titleNorm.includes(model.queryNorm)) score += 4.5;
      if (doc.combinedNorm.includes(model.queryNorm)) score += 2.4;
    }
    for (const bg of model.bigrams) {
      if (doc.titleNorm.includes(bg)) score += 1.4;
      else if (doc.combinedNorm.includes(bg)) score += 0.8;
    }

    const citationPrior = Math.log1p(doc.node.citation_count || 0);
    const centralityPrior = (doc.node.core_score || 0) * 2.2 + (doc.node.rank_pagerank || 0);
    score += 0.18 * citationPrior + 0.45 * centralityPrior;
    return score;
  }

  function rebuildAdjacency(nodes, edges) {
    nodeById = new Map(nodes.map(n => [n.id, n]));
    undirected = new Map(nodes.map(n => [n.id, new Set()]));
    incoming = new Map(nodes.map(n => [n.id, new Set()]));
    outgoing = new Map(nodes.map(n => [n.id, new Set()]));
    edges.forEach(e => {
      if (!undirected.has(e.source) || !undirected.has(e.target)) return;
      undirected.get(e.source).add(e.target);
      undirected.get(e.target).add(e.source);
      outgoing.get(e.source).add(e.target);
      incoming.get(e.target).add(e.source);
    });
  }

  function styleSelectedSubgraph(focusId) {
    selectedNodeId = focusId || null;
    selectedIncoming = new Set(selectedNodeId ? Array.from(incoming.get(selectedNodeId) || []) : []);
    selectedOutgoing = new Set(selectedNodeId ? Array.from(outgoing.get(selectedNodeId) || []) : []);
    selectedIncident = new Set(selectedNodeId ? [selectedNodeId, ...selectedIncoming, ...selectedOutgoing] : []);
    if (renderer) renderer.refresh();
  }

  function setPreset(mode) {
    if (mode === "undergrad") {
      coreMetricEl.value = "composite";
      difficultyMaxEl.value = "3";
      minInDegreeEl.value = "3";
      minOutDegreeEl.value = "3";
      minKcoreEl.value = "6";
      corePctEl.value = "20";
      requireAbstractEl.checked = true;
    } else if (mode === "grad") {
      coreMetricEl.value = "pagerank";
      difficultyMaxEl.value = "5";
      minInDegreeEl.value = "8";
      minOutDegreeEl.value = "8";
      minKcoreEl.value = "12";
      corePctEl.value = "60";
      requireAbstractEl.checked = true;
    } else {
      coreMetricEl.value = "composite";
      difficultyMaxEl.value = "4";
      minInDegreeEl.value = "5";
      minOutDegreeEl.value = "5";
      minKcoreEl.value = "10";
      corePctEl.value = "40";
      requireAbstractEl.checked = true;
    }
    corePctValueEl.textContent = `${corePctEl.value}%`;
    applyCoreFilter();
  }

  function applyCoreFilter() {
    const metric = coreMetricEl.value || "composite";
    const maxDifficulty = Number(difficultyMaxEl.value || 5);
    const minInDegree = Math.max(0, Number(minInDegreeEl.value || 0));
    const minOutDegree = Math.max(0, Number(minOutDegreeEl.value || 0));
    const minKcore = Math.max(0, Number(minKcoreEl.value || 0));
    const cutoff = Number(corePctEl.value || 0) / 100;
    const requireAbstract = !!requireAbstractEl.checked;
    corePctValueEl.textContent = `${Math.round(cutoff * 100)}%`;

    const matchedNodes = rawNodes
        .filter(n => !requireAbstract || !!n.has_abstract)
        .filter(n => Number(n.difficulty || 3) <= maxDifficulty)
        .filter(n => Number(n.in_degree || 0) >= minInDegree)
        .filter(n => Number(n.out_degree || 0) >= minOutDegree)
        .filter(n => Number(n.kcore || 0) >= minKcore)
        .filter(n => {
          if (metric === "pagerank") return (n.rank_pagerank || 0) >= cutoff;
          if (metric === "kcore") return (n.rank_kcore || 0) >= cutoff;
          if (metric === "in_degree") return (n.rank_in_degree || 0) >= cutoff;
          if (metric === "age_normalized") return (n.rank_age_normalized_importance || 0) >= cutoff;
          return (n.core_score || 0) >= cutoff;
        });

    const renderNodes = matchedNodes;

    const nodeIds = new Set(
      renderNodes
        .map(n => n.id)
    );

    if (graphStatusEl) {
      const communities = new Set(renderNodes.map(n => communityKey(n))).size;
      const edgesCount = rawEdges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target)).length;
      const heapBytes = (performance && performance.memory && performance.memory.usedJSHeapSize)
        ? Number(performance.memory.usedJSHeapSize)
        : 0;
      const detailsState = (detailsById instanceof Map)
        ? `Details: loaded ${formatMB(loadStats.detailsBytes)} (fetch ${Math.round(loadStats.detailsFetchMs)} ms + parse ${Math.round(loadStats.detailsParseMs)} ms).`
        : (detailsLoadError ? `Details: failed (${escapeHtml(detailsLoadError)}).` : "Details: lazy (load on first node/details search).");
      const sourceLabel = payloadMode === "full" ? "full payload" : (payloadMode === "mobile" ? "mobile payload" : "lite payload");
      graphStatusEl.innerHTML = `<p><em>Rendering ${matchedNodes.length.toLocaleString()} papers (${edgesCount.toLocaleString()} citations, ${communities.toLocaleString()} communities). Source: ${sourceLabel}. Base payload: ${formatMB(loadStats.payloadBytes)}. Load: fetch ${Math.round(loadStats.fetchMs)} ms + parse ${Math.round(loadStats.parseMs)} ms. ${detailsState}${heapBytes ? ` Heap: ${formatMB(heapBytes)}.` : ""}</em></p>`;
    }

    visibleNodes = renderNodes.filter(n => nodeIds.has(n.id));
    visibleEdges = rawEdges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    rebuildAdjacency(visibleNodes, visibleEdges);
    journeySelection = journeySelection.filter((id) => nodeById.has(id));
    renderJourneySelection();
    const positionById = buildCommunityPositions(visibleNodes);
    kcoreThresholds = computeKcoreThresholds(visibleNodes);
    const ready = buildSigmaGraph(positionById);
    if (ready) {
      styleSelectedSubgraph(null);
      stabilizeThenSettle(0);
    }

    if (visibleNodes.length) {
      const top = [...visibleNodes].sort((a, b) => (b.importance || 0) - (a.importance || 0))[0];
      focusNode(top.id);
    } else {
      detailsEl.innerHTML = "No papers match the current core/language filter.";
      parentEl.innerHTML = "";
      childEl.innerHTML = "";
      relatedEl.innerHTML = "";
      selectedNodeId = null;
      selectedIncoming = new Set();
      selectedOutgoing = new Set();
      selectedIncident = new Set();
      killRenderer();
      if (graphStatusEl) {
        graphStatusEl.innerHTML = "<p><em>No papers matched current filters.</em></p>";
      }
    }
  }

  function rankedNodes(ids, limit = 10, mode = "importance") {
    return Array.from(ids || [])
      .map(id => nodeById.get(id))
      .filter(Boolean)
      .sort((a, b) => {
        if (mode === "citation_count") {
          return ((b.citation_count || 0) - (a.citation_count || 0))
            || ((b.importance || 0) - (a.importance || 0));
        }
        return (b.importance || 0) - (a.importance || 0);
      })
      .slice(0, limit);
  }

  function parentsOf(id) {
    return rankedNodes(outgoing.get(id), 10, "citation_count");
  }

  function childrenOf(id) {
    return rankedNodes(incoming.get(id), 10, "citation_count");
  }

  function relatedOf(id) {
    const direct = new Set([...(incoming.get(id) || []), ...(outgoing.get(id) || [])]);
    const scoreMap = new Map();
    for (const n of direct) {
      for (const nn of (undirected.get(n) || [])) {
        if (nn === id || direct.has(nn)) continue;
        scoreMap.set(nn, (scoreMap.get(nn) || 0) + 1);
      }
    }
    const ranked = Array.from(scoreMap.entries())
      .map(([nid, overlap]) => ({ node: nodeById.get(nid), overlap }))
      .filter(x => x.node)
      .sort((a, b) => (b.overlap - a.overlap) || ((b.node.importance || 0) - (a.node.importance || 0)))
      .slice(0, 10)
      .map(x => x.node);
    if (ranked.length) return ranked;
    return rankedNodes(direct, 10);
  }

  function renderButtons(targetEl, nodes, emptyText) {
    if (!nodes.length) {
      targetEl.innerHTML = `<p>${emptyText}</p>`;
      return;
    }
    targetEl.innerHTML = nodes
      .map(n => `${renderActionButtons(n)} <span>${escapeHtml((n.title || "Untitled").slice(0, 85))}</span>`)
      .join("");
  }

  function renderRelationshipNavigator(id) {
    renderButtons(parentEl, parentsOf(id), "No parent links in current view.");
    renderButtons(childEl, childrenOf(id), "No child links in current view.");
    renderButtons(relatedEl, relatedOf(id), "No related links in current view.");
  }

  function renderPaper(id) {
    const node = nodeById.get(id);
    if (!node) return;
    if (!node._detailsLoaded && !detailsLoadError) {
      detailsEl.innerHTML = `
        <strong>${escapeHtml(node.title || "Untitled")}</strong><br />
        <div>Loading summary and abstract details...</div>
      `;
      ensureDetailsLoaded().then(() => {
        const latest = nodeById.get(id);
        if (latest) renderPaper(id);
      });
      return;
    }
    const sourceLink = node.source_url ? `<a href="${node.source_url}" target="_blank" rel="noopener">Open source paper</a>` : "No source link";
    const citationPlaintext = citationPlaintextForNode(node);
    const bibtex = citationBibtexForNode(node);
    const bibHref = `data:text/plain;charset=utf-8,${encodeURIComponent(bibtex)}`;
    const bibLink = `<a href="${bibHref}" download="${node.id}.bib">Download .bib</a>`;
    const yearInt = Number.isFinite(Number(node.year)) ? Math.trunc(Number(node.year)) : null;
    const year = yearInt ? ` (${yearInt})` : "";
    const summary = cleanNarrativeText(node.summary || "");
    const topic = node.topic_label ? `<span class="pill">${escapeHtml(node.topic_label)}</span>` : "";
    const difficultyLevel = Number(node.difficulty || 3);
    const difficultyLabel = (
      difficultyLevel <= 2 ? "plain language" :
      difficultyLevel === 3 ? "moderately technical" :
      difficultyLevel === 4 ? "advanced technical" : "specialist technical"
    );
    const diff = `<span class="pill">Language level ${difficultyLevel}/5 (${difficultyLabel})</span>`;
    const inLinks = Number(node.in_degree || 0);
    const outLinks = Number(node.out_degree || 0);
    const visibleIn = (incoming.get(id) || new Set()).size;
    const visibleOut = (outgoing.get(id) || new Set()).size;
    const linkCounts = `<span class="pill">Links in/out (corpus): ${inLinks}/${outLinks}</span><span class="pill">Links in/out (visible): ${visibleIn}/${visibleOut}</span>`;
    const kTierRaw = kcoreTier(node);
    const kTier = (kTierRaw === "high") ? "core" : (kTierRaw === "mid" ? "middle" : "peripheral");
    const kTierPill = `<span class="pill">k-core tier: ${kTier}</span>`;
    const paperRank = paperRankMap.get(node.id);
    const ageRank = paperAgeRankMap.get(node.id);
    const paperRankPill = paperRank ? `<span class="pill">Paper rank (raw): ${paperRank}/${Math.max(1, rawNodes.length)}</span>` : "";
    const paperAgeRankPill = ageRank ? `<span class="pill">Paper rank (age-norm): ${ageRank}/${Math.max(1, rawNodes.length)}</span>` : "";
    const authorName = String(node.first_author || "").trim();
    const authorStats = authorName ? authorStatsMap.get(authorName) : null;
    const authorRankPill = authorStats ? `<span class="pill">Author rank: ${authorStats.rank}/${Math.max(1, authorStatsMap.size)}</span>` : "";
    const evidenceType = String(node.evidence_type || "other").replaceAll("_", " ");
    const evidenceStrength = Number(node.evidence_strength || 2);
    const evidencePill = `<span class="pill">Evidence: ${escapeHtml(evidenceType)} (${evidenceStrength}/5)</span>`;
    const certaintyPct = Math.round(Math.max(0, Math.min(1, Number(node.summary_certainty_score || 0))) * 100);
    const certaintyLabel = escapeHtml(String(node.summary_certainty_label || "unknown"));
    const certaintyPill = `<span class="pill">Summary certainty: ${certaintyLabel} (${certaintyPct}%)</span>`;
    const ageNormScorePill = `<span class="pill">Age-normalized score: ${Number(node.age_normalized_importance || 0).toFixed(3)}</span>`;
    const cpyPill = `<span class="pill">Citations/year: ${Number(node.citations_per_year || 0).toFixed(2)}</span>`;
    const provenance = `<strong>Summary provenance:</strong> source=${escapeHtml(node.summary_source || "unknown")}; method=${escapeHtml(node.distill_method || "unknown")}; generated=${escapeHtml(node.summary_generated_at_utc || "unknown")}; hash=${escapeHtml(String(node.source_text_hash || "").slice(0, 12) || "n/a")}; overlap=${Number(node.faithfulness_overlap || 0).toFixed(2)}`;
    const journeyToggle = `<button data-journey-toggle="${node.id}">${journeyButtonLabel(node.id)} ${journeySelection.includes(node.id) ? "from" : "to"} Journey</button>`;
    const takeaways = Array.isArray(node.key_takeaways) ? node.key_takeaways : [];
    const takeawayHtml = takeaways.length
      ? `<ul>${takeaways.map(t => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`
      : "<p>No key takeaways available.</p>";
    const abstractText = cleanNarrativeText(node.abstract || "");
    detailsEl.innerHTML = `
      <strong>${escapeHtml(node.title || "Untitled")}</strong>${year}<br />
      ${topic}${diff}${kTierPill}${evidencePill}${certaintyPill}${ageNormScorePill}${cpyPill}${linkCounts}${paperRankPill}${paperAgeRankPill}${authorRankPill}<br />
      <div><strong>Lead author:</strong> ${escapeHtml(authorName || "Unknown")}</div><br />
      <div><strong>Abstract</strong><br />${escapeHtml(abstractText || "No abstract available.")}</div><br />
      <div>${escapeHtml(summary || "No summary available.")}</div><br />
      <div>${provenance}</div>
      <div><strong>Key takeaways</strong>${takeawayHtml}</div>
      <div><strong>Paper link:</strong> ${sourceLink}</div>
      <div><strong>Bibliography (plain text):</strong> ${escapeHtml(citationPlaintext)}</div>
      <div>${bibLink}</div>
      <div><em>${escapeHtml(String(node.summary_disclaimer || ""))}</em></div>
      <div class="explorer-actions">${journeyToggle}</div>
    `;
    renderRelationshipNavigator(id);
  }

  function focusNode(id) {
    if (!nodeById.has(id) || !renderer || !sigmaGraph) return;
    styleSelectedSubgraph(id);
    if (sigmaGraph.hasNode(id)) {
      const x = sigmaGraph.getNodeAttribute(id, "x");
      const y = sigmaGraph.getNodeAttribute(id, "y");
      const camera = renderer.getCamera && renderer.getCamera();
      if (camera && Number.isFinite(x) && Number.isFinite(y)) {
        camera.animate({ x, y, ratio: 0.22 }, { duration: 280 });
      }
    }
    renderPaper(id);
  }

  function toggleJourneySelection(id) {
    const idx = journeySelection.indexOf(id);
    if (idx >= 0) {
      journeySelection.splice(idx, 1);
    } else {
      journeySelection.push(id);
    }
    renderJourneySelection();
    if (selectedNodeId === id) {
      renderPaper(id);
    }
    if ((directSearchInputEl.value || "").trim()) {
      runDirectSearch();
    }
    if ((ideaInputEl.value || "").trim()) {
      runIdeaMatch();
    }
  }

  function clearJourneySelection() {
    journeySelection = [];
    renderJourneySelection();
  }

  function renderJourneySelection() {
    if (!journeySelection.length) {
      journeySelectedEl.innerHTML = "<p>No papers selected yet. Use Add buttons from graph results or tools.</p>";
      return;
    }
    journeySelectedEl.innerHTML = `
      <p><strong>Selected papers (${journeySelection.length})</strong></p>
      <ol>
        ${journeySelection.map((id) => {
          const node = nodeById.get(id);
          if (!node) return "";
          return `<li>${renderActionButtons(node)} ${escapeHtml(node.title || "Untitled")}</li>`;
        }).join("")}
      </ol>
    `;
  }

  function neighborOverlapWithSeeds(nodeId, seedSet) {
    const inSet = incoming.get(nodeId) || new Set();
    const outSet = outgoing.get(nodeId) || new Set();
    let overlap = 0;
    for (const n of inSet) if (seedSet.has(n)) overlap += 1;
    for (const n of outSet) if (seedSet.has(n)) overlap += 1;
    return overlap;
  }

  function renderJourneyList(nodes, emptyText) {
    if (!nodes.length) return `<p>${emptyText}</p>`;
    return `<ol>${nodes.map((node) => `<li>${renderActionButtons(node)} ${escapeHtml(node.title || "Untitled")}</li>`).join("")}</ol>`;
  }

  async function generateLearningJourney() {
    const selected = journeySelection.map((id) => nodeById.get(id)).filter(Boolean);
    if (!selected.length) {
      journeyResultsEl.innerHTML = "<p>Select at least one paper to generate a journey.</p>";
      return;
    }
    if (!(detailsById instanceof Map) && !detailsLoadError) {
      journeyResultsEl.innerHTML = "<p>Loading text details for journey generation...</p>";
      await ensureDetailsLoaded();
    }

    const selectedSet = new Set(selected.map((n) => n.id));
    const corpus = visibleNodes.length ? visibleNodes : rawNodes;
    const index = prepareSearchIndex(corpus);
    const queryText = selected.map((n) => `${n.title || ""} ${n.summary || ""} ${n.abstract || ""} ${n.topic_label || ""}`).join(" ");
    const model = buildQueryModel(queryText, index);
    const docsById = new Map(index.docs.map((doc) => [doc.node.id, doc]));

    const candidateIds = new Set();
    selected.forEach((node) => {
      (incoming.get(node.id) || new Set()).forEach((id) => candidateIds.add(id));
      (outgoing.get(node.id) || new Set()).forEach((id) => candidateIds.add(id));
      (undirected.get(node.id) || new Set()).forEach((id) => candidateIds.add(id));
    });

    const candidates = Array.from(candidateIds)
      .filter((id) => !selectedSet.has(id))
      .map((id) => nodeById.get(id))
      .filter(Boolean)
      .map((node) => {
        const doc = docsById.get(node.id);
        const relevance = doc ? scoreIdeaDoc(doc, model, index) : 0;
        const overlap = neighborOverlapWithSeeds(node.id, selectedSet);
        const score = relevance + (overlap * 2.0) + (node.core_score || 0) * 1.4 + Math.log1p(node.citation_count || 0) * 0.2;
        return { node, score, overlap };
      })
      .sort((a, b) => (b.score - a.score) || ((b.node.importance || 0) - (a.node.importance || 0)));

    const foundations = [...selected].sort((a, b) =>
      (Number(a.difficulty || 3) - Number(b.difficulty || 3))
      || ((b.citation_count || 0) - (a.citation_count || 0))
    );
    const bridges = candidates.filter((x) => x.overlap > 0).slice(0, 5).map((x) => x.node);
    const deepDives = candidates.slice(0, 8).map((x) => x.node);

    journeyResultsEl.innerHTML = `
      <p><strong>Generated learning journey</strong></p>
      <h5>1. Foundations (start here)</h5>
      ${renderJourneyList(foundations, "No foundation papers found.")}
      <h5>2. Bridges (connect mechanisms to applications)</h5>
      ${renderJourneyList(bridges, "No bridge papers found from selected set.")}
      <h5>3. Deep Dives (advanced extensions)</h5>
      ${renderJourneyList(deepDives, "No deep-dive recommendations found.")}
    `;
  }

  async function runIdeaMatch() {
    const idea = (ideaInputEl.value || "").trim();
    if (!idea) {
      ideaResultsEl.innerHTML = "<p>Add a brief note first.</p>";
      return;
    }
    if (!(detailsById instanceof Map) && !detailsLoadError) {
      ideaResultsEl.innerHTML = "<p>Loading text details for idea matching...</p>";
      await ensureDetailsLoaded();
    }
    const baseNodes = rawNodes.filter(n => {
      const metric = coreMetricEl.value || "composite";
      const maxDifficulty = Number(difficultyMaxEl.value || 5);
      const minInDegree = Math.max(0, Number(minInDegreeEl.value || 0));
      const minOutDegree = Math.max(0, Number(minOutDegreeEl.value || 0));
      const minKcore = Math.max(0, Number(minKcoreEl.value || 0));
      const cutoff = Number(corePctEl.value || 0) / 100;
      const requireAbstract = !!requireAbstractEl.checked;
      if (requireAbstract && !n.has_abstract) return false;
      if (Number(n.difficulty || 3) > maxDifficulty) return false;
      if (Number(n.in_degree || 0) < minInDegree) return false;
      if (Number(n.out_degree || 0) < minOutDegree) return false;
      if (Number(n.kcore || 0) < minKcore) return false;
      if (metric === "pagerank") return (n.rank_pagerank || 0) >= cutoff;
      if (metric === "kcore") return (n.rank_kcore || 0) >= cutoff;
      if (metric === "in_degree") return (n.rank_in_degree || 0) >= cutoff;
      if (metric === "age_normalized") return (n.rank_age_normalized_importance || 0) >= cutoff;
      return (n.core_score || 0) >= cutoff;
    });
    const index = prepareSearchIndex(baseNodes);
    const model = buildQueryModel(idea, index);
    if (!model.terms.length) {
      ideaResultsEl.innerHTML = "<p>Add more specific terms (for example: EBV, NfL, RRMS, MRI lesions).</p>";
      return;
    }
    let scored = index.docs
      .map(doc => ({ node: doc.node, score: scoreIdeaDoc(doc, model, index) }))
      .filter(x => x.score > 0);
    scored.sort((a, b) => (b.score - a.score) || ((b.node.importance || 0) - (a.node.importance || 0)));

    if (scored.length) {
      const best = scored[0].score;
      const minKeep = Math.max(1.2, best * 0.16);
      scored = scored.filter(x => x.score >= minKeep);
    }
    scored = scored.slice(0, 12);

    if (!scored.length) {
      ideaResultsEl.innerHTML = "<p>No strong matches in this explorer subset. Try adding modality (MRI/OCT), phenotype (RRMS/SPMS), or mechanism terms.</p>";
      return;
    }
    ideaResultsEl.innerHTML = `
      <p><strong>Top matches:</strong></p>
      <p><em>Hybrid ranker: field-weighted BM25 + phrase boosts + graph-prior.</em></p>
      <ol>
        ${scored.map(({ node, score }) => `
          <li>
            ${renderActionButtons(node)}
            ${escapeHtml(node.title)} (relevance ${score.toFixed(2)})
          </li>
        `).join("")}
      </ol>
    `;
  }

  function stabilizeThenSettle(amplitude = 0) {
    if (!renderer || !sigmaGraph) return;
    const positionById = buildCommunityPositions(visibleNodes);
    const jitter = Math.max(0, Number(amplitude) || 0);
    visibleNodes.forEach((node) => {
      if (!sigmaGraph.hasNode(node.id)) return;
      const base = positionById.get(node.id) || { x: 0, y: 0 };
      sigmaGraph.setNodeAttribute(node.id, "x", (Number(base.x) || 0) + (Math.random() - 0.5) * jitter);
      sigmaGraph.setNodeAttribute(node.id, "y", (Number(base.y) || 0) + (Math.random() - 0.5) * jitter);
    });
    renderer.refresh();
  }

  async function loadCorpusPayload(candidates) {
    if (isLoadingCorpus) return;
    isLoadingCorpus = true;
    refreshFullCorpusButton();
    const candidateList = Array.isArray(candidates) ? candidates : [candidates];
    let lastErr = null;
    const candidateErrors = [];
    try {
      for (const candidate of candidateList) {
        const loadStart = performance.now();
        try {
          setGraphStatus(`Loading ${candidate.label || candidate.mode || "payload"} payload...`);
          const r = await fetchTextWithTimeout(candidate.url, 20000);
          if (!r.ok) throw new Error(`${candidate.label || candidate.mode || "payload"} request failed (${r.status})`);
          const text = await r.text();
          const parseStart = performance.now();
          loadStats.fetchMs = parseStart - loadStart;
          loadStats.payloadBytes = Number(r.headers.get("content-length")) || (text.length * 2);
          const payload = JSON.parse(text);
          loadStats.parseMs = performance.now() - parseStart;
          const decoded = decodeGraphPayload(payload);
          payloadMode = candidate.mode;
          detailsUrlActive = candidate.detailsUrl;
          detailsById = null;
          detailsLoadPromise = null;
          detailsLoadError = "";
          loadStats.detailsBytes = 0;
          loadStats.detailsFetchMs = 0;
          loadStats.detailsParseMs = 0;
          rawNodes = (decoded.nodes || []).map((node) => ({ ...normalizeNode(node), _detailsLoaded: false }));
          rawEdges = decoded.edges || [];
          buildRankIndexes(rawNodes);
          visibleNodes = [];
          visibleEdges = [];
          rebuildAdjacency(visibleNodes, visibleEdges);
          corePctValueEl.textContent = `${corePctEl.value}%`;
          applyCoreFilter();
          lastErr = null;
          break;
        } catch (err) {
          lastErr = err;
          candidateErrors.push(`${candidate.label || candidate.mode || "payload"}: ${err}`);
        }
      }
      if (lastErr) {
        showFatalOverlay("Explorer data load failed", candidateErrors.join("\n"));
      }
    } finally {
      isLoadingCorpus = false;
      refreshFullCorpusButton();
    }
  }

  setGraphStatus("Loading explorer graph...");
  if (window.__mskbDebug) window.__mskbDebug("main IIFE: about to call loadCorpusPayload (mobile=" + isMobileView + ")");
  loadCorpusPayload(initialPayloadCandidates).then(function () {
    if (window.__mskbDebug) {
      window.__mskbDebug("after load: rawNodes=" + rawNodes.length + " rawEdges=" + rawEdges.length + " visibleNodes=" + visibleNodes.length + " visibleEdges=" + visibleEdges.length);
      window.__mskbDebug("after load: renderer=" + (renderer ? "yes" : "no") + " sigmaGraph=" + (sigmaGraph ? sigmaGraph.order + "n/" + sigmaGraph.size + "e" : "null"));
      var pg = document.getElementById("paper-graph");
      if (pg) {
        var rr = pg.getBoundingClientRect();
        window.__mskbDebug("paper-graph rect after load: " + Math.round(rr.width) + "x" + Math.round(rr.height));
        var canv = pg.querySelectorAll("canvas");
        window.__mskbDebug("paper-graph canvases: " + canv.length);
      }
    }
  });

  [parentEl, childEl, relatedEl, directSearchResultsEl, ideaResultsEl, journeySelectedEl, journeyResultsEl, detailsEl].forEach(container => {
    container.addEventListener("click", (ev) => {
      const focusBtn = ev.target.closest("button[data-focus]");
      if (focusBtn) {
        focusNode(focusBtn.dataset.focus);
        return;
      }
      const toggleBtn = ev.target.closest("button[data-journey-toggle]");
      if (toggleBtn) {
        toggleJourneySelection(toggleBtn.dataset.journeyToggle);
      }
    });
  });

  directSearchRunEl.addEventListener("click", runDirectSearch);
  directSearchInputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      runDirectSearch();
    }
  });

  journeyGenerateEl.addEventListener("click", generateLearningJourney);
  journeyClearEl.addEventListener("click", clearJourneySelection);

  ideaRunEl.addEventListener("click", runIdeaMatch);
  coreApplyEl.addEventListener("click", applyCoreFilter);
  presetUndergradEl.addEventListener("click", () => setPreset("undergrad"));
  presetBalancedEl.addEventListener("click", () => setPreset("balanced"));
  presetGradEl.addEventListener("click", () => setPreset("grad"));
  ideaInputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      runIdeaMatch();
    }
  });
  corePctEl.addEventListener("input", () => {
    corePctValueEl.textContent = `${corePctEl.value}%`;
  });
  loadFullCorpusEl.addEventListener("click", () => {
    if (isMobileView || payloadMode === "full") return;
    loadCorpusPayload([{ url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" }]);
  });
  relayoutEl.addEventListener("click", () => {
    if (isMobileView) return;
    stabilizeThenSettle(18);
  });
  nodeDragToggleEl.addEventListener("click", () => {
    if (isMobileView) return;
    dragEnabled = !dragEnabled;
    draggingNode = null;
    refreshNodeDragToggleLabel();
  });
  if (isMobileView) {
    relayoutEl.disabled = true;
    relayoutEl.title = "Re-layout disabled on mobile";
  }
  refreshFullCorpusButton();
  refreshNodeDragToggleLabel();
  renderJourneySelection();
})();
</script>
