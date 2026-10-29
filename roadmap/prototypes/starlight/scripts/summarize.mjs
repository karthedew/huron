import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { json, sha256, inventory } from './files.mjs';
import { ast } from './markdown.mjs';
import { visit } from 'unist-util-visit';

const readJSON = (file) => JSON.parse(readFileSync(file, 'utf8'));
const cliResult = (file) => JSON.parse(readFileSync(file, 'utf8').split('### Result\n')[1].split('\n### ')[0].trim());
const rootErrors = readFileSync(existsSync('evidence/commands/root-roadmap-check-final.log') ? 'evidence/commands/root-roadmap-check-final.log' : 'evidence/commands/root-roadmap-check.log', 'utf8').trim().split('\n');
const externalWhitespace = rootErrors.filter((line) => line.includes('/node_modules/') && line.endsWith(': trailing whitespace'));
const generatedWhitespace = rootErrors.filter((line) => line.includes('/evidence/e2e-') && line.includes('/error-context.md:') && line.endsWith(': trailing whitespace'));
const otherRootErrors = rootErrors.filter((line) => !externalWhitespace.includes(line) && !generatedWhitespace.includes(line));

function e2e(file) {
  const report = readJSON(file);
  const result = { stats: report.stats, browserVersions: [], externalRequests: [], normalErrors: [], injected: [] };
  const browsers = new Set();
  function walk(suite) {
    for (const spec of suite.specs ?? []) for (const test of spec.tests ?? []) for (const run of test.results ?? []) {
      for (const attachment of run.attachments ?? []) {
        if (!['network-and-console', 'injected-index-failure'].includes(attachment.name)) continue;
        const data = JSON.parse(attachment.body ? Buffer.from(attachment.body, 'base64').toString('utf8') : readFileSync(attachment.path, 'utf8'));
        if (attachment.name === 'injected-index-failure') result.injected.push({ project: test.projectName, ...data });
        else {
          if (data.browserVersion) browsers.add(data.browserVersion);
          result.externalRequests.push(...data.external);
          if (!spec.title.startsWith('An aborted') && !spec.title.startsWith('A missing')) result.normalErrors.push(...data.errors);
        }
      }
    }
    for (const child of suite.suites ?? []) walk(child);
  }
  for (const suite of report.suites) walk(suite);
  result.browserVersions = [...browsers];
  return result;
}
const owned = [
  '.npmrc', 'package.json', 'package-lock.json', 'content-map.json', 'astro.config.mjs',
  'tsconfig.json', 'playwright.config.ts', 'src/content.config.ts', 'src/styles/probe.css',
  ...['scripts', 'tests', 'e2e', 'fixtures', 'public'].flatMap((dir) => Object.keys(inventory(resolve(dir))).map((name) => `${dir}/${name}`)),
  ...['evidence.md', 'evidence/README.md', 'evidence/pins.md'].filter(existsSync),
].sort();
const whitespace = [];
const ownLinks = [];
for (const file of owned) {
  const text = readFileSync(file, 'utf8');
  text.split('\n').forEach((line, index) => { if (line.trimEnd() !== line) whitespace.push(`${file}:${index + 1}`); });
  if (!['evidence.md', 'evidence/README.md', 'evidence/pins.md'].includes(file)) continue;
  visit(ast(text), (node) => {
    if (!['link', 'image', 'definition'].includes(node.type) || /^[a-z][a-z\d+.-]*:/i.test(node.url)) return;
    const target = new URL(node.url, new URL(file, `file://${process.cwd()}/`));
    const path = decodeURIComponent(target.pathname);
    if (!existsSync(path)) ownLinks.push(`${file}: missing ${node.url}`);
    if (target.hash && path.endsWith('.md')) ownLinks.push(`${file}: use explicit evidence files instead of unchecked fragment ${node.url}`);
  });
}
assert.deepEqual(whitespace, [], 'Authored/copied source text whitespace');
assert.deepEqual(ownLinks, [], 'Owned evidence local references');
const ownedFiles = Object.fromEntries(owned.map((file) => [file, sha256(readFileSync(file))]));
writeFileSync('evidence/owned-files.json', json(ownedFiles));
const sameBuildInputs = ['package.json', 'package-lock.json', '.npmrc', 'astro.config.mjs', 'content-map.json', 'src/content.config.ts', 'src/styles/probe.css', 'scripts/files.mjs', 'scripts/markdown.mjs', 'scripts/prepare-content.mjs', 'scripts/check-site.mjs', 'scripts/build.mjs'];
for (const path of sameBuildInputs) assert.equal(sha256(readFileSync(path)), sha256(readFileSync(`clean-reproduction/${path}`)), `Clean build input remains exact: ${path}`);
for (const base of ['root', 'subbase']) assert.deepEqual(readJSON(`evidence/manifests/${base}.json`), readJSON(`clean-reproduction/evidence/manifests/${base}.json`));
const summary = {
  verdict: 'FAIL: index-failure UX and root checker findings prevent a full gate PASS',
  package: readJSON('evidence/package-proof.json'),
  rootChecker: { total: rootErrors.length, thirdPartyWhitespace: externalWhitespace.length, generatedPlaywrightWhitespace: generatedWhitespace.length, otherErrors: otherRootErrors },
  root: e2e('evidence/e2e-root-final.json'),
  subbase: e2e('evidence/e2e-subbase-final.json'),
  namedRoot: cliResult('evidence/commands/browser-named-matrix.log'),
  namedSubbase: cliResult('evidence/commands/browser-subbase-matrix.log'),
  namedFailure: cliResult('evidence/commands/browser-subbase-failures.log'),
  manifests: Object.fromEntries(['root', 'subbase'].map((base) => { const m = readJSON(`evidence/manifests/${base}.json`); return [base, { pages: m.pages.length, assets: Object.keys(m.assets).length, localLinks: m.localLinks, externalReferences: m.externalReferences }]; })),
  cleanReproduction: readJSON('evidence/clean-reproduction.json'),
  copiedCorpus: readJSON('evidence/corpus.json'),
  ownText: { files: owned.length, whitespaceErrors: 0, brokenEvidenceReferences: 0 },
  sourceState: { ...readJSON('evidence/initial-state.json'), files: undefined },
  screenshots: Object.keys(inventory(resolve('evidence/screenshots'))),
  servicesStopped: readJSON('.work/preview.json').stopped,
};
writeFileSync('evidence/summary.json', json(summary));
console.log(json({ rootChecker: summary.rootChecker, rootTests: summary.root.stats, subbaseTests: summary.subbase.stats, observedBrowserVersions: summary.subbase.browserVersions, normalConsoleErrors: summary.root.normalErrors.length + summary.subbase.normalErrors.length, attemptedExternalRequests: summary.root.externalRequests.length + summary.subbase.externalRequests.length, manifests: summary.manifests, ownText: summary.ownText, screenshots: summary.screenshots.length, servicesStopped: summary.servicesStopped }));
