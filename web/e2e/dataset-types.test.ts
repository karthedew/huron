import { randomUUID } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';
import { createUser, openPage, repositoryUrl, signIn, USER_PASSWORD } from './helpers';

function registrationForm(page: Page, submit: string) {
	return page
		.locator('form')
		.filter({ has: page.getByRole('button', { name: submit, exact: true }) });
}

async function openRegistration(page: Page, kind: 'Raw collection' | 'Iceberg table') {
	await page.getByText('Namespace operations', { exact: true }).click();
	await page
		.getByText(`Register ${kind === 'Raw collection' ? 'a' : 'an'} ${kind}`, { exact: true })
		.click();
	return registrationForm(page, `Register ${kind}`);
}

test('one namespace lists Raw, Icechunk, Iceberg and other generic assets with independent type and layer filters', async ({
	page
}) => {
	await signIn(page, 'admin', 'browser-admin-password', repositoryUrl);
	const contents = page.getByRole('region', { name: 'Folder contents' });
	await expect(contents.getByRole('row').filter({ hasText: 'source_files' })).toContainText(
		'Raw files'
	);
	await expect(contents.getByRole('row').filter({ hasText: 'temperature' })).toContainText(
		'Icechunk'
	);
	await expect(contents.getByRole('row').filter({ hasText: 'observations' })).toContainText(
		'Iceberg'
	);
	await expect(contents.getByRole('row').filter({ hasText: 'observations' })).toContainText(
		'Not loaded'
	);
	await expect(contents.getByRole('row').filter({ hasText: 'external_delta' })).toContainText(
		'Generic'
	);
	await page
		.getByRole('combobox', { name: 'Processing layer', exact: true })
		.selectOption('unknown');
	await expect(contents.getByRole('link', { name: 'observations', exact: true })).toBeVisible();
	await expect(contents.getByRole('link', { name: 'source_files', exact: true })).toHaveCount(0);
	await page
		.getByRole('combobox', { name: 'Processing layer', exact: true })
		.selectOption('unassigned');
	await expect(contents.getByRole('link', { name: 'observations', exact: true })).toHaveCount(0);
	await page.getByRole('combobox', { name: 'Dataset type', exact: true }).selectOption('raw');
	await page
		.getByRole('combobox', { name: 'Processing layer', exact: true })
		.selectOption('bronze');
	await expect(contents.getByRole('link', { name: 'source_files', exact: true })).toBeVisible();
	await expect(contents.getByRole('link', { name: 'temperature', exact: true })).toHaveCount(0);
	await expect(contents.getByRole('link', { name: 'external_delta', exact: true })).toHaveCount(0);
	await page.getByRole('combobox', { name: 'Processing layer', exact: true }).selectOption('gold');
	await expect(contents.getByRole('link', { name: 'source_files', exact: true })).toHaveCount(0);
	await expect(page.getByText('No datasets match these filters on this page.')).toBeVisible();
	await page.getByRole('combobox', { name: 'Dataset type', exact: true }).selectOption('generic');
	await page.getByRole('combobox', { name: 'Processing layer', exact: true }).selectOption('all');
	await contents.getByRole('link', { name: 'external_delta', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'external_delta', exact: true })).toBeVisible();
	await expect(page.locator('main')).toContainText('Registered format');
	await expect(page.locator('main')).toContainText('delta');
	await expect(page.locator('main')).toContainText('Generic');
});

test('a Writer registers a persistent Raw collection while files and revision publication remain explicit', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'writer');
	await signIn(page, username, USER_PASSWORD, repositoryUrl);
	const name = `raw-${randomUUID().slice(0, 8)}`;
	const form = await openRegistration(page, 'Raw collection');
	await form.getByLabel('Dataset name', { exact: true }).fill(name);
	await form
		.getByLabel('Storage location · optional')
		.fill(`file:///tmp/huron-browser-test/raw/${name}`);
	await form.getByLabel('Description · optional').fill('Original source collection');
	await form
		.getByRole('combobox', { name: 'Processing layer', exact: true })
		.selectOption('bronze');
	await form.getByRole('button', { name: 'Register Raw collection', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `Raw collection ${name} registered in Polaris` })
	).toContainText('No files were uploaded and no Raw revision was published');
	await page.reload({ waitUntil: 'networkidle' });
	await page
		.getByRole('region', { name: 'Folder contents' })
		.getByRole('link', { name, exact: true })
		.click();
	await expect(page).toHaveURL(new RegExp(`table=${name}.*format=raw`));
	await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
	await expect(page.locator('main')).toContainText('Persisted in Polaris');
	await expect(page.locator('main')).toContainText('Bronze');
	const tabs = page.getByRole('navigation', { name: 'Dataset details' });
	await tabs.getByRole('link', { name: 'Files', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Files and manifests' })).toBeVisible();
	await expect(page.locator('main')).toContainText('File listing is not connected');
	await tabs.getByRole('link', { name: 'History', exact: true }).click();
	await expect(page.locator('main')).toContainText('Raw revision history is not connected');
	await tabs.getByRole('link', { name: 'Permissions', exact: true }).click();
	await expect(page.locator('main')).toContainText('TABLE_WRITE_DATA');
	await tabs.getByRole('link', { name: 'Policies', exact: true }).click();
	await expect(page.locator('main')).toContainText(
		'does not support those bindings for generic-table assets'
	);
});

