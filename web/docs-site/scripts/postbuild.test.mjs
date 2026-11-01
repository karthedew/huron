import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { brokenLinks, inlineHashes, rewrittenOptions } from './postbuild.mjs';

const sha = (text) => `'sha256-${createHash('sha256').update(text).digest('base64')}'`;

test('inline scripts and style elements are hashed once each; external scripts are not', () => {
	const page = '<script>a()</script><script type="module" src="/x.js"></script><style>p{}</style>';
	const hashes = inlineHashes([page, page, '<script is:inline>b()</script>']);
	assert.deepEqual(hashes['script-src'], [sha('a()'), sha('b()')].sort());
	assert.deepEqual(hashes['style-src'], [sha('p{}')]);
});

test('links to missing pages or ids are reported; assets and other sites are not', () => {
	const pages = new Map([
		[
			'index.html',
			'<a href="/docs/guide/#ok"></a><a href="/docs/guide/#gone"></a><a href="/docs/nope/"></a>' +
				'<a href="#top"></a><a href="/docs/favicon.svg"></a><a href="https://example.org/"></a>'
		],
		['guide/index.html', '<h2 id="ok"></h2><a href="/docs/"></a>']
	]);
	assert.deepEqual(brokenLinks(pages), [
		'index.html: /docs/guide/#gone',
		'index.html: /docs/nope/',
		'index.html: #top'
	]);
});

test('typographic dashes before a letter are reported on CLI reference pages only', () => {
	const pages = new Map([
		['reference/cli/adm/index.html', '<p>on an organization (\u2013org) or <code>--catalog</code></p>'],
		['reference/cli/get/index.html', '<p>pages 1\u20132 and --org</p>'],
		['guides/index.html', '<p>a dash \u2013word in a guide</p>']
	]);
	assert.deepEqual(rewrittenOptions(pages), ['reference/cli/adm/index.html: \u2013org']);
});
