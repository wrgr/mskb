// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// MSKB runs as a GitHub Pages project site at https://wrgr.github.io/mskb/.
// Override MSKB_SITE and MSKB_BASE at build time to publish elsewhere.
const SITE = process.env.MSKB_SITE || 'https://wrgr.github.io';
const BASE = process.env.MSKB_BASE ?? '/mskb';

export default defineConfig({
  site: SITE,
  base: BASE,
  trailingSlash: 'always',
  outDir: './dist',
  integrations: [
    starlight({
      title: 'MSKB',
      description:
        'Multiple Sclerosis Knowledge Base — a concept-first learning map linked to the citation graph of MS research.',
      favicon: '/favicon.svg',
      social: [],
      customCss: [
        './src/styles/utilities.css',
        './src/styles/site-banner.css',
        './src/styles/concept-pages.css',
        './src/styles/explorer.css',
        './src/styles/citation-graph.css',
        './src/styles/journey.css',
        './src/styles/graphs.css',
      ],
      components: {
        Footer: './src/components/SiteFooter.astro',
        // Site-wide top header: render the project banner full-width above
        // Starlight's default header bar (title + search + theme + social)
        // on every route, so the search and sidebar sit below the banner.
        Header: './src/components/Header.astro',
        // Explorer-only sidebar augmentation: prepend a Direct-Search card
        // so it sits with the site nav instead of being buried below the
        // graph. Falls through to the default on every other route.
        Sidebar: './src/components/Sidebar.astro',
      },
      // The sidebar is intentionally trimmed to the learner spine so new
      // undergraduate readers see one obvious path instead of the full site.
      // Builder/methodology pages (corpus docs, whitepaper, citation-topic
      // clusters) and the advanced citation visualizations (lineage, citation
      // tree, field development, learning-journey studio) still build and stay
      // reachable by direct link and site search — they are just kept out of
      // the primary nav. Re-add an entry here to resurface a page in the nav.
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Getting Started', link: '/getting-started/' },
        {
          label: 'Pathways',
          items: [
            { label: 'Overview', link: '/pathways/' },
            { label: 'Intro to MS research', link: '/pathways/intro-to-ms-research/' },
            { label: 'Clinical', link: '/pathways/clinical/' },
            { label: 'Mechanistic', link: '/pathways/mechanistic/' },
            { label: 'Emerging frontiers', link: '/pathways/emerging/' },
            { label: 'Journal club (undergrad)', link: '/pathways/journal-club/' },
          ],
        },
        {
          label: 'Concepts',
          items: [
            { label: 'Concept map', link: '/concepts/' },
            {
              label: 'Foundations',
              collapsed: true,
              autogenerate: { directory: 'concepts/foundations' },
            },
            {
              label: 'Mechanisms',
              collapsed: true,
              autogenerate: { directory: 'concepts/mechanisms' },
            },
            {
              label: 'Diagnosis & imaging',
              collapsed: true,
              autogenerate: { directory: 'concepts/diagnosis' },
            },
            {
              label: 'Therapeutics',
              collapsed: true,
              autogenerate: { directory: 'concepts/therapeutics' },
            },
            {
              label: 'Clinical & populations',
              collapsed: true,
              autogenerate: { directory: 'concepts/clinical' },
            },
          ],
        },
        { label: 'Citation Explorer', link: '/explorer/' },
        { label: 'Glossary', link: '/glossary/' },
      ],
      pagination: false,
      lastUpdated: true,
    }),
  ],
});
