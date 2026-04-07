# Debug Graph

Minimal sigma + graphology smoke test. No filters, no JSON fetch, no theme integration. Five hardcoded nodes and four edges. If this renders a graph, the vendor stack works in your browser; if it doesn't, the green debug panel in the bottom-left will say why.

<script src="../javascripts/vendor/graphology.umd.min.js"></script>
<script src="../javascripts/vendor/sigma.min.js"></script>

<div id="debug-graph-container" style="width:100%;height:60vh;border:1px solid #888;border-radius:8px;background:#fafafa;"></div>

<script>
(function () {
  function dbg(msg) {
    try {
      var panel = document.getElementById("mskb-debug-panel");
      if (!panel) {
        panel = document.createElement("div");
        panel.id = "mskb-debug-panel";
        panel.style.cssText = "position:fixed;left:8px;bottom:8px;z-index:999999;max-width:46vw;max-height:40vh;overflow:auto;background:#111;color:#0f0;font:11px/1.35 ui-monospace,Menlo,Consolas,monospace;padding:8px 10px;border:1px solid #0f0;border-radius:6px;white-space:pre-wrap;box-shadow:0 4px 12px rgba(0,0,0,0.4);";
        panel.innerHTML = '<strong style="color:#fff;">debug-graph</strong><br>';
        (document.body || document.documentElement).appendChild(panel);
      }
      var line = document.createElement("div");
      line.textContent = "[" + new Date().toISOString().slice(11, 23) + "] " + String(msg);
      panel.appendChild(line);
      if (window.console && console.log) console.log("[debug-graph]", msg);
    } catch (_) {}
  }

  window.addEventListener("error", function (e) {
    var m = (e && e.error && e.error.message) || (e && e.message) || "unknown error";
    var s = (e && e.error && e.error.stack) || "";
    dbg("ERROR: " + m + (s ? "\n" + s : ""));
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    dbg("REJECTION: " + ((r && r.message) || String(r)));
  });

  function boot() {
    try {
      dbg("boot: DOM ready");
      dbg("vendors: Sigma=" + (typeof window.Sigma) + " graphology=" + (typeof window.graphology));
      var container = document.getElementById("debug-graph-container");
      if (!container) { dbg("FATAL: #debug-graph-container missing"); return; }
      var rect = container.getBoundingClientRect();
      dbg("container rect: " + Math.round(rect.width) + "x" + Math.round(rect.height));

      var GraphCtor = window.graphology && (window.graphology.DirectedGraph || window.graphology.Graph);
      var SigmaCtor = window.Sigma || (window.sigma && (window.sigma.Sigma || window.sigma.default));
      if (!GraphCtor) { dbg("FATAL: no graphology constructor"); return; }
      if (!SigmaCtor) { dbg("FATAL: no Sigma constructor"); return; }
      dbg("ctors: GraphCtor=" + (typeof GraphCtor) + " SigmaCtor=" + (typeof SigmaCtor));

      var g = new GraphCtor();
      var nodes = [
        { id: "a", x: 0, y: 0, label: "Alpha", color: "#1f77b4" },
        { id: "b", x: 2, y: 1, label: "Beta", color: "#d62728" },
        { id: "c", x: -1, y: 2, label: "Gamma", color: "#2ca02c" },
        { id: "d", x: 1, y: -2, label: "Delta", color: "#9467bd" },
        { id: "e", x: -2, y: -1, label: "Epsilon", color: "#ff7f0e" },
      ];
      nodes.forEach(function (n) { g.addNode(n.id, { x: n.x, y: n.y, size: 12, label: n.label, color: n.color }); });
      var edges = [["a","b"],["a","c"],["b","d"],["c","e"]];
      edges.forEach(function (e, i) { g.addEdgeWithKey("e" + i, e[0], e[1], { size: 2, color: "#888" }); });
      dbg("graph built: " + g.order + " nodes / " + g.size + " edges");

      var renderer;
      try {
        renderer = new SigmaCtor(g, container, { renderLabels: true, allowInvalidContainer: true });
      } catch (err) {
        dbg("FATAL: Sigma ctor threw: " + (err && err.message ? err.message : err) + (err && err.stack ? "\n" + err.stack : ""));
        return;
      }
      dbg("renderer constructed: " + (renderer ? "ok" : "null"));

      setTimeout(function () {
        var canv = container.querySelectorAll("canvas");
        var rect2 = container.getBoundingClientRect();
        dbg("post-init: canvases=" + canv.length + " container=" + Math.round(rect2.width) + "x" + Math.round(rect2.height));
        if (canv.length) {
          var c0 = canv[0];
          dbg("canvas[0]: " + c0.width + "x" + c0.height + " styleW=" + c0.style.width + " styleH=" + c0.style.height);
          try {
            var gl = c0.getContext("webgl2") || c0.getContext("webgl") || c0.getContext("experimental-webgl");
            dbg("canvas[0] webgl: " + (gl ? "ok" : "MISSING"));
          } catch (e) { dbg("canvas[0] webgl probe threw: " + e); }
        }
      }, 500);
    } catch (err) {
      dbg("FATAL boot threw: " + (err && err.message ? err.message : err) + (err && err.stack ? "\n" + err.stack : ""));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
</script>
