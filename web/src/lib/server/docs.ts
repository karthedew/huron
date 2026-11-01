import { createHash } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { env } from '$env/dynamic/private';
import { setSecurityHeaders } from './security-headers';

/**
 * The documentation: the static Starlight build of `web/docs-site` (`npm run docs:build`), which
 * the web serves at `/docs` to anyone, signed in or not (docs/web-design.md §3.9). The hook
 * answers these paths before it reads a session, so they set no cookie and call no API.
 */
export const DOCS_PREFIX = '/docs';

/** Where the build is when `HURON_WEB_DOCS_DIR` is unset, relative to the working directory. */
export const DEFAULT_DOCS_DIR = 'docs-site/dist';

/**
 * The documentation's content security policy: the application's (`kit.csp` in
 * `svelte.config.js`), except `script-src`. That adds the hash of each inline script of the page
 * served (Starlight's theme script, small scripts Astro inlines) and `'wasm-unsafe-eval'`, which
 * Pagefind's search needs to compile its WebAssembly. No `'unsafe-inline'` for scripts.
 */
export const DOCS_CSP_DIRECTIVES: Readonly<Record<string, readonly string[]>> = {
	'default-src': ["'self'"],
	'script-src': ["'self'", "'wasm-unsafe-eval'"],
	'style-src': ["'self'", "'unsafe-inline'"],
	'img-src': ["'self'", 'data:'],
	'font-src': ["'self'"],
	'connect-src': ["'self'"],
	'object-src': ["'none'"],
	'base-uri': ["'self'"],
	'frame-ancestors': ["'none'"]
};

/** Whether the web answers `pathname` from the documentation. */
export function isDocsPath(pathname: string): boolean {
	return pathname === DOCS_PREFIX || pathname.startsWith(`${DOCS_PREFIX}/`);
}

/** The build's directory: `HURON_WEB_DOCS_DIR`, else `DEFAULT_DOCS_DIR`, made absolute. */
export function docsRoot(source: Record<string, string | undefined> = env): string {
	const configured = source.HURON_WEB_DOCS_DIR;
	return path.resolve(
		configured === undefined || configured === '' ? DEFAULT_DOCS_DIR : configured
	);
}

/** The documentation's policy for a page whose inline scripts have `hashes` (see `scriptHashes`). */
export function docsPolicy(hashes: readonly string[] = []): string {
	return Object.entries(DOCS_CSP_DIRECTIVES)
		.map(([directive, sources]) => {
			const all = directive === 'script-src' ? [...sources, ...hashes] : sources;
			return [directive, ...all].join(' ');
		})
		.join('; ');
}

/**
 * The CSP source of each distinct inline script of an HTML page, `'sha256-<base64>'`: the hash
 * of its text exactly as the page holds it, which is what browsers compare. Scripts with a `src`
 * are left out; `'self'` covers them.
 */
export function scriptHashes(html: string): string[] {
	const hashes = new Set<string>();
	for (const [, attributes, text] of html.matchAll(SCRIPT)) {
		if (SRC.test(attributes)) continue;
		hashes.add(`'sha256-${createHash('sha256').update(text, 'utf8').digest('base64')}'`);
	}
	return [...hashes];
}

/**
 * The answer to a documentation request. GET and HEAD only. A directory answers its
 * `index.html`, and its path without the trailing slash redirects to the path with it, so the
 * build's relative links resolve. Anything that is not a file inside `root` (a missing path, a
 * `.` or `..` segment, an encoded slash, a link that leads out of `root`) answers the build's
 * `404.html` with status 404.
 */
export async function serveDocs(request: Request, url: URL, root: string): Promise<Response> {
	if (request.method !== 'GET' && request.method !== 'HEAD') {
		return plain(405, 'Method Not Allowed', { allow: 'GET, HEAD' });
	}
	const head = request.method === 'HEAD';
	const base = await realpathOf(root);
	if (base === undefined) return plain(404, NOT_BUILT);
	const found = await locate(base, url.pathname);
	if (found.kind === 'directory') {
		return plain(308, null, { location: `${url.pathname}/${url.search}` });
	}
	if (found.kind === 'file') return file(base, found.file, 200, head);
	const notFound = path.join(base, NOT_FOUND_PAGE);
	if ((await kindOf(notFound)) === 'file') return file(base, notFound, 404, head);
	return plain(404, 'Not Found');
}

