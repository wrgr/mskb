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
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Getting Started', link: '/getting-started/' },
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
        {
          label: 'Learning Pathways',
          items: [
            { label: 'Overview', link: '/pathways/' },
            { label: 'Clinical pathway', link: '/pathways/clinical/' },
            { label: 'Mechanistic pathway', link: '/pathways/mechanistic/' },
            { label: 'Emerging topics', link: '/pathways/emerging/' },
          ],
        },
        { label: 'Learning Journey', link: '/journey/' },
        {
          label: 'Topics',
          collapsed: true,
          autogenerate: { directory: 'topics' },
        },
        { label: 'Explorer', link: '/explorer/' },
        { label: 'Glossary', link: '/glossary/' },
      ],
      pagination: false,
      lastUpdated: true,
    }),
  ],
});
