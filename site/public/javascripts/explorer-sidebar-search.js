/**
 * Relocates the Citation Explorer's Direct-Search tool card into the
 * Starlight left sidebar so it sits with the rest of the site menu.
 * Falls back silently to the in-page position if the sidebar isn't found.
 *
 * Robustness: tries on script-load, on DOMContentLoaded, on window 'load',
 * and via a MutationObserver — Starlight's <sl-sidebar-state-persist>
 * component can reflow the sidebar after our first attempt, so a single
 * one-shot move is fragile.
 */
(function moveDirectSearchToSidebar() {
  var moved = false;
  var SIDEBAR_SELECTORS = [
    "nav.sidebar .sidebar-content",
    ".sidebar-pane .sidebar-content",
    ".sidebar-content",
    ".sidebar-pane",
    "nav.sidebar",
    "aside.sidebar",
  ];

  function findSidebar() {
    for (var i = 0; i < SIDEBAR_SELECTORS.length; i++) {
      var host = document.querySelector(SIDEBAR_SELECTORS[i]);
      if (host) return host;
    }
    return null;
  }

  function tryMove() {
    if (moved) return true;
    var card = document.getElementById("direct-search-card");
    if (!card) return false;
    var host = findSidebar();
    if (!host) return false;
    // Already in the sidebar? Nothing to do.
    if (host.contains(card)) {
      moved = true;
      return true;
    }
    var slot = document.createElement("div");
    slot.className = "sidebar-explorer-search";
    slot.appendChild(card);
    host.insertBefore(slot, host.firstChild);
    moved = true;
    return true;
  }

  // Attempt 1: synchronous (script is loaded near end of body).
  if (tryMove()) return;

  // Attempt 2: on DOMContentLoaded.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryMove);
  }

  // Attempt 3: on full window load (after fonts/images settle).
  window.addEventListener("load", tryMove);

  // Attempt 4: short polling fallback for the first 2 seconds, in case
  // Starlight's hydration replaces the sidebar children after our move.
  var attempts = 0;
  var poll = setInterval(function () {
    attempts += 1;
    if (tryMove() || attempts > 20) clearInterval(poll);
  }, 100);

  // Attempt 5: observe DOM mutations on body. If Starlight removes our
  // injected wrapper or replaces the sidebar, re-run the move.
  if (typeof MutationObserver === "function") {
    var obs = new MutationObserver(function () {
      var card = document.getElementById("direct-search-card");
      if (!card) return;
      var host = findSidebar();
      if (host && !host.contains(card)) {
        moved = false;
        tryMove();
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }
})();
