import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { createUser, openPage, signIn, USER_PASSWORD } from './helpers';

// These browser tests use an isolated account store and a stateful Polaris protocol peer.
test('unauthenticated visitors sign in with the bootstrap Huron account and return to their page', async ({
	page
}) => {
	await openPage(page, '/browse');
	await expect(page).toHaveURL(/\/login\?returnTo=%2Fbrowse$/);
	await expect(page.getByRole('heading', { name: 'Sign in to Huron' })).toBeVisible();
	await expect(page.getByRole('complementary', { name: 'Application sidebar' })).toHaveCount(0);
	await page.getByLabel('Username', { exact: true }).fill('admin');
	await page.getByLabel('Password', { exact: true }).fill('browser-admin-password');
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();
	await expect(page).toHaveURL('/browse');
	await expect(page.getByRole('heading', { name: 'Explorer', exact: true })).toBeVisible();
});

test('users without organization membership can navigate Browse and their account settings', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page);
	await signIn(page, username, USER_PASSWORD);
	const sidebar = page.getByRole('complementary', { name: 'Application sidebar' });
	await sidebar.getByRole('link', { name: 'Browse', exact: true }).click();
	await expect(page).toHaveURL('/browse');
	await expect(page.getByText('No catalogs available', { exact: true })).toBeVisible();
	await page.getByLabel('Open account menu').click();
	await page.getByRole('link', { name: 'User settings', exact: true }).click();
	await expect(page).toHaveURL('/account');
	await expect(page.getByRole('heading', { name: 'Account', exact: true })).toBeVisible();
	await expect(page.getByLabel('Current password', { exact: true })).toBeVisible();
	await sidebar.getByRole('link', { name: 'Catalogs', exact: true }).click();
	await page.getByLabel('Search query', { exact: true }).fill('science');
	await page.locator('main').getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page.getByText('No matching catalogs', { exact: true })).toBeVisible();
	expect(new URL(page.url()).searchParams.has('organization')).toBe(false);
});

test('invalid credentials and forged legacy or opaque cookies do not authenticate', async ({
	page,
	context
}) => {
	await context.addCookies([
		{ name: 'huron_preview_session', value: 'forged', url: 'http://localhost:4173' },
		{ name: 'huron_session', value: 'forged', url: 'http://localhost:4173' }
	]);
	await openPage(page, '/browse');
	await expect(page).toHaveURL(/\/login\?returnTo=%2Fbrowse$/);
	await page.getByLabel('Username', { exact: true }).fill('admin');
	await page.getByLabel('Password', { exact: true }).fill('wrong-password');
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('incorrect');
	await expect(page.locator('body')).not.toContainText('wrong-password');
});

test('public signup is disabled when users are provisioned by the administrator', async ({
	page
}) => {
	await openPage(page, '/signup');
	await expect(page.getByText(/administrator.*create.*account/i)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveCount(0);
	const response = await page.request.post('/signup', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: {
			username: 'uninvited',
			displayName: 'Uninvited',
			password: USER_PASSWORD,
			confirmation: USER_PASSWORD
		}
	});
	expect(response.status()).toBe(403);
});

test('catalog search shows only live Polaris metadata and organizations', async ({ page }) => {
	await signIn(page);
	await expect(page.getByRole('heading', { name: 'Huron workspace', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'huron-local', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'ocean-data', exact: true })).toBeVisible();
	await page.getByLabel('Search query').fill('Earth observations');
	await page.locator('main').getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'huron-local', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'ocean-data', exact: true })).toHaveCount(0);
	await expect(page.locator('main')).not.toContainText('Example Organization');
});

test('the toolbar switches organization roots and keeps catalog choices in Browse', async ({
	page
}) => {
	await page.setViewportSize({ width: 1087, height: 735 });
	await signIn(page, 'admin', 'browser-admin-password', '/browse');
	const slug = `toolbar-${randomUUID().slice(0, 8)}`;
	const name = `Toolbar research ${slug}`;
	const created = await page.request.post('/admin?/createOrganization', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: { slug, name, description: '', realm: 'E2E_TOOLBAR' }
	});
	expect(created.status()).toBe(200);
	expect(await created.text()).toContain(`Organization ${name} created.`);
	await openPage(page, '/browse?catalog=huron-local');
	const banner = page.getByRole('banner');
	await expect(banner.getByLabel('Switch catalog')).toHaveCount(0);
	const switcher = banner.getByLabel('Switch organization');
	await switcher.click();
	const choice = banner.getByRole('link', { name: new RegExp(name) });
	await expect(choice).toBeVisible();
	await expect(banner.getByRole('link', { name: /ocean-data/ })).toHaveCount(0);
	await page.getByRole('heading', { name: 'Explorer', exact: true }).click();
	await expect(choice).toBeHidden();
	await switcher.press('Enter');
	await page.keyboard.press('Escape');
	await expect(choice).toBeHidden();
	await expect(switcher).toBeFocused();
	await switcher.press('Enter');
	await choice.click();
	await expect(page).toHaveURL(`/browse?organization=${slug}`);
	await expect(switcher).toHaveAttribute('title', name);
	await expect(page.getByText('No catalogs available', { exact: true })).toBeVisible();
	await expect(page.locator('main')).not.toContainText('huron-local');
	await expect(page.locator('main')).not.toContainText('ocean-data');
});

