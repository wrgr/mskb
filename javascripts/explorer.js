// ---- explorer boot ----
// IIFE that wires the Cytoscape-based Explorer page. DOM ids referenced here
// are asserted in tests/test_explorer_assets.py so they stay in sync with
// the markdown shell in site/src/content/docs/explorer.mdx.
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
  const communityStatsEl = document.getElementById("community-stats");
  const communityResultsEl = document.getElementById("community-results");
  const communityGenerateEl = document.getElementById("community-generate");
  const communityDownloadEl = document.getElementById("community-download");
  const ideaRunEl = document.getElementById("idea-run");
  const relayoutEl = document.getElementById("graph-relayout");
  const nodeDragToggleEl = document.getElementById("node-drag-toggle");
  const graphStatusEl = document.getElementById("graph-status");
  const coreMetricEl = document.getElementById("core-metric");
  const readingLevelEl = document.getElementById("reading-level");
  const minInDegreeEl = document.getElementById("min-in-degree");
  const minOutDegreeEl = document.getElementById("min-out-degree");
  const minKcoreEl = document.getElementById("min-kcore");
  const corePctEl = document.getElementById("core-percentile");
  const corePctValueEl = document.getElementById("core-percentile-value");
  const clusterSpreadEl = document.getElementById("cluster-spread");
  const clusterSpreadValueEl = document.getElementById("cluster-spread-value");
  const coreApplyEl = document.getElementById("core-apply");
  const loadFullCorpusEl = document.getElementById("load-full-corpus");
  const requireAbstractEl = document.getElementById("require-abstract");
  const presetUndergradEl = document.getElementById("preset-undergrad");
  const presetBalancedEl = document.getElementById("preset-balanced");
  const presetGradEl = document.getElementById("preset-grad");
  const journeyImportEl = document.getElementById("journey-import");
  const journeyExportJsonEl = document.getElementById("journey-export-json");
  const journeyExportBibtexEl = document.getElementById("journey-export-bibtex");
  const journeyExportMarkdownEl = document.getElementById("journey-export-markdown");
  const journeyIoStatusEl = document.getElementById("journey-io-status");
  const spineGraphEl = document.getElementById("mskb-graph-spine");
  const researchGraphEl = document.getElementById("mskb-graph-research");
  const hasExplorerGraph = Boolean(
    graphEl && detailsEl && parentEl && childEl && relatedEl
  );
  const isMobileView = window.matchMedia("(max-width: 768px), (pointer: coarse)").matches;
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
  const SELECTION_STORAGE_KEY = "mskb.explorer.selection.v1";
  let journeySelection = loadStoredSelection();
  const selectionCountEl = document.getElementById("selection-count");

  function loadStoredSelection() {
    try {
      const raw = window.localStorage && window.localStorage.getItem(SELECTION_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      const seen = new Set();
      const out = [];
      for (const id of parsed) {
        const s = String(id || "");
        if (!s || seen.has(s)) continue;
        seen.add(s);
        out.push(s);
      }
      return out;
    } catch (_) {
      return [];
    }
  }

  function persistSelection() {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(journeySelection));
      }
    } catch (_) { /* swallow */ }
  }

  const READING_LEVEL_STORAGE_KEY = "mskb.explorer.readingLevel.v2";
  const READING_LEVELS = new Set(["basic", "advanced"]);
  function normalizeReadingLevel(value) {
    const raw = String(value == null ? "" : value).trim().toLowerCase();
    if (READING_LEVELS.has(raw)) return raw;
    // Legacy numeric values from the older 1-5 control.
    const n = Number(raw);
    if (Number.isFinite(n)) return n >= 4 ? "advanced" : "basic";
    return "basic";
  }
  function loadStoredReadingLevel() {
    try {
      const raw = window.localStorage && window.localStorage.getItem(READING_LEVEL_STORAGE_KEY);
      if (raw == null) return null;
      return normalizeReadingLevel(raw);
    } catch (_) { /* swallow */ }
    return null;
  }
  function persistReadingLevel(value) {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(READING_LEVEL_STORAGE_KEY, normalizeReadingLevel(value));
      }
    } catch (_) { /* swallow */ }
  }
  function currentReadingLevel() {
    if (readingLevelEl) return normalizeReadingLevel(readingLevelEl.value);
    return "basic";
  }

  function pruneSelectionToCorpus() {
    if (!journeySelection.length || !nodeById.size) return;
    const before = journeySelection.length;
    journeySelection = journeySelection.filter((id) => nodeById.has(id));
    if (journeySelection.length !== before) {
      applySelectionMutation(true);
    }
  }

  let paperRankMap = new Map();
  let paperAgeRankMap = new Map();
  let authorStatsMap = new Map();
  let searchIndexCache = { signature: "", index: null };
  let spreadMultiplier = clusterSpreadEl ? (Number(clusterSpreadEl.value || 180) / 100) : 1.8;

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

  // Only escalate to the fatal overlay when the error actually came from
  // explorer code. On mobile, unrelated Starlight/image errors fire during
  // pinch-zoom and would otherwise paint the whole page red.
  let lastOverlayAtMs = 0;
  const OVERLAY_DEBOUNCE_MS = 1500;
  function isExplorerError(filename, stack) {
    const hay = `${filename || ""}\n${stack || ""}`.toLowerCase();
    return hay.includes("explorer.js") || hay.includes("cytoscape") || hay.includes("mskb_graph_renderer");
  }
  function maybeShowFatalOverlay(title, msg, filename, stack) {
    if (!isExplorerError(filename, stack)) {
      console.warn(`[explorer] non-fatal error ignored: ${msg}`);
      return;
    }
    const now = Date.now();
    if (now - lastOverlayAtMs < OVERLAY_DEBOUNCE_MS) {
      console.warn(`[explorer] debounced overlay: ${msg}`);
      return;
    }
    lastOverlayAtMs = now;
    showFatalOverlay(title, `${msg}\n${stack || ""}`);
  }

  window.addEventListener("error", (event) => {
    const msg = event?.error?.message || event?.message || "Unknown script error";
    const stack = event?.error?.stack || "";
    const filename = event?.filename || "";
    maybeShowFatalOverlay("Explorer runtime error", msg, filename, stack);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event?.reason;
    const msg = typeof reason === "string" ? reason : (reason?.message || String(reason || "Unknown promise rejection"));
    const stack = reason && reason.stack ? reason.stack : "";
    maybeShowFatalOverlay("Explorer async error", msg, "", stack);
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
    n.summary_basic = String(n.summary_basic || "");
    n.summary_advanced = String(n.summary_advanced || "");
    n.why_it_matters_basic = String(n.why_it_matters_basic || "");
    n.why_it_matters_advanced = String(n.why_it_matters_advanced || "");
    n.key_takeaways_basic = Array.isArray(n.key_takeaways_basic) ? n.key_takeaways_basic : [];
    n.key_takeaways_advanced = Array.isArray(n.key_takeaways_advanced) ? n.key_takeaways_advanced : [];
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

  function normalizeJargon(raw) {
    if (!raw) return [];
    let items = raw;
    if (typeof raw === "string") {
      const trimmed = raw.trim();
      if (!trimmed) return [];
      try {
        items = JSON.parse(trimmed);
      } catch (err) {
        return [];
      }
    }
    if (!Array.isArray(items)) return [];
    const out = [];
    items.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      const term = String(entry.term || "").trim();
      if (!term) return;
      const definition = String(entry.definition || "").trim();
      out.push({ term, definition });
    });
    return out;
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
          summary_basic: String(obj.summary_basic || ""),
          summary_advanced: String(obj.summary_advanced || ""),
          why_it_matters_basic: String(obj.why_it_matters_basic || ""),
          why_it_matters_advanced: String(obj.why_it_matters_advanced || ""),
          key_takeaways_basic: Array.isArray(obj.key_takeaways_basic) ? obj.key_takeaways_basic : [],
          key_takeaways_advanced: Array.isArray(obj.key_takeaways_advanced) ? obj.key_takeaways_advanced : [],
          jargon: normalizeJargon(obj.jargon),
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
        summary_basic: String(obj?.summary_basic || ""),
        summary_advanced: String(obj?.summary_advanced || ""),
        why_it_matters_basic: String(obj?.why_it_matters_basic || ""),
        why_it_matters_advanced: String(obj?.why_it_matters_advanced || ""),
        key_takeaways_basic: Array.isArray(obj?.key_takeaways_basic) ? obj.key_takeaways_basic : [],
        key_takeaways_advanced: Array.isArray(obj?.key_takeaways_advanced) ? obj.key_takeaways_advanced : [],
        jargon: normalizeJargon(obj?.jargon),
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
    // Mutate existing node objects in place so other references
    // (nodeById, visibleNodes, cytoscape data) see _detailsLoaded=true
    // and don't infinite-loop in renderPaper.
    for (const node of rawNodes) {
      const details = detailsById.get(node.id);
      if (details) {
        node.abstract = String(details.abstract || "");
        node.summary = String(details.summary || "");
        node.summary_source = String(details.summary_source || "");
        node.why_it_matters = String(details.why_it_matters || "");
        node.key_takeaways = Array.isArray(details.key_takeaways) ? details.key_takeaways : [];
        node.summary_basic = String(details.summary_basic || "");
        node.summary_advanced = String(details.summary_advanced || "");
        node.why_it_matters_basic = String(details.why_it_matters_basic || "");
        node.why_it_matters_advanced = String(details.why_it_matters_advanced || "");
        node.key_takeaways_basic = Array.isArray(details.key_takeaways_basic) ? details.key_takeaways_basic : [];
        node.key_takeaways_advanced = Array.isArray(details.key_takeaways_advanced) ? details.key_takeaways_advanced : [];
        node.jargon = Array.isArray(details.jargon) ? details.jargon : [];
        node.summary_generated_at_utc = String(details.summary_generated_at_utc || "");
        node.distill_method = String(details.distill_method || "");
        node.summary_certainty_score = Number(details.summary_certainty_score || 0);
        node.summary_certainty_label = String(details.summary_certainty_label || "");
        node.summary_disclaimer = String(details.summary_disclaimer || "");
        node.faithfulness_overlap = Number(details.faithfulness_overlap || 0);
        node.source_text_hash = String(details.source_text_hash || "");
        node.source_text_chars = Number(details.source_text_chars || 0);
      }
      node._detailsLoaded = true;
    }
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

  let cy = null;
  let cyBuildGen = 0;

  function getCytoCtor() {
    return (typeof window.cytoscape === "function") ? window.cytoscape : null;
  }

  function killRenderer() {
    if (cy && typeof cy.destroy === "function") {
      try { cy.destroy(); } catch (_) {}
    }
    cy = null;
    // Bump generation so any in-flight chunked-add loop bails out.
    cyBuildGen += 1;
  }

  function scheduleIdle(fn) {
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(fn, { timeout: 80 });
    } else {
      setTimeout(fn, 0);
    }
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

  // Convert raw topic_label like "Medicine / Multiple Sclerosis Research Studies / Multiple sclerosis"
  // into a friendlier theme name. Strips redundant words that are common across the whole MS corpus
  // and keeps the most distinctive terms.
  const CLUSTER_LABEL_STOPWORDS = new Set([
    "medicine", "biology", "internal medicine", "disease",
    "multiple sclerosis", "ms", "research", "studies",
    "multiple sclerosis research studies", "research studies",
    "general", "other",
  ]);
  function prettifyClusterLabel(raw, fallbackKey) {
    const text = String(raw || "").trim();
    if (!text) {
      if (!fallbackKey) return "Research theme";
      const fb = fallbackKey
        .replace(/^topic:/, "Theme ")
        .replace(/^label:/, "")
        .trim();
      return fb || "Research theme";
    }
    const parts = text
      .split(/\s*[\/|]\s*/)
      .map((s) => s.trim())
      .filter(Boolean);
    const distinctive = [];
    const seenNorm = new Set();
    for (const p of parts) {
      const norm = p.toLowerCase().replace(/\s+/g, " ").trim();
      if (CLUSTER_LABEL_STOPWORDS.has(norm)) continue;
      if (seenNorm.has(norm)) continue;
      // Skip if this part is a substring of (or contains) one already kept.
      let dup = false;
      for (const k of distinctive) {
        const kn = k.toLowerCase();
        if (kn.includes(norm) || norm.includes(kn)) { dup = true; break; }
      }
      if (dup) continue;
      seenNorm.add(norm);
      distinctive.push(p);
    }
    let chosen;
    if (distinctive.length === 0) {
      // All parts were stopwords or duplicates. Pick the longest non-empty raw part.
      chosen = parts.slice().sort((a, b) => b.length - a.length)[0] || text;
    } else if (distinctive.length === 1) {
      chosen = distinctive[0];
    } else {
      chosen = distinctive.slice(0, 2).join(" \u00b7 ");
    }
    return chosen.charAt(0).toUpperCase() + chosen.slice(1);
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
    const mult = Math.max(0.4, Number(spreadMultiplier) || 1);
    const spacingX = 700 * mult;
    const spacingY = 600 * mult;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const positions = new Map();

    ordered.forEach(([_, members], idx) => {
      const col = idx % cols;
      const row = Math.floor(idx / cols);
      const cx = (col - (cols - 1) / 2) * spacingX;
      const cy = (row - (rows - 1) / 2) * spacingY;
      members.sort((a, b) => ((b.citation_count || 0) - (a.citation_count || 0)) || String(a.id).localeCompare(String(b.id)));
      const radialStep = Math.max(28, Math.min(56, 22 + Math.sqrt(members.length))) * mult;
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
    // Also stamp a normalized percentile rank on every node so the composite
    // filter has something to compare against (mirrors the rank_pagerank /
    // rank_kcore / rank_in_degree / rank_age_normalized_importance fields the
    // pipeline emits via pandas .rank(method="average", pct=True) — the
    // best-scoring node lands at 1.0 and the worst at ~1/n).
    const totalRanked = rankedPapers.length;
    rankedPapers.forEach((n, idx) => {
      paperRankMap.set(n.id, idx + 1);
      n.rank_core_score = totalRanked > 0 ? (totalRanked - idx) / totalRanked : 0;
    });
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

  function buildCytoscapeGraph(positionById, onReady) {
    const CytoCtor = getCytoCtor();
    if (!CytoCtor) {
      const detail = `cytoscape=${typeof window.cytoscape}. Vendor script at /javascripts/vendor/cytoscape.min.js may have failed to load.`;
      showFatalOverlay("Explorer renderer failed to initialize", detail);
      return false;
    }

    try {
      killRenderer();
      const myGen = cyBuildGen;

      const t0 = (performance && performance.now) ? performance.now() : 0;
      // Pre-aggregate cluster centroids and friendly names while building nodes.
      const clusterAgg = new Map(); // key -> { name, count, sumX, sumY, minX, minY, maxX, maxY }
      const elements = new Array(visibleNodes.length + visibleEdges.length + 16);
      let ei = 0;
      const nodeIds = new Set();
      for (let i = 0; i < visibleNodes.length; i += 1) {
        const n = visibleNodes[i];
        const style = buildBaseNodeStyle(n);
        const pos = positionById.get(n.id) || { x: (Math.random() - 0.5) * 2, y: (Math.random() - 0.5) * 2 };
        const px = Number(pos.x) || 0;
        const py = Number(pos.y) || 0;
        nodeIds.add(n.id);
        const baseSizeRaw = (Number(style.size) || 2) * 1.6;
        const baseSize = isMobileView
          ? Math.max(12, baseSizeRaw * 1.8)
          : Math.max(4, baseSizeRaw);
        elements[ei++] = {
          group: "nodes",
          data: {
            id: n.id,
            label: style.label,
            baseColor: style.kcoreColor || style.color,
            baseSize,
          },
          position: { x: px, y: py },
        };

        const ck = communityKey(n);
        let agg = clusterAgg.get(ck);
        if (!agg) {
          const niceName = prettifyClusterLabel(n.topic_label, ck);
          agg = { name: niceName, count: 0, sumX: 0, sumY: 0, minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
          clusterAgg.set(ck, agg);
        }
        agg.count += 1;
        agg.sumX += px;
        agg.sumY += py;
        if (px < agg.minX) agg.minX = px;
        if (py < agg.minY) agg.minY = py;
        if (px > agg.maxX) agg.maxX = px;
        if (py > agg.maxY) agg.maxY = py;
      }
      for (let i = 0; i < visibleEdges.length; i += 1) {
        const e = visibleEdges[i];
        if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
        elements[ei++] = {
          group: "edges",
          data: { id: "e" + i, source: e.source, target: e.target },
        };
      }
      // Cluster label "ghost" nodes — non-interactive, always visible.
      // Skip clusters of 1 node and "(unlabeled)" buckets. Guard against
      // Infinity/NaN from pathological coordinate inputs.
      clusterAgg.forEach((agg, key) => {
        if (agg.count < 2) return;
        if (!agg.name || agg.name === "unassigned") return;
        const cx = agg.sumX / agg.count;
        const cy = (agg.minY) - 30;
        if (!Number.isFinite(cx) || !Number.isFinite(cy)) return;
        elements[ei++] = {
          group: "nodes",
          data: { id: "__cl__" + key, label: agg.name, isCluster: 1 },
          position: { x: cx, y: cy },
          selectable: false,
          grabbable: false,
        };
      });
      elements.length = ei;

      // Construct cytoscape with NO elements first; we add them in idle-callback
      // chunks below to keep the main thread responsive on large payloads.
      cy = CytoCtor({
        container: graphEl,
        elements: [],
        layout: { name: "preset", fit: false, padding: 30 },
        pixelRatio: 1,
        textureOnViewport: true,
        hideEdgesOnViewport: true,
        motionBlur: false,
        autoungrabify: !dragEnabled || isMobileView,
        autounselectify: false,
        // minZoom intentionally low so the initial cy.fit() can actually fit
        // the whole corpus into view on the first paint — at 0.15 a ~1k-node
        // graph gets clamped and part of it stays off-screen.
        minZoom: 0.04,
        maxZoom: 3,
        tapThreshold: 8,
        touchTapThreshold: 12,
        wheelSensitivity: 0.2,
        style: [
          {
            selector: "node[baseColor]",
            style: {
              "background-color": "data(baseColor)",
              "width": "data(baseSize)",
              "height": "data(baseSize)",
              "border-width": 0,
            },
          },
          {
            selector: "edge",
            style: {
              "width": 1,
              "line-color": "rgba(125,138,150,0.18)",
              "curve-style": "straight",
              "target-arrow-shape": "triangle",
              "target-arrow-color": "rgba(125,138,150,0.32)",
              "arrow-scale": 0.7,
            },
          },
          // Always-visible cluster label nodes
          {
            selector: "node[?isCluster]",
            style: {
              "background-opacity": 0,
              "border-width": 0,
              "label": "data(label)",
              "font-size": 16,
              "font-weight": "bold",
              "color": "rgba(40,52,68,0.55)",
              "text-outline-color": "#ffffff",
              "text-outline-width": 3,
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": 220,
              "events": "no",
              "min-zoomed-font-size": 6,
              "width": 1,
              "height": 1,
              "z-index": 1,
            },
          },
          // Selection-active styling
          { selector: "node.dim",   style: { "background-color": "rgba(150,160,170,0.18)" } },
          { selector: "edge.dim",   style: { "line-color": "rgba(154,166,178,0.06)", "target-arrow-color": "rgba(154,166,178,0.06)", "width": 0.6 } },
          { selector: "node.in",    style: { "background-color": "#25a16d", "label": "data(label)", "font-size": 10, "color": "#1a5d40", "text-outline-color": "#fff", "text-outline-width": 2, "text-valign": "top", "text-margin-y": -4, "min-zoomed-font-size": 8, "z-index": 5 } },
          { selector: "node.out",   style: { "background-color": "#cf5b2f", "label": "data(label)", "font-size": 10, "color": "#7f2c0f", "text-outline-color": "#fff", "text-outline-width": 2, "text-valign": "top", "text-margin-y": -4, "min-zoomed-font-size": 8, "z-index": 5 } },
          { selector: "node.both",  style: { "background-color": "#b97e1d", "label": "data(label)", "font-size": 10, "color": "#6c4708", "text-outline-color": "#fff", "text-outline-width": 2, "text-valign": "top", "text-margin-y": -4, "min-zoomed-font-size": 8, "z-index": 5 } },
          { selector: "node.focus", style: { "background-color": "#0a3f5c", "label": "data(label)", "font-size": 13, "color": "#0a3f5c", "text-outline-color": "#fff", "text-outline-width": 2, "text-valign": "top", "text-margin-y": -6, "z-index": 10 } },
          { selector: "edge.eIn",   style: { "line-color": "#25a16d", "target-arrow-color": "#25a16d", "width": 2.4 } },
          { selector: "edge.eOut",  style: { "line-color": "#cf5b2f", "target-arrow-color": "#cf5b2f", "width": 2.4 } },
          { selector: "edge.eBridge", style: { "line-color": "rgba(76,111,138,0.42)", "target-arrow-color": "rgba(76,111,138,0.42)", "width": 1.2 } },
        ],
      });
      cy.on("tap", "node", (evt) => {
        const node = evt.target;
        if (node.data("isCluster")) return;
        focusNode(node.id());
      });
      cy.on("tap", (evt) => {
        if (evt.target !== cy) return;
        // Coarse-pointer fallback: if the tap landed near a node, select that
        // node instead of clearing the selection. Fixes "I can't tap this
        // small node" on mobile.
        const coarse = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
        if (coarse && evt.position) {
          const { x: tx, y: ty } = evt.position;
          let best = null;
          let bestDist2 = Infinity;
          const RADIUS_PX = 20;
          const zoom = cy.zoom() || 1;
          const thresh2 = (RADIUS_PX / zoom) * (RADIUS_PX / zoom);
          cy.nodes().forEach((n) => {
            if (n.data("isCluster")) return;
            const p = n.position();
            const dx = p.x - tx;
            const dy = p.y - ty;
            const d2 = dx * dx + dy * dy;
            if (d2 < thresh2 && d2 < bestDist2) {
              best = n;
              bestDist2 = d2;
            }
          });
          if (best) {
            focusNode(best.id());
            return;
          }
        }
        selectedNodeId = null;
        styleSelectedSubgraph(null);
      });

      // Drain the elements array into cytoscape in idle-callback chunks so the
      // main thread stays responsive (avoids "page unresponsive" dialogs on the
      // initial load with the lite payload).
      const localCy = cy;
      const CHUNK = 1500;
      let drainIdx = 0;
      function pumpElements() {
        if (myGen !== cyBuildGen || cy !== localCy) return;
        const slice = elements.slice(drainIdx, drainIdx + CHUNK);
        if (slice.length) {
          try {
            cy.startBatch();
            cy.add(slice);
          } finally {
            cy.endBatch();
          }
        }
        drainIdx += CHUNK;
        if (drainIdx < elements.length) {
          scheduleIdle(pumpElements);
        } else {
          // Initial paint: zoom out far enough to show the full corpus, then
          // pull back further so the viewer lands on a wide overview rather
          // than a tightly-fitted shot. cy.fit() is followed by an explicit
          // 0.55x zoom so cluster labels and outermost nodes have breathing
          // room on every viewport size.
          try {
            cy.fit(undefined, 80);
            const fitZoom = Number(cy.zoom()) || 1;
            cy.zoom({ level: fitZoom * 0.55, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
            cy.center();
          } catch (_) {}
          if (typeof onReady === "function") {
            try { onReady(); } catch (_) { /* swallow */ }
          }
        }
      }
      scheduleIdle(pumpElements);

      return true;
    } catch (err) {
      showFatalOverlay("Explorer renderer crashed during graph construction", `${err && err.message ? err.message : err}\n${err && err.stack ? err.stack : ""}`);
      return false;
    }
  }

  function renderJourneyButton(id) {
    const inList = journeySelection.includes(id);
    const cls = inList ? "btn-in-list" : "btn-add";
    const label = inList ? "In list ✓" : "Add to list";
    const pressed = inList ? "true" : "false";
    return `<button class="${cls}" data-journey-toggle="${id}" aria-pressed="${pressed}">${label}</button>`;
  }

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

  function refreshJourneyButtons() {
    const nodes = document.querySelectorAll("[data-journey-toggle]");
    nodes.forEach((btn) => {
      const id = btn.getAttribute("data-journey-toggle");
      if (!id) return;
      const inList = journeySelection.includes(id);
      btn.classList.toggle("btn-in-list", inList);
      btn.classList.toggle("btn-add", !inList);
      btn.setAttribute("aria-pressed", inList ? "true" : "false");
      btn.textContent = inList ? "In list ✓" : "Add to list";
    });
  }

  // Cross-page pub/sub + facade for the shared journey paper selection.
  const journeyEventTarget = typeof EventTarget === "function" ? new EventTarget() : null;
  function normalizeIds(value) {
    const raw = Array.isArray(value) ? value : [value];
    const seen = new Set();
    const out = [];
    raw.forEach((entry) => {
      const id = String(entry || "").trim();
      if (!id || seen.has(id)) return;
      seen.add(id);
      out.push(id);
    });
    return out;
  }
  function notifyJourneyChange() {
    try {
      if (journeyEventTarget) {
        const evt = typeof CustomEvent === "function"
          ? new CustomEvent("change", { detail: { ids: [...journeySelection] } })
          : new Event("change");
        journeyEventTarget.dispatchEvent(evt);
      }
    } catch (_err) {
      // no-op: event dispatch must never break UI flows
    }
  }

  function applySelectionMutation(didChange) {
    if (!didChange) return;
    persistSelection();
    invalidateCommunityCache();
    renderJourneySelection();
    refreshJourneyButtons();
    notifyJourneyChange();
    if (selectedNodeId) renderPaper(selectedNodeId);
  }

  function addJourneyIds(ids) {
    const normalized = normalizeIds(ids);
    let added = 0;
    normalized.forEach((id) => {
      if (journeySelection.includes(id)) return;
      journeySelection.push(id);
      added += 1;
    });
    applySelectionMutation(added > 0);
    return added;
  }

  function removeJourneyIds(ids) {
    const normalized = new Set(normalizeIds(ids));
    if (!normalized.size) return 0;
    const before = journeySelection.length;
    journeySelection = journeySelection.filter((id) => !normalized.has(id));
    const removed = before - journeySelection.length;
    applySelectionMutation(removed > 0);
    return removed;
  }

  function installJourneyFacade() {
    window.mskbJourney = {
      addIds(ids) {
        return addJourneyIds(ids);
      },
      removeIds(ids) {
        return removeJourneyIds(ids);
      },
      has(id) {
        const key = String(id || "").trim();
        return key ? journeySelection.includes(key) : false;
      },
      getIds() {
        return [...journeySelection];
      },
      clear() {
        const count = journeySelection.length;
        journeySelection = [];
        applySelectionMutation(count > 0);
        return count;
      },
      subscribe(callback) {
        if (typeof callback !== "function" || !journeyEventTarget) {
          return () => {};
        }
        const handler = (event) => {
          const ids = event && event.detail && Array.isArray(event.detail.ids)
            ? event.detail.ids
            : [...journeySelection];
          callback(ids);
        };
        journeyEventTarget.addEventListener("change", handler);
        return () => {
          try {
            journeyEventTarget.removeEventListener("change", handler);
          } catch (_err) {
            // no-op
          }
        };
      },
    };
  }
  installJourneyFacade();

  function renderActionButtons(node) {
    return `<button data-focus="${node.id}">Focus</button> ${renderJourneyButton(node.id)}`;
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
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass("dim in out both focus eIn eOut eBridge");
      if (!selectedNodeId) return;
      const focusEl = cy.getElementById(selectedNodeId);
      if (!focusEl || !focusEl.length) return;
      // Cluster label nodes are never dimmed/classified.
      const paperNodes = cy.nodes("[!isCluster]");
      const incomingEdges = focusEl.incomers("edge");
      const outgoingEdges = focusEl.outgoers("edge");
      const incomingNodes = focusEl.incomers("node");
      const outgoingNodes = focusEl.outgoers("node");
      const bothNodes = incomingNodes.intersection(outgoingNodes);
      paperNodes.addClass("dim");
      cy.edges().addClass("dim");
      focusEl.removeClass("dim").addClass("focus");
      incomingNodes.removeClass("dim").addClass("in");
      outgoingNodes.removeClass("dim").addClass("out");
      bothNodes.removeClass("in out").addClass("both");
      incomingEdges.removeClass("dim").addClass("eIn");
      outgoingEdges.removeClass("dim").addClass("eOut");
    });
  }

  function setPreset(mode) {
    if (mode === "undergrad") {
      coreMetricEl.value = "composite";
      if (readingLevelEl) readingLevelEl.value = "basic";
      minInDegreeEl.value = "3";
      minOutDegreeEl.value = "3";
      minKcoreEl.value = "6";
      corePctEl.value = "20";
      requireAbstractEl.checked = true;
    } else if (mode === "grad") {
      coreMetricEl.value = "pagerank";
      if (readingLevelEl) readingLevelEl.value = "advanced";
      minInDegreeEl.value = "8";
      minOutDegreeEl.value = "8";
      minKcoreEl.value = "12";
      corePctEl.value = "60";
      requireAbstractEl.checked = true;
    } else {
      coreMetricEl.value = "composite";
      if (readingLevelEl) readingLevelEl.value = "basic";
      minInDegreeEl.value = "5";
      minOutDegreeEl.value = "5";
      minKcoreEl.value = "10";
      corePctEl.value = "40";
      requireAbstractEl.checked = true;
    }
    if (readingLevelEl) persistReadingLevel(readingLevelEl.value);
    corePctValueEl.textContent = `${corePctEl.value}%`;
    applyCoreFilter();
    if (selectedNodeId) renderPaper(selectedNodeId);
  }

  function applyCoreFilter() {
    const metric = coreMetricEl ? (coreMetricEl.value || "composite") : "composite";
    const minInDegree = Math.max(0, Number(minInDegreeEl ? (minInDegreeEl.value || 0) : 0));
    const minOutDegree = Math.max(0, Number(minOutDegreeEl ? (minOutDegreeEl.value || 0) : 0));
    const minKcore = Math.max(0, Number(minKcoreEl ? (minKcoreEl.value || 0) : 0));
    const cutoff = Number(corePctEl ? (corePctEl.value || 0) : 0) / 100;
    const requireAbstract = requireAbstractEl ? !!requireAbstractEl.checked : false;
    if (corePctValueEl) {
      corePctValueEl.textContent = `${Math.round(cutoff * 100)}%`;
    }

    const matchedNodes = rawNodes
        .filter(n => !requireAbstract || !!n.has_abstract)
        .filter(n => Number(n.in_degree || 0) >= minInDegree)
        .filter(n => Number(n.out_degree || 0) >= minOutDegree)
        .filter(n => Number(n.kcore || 0) >= minKcore)
        .filter(n => {
          if (metric === "pagerank") return (n.rank_pagerank || 0) >= cutoff;
          if (metric === "kcore") return (n.rank_kcore || 0) >= cutoff;
          if (metric === "in_degree") return (n.rank_in_degree || 0) >= cutoff;
          if (metric === "age_normalized") return (n.rank_age_normalized_importance || 0) >= cutoff;
          // Composite uses rank_core_score (computed in buildRankIndexes), NOT
          // the raw core_score, so the percentile slider behaves like the other
          // metrics: cutoff=0.4 keeps the top 60% by composite rank.
          return (n.rank_core_score || 0) >= cutoff;
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
    kcoreThresholds = computeKcoreThresholds(visibleNodes);
    if (!hasExplorerGraph) {
      selectedNodeId = null;
      selectedIncoming = new Set();
      selectedOutgoing = new Set();
      selectedIncident = new Set();
      return;
    }
    if (visibleNodes.length) {
      const positionById = buildCommunityPositions(visibleNodes);
      // Capture the initial-focus target up-front; it'll be invoked from the
      // chunked-build onReady callback below, after all elements are added.
      const initialFocusTarget =
        [...visibleNodes].sort((a, b) => (b.importance || 0) - (a.importance || 0))[0];
      buildCytoscapeGraph(positionById, () => {
        styleSelectedSubgraph(null);
        if (initialFocusTarget) {
          try { focusNode(initialFocusTarget.id); }
          catch (_) { /* swallow */ }
        }
      });
    } else {
      detailsEl.innerHTML = "No papers match the current core filter.";
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
        // Bail if the user selected a different paper while details were loading.
        if (selectedNodeId && selectedNodeId !== id) return;
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
    const level = currentReadingLevel();
    const summaryVariant = (level === "advanced" && node.summary_advanced)
      ? node.summary_advanced
      : (level === "basic" && node.summary_basic)
        ? node.summary_basic
        : (node.summary || node.summary_basic || node.summary_advanced || "");
    const whyVariant = (level === "advanced" && node.why_it_matters_advanced)
      ? node.why_it_matters_advanced
      : (level === "basic" && node.why_it_matters_basic)
        ? node.why_it_matters_basic
        : (node.why_it_matters || node.why_it_matters_basic || node.why_it_matters_advanced || "");
    const takeawaysVariant = (level === "advanced" && Array.isArray(node.key_takeaways_advanced) && node.key_takeaways_advanced.length)
      ? node.key_takeaways_advanced
      : (level === "basic" && Array.isArray(node.key_takeaways_basic) && node.key_takeaways_basic.length)
        ? node.key_takeaways_basic
        : (Array.isArray(node.key_takeaways) && node.key_takeaways.length
          ? node.key_takeaways
          : (Array.isArray(node.key_takeaways_basic) ? node.key_takeaways_basic : []));
    const summary = cleanNarrativeText(summaryVariant || "");
    const topic = node.topic_label ? `<span class="pill">${escapeHtml(node.topic_label)}</span>` : "";
    const levelLabel = level === "advanced" ? "Advanced (specialist)" : "Basic (plain language)";
    const diff = `<span class="pill">Reading level: ${levelLabel}</span>`;
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
    const journeyToggle = renderJourneyButton(node.id);
    const flagLink = renderFlagLink(node.id, node.title);
    const takeaways = Array.isArray(takeawaysVariant) ? takeawaysVariant : [];
    const strippedTakeaways = takeaways
      .map(t => String(t || "").replace(/^(opportunity|challenge|action|resolution)\s*:\s*/i, "").trim())
      .filter(Boolean);
    const takeawayHtml = strippedTakeaways.length
      ? `<ul>${strippedTakeaways.map(t => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`
      : "<p>No key takeaways available.</p>";
    const abstractText = cleanNarrativeText(node.abstract || "");
    const why = cleanNarrativeText(whyVariant || "");
    const disclaimer = String(node.summary_disclaimer || "").trim();
    const metricsPills = [diff, kTierPill, evidencePill, certaintyPill, ageNormScorePill, cpyPill, linkCounts, paperRankPill, paperAgeRankPill, authorRankPill]
      .filter(Boolean)
      .join("");

    detailsEl.innerHTML = `
      <article class="paper-card-detail">
        <header class="pcd-header">
          <h4 class="pcd-title">${escapeHtml(node.title || "Untitled")}<span class="pcd-year">${year}</span></h4>
          ${authorName ? `<p class="pcd-byline">${escapeHtml(authorName)}</p>` : ""}
        </header>

        ${topic ? `<div class="pcd-taxonomy">${topic}</div>` : ""}
        ${metricsPills ? `<div class="pcd-pills">${metricsPills}</div>` : ""}

        ${why ? `
          <section class="pcd-section">
            <h5>Why it matters</h5>
            <p>${escapeHtml(why)}</p>
          </section>` : ""}

        <section class="pcd-section">
          <h5>Plain-language summary</h5>
          <p>${escapeHtml(summary || "No summary available.")}</p>
        </section>

        ${strippedTakeaways.length ? `
          <section class="pcd-section">
            <h5>Key takeaways</h5>
            ${takeawayHtml}
          </section>` : ""}

        <section class="pcd-section">
          <h5>Abstract</h5>
          <p>${escapeHtml(abstractText || "No abstract available.")}</p>
        </section>

        <footer class="pcd-footer">
          <div class="pcd-actions">${journeyToggle}${flagLink}</div>
          <div class="pcd-links">${sourceLink} · ${bibLink}</div>
          <p class="pcd-bibtext">${escapeHtml(citationPlaintext)}</p>
          <details class="pcd-provenance">
            <summary>Summary provenance &amp; disclaimer</summary>
            <p class="pcd-prov-body">${provenance}</p>
            ${disclaimer ? `<p class="pcd-disclaimer"><em>${escapeHtml(disclaimer)}</em></p>` : ""}
          </details>
        </footer>
      </article>
    `;
    renderRelationshipNavigator(id);
  }

  function focusNode(id) {
    if (!nodeById.has(id) || !cy) return;
    styleSelectedSubgraph(id);
    const el = cy.getElementById(id);
    if (el && el.length) {
      try {
        const current = Number(cy.zoom()) || 1;
        const target = Math.min(Math.max(current, 1.2), cy.maxZoom());
        cy.animate({ center: { eles: el }, zoom: target }, { duration: 280 });
      } catch (_) {}
    }
    renderPaper(id);
  }

  function toggleJourneySelection(id) {
    const key = String(id || "").trim();
    if (!key) return;
    if (journeySelection.includes(key)) {
      removeJourneyIds([key]);
    } else {
      addJourneyIds([key]);
    }
    if (directSearchInputEl && (directSearchInputEl.value || "").trim()) {
      runDirectSearch();
    }
    if (ideaInputEl && (ideaInputEl.value || "").trim()) {
      runIdeaMatch();
    }
  }

  function clearJourneySelection() {
    if (!journeySelection.length) return;
    if (typeof window.confirm === "function" && !window.confirm("Clear all relevant papers from your working list?")) {
      return;
    }
    removeJourneyIds([...journeySelection]);
  }

  function invalidateCommunityCache() {
    communityMarkdownCache = "";
    if (communityDownloadEl) communityDownloadEl.disabled = true;
    if (communityStatsEl) communityStatsEl.innerHTML = "";
    if (communityResultsEl) communityResultsEl.innerHTML = "";
  }

  function renderJourneySelection() {
    if (selectionCountEl) {
      selectionCountEl.textContent = String(journeySelection.length);
    }
    if (!journeySelectedEl) return;
    if (!journeySelection.length) {
      journeySelectedEl.innerHTML = `<p class="selection-empty">No papers added yet. Click any node in the graph to view its details, then use the <em>Add</em> button to build your relevant papers list. The list is saved in your browser and shared by every tool below.</p>`;
      return;
    }
    const items = journeySelection.map((id, i) => {
      const node = nodeById.get(id);
      if (!node) {
        return `<li class="selection-item"><span class="selection-index">${i + 1}.</span><div class="selection-title"><em>Unknown paper</em><span class="selection-meta">id: ${escapeHtml(id)} (not in current corpus)</span></div><div class="selection-actions"><button data-journey-toggle="${escapeHtml(id)}">Remove</button></div></li>`;
      }
      const yr = Number.isFinite(Number(node.year)) ? Math.trunc(Number(node.year)) : null;
      const author = String(node.first_author || "").trim();
      const metaParts = [];
      if (author) metaParts.push(escapeHtml(author));
      if (yr) metaParts.push(String(yr));
      if (node.topic_label) metaParts.push(escapeHtml(node.topic_label));
      const meta = metaParts.length ? `<span class="selection-meta">${metaParts.join(" · ")}</span>` : "";
      return `
        <li class="selection-item">
          <span class="selection-index">${i + 1}.</span>
          <div class="selection-title">
            ${escapeHtml(node.title || "Untitled")}
            ${meta}
          </div>
          <div class="selection-actions">
            <button data-focus="${node.id}">Focus</button>
            <button data-journey-toggle="${node.id}">Remove</button>
            ${renderFlagLink(node.id, node.title)}
          </div>
        </li>
      `;
    }).join("");
    journeySelectedEl.innerHTML = `<ol class="selection-list">${items}</ol>`;
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

  // Generic-sounding terms that leak in from structured takeaways and offer
  // no real learning signal for students planning a study path.
  const JOURNEY_SKILL_STOPWORDS = new Set([
    "multiple sclerosis",
    "ms",
    "patient",
    "patients",
    "study",
    "studies",
    "result",
    "results",
    "method",
    "methods",
    "conclusion",
    "background",
    "data",
    "analysis",
  ]);

  function collectConcepts(nodes) {
    const counts = new Map();
    const definitions = new Map();
    const display = new Map();
    nodes.forEach((node) => {
      const jargon = Array.isArray(node && node.jargon) ? node.jargon : [];
      jargon.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        const term = String(entry.term || "").trim();
        if (!term) return;
        const key = term.toLowerCase();
        if (JOURNEY_SKILL_STOPWORDS.has(key)) return;
        counts.set(key, (counts.get(key) || 0) + 1);
        if (!display.has(key)) display.set(key, term);
        if (!definitions.has(key) || !definitions.get(key)) {
          definitions.set(key, String(entry.definition || "").trim());
        }
      });
    });
    return Array.from(counts.keys())
      .sort((a, b) => (counts.get(b) - counts.get(a)) || a.localeCompare(b))
      .map((key) => ({
        term: display.get(key) || key,
        definition: definitions.get(key) || "",
        count: counts.get(key) || 0,
      }));
  }

  function renderSkillsBlock(nodes, limit) {
    const concepts = collectConcepts(nodes).slice(0, limit || 10);
    if (!concepts.length) {
      return `
        <div class="journey-skills">
          <strong>Concepts &amp; skills to master</strong>
          <p><em>No concept tags available for these papers yet. Generate a journey after text details finish loading, or pick papers with distilled summaries.</em></p>
        </div>`;
    }
    const items = concepts.map((c) => {
      const safeTerm = escapeHtml(c.term);
      if (c.definition) {
        return `<li class="journey-skill--concept"><details><summary>${safeTerm}</summary><p>${escapeHtml(c.definition)}</p></details></li>`;
      }
      return `<li class="journey-skill--concept">${safeTerm}</li>`;
    }).join("");
    return `
      <div class="journey-skills">
        <strong>Concepts &amp; skills to master</strong>
        <ul>${items}</ul>
      </div>`;
  }

  function renderJourneyPhase({ title, description, nodes, emptyText, skillLimit }) {
    return `
      <section class="journey-phase">
        <h5>${title}</h5>
        <p>${description}</p>
        ${renderJourneyList(nodes, emptyText)}
        ${renderSkillsBlock(nodes, skillLimit)}
      </section>`;
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

    const topicSet = new Set();
    [...foundations, ...bridges, ...deepDives].forEach((node) => {
      const label = (node && node.topic_label) ? String(node.topic_label).trim() : "";
      if (label) topicSet.add(label);
    });
    const topicSummary = topicSet.size
      ? `<p><em>Research themes touched:</em> ${Array.from(topicSet).map((t) => `<span class="pill">${escapeHtml(t)}</span>`).join(" ")}</p>`
      : "";

    journeyResultsEl.innerHTML = `
      <p><strong>Generated learning journey</strong> — each phase pairs papers with the concepts and skills they teach.</p>
      ${topicSummary}
      ${renderJourneyPhase({
        title: "1. Foundations (start here)",
        description: "Core papers you already selected, ordered from the most accessible language to the most technical.",
        nodes: foundations,
        emptyText: "No foundation papers found.",
        skillLimit: 10,
      })}
      ${renderJourneyPhase({
        title: "2. Bridges (connect mechanisms to applications)",
        description: "Neighboring papers that link your selection to adjacent work — read these to fill gaps between ideas.",
        nodes: bridges,
        emptyText: "No bridge papers found from selected set.",
        skillLimit: 10,
      })}
      ${renderJourneyPhase({
        title: "3. Deep Dives (advanced extensions)",
        description: "Higher-signal follow-up reading for when the foundations feel comfortable.",
        nodes: deepDives,
        emptyText: "No deep-dive recommendations found.",
        skillLimit: 12,
      })}
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
      const minInDegree = Math.max(0, Number(minInDegreeEl.value || 0));
      const minOutDegree = Math.max(0, Number(minOutDegreeEl.value || 0));
      const minKcore = Math.max(0, Number(minKcoreEl.value || 0));
      const cutoff = Number(corePctEl.value || 0) / 100;
      const requireAbstract = !!requireAbstractEl.checked;
      if (requireAbstract && !n.has_abstract) return false;
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

  let communityMarkdownCache = "";

  function buildCommunityMarkdown(selected, reading, anchors, companions, topTopics, intraEdges, density) {
    const lines = [];
    const today = new Date().toISOString().slice(0, 10);
    lines.push(`# Community Reading List`);
    lines.push("");
    lines.push(`*Generated ${today} from the MS Knowledge Base explorer.*`);
    lines.push("");
    lines.push(`## Stats`);
    lines.push("");
    lines.push(`- Papers in selection: **${selected.length}**`);
    lines.push(`- Internal citations (intra-set edges): **${intraEdges}**`);
    lines.push(`- Density: **${density.toFixed(3)}**`);
    if (topTopics.length) {
      lines.push(`- Dominant topics: ${topTopics.map(([t, c]) => `${t} (${c})`).join("; ")}`);
    }
    lines.push("");
    if (anchors.length) {
      lines.push(`## Anchor papers (most internally cited)`);
      lines.push("");
      anchors.forEach((n, i) => {
        const yr = n.year ? ` (${n.year})` : "";
        const author = n.first_author ? `${n.first_author}. ` : "";
        const link = n.source_url ? ` <${n.source_url}>` : "";
        lines.push(`${i + 1}. ${author}${n.title}${yr}.${link}`);
      });
      lines.push("");
    }
    lines.push(`## Reading order (chronological)`);
    lines.push("");
    reading.forEach((n, i) => {
      const yr = n.year ? ` (${n.year})` : "";
      const author = n.first_author ? `${n.first_author}. ` : "";
      const link = n.source_url ? ` <${n.source_url}>` : "";
      const cites = (n.citation_count || 0) > 0 ? ` [${n.citation_count} citations]` : "";
      lines.push(`${i + 1}. ${author}${n.title}${yr}.${link}${cites}`);
    });
    lines.push("");
    if (companions.length) {
      lines.push(`## Suggested companion papers`);
      lines.push("");
      lines.push(`Papers in the current visible graph that connect to multiple papers in the selection:`);
      lines.push("");
      companions.forEach(({ node, count }, i) => {
        const yr = node.year ? ` (${node.year})` : "";
        const author = node.first_author ? `${node.first_author}. ` : "";
        const link = node.source_url ? ` <${node.source_url}>` : "";
        lines.push(`${i + 1}. ${author}${node.title}${yr}.${link} — ${count} link${count === 1 ? "" : "s"} into selection`);
      });
      lines.push("");
    }
    return lines.join("\n");
  }

  async function generateCommunityReadingList() {
    const selected = journeySelection.map((id) => nodeById.get(id)).filter(Boolean);
    if (selected.length < 2) {
      communityStatsEl.innerHTML = "";
      communityResultsEl.innerHTML = "<p>Add at least 2 papers to your selection (use the Add buttons in search results or paper details).</p>";
      communityDownloadEl.disabled = true;
      return;
    }
    if (!(detailsById instanceof Map) && !detailsLoadError) {
      communityResultsEl.innerHTML = "<p>Loading text details...</p>";
      await ensureDetailsLoaded();
    }

    const idSet = new Set(selected.map((n) => n.id));
    let intraEdges = 0;
    const inSubset = new Map();
    selected.forEach((n) => inSubset.set(n.id, 0));
    selected.forEach((n) => {
      (outgoing.get(n.id) || new Set()).forEach((target) => {
        if (idSet.has(target)) {
          intraEdges += 1;
          inSubset.set(target, (inSubset.get(target) || 0) + 1);
        }
      });
    });
    const possible = selected.length * (selected.length - 1);
    const density = possible ? (intraEdges / possible) : 0;

    const candidate = new Map();
    selected.forEach((n) => {
      const neighbors = new Set([
        ...(incoming.get(n.id) || []),
        ...(outgoing.get(n.id) || []),
      ]);
      neighbors.forEach((other) => {
        if (idSet.has(other)) return;
        candidate.set(other, (candidate.get(other) || 0) + 1);
      });
    });
    const companions = Array.from(candidate.entries())
      .filter(([, cnt]) => cnt >= 2)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([id, count]) => ({ node: nodeById.get(id), count }))
      .filter((x) => x.node);

    const topicCount = new Map();
    selected.forEach((n) => {
      const t = (n.topic_label || "").trim() || "(unlabeled)";
      topicCount.set(t, (topicCount.get(t) || 0) + 1);
    });
    const topTopics = Array.from(topicCount.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    const anchors = [...selected]
      .sort((a, b) => (inSubset.get(b.id) || 0) - (inSubset.get(a.id) || 0))
      .slice(0, 5);

    const reading = [...selected].sort((a, b) =>
      (Number(a.year || 9999) - Number(b.year || 9999))
      || ((b.citation_count || 0) - (a.citation_count || 0))
    );

    communityMarkdownCache = buildCommunityMarkdown(
      selected, reading, anchors, companions, topTopics, intraEdges, density
    );
    communityDownloadEl.disabled = false;

    communityStatsEl.innerHTML = `
      <dl>
        <dt>Papers</dt><dd>${selected.length}</dd>
        <dt>Intra-set edges</dt><dd>${intraEdges}</dd>
        <dt>Density</dt><dd>${density.toFixed(3)}</dd>
        <dt>Top topics</dt><dd>${topTopics.map(([t, c]) => `${escapeHtml(t)} (${c})`).join(", ") || "—"}</dd>
      </dl>
    `;

    const anchorHtml = anchors.length
      ? `<h5>Anchor papers</h5><ol>${anchors.map((n) =>
          `<li>${renderActionButtons(n)} ${escapeHtml(n.title || "Untitled")}<em> — ${inSubset.get(n.id) || 0} internal citations</em></li>`
        ).join("")}</ol>`
      : "";
    const readingHtml = `<h5>Reading order (chronological)</h5><ol>${reading.map((n) => {
      const yr = n.year ? ` <em>(${n.year})</em>` : "";
      return `<li>${renderActionButtons(n)} ${escapeHtml(n.title || "Untitled")}${yr}</li>`;
    }).join("")}</ol>`;
    const companionHtml = companions.length
      ? `<h5>Companion papers (≥2 links into selection)</h5><ol>${companions.map(({ node, count }) =>
          `<li>${renderActionButtons(node)} ${escapeHtml(node.title || "Untitled")}<em> — ${count} link${count === 1 ? "" : "s"}</em></li>`
        ).join("")}</ol>`
      : "<p><em>No companion papers found in current visible graph. Try widening filters or loading the full corpus.</em></p>";

    communityResultsEl.innerHTML = anchorHtml + readingHtml + companionHtml;
  }

  function downloadCommunityMarkdown() {
    if (!communityMarkdownCache) return;
    const blob = new Blob([communityMarkdownCache], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mskb-reading-list-${new Date().toISOString().slice(0, 10)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 200);
  }

  function downloadTextFile(filename, text, mimeType) {
    const blob = new Blob([text], { type: `${mimeType || "text/plain"};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    setTimeout(() => URL.revokeObjectURL(url), 200);
  }

  function setJourneyIoStatus(message, isError = false) {
    if (!journeyIoStatusEl) return;
    const safe = escapeHtml(String(message || ""));
    journeyIoStatusEl.innerHTML = isError ? `<p><strong>${safe}</strong></p>` : `<p><em>${safe}</em></p>`;
  }

  function exportJourneyJSON() {
    const papers = journeySelection.map((id) => nodeById.get(id)).filter(Boolean).map((node) => ({
      id: node.id,
      title: node.title || "Untitled",
      year: node.year || null,
      doi: node.doi || "",
      source_url: node.source_url || "",
      citation: citationPlaintextForNode(node),
    }));
    const payload = {
      version: 1,
      exported_at_utc: new Date().toISOString(),
      paper_ids: [...journeySelection],
      papers,
    };
    downloadTextFile(
      `mskb-journey-${new Date().toISOString().slice(0, 10)}.json`,
      `${JSON.stringify(payload, null, 2)}\n`,
      "application/json"
    );
    setJourneyIoStatus(`Exported ${journeySelection.length} paper ids to JSON.`);
  }

  function exportJourneyBibtex() {
    const rows = journeySelection.map((id) => nodeById.get(id)).filter(Boolean);
    if (!rows.length) {
      setJourneyIoStatus("No selected papers with citation metadata available for BibTeX export.", true);
      return;
    }
    const text = rows.map((node) => citationBibtexForNode(node)).join("\n\n");
    downloadTextFile(
      `mskb-journey-${new Date().toISOString().slice(0, 10)}.bib`,
      `${text}\n`,
      "application/x-bibtex"
    );
    setJourneyIoStatus(`Exported ${rows.length} papers to BibTeX.`);
  }

  function exportJourneyMarkdown() {
    const rows = journeySelection.map((id) => nodeById.get(id)).filter(Boolean);
    const lines = [
      "# MSKB Journey Export",
      "",
      `Generated: ${new Date().toISOString()}`,
      "",
      "## Selected papers",
      "",
    ];
    if (!rows.length) {
      lines.push("_No known papers from current corpus. IDs only:_");
      lines.push("");
      journeySelection.forEach((id, idx) => lines.push(`${idx + 1}. ${id}`));
    } else {
      rows.forEach((node, idx) => {
        const line = `${idx + 1}. ${citationPlaintextForNode(node)}`;
        lines.push(line);
      });
    }
    downloadTextFile(
      `mskb-journey-${new Date().toISOString().slice(0, 10)}.md`,
      `${lines.join("\n")}\n`,
      "text/markdown"
    );
    setJourneyIoStatus(`Exported ${journeySelection.length} paper ids to Markdown.`);
  }

  async function importJourneyFile(file) {
    if (!file) return;
    let parsed = null;
    try {
      const text = await file.text();
      parsed = JSON.parse(text);
    } catch (err) {
      setJourneyIoStatus(`Import failed: invalid JSON (${err && err.message ? err.message : err}).`, true);
      return;
    }
    const ids = Array.isArray(parsed)
      ? parsed
      : (Array.isArray(parsed.paper_ids) ? parsed.paper_ids : (Array.isArray(parsed.ids) ? parsed.ids : []));
    const normalized = normalizeIds(ids);
    if (!normalized.length) {
      setJourneyIoStatus("Import failed: no paper ids found (expected array or {paper_ids:[...]}).", true);
      return;
    }
    const added = addJourneyIds(normalized);
    setJourneyIoStatus(`Imported ${normalized.length} ids (${added} new).`);
    if (journeyImportEl) journeyImportEl.value = "";
  }

  function normalizeTopicParam(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (text.startsWith("topic:")) return text.slice("topic:".length);
    if (text.startsWith("topic::")) return text.slice("topic::".length);
    return text;
  }

  let researchMapSeedPromise = null;
  async function preloadSeedTopicPapers(topicSeedId) {
    const topicId = normalizeTopicParam(topicSeedId);
    if (!topicId) return;
    if (!researchMapSeedPromise) {
      researchMapSeedPromise = fetch("/mskb/assets/research_map_graph.json")
        .then((res) => {
          if (!res.ok) throw new Error(`research_map_graph.json request failed (${res.status})`);
          return res.json();
        })
        .catch((_err) => null);
    }
    const payload = await researchMapSeedPromise;
    if (!payload || !payload.seed_topic_papers) return;
    const seed = payload.seed_topic_papers[String(topicId)] || payload.seed_topic_papers[normalizeTopicParam(topicId)];
    if (!Array.isArray(seed) || !seed.length) return;
    addJourneyIds(seed);
    setJourneyIoStatus(`Seeded ${seed.length} papers from topic ${topicId}.`);
  }

  function wireJourneyIO() {
    if (journeyExportJsonEl) {
      journeyExportJsonEl.addEventListener("click", exportJourneyJSON);
    }
    if (journeyExportBibtexEl) {
      journeyExportBibtexEl.addEventListener("click", exportJourneyBibtex);
    }
    if (journeyExportMarkdownEl) {
      journeyExportMarkdownEl.addEventListener("click", exportJourneyMarkdown);
    }
    if (journeyImportEl) {
      journeyImportEl.addEventListener("change", () => {
        const file = journeyImportEl.files && journeyImportEl.files[0];
        if (file) importJourneyFile(file);
      });
    }

    const params = new URLSearchParams(window.location.search || "");
    const seedParam = normalizeTopicParam(params.get("seed"));
    const topicParam = normalizeTopicParam(params.get("topic"));
    const conceptParam = String(params.get("concept") || "").trim();

    if (spineGraphEl && window.MSKBGraph && typeof window.MSKBGraph.render === "function") {
      const initial = conceptParam
        ? `concept:${conceptParam}`
        : (topicParam ? `topic:${topicParam}` : (seedParam ? `topic:${seedParam}` : ""));
      window.MSKBGraph.render(spineGraphEl, {
        dataUrl: "/mskb/assets/learning_spine_graph.json",
        initialId: initial || undefined,
      });
    }
    if (researchGraphEl && window.MSKBGraph && typeof window.MSKBGraph.render === "function") {
      const initial = topicParam
        ? `topic:${topicParam}`
        : (conceptParam ? `concept:${conceptParam}` : "");
      window.MSKBGraph.render(researchGraphEl, {
        dataUrl: "/mskb/assets/research_map_graph.json",
        initialId: initial || undefined,
      });
    }
    if (seedParam) {
      preloadSeedTopicPapers(seedParam);
    }
  }

  function stabilizeThenSettle(amplitude = 0) {
    if (!cy) return;
    const positionById = buildCommunityPositions(visibleNodes);
    const jitter = Math.max(0, Number(amplitude) || 0);
    cy.batch(() => {
      visibleNodes.forEach((node) => {
        const el = cy.getElementById(node.id);
        if (!el || !el.length) return;
        const base = positionById.get(node.id) || { x: 0, y: 0 };
        el.position({
          x: (Number(base.x) || 0) + (Math.random() - 0.5) * jitter,
          y: (Number(base.y) || 0) + (Math.random() - 0.5) * jitter,
        });
      });
    });
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
          if (hasExplorerGraph) {
            visibleNodes = [];
            visibleEdges = [];
            rebuildAdjacency(visibleNodes, visibleEdges);
            if (corePctValueEl && corePctEl) corePctValueEl.textContent = `${corePctEl.value}%`;
            applyCoreFilter();
          } else {
            visibleNodes = rawNodes.slice();
            visibleEdges = rawEdges.slice();
            rebuildAdjacency(visibleNodes, visibleEdges);
            renderJourneySelection();
          }
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

  const shouldLoadCorpus = Boolean(
    hasExplorerGraph
    || journeyGenerateEl
    || communityGenerateEl
    || journeyExportBibtexEl
    || journeyExportMarkdownEl
  );
  if (shouldLoadCorpus) {
    setGraphStatus("Loading explorer graph...");
    loadCorpusPayload(initialPayloadCandidates).then(function () {
      pruneSelectionToCorpus();
      renderJourneySelection();
    });
  } else {
    renderJourneySelection();
  }

  [parentEl, childEl, relatedEl, directSearchResultsEl, ideaResultsEl, journeySelectedEl, journeyResultsEl, detailsEl]
    .filter(Boolean)
    .forEach((container) => {
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

  if (directSearchRunEl) directSearchRunEl.addEventListener("click", runDirectSearch);
  if (directSearchInputEl) {
    directSearchInputEl.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        runDirectSearch();
      }
    });
  }

  if (journeyGenerateEl) journeyGenerateEl.addEventListener("click", generateLearningJourney);
  if (journeyClearEl) journeyClearEl.addEventListener("click", clearJourneySelection);
  if (communityGenerateEl) communityGenerateEl.addEventListener("click", generateCommunityReadingList);
  if (communityDownloadEl) communityDownloadEl.addEventListener("click", downloadCommunityMarkdown);

  if (ideaRunEl) ideaRunEl.addEventListener("click", runIdeaMatch);
  if (coreApplyEl) coreApplyEl.addEventListener("click", applyCoreFilter);
  if (presetUndergradEl) presetUndergradEl.addEventListener("click", () => setPreset("undergrad"));
  if (presetBalancedEl) presetBalancedEl.addEventListener("click", () => setPreset("balanced"));
  if (presetGradEl) presetGradEl.addEventListener("click", () => setPreset("grad"));
  if (ideaInputEl) {
    ideaInputEl.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
        ev.preventDefault();
        runIdeaMatch();
      }
    });
  }
  if (corePctEl && corePctValueEl) {
    corePctEl.addEventListener("input", () => {
      corePctValueEl.textContent = `${corePctEl.value}%`;
    });
  }
  if (readingLevelEl) {
    const storedLevel = loadStoredReadingLevel();
    if (storedLevel) readingLevelEl.value = storedLevel;
    readingLevelEl.addEventListener("change", () => {
      persistReadingLevel(readingLevelEl.value);
      if (selectedNodeId) renderPaper(selectedNodeId);
    });
  }
  if (clusterSpreadEl) {
    const refreshSpreadLabel = () => {
      if (clusterSpreadValueEl) {
        const m = (Number(clusterSpreadEl.value || 100) / 100).toFixed(1);
        clusterSpreadValueEl.innerHTML = `${m}&times;`;
      }
    };
    refreshSpreadLabel();
    let spreadRaf = 0;
    clusterSpreadEl.addEventListener("input", () => {
      spreadMultiplier = Math.max(0.4, Number(clusterSpreadEl.value || 100) / 100);
      refreshSpreadLabel();
      if (!cy) return;
      if (spreadRaf) cancelAnimationFrame(spreadRaf);
      spreadRaf = requestAnimationFrame(() => {
        spreadRaf = 0;
        stabilizeThenSettle(0);
        try { cy.fit(undefined, 50); } catch (_) {}
      });
    });
  }
  if (loadFullCorpusEl) {
    loadFullCorpusEl.addEventListener("click", () => {
      if (isMobileView || payloadMode === "full") return;
      loadCorpusPayload([{ url: fullDataUrl, detailsUrl: fullDetailsUrl, mode: "full", label: "full" }]).then(() => {
        pruneSelectionToCorpus();
        renderJourneySelection();
      });
    });
  }
  if (relayoutEl) {
    relayoutEl.addEventListener("click", () => {
      if (isMobileView) return;
      stabilizeThenSettle(18);
    });
  }
  if (nodeDragToggleEl) {
    nodeDragToggleEl.addEventListener("click", () => {
      if (isMobileView) return;
      dragEnabled = !dragEnabled;
      draggingNode = null;
      if (cy) cy.autoungrabify(!dragEnabled);
      refreshNodeDragToggleLabel();
    });
  }
  if (isMobileView && relayoutEl) {
    relayoutEl.disabled = true;
    relayoutEl.title = "Re-layout disabled on mobile";
  }
  refreshFullCorpusButton();
  refreshNodeDragToggleLabel();
  wireJourneyIO();
  renderJourneySelection();
})();
