import { randomUUID } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';
import { createUser, openPage, signIn, USER_PASSWORD } from './helpers';

function actionForm(page: Page, name: string) {
	return page.locator('form').filter({ has: page.getByRole('button', { name, exact: true }) });
}

async function createOrganization(page: Page) {
	const slug = `research-${randomUUID().slice(0, 8)}`;
	const name = `Research division ${slug}`;
	await openPage(page, '/admin?tab=organizations');
	const form = actionForm(page, 'Create organization');
	await form.getByLabel('Organization name', { exact: true }).fill(name);
	await form.getByLabel('Organization identifier', { exact: true }).fill(slug);
	await form.getByRole('button', { name: 'Create organization', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `Organization ${name} created.` })
	).toBeVisible();
	return { slug, name };
}

async function createCatalog(page: Page, organization?: string) {
	const name = `science-${randomUUID().slice(0, 8)}`;
	await openPage(page, '/admin?tab=catalogs');
	const form = actionForm(page, 'Create catalog');
	if (organization)
		await form
			.getByRole('combobox', { name: 'Organization', exact: true })
			.selectOption(organization);
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
	await form.getByRole('button', { name: 'Add organization member', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: 'Organization membership saved.' })
	).toBeVisible();
}

test('catalog settings keep an empty organization empty instead of selecting another catalog', async ({
	page
}) => {
	await signIn(page);
	const organization = await createOrganization(page);
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
	await page.getByRole('banner').getByLabel('Switch catalog', { exact: true }).click();
	await expect(
		page
			.getByRole('banner')
			.getByText('No accessible catalogs in this organization.', { exact: true })
	).toBeVisible();
});

test('moving a catalog requires the receiving organization membership as well as its Polaris role', async ({
	page
}) => {
	await signIn(page);
	const catalog = await createCatalog(page);
	const username = await createUser(page, catalog, 'reader');
	const organization = await createOrganization(page);
	const assignment = actionForm(page, 'Assign catalog');
	await assignment
		.getByRole('combobox', { name: 'Catalog to assign', exact: true })
		.selectOption(catalog);
	await assignment
		.getByRole('combobox', { name: 'Owning organization', exact: true })
		.selectOption(organization.slug);
	await assignment.getByRole('button', { name: 'Assign catalog', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: 'Catalog organization saved.' })
	).toBeVisible();
	await signIn(page, username, USER_PASSWORD);
	expect((await openPage(page, `/browse?catalog=${catalog}`))?.status()).toBe(404);
	expect(
		(await openPage(page, `/settings/organization?organization=${organization.slug}`))?.status()
	).toBe(404);
	await signIn(page);
	await addOrganizationMember(page, organization.slug, username);
	await signIn(page, username, USER_PASSWORD, `/?organization=${organization.slug}`);
	await expect(page.getByRole('heading', { name: catalog, exact: true })).toBeVisible();
	expect((await openPage(page, `/browse?catalog=${catalog}`))?.status()).toBe(200);
	await expect(page.getByRole('navigation', { name: 'Namespace path' })).toContainText(catalog);
	await openPage(page, `/settings/organization?organization=${organization.slug}`);
	await expect(page.getByRole('button', { name: 'Save organization', exact: true })).toHaveCount(0);
	await expect(
		page.getByRole('button', { name: 'Add organization member', exact: true })
	).toHaveCount(0);
	const forbidden = await page.request.post(
		`/settings/organization?organization=${organization.slug}&/updateOrganization`,
		{
			headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
			form: { organization: organization.slug, name: 'Unauthorized rename', description: '' }
		}
	);
	expect(forbidden.status()).toBe(403);
	await page.reload();
	await expect(page.getByRole('heading', { name: organization.name, exact: true })).toBeVisible();
});

test('retrying catalog creation cannot move an existing catalog to another organization', async ({
	page
}) => {
	await signIn(page);
	const owner = await createOrganization(page);
	const catalog = await createCatalog(page, owner.slug);
	const username = await createUser(page, catalog, 'reader');
	const other = await createOrganization(page);
	const form = {
		organization: owner.slug,
		name: catalog,
		defaultBaseLocation: `file:///tmp/huron-browser-test/${catalog}/`,
		storageConfigInfo: JSON.stringify({
			storageType: 'FILE',
			allowedLocations: ['file:///tmp/huron-browser-test/']
		}),
		properties: '{}'
	};
	const retry = await page.request.post('/admin?/createCatalog', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form
	});
	expect(retry.status()).toBe(200);
	expect(await retry.text()).toContain(`Catalog ${catalog} is ready in Polaris`);
	const wrongOrganization = await page.request.post('/admin?/createCatalog', {
		headers: { Origin: 'http://localhost:4173', Accept: 'text/html' },
		form: { ...form, organization: other.slug }
	});
	expect(wrongOrganization.status()).toBe(409);
	expect(await wrongOrganization.text()).toContain(
		'Use Assign catalog to move an existing catalog.'
	);
	await signIn(page, username, USER_PASSWORD, `/?organization=${owner.slug}`);
	expect(
		(await openPage(page, `/browse?organization=${owner.slug}&catalog=${catalog}`))?.status()
	).toBe(200);
	expect(
		(await openPage(page, `/browse?organization=${other.slug}&catalog=${catalog}`))?.status()
	).toBe(404);
});

test('organization administrators manage people without receiving implicit Polaris catalog grants', async ({
	page
}) => {
	await signIn(page);
	const organization = await createOrganization(page);
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
	expect((await openPage(page, `/browse?catalog=${catalog}`))?.status()).toBe(404);
	expect((await openPage(page, `/settings/catalog?catalog=${catalog}`))?.status()).toBe(404);
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
			for (const name of ['Switch organization', 'Switch catalog']) {
				const trigger = page.getByRole('banner').getByLabel(name, { exact: true });
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
			}
			expect(
				await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
			).toBe(true);
		}
		expect(errors).toEqual([]);
	});
}
