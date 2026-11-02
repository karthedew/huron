// @vitest-environment node
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, symlink, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import svelteConfig from '../../../svelte.config.js';
import {
	DEFAULT_DOCS_DIR,
	DOCS_CSP_DIRECTIVES,
	docsPolicy,
	docsRoot,
	isDocsPath,
	scriptHashes,
	serveDocs
} from './docs';

vi.mock('$env/dynamic/private', () => ({ env: {} }));

/**
 * A stand-in for the Starlight build (`web/docs-site/dist`): a home page and a 404 page with an
 * inline script each, a CLI reference page with a module script, an Astro asset and a Pagefind
 * file. `docs-outside.txt` beside it is outside the build.
 */
const FIXTURE = fileURLToPath(new URL('../testing/docs', import.meta.url));
const ORIGIN = 'http://localhost:4173';

function get(pathname: string, method = 'GET') {
	const url = new URL(pathname, ORIGIN);
	return serveDocs(new Request(url, { method }), url, FIXTURE);
}

function hashOf(text: string): string {
	return `'sha256-${createHash('sha256').update(text).digest('base64')}'`;
}

async function fixtureText(relative: string): Promise<string> {
	return readFile(path.join(FIXTURE, relative), 'utf8');
}

describe('isDocsPath', () => {
	it.each(['/docs', '/docs/', '/docs/reference/cli/get/', '/docs/_astro/x.css'])(
		'holds %s',
		(pathname) => expect(isDocsPath(pathname)).toBe(true)
	);

	it.each(['/', '/doc', '/docsx', '/docs-site/dist/index.html', '/catalogs/docs'])(
		'leaves %s to the application',
		(pathname) => expect(isDocsPath(pathname)).toBe(false)
	);
});

describe('docsRoot', () => {
	it('is the configured directory, made absolute', () => {
		expect(docsRoot({ HURON_WEB_DOCS_DIR: 'somewhere/dist' })).toBe(path.resolve('somewhere/dist'));
	});

	it.each([{}, { HURON_WEB_DOCS_DIR: '' }])('defaults to the docs-site build (%o)', (source) => {
		expect(docsRoot(source)).toBe(path.resolve(DEFAULT_DOCS_DIR));
	});
});

describe('scriptHashes', () => {
	it('hashes the text of each inline script exactly as the page holds it', () => {
		const theme = "\n\tdocument.documentElement.dataset.theme = 'dark';\n";
		const html = `<head><script>${theme}</script><script type="module">import './x.js';</script></head>`;
		expect(scriptHashes(html)).toEqual([hashOf(theme), hashOf("import './x.js';")]);
	});

	it('leaves out scripts loaded from a file and repeats no hash', () => {
		const html =
			'<script src="/docs/_astro/a.js"></script><script type="module" src=/docs/b.js></script>' +
			'<script>one()</script><SCRIPT>one()</SCRIPT >';
		expect(scriptHashes(html)).toEqual([hashOf('one()')]);
	});

	it('finds nothing in a page without inline scripts', () => {
		expect(scriptHashes('<p>No scripts</p>')).toEqual([]);
		expect(scriptHashes('')).toEqual([]);
	});

	it('hashes an empty inline script too, which browsers also check', () => {
		expect(scriptHashes('<script></script>')).toEqual([hashOf('')]);
	});
});

describe('docsPolicy', () => {
	it("adds the page's hashes to script-src only", () => {
		const policy = docsPolicy(["'sha256-abc='"]);
		expect(policy).toContain("script-src 'self' 'wasm-unsafe-eval' 'sha256-abc='");
		expect(policy.match(/sha256/g)).toHaveLength(1);
	});

	it('never lets inline scripts run unhashed', () => {
		const scripts = DOCS_CSP_DIRECTIVES['script-src'];
		expect(scripts).not.toContain("'unsafe-inline'");
		expect(scripts).not.toContain("'unsafe-eval'");
		expect(docsPolicy()).toMatch(/^default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; /);
	});

	it("differs from the application's policy in script-src alone", () => {
		const keywords = new Set(['self', 'none', 'unsafe-inline', 'unsafe-eval', 'wasm-unsafe-eval']);
		const application = Object.fromEntries(
			Object.entries(svelteConfig.kit?.csp?.directives ?? {}).map(([name, sources]) => [
				name,
				(sources as string[]).map((source) => (keywords.has(source) ? `'${source}'` : source))
			])
		);
		const { 'script-src': docsScripts, ...docsRest } = DOCS_CSP_DIRECTIVES;
		const { 'script-src': applicationScripts, ...applicationRest } = application;
		expect(docsRest).toEqual(applicationRest);
		expect(docsScripts).toEqual([...(applicationScripts ?? []), "'wasm-unsafe-eval'"]);
	});
});

