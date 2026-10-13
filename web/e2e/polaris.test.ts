import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import {
	createUser,
	openPage,
	repositoryUrl,
	setMembership,
	signIn,
	USER_PASSWORD
} from './helpers';

function formWithButton(page: import('@playwright/test').Page, name: string) {
	return page.locator('form').filter({ has: page.getByRole('button', { name, exact: true }) });
}

test('administrator creates a Polaris catalog in an organization and sees it after reload', async ({
	page
}) => {
	await signIn(page, 'admin', 'browser-admin-password', '/admin');
	const name = `browser-catalog-${randomUUID().slice(0, 8)}`;
	const form = formWithButton(page, 'Create catalog');
	await form.getByLabel('Catalog name', { exact: true }).fill(name);
	await form
		.getByLabel('Default repository base URI')
		.fill(`file:///tmp/huron-browser-test/${name}/`);
	await form
		.getByLabel('Storage configuration · JSON')
		.fill(
			JSON.stringify({ storageType: 'FILE', allowedLocations: ['file:///tmp/huron-browser-test/'] })
		);
	await form.getByRole('button', { name: 'Create catalog', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `Catalog ${name} is ready in Polaris` })
	).toBeVisible();
	await openPage(page, '/');
	await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
	await page.getByRole('heading', { name, exact: true }).getByRole('link').click();
	await expect(page).toHaveURL(`/browse?catalog=${name}`);
	await expect(page.getByRole('navigation', { name: 'Namespace path' })).toContainText(name);
});

test('manual users start without implicit catalogs and membership uses live Polaris grants', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page);
	await signIn(page, username, USER_PASSWORD, '/browse');
	await expect(page.getByText('No catalogs available', { exact: true })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0);
	await signIn(page);
	await setMembership(page, 'huron-local', username, 'reader');
	await signIn(page, username, USER_PASSWORD);
	await expect(page.getByRole('heading', { name: 'huron-local', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'ocean-data', exact: true })).toHaveCount(0);
	await openPage(page, `${repositoryUrl}&table=temperature`);
	await expect(page.getByRole('heading', { name: 'temperature', exact: true })).toBeVisible();
});

test('catalog membership is independent across catalogs and direct inaccessible URLs remain 404', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'reader');
	await signIn(page, username, USER_PASSWORD);
	const missing = await openPage(
		page,
		'/browse?catalog=ocean-data&namespace=%5B%22science%22%5D&table=temperature'
	);
	expect(missing?.status()).toBe(404);
	await expect(page.getByRole('heading', { name: 'Not found', exact: true })).toBeVisible();
	await expect(page.locator('main')).not.toContainText(/PRIVATE|permission|forbidden/);
	await signIn(page);
	await setMembership(page, 'ocean-data', username, 'writer');
	await signIn(page, username, USER_PASSWORD);
	await expect(page.getByRole('heading', { name: 'huron-local', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'ocean-data', exact: true })).toBeVisible();
	await openPage(
		page,
		'/browse?catalog=ocean-data&namespace=%5B%22science%22%5D&table=temperature'
	);
	await expect(page.getByRole('heading', { name: 'temperature', exact: true })).toBeVisible();
	await signIn(page);
	await setMembership(page, 'ocean-data', username, 'none');
	await signIn(page, username, USER_PASSWORD);
	await expect(page.getByRole('heading', { name: 'ocean-data', exact: true })).toHaveCount(0);
});

test('Reader cannot mutate repositories or access realm administration', async ({ page }) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'reader');
	await signIn(page, username, USER_PASSWORD, `${repositoryUrl}&table=temperature`);
	await expect(page.getByText('Create a catalog', { exact: true })).toHaveCount(0);
	await expect(page.getByText('Principals', { exact: true })).toHaveCount(0);
	await page.getByText('Repository operations', { exact: true }).click();
	await page.getByText('Storage access', { exact: true }).click();
	await page.getByLabel('Requested access').selectOption('read-write');
	await page.getByRole('button', { name: 'Check storage access', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('does not have permission');
	const denied = await page.request.post('/browse?/createTable', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: {
			catalog: 'huron-local',
			namespace: '["science"]',
			name: 'reader-forbidden',
			location: 'file:///tmp/reader-forbidden',
			properties: '{}'
		}
	});
	expect(denied.status()).toBe(403);
	await expect(page.getByRole('navigation', { name: 'Namespace path' })).toContainText(
		'huron-local'
	);
	const admin = await openPage(page, '/admin');
	expect(admin?.status()).toBe(403);
	await expect(page.locator('main')).not.toContainText('Create Huron user');
});

