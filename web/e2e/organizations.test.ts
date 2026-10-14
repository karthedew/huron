import { randomUUID } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';
import { createUser, openPage, signIn, USER_PASSWORD } from './helpers';

function actionForm(page: Page, name: string) {
	return page.locator('form').filter({ has: page.getByRole('button', { name, exact: true }) });
}

async function createOrganization(page: Page, realm: string) {
	const slug = `research-${randomUUID().slice(0, 8)}`;
	const name = `Research division ${slug}`;
	await openPage(page, '/admin?tab=organizations');
	const form = actionForm(page, 'Create organization');
	await form.getByLabel('Organization name', { exact: true }).fill(name);
	await form.getByLabel('Organization identifier', { exact: true }).fill(slug);
	await form.getByRole('combobox', { name: 'Polaris realm', exact: true }).selectOption(realm);
	await form.getByRole('button', { name: 'Create organization', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `Organization ${name} created.` })
	).toBeVisible();
	return { slug, name };
}

async function createCatalog(
	page: Page,
	organization: string,
	name = `science-${randomUUID().slice(0, 8)}`
) {
	await openPage(page, '/admin?tab=catalogs');
	const form = actionForm(page, 'Create catalog');
	if (organization)
		await form
			.getByRole('combobox', { name: 'Organization', exact: true })
			.selectOption(organization);
	await form.getByLabel('Catalog name', { exact: true }).fill(name);
	await form
		.getByLabel('Default repository base URI')
		.fill(`file:///tmp/huron-browser-test/${organization}/${name}/`);
	await form
		.getByLabel('Storage configuration · JSON')
		.fill(
			JSON.stringify({ storageType: 'FILE', allowedLocations: ['file:///tmp/huron-browser-test/'] })
		);
	await form.getByRole('button', { name: 'Create catalog', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `Catalog ${name} is ready in Polaris` })
	).toBeVisible();
	return name;
}

async function addOrganizationMember(
	page: Page,
	organization: string,
	username: string,
	role = 'member'
) {
	await openPage(page, `/settings/organization?organization=${organization}`);
	const form = actionForm(page, 'Add organization member');
	await form.getByLabel('Username', { exact: true }).fill(username);
	await form.getByRole('combobox', { name: 'Organization role', exact: true }).selectOption(role);
	const submitted = page.waitForResponse((response) => {
		const url = new URL(response.url());
		return (
			response.request().method() === 'POST' &&
			url.pathname === '/settings/organization' &&
			url.searchParams.has('/setOrganizationMembership')
		);
	});
	await form.getByRole('button', { name: 'Add organization member', exact: true }).click();
	expect((await submitted).status()).toBe(200);
	await expect(
		page.getByRole('status').filter({ hasText: 'Organization membership saved.' })
	).toBeVisible();
}

test('catalog settings keep an empty organization empty instead of selecting another catalog', async ({
	page
}) => {
	await signIn(page);
	const organization = await createOrganization(page, 'E2E_EMPTY');
	const response = await openPage(page, `/settings/catalog?organization=${organization.slug}`);
	expect(response?.status()).toBe(200);
	await expect(
		page.getByRole('heading', { name: 'No catalogs available', exact: true })
	).toBeVisible();
	await expect(page.locator('main')).not.toContainText('huron-local');
	await expect(page.locator('main')).not.toContainText('ocean-data');
	await expect(
		page.getByRole('button', { name: 'Save catalog configuration', exact: true })
	).toHaveCount(0);
	await expect(page.getByRole('banner').getByLabel('Switch catalog')).toHaveCount(0);
	await page.getByRole('banner').getByLabel('Switch organization', { exact: true }).click();
	await page
		.getByRole('banner')
		.getByRole('link', { name: new RegExp(organization.name) })
		.click();
	await expect(page).toHaveURL(`/browse?organization=${organization.slug}`);
	await expect(page.getByText('No catalogs available', { exact: true })).toBeVisible();
	await expect(page.locator('main')).not.toContainText('huron-local');
	await expect(page.locator('main')).not.toContainText('ocean-data');
});

async function grantCatalog(
	page: Page,
	organization: string,
	catalog: string,
	username: string,
	role = 'reader'
) {
	await openPage(page, `/settings/catalog?organization=${organization}&catalog=${catalog}`);
	await page.getByLabel('Find a user').fill(username);
	const form = actionForm(page, `Save access for ${username}`);
	await form.getByLabel('Catalog role').selectOption(role);
	await form.getByRole('button', { name: `Save access for ${username}`, exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: 'Catalog membership saved in Polaris.' })
	).toBeVisible();
}

async function createNamespace(page: Page, organization: string, catalog: string, name: string) {
	const response = await page.request.post(
		`/browse?organization=${organization}&catalog=${catalog}&/createNamespace`,
		{
			headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
			form: { organization, catalog, namespace: JSON.stringify([name]), properties: '{}' }
		}
	);
	expect(response.status()).toBe(200);
}