describe('serveDocs', () => {
	afterEach(async () => {
		vi.restoreAllMocks();
	});

	it("answers /docs/ with the home page, its scripts' hashes and the security headers", async () => {
		const response = await get('/docs/');
		const html = await fixtureText('index.html');
		expect(response.status).toBe(200);
		expect(await response.text()).toBe(html);
		expect(Object.fromEntries(response.headers)).toMatchObject({
			'content-type': 'text/html; charset=utf-8',
			'content-length': String(Buffer.byteLength(html)),
			'cache-control': 'no-cache',
			'content-security-policy': docsPolicy(scriptHashes(html)),
			'x-content-type-options': 'nosniff',
			'x-frame-options': 'DENY',
			'referrer-policy': 'same-origin'
		});
		expect(scriptHashes(html)).toHaveLength(1);
		expect(response.headers.has('set-cookie')).toBe(false);
	});

	it.each([
		['/docs', '/docs/'],
		['/docs/reference/cli/checkout', '/docs/reference/cli/checkout/'],
		['/docs/reference?x=1', '/docs/reference/?x=1']
	])('redirects the directory %s to %s', async (pathname, location) => {
		const response = await get(pathname);
		expect(response.status).toBe(308);
		expect(response.headers.get('location')).toBe(location);
		expect(response.headers.get('x-frame-options')).toBe('DENY');
	});

	it("answers a directory's index page", async () => {
		const response = await get('/docs/reference/cli/checkout/');
		expect(response.status).toBe(200);
		expect(await response.text()).toContain('<h1>huron checkout</h1>');
		// A module script loaded from a file: 'self' allows it, no hash needed.
		expect(response.headers.get('content-security-policy')).toBe(docsPolicy());
	});

	it.each([
		['/docs/_astro/site.css', 'text/css; charset=utf-8', 'public, max-age=31536000, immutable'],
		[
			'/docs/_astro/page.js',
			'text/javascript; charset=utf-8',
			'public, max-age=31536000, immutable'
		],
		['/docs/pagefind/wasm.en.pagefind', 'application/octet-stream', 'no-cache']
	])('answers the asset %s as %s', async (pathname, type, cache) => {
		const response = await get(pathname);
		expect(response.status).toBe(200);
		expect(response.headers.get('content-type')).toBe(type);
		expect(response.headers.get('cache-control')).toBe(cache);
		expect(response.headers.get('content-security-policy')).toBe(docsPolicy());
		expect(response.headers.get('x-content-type-options')).toBe('nosniff');
	});

	it("answers an unknown path with the build's 404 page and its own hashes", async () => {
		const response = await get('/docs/reference/cli/nowhere/');
		const html = await fixtureText('404.html');
		expect(response.status).toBe(404);
		expect(await response.text()).toBe(html);
		expect(response.headers.get('content-security-policy')).toBe(docsPolicy(scriptHashes(html)));
		expect(response.headers.get('cache-control')).toBe('no-cache');
	});

	it.each([
		'/docs/..%2Fdocs-outside.txt',
		'/docs/%2e%2e/docs-outside.txt',
		'/docs/reference/..%2F..%2F..%2Fdocs-outside.txt',
		'/docs/..%5Cdocs-outside.txt',
		'/docs/index.html%00',
		'/docs/%E0%A4%A',
		'/docs//index.html',
		'/docs/.hidden',
		'/docs-outside.txt',
		'/docs/_astro/site.css/'
	])('serves nothing outside a file of the build for %s', async (pathname) => {
		const response = await get(pathname);
		expect(response.status).toBe(404);
		expect(await response.text()).toContain('Page not found');
	});

	it('answers HEAD with the headers of GET and no body', async () => {
		const response = await get('/docs/', 'HEAD');
		expect(response.status).toBe(200);
		expect(response.headers.get('content-length')).toBe(
			String(Buffer.byteLength(await fixtureText('index.html')))
		);
		expect(await response.text()).toBe('');
	});

	it.each(['POST', 'PUT', 'DELETE'])('refuses %s', async (method) => {
		const response = await get('/docs/', method);
		expect(response.status).toBe(405);
		expect(response.headers.get('allow')).toBe('GET, HEAD');
		expect(response.headers.get('content-security-policy')).toBe(docsPolicy());
	});

	it('says how to build the documentation when the build is missing', async () => {
		const url = new URL('/docs/', ORIGIN);
		const response = await serveDocs(new Request(url), url, path.join(FIXTURE, 'missing'));
		expect(response.status).toBe(404);
		expect(await response.text()).toContain('npm run docs:build');
		expect(response.headers.get('x-frame-options')).toBe('DENY');
	});

	describe('in a build of its own', () => {
		let root: string;

		async function build(files: Record<string, string>): Promise<string> {
			root = await mkdtemp(path.join(tmpdir(), 'huron-docs-'));
			for (const [name, text] of Object.entries(files)) {
				await mkdir(path.dirname(path.join(root, 'dist', name)), { recursive: true });
				await writeFile(path.join(root, 'dist', name), text);
			}
			return path.join(root, 'dist');
		}

		afterEach(async () => {
			await rm(root, { recursive: true, force: true });
		});

		it('follows no link that leads out of the build', async () => {
			const dist = await build({ 'index.html': '<p>home</p>' });
			await writeFile(path.join(root, 'secret.txt'), 'secret');
			await symlink(path.join(root, 'secret.txt'), path.join(dist, 'leak.txt'));
			await symlink(root, path.join(dist, 'up'));
			for (const pathname of ['/docs/leak.txt', '/docs/up/secret.txt']) {
				const url = new URL(pathname, ORIGIN);
				const response = await serveDocs(new Request(url), url, dist);
				expect(response.status, pathname).toBe(404);
				expect(await response.text(), pathname).not.toContain('secret');
			}
		});

		it('answers a plain 404 without a 404 page, and a directory without an index as missing', async () => {
			const dist = await build({ 'guides/notes.txt': 'notes' });
			for (const pathname of ['/docs/nowhere', '/docs/guides/']) {
				const url = new URL(pathname, ORIGIN);
				const response = await serveDocs(new Request(url), url, dist);
				expect(response.status, pathname).toBe(404);
				expect(await response.text(), pathname).toBe('Not Found');
			}
		});

		it('answers an unknown kind of file as bytes', async () => {
			const dist = await build({ 'pagefind/index/en_1.pf_index': 'index' });
			const url = new URL('/docs/pagefind/index/en_1.pf_index', ORIGIN);
			const response = await serveDocs(new Request(url), url, dist);
			expect(response.headers.get('content-type')).toBe('application/octet-stream');
			expect(await response.text()).toBe('index');
		});
	});
});
