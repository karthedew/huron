import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, cpSync, readFileSync, writeFileSync, unlinkSync, symlinkSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { prepare, planContent } from '../scripts/prepare-content.mjs';
import { inventory, json } from '../scripts/files.mjs';
import { ast } from '../scripts/markdown.mjs';
import { visit } from 'unist-util-visit';

const proto = process.cwd();
mkdirSync('.test-work', { recursive: true });
function fixture() {
  const root = mkdtempSync(resolve('.test-work', 'content-'));
  cpSync('fixtures', resolve(root, 'fixtures'), { recursive: true, errorOnExist: true });
  cpSync('content-map.json', resolve(root, 'content-map.json'), { errorOnExist: true });
  return root;
}
function changeMap(root, change) {
  const map = JSON.parse(readFileSync(resolve(root, 'content-map.json'), 'utf8'));
  change(map);
  writeFileSync(resolve(root, 'content-map.json'), json(map));
}
function append(root, text) {
  const path = resolve(root, 'fixtures/docs/probe.md');
  writeFileSync(path, readFileSync(path, 'utf8') + '\n' + text + '\n');
}
function cli(root, args = []) {
  return spawnSync(process.execPath, [resolve(proto, 'scripts/prepare-content.mjs'), ...args], { cwd: root, encoding: 'utf8' });
}

for (const base of ['/', '/huron-docs/']) test(`Every fixture is deterministic and source-preserving at ${base}`, async () => {
  const root = fixture();
  const before = inventory(resolve(root, 'fixtures'));
  const result = await prepare({ root, base });
  assert.equal(result.inputs.length, 14);
  assert.equal(Object.keys(result.files).length, 15);
  const first = inventory(resolve(root, 'src/content/docs'));
  const work = readdirSync(resolve(root, '.work'));
  await prepare({ root, base });
  await prepare({ root, base, check: true });
  assert.deepEqual(inventory(resolve(root, 'src/content/docs')), first);
  assert.deepEqual(inventory(resolve(root, 'fixtures')), before);
  assert.deepEqual(readdirSync(resolve(root, '.work')), work, 'An identical prepare does not publish another generation');
  assert.match(readFileSync(resolve(root, 'src/content/docs/adr/0002-domain-owned-core-workflows.md'), 'utf8'), /status: accepted/);
  assert.match(readFileSync(resolve(root, 'src/content/docs/probe.md'), 'utf8'), new RegExp(`${base}history/#domain-owned-core`));
});

