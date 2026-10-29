import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, unlinkSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { spawnSync } from 'node:child_process';
import { json } from '../scripts/files.mjs';
import { checkSite } from '../scripts/check-site.mjs';

const proto = process.cwd();
mkdirSync('.test-work', { recursive: true });
function put(root, path, text) {
  const dest = resolve(root, path);
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, text);
}
function fixture(base) {
  const root = mkdtempSync(resolve('.test-work', 'site-'));
  put(root, 'content-map.json', json({ pages: [{ route: '' }, { route: 'guide' }] }));
  put(root, 'dist/index.html', `<html><head><title>Home</title><link rel="stylesheet" href="${base}style.css"></head><body><h1 id="home">Home</h1><a href="${base}guide/#stable">Guide</a><img src="${base}image.svg" alt="Probe"></body></html>`);
  put(root, 'dist/guide/index.html', `<html><head><title>Guide</title></head><body><h1 id="stable">Guide</h1><a href="${base}">Home</a></body></html>`);
  put(root, 'dist/404.html', `<html><head><title>Not found</title></head><body><a href="${base}">Home</a></body></html>`);
  put(root, 'dist/image.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>');
  put(root, 'dist/style.css', `body{background-image:url('${base}image.svg')}`);
  put(root, 'dist/pagefind/pagefind.js', '/* Fixture asset, no browser claim. */');
  put(root, 'dist/pagefind/pagefind-entry.json', json({ languages: { en: { hash: 'fixture', wasm: 'en', page_count: 2 } } }));
  put(root, 'dist/pagefind/pagefind.fixture.pf_meta', 'fixture');
  put(root, 'dist/pagefind/wasm.en.pagefind', 'fixture');
  return root;
}
for (const base of ['/', '/huron-docs/']) test(`Emitted routes, fragments, CSS and assets validate at ${base}`, () => {
  const proof = checkSite({ root: fixture(base), dist: 'dist', base });
  assert.equal(proof.pages.length, 3);
  assert.equal(proof.localLinks, 6);
  assert.equal(proof.externalReferences, 0);
});

const invalid = [
  ['missing emitted page', (root) => unlinkSync(resolve(root, 'dist/guide/index.html')), /Emitted routes/],
  ['missing emitted fragment', (root) => put(root, 'dist/guide/index.html', '<h1 id="other">Guide</h1>'), /Missing emitted fragment/],
  ['missing emitted asset', (root) => unlinkSync(resolve(root, 'dist/image.svg')), /Missing emitted file or asset/],
  ['bad root-only link under a subbase', (root) => put(root, 'dist/guide/index.html', '<h1 id="stable">Guide</h1><a href="/">Bad root link</a>'), /Root-only link/],
  ['duplicate emitted ID', (root) => put(root, 'dist/guide/index.html', '<h1 id="stable">Guide</h1><p id="stable">Duplicate</p>'), /Duplicate emitted ID/],
  ['unknown emitted route', (root) => put(root, 'dist/extra.html', '<h1>Extra</h1>'), /Emitted routes/],
  ['runtime external dependency', (root) => put(root, 'dist/guide/index.html', '<h1 id="stable">Guide</h1><script src="https://example.com/runtime.js"></script>'), /External runtime asset/],
  ['missing search metadata', (root) => unlinkSync(resolve(root, 'dist/pagefind/pagefind.fixture.pf_meta')), /Missing Pagefind metadata/],
  ['missing search WASM', (root) => unlinkSync(resolve(root, 'dist/pagefind/wasm.en.pagefind')), /Missing Pagefind WASM/],
  ['missing search page', (root) => put(root, 'dist/pagefind/pagefind-entry.json', json({ languages: { en: { hash: 'fixture', wasm: 'en', page_count: 1 } } })), /Every fixture page/],
];
for (const [name, mutate, message] of invalid) test(`${name} fails the strict CLI`, () => {
  const root = fixture('/huron-docs/');
  mutate(root);
  const result = spawnSync(process.execPath, [resolve(proto, 'scripts/check-site.mjs'), '--dist', 'dist', '--base', '/huron-docs/'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 1, result.stdout + result.stderr);
  assert.match(result.stderr, message);
  assert.doesNotMatch(result.stdout, /PASS/);
});