test('Raw registration rejects conflicting processing stages before creating a catalog asset', async ({
	page
}) => {
	await signIn(page);
	const name = `layer-${randomUUID().slice(0, 8)}`;
	const parent = await page.request.post('/browse?/createNamespace', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: { catalog: 'huron-local', namespace: JSON.stringify([name]), properties: '{}' }
	});
	expect(parent.ok()).toBe(true);
	const created = await page.request.post('/browse?/createNamespace', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: { catalog: 'huron-local', namespace: JSON.stringify([name, 'bronze']), properties: '{}' }
	});
	expect(created.ok()).toBe(true);
	await openPage(
		page,
		`/browse?catalog=huron-local&namespace=${encodeURIComponent(JSON.stringify([name, 'bronze']))}`
	);
	const form = await openRegistration(page, 'Raw collection');
	await form.getByLabel('Dataset name', { exact: true }).fill('conflicting_files');
	await form
		.getByRole('combobox', { name: 'Processing layer', exact: true })
		.selectOption('silver');
	await form.getByRole('button', { name: 'Register Raw collection', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText(
		'must identify the same bronze, silver or gold stage'
	);
	await expect(
		page
			.getByRole('region', { name: 'Folder contents' })
			.getByRole('link', { name: 'conflicting_files' })
	).toHaveCount(0);
	await openPage(
		page,
		`/browse?catalog=huron-local&namespace=${encodeURIComponent(JSON.stringify([name, 'bronze']))}&table=conflicting_files&format=raw`
	);
	await expect(page.getByRole('heading', { name: 'Not found', exact: true })).toBeVisible();
});

test('a Reader cannot register Raw or Iceberg assets and cannot discover another catalog’s Raw assets', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'reader');
	await signIn(page, username, USER_PASSWORD, repositoryUrl);
	for (const action of ['registerRawTable', 'registerIcebergTable']) {
		const response = await page.request.post(`/browse?/${action}`, {
			headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
			form: {
				catalog: 'huron-local',
				namespace: '["science"]',
				name: `denied-${randomUUID().slice(0, 8)}`,
				metadataLocation: 's3://browser-test/existing/metadata/v1.metadata.json'
			}
		});
		expect(response.status()).toBe(403);
	}
	const response = await openPage(
		page,
		'/browse?catalog=ocean-data&namespace=%5B%22science%22%5D&table=source_files&format=raw'
	);
	expect(response?.status()).toBe(404);
	await expect(page.getByRole('heading', { name: 'Not found', exact: true })).toBeVisible();
	await expect(page.locator('main')).not.toContainText('PRIVATE');
});

test('an existing Iceberg metadata registration persists and opens its native schema', async ({
	page
}) => {
	await signIn(page);
	const username = await createUser(page, 'huron-local', 'writer');
	await signIn(page, username, USER_PASSWORD, repositoryUrl);
	const name = `summary-${randomUUID().slice(0, 8)}`;
	const form = await openRegistration(page, 'Iceberg table');
	await form.getByLabel('Dataset name', { exact: true }).fill(name);
	await form
		.getByLabel('Existing metadata JSON location')
		.fill('s3://browser-test/existing/metadata/v1.metadata.json');
	await form.getByRole('button', { name: 'Register Iceberg table', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `Iceberg table ${name} registered in Polaris` })
	).toBeVisible();
	await page.reload({ waitUntil: 'networkidle' });
	await page
		.getByRole('region', { name: 'Folder contents' })
		.getByRole('link', { name, exact: true })
		.click();
	await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
	await page
		.getByRole('navigation', { name: 'Dataset details' })
		.getByRole('link', { name: 'Schema', exact: true })
		.click();
	await expect(page.getByRole('row').filter({ hasText: 'temperature' })).toContainText('double');
	await expect(page.getByRole('row').filter({ hasText: 'station' })).toContainText('string');
});
