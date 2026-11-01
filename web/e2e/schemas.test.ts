import { expect } from '@playwright/test';
import { SCHEMAS } from './support/fixture.mjs';
import { ApiSession, horizontalOverflow, signIn, test } from './support/harness.ts';

const ORGANIZATION_SCHEMA = SCHEMAS[0];

test('browses organization versions, their resolved fields and their platform parent', async ({
	page
}) => {
	await signIn(page, 'erin');
	await page.goto(`/schemas?organization=${ORGANIZATION_SCHEMA.organization}`);
	await expect(page.getByRole('heading', { name: 'Schemas', level: 1 })).toBeVisible();
	const versions = page.getByRole('table', { name: 'Published schema versions' });
	await versions.getByRole('link', { name: ORGANIZATION_SCHEMA.name, exact: true }).click();
	await expect(
		page.getByRole('heading', { name: `${ORGANIZATION_SCHEMA.name} v1`, level: 1 })
	).toBeVisible();
	const fields = page.getByRole('table', { name: 'Resolved schema fields' });
	await expect(fields.getByRole('rowheader', { name: /Mission/ })).toBeVisible();
	await expect(fields.getByRole('rowheader', { name: /Title/ })).toBeVisible();
	await page.getByText('Authored schema', { exact: true }).click();
	const authored = page.getByRole('table', { name: 'Authored schema fields' });
	await expect(authored.getByRole('rowheader', { name: /Mission/ })).toBeVisible();
	await expect(authored.getByRole('rowheader', { name: /Title/ })).toHaveCount(0);
	await page.getByRole('link', { name: `${ORGANIZATION_SCHEMA.extends} v1`, exact: true }).click();
	await expect(
		page.getByRole('heading', { name: `${ORGANIZATION_SCHEMA.extends} v1`, level: 1 })
	).toBeVisible();
	await page.getByRole('link', { name: 'Back to schemas' }).click();
	await expect(page).toHaveURL('/schemas?organization=');
	await expect(page.getByRole('heading', { name: 'Platform schemas' })).toBeVisible();
});

test('changes schema source with a GET form and explains an empty organization registry', async ({
	page
}) => {
	await signIn(page, 'alice');
	await page.goto('/schemas?organization=helio');
	await page.getByRole('combobox', { name: 'Schema source' }).selectOption('geo');
	await page.getByRole('button', { name: 'Browse schemas' }).click();
	await expect(page).toHaveURL('/schemas?organization=geo');
	await expect(page.getByText('No schema versions have been published here.')).toBeVisible();
	await page.getByRole('combobox', { name: 'Schema source' }).selectOption('');
	await page.getByRole('button', { name: 'Browse schemas' }).click();
	await expect(page.getByRole('table', { name: 'Published schema versions' })).toBeVisible();
});

test('conceals hidden organization schemas and keeps platform schemas readable', async ({
	page
}) => {
	const api = await ApiSession.as('erin');
	const answer = await api.get(`organizations/${ORGANIZATION_SCHEMA.organization}/schemas`);
	const body = answer.body;
	if (typeof body !== 'object' || body === null || !('items' in body) || !Array.isArray(body.items))
		throw new Error('fixture schema page is missing');
	const entry: unknown = body.items[0];
	if (
		typeof entry !== 'object' ||
		entry === null ||
		!('id' in entry) ||
		typeof entry.id !== 'string'
	)
		throw new Error('fixture schema entry is missing');
	await signIn(page, 'mallory');
	for (const path of ['/schemas?organization=helio', `/schemas/${entry.id}`]) {
		await page.goto(path);
		await expect(
			page.getByRole('heading', { name: "Not found, or you don't have access.", level: 1 })
		).toBeVisible();
	}
	await page.goto('/schemas?organization=');
	await expect(page.getByRole('link', { name: 'huron-base', exact: true })).toBeVisible();
});

for (const width of [390, 816, 1440]) {
	test(`schema pages keep their tables inside the page at ${width}`, async ({ page }) => {
		await page.setViewportSize({ width, height: 900 });
		await signIn(page, 'erin');
		await page.goto('/schemas?organization=helio');
		expect(await horizontalOverflow(page)).toBe(0);
		await page.getByRole('link', { name: ORGANIZATION_SCHEMA.name, exact: true }).click();
		await expect(
			page.getByRole('heading', { name: `${ORGANIZATION_SCHEMA.name} v1`, level: 1 })
		).toBeVisible();
		expect(await horizontalOverflow(page)).toBe(0);
	});
}