test('separate organization roots isolate equal catalog names and require independent membership and grants', async ({
	page,
	browser
}) => {
	await signIn(page);
	const alpha = await createOrganization(page, 'E2E_ALPHA');
	const beta = await createOrganization(page, 'E2E_BETA');
	const catalog = `shared-${randomUUID().slice(0, 8)}`;
	await createCatalog(page, alpha.slug, catalog);
	await createCatalog(page, beta.slug, catalog);
	await createNamespace(page, alpha.slug, catalog, 'alpha_only');
	await createNamespace(page, beta.slug, catalog, 'beta_only');
	const username = await createUser(page);
	await addOrganizationMember(page, alpha.slug, username);
	await grantCatalog(page, alpha.slug, catalog, username);
	const scientistContext = await browser.newContext({ baseURL: 'http://localhost:4173' });
	try {
		const scientist = await scientistContext.newPage();
		await signIn(scientist, username, USER_PASSWORD, `/?organization=${alpha.slug}`);
		await expect(scientist.getByRole('heading', { name: catalog, exact: true })).toBeVisible();
		expect(
			(await openPage(scientist, `/browse?organization=${alpha.slug}&catalog=${catalog}`))?.status()
		).toBe(200);
		await expect(scientist.getByRole('navigation', { name: 'Namespace path' })).toContainText(
			catalog
		);
		await expect(scientist.locator('main')).toContainText('alpha_only');
		await expect(scientist.locator('main')).not.toContainText('beta_only');
		expect(
			(await openPage(scientist, `/browse?organization=${beta.slug}&catalog=${catalog}`))?.status()
		).toBe(404);
		expect((await openPage(scientist, '/browse?organization=unknown-organization'))?.status()).toBe(
			404
		);
		expect(
			(await openPage(scientist, `/settings/organization?organization=${beta.slug}`))?.status()
		).toBe(404);

		await addOrganizationMember(page, beta.slug, username);
		await openPage(scientist, `/browse?organization=${beta.slug}`);
		await expect(scientist.getByText('No catalogs available', { exact: true })).toBeVisible();
		expect(
			(await openPage(scientist, `/browse?organization=${beta.slug}&catalog=${catalog}`))?.status()
		).toBe(404);
		await grantCatalog(page, beta.slug, catalog, username);
		await openPage(scientist, `/browse?organization=${alpha.slug}&catalog=${catalog}`);
		await expect(scientist.locator('main')).toContainText('alpha_only');
		expect(
			(await openPage(scientist, `/browse?organization=${beta.slug}&catalog=${catalog}`))?.status()
		).toBe(200);
		await expect(scientist.locator('main')).toContainText('beta_only');
		await expect(scientist.locator('main')).not.toContainText('alpha_only');
		await openPage(scientist, `/settings/organization?organization=${beta.slug}`);
		await expect(
			scientist.getByRole('button', { name: 'Save organization', exact: true })
		).toHaveCount(0);
		await expect(
			scientist.getByRole('button', { name: 'Add organization member', exact: true })
		).toHaveCount(0);
		const forbidden = await scientist.request.post(
			`/settings/organization?organization=${beta.slug}&/updateOrganization`,
			{
				headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
				form: { organization: beta.slug, name: 'Unauthorized rename', description: '' }
			}
		);
		expect(forbidden.status()).toBe(403);
		await scientist.reload();
		await expect(scientist.getByRole('heading', { name: beta.name, exact: true })).toBeVisible();
	} finally {
		await scientistContext.close();
	}
});

test('retrying catalog creation preserves its identity and namespaces within the selected realm', async ({
	page
}) => {
	await signIn(page);
	const owner = await createOrganization(page, 'E2E_RETRY');
	const catalog = await createCatalog(page, owner.slug);
	await createNamespace(page, owner.slug, catalog, 'retained');
	const form = {
		organization: owner.slug,
		name: catalog,
		defaultBaseLocation: `file:///tmp/huron-browser-test/${owner.slug}/${catalog}/`,
		storageConfigInfo: JSON.stringify({
			storageType: 'FILE',
			allowedLocations: ['file:///tmp/huron-browser-test/']
		}),
		properties: '{}'
	};
	const retry = await page.request.post(`/admin?organization=${owner.slug}&/createCatalog`, {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form
	});
	expect(retry.status()).toBe(200);
	expect(await retry.text()).toContain(`Catalog ${catalog} is ready in Polaris`);
	expect(
		(await openPage(page, `/browse?organization=${owner.slug}&catalog=${catalog}`))?.status()
	).toBe(200);
	await expect(page.locator('main')).toContainText('retained');
	expect(
		(await openPage(page, `/browse?organization=workspace&catalog=${catalog}`))?.status()
	).toBe(404);
	const conflicting = await page.request.post(`/admin?organization=${owner.slug}&/createCatalog`, {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: { ...form, defaultBaseLocation: `file:///tmp/huron-browser-test/different/${catalog}/` }
	});
	expect(conflicting.status()).toBe(409);
});

