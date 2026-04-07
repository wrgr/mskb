# Multiple Sclerosis Knowledge Base

<div class="landing-hero">
  <p><strong>MSKB</strong> is a navigable research map for undergraduate teams working in multiple sclerosis.</p>
  <p>Move from mechanisms to trials to population health using topic clusters, plain-English summaries, and guided reading paths.</p>
  <div class="landing-kpis">
    <a class="kpi-pill kpi-link" href="topics/">Citation-network topics</a>
    <a class="kpi-pill kpi-link" href="topics/">Paper-level summaries</a>
    <a class="kpi-pill kpi-link" href="explorer/">Graph explorer</a>
    <a class="kpi-pill kpi-link" href="explorer/#parameters">Core KB filtering</a>
  </div>
</div>

## Start Here

<div class="landing-grid">
  <div class="landing-card">
    <h3><a href="getting-started/">Orientation</a></h3>
    <p>New to MS literature? Use the onboarding guide and pick a route by background.</p>
  </div>
  <div class="landing-card">
    <h3><a href="topics/">Topic Atlas</a></h3>
    <p>Browse discovered clusters with reading paths, summaries, and language-level cues.</p>
  </div>
  <div class="landing-card">
    <h3><a href="explorer/">Interactive Explorer</a></h3>
    <p>Navigate parent/child/related papers and map a short research note to relevant work.</p>
  </div>
</div>

## What You’ll Find

- Topic clusters derived from citation communities (Louvain + concept labeling)
- Plain-English paper cards with abstracts, takeaways, citation links, and BibTeX
- A dynamic “core knowledge” filter using PageRank, k-core, and in-degree
- A glossary for key immunology, imaging, and clinical vocabulary

## Method

This knowledge base was built using a bibliometric pipeline that retrieves, scores, and organizes MS literature from [OpenAlex](https://openalex.org/). Papers are scored for relevance, clustered into topics using citation network analysis, and distilled into accessible summaries.

Pipeline architecture adapted from [connectome-kb](https://github.com/wrgr/connectome-kb).
