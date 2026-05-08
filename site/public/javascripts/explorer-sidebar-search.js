/**
 * Relocates the Citation Explorer's Direct-Search tool card into the
 * Starlight left sidebar so it sits with the rest of the site menu.
 * Falls back silently to the in-page position if the sidebar isn't found.
 */
(function moveDirectSearchToSidebar() {
  function tryMove() {
    var card = document.getElementById("direct-search-card");
    if (!card) return false;
    var selectors = [
      ".sidebar-content",
      "nav.sidebar .sidebar-content",
      ".sidebar-pane .sidebar-content",
      "starlight-menu-button + .sidebar-content",
      "aside.sidebar .sidebar-content",
      ".sidebar-pane",
      "nav.sidebar",
      "aside.sidebar",
    ];
    var host = null;
    for (var i = 0; i < selectors.length; i++) {
      host = document.querySelector(selectors[i]);
      if (host) break;
    }
    if (!host) return false;
    var slot = document.createElement("div");
    slot.className = "sidebar-explorer-search";
    slot.appendChild(card);
    host.insertBefore(slot, host.firstChild);
    return true;
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryMove);
  } else {
    tryMove();
  }
})();
