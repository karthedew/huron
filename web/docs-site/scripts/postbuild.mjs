// Checks the built site; the last step of `npm run build`.
//
// - Every link to /docs/… in dist/ must reach a built page, and its #fragment an id on that page.
// - No CLI reference page may hold a typographic dash before a letter (`–org`): option names must
//   stay pasteable, so astro.config.mjs turns smartypants off.
// - It reports how many distinct inline <script> and <style> elements the pages hold. The web
//   hashes the inline scripts of each page when it serves it (web/src/lib/server/docs.ts), so
//   nothing is written for it here.

import { readdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** The site's base path, as `base` in astro.config.mjs. */
export const BASE = '/docs';

/** Every HTML file under `dir`, as paths relative to it. */
export async function htmlFiles(dir) {
	const entries = await readdir(dir, { recursive: true, withFileTypes: true });
	return entries
		.filter((entry) => entry.isFile() && entry.name.endsWith('.html'))
		.map((entry) => path.relative(dir, path.join(entry.parentPath, entry.name)))
		.sort();
}

/** The `'sha256-…'` sources of the inline scripts and style elements of `pages` (HTML strings). */
export function inlineHashes(pages) {
	const scripts = new Set();
	const styles = new Set();
	for (const html of pages) {
		for (const match of html.matchAll(/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
			scripts.add(source(match[1]));
		}
		for (const match of html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) {
			styles.add(source(match[1]));
		}
	}
	return { 'script-src': [...scripts].sort(), 'style-src': [...styles].sort() };
}

/**
 * The links of `pages` (a map from path relative to dist/ to HTML) that name a page or an id the
 * site does not have, as `file: href` lines.
 */
export function brokenLinks(pages) {
	const ids = new Map();
	for (const [file, html] of pages) {
		ids.set(file, new Set([...html.matchAll(/\sid="([^"]*)"/g)].map((match) => match[1])));
	}
	const broken = [];
	for (const [file, html] of pages) {
		for (const [, href] of html.matchAll(/\shref="([^"]*)"/g)) {
			const target = resolve(file, href);
			if (target === null) continue;
			const [page, fragment] = target;
			const known = ids.get(page);
			if (!known || (fragment && !known.has(decodeURIComponent(fragment)))) {
				broken.push(`${file}: ${href}`);
			}
		}
	}
	return broken;
}

/**
 * The CLI reference pages of `pages` (a map from path relative to dist/ to HTML) where an en or em
 * dash stands before a letter, as `file: text` lines: an option name typography rewrote.
 */
export function rewrittenOptions(pages) {
	const found = [];
	for (const [file, html] of pages) {
		if (!file.startsWith('reference/cli/')) continue;
		for (const match of html.matchAll(/[\u2013\u2014][A-Za-z][\w-]*/g)) {
			found.push(`${file}: ${match[0]}`);
		}
	}
	return found;
}

function resolve(file, href) {
	const [pathname, fragment = ''] = href.split('#', 2);
	if (!pathname) return [file, fragment];
	if (!pathname.startsWith(`${BASE}/`) || path.extname(pathname)) return null;
	const relative = pathname.slice(BASE.length + 1);
	return [path.posix.join(relative, 'index.html'), fragment];
}

function source(text) {
	return `'sha256-${createHash('sha256').update(text, 'utf8').digest('base64')}'`;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist');
	const pages = new Map();
	for (const file of await htmlFiles(dist)) {
		pages.set(file.split(path.sep).join('/'), await readFile(path.join(dist, file), 'utf8'));
	}
	const broken = brokenLinks(pages);
	for (const line of broken) console.error(`broken link: ${line}`);
	const rewritten = rewrittenOptions(pages);
	for (const line of rewritten) console.error(`typographic dash in an option name: ${line}`);
	if (broken.length || rewritten.length) process.exit(1);
	const hashes = inlineHashes(pages.values());
	console.log(
		`postbuild: ${pages.size} pages, links resolve; ` +
			`${hashes['script-src'].length} distinct inline scripts, ` +
			`${hashes['style-src'].length} inline style elements`
	);
}