test('Writer registration persists and unregistering removes only the catalog record', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'writer');
	await signIn(page, username, USER_PASSWORD, repositoryUrl);
	const name = `browser-repo-${randomUUID().slice(0, 8)}`;
	await page.getByText('Namespace operations', { exact: true }).click();
	await page.getByText('Register an Icechunk repository', { exact: true }).click();
	const form = formWithButton(page, 'Register repository');
	await form.getByLabel('Repository name', { exact: true }).fill(name);
	const location = await form.getByLabel('Repository root URI').getAttribute('placeholder');
	expect(location).toMatch(/^file:\/\//);
	await form
		.getByLabel('Repository root URI')
		.fill((location ?? '').replace(/simulation-output\/?$/, name));
	await form.getByRole('button', { name: 'Register repository', exact: true }).click();
	await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
	await expect(page).toHaveURL(new RegExp(`table=${name}`));
	await page.reload();
	await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
	await page.getByText('Repository operations', { exact: true }).click();
	await page.getByText('Unregister repository', { exact: true }).first().click();
	await page.getByLabel(`Type ${name} to confirm`).fill(name);
	await page.getByRole('button', { name: 'Unregister repository', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: 'Storage contents remain untouched' })
	).toBeVisible();
	await openPage(page, repositoryUrl);
	await expect(page.getByRole('link', { name, exact: true })).toHaveCount(0);
});

test('credential checks expose availability and expiry without storage or account secrets', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page, 'ocean-data', 'writer');
	await signIn(
		page,
		username,
		USER_PASSWORD,
		'/browse?catalog=ocean-data&namespace=%5B%22science%22%5D&table=temperature'
	);
	await page.getByText('Repository operations', { exact: true }).click();
	await page.getByText('Storage access', { exact: true }).click();
	await page.getByLabel('Requested access').selectOption('read-write');
	const response = page.waitForResponse(
		(result) => result.request().method() === 'POST' && result.url().includes('tableCredentials')
	);
	await page.getByRole('button', { name: 'Check storage access', exact: true }).click();
	const body = await (await response).text();
	expect(body).not.toContain('NEVER_RENDER_');
	expect(body).not.toContain('browser-secret');
	expect(body).not.toContain(USER_PASSWORD);
	await expect(page.getByText(/Polaris vended storage credentials/)).toBeVisible();
	await expect(page.locator('body')).not.toContainText('NEVER_RENDER_');
	await page.reload();
	await expect(page.getByText(/Polaris vended storage credentials/)).toHaveCount(0);
});

test('nested namespace deep links preserve each level and keyboard navigation opens a repository', async ({
	page
}) => {
	await signIn(page, 'admin', 'browser-admin-password', repositoryUrl);
	await page.getByText('Namespace operations', { exact: true }).click();
	await page.getByText('Create a child namespace', { exact: true }).click();
	const name = `child-${randomUUID().slice(0, 8)}`;
	const form = formWithButton(page, 'Create namespace');
	await form.getByLabel('Namespace name', { exact: true }).fill(name);
	await form.getByRole('button', { name: 'Create namespace', exact: true }).click();
	const childFolder = page
		.getByRole('navigation', { name: 'Namespace explorer' })
		.getByRole('link', { name, exact: true });
	await expect(childFolder).toBeVisible();
	await childFolder.click();
	await expect
		.poll(() => JSON.parse(new URL(page.url()).searchParams.get('namespace') ?? '[]'))
		.toEqual(['science', name]);
	await page.reload();
	await expect(page.getByRole('navigation', { name: 'Namespace path' })).toContainText(name);
	await openPage(page, repositoryUrl);
	const repository = page
		.getByRole('navigation', { name: 'Namespace explorer' })
		.getByRole('link', { name: 'temperature', exact: true });
	await repository.focus();
	await expect(repository).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(page).toHaveURL(/table=temperature$/);
	await expect(page.getByRole('heading', { name: 'temperature', exact: true })).toBeVisible();
});

