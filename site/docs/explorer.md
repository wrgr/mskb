# Explorer

Use this graph to inspect papers, follow citation paths, and turn a short research note into parent/child/related paper choices.

<script src="../javascripts/vendor/cytoscape.min.js"></script>

<div class="top-idea reveal">
  <h3>Explore the MS Knowledge Graph</h3>
  <p>Use this view to inspect citation structure, read paper summaries, and plan literature exploration from core papers out to related work.</p>
  <div class="explorer-guide">
    <div class="guide-card"><strong>Undergrad flow:</strong> start with lower language level, then branch through related papers.</div>
    <div class="guide-card"><strong>Grad flow:</strong> raise structural filters (in/out degree and k-core) for denser, high-signal papers.</div>
    <div class="guide-card"><strong>Node semantics:</strong> size is log(citations), color is k-core tier, arrows are citations.</div>
  </div>
</div>

<details id="parameters" class="param-tray reveal">
  <summary><strong>Parameters &amp; filters</strong> (click to expand)</summary>
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

<div id="paper-graph"></div>

<section class="paper-panel reveal">
  <header class="paper-panel-head">
    <h3>Selected paper</h3>
    <span class="paper-panel-hint">Click any node in the graph to focus it.</span>
  </header>
  <div id="paper-details">Select a node to view summary, source link, and relationship choices.</div>
  <div class="rel-grid">
    <div class="rel-section">
      <h4>Parents <small>(papers this one cites)</small></h4>
      <div id="parent-links"></div>
    </div>
    <div class="rel-section">
      <h4>Children <small>(papers that cite this one)</small></h4>
      <div id="child-links"></div>
    </div>
    <div class="rel-section">
      <h4>Related <small>(nearby in citation neighborhood)</small></h4>
      <div id="related-links"></div>
    </div>
  </div>
</section>

<div class="tools-panel reveal">
  <h3>Tools</h3>
  <p class="tools-intro">Add papers to your <strong>working selection</strong> using the <em>Add</em> buttons in the graph, search results, or paper details. The selection is shared between the Learning Path and Community Reading List tools.</p>
  <div class="tool-grid">
    <section class="tool-card">
      <h4>Learning path</h4>
      <p>Stage your selection into <em>foundations &rarr; bridges &rarr; deep dives</em> for self-paced study.</p>
      <div id="journey-selected"></div>
      <div class="explorer-actions">
        <button id="journey-generate" type="button">Generate Learning Path</button>
        <button id="journey-clear" type="button">Clear Selection</button>
      </div>
      <div id="journey-results"></div>
    </section>

    <section class="tool-card">
      <h4>Direct search</h4>
      <p>Find papers by author, title, or abstract text.</p>
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
      <h4>Find research like&hellip;</h4>
      <p>Describe a research idea and retrieve relevant papers from the current filtered corpus.</p>
      <textarea id="idea-input" placeholder="Example: EBV-linked immune mechanisms that connect to progression biomarkers in MS"></textarea>
      <div class="explorer-actions">
        <button id="idea-run" type="button">Find Relevant Papers</button>
      </div>
      <div id="idea-results"></div>
    </section>

    <section class="tool-card">
      <h4>Community reading list</h4>
      <p>Treat your selection as a community: compute graph stats, suggest companion papers, and export a markdown reading list (e.g. for a journal club).</p>
      <div id="community-stats" class="community-stats"></div>
      <div class="explorer-actions">
        <button id="community-generate" type="button">Build Community Stats</button>
        <button id="community-download" type="button" disabled>Download Reading List (.md)</button>
      </div>
      <div id="community-results"></div>
    </section>
  </div>
</div>

<script src="../javascripts/explorer/utils.js"></script>
<script src="../javascripts/explorer/debug.js"></script>
<script src="../javascripts/explorer.js"></script>
