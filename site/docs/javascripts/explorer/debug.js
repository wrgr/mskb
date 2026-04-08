// Explorer boot diagnostics: an on-page debug panel + unhandled-error
// capture, extracted from explorer.js. Loaded as a classic <script> BEFORE
// explorer.js so window.__mskbDebug is available when the main IIFE runs
// and the boot diagnostics fire against the DOM that already exists above
// the script tag in explorer.md.
//
// Kept out of explorer/utils.js because this file deliberately touches
// window / document / console and is therefore not safely require-able
// from Node.
(function () {
  "use strict";

  if (typeof window === "undefined") {
    return;
  }

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
        if (closer) {
          closer.addEventListener("click", function (e) {
            e.preventDefault();
            panel.style.display = "none";
          });
        }
      }
      var line = document.createElement("div");
      var t = new Date().toISOString().slice(11, 23);
      line.textContent = "[" + t + "] " + String(msg);
      panel.appendChild(line);
      if (window.console && console.log) console.log("[mskb]", msg);
    } catch (_) { /* swallow */ }
  };

  try {
    window.__mskbDebug("boot: inline script reached");
    window.__mskbDebug("vendors: cytoscape=" + (typeof window.cytoscape));
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
