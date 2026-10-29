// Isolated planning-artifact check; never used as a product gate dependency.
import assert from 'node:assert/strict';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../../', import.meta.url));
const owned = ['roadmap/dispatch-concurrency-design.md', 'roadmap/plans/dispatch-concurrency.md',
  ...readdirSync(resolve(root, 'roadmap/prototypes/dispatch-concurrency'))
    .filter(n => /\.(md|mjs)$/.test(n)).map(n => `roadmap/prototypes/dispatch-concurrency/${n}`)];
for (const name of owned) {
  const path = resolve(root, name);
  const text = readFileSync(path, 'utf8');
  assert.ok(text.endsWith('\n'), `${name}: final newline`);
  assert.ok(!/[\t ]+$/m.test(text), `${name}: trailing whitespace`);
  if (name.endsWith('.md')) {
    for (const m of text.matchAll(/\[[^\]\n]*\]\(([^)\s]+)\)/g)) {
      if (/^[a-z]+:/i.test(m[1])) continue;
      assert.ok(existsSync(resolve(dirname(path), m[1])), `${name}: missing link ${m[1]}`);
    }
    for (const m of text.matchAll(/\.agents\/skills\/[a-z-]+\/SKILL\.md/g)) {
      assert.ok(existsSync(resolve(root, m[0])), `${name}: missing skill ${m[0]}`);
    }
  }
}
const plan = readFileSync(resolve(root, 'roadmap/plans/dispatch-concurrency.md'), 'utf8');
for (const section of ['Context and outcome', 'Prototype evidence', 'Exact scope and ownership',
  'Interfaces and implementation examples', 'Serial task slices', 'Skills',
  'Acceptance and complete applicable gates', 'Blockers and readiness', 'Execution ledger',
  'Escalation / final receipt']) assert.ok(plan.includes(`## ${section}`), section);
console.log(`Owned planning text: ${owned.length} files, whitespace/links/skills/phase sections OK`);
