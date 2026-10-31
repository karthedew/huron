import { createServer } from 'node:http';
import { expect } from '@playwright/test';
import { COOKIES, signIn, stack, test, webCookie } from './support/harness.ts';

/** Three base64url parts whose first two decode to JSON objects: a JWT. */
const JWT_SHAPED = /eyJ[\w-]{5,}\.eyJ[\w-]{5,}\.[\w-]{10,}/;
/** Enough to reach every kind of page, few enough to stay quick as the fixture grows. */
const MAX_PAGES = 40;

test('a cross-site POST /logout is refused and the session survives', async ({ page, context }) => {
	await signIn(page, 'dave');
	const session = await webCookie(context, COOKIES.session);
	if (session === undefined) throw new Error('the sign-in set no session cookie');

	await page.route('http://evil.example/**', (route) =>
		route.fulfill({
			contentType: 'text/html',
			body: `<!doctype html><title>Elsewhere</title>
				<form method="post" action="${stack.webOrigin}/logout"><button>Log out of Huron</button></form>`
		})
	);
	await page.goto('http://evil.example/');
	const [refused] = await Promise.all([
		page.waitForResponse(`${stack.webOrigin}/logout`),
		page.getByRole('button', { name: 'Log out of Huron' }).click()
	]);
	expect(refused.status()).toBe(403);

	// The browser keeps the Lax session cookie home; with it attached the origin check refuses
	// too, also for bodies SvelteKit's own check ignores because they are not forms.
	const forgeries = {
		form: { headers: { origin: 'http://evil.example' }, form: { from: 'elsewhere' } },
		'no body': { headers: { origin: 'http://evil.example' } },
		JSON: { headers: { origin: 'null', 'content-type': 'application/json' }, data: '{}' }
	};
	for (const [kind, forgery] of Object.entries(forgeries)) {
		const forged = await page.request.post('/logout', { ...forgery, maxRedirects: 0 });
		expect(forged.status(), `a forged POST with ${kind}`).toBe(403);
	}

	await page.goto('/');
	await expect(page).toHaveURL('/');
	await expect(page.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();
	expect((await webCookie(context, COOKIES.session))?.value).toBe(session.value);
});

test('a page on another port of the same site cannot end the session', async ({
	page,
	context
}) => {
	await signIn(page, 'dave');
	const session = await webCookie(context, COOKIES.session);
	if (session === undefined) throw new Error('the sign-in set no session cookie');
	const logoutAnswers: number[] = [];
	page.on('response', (response) => {
		if (response.url() === `${stack.webOrigin}/logout`) logoutAnswers.push(response.status());
	});

	const elsewhere = await serveSameSitePage('<!doctype html><title>Elsewhere</title>');
	try {
		await page.goto(elsewhere.url);
		// Bodiless requests a page may send anywhere; same site, so they carry the Lax cookie.
		await page.evaluate(async (logout) => {
			await fetch(logout, { method: 'POST', mode: 'no-cors', credentials: 'include' });
			if (!navigator.sendBeacon(logout)) throw new Error('the beacon was not queued');
		}, `${stack.webOrigin}/logout`);
		await expect.poll(() => logoutAnswers).toEqual([403, 403]);
	} finally {
		await elsewhere.close();
	}

	await page.goto('/');
	await expect(page).toHaveURL('/');
	await expect(page.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();
	expect((await webCookie(context, COOKIES.session))?.value).toBe(session.value);
});

test('pages carry the security headers and the content security policy', async ({ page }) => {
	const login = await page.goto('/login');
	expect(login?.headers()).toMatchObject({
		'x-content-type-options': 'nosniff',
		'x-frame-options': 'DENY',
		'referrer-policy': 'same-origin'
	});
	await signIn(page, 'dave');
	const home = await page.goto('/');
	const headers = home?.headers() ?? {};
	expect(headers).toMatchObject({
		'x-content-type-options': 'nosniff',
		'x-frame-options': 'DENY',
		'referrer-policy': 'same-origin',
		'cache-control': 'private, no-store'
	});
	const policy = headers['content-security-policy'] ?? '';
	for (const directive of [
		"default-src 'self'",
		"object-src 'none'",
		"base-uri 'self'",
		"frame-ancestors 'none'"
	]) {
		expect(policy).toContain(directive);
	}
	expect(policy).toMatch(/script-src 'self' 'nonce-[^']+'/);
});

test('no token and no session id reach any page or data answer', async ({ page, context }) => {
	const violations: string[] = [];
	page.on('console', (message) => {
		if (/content security policy/i.test(message.text())) violations.push(message.text());
	});
	const bodies: Array<Promise<{ url: string; text: string }>> = [];
	page.on('response', (response) => {
		const kind = response.request().resourceType();
		const redirected = response.status() >= 300 && response.status() < 400;
		if (new URL(response.url()).origin !== stack.webOrigin || redirected) return;
		if (kind !== 'document' && kind !== 'fetch' && kind !== 'xhr') return;
		bodies.push(response.text().then((text) => ({ url: response.url(), text })));
	});
	await signIn(page, 'alice');
	const session = await webCookie(context, COOKIES.session);
	if (session === undefined) throw new Error('the sign-in set no session cookie');

	const queue = ['/'];
	const visited = new Set<string>();
	for (let path = queue.shift(); path !== undefined; path = queue.shift()) {
		if (visited.has(path)) continue;
		if (visited.size === MAX_PAGES) break;
		visited.add(path);
		await page.goto(path);
		const data = await page.request.get(dataPath(path));
		bodies.push(data.text().then((text) => ({ url: data.url(), text })));
		const links = await page
			.locator('a[href]')
			.evaluateAll((anchors) =>
				anchors.map((anchor) => (anchor instanceof HTMLAnchorElement ? anchor.href : ''))
			);
		for (const link of links) {
			const next = crawlable(link);
			if (next !== null && !visited.has(next)) queue.push(next);
		}
	}

	expect(visited.size).toBeGreaterThan(1);
	for (const { url, text } of await Promise.all(bodies)) {
		expect(text, `${url} holds a JWT`).not.toMatch(JWT_SHAPED);
		expect(text.includes(session.value), `${url} holds the session id`).toBe(false);
	}
	expect(await page.evaluate(() => document.cookie)).not.toContain(COOKIES.session);
	expect(violations).toEqual([]);
});

/** The data request SvelteKit's client makes for a page. */
function dataPath(path: string): string {
	const url = new URL(path, stack.webOrigin);
	const base = url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '');
	return `${base}/__data.json${url.search}`;
}

/** A link's path when the crawl may follow it: same origin, not signing in or out. */
function crawlable(href: string): string | null {
	if (href === '') return null;
	const url = new URL(href);
	if (url.origin !== stack.webOrigin) return null;
	const { pathname } = url;
	if (pathname === '/login' || pathname === '/logout' || pathname.startsWith('/auth/')) return null;
	return pathname + url.search;
}

/**
 * Serve a page at `http://localhost:<free port>/`: another origin than the web, but the same
 * site, as another app on the web's domain would be. It must be a real server: Chromium blocks
 * requests from a routed public origin to `localhost` before they leave the browser.
 */
async function serveSameSitePage(
	html: string
): Promise<{ url: string; close: () => Promise<void> }> {
	const server = createServer((_request, response) => {
		response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
		response.end(html);
	});
	await new Promise<void>((resolve, reject) => {
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => resolve());
	});
	const address = server.address();
	if (address === null || typeof address === 'string') throw new Error('the page has no port');
	return {
		url: `http://localhost:${address.port}/`,
		close: () =>
			new Promise<void>((resolve) => {
				server.close(() => resolve());
				server.closeAllConnections();
			})
	};
}