test('Browse keeps only the selected catalog and folders expand or collapse around repository leaves', async ({
	page
}) => {
	await signIn(page, 'admin', 'browser-admin-password', '/browse?catalog=huron-local');
	await expect(page.locator('main')).not.toContainText('ocean-data');
	const explorer = page.getByRole('navigation', { name: 'Namespace explorer' });
	await expect(explorer.getByRole('link', { name: 'science', exact: true })).toBeVisible();
	await expect(explorer.getByRole('link', { name: 'temperature', exact: true })).toHaveCount(0);
	await explorer.getByRole('button', { name: 'Expand science', exact: true }).click();
	await expect
		.poll(() => JSON.parse(new URL(page.url()).searchParams.get('namespace') ?? '[]'))
		.toEqual(['science']);
	await expect(explorer.getByRole('link', { name: 'temperature', exact: true })).toBeVisible();
	await explorer.getByRole('button', { name: 'Collapse science', exact: true }).click();
	await expect(explorer.getByRole('link', { name: 'temperature', exact: true })).toHaveCount(0);
	await expect(page.getByRole('navigation', { name: 'Namespace path' })).toContainText('science');
	await explorer.getByRole('button', { name: 'Expand science', exact: true }).click();
	await explorer.getByRole('link', { name: 'temperature', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'temperature', exact: true })).toBeVisible();
	await expect(
		page
			.getByRole('navigation', { name: 'Dataset details' })
			.getByRole('link', { name: 'Overview', exact: true })
	).toHaveAttribute('aria-current', 'page');
	await expect(
		explorer.getByRole('button', { name: 'Collapse science', exact: true })
	).toBeVisible();
	await openPage(page, '/browse?catalog=ocean-data');
	await expect(page.locator('main')).not.toContainText('huron-local');
	await expect(
		page
			.getByRole('navigation', { name: 'Namespace explorer' })
			.getByRole('button', { name: 'Expand science', exact: true })
	).toBeVisible();
});

test('FILE repositories provide Python code using authorized metadata without Huron principal credentials', async ({
	page
}) => {
	await signIn(page, 'admin', 'browser-admin-password', `${repositoryUrl}&table=temperature`);
	await page.getByText('Repository operations', { exact: true }).click();
	await page.getByText('Open in Python', { exact: true }).click();
	const code = page.getByText('Open in Python', { exact: true }).locator('..').locator('pre');
	await expect(code).toContainText('icechunk.local_filesystem_storage');
	await expect(code).toContainText('icechunk.Repository.open');
	await expect(code).toContainText('readonly_session');
	await expect(code).toContainText('snapshot_id=');
	await expect(code).not.toContainText('POLARIS_CLIENT_SECRET');
	await expect(code).not.toContainText('oauth');
	await expect(page.getByText(/no Polaris credentials are needed/)).toBeVisible();
});

test('undiscoverable repository selections do not leak upstream errors', async ({ page }) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'reader');
	await signIn(page, username, USER_PASSWORD);
	const response = await openPage(page, `${repositoryUrl}&table=concealed`);
	expect(response?.status()).toBe(404);
	await expect(page.getByRole('heading', { name: 'Not found', exact: true })).toBeVisible();
	await expect(page.locator('main')).not.toContainText(/PRIVATE|permission|forbidden/);
});

