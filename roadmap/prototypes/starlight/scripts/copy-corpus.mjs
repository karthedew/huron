import { readFileSync, mkdirSync, writeFileSync, lstatSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

// One-time, explicit copy of public Markdown only. Never traverses the workspace.
const repo = fileURLToPath(new URL('../../../../', import.meta.url));
const manifest = JSON.parse(readFileSync('content-map.json', 'utf8'));
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const proofs = [];
for (const page of manifest.pages.filter((page) => !page.synthetic)) {
  if (!/^(docs\/|design\/raw-first\.md$|CONTEXT\.md$)/.test(page.source) || !page.source.endsWith('.md')) throw new Error('Only explicit Markdown fixtures');
  const original = resolve(repo, page.source);
  if (!lstatSync(original).isFile()) throw new Error(`Not a regular source: ${page.source}`);
  const bytes = readFileSync(original);
  const copied = page.excerpt ? Buffer.from(bytes.toString('utf8').split('\n').slice(page.excerpt[0] - 1, page.excerpt[1]).join('\n') + '\n') : bytes;
  const destination = resolve('fixtures', page.source);
  mkdirSync(dirname(destination), { recursive: true });
  writeFileSync(destination, copied, { flag: 'wx' });
  proofs.push({ source: page.source, excerpt: page.excerpt ?? null, sourceBytes: bytes.length, sourceSha256: sha(bytes), fixtureBytes: copied.length, fixtureSha256: sha(copied) });
}
writeFileSync('evidence/corpus.json', JSON.stringify(proofs, null, 2) + '\n', { flag: 'wx' });
console.log(`Copied ${proofs.length} canonical pages: ${proofs.filter((p) => !p.excerpt).length} whole and one credential-free verbatim excerpt.`);
