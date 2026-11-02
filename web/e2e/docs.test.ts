import { expect, type Page } from '@playwright/test';
import { COOKIES, signIn, stack, test, webCookie } from './support/harness.ts';

/**
 * The web serves the documentation build at `/docs` to anyone (src/lib/server/docs.ts). These
 * tests run against `npm run docs:build`'s output, or against the unit tests' stand-in
 * (`HURON_E2E_DOCS_DIR=src/lib/testing/docs`), which has every page they read but no search index.
 */
const STAND_IN = /src[/\\]lib[/\\]testing[/\\]docs\/?$/.test(stack.docsDir);

/** The CSP violations the page reports in its console, collected from now on. */
function policyViolations(page: Page): string[] {
	const violations: string[] = [];
	page.on('console', (message) => {
		if (/content security policy/i.test(message.text())) violations.push(message.text());
	});
	return violations;
}

/** The sources of one directive of a policy. */
function directive(policy: string, name: string): string[] {
	const found = policy
		.split(';')
		.map((part) => part.trim().split(/\s+/))
		.find(([directiveName]) => directiveName === name);
	return found?.slice(1) ?? [];
}

test('the documentation opens from the sign-in page, signed out, and sets no cookie', async ({
	page,
	context
}) => {
	const violations = policyViolations(page);
	await page.goto('/login');
	await page.getByRole('link', { name: 'Docs', exact: true }).click();
	await expect(page).toHaveURL('/docs/');
	await expect(page).toHaveTitle(/Huron/);
	await expect(page.getByRole('heading', { level: 1, name: 'Huron' })).toBeVisible();
	expect(await context.cookies()).toEqual([]);
	expect(violations).toEqual([]);
});