test('real Icechunk array schema, snapshots and branch selection stay pinned to repository identity', async ({
	page
}) => {
	await signIn(
		page,
		'admin',
		'browser-admin-password',
		`${repositoryUrl}&table=temperature&tab=schema`
	);
	const tabs = page.getByRole('navigation', { name: 'Dataset details' });
	await expect(tabs.getByRole('link', { name: 'Schema', exact: true })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(page.getByRole('heading', { name: 'Array schema', exact: true })).toBeVisible();
	await expect(page.getByRole('row').filter({ hasText: 'temperature' })).toContainText('float32');
	await expect(page.getByRole('row').filter({ hasText: 'temperature' })).toContainText(
		'time × lat × lon'
	);
	await expect(page.getByRole('row').filter({ hasText: 'temperature' })).toContainText('kelvin');
	await tabs.getByRole('link', { name: 'History', exact: true }).click();
	await expect(page.getByText('Fixture metadata correction', { exact: true })).toBeVisible();
	await expect(page.getByText('Fixture ingest 1', { exact: true })).toBeVisible();
	const snapshot = page
		.locator('main ol li')
		.filter({ hasText: 'Fixture ingest 1' })
		.getByRole('link');
	const snapshotUrl = await snapshot.getAttribute('href');
	expect(new URL(snapshotUrl ?? '', page.url()).searchParams.get('snapshot')).toBe(
		(await snapshot.textContent())?.trim()
	);
	await snapshot.click();
	await expect(tabs.getByRole('link', { name: 'Schema', exact: true })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(page.getByRole('row').filter({ hasText: 'temperature' })).toContainText('kelvin');
	await tabs.getByRole('link', { name: 'Overview', exact: true }).click();
	await page.getByText('Repository operations', { exact: true }).click();
	await page.getByText('Open in Python', { exact: true }).click();
	const pinnedCode = page.getByText('Open in Python', { exact: true }).locator('..').locator('pre');
	await expect(pinnedCode).toContainText(
		`snapshot_id=${JSON.stringify(new URL(snapshotUrl ?? '', page.url()).searchParams.get('snapshot'))}`
	);
	await page.getByLabel('Repository branch').selectOption('analysis');
	await page.getByRole('button', { name: 'Open branch', exact: true }).click();
	await expect(page).toHaveURL(/branch=analysis/);
	expect(new URL(page.url()).searchParams.has('snapshot')).toBe(false);
	await tabs.getByRole('link', { name: 'History', exact: true }).click();
	await expect(page.getByText('Fixture ingest 1', { exact: true })).toBeVisible();
	await expect(page.getByText('Fixture metadata correction', { exact: true })).toHaveCount(0);
	const explorer = page.getByRole('navigation', { name: 'Namespace explorer' });
	await explorer.getByRole('button', { name: 'Collapse science', exact: true }).click();
	await tabs.getByRole('link', { name: 'Schema', exact: true }).click();
	await expect(explorer.getByRole('button', { name: 'Expand science', exact: true })).toBeVisible();
	await expect(explorer.getByRole('link', { name: 'temperature', exact: true })).toHaveCount(0);
	await tabs.getByRole('link', { name: 'Lineage', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Lineage', exact: true })).toBeVisible();
	await expect(page.getByText('Recorded source', { exact: true })).toBeVisible();
});

test('native Iceberg metadata has schema and history without Icechunk operations', async ({
	page
}) => {
	await signIn(
		page,
		'admin',
		'browser-admin-password',
		'/browse?catalog=huron-local&namespace=%5B%22science%22%5D&table=observations&format=iceberg&tab=schema'
	);
	await expect(page.getByRole('heading', { name: 'observations', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Table schema', exact: true })).toBeVisible();
	await expect(page.getByRole('row').filter({ hasText: 'station' })).toContainText('string');
	await expect(page.getByRole('row').filter({ hasText: 'temperature' })).toContainText('double');
	await expect(page.getByText('Repository operations', { exact: true })).toHaveCount(0);
	const tabs = page.getByRole('navigation', { name: 'Dataset details' });
	await tabs.getByRole('link', { name: 'History', exact: true }).click();
	await expect(page.getByRole('link', { name: '42', exact: true })).toBeVisible();
	await tabs.getByRole('link', { name: 'Policies', exact: true }).click();
	await expect(
		page.getByText('No applicable policies are disclosed for this table.', { exact: true })
	).toBeVisible();
});
