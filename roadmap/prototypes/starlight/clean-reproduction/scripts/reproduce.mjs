import { mkdirSync, cpSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import assert from 'node:assert/strict';
import { json, sha256, inventory } from './files.mjs';

const source = process.cwd();
const clean = resolve('clean-reproduction');
if (existsSync(clean)) throw new Error('Clean reproduction destination exists; preserve it, do not replay over unknown data');
mkdirSync(clean);
for (const file of ['package.json', 'package-lock.json', '.npmrc', 'astro.config.mjs', 'tsconfig.json', 'content-map.json', 'playwright.config.ts', 'fixtures', 'scripts', 'tests', 'e2e', 'public']) cpSync(file, resolve(clean, file), { recursive: true, errorOnExist: true });
mkdirSync(resolve(clean, 'src/styles'), { recursive: true });
cpSync('src/content.config.ts', resolve(clean, 'src/content.config.ts'));
cpSync('src/styles/probe.css', resolve(clean, 'src/styles/probe.css'));
mkdirSync(resolve(clean, 'evidence'));
const outcomes = [];
for (const [command, base] of [[['npm', 'ci'], '/'], [['npm', 'run', 'check'], '/'], [['npm', 'run', 'build'], '/'], [['npm', 'run', 'build'], '/huron-docs/']]) {
  const result = spawnSync(command[0], command.slice(1), { cwd: clean, env: { ...process.env, DOCS_BASE: base }, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  outcomes.push({ command, cwd: clean, base, exit: result.status, output: result.stdout + result.stderr });
  writeFileSync('evidence/clean-reproduction-commands.json', json(outcomes));
  process.stdout.write(result.stdout + result.stderr);
  assert.equal(result.status, 0, `${command.join(' ')} must pass in the clean package`);
}
assert.equal(sha256(readFileSync('package-lock.json')), sha256(readFileSync(resolve(clean, 'package-lock.json'))));
assert.deepEqual(inventory(resolve(clean, 'fixtures')), inventory(resolve(source, 'fixtures')));
for (const base of ['root', 'subbase']) {
  const original = JSON.parse(readFileSync(`evidence/manifests/${base}.json`, 'utf8'));
  const rebuilt = JSON.parse(readFileSync(resolve(clean, `evidence/manifests/${base}.json`), 'utf8'));
  assert.deepEqual(rebuilt, original, `Clean ${base} route/content/asset manifests must match, including HTML and asset bytes`);
}
writeFileSync('evidence/clean-reproduction.json', json({ pass: true, cwd: clean, lockSha256: sha256(readFileSync('package-lock.json')), inputFiles: Object.keys(inventory(resolve(source, 'fixtures'))).length, compared: ['root', 'subbase'], volatileLogsExcluded: true }));
console.log('PASS: clean locked install/check/build at both bases; identical full route/content/asset manifests, fixture bytes and lock hash.');
