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
      customCss: ['./src/styles/custom.css'],
      components: {
        Footer: './src/components/SiteFooter.astro',
      },
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Getting Started', link: '/getting-started/' },
        {
          label: 'Pathways',
          items: [
            { label: 'Overview', link: '/pathways/' },
            { label: 'Clinical', link: '/pathways/clinical/' },
            { label: 'Mechanistic', link: '/pathways/mechanistic/' },
            { label: 'Emerging frontiers', link: '/pathways/emerging/' },
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
        { label: 'Learning Journey', link: '/journey/' },
        { label: 'Citation Explorer', link: '/explorer/' },
        { label: 'Citation Lineage', link: '/lineage/' },
        { label: 'Citation Tree', link: '/citation-tree/' },
        { label: 'Field Development', link: '/field-development/' },
        { label: 'Glossary', link: '/glossary/' },
        {
          label: 'Citation Topics',
          collapsed: true,
          autogenerate: { directory: 'topics' },
        },
        {
          label: 'Corpus & Docs',
          items: [
            { label: 'Overview', link: '/corpus/' },
            { label: 'Statistics', link: '/corpus/stats/' },
            { label: 'Methodology & Limitations', link: '/corpus/methodology/' },
            { label: 'Topic Map', link: '/corpus/topics/' },
            { label: 'Seeds & Anchors', link: '/corpus/seeds/' },
            { label: 'Design Decisions', link: '/corpus/design-decisions/' },
            { label: 'Gap Tracker', link: '/corpus/gaps/' },
          ],
        },
        { label: 'Whitepaper', link: '/whitepaper/' },
      ],
      pagination: false,
      lastUpdated: true,
    }),
  ],
});