async function publishRaw(page: Page, organization: string, catalog: string, contents: string) {
	await openPage(
		page,
		`/ingestion?organization=${organization}&catalog=${catalog}&namespace=%5B%22science%22%5D`
	);
	await page.getByRole('textbox', { name: 'Dataset name', exact: true }).fill('measurements');
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await page.getByLabel('Add files', { exact: true }).setInputFiles({
		name: 'observations.csv',
		mimeType: 'text/csv',
		buffer: Buffer.from(contents)
	});
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await page
		.getByRole('textbox', { name: 'Revision title', exact: true })
		.fill('Realm observations');
	await page.getByRole('textbox', { name: 'Creators', exact: true }).fill('Science team');
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await page.getByRole('button', { name: 'Upload and commit', exact: true }).click();
	await expect(page.getByText('Revision 1 committed and registered')).toBeVisible();
	await page.getByRole('link', { name: 'Browse uploaded files' }).click();
	const download = await page
		.getByRole('link', { name: 'Download payload/observations.csv', exact: true })
		.getAttribute('href');
	if (!download) throw new Error('The published Raw revision has no download URL.');
	const response = await page.request.get(download);
	expect(response.status()).toBe(200);
	expect(await response.body()).toEqual(Buffer.from(contents));
	return new URL(download, 'http://localhost:4173');
}

test('Raw uploads with identical catalog paths remain separate across organization realms', async ({
	page
}) => {
	await signIn(page);
	const alpha = await createOrganization(page, 'E2E_RAW_ALPHA');
	const beta = await createOrganization(page, 'E2E_RAW_BETA');
	const catalog = `raw-${randomUUID().slice(0, 8)}`;
	for (const organization of [alpha, beta]) {
		await createCatalog(page, organization.slug, catalog);
		await createNamespace(page, organization.slug, catalog, 'science');
	}
	const alphaDownload = await publishRaw(page, alpha.slug, catalog, 'realm,value\nalpha,11\n');
	const betaDownload = await publishRaw(page, beta.slug, catalog, 'realm,value\nbeta,22\n');
	expect(alphaDownload.pathname).not.toBe(betaDownload.pathname);
	alphaDownload.searchParams.set('organization', beta.slug);
	alphaDownload.searchParams.set(
		'target',
		JSON.stringify({
			organization: beta.slug,
			catalog,
			namespace: ['science'],
			name: 'measurements'
		})
	);
	const wrongRoot = await page.request.get(alphaDownload.href);
	expect(wrongRoot.status()).toBe(404);
	alphaDownload.searchParams.set('organization', alpha.slug);
	alphaDownload.searchParams.set(
		'target',
		JSON.stringify({
			organization: alpha.slug,
			catalog,
			namespace: ['science'],
			name: 'measurements'
		})
	);
	expect(await (await page.request.get(alphaDownload.href)).body()).toEqual(
		Buffer.from('realm,value\nalpha,11\n')
	);
});

test('organization administrators manage people without receiving implicit Polaris catalog grants', async ({
	page
}) => {
	await signIn(page);
	const organization = await createOrganization(page, 'E2E_ORGADMIN');
	const catalog = await createCatalog(page, organization.slug);
	const username = await createUser(page);
	await addOrganizationMember(page, organization.slug, username, 'admin');
	await signIn(
		page,
		username,
		USER_PASSWORD,
		`/settings/organization?organization=${organization.slug}`
	);
	await expect(page.getByRole('button', { name: 'Save organization', exact: true })).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'Add organization member', exact: true })
	).toBeVisible();
	await expect(
		page.locator('main').getByText('No accessible catalogs in this organization.', { exact: true })
	).toBeVisible();
	expect(
		(await openPage(page, `/browse?organization=${organization.slug}&catalog=${catalog}`))?.status()
	).toBe(404);
	expect(
		(
			await openPage(page, `/settings/catalog?organization=${organization.slug}&catalog=${catalog}`)
		)?.status()
	).toBe(404);
	expect((await openPage(page, '/admin'))?.status()).toBe(403);
});

for (const width of [390, 816, 1440]) {
	test(`organization and catalog navigation stay accessible at ${width}px in both themes`, async ({
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
			await openPage(page, '/browse?catalog=huron-local');
			await expect(page.getByRole('banner').getByLabel('Switch catalog')).toHaveCount(0);
			const trigger = page.getByRole('banner').getByLabel('Switch organization', { exact: true });
			await trigger.press('Enter');
			const menu = trigger.locator('..').locator(':scope > div');
			await expect(menu).toBeVisible();
			const bounds = await menu.boundingBox();
			expect(bounds).not.toBeNull();
			if (bounds) {
				expect(bounds.x).toBeGreaterThanOrEqual(0);
				expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
			}
			await page.keyboard.press('Escape');
			await expect(menu).toBeHidden();
			await expect(trigger).toBeFocused();
			expect(
				await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
			).toBe(true);
		}
		expect(errors).toEqual([]);
	});
}
