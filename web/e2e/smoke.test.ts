import { createHmac } from 'node:crypto';
import { expect, test } from '@playwright/test';

const PREVIEW_SESSION_SECRET = 'e2e-preview-session-secret';

function previewCookieValue(nonce: string): string {
	const signature = createHmac('sha256', PREVIEW_SESSION_SECRET).update(nonce).digest('base64url');
	return `${nonce}.${signature}`;
}

/**
 * The UI gate named in design/roadmap.html: "E2E smoke against the compose stack".
 * Until the API exists this smoke runs against fixtures — it proves the shell renders
 * and routes resolve, not that any data is real.
 */

test.beforeEach(async ({ context }) => {
	await context.addCookies([
		{
			name: 'huron_preview_session',
			value: previewCookieValue('e2e-preview-session'),
			url: 'http://localhost:4173'
		}
	]);
});

test('unauthenticated visitors sign in and return to their requested page', async ({
	page,
	context
}) => {
	await context.clearCookies();
	await page.goto('/ingestion');
	await expect(page).toHaveURL(/\/login\?returnTo=%2Fingestion$/);
	await expect(page.getByRole('heading', { name: 'Sign in to Huron' })).toBeVisible();
	await expect(page.getByRole('complementary', { name: 'Application sidebar' })).toHaveCount(0);

	await page.getByLabel('Email address').fill('karl.schmidt@example.org');
	await page.getByLabel('Password', { exact: true }).fill('preview-password');
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();

	await expect(page).toHaveURL('/ingestion');
	await expect(page.getByRole('heading', { name: 'Ingest a dataset' })).toBeVisible();
});

test('signup creates a preview session and preserves the requested destination', async ({
	page,
	context
}) => {
	await context.clearCookies();
	await page.goto('/signup?returnTo=/browse');
	await page.getByLabel('Display name').fill('Ada Lovelace');
	await page.getByLabel('Email address').fill('ada@example.org');
	await page.getByLabel('Password', { exact: true }).fill('preview-password');
	await page.getByLabel('Confirm password').fill('preview-password');
	await page.getByLabel(/I agree to/).check();
	await page.getByRole('button', { name: 'Create account', exact: true }).click();

	await expect(page).toHaveURL('/browse');
	await expect(page.getByRole('heading', { name: 'Browse the lakehouse' })).toBeVisible();
});

test('unsigned preview cookies do not authenticate a visitor', async ({ page, context }) => {
	await context.clearCookies();
	await context.addCookies([
		{
			name: 'huron_preview_session',
			value: 'forged-preview-session',
			url: 'http://localhost:4173'
		}
	]);
	await page.goto('/browse');
	await expect(page).toHaveURL(/\/login\?returnTo=%2Fbrowse$/);
});

test('search page renders', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Search', level: 1 })).toBeVisible();
});

test('browse walks down to a revision manifest', async ({ page }) => {
	await page.goto('/browse');
	await page.getByRole('button', { name: /Example Study/ }).click();
	await page.getByRole('link', { name: /Example Sweep/ }).click();
	await page.getByRole('link', { name: 'run-0001' }).click();
	await page.getByRole('link', { name: 'Manifest →' }).first().click();
	await expect(page.getByRole('heading', { name: /Revision/ })).toBeVisible();
});

test('an undiscoverable resource renders as not found, with no hint that it exists', async ({
	page
}) => {
	const response = await page.goto('/no-such-org');
	expect(response?.status()).toBe(404);
	await expect(page.getByRole('heading', { name: 'Not found' })).toBeVisible();
	await expect(page.getByText(/forbidden|permission|access/i)).toHaveCount(0);
});

test('deep links are shareable and render directly', async ({ page }) => {
	await page.goto('/example-org/example-study/example-sweep/run-0001');
	await expect(page.getByRole('heading', { name: 'run-0001' })).toBeVisible();
});

test('organization switching updates the active catalog scope', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('banner').getByLabel('Switch organization').click();
	await page.getByRole('button', { name: /Second Organization/ }).click();
	await expect(page.getByText('No visible assets')).toBeVisible();
});

test('browse stays within the toolbar organization and closes its switcher outside', async ({
	page
}) => {
	await page.setViewportSize({ width: 1087, height: 735 });
	await page.goto('/browse');
	const switcher = page.getByRole('banner').getByLabel('Switch organization');
	const secondOrganization = page.getByRole('button', { name: /Second Organization/ });

	await expect(page.getByRole('heading', { name: 'Organizations' })).toHaveCount(0);
	await expect(
		page
			.getByRole('complementary', { name: 'Application sidebar' })
			.getByLabel('Switch organization')
	).toHaveCount(0);
	await switcher.click();
	await expect(secondOrganization).toBeVisible();
	await page.getByRole('heading', { name: 'Browse the lakehouse' }).click();
	await expect(secondOrganization).toBeHidden();

	await switcher.click();
	await secondOrganization.click();
	await expect(
		page.getByText('Explore projects and datasets within Second Organization.')
	).toBeVisible();
	await expect(page.getByText('No visible projects in this organization.')).toBeVisible();
});

