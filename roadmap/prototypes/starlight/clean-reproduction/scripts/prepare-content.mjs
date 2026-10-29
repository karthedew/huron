import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, renameSync, existsSync, openSync, closeSync, unlinkSync } from 'node:fs';
import { resolve, dirname, relative, posix } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs, isDeepStrictEqual } from 'node:util';
import assert from 'node:assert/strict';
import { inside, noSymlinks, regular, inventory, sha256, json } from './files.mjs';
import { view, rewrite, generated, validTitle } from './markdown.mjs';

const marker = '_ownership.json';
const cleanPath = (name) => typeof name === 'string' && !!name && !name.includes('\\') && !name.startsWith('/') && !name.split('/').some((part) => ['', '.', '..'].includes(part));
const routeFile = (route) => route ? `${route}.md` : 'index.md';
export const routeUrl = (base, route) => `${base}${route}${route ? '/' : ''}`;

export async function planContent({ root, input = 'fixtures', manifest = 'content-map.json', base = '/' }) {
  if (!['/', '/huron-docs/'].includes(base)) throw new Error('Invalid base');
  const inputRoot = noSymlinks(root, input);
  const map = JSON.parse(regular(root, manifest));
  if (map.version !== 1 || !Array.isArray(map.pages) || !map.pages.length || !Array.isArray(map.assets)) throw new Error('Invalid manifest');
  const seenSources = new Set();
  const seenOutputs = new Set([marker]);
  const pages = new Map();
  const files = {};
  for (const page of map.pages) {
    if (!cleanPath(page.source) || page.source.startsWith('roadmap/')) throw new Error('Invalid source path');
    if (typeof page.route !== 'string' || (page.route && !/^[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(page.route)) || page.route === 'index' || page.route === '404') throw new Error('Invalid route');
    if (!validTitle(page.title)) throw new Error('Invalid manifest title');
    const output = routeFile(page.route);
    if (seenSources.has(page.source) || seenOutputs.has(output)) throw new Error('Duplicate route or source');
    seenSources.add(page.source);
    seenOutputs.add(output);
    const bytes = regular(inputRoot, page.source);
    pages.set(page.source, { page, output, sha256: sha256(bytes), parsed: await view(bytes.toString('utf8'), page.title) });
  }
  const assets = new Map();
  for (const asset of map.assets) {
    if (!cleanPath(asset.source) || !cleanPath(asset.output) || !asset.output.startsWith('_assets/') || seenOutputs.has(asset.output) || seenSources.has(asset.source)) throw new Error('Invalid or colliding asset');
    const bytes = regular(inputRoot, asset.source);
    seenOutputs.add(asset.output);
    seenSources.add(asset.source);
    assets.set(asset.source, asset);
    files[asset.output] = bytes;
  }
  const externalSources = map.externalSources ?? {};
  for (const [path, url] of Object.entries(externalSources)) {
    if (!cleanPath(path) || !path.startsWith('design/') || !path.endsWith('.html') || !/^https:\/\/github\.com\/karthedew\/huron\/blob\/[0-9a-f]{40}\/design\//.test(url)) throw new Error('Invalid external source mapping');
  }
  for (const current of pages.values()) {
    const resolver = (url, image) => {
      if (/^[a-z][a-z\d+.-]*:/i.test(url) || url.startsWith('//')) {
        if (image || !/^(https?:|mailto:|tel:)/.test(url)) throw new Error(`Unsupported or runtime-external URL: ${url}`);
        return { url };
      }
      if (url.startsWith('/') || url.includes('\\')) throw new Error(`Root-only or invalid source link: ${url}`);
      const match = /^([^?#]*)(\?[^#]*)?(#.*)?$/.exec(url);
      const path = decodeURIComponent(match[1]);
      const fragment = decodeURIComponent((match[3] ?? '').slice(1));
      const target = path ? posix.normalize(posix.join(posix.dirname(current.page.source), path)) : current.page.source;
      inside(inputRoot, target);
      if (target === 'roadmap' || target.startsWith('roadmap/')) throw new Error(`Ignored roadmap dependency: ${url}`);
      if (externalSources[target]) return { url: externalSources[target], externalSource: true };
      // Even mapped targets must remain present and no-follow safe at validation time.
      regular(inputRoot, target);
      if (pages.has(target)) {
        if (image) throw new Error('Image references a page');
        const other = pages.get(target);
        if (fragment && !other.parsed.ids.has(fragment)) throw new Error(`Missing fragment: ${url}`);
        return { url: `${routeUrl(base, other.page.route)}${match[2] ?? ''}${match[3] ?? ''}` };
      }
      const asset = assets.get(target);
      if (!asset) throw new Error(`Unmapped local target: ${url}`);
      if (fragment) throw new Error('Asset fragments are unsupported in this corpus');
      return { url: posix.relative(posix.dirname(current.output), asset.output) };
    };
    const body = rewrite(current.parsed.body, current.parsed.tree, resolver);
    files[current.output] = Buffer.from(generated(current.page, current.parsed, body));
  }
  const hashes = Object.fromEntries(Object.keys(files).sort().map((key) => [key, sha256(files[key])]));
  const proof = {
    version: 1, base,
    inputs: [...pages.values()].map(({ page, sha256 }) => ({ source: page.source, route: page.route, sha256 })),
    files: hashes,
  };
  files[marker] = Buffer.from(json(proof));
  return { files, proof };
}

function validateOwned(output) {
  if (!existsSync(output)) return;
  const actual = inventory(output);
  if (!Object.hasOwn(actual, marker)) throw new Error('Unknown output: missing ownership manifest');
  const owned = JSON.parse(readFileSync(resolve(output, marker), 'utf8'));
  delete actual[marker];
  if (owned.version !== 1) throw new Error('Unknown output ownership version');
  assert.deepEqual(actual, owned.files, 'Unknown or modified output; refuse cleanup or overwrite');
  // Unknown empty directories are not silently removed either.
  const dirs = new Set(Object.keys(owned.files).flatMap((name) => {
    const parts = name.split('/');
    return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'));
  }));
  const entries = readdirDirectories(output);
  assert.deepEqual(entries.sort(), [...dirs].sort(), 'Unknown output directory');
}

import { readdirSync } from 'node:fs';
function readdirDirectories(root, dir = root) {
  return readdirSync(dir, { withFileTypes: true }).filter((entry) => entry.isDirectory()).flatMap((entry) => {
    const path = resolve(dir, entry.name);
    return [relative(root, path), ...readdirDirectories(root, path)];
  });
}

export async function prepare(options) {
  const root = resolve(options.root);
  const output = noSymlinks(root, options.output ?? 'src/content/docs', true);
  const input = noSymlinks(root, options.input ?? 'fixtures');
  if (output === root || output === input || output.startsWith(`${input}/`) || input.startsWith(`${output}/`)) throw new Error('Input/output roots must be separate');
  mkdirSync(dirname(output), { recursive: true });
  const lockPath = `${output}.lock`;
  const lock = openSync(lockPath, 'wx');
  try {
    validateOwned(output);
    const planned = await planContent({ ...options, root });
    const desired = Object.fromEntries(Object.entries(planned.files).map(([path, bytes]) => [path, sha256(bytes)]));
    if (options.check) {
      assert.deepEqual(inventory(output), desired, 'Generated view is stale or non-deterministic');
      return planned.proof;
    }
    if (existsSync(output) && isDeepStrictEqual(inventory(output), desired)) return planned.proof;
    const work = noSymlinks(root, '.work', true);
    mkdirSync(work, { recursive: true });
    const stage = mkdtempSync(resolve(work, 'stage-'));
    for (const [name, bytes] of Object.entries(planned.files)) {
      const path = inside(stage, name);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, bytes, { flag: 'wx' });
    }
    assert.deepEqual(inventory(stage), desired);
    let backup;
    if (existsSync(output)) {
      backup = resolve(mkdtempSync(resolve(work, 'previous-')), 'docs');
      renameSync(output, backup);
    }
    try { renameSync(stage, output); }
    catch (error) {
      if (backup) renameSync(backup, output);
      throw error;
    }
    return planned.proof;
  } finally {
    closeSync(lock);
    unlinkSync(lockPath);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { values } = parseArgs({ options: { input: { type: 'string' }, manifest: { type: 'string' }, output: { type: 'string' }, base: { type: 'string', default: process.env.DOCS_BASE ?? '/' }, check: { type: 'boolean', default: false } } });
    const result = await prepare({ root: process.cwd(), ...values });
    console.log(`PASS: ${result.inputs.length} pages, ${Object.keys(result.files).length} generated files at ${result.base}; ${values.check ? 'determinism checked' : 'validated before publication'}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