test('obsolete scientific fixture routes redirect into live browse', async ({ page }) => {
	await signIn(page);
	for (const route of [
		'/example-org/example-study/example-sweep/run-0001',
		'/queue',
		'/polaris',
		'/settings/project'
	]) {
		await openPage(page, route);
		await expect(page).toHaveURL(/\/browse(?:\?|$)/);
		await expect(page.getByRole('heading', { name: 'Explorer', exact: true })).toBeVisible();
	}
});

test('sidebar becomes an icon rail and expands or collapses without losing the workspace', async ({
	page
}) => {
	const runtimeErrors: string[] = [];
	page.on('pageerror', (error) => runtimeErrors.push(error.stack ?? error.message));
	await page.setViewportSize({ width: 816, height: 735 });
	await signIn(page);
	expect(runtimeErrors).toEqual([]);
	const sidebar = page.getByRole('complementary', { name: 'Application sidebar' });
	await expect(sidebar).toHaveCSS('width', '68px');
	await expect(page.getByLabel('Toggle navigation')).toBeHidden();
	await page.getByRole('button', { name: 'Expand navigation' }).click();
	const overlay = page.getByRole('dialog', { name: 'Expanded navigation' });
	await expect(overlay).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(overlay).toBeHidden();
	await page.setViewportSize({ width: 1440, height: 900 });
	await expect(sidebar).toHaveCSS('width', '248px');
	await page.getByRole('button', { name: 'Collapse sidebar' }).click();
	await expect(sidebar).toHaveCSS('width', '68px');
	await page.getByRole('button', { name: 'Expand sidebar' }).click();
	await expect(sidebar).toHaveCSS('width', '248px');
});

test('account menu supports a real logout and reauthentication gate', async ({ page }) => {
	await signIn(page, 'admin', 'browser-admin-password', '/browse');
	await page.getByLabel('Open account menu').click();
	await page.getByRole('link', { name: 'User settings' }).click();
	await expect(page.getByRole('heading', { name: 'Account', exact: true })).toBeVisible();
	await page.getByLabel('Open account menu').click();
	await page.getByRole('button', { name: 'Log out', exact: true }).click();
	await page
		.getByRole('dialog', { name: 'Log out of Huron?' })
		.getByRole('button', { name: 'Log out', exact: true })
		.click();
	await expect(page).toHaveURL('/login?status=signed-out');
	await expect(page.getByText('You’ve been signed out successfully.')).toBeVisible();
	await openPage(page, '/browse');
	await expect(page).toHaveURL(/\/login\?returnTo=%2Fbrowse$/);
});

test('users change their own password and all old sessions are invalidated', async ({
	page,
	browser
}) => {
	await signIn(page);
	const username = await createUser(page);
	const other = await browser.newContext({ baseURL: 'http://localhost:4173' });
	const otherPage = await other.newPage();
	await signIn(page, username, USER_PASSWORD, '/account');
	await signIn(otherPage, username, USER_PASSWORD, '/browse');
	await page.getByLabel('Current password').fill('incorrect-password');
	await page.getByLabel('New password', { exact: true }).fill('changed-user-password');
	await page.getByRole('button', { name: 'Change password', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('current password is incorrect');
	await page.getByLabel('Current password').fill(USER_PASSWORD);
	await page.getByLabel('New password', { exact: true }).fill('changed-user-password');
	await page.getByRole('button', { name: 'Change password', exact: true }).click();
	await expect(page).toHaveURL('/login?status=password-changed');
	await openPage(otherPage, '/browse');
	await expect(otherPage).toHaveURL(/\/login\?returnTo=%2Fbrowse$/);
	await signIn(page, username, 'changed-user-password', '/browse');
	await expect(page.getByText('No catalogs available', { exact: true })).toBeVisible();
	await other.close();
});

for (const width of [390, 816, 1440]) {
	test(`catalog and browse remain usable at ${width}px in light and dark modes`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		const errors: string[] = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await signIn(page);
		for (const dark of [false, true]) {
			await page.evaluate(
				(enabled) => localStorage.setItem('huron-theme', enabled ? 'dark' : 'light'),
				dark
			);
			for (const route of [
				'/',
				'/browse?catalog=huron-local&namespace=%5B%22science%22%5D&table=temperature'
			]) {
				await openPage(page, route);
				expect(
					await page.locator('html').evaluate((element) => element.classList.contains('dark'))
				).toBe(dark);
				await expect(page.locator('main h1')).toBeVisible();
				if (route.startsWith('/browse'))
					expect(
						await page
							.locator('main h1')
							.evaluate((element) => element.getBoundingClientRect().height)
					).toBeLessThanOrEqual(40);
				if (route.startsWith('/browse')) {
					await page
						.getByRole('navigation', { name: 'Dataset details' })
						.getByRole('link', { name: 'Schema', exact: true })
						.click();
					const schema = page.getByRole('region', { name: 'Array schema', exact: true });
					if (await schema.evaluate((element) => element.scrollWidth > element.clientWidth)) {
						await schema.getByText('temperature', { exact: true }).press('ArrowRight');
						await expect
							.poll(() => schema.evaluate((element) => element.scrollLeft))
							.toBeGreaterThan(0);
					}
				}
				expect(
					await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
				).toBe(true);
				await expect(page.getByText('Something went wrong')).toHaveCount(0);
			}
		}
		expect(errors).toEqual([]);
	});
}