test('browse filters enumerated dataset metadata', async ({ page }) => {
	await page.goto('/browse');
	await page.getByRole('combobox', { name: 'Filter by lifecycle' }).selectOption('ACTIVE');
	await expect(page.getByRole('link', { name: /Draft Dataset/ })).toBeVisible();
	await expect(page.getByRole('link', { name: /Example Sweep/ })).toBeVisible();

	await page.getByRole('combobox', { name: 'Filter by lifecycle' }).selectOption('all');
	await page.getByRole('combobox', { name: 'Filter by materialized layer' }).selectOption('gold');
	await expect(page.getByRole('link', { name: /Example Sweep/ })).toBeVisible();
	await expect(page.getByRole('link', { name: /Draft Dataset/ })).toBeHidden();

	await page.getByRole('button', { name: /Clear/ }).click();
	await page.getByRole('button', { name: /Empty Study/ }).click();
	await expect(page.getByText('No datasets found')).toBeVisible();
});

test('browse names the selected project and bounds large result sets', async ({ page }) => {
	await page.setViewportSize({ width: 1087, height: 735 });
	await page.goto('/browse');

	const explorerHeading = page.getByRole('heading', { name: 'Project explorer' });
	await expect(explorerHeading).toHaveCSS('font-size', '12px');
	await expect(explorerHeading).toHaveCSS('margin-top', '0px');
	await expect(page.getByRole('heading', { name: 'Datasets in Example Study' })).toBeVisible();
	await expect(page.getByTestId('catalog-explorer')).toHaveCSS('height', '527px');
	await expect(page.getByTestId('dataset-results')).toHaveCSS('overflow-y', 'auto');
	await expect(page.getByLabel('Dataset pagination')).toContainText('Showing 1–2 of 2');
	await expect(page.getByLabel('Datasets per page')).toHaveValue('25');

	await page.getByRole('button', { name: /Empty Study/ }).click();
	await expect(page.getByRole('heading', { name: 'Datasets in Empty Study' })).toBeVisible();
});

test('sidebar becomes an icon rail and can be collapsed on desktop', async ({ page }) => {
	await page.setViewportSize({ width: 816, height: 735 });
	await page.goto('/');
	const sidebar = page.getByRole('complementary', { name: 'Application sidebar' });
	await expect(sidebar).toHaveCSS('width', '68px');
	await expect(page.getByLabel('Toggle navigation')).toBeHidden();
	await expect(sidebar.getByRole('link', { name: 'Catalog', exact: true })).toBeVisible();

	await page.setViewportSize({ width: 1440, height: 900 });
	await expect(sidebar).toHaveCSS('width', '248px');
	await page.getByRole('button', { name: 'Collapse sidebar' }).click();
	await expect(sidebar).toHaveCSS('width', '68px');
	await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
});

test('the compact rail expands as an overlay without moving the workspace', async ({ page }) => {
	await page.setViewportSize({ width: 816, height: 735 });
	await page.goto('/browse');
	await page.getByRole('button', { name: 'Expand navigation' }).click();
	const overlay = page.getByRole('dialog', { name: 'Expanded navigation' });
	await expect(overlay).toBeVisible();
	await expect(overlay.getByRole('link', { name: 'Ingestion' })).toBeVisible();
	await overlay.getByRole('button', { name: 'Close expanded navigation' }).click();
	await expect(overlay).toBeHidden();
});

test('browse and ingestion hydrate at the compact viewport', async ({ page }) => {
	await page.setViewportSize({ width: 816, height: 735 });
	for (const [route, heading] of [
		['/browse', 'Browse the lakehouse'],
		['/ingestion', 'Ingest a dataset']
	] as const) {
		await page.goto(route);
		await expect(page.getByRole('heading', { name: heading })).toBeVisible();
		await expect(page.getByText('Something went wrong')).toHaveCount(0);
	}
});

