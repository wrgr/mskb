// Pure helpers + constants used by site/docs/javascripts/explorer.js.
// Zero DOM access, zero shared mutable state: everything in this file can
// be unit-tested in Node via `require()`, and the browser reads it off
// `window.MSKBExplorerUtils` after loading it as a classic <script>.
//
// When adding a helper: it must be pure, it must not close over any
// browser-only globals, and it must work under `node --check`.
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module && typeof module.exports === "object") {
    module.exports = api;
  }
  if (root) {
    root.MSKBExplorerUtils = api;
  }
})(typeof self !== "undefined" ? self : (typeof window !== "undefined" ? window : null), function () {
  "use strict";

  // ---- Constants --------------------------------------------------------

  var categoryColors = {
    pathogenesis_and_immunology: "#1f77b4",
    imaging_and_biomarkers: "#17a2b8",
    clinical_trials_and_therapeutics: "#d62728",
    clinical_care_and_management: "#2ca02c",
    epidemiology_and_population_health: "#9467bd",
  };

  var stopWords = new Set([
    "a","an","the","and","or","but","for","with","from","that","this","into","about","using","through","between",
    "their","they","are","was","were","how","what","when","where","which","who","our","your","you","can","could",
    "should","would","will","may","might","have","has","had","been","being","its","it's","it","as","at","by","to",
    "in","on","of","if","than","then","also","we","i","he","she","them","these","those","there","here","do","does",
    "did","done","not","no","yes","up","down","over","under","new","study","paper"
  ]);

  var FIELD_WEIGHTS = {
    title: 3.4,
    abstract: 2.2,
    summary: 1.6,
    topic: 1.3,
    why: 1.0,
  };

  var QUERY_EXPANSIONS = {
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

  // ---- HTML / text helpers ---------------------------------------------

  function escapeHtml(text) {
    return (text || "").replace(/[&<>"']/g, function (ch) {
      return ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[ch];
    });
  }

  function cleanNarrativeText(text) {
    var t = String(text || "").trim();
    if (!t) return "";
    t = t.replace(/\bnan\b/gi, "").replace(/\s{2,}/g, " ").trim();
    var genericPatterns = [
      /^this\s+\d{4}(?:\.0)?\s+paper\s+in\s+.+?contributes\s+to\s+our\s+understanding\s+of\s+multiple\s+sclerosis\.?$/i,
      /^this\s+paper\s+in\s+.+?contributes\s+to\s+our\s+understanding\s+of\s+multiple\s+sclerosis\.?$/i,
    ];
    if (genericPatterns.some(function (rx) { return rx.test(t); })) {
      return "";
    }
    return t;
  }

  function formatMB(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "n/a";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  // ---- Node normalization ----------------------------------------------

  function normalizeNode(node) {
    var n = Object.assign({}, node || {});
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

  // ---- Citation helpers ------------------------------------------------

  function cleanDoi(doi) {
    var value = String(doi || "").trim();
    if (!value) return "";
    return value.replace(/^https?:\/\/doi\.org\//i, "");
  }

  function citationPlaintextForNode(node) {
    var author = String((node && node.first_author) || "").trim() || "Unknown author";
    var year = Number.isFinite(Number(node && node.year)) ? Math.trunc(Number(node.year)) : "n.d.";
    var title = String((node && node.title) || "Untitled").trim();
    var venue = String((node && node.venue) || "").trim();
    var source = String((node && node.source_url) || "").trim();
    var pieces = [author + ". (" + year + "). " + title + "."];
    if (venue) pieces.push(venue + ".");
    if (source) pieces.push(source);
    return pieces.join(" ").trim();
  }

  function citationBibtexForNode(node) {
    var id = String((node && node.id) || "paper").replace(/[^a-zA-Z0-9]/g, "").slice(0, 12);
    var year = Number.isFinite(Number(node && node.year)) ? String(Math.trunc(Number(node.year))) : "0000";
    var key = "mskb_" + id + "_" + year;
    var esc = function (s) {
      return String(s || "").replace(/\\/g, "\\\\").replace(/\{/g, "\\{").replace(/\}/g, "\\}");
    };
    var lines = [
      "@article{" + key + ",",
      "  title = {" + esc((node && node.title) || "Untitled") + "},",
      "  author = {" + esc((node && node.first_author) || "Unknown") + "},",
      "  year = {" + year + "},",
    ];
    if (node && node.venue) lines.push("  journal = {" + esc(node.venue) + "},");
    var doi = cleanDoi((node && node.doi) || "");
    if (doi) lines.push("  doi = {" + esc(doi) + "},");
    if (node && node.source_url) lines.push("  url = {" + esc(node.source_url) + "},");
    lines.push("}");
    return lines.join("\n");
  }

  // ---- Tokenization + BM25 --------------------------------------------

  function normalizeText(text) {
    return (text || "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function stemToken(token) {
    var t = token;
    if (t.length > 6 && t.endsWith("ation")) t = t.slice(0, -5);
    else if (t.length > 5 && t.endsWith("ing")) t = t.slice(0, -3);
    else if (t.length > 4 && t.endsWith("ed")) t = t.slice(0, -2);
    else if (t.length > 4 && t.endsWith("ly")) t = t.slice(0, -2);
    else if (t.length > 5 && t.endsWith("ment")) t = t.slice(0, -4);
    else if (t.length > 4 && t.endsWith("ies")) t = t.slice(0, -3) + "y";
    else if (t.length > 4 && t.endsWith("s")) t = t.slice(0, -1);
    return t;
  }

  function tokenize(text) {
    return normalizeText(text)
      .split(/\s+/)
      .filter(function (t) { return t && t.length > 1 && !stopWords.has(t); })
      .map(stemToken)
      .filter(function (t) { return t.length > 1 && !stopWords.has(t); });
  }

  function tokenCounts(tokens) {
    var m = new Map();
    for (var i = 0; i < tokens.length; i++) {
      var t = tokens[i];
      m.set(t, (m.get(t) || 0) + 1);
    }
    return m;
  }

  function nodeSetSignature(nodes) {
    if (!nodes || !nodes.length) return "0";
    var first = (nodes[0] && nodes[0].id) || "";
    var last = (nodes[nodes.length - 1] && nodes[nodes.length - 1].id) || "";
    return nodes.length + ":" + first + ":" + last;
  }

  function bm25(tf, len, avgLen, idf, k1, b) {
    if (k1 === undefined) k1 = 1.35;
    if (b === undefined) b = 0.72;
    if (!tf) return 0;
    var denom = tf + k1 * (1 - b + b * (len / Math.max(1e-9, avgLen)));
    return idf * ((tf * (k1 + 1)) / denom);
  }

  // ---- Visual helpers --------------------------------------------------

  function colorFor(node) {
    if (!node || !node.topic_label) return "#4c78a8";
    var key = (node.topic_label || "").toLowerCase();
    var entries = Object.entries(categoryColors);
    for (var i = 0; i < entries.length; i++) {
      var cat = entries[i][0];
      var color = entries[i][1];
      if (key.includes(cat.replaceAll("_", " ").split(" ")[0])) return color;
    }
    return "#4c78a8";
  }

  function nodeSizeFromCitations(node) {
    var cites = Math.max(0, Number((node && node.citation_count) || 0));
    return Math.max(4, Math.log1p(cites) * 3.2);
  }

  function quantile(sorted, q) {
    if (!sorted.length) return 0;
    var pos = (sorted.length - 1) * q;
    var base = Math.floor(pos);
    var rest = pos - base;
    if (sorted[base + 1] !== undefined) {
      return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
    }
    return sorted[base];
  }

  function computeKcoreThresholds(nodes) {
    var values = nodes
      .map(function (n) { return Number(n.kcore || 0); })
      .filter(function (v) { return Number.isFinite(v); })
      .sort(function (a, b) { return a - b; });
    if (!values.length) return { lowMax: 0, midMax: 0 };
    return {
      lowMax: quantile(values, 0.33),
      midMax: quantile(values, 0.66),
    };
  }

  // ---- Public API ------------------------------------------------------

  return {
    // constants
    categoryColors: categoryColors,
    stopWords: stopWords,
    FIELD_WEIGHTS: FIELD_WEIGHTS,
    QUERY_EXPANSIONS: QUERY_EXPANSIONS,
    // html / text
    escapeHtml: escapeHtml,
    cleanNarrativeText: cleanNarrativeText,
    formatMB: formatMB,
    // node + citation
    normalizeNode: normalizeNode,
    cleanDoi: cleanDoi,
    citationPlaintextForNode: citationPlaintextForNode,
    citationBibtexForNode: citationBibtexForNode,
    // tokenization
    normalizeText: normalizeText,
    stemToken: stemToken,
    tokenize: tokenize,
    tokenCounts: tokenCounts,
    nodeSetSignature: nodeSetSignature,
    bm25: bm25,
    // visual
    colorFor: colorFor,
    nodeSizeFromCitations: nodeSizeFromCitations,
    quantile: quantile,
    computeKcoreThresholds: computeKcoreThresholds,
  };
});
