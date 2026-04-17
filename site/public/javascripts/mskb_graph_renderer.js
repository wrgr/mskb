(() => {
  if (window.MSKBGraph && typeof window.MSKBGraph.render === "function") return;

  const DATA_CACHE = new Map();
  const SCRIPT_CACHE = new Map();

  const GROUP_COLORS = [
    "#0f766e",
    "#1d4ed8",
    "#6d28d9",
    "#b45309",
    "#be123c",
    "#0369a1",
    "#4f46e5",
    "#15803d",
  ];

  const NODE_ACTIVE = "#0b3b66";
  const NODE_DIM = "#d6dee8";
  const EDGE_BASE = "rgba(66, 84, 102, 0.26)";
  const EDGE_ACTIVE = "rgba(11, 59, 102, 0.72)";
  const EDGE_DIM = "rgba(167, 180, 194, 0.35)";

  function esc(text) {
    return String(text || "").replace(/[&<>\"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '\"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function create(tag, attrs = {}, text = "") {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      node.setAttribute(key, String(value));
    });
    if (text) node.textContent = text;
    return node;
  }

  function loadScript(src) {
    const key = String(src || "");
    if (!key) return Promise.reject(new Error("Missing script src"));
    if (SCRIPT_CACHE.has(key)) return SCRIPT_CACHE.get(key);

    const pending = new Promise((resolve, reject) => {
      const scripts = Array.from(document.getElementsByTagName("script"));
      const existing = scripts.find((script) => {
        const raw = script.getAttribute("src") || "";
        return raw === key || raw.endsWith(key);
      });

      if (existing) {
        if (existing.dataset.loaded === "true") {
          resolve();
          return;
        }
        existing.addEventListener("load", () => {
          existing.dataset.loaded = "true";
          resolve();
        }, { once: true });
        existing.addEventListener("error", () => {
          reject(new Error(`Failed to load ${key}`));
        }, { once: true });
        return;
      }

      const script = document.createElement("script");
      script.src = key;
      script.async = true;
      script.addEventListener("load", () => {
        script.dataset.loaded = "true";
        resolve();
      }, { once: true });
      script.addEventListener("error", () => {
        reject(new Error(`Failed to load ${key}`));
      }, { once: true });
      document.head.appendChild(script);
    });

    SCRIPT_CACHE.set(key, pending);
    return pending;
  }

  async function loadAnyScript(paths) {
    let lastError = null;
    for (const candidate of paths) {
      try {
        await loadScript(candidate);
        return;
      } catch (err) {
        lastError = err;
      }
    }
    if (lastError) throw lastError;
    throw new Error("No script paths provided");
  }

  async function ensureRuntime() {
    if (typeof window.graphology !== "function") {
      await loadAnyScript([
        "/mskb/javascripts/vendor/graphology.umd.min.js",
        "/javascripts/vendor/graphology.umd.min.js",
      ]);
    }
    const sigmaCtor = typeof window.Sigma === "function"
      ? window.Sigma
      : (window.Sigma && typeof window.Sigma.default === "function" ? window.Sigma.default : null);
    if (!sigmaCtor) {
      await loadAnyScript([
        "/mskb/javascripts/vendor/sigma.min.js",
        "/javascripts/vendor/sigma.min.js",
      ]);
    }

    const Graph = window.graphology;
    const Sigma = typeof window.Sigma === "function"
      ? window.Sigma
      : (window.Sigma && window.Sigma.default);

    if (typeof Graph !== "function") {
      throw new Error("Graphology runtime unavailable");
    }
    if (typeof Sigma !== "function") {
      throw new Error("Sigma runtime unavailable");
    }

    return { Graph, Sigma };
  }

  async function loadData(url) {
    const key = String(url || "");
    if (!key) throw new Error("Missing graph data URL");
    if (DATA_CACHE.has(key)) return DATA_CACHE.get(key);
    const response = await fetch(key);
    if (!response.ok) throw new Error(`Graph request failed (${response.status})`);
    const payload = await response.json();
    DATA_CACHE.set(key, payload);
    return payload;
  }

  function normalizeNodes(nodes) {
    return (Array.isArray(nodes) ? nodes : [])
      .map((node, idx) => {
        const rawPaperIds = Array.isArray(node && node.paper_ids)
          ? node.paper_ids.map((v) => String(v || "")).filter(Boolean)
          : [];
        // paper_count: explicit field beats paper_ids length
        let paperCount = rawPaperIds.length;
        if (node && Number.isFinite(Number(node.paper_count)) && Number(node.paper_count) >= 0) {
          paperCount = Math.trunc(Number(node.paper_count));
        }
        return {
          id: String(node && node.id ? node.id : `node:${idx}`),
          label: String(node && node.label ? node.label : ""),
          summary: String(node && node.summary ? node.summary : ""),
          group: String(node && node.group ? node.group : "Other"),
          // node_color: optional per-node hex override (e.g. concept section color)
          node_color: String(node && node.node_color ? node.node_color : ""),
          href: String(node && node.href ? node.href : ""),
          paper_ids: rawPaperIds,
          paper_count: paperCount,
          layer: Number.isFinite(Number(node && node.layer)) ? Math.trunc(Number(node.layer)) : 0,
          x: Number.isFinite(Number(node && node.x)) ? Number(node.x) : idx,
          y: Number.isFinite(Number(node && node.y)) ? Number(node.y) : 0,
        };
      })
      .filter((node) => node.id);
  }

  function normalizeEdges(edges) {
    return (Array.isArray(edges) ? edges : [])
      .map((edge, idx) => ({
        id: String(edge && edge.id ? edge.id : `edge:${idx}`),
        source: String(edge && edge.source ? edge.source : ""),
        target: String(edge && edge.target ? edge.target : ""),
      }))
      .filter((edge) => edge.source && edge.target && edge.source !== edge.target);
  }

  function normalizeCoordinate(value, min, max) {
    if (!Number.isFinite(value)) return 0;
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return value;
    return ((value - min) / (max - min)) * 2 - 1;
  }

  function orderGroups(groups) {
    const priority = new Map([
      ["Pathway", 0],
      ["Category", 1],
      ["Concept", 2],
    ]);
    return [...groups].sort((a, b) => {
      const pa = priority.has(a) ? priority.get(a) : 10;
      const pb = priority.has(b) ? priority.get(b) : 10;
      if (pa !== pb) return pa - pb;
      return a.localeCompare(b);
    });
  }

  function colorScale(groups) {
    const map = new Map();
    orderGroups(groups).forEach((group, idx) => {
      map.set(group, GROUP_COLORS[idx % GROUP_COLORS.length]);
    });
    return map;
  }

  function nodeSize(node) {
    const group = String(node && node.group ? node.group : "");
    const count = Number.isFinite(node && node.paper_count) ? Math.max(0, node.paper_count) : 0;
    // Log-scale boost: 0 for 0 papers, ~3.6 for 1 k papers, ~5.3 for 10 k papers
    const citationBoost = count > 0 ? Math.min(8, Math.log10(count + 1) * 2.4) : 0;
    if (group === "Pathway") return 13;
    if (group === "Category") return 15;
    // Topic nodes scale with paper / citation count
    if (group !== "Concept") return 6 + citationBoost;
    // Concept nodes: modest fixed boost from linked papers
    const conceptBoost = Math.min(2, Math.log10(count + 1));
    return 8 + conceptBoost;
  }

  // Pan the camera to a node. By default preserves the caller's current
  // zoom level — previously defaulted to 0.35 which snapped the camera
  // back to heavily-zoomed-in on every click, making zoom feel "reset".
  function centerOnNode(renderer, nodeId, ratio) {
    if (!renderer || !nodeId) return;
    const graph = renderer.getGraph();
    if (!graph || !graph.hasNode(nodeId)) return;

    const x = graph.getNodeAttribute(nodeId, "x");
    const y = graph.getNodeAttribute(nodeId, "y");
    const camera = renderer.getCamera();
    if (!camera || !Number.isFinite(x) || !Number.isFinite(y)) return;

    const currentRatio = Number.isFinite(camera.ratio) ? camera.ratio : 1;
    const targetRatio = Number.isFinite(ratio) ? ratio : currentRatio;

    if (typeof camera.animate === "function") {
      camera.animate({ x, y, ratio: targetRatio }, { duration: 350 });
    } else if (typeof camera.setState === "function") {
      camera.setState({ x, y, ratio: targetRatio });
    }
  }

  async function render(rootEl, options = {}) {
    if (!rootEl) return null;

    const dataUrl = String(options.dataUrl || "");
    const initialId = options.initialId ? String(options.initialId) : "";
    const onNodeClick = typeof options.onNodeClick === "function" ? options.onNodeClick : null;

    rootEl.innerHTML = "";
    const shell = create("div", { class: "mskb-graph-shell" });
    const controls = create("div", { class: "mskb-graph-controls" });
    const search = create("input", {
      type: "search",
      placeholder: "Search pathways, concepts, topics",
      "aria-label": "Search graph nodes",
    });
    const pills = create("div", { class: "mskb-graph-pills" });
    const actions = create("div", { class: "mskb-graph-actions" });
    const fitButton = create("button", { type: "button" }, "Reset camera");
    const resetButton = create("button", { type: "button" }, "Clear filters");
    actions.appendChild(fitButton);
    actions.appendChild(resetButton);
    controls.appendChild(search);
    controls.appendChild(pills);
    controls.appendChild(actions);

    const layout = create("div", { class: "mskb-graph-layout" });
    const canvasWrap = create("div", { class: "mskb-graph-canvas" });
    const stage = create("div", { class: "mskb-sigma-stage" });
    canvasWrap.appendChild(stage);
    const details = create("aside", { class: "mskb-graph-details" });
    details.innerHTML = "<p>Select a node to view details.</p>";

    layout.appendChild(canvasWrap);
    layout.appendChild(details);
    shell.appendChild(controls);
    shell.appendChild(layout);
    rootEl.appendChild(shell);

    let runtime;
    let payload;
    try {
      [runtime, payload] = await Promise.all([
        ensureRuntime(),
        loadData(dataUrl),
      ]);
    } catch (err) {
      details.innerHTML = `<p><strong>Graph failed to load.</strong><br/>${esc(err && err.message ? err.message : String(err))}</p>`;
      return null;
    }

    const nodes = normalizeNodes(payload.nodes);
    const edges = normalizeEdges(payload.edges);

    if (!nodes.length) {
      details.innerHTML = "<p>No nodes available.</p>";
      return null;
    }

    const xValues = nodes.map((node) => node.x);
    const yValues = nodes.map((node) => node.y);
    const minX = Math.min(...xValues);
    const maxX = Math.max(...xValues);
    const minY = Math.min(...yValues);
    const maxY = Math.max(...yValues);

    const idToNode = new Map();
    nodes.forEach((node) => {
      idToNode.set(node.id, {
        ...node,
        nx: normalizeCoordinate(node.x, minX, maxX),
        ny: normalizeCoordinate(node.y, minY, maxY),
      });
    });

    const neighbors = new Map(nodes.map((node) => [node.id, new Set()]));
    edges.forEach((edge) => {
      if (!neighbors.has(edge.source) || !neighbors.has(edge.target)) return;
      neighbors.get(edge.source).add(edge.target);
      neighbors.get(edge.target).add(edge.source);
    });

    const groups = Array.from(new Set(nodes.map((node) => node.group)));
    const colors = colorScale(groups);

    const graph = new runtime.Graph({ multi: false, allowSelfLoops: false });
    idToNode.forEach((node) => {
      // node_color overrides group-based color (used for per-section concept coloring)
      const color = node.node_color || colors.get(node.group) || "#5e7388";
      const size = nodeSize(node);
      graph.addNode(node.id, {
        label: node.label,
        x: node.nx,
        y: node.ny,
        size,
        originalSize: size,
        color,
        originalColor: color,
        group: node.group,
        layer: node.layer,
      });
    });

    edges.forEach((edge, idx) => {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) return;
      const key = graph.hasEdge(edge.id)
        ? `edge:${idx}:${edge.source}:${edge.target}`
        : edge.id;
      graph.addEdgeWithKey(key, edge.source, edge.target, {
        size: 1.0,
        originalSize: 1.0,
        color: EDGE_BASE,
        originalColor: EDGE_BASE,
      });
    });

    let renderer;
    try {
      renderer = new runtime.Sigma(graph, stage, {
        renderLabels: true,
        renderEdgeLabels: false,
        labelDensity: 0.08,
        labelGridCellSize: 96,
        labelRenderedSizeThreshold: 8,
        minCameraRatio: 0.04,
        maxCameraRatio: 10,
        defaultNodeType: "circle",
        defaultEdgeType: "line",
        allowInvalidContainer: true,
        zIndex: true,
      });
    } catch (err) {
      details.innerHTML = `<p><strong>Renderer failed to initialize.</strong><br/>${esc(err && err.message ? err.message : String(err))}</p>`;
      return null;
    }

    const orderedGroups = orderGroups(groups);
    let selectedId = idToNode.has(initialId) ? initialId : nodes[0].id;
    let hoveredId = "";
    let activeGroup = "All";
    let neighborMode = false;
    let searchText = "";

    const pillButtons = new Map();

    function setActivePill(name) {
      pillButtons.forEach((button, key) => {
        button.classList.toggle("is-active", key === name);
      });
    }

    function addPill(name, handler) {
      const button = create("button", { type: "button" }, name);
      button.addEventListener("click", handler);
      pills.appendChild(button);
      pillButtons.set(name, button);
    }

    addPill("All", () => {
      activeGroup = "All";
      neighborMode = false;
      setActivePill("All");
      applyVisualState();
    });

    orderedGroups.forEach((group) => {
      addPill(group, () => {
        activeGroup = group;
        neighborMode = false;
        setActivePill(group);
        applyVisualState();
      });
    });

    addPill("Neighbors", () => {
      neighborMode = true;
      setActivePill("Neighbors");
      applyVisualState();
    });

    setActivePill("All");

    function matchesSearch(node) {
      if (!searchText) return true;
      const hay = `${node.label} ${node.summary} ${node.id}`.toLowerCase();
      return hay.includes(searchText);
    }

    function computeVisibleSet() {
      const visible = new Set();
      const selectedNeighbors = selectedId && neighbors.has(selectedId)
        ? neighbors.get(selectedId)
        : new Set();

      nodes.forEach((rawNode) => {
        const node = idToNode.get(rawNode.id);
        if (!node) return;

        if (!neighborMode && activeGroup !== "All" && node.group !== activeGroup) return;
        if (neighborMode && selectedId) {
          const inNeighborhood = node.id === selectedId || selectedNeighbors.has(node.id);
          if (!inNeighborhood) return;
        }

        if (!matchesSearch(node)) {
          if (selectedId && node.id === selectedId) {
            visible.add(node.id);
          }
          return;
        }

        visible.add(node.id);
      });

      if (!visible.size && selectedId && idToNode.has(selectedId)) {
        visible.add(selectedId);
      }
      return visible;
    }

    function nearestInLayer(layer, fromY, visibleSet) {
      const candidates = nodes
        .filter((node) => node.layer === layer && visibleSet.has(node.id))
        .map((node) => idToNode.get(node.id))
        .filter(Boolean)
        .sort((a, b) => Math.abs(a.y - fromY) - Math.abs(b.y - fromY));
      return candidates.length ? candidates[0] : null;
    }

    function renderDetails(nodeId) {
      if (!nodeId || !idToNode.has(nodeId)) {
        details.innerHTML = "<p>Select a node to view details.</p>";
        return;
      }

      const node = idToNode.get(nodeId);
      const linked = Array.from(neighbors.get(nodeId) || [])
        .map((id) => idToNode.get(id))
        .filter(Boolean)
        .sort((a, b) => a.label.localeCompare(b.label))
        .slice(0, 18);
      const paperIds = Array.isArray(node.paper_ids) ? node.paper_ids.filter(Boolean) : [];
      const journey = window.mskbJourney;
      const canAdd = journey && typeof journey.addIds === "function" && paperIds.length > 0;

      details.innerHTML = `
        <div class="mskb-detail-head">
          <span class="mskb-chip">${esc(node.group)}</span>
          <h4>${esc(node.label)}</h4>
        </div>
        <p>${esc(node.summary || "No summary available.")}</p>
        ${node.href ? `<p><a href="${esc(node.href)}">Open page</a></p>` : ""}
        <div class="mskb-connected">
          <strong>Connected nodes</strong>
          <div class="mskb-connected-list">
            ${linked.map((n) => `<button type="button" data-node-id="${esc(n.id)}">${esc(n.label)}</button>`).join("") || "<span>None</span>"}
          </div>
        </div>
        <div class="mskb-add">
          <button type="button" id="mskb-add-papers" ${canAdd ? "" : "disabled"}>Add papers to list</button>
          ${paperIds.length ? `<small>${paperIds.length} paper id${paperIds.length === 1 ? "" : "s"}</small>` : "<small>No paper ids on this node.</small>"}
        </div>
      `;

      details.querySelectorAll("[data-node-id]").forEach((button) => {
        button.addEventListener("click", () => {
          const targetId = button.getAttribute("data-node-id");
          if (!targetId) return;
          selectedId = targetId;
          hoveredId = "";
          centerOnNode(renderer, selectedId);
          renderDetails(selectedId);
          applyVisualState();
        });
      });

      const addButton = details.querySelector("#mskb-add-papers");
      if (addButton && canAdd) {
        addButton.addEventListener("click", () => {
          const added = window.mskbJourney.addIds(paperIds);
          addButton.textContent = Number(added) > 0 ? `Added (+${added})` : "Already added";
        });
      }

      if (onNodeClick) {
        try {
          onNodeClick(node);
        } catch (_err) {
          // Intentionally swallow callback errors.
        }
      }
    }

    function applyVisualState() {
      const visibleSet = computeVisibleSet();
      if (!visibleSet.has(selectedId)) {
        const firstVisible = nodes.find((node) => visibleSet.has(node.id));
        selectedId = firstVisible ? firstVisible.id : "";
      }

      const focusId = selectedId || hoveredId;
      const focusedNeighbors = focusId && neighbors.has(focusId)
        ? new Set(neighbors.get(focusId))
        : new Set();
      if (focusId) focusedNeighbors.add(focusId);

      graph.forEachNode((nodeId, attrs) => {
        const visible = visibleSet.has(nodeId);
        graph.setNodeAttribute(nodeId, "hidden", !visible);
        if (!visible) return;

        let color = attrs.originalColor || "#5e7388";
        let size = attrs.originalSize || 7;

        if (focusId) {
          if (focusedNeighbors.has(nodeId)) {
            if (nodeId === focusId) {
              color = NODE_ACTIVE;
              size = (attrs.originalSize || 7) * 1.2;
            }
          } else {
            color = NODE_DIM;
          }
        }

        graph.setNodeAttribute(nodeId, "color", color);
        graph.setNodeAttribute(nodeId, "size", size);
      });

      graph.forEachEdge((edgeId, attrs, source, target) => {
        const visible = visibleSet.has(source) && visibleSet.has(target);
        graph.setEdgeAttribute(edgeId, "hidden", !visible);
        if (!visible) return;

        let color = attrs.originalColor || EDGE_BASE;
        let size = attrs.originalSize || 1;

        if (focusId) {
          if (source === focusId || target === focusId) {
            color = EDGE_ACTIVE;
            size = 1.6;
          } else {
            color = EDGE_DIM;
            size = 0.8;
          }
        }

        graph.setEdgeAttribute(edgeId, "color", color);
        graph.setEdgeAttribute(edgeId, "size", size);
      });

      renderer.refresh();
      renderDetails(selectedId || "");
    }

    search.addEventListener("input", () => {
      searchText = String(search.value || "").trim().toLowerCase();
      applyVisualState();
    });

    fitButton.addEventListener("click", () => {
      // Zoom out to ratio 1.4 so the full graph plus a margin is visible,
      // not cropped to the tightest bbox (which clips node halos at edges).
      fitWholeGraph(true);
    });

    resetButton.addEventListener("click", () => {
      search.value = "";
      searchText = "";
      activeGroup = "All";
      neighborMode = false;
      setActivePill("All");
      applyVisualState();
      fitWholeGraph(true);
    });

    // Center on the graph's centroid and zoom out so every node is visible
    // with a comfortable margin. ratio > 1 = zoomed OUT in Sigma;
    // 2.0 gives the full graph plus generous whitespace on all sides.
    function fitWholeGraph(animated) {
      const camera = renderer.getCamera();
      if (!camera) return;
      const state = { x: 0.5, y: 0.5, ratio: 2.0, angle: 0 };
      if (animated && typeof camera.animate === "function") {
        camera.animate(state, { duration: 300 });
      } else if (typeof camera.setState === "function") {
        camera.setState(state);
      }
    }

    renderer.on("clickNode", ({ node }) => {
      selectedId = node;
      hoveredId = "";
      centerOnNode(renderer, selectedId);
      renderDetails(selectedId);
      applyVisualState();
    });

    renderer.on("clickStage", () => {
      hoveredId = "";
      applyVisualState();
    });

    renderer.on("enterNode", ({ node }) => {
      hoveredId = node;
      applyVisualState();
    });

    renderer.on("leaveNode", () => {
      hoveredId = "";
      applyVisualState();
    });

    shell.setAttribute("tabindex", "0");
    shell.addEventListener("keydown", (event) => {
      if (!selectedId || !idToNode.has(selectedId)) return;
      const selected = idToNode.get(selectedId);
      const visibleSet = computeVisibleSet();
      if (event.key === "ArrowLeft") {
        const next = nearestInLayer(selected.layer - 1, selected.y, visibleSet);
        if (next) {
          event.preventDefault();
          selectedId = next.id;
          centerOnNode(renderer, selectedId);
          applyVisualState();
        }
      } else if (event.key === "ArrowRight") {
        const next = nearestInLayer(selected.layer + 1, selected.y, visibleSet);
        if (next) {
          event.preventDefault();
          selectedId = next.id;
          centerOnNode(renderer, selectedId);
          applyVisualState();
        }
      }
    });

    renderDetails(selectedId);
    applyVisualState();
    // Initial view: show the whole graph, centered, slightly zoomed out,
    // rather than zooming in on the first selected node.
    fitWholeGraph(false);

    return {
      destroy() {
        try {
          renderer.kill();
        } catch (_err) {
          // no-op
        }
        rootEl.innerHTML = "";
      },
    };
  }

  window.MSKBGraph = { render };
})();