test('Literal fenced code remains byte-identical while real links are transformed', async () => {
  const root = fixture();
  await prepare({ root });
  const code = (body) => {
    const values = [];
    visit(ast(body), 'code', (node) => { values.push(body.slice(node.position.start.offset, node.position.end.offset)); });
    return values;
  };
  const original = readFileSync(resolve(root, 'fixtures/docs/probe.md'), 'utf8');
  const result = readFileSync(resolve(root, 'src/content/docs/probe.md'), 'utf8');
  assert.equal(code(original).length, 3);
  assert.deepEqual(code(result), code(original));
  assert.match(result, /href|not a link/);
  assert.match(result, /\[history authority\]\(\/history\/#domain-owned-core\)/);
  assert.doesNotMatch(result, /^# Rendering probe$/m);
  assert.match(result, /<a id="rendering-probe"><\/a>/);
  assert.match(result, /<a id="explicit-contract"><\/a>/);
});

const invalid = [
  ['missing input', (root) => unlinkSync(resolve(root, 'fixtures/docs/history.md')), /ENOENT/],
  ['missing linked file', (root) => append(root, '[missing](absent.md)'), /ENOENT/],
  ['missing fragment', (root) => append(root, '[missing](history.md#absent)'), /Missing fragment/],
  ['missing asset', (root) => unlinkSync(resolve(root, 'fixtures/docs/diagram.svg')), /ENOENT/],
  ['duplicate routes', (root) => changeMap(root, (map) => { map.pages[1].route = map.pages[0].route; }), /Duplicate route/],
  ['escaping input symlink', (root) => { unlinkSync(resolve(root, 'fixtures/docs/history.md')); symlinkSync(resolve(proto, 'fixtures/docs/history.md'), resolve(root, 'fixtures/docs/history.md')); }, /Symlink/],
  ['ignored roadmap dependency', (root) => append(root, '[ignored](../roadmap/plan.md)'), /Ignored roadmap dependency/],
  ['path escape', (root) => append(root, '[escape](../../../elsewhere.md)'), /Path escape/],
  ['invalid manifest title', (root) => changeMap(root, (map) => { map.pages[0].title = ''; }), /Invalid manifest title/],
  ['invalid frontmatter YAML', (root) => writeFileSync(resolve(root, 'fixtures/docs/probe.md'), '---\ntitle: [unclosed\n---\n# Rendering probe\n'), /Invalid frontmatter/],
  ['invalid frontmatter title', (root) => writeFileSync(resolve(root, 'fixtures/docs/probe.md'), '---\ntitle: 42\n---\n# Rendering probe\n'), /Invalid frontmatter title/],
  ['unknown frontmatter field', (root) => writeFileSync(resolve(root, 'fixtures/docs/probe.md'), '---\nredirect: /somewhere/\n---\n# Rendering probe\n'), /Invalid frontmatter/],
  ['unknown native aside', (root) => append(root, ':::unknown[Invalid]\nNever silently render unknown syntax.\n:::'), /Invalid aside/],
  ['unknown legacy aside', (root) => append(root, '!!! unknown "Invalid"\n\n    Text'), /Invalid legacy aside/],
  ['unclosed native aside', (root) => append(root, ':::note\nNever close'), /Invalid aside/],
  ['root-only source link', (root) => append(root, '[root only](/history/)'), /Root-only/],
  ['external runtime image', (root) => append(root, '![remote](https://example.com/image.png)'), /runtime-external/],
  ['duplicate explicit anchor', (root) => append(root, '<a id="explicit-contract"></a>'), /Duplicate/],
  ['unknown generated file', (root) => writeFileSync(resolve(root, 'src/content/docs/unknown.txt'), 'owned by somebody else'), /Unknown or modified/],
  ['unknown empty output directory', (root) => mkdirSync(resolve(root, 'src/content/docs/unknown')), /Unknown output directory/],
  ['escaping output symlink', (root) => symlinkSync(resolve(root, 'fixtures'), resolve(root, 'src/content/docs/escape')), /Symlink/],
  ['concurrent prepare lock', (root) => writeFileSync(resolve(root, 'src/content/docs.lock'), 'other invocation'), /EEXIST/],
];
for (const [name, mutate, message] of invalid) test(`${name} fails nonzero without replacing last good output`, async () => {
  const root = fixture();
  await prepare({ root });
  const before = readFileSync(resolve(root, 'src/content/docs/probe.md'));
  mutate(root);
  const result = cli(root);
  assert.equal(result.status, 1, result.stdout + result.stderr);
  assert.match(result.stderr, message);
  assert.deepEqual(readFileSync(resolve(root, 'src/content/docs/probe.md')), before);
  assert.doesNotMatch(result.stdout, /PASS/);
  if (name === 'unknown generated file') assert.equal(readFileSync(resolve(root, 'src/content/docs/unknown.txt'), 'utf8'), 'owned by somebody else');
});

test('A changed known input becomes a new view only after validation and recovers after a failed attempt', async () => {
  const root = fixture();
  await prepare({ root });
  append(root, '[broken](absent.md)');
  assert.equal(cli(root).status, 1);
  cpSync(resolve(proto, 'fixtures/docs/probe.md'), resolve(root, 'fixtures/docs/probe.md'));
  append(root, 'A recovered fixture change.');
  assert.equal(cli(root).status, 0);
  assert.match(readFileSync(resolve(root, 'src/content/docs/probe.md'), 'utf8'), /A recovered fixture change/);
  assert.equal(cli(root, ['--check']).status, 0);
});

test('Source and output roots cannot overlap', async () => {
  const root = fixture();
  await assert.rejects(prepare({ root, output: 'fixtures/out' }), /must be separate/);
  await assert.rejects(planContent({ root, input: '../outside' }), /Path escape/);
});
