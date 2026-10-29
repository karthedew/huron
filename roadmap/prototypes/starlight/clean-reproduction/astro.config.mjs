import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { unified } from '@astrojs/markdown-remark';

const base = process.env.DOCS_BASE ?? '/';
if (!['/', '/huron-docs/'].includes(base)) throw new Error('Only the two declared experiment bases are supported');

export default defineConfig({
  base,
  output: 'static',
  outDir: base === '/' ? './dist/root/' : './dist/subbase/',
  trailingSlash: 'always',
  markdown: { processor: unified({ smartypants: false }) },
  integrations: [starlight({
    title: 'Huron · throwaway docs probe',
    pagefind: true,
    customCss: ['./src/styles/probe.css'],
    sidebar: [
      { slug: '', label: 'Prototype home' },
      { slug: 'probe', label: 'Rendering probe' },
      { label: 'Developer fixtures', items: [{ autogenerate: { directory: 'getting-started' } }] },
      { label: 'Authority and history', items: [
        { slug: 'reference/raw-first' },
        { slug: 'reference/vocabulary', label: 'Vocabulary' },
        { slug: 'history' },
        { autogenerate: { directory: 'adr' } },
        { slug: 'agents/domain' },
        { slug: 'operations/controlled-cutover' },
      ] },
    ],
  })],
});
