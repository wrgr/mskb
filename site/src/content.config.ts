import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

// Layer A: Learner Concept Graph.
//
// Each concept is a page under src/content/docs/concepts/**. The `concept`
// frontmatter block models the learner-facing graph:
//
//   - prerequisites: concepts you should understand first
//   - specializes:   more-specific concepts this one branches into
//   - related:       lateral connections (no prereq relationship)
//   - objectives:    what a learner should be able to do after this concept
//   - papers:        canonical paper ids from Layer B (citation navigator)
//   - resources:     curated non-paper materials (videos, explainers, tools)
//
// Layer B and C don't get their own schemas here — topics are plain docs with
// a light `topic` block, and semantic KG detail lives inline on concept pages.
const ConceptRef = z.string(); // slug under /concepts/, e.g. "foundations/immunology"

const Resource = z.object({
  title: z.string(),
  type: z.enum(['video', 'article', 'textbook', 'tool', 'course', 'dataset', 'podcast']),
  link: z.string().url(),
  source: z.string().optional(),
  level: z.enum(['intro', 'intermediate', 'advanced']).default('intro'),
  note: z.string().optional(),
});

const ConceptBlock = z.object({
  id: z.string(),
  category: z.enum([
    'foundations',
    'mechanisms',
    'diagnosis',
    'therapeutics',
    'clinical',
  ]),
  difficulty: z.number().int().min(1).max(5),
  prerequisites: z.array(ConceptRef).default([]),
  specializes: z.array(ConceptRef).default([]),
  related: z.array(ConceptRef).default([]),
  objectives: z.array(z.string()).default([]),
  papers: z.array(z.string()).default([]),
  resources: z.array(Resource).default([]),
});

const TopicBlock = z.object({
  id: z.union([z.string(), z.number()]),
  category: z.string(),
  difficulty: z.number().int().min(1).max(5),
  paperCount: z.number().int().min(0),
  concepts: z.array(ConceptRef).default([]),
});

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        concept: ConceptBlock.optional(),
        topic: TopicBlock.optional(),
      }),
    }),
  }),
};