const SCRIPT = /<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
const SRC = /(?:^|\s)src\s*=/i;
const NOT_FOUND_PAGE = '404.html';
const INDEX_PAGE = 'index.html';
/** Astro's hashed assets, which never change under their name. */
const IMMUTABLE_DIR = '_astro';
const NOT_BUILT =
	'The documentation is not built: run `npm run docs:build` in web/, or set HURON_WEB_DOCS_DIR.';

const CONTENT_TYPES: ReadonlyMap<string, string> = new Map([
	['.html', 'text/html; charset=utf-8'],
	['.css', 'text/css; charset=utf-8'],
	['.js', 'text/javascript; charset=utf-8'],
	['.mjs', 'text/javascript; charset=utf-8'],
	['.json', 'application/json'],
	['.xml', 'application/xml'],
	['.txt', 'text/plain; charset=utf-8'],
	['.svg', 'image/svg+xml'],
	['.png', 'image/png'],
	['.jpg', 'image/jpeg'],
	['.jpeg', 'image/jpeg'],
	['.gif', 'image/gif'],
	['.webp', 'image/webp'],
	['.avif', 'image/avif'],
	['.ico', 'image/x-icon'],
	['.woff', 'font/woff'],
	['.woff2', 'font/woff2'],
	['.wasm', 'application/wasm']
]);
/** Pagefind's index, fragments and gzipped WebAssembly, which its script reads as bytes. */
const BYTES = 'application/octet-stream';

type Located = { kind: 'file'; file: string } | { kind: 'directory' } | { kind: 'missing' };

async function locate(base: string, pathname: string): Promise<Located> {
	const segments = segmentsOf(pathname);
	if (segments === null) return { kind: 'missing' };
	const target = await realpathOf(path.join(base, ...segments));
	if (target === undefined || !within(base, target)) return { kind: 'missing' };
	const kind = await kindOf(target);
	const slashed = pathname.endsWith('/');
	if (kind === 'file' && !slashed) return { kind: 'file', file: target };
	if (kind !== 'directory') return { kind: 'missing' };
	if (!slashed) return { kind: 'directory' };
	const index = path.join(target, INDEX_PAGE);
	return (await kindOf(index)) === 'file' ? { kind: 'file', file: index } : { kind: 'missing' };
}

/**
 * The decoded path segments below `/docs`, or `null` when one may not name a file of the build:
 * empty (`//`), `.` or `..`, a dot file, or holding a slash, a backslash or a NUL once decoded.
 */
function segmentsOf(pathname: string): string[] | null {
	if (!isDocsPath(pathname)) return null;
	const rest = pathname.slice(DOCS_PREFIX.length);
	if (rest === '') return [];
	const raw = rest.slice(1).split('/');
	if (raw.at(-1) === '') raw.pop();
	const segments: string[] = [];
	for (const encoded of raw) {
		let segment: string;
		try {
			segment = decodeURIComponent(encoded);
		} catch {
			return null;
		}
		if (segment === '' || segment.startsWith('.') || /[/\\\0]/.test(segment)) return null;
		segments.push(segment);
	}
	return segments;
}

function within(base: string, target: string): boolean {
	return target === base || target.startsWith(base + path.sep);
}

async function realpathOf(target: string): Promise<string | undefined> {
	try {
		return await realpath(target);
	} catch {
		return undefined;
	}
}

async function kindOf(target: string): Promise<'file' | 'directory' | 'other' | 'missing'> {
	try {
		const info = await stat(target);
		if (info.isFile()) return 'file';
		return info.isDirectory() ? 'directory' : 'other';
	} catch {
		return 'missing';
	}
}

async function file(base: string, target: string, status: number, head: boolean) {
	const bytes = await readFile(target);
	const type = CONTENT_TYPES.get(path.extname(target).toLowerCase()) ?? BYTES;
	const html = type.startsWith('text/html');
	const immutable =
		status === 200 && path.relative(base, target).split(path.sep)[0] === IMMUTABLE_DIR;
	const headers = new Headers({
		'content-type': type,
		'content-length': String(bytes.byteLength),
		'cache-control': immutable ? 'public, max-age=31536000, immutable' : 'no-cache'
	});
	headers.set(
		'content-security-policy',
		docsPolicy(html ? scriptHashes(bytes.toString('utf8')) : [])
	);
	setSecurityHeaders(headers);
	return new Response(head ? null : new Uint8Array(bytes), { status, headers });
}

function plain(status: number, text: string | null, extra: Record<string, string> = {}): Response {
	const headers = new Headers({
		'content-type': 'text/plain; charset=utf-8',
		'cache-control': 'no-cache',
		'content-security-policy': docsPolicy(),
		...extra
	});
	setSecurityHeaders(headers);
	return new Response(text, { status, headers });
}
