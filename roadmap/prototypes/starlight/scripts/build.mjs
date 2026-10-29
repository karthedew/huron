import { spawnSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, writeFileSync, openSync, closeSync, unlinkSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { prepare } from './prepare-content.mjs';
import { checkSite } from './check-site.mjs';
import { inventory, json, noSymlinks } from './files.mjs';

const root = process.cwd();
const base = process.env.DOCS_BASE ?? '/';
const name = base === '/' ? 'root' : 'subbase';
const dist = `dist/${name}`;
const ownership = `.work/build-${name}.json`;
mkdirSync(noSymlinks(root, '.work', true), { recursive: true });
const lock = openSync('.work/build.lock', 'wx');
try {
  // Astro empties outDir; refuse if it contains anything not from our last build.
  noSymlinks(root, dist, true);
  if (existsSync(dist)) {
    if (!existsSync(ownership)) throw new Error('Unknown build output; refuse Astro cleanup');
    assert.deepEqual(inventory(resolve(dist)), JSON.parse(readFileSync(ownership, 'utf8')), 'Unknown/modified build output; refuse cleanup');
  }
  await prepare({ root, base });
  const result = spawnSync(process.execPath, ['node_modules/astro/bin/astro.mjs', 'build'], { stdio: 'inherit', env: process.env });
  // Keep the exact failed-build inventory too; never mistake it for qualification.
  if (existsSync(dist)) writeFileSync(ownership, json(inventory(resolve(dist))));
  if (result.status !== 0) throw new Error(`Astro build failed (${result.status})`);
  const proof = checkSite({ root, dist, base });
  mkdirSync('evidence/manifests', { recursive: true });
  writeFileSync(`evidence/manifests/${name}.json`, json(proof));
  console.log(`PASS: ${proof.pages.length} emitted routes and ${Object.keys(proof.assets).length} assets verified at ${base}`);
} finally {
  closeSync(lock);
  unlinkSync('.work/build.lock');
}