test('every documentation page and asset answers signed out; an unknown one is a 404', async ({
	page,
	context
}) => {
	const bare = await page.goto('/docs');
	expect(bare?.status()).toBe(200);
	await expect(page).toHaveURL('/docs/');

	await page.goto('/docs/reference/cli/push');
	await expect(page).toHaveURL('/docs/reference/cli/push/');
	await expect(page.getByRole('heading', { level: 1, name: 'huron push' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Options' })).toBeVisible();
	await expect(page.getByRole('cell', { name: '--message, -m' })).toBeVisible();

	const missing = await page.goto('/docs/reference/cli/nowhere/');
	expect(missing?.status()).toBe(404);
	await expect(page).toHaveTitle(/404/);

	const traversal = await page.request.get('/docs/..%2F..%2Fpackage.json');
	expect(traversal.status()).toBe(404);
	expect(await traversal.text()).not.toContain('"name": "huron-web"');
	expect(await context.cookies()).toEqual([]);
});

test('the documentation search finds a CLI command and opens its reference page', async ({
	page
}) => {
	test.skip(STAND_IN, 'the stand-in build has no search index');
	const violations = policyViolations(page);
	await page.goto('/docs/');
	await page.getByRole('button', { name: 'Search' }).click();
	const dialog = page.getByRole('dialog', { name: 'Search' });
	await dialog.getByPlaceholder('Search').fill('checkout');
	const result = dialog.locator('a[href^="/docs/reference/cli/checkout/"]').first();
	await expect(result).toBeVisible();
	await result.click();
	await expect(page).toHaveURL(/\/docs\/reference\/cli\/checkout\/(#.*)?$/);
	await expect(page.getByRole('heading', { level: 1, name: 'huron checkout' })).toBeVisible();
	// The search compiles Pagefind's WebAssembly and the pages run their inline scripts.
	expect(violations).toEqual([]);
});

test('the documentation header links back to the web, also as an icon on narrow screens', async ({
	page
}) => {
	test.skip(STAND_IN, 'the stand-in build has no Starlight header');
	const violations = policyViolations(page);
	await page.goto('/docs/');
	const link = page.getByRole('banner').getByRole('link', { name: 'Catalog', exact: true });
	await expect(link).toBeVisible();
	await expect(link).toHaveAttribute('href', '/');
	await expect(link).toContainText('Catalog');

	// Signed out, the web's home goes through sign-in.
	await link.click();
	await expect(page.getByRole('heading', { name: 'Sign in to Huron' })).toBeVisible();

	// On a phone the link stays in the header, with its icon only and its name kept: on the splash
	// home page, which has no menu, and on a page with a sidebar.
	await page.setViewportSize({ width: 390, height: 800 });
	for (const path of ['/docs/', '/docs/getting-started/']) {
		await page.goto(path);
		const narrow = page.getByRole('banner').getByRole('link', { name: 'Catalog', exact: true });
		await expect(narrow).toBeVisible();
		await expect(narrow).toHaveAttribute('href', '/');
		await expect(narrow).toHaveText('');
		const box = await narrow.boundingBox();
		expect(box?.width).toBeGreaterThanOrEqual(24);
		expect(box?.height).toBeGreaterThanOrEqual(24);
	}
	expect(violations).toEqual([]);
});

test('the rest of the web stays behind sign-in', async ({ page }) => {
	for (const path of ['/catalogs', '/catalogs/heliophysics', '/docsx']) {
		await page.goto(path);
		await expect(page).toHaveURL(`/login?returnTo=${encodeURIComponent(path)}`);
		await expect(page.getByRole('heading', { name: 'Sign in to Huron' })).toBeVisible();
	}
});

test('the documentation has its own policy, which only adds to script-src', async ({ request }) => {
	const docs = await request.get('/docs/');
	const login = await request.get('/login');
	const docsPolicy = docs.headers()['content-security-policy'] ?? '';
	const appPolicy = login.headers()['content-security-policy'] ?? '';
	for (const answer of [docs, login]) {
		expect(answer.headers()).toMatchObject({
			'x-content-type-options': 'nosniff',
			'x-frame-options': 'DENY',
			'referrer-policy': 'same-origin'
		});
	}

	const docsScripts = directive(docsPolicy, 'script-src');
	expect(docsScripts.slice(0, 2)).toEqual(["'self'", "'wasm-unsafe-eval'"]);
	expect(docsScripts.length).toBeGreaterThan(2);
	for (const source of docsScripts.slice(2)) expect(source).toMatch(/^'sha256-[\w+/]+=*'$/);
	expect(docsScripts).not.toContain("'unsafe-inline'");

	const appScripts = directive(appPolicy, 'script-src');
	expect(appScripts[0]).toBe("'self'");
	expect(appScripts).not.toContain("'wasm-unsafe-eval'");
	expect(appScripts.some((source) => source.startsWith("'sha256-"))).toBe(false);
	for (const name of ['default-src', 'object-src', 'base-uri', 'frame-ancestors', 'style-src']) {
		expect(directive(docsPolicy, name), name).toEqual(directive(appPolicy, name));
	}
});

test('a signed-in user reaches the documentation from the sidebar and a CLI hint, and stays signed in', async ({
	page,
	context
}) => {
	await signIn(page, 'erin');
	const session = await webCookie(context, COOKIES.session);
	if (session === undefined) throw new Error('the sign-in set no session cookie');

	await page.goto('/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/cli');
	await page
		.getByRole('region', { name: 'Select this collection' })
		.getByRole('link', { name: 'huron checkout' })
		.click();
	await expect(page).toHaveURL('/docs/reference/cli/checkout/');
	await expect(page.getByRole('heading', { level: 1, name: 'huron checkout' })).toBeVisible();

	await page.goto('/');
	await page
		.getByRole('complementary', { name: 'Sidebar' })
		.getByRole('link', { name: 'Docs' })
		.click();
	await expect(page).toHaveURL('/docs/');

	// Still signed in: the shell answers, not the sign-in page.
	await page.goto('/account');
	await expect(page).toHaveURL('/account');
	expect((await webCookie(context, COOKIES.session))?.value).toBe(session.value);
});
