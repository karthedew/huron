import assert from 'node:assert/strict';
import { mkdtemp, readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { parse, plan, render, rewriteLinks, SOURCES as SITE_SOURCES, sync } from './sync.mjs';

const DOCS_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs');

const GUIDE = `# Guide

Intro.

## Logging in

See [errors](errors.md#codes) and [setup](#set-up).

### Set up

\`\`\`bash
# not a heading [x](missing.md)
\`\`\`

## Logging in

Twice.
`;

const ERRORS = `# Errors

## Codes

Back to [the guide](guide.md), [its setup](guide.md#set-up), [README](../README.md) and
[\`deploy/README.md\`](../deploy/README.md). Keep [web](https://example.org) and \`[a](b.md)\`.
`;

const CONCEPT = `# A concept

See [the guide](../guide.md#set-up), [below](#more), [errors](../errors.md) and
[a sibling](other.md).

## More

Text.
`;

const SOURCES = [
	{ file: 'guide.md', section: 'admin', split: true },
	{ file: 'errors.md', section: 'guides', slug: 'errors', order: 3 },
	{ file: 'concepts/concept.md', section: 'concepts', slug: 'concept', order: 1 }
];

const DOCUMENTS = { 'guide.md': GUIDE, 'errors.md': ERRORS, 'concepts/concept.md': CONCEPT };

test('parse takes the title and the second-level sections, skipping headings in code', () => {
	const document = parse(GUIDE);
	assert.equal(document.title, 'Guide');
	assert.deepEqual(
		document.sections.map((section) => [section.title, section.anchor]),
		[
			['Logging in', 'logging-in'],
			['Logging in', 'logging-in-1']
		]
	);
	assert.deepEqual(
		document.headings.map((heading) => heading.anchor),
		['guide', 'logging-in', 'set-up', 'logging-in-1']
	);
	assert.deepEqual(document.preamble.filter(Boolean), ['Intro.']);
});

test('plan splits a document by section and indexes every heading', () => {
	const { pages, urls } = plan(SOURCES, DOCUMENTS);
	assert.deepEqual(
		pages.map((page) => [page.slug, page.title, page.order]),
		[
			['admin/guide', 'Guide', 0],
			['admin/logging-in', 'Logging in', 1],
			['admin/logging-in-1', 'Logging in', 2],
			['guides/errors', 'Errors', 3],
			['concepts/concept', 'A concept', 1]
		]
	);
	assert.equal(urls.get('guide.md'), '/docs/admin/guide/');
	assert.equal(urls.get('guide.md#set-up'), '/docs/admin/logging-in/#set-up');
	assert.equal(urls.get('guide.md#logging-in-1'), '/docs/admin/logging-in-1/');
	assert.equal(urls.get('errors.md#codes'), '/docs/guides/errors/#codes');
	assert.equal(urls.get('errors.md#errors'), '/docs/guides/errors/');
});

test('split pages promote their headings one level', () => {
	const { pages, urls } = plan(SOURCES, DOCUMENTS);
	const page = render(pages[1], urls);
	assert.match(page, /^---\ntitle: "Logging in"\nsidebar:\n {2}order: 1\n---\n/);
	assert.match(page, /\n## Set up\n/);
	assert.match(page, /# not a heading \[x\]\(missing\.md\)/);
});

test('links to synced documents and headings point at the site', () => {
	const { urls } = plan(SOURCES, DOCUMENTS);
	const text = rewriteLinks(ERRORS, 'errors.md', urls);
	assert.match(text, /\[the guide\]\(\/docs\/admin\/guide\/\)/);
	assert.match(text, /\[its setup\]\(\/docs\/admin\/logging-in\/#set-up\)/);
	assert.match(text, /README \(`README\.md` in the repository\)/);
	assert.match(text, /`deploy\/README\.md`\. Keep/);
	assert.match(text, /\[web\]\(https:\/\/example\.org\)/);
	assert.match(text, /`\[a\]\(b\.md\)`/);
	assert.equal(rewriteLinks('[x](#set-up)', 'guide.md', urls), '[x](/docs/admin/logging-in/#set-up)');
});

test('links in a subdirectory of docs/ resolve against that subdirectory', () => {
	const { urls } = plan(SOURCES, DOCUMENTS);
	assert.equal(urls.get('concepts/concept.md#more'), '/docs/concepts/concept/#more');
	const text = rewriteLinks(CONCEPT, 'concepts/concept.md', urls);
	assert.match(text, /\[the guide\]\(\/docs\/admin\/logging-in\/#set-up\)/);
	assert.match(text, /\[below\]\(\/docs\/concepts\/concept\/#more\)/);
	assert.match(text, /\[errors\]\(\/docs\/guides\/errors\/\)/);
	assert.match(text, /a sibling \(`docs\/concepts\/other\.md` in the repository\)/);
	// The same name without `../` is a file in the subdirectory, not the guide at the docs root.
	assert.match(
		rewriteLinks('[x](guide.md)', 'concepts/concept.md', urls),
		/`docs\/concepts\/guide\.md` in the repository/
	);
});

test('a link to a missing heading fails the sync', () => {
	const { urls } = plan(SOURCES, DOCUMENTS);
	assert.throws(() => rewriteLinks('[x](guide.md#nope)', 'errors.md', urls), /guide\.md#nope/);
});

test('sync replaces the section directories and leaves other content alone', async () => {
	const root = await mkdtemp(path.join(tmpdir(), 'huron-docs-sync-'));
	const docsDir = path.join(root, 'docs');
	const contentDir = path.join(root, 'content');
	await mkdir(docsDir);
	await mkdir(path.join(contentDir, 'admin'), { recursive: true });
	await writeFile(path.join(docsDir, 'guide.md'), GUIDE);
	await writeFile(path.join(docsDir, 'errors.md'), ERRORS);
	await writeFile(path.join(contentDir, 'admin', 'stale.md'), 'old');
	await writeFile(path.join(contentDir, 'index.mdx'), 'kept');
	await mkdir(path.join(docsDir, 'concepts'));
	await writeFile(path.join(docsDir, 'concepts', 'concept.md'), CONCEPT);
	const slugs = await sync({ docsDir, contentDir, sources: SOURCES });
	assert.equal(slugs.length, 5);
	assert.deepEqual((await readdir(path.join(contentDir, 'admin'))).sort(), [
		'guide.md',
		'logging-in-1.md',
		'logging-in.md'
	]);
	assert.equal(await readFile(path.join(contentDir, 'index.mdx'), 'utf8'), 'kept');
	const errors = await readFile(path.join(contentDir, 'guides', 'errors.md'), 'utf8');
	assert.match(errors, /Generated by web\/docs-site\/scripts\/sync\.mjs from docs\/errors\.md/);
	const concept = await readFile(path.join(contentDir, 'concepts', 'concept.md'), 'utf8');
	assert.match(concept, /from docs\/concepts\/concept\.md: edit that file/);
});

test('the concept pages keep their reading order', () => {
	const concepts = SITE_SOURCES.filter((source) => source.section === 'concepts');
	assert.deepEqual(
		concepts.map((source) => [source.file, source.slug, source.order]),
		[
			['concepts/how-huron-works.md', 'how-huron-works', 1],
			['concepts/raw-ingest.md', 'raw-ingest', 2],
			['concepts/search.md', 'search', 3],
			['concepts/metadata-and-schemas.md', 'metadata-and-schemas', 4],
			['concepts/access-and-roles.md', 'access-and-roles', 5],
			['architecture.md', 'architecture', 6]
		]
	);
});

test('every link from one docs page to another resolves to a site page', async () => {
	const documents = {};
	for (const source of SITE_SOURCES) {
		documents[source.file] = await readFile(path.join(DOCS_DIR, source.file), 'utf8');
	}
	const { pages, urls } = plan(SITE_SOURCES, documents);
	assert.deepEqual(
		pages.filter((page) => page.slug.startsWith('concepts/')).map((page) => page.title),
		[
			'How Huron works',
			'How raw ingest works',
			'How search works',
			'Metadata and schemas',
			'Access and roles',
			'Architecture'
		]
	);
	// A link to another docs/ page that fell back to its repository path is a broken link.
	for (const page of pages) {
		const body = render(page, urls);
		assert.doesNotMatch(body, /`docs\/[^`]*\.md` in the repository/, `docs/${page.file}`);
	}
});