test('account menu opens user settings and supports logout', async ({ page }) => {
	await page.goto('/browse');
	await page.getByLabel('Open account menu').click();
	await page.getByRole('link', { name: 'User settings' }).click();
	await expect(page.getByRole('heading', { name: 'User settings' })).toBeVisible();

	await page.getByLabel('Open account menu').click();
	await page.getByRole('button', { name: 'Log out', exact: true }).click();
	const logout = page.getByRole('dialog', { name: 'Log out of Huron?' });
	await logout.getByRole('button', { name: 'Log out', exact: true }).click();
	await expect(page).toHaveURL('/login?status=signed-out');
	await expect(page.getByRole('heading', { name: 'Sign in to Huron' })).toBeVisible();
	await expect(page.getByText('You’ve been signed out successfully.')).toBeVisible();

	await page.goto('/browse');
	await expect(page).toHaveURL(/\/login\?returnTo=%2Fbrowse$/);
});

test('ingestion branches from raw uploads to bronze materialization', async ({ page }) => {
	await page.goto('/ingestion');
	await expect(page.getByRole('heading', { name: 'Ingest a dataset' })).toBeVisible();
	await expect(page.getByText('Example Organization', { exact: true }).first()).toBeVisible();
	await page.getByText('Bronze', { exact: true }).click();
	await page.getByRole('button', { name: /Continue/ }).click();
	await expect(page.getByRole('heading', { name: 'Select the raw source' })).toBeVisible();
});

test('raw ingestion validates its source and appears in activity', async ({ page }) => {
	await page.goto('/ingestion');
	await page.getByRole('button', { name: /Continue/ }).click();

	const continueButton = page.getByRole('button', { name: /Continue/ });
	await expect(continueButton).toBeDisabled();
	await expect(
		page.getByText('Add at least one source file or use the sample manifest.')
	).toBeVisible();
	await page.getByRole('button', { name: 'Use sample manifest' }).click();
	await expect(continueButton).toBeEnabled();
	await continueButton.click();

	await expect(page.getByRole('heading', { name: 'Describe this revision' })).toBeVisible();
	await continueButton.click();
	await expect(page.getByRole('heading', { name: 'Review and begin ingest' })).toBeVisible();
	await expect(page.getByText('Example Study / Example Sweep')).toBeVisible();
	await page.getByRole('button', { name: 'Begin ingest' }).click();
	await expect(page.getByText(/Ingest queued · ING-/)).toBeVisible();

	await page.getByRole('link', { name: 'Open ingest activity →' }).click();
	await expect(page.getByRole('heading', { name: 'Jobs & queue' })).toBeVisible();
	await expect(page.getByText(/^ING-\d{8}$/).first()).toBeVisible();
	await expect(page.getByLabel('Status: Queued').first()).toBeVisible();
});

test('organization users combine activity and role management', async ({ page }) => {
	await page.setViewportSize({ width: 1007, height: 735 });
	await page.goto('/settings/organization');
	await expect(page.getByRole('button', { name: 'Users', exact: true })).toBeVisible();
	await expect(page.getByText('Last active', { exact: true })).toBeVisible();
	await expect(page.getByLabel('Role for Karl Schmidt')).toHaveValue('organization_admin');
	await expect(page.getByText('Bronze Pipeline')).toHaveCount(0);
	await page.getByLabel('Role for Maya Chen').selectOption('developer');
	await expect(page.getByLabel('Role for Maya Chen')).toHaveValue('developer');

	await page.getByRole('button', { name: 'Add user' }).click();
	const dialog = page.getByRole('dialog');
	await dialog.getByPlaceholder('Maya Chen').fill('New User');
	await dialog.getByPlaceholder('maya@example.org').fill('new.user@example.org');
	await dialog.getByLabel('Organization role').selectOption('developer');
	await dialog.getByRole('button', { name: 'Add user' }).click();
	await expect(page.getByText('user:new.user@example.org')).toBeVisible();
	await expect(page.getByLabel('Role for New User')).toHaveValue('developer');
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
		true
	);
});

test('service accounts are managed separately from users', async ({ page }) => {
	await page.setViewportSize({ width: 1007, height: 735 });
	await page.goto('/settings/organization');
	await page.getByRole('button', { name: 'Service Accounts', exact: true }).click();
	await expect(page.getByText('Bronze Pipeline')).toBeVisible();
	await expect(page.getByText('Silver + gold · intrinsic')).toBeVisible();
	await expect(page.getByText('Karl Schmidt', { exact: true })).toBeHidden();

	await page.getByRole('button', { name: 'Create service account' }).click();
	const dialog = page.getByRole('dialog');
	await dialog.getByPlaceholder('Silver refresh pipeline').fill('Silver refresh pipeline');
	await dialog.getByRole('button', { name: 'Create service account' }).click();
	await expect(page.getByText('sa:silver-refresh-pipeline')).toBeVisible();
	await expect(page.getByText('Silver + gold · intrinsic')).toHaveCount(2);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
		true
	);
});
