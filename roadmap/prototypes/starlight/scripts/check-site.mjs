import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { parse } from 'parse5';
import assert from 'node:assert/strict';
import { inventory, sha256, json, noSymlinks } from './files.mjs';
import { htmlWalk } from './markdown.mjs';
import { routeUrl } from './prepare-content.mjs';

const origin = 'http://127.0.0.1:4327';
const textOf = (node) => node.nodeName === '#text' ? node.value : (node.childNodes ?? []).map(textOf).join('');

export function checkSite({ root, dist, base = '/', manifest = 'content-map.json' }) {
  if (!['/', '/huron-docs/'].includes(base)) throw new Error('Invalid base');
  const out = noSymlinks(root, dist);
  const files = inventory(out);
  const map = JSON.parse(readFileSync(noSymlinks(root, manifest), 'utf8'));
  const expected = [...map.pages.map(({ route }) => route ? `${route}/index.html` : 'index.html'), '404.html'].sort();
  assert.deepEqual(Object.keys(files).filter((name) => name.endsWith('.html')).sort(), expected, 'Emitted routes differ from explicit manifest');
  const pages = new Map();
  const links = [];
  const content = [];
  for (const filename of expected) {
    const html = readFileSync(resolve(out, filename), 'utf8');
    const tree = parse(html);
    const url = base + filename.replace(/index\.html$/, '');
    const ids = new Set();
    let title = '';
    let main = '';
    htmlWalk(tree, (node) => {
      if (node.tagName === 'title') title = textOf(node);
      if ((node.attrs ?? []).some((attr) => attr.name === 'class' && attr.value.split(' ').includes('sl-markdown-content'))) main = textOf(node);
      for (const attr of node.attrs ?? []) {
        if (attr.name === 'id' || (node.tagName === 'a' && attr.name === 'name')) {
          if (ids.has(attr.value)) throw new Error(`Duplicate emitted ID ${attr.value} in ${filename}`);
          ids.add(attr.value);
        }
        if (['href', 'src', 'poster'].includes(attr.name)) links.push({ from: url, value: attr.value, runtime: node.tagName !== 'a' });
        if (attr.name === 'srcset') {
          for (const candidate of attr.value.split(',')) links.push({ from: url, value: candidate.trim().split(/\s/)[0], runtime: true });
        }
      }
    });
    pages.set(url, { filename, ids });
    content.push({ url, title, ids: [...ids].sort(), htmlSha256: sha256(html), contentSha256: sha256(main) });
  }
  for (const filename of Object.keys(files).filter((name) => name.endsWith('.css'))) {
    const css = readFileSync(resolve(out, filename), 'utf8');
    for (const match of css.matchAll(/url\(\s*['"]?([^)'"\s]+)['"]?\s*\)/g)) links.push({ from: base + filename, value: match[1], runtime: true });
  }
  let localLinks = 0;
  let externalReferences = 0;
  for (const link of links) {
    if (link.value.startsWith('data:')) {
      if (!link.runtime) throw new Error('Unsupported data navigation');
      continue;
    }
    const target = new URL(link.value, origin + link.from);
    if (target.origin !== origin) {
      if (link.runtime || !['http:', 'https:', 'mailto:', 'tel:'].includes(target.protocol)) throw new Error(`External runtime asset: ${link.value}`);
      externalReferences++;
      continue;
    }
    if (!target.pathname.startsWith(base)) throw new Error(`Root-only link escapes subbase: ${link.value} from ${link.from}`);
    const relative = decodeURIComponent(target.pathname.slice(base.length));
    if (relative.includes('\\') || relative.split('/').includes('..')) throw new Error('Emitted path escape');
    const file = relative.endsWith('/') || !relative ? relative + 'index.html' : relative;
    if (!Object.hasOwn(files, file)) throw new Error(`Missing emitted file or asset: ${link.value} from ${link.from}`);
    if (target.hash) {
      const page = pages.get(target.pathname);
      if (!page || !page.ids.has(decodeURIComponent(target.hash.slice(1)))) throw new Error(`Missing emitted fragment: ${link.value} from ${link.from}`);
    }
    localLinks++;
  }
  for (const page of map.pages) {
    const emitted = pages.get(routeUrl(base, page.route));
    if (!emitted) throw new Error('Expected canonical route missing');
  }
  // Pagefind's dynamic index is not listed in document href/src attributes.
  for (const name of ['pagefind/pagefind.js', 'pagefind/pagefind-entry.json']) if (!files[name]) throw new Error(`Missing Pagefind asset: ${name}`);
  const entry = JSON.parse(readFileSync(resolve(out, 'pagefind/pagefind-entry.json'), 'utf8'));
  for (const language of Object.values(entry.languages ?? {})) {
    if (!files[`pagefind/pagefind.${language.hash}.pf_meta`]) throw new Error('Missing Pagefind metadata asset');
    if (!files[`pagefind/wasm.${language.wasm}.pagefind`]) throw new Error('Missing Pagefind WASM asset');
  }
  assert.equal(Object.values(entry.languages ?? {}).reduce((sum, language) => sum + language.page_count, 0), map.pages.length, 'Every fixture page must be indexed');
  return { base, pages: content.sort((a, b) => a.url.localeCompare(b.url, 'en')), assets: Object.fromEntries(Object.entries(files).filter(([name]) => !name.endsWith('.html'))), localLinks, externalReferences };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { values } = parseArgs({ options: { dist: { type: 'string' }, base: { type: 'string', default: process.env.DOCS_BASE ?? '/' }, manifest: { type: 'string' }, receipt: { type: 'string' } } });
    const result = checkSite({ root: process.cwd(), dist: values.dist ?? (values.base === '/' ? 'dist/root' : 'dist/subbase'), ...values });
    if (values.receipt) writeFileSync(noSymlinks(process.cwd(), values.receipt, true), json(result));
    console.log(`PASS: ${result.pages.length} routes, ${Object.keys(result.assets).length} assets, ${result.localLinks} local URLs/fragments; base ${result.base}; ${result.externalReferences} non-runtime external references`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
