import { expect } from '@playwright/test';
import { CATALOGS, NAMESPACES, ORGANIZATIONS, visibleOrganizations } from './support/fixture.mjs';
import { ApiSession, VIEWPORTS, horizontalOverflow, signIn, test } from './support/harness.ts';

/** The `next_cursor` of an API page answer. */
function nextCursor(body: unknown): string {
	const cursor =
		typeof body === 'object' && body !== null && 'next_cursor' in body ? body.next_cursor : null;
	if (typeof cursor !== 'string') throw new Error('the page has no next cursor');
	return cursor;
}

/** "N namespaces in total" as the fixture creates them. */
function namespaceCount(catalog: string): string {
	const count = NAMESPACES.filter((namespace) => namespace.catalog === catalog).length;
	return `${count} ${count === 1 ? 'namespace' : 'namespaces'} in total`;
}

test.describe('all organizations', () => {
	test('shows a card per visible organization', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto('/orgs');
		await expect(page).toHaveTitle('All organizations · Huron');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: 'All organizations', level: 1 })).toBeVisible();
		const cards = main.getByRole('list').getByRole('link');
		await expect(cards).toHaveCount(visibleOrganizations('alice').length);
		for (const organization of ORGANIZATIONS) {
			const card = main.getByRole('link', { name: new RegExp(`^${organization.displayName}`) });
			await expect(card).toHaveAttribute('href', `/orgs/${organization.name}`);
			await expect(card).toContainText(organization.name);
			if (organization.description !== '')
				await expect(card).toContainText(organization.description);
			const catalogs = CATALOGS.filter(({ organization: owner }) => owner === organization.name);
			await expect(card).toContainText(
				`${catalogs.length} ${catalogs.length === 1 ? 'catalog' : 'catalogs'}`
			);
		}
		await expect(main.getByRole('navigation', { name: 'Organization pages' })).toHaveCount(0);
	});

	test('pages by cursor and leads back to the first page', async ({ page }) => {
		const alice = await ApiSession.as('alice');
		const cursor = nextCursor((await alice.get('organizations?limit=1')).body);
		await signIn(page, 'alice');
		await page.goto(`/orgs?cursor=${encodeURIComponent(cursor)}`);
		const main = page.getByRole('main');
		const rest = visibleOrganizations('alice').slice(1);
		await expect(main.getByRole('list').getByRole('link')).toHaveCount(rest.length);
		await expect(main.getByRole('link', { name: /^Astrophysics/ })).toHaveCount(0);

		const pages = main.getByRole('navigation', { name: 'Organization pages' });
		await expect(pages.getByRole('link', { name: 'Next page' })).toHaveCount(0);
		await pages.getByRole('link', { name: 'First page' }).click();
		await expect(page).toHaveURL('/orgs');
		await expect(main.getByRole('link', { name: /^Astrophysics/ })).toBeVisible();
	});

	test('a user without organizations learns why there too and can sign in again', async ({
		page
	}) => {
		await signIn(page, 'mallory');
		await page
			.getByRole('complementary', { name: 'Sidebar' })
			.getByRole('link', { name: 'Catalogs' })
			.click();
		await expect(page).toHaveURL('/orgs');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: 'All organizations', level: 1 })).toBeVisible();
		await expect(main.getByText("You don't have access to any organization yet.")).toBeVisible();
		await expect(main.getByText('Huron received no groups for your account.')).toBeVisible();
		await expect(
			main.getByText(
				'Groups are read when you sign in; if you were just added to a group, sign out and sign in again.'
			)
		).toBeVisible();
		await main.getByRole('button', { name: 'Sign out', exact: true }).click();
		await expect(page).toHaveURL('/login?status=signed-out');
	});

	test('an expired page link starts over and says so', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto('/orgs?cursor=not-a-cursor');
		await expect(page).toHaveURL('/orgs?notice=page_expired');
		await expect(page.getByRole('note')).toHaveText(
			'That page link expired; showing the first page.'
		);
		await expect(page.getByRole('main').getByRole('link', { name: /^Astrophysics/ })).toBeVisible();
	});
});

test.describe('an organization', () => {
	test('heads its pages and lists its catalogs', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/helio');
		const main = page.getByRole('main');
		await expect(
			main.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
		await expect(
			main.getByText('The Sun, the solar wind and the space environment.')
		).toBeVisible();
		const sections = main.getByRole('navigation', { name: 'Organization' });
		await expect(sections.getByRole('link')).toHaveText(['Catalogs2', 'Search']);
		await expect(sections.getByRole('link', { name: 'Catalogs' })).toHaveAttribute(
			'aria-current',
			'page'
		);

		const catalogs = main.getByRole('list', { name: 'Catalogs' }).getByRole('listitem');
		const helio = CATALOGS.filter(({ organization }) => organization === 'helio');
		await expect(catalogs).toHaveCount(helio.length);
		for (const [index, catalog] of helio.entries()) {
			const row = catalogs.nth(index);
			await expect(row.getByRole('link', { name: catalog.displayName })).toHaveAttribute(
				'href',
				`/catalogs/${catalog.name}`
			);
			await expect(row).toContainText(catalog.name);
			await expect(row).toContainText(catalog.description);
			await expect(row).toContainText(namespaceCount(catalog.name));
		}
		await expect(catalogs.nth(0).getByRole('link', { name: 'huron-base v1' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/schema'
		);
		await expect(catalogs.nth(1).getByRole('link', { name: 'space-weather v1' })).toHaveAttribute(
			'href',
			'/catalogs/space-weather/schema'
		);
		await expect(main.getByRole('region')).toHaveCount(0);
	});

	test('without catalogs, shows administrators how to create one', async ({ page, context }) => {
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		await signIn(page, 'alice');
		await page.goto('/orgs/planetary');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: 'Planetary Science', level: 1 })).toBeVisible();
		await expect(main.getByText('No catalogs you can see in this organization.')).toBeVisible();
		const hint = main.getByRole('region', { name: 'Create a catalog in this organization' });
		await expect(hint.getByText('huron catalog create planetary <name>')).toBeVisible();
		await expect(
			hint.getByText(
				'This website is read-only; changes are made with the huron CLI on a machine that mounts the share.'
			)
		).toBeVisible();
		await hint.getByRole('button', { name: 'Copy: Create a catalog in this organization' }).click();
		await expect(hint.getByRole('status')).toHaveText('Copied');
		expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
			'huron catalog create planetary <name>'
		);
	});

	test('without a clipboard, the hint shows the whole command on a phone, and a field with room', async ({
		browser
	}) => {
		const context = await browser.newContext({ viewport: VIEWPORTS.phone });
		try {
			// As on an insecure origin, where browsers offer no clipboard API.
			await context.addInitScript(() => {
				Object.defineProperty(Navigator.prototype, 'clipboard', { get: () => undefined });
			});
			const page = await context.newPage();
			await signIn(page, 'alice');
			await page.goto('/orgs/planetary');
			const hint = page.getByRole('region', { name: 'Create a catalog in this organization' });
			await expect(hint.locator('pre')).toHaveText('huron catalog create planetary <name>');
			await expect(hint.getByRole('textbox')).toHaveCount(0);
			await expect(hint.getByRole('button')).toHaveCount(0);
			expect(await horizontalOverflow(page)).toBe(0);

			await page.setViewportSize(VIEWPORTS.desktop);
			const field = hint.getByRole('textbox', { name: 'Create a catalog in this organization' });
			await expect(field).toHaveValue('huron catalog create planetary <name>');
			await expect(hint.locator('pre')).toBeHidden();
			// A command keeps its one row: none is hidden.
			expect(await field.evaluate((element) => element.scrollHeight - element.clientHeight)).toBe(
				0
			);
			expect(await horizontalOverflow(page)).toBe(0);
		} finally {
			await context.close();
		}
	});

	test('the command reads alike with and without a clipboard, in the text color', async ({
		browser
	}) => {
		const looks: { color: string; size: string; text: string }[] = [];
		for (const clipboard of [true, false]) {
			const context = await browser.newContext();
			try {
				if (!clipboard) {
					await context.addInitScript(() => {
						Object.defineProperty(Navigator.prototype, 'clipboard', { get: () => undefined });
					});
				}
				const page = await context.newPage();
				await signIn(page, 'alice');
				await page.goto('/orgs/planetary');
				const hint = page.getByRole('region', { name: 'Create a catalog in this organization' });
				const command = clipboard ? hint.locator('pre') : hint.getByRole('textbox');
				await expect(command).toBeVisible();
				looks.push(
					await command.evaluate((element) => ({
						color: getComputedStyle(element).color,
						size: getComputedStyle(element).fontSize,
						text: getComputedStyle(document.body).color
					}))
				);
			} finally {
				await context.close();
			}
		}
		const [code, field] = looks;
		// Not in the muted color of the empty state around it.
		expect(code.color).toBe(code.text);
		expect(field).toEqual(code);
	});

	test('the hint is plain text that a browser without scripts can select', async ({ browser }) => {
		const context = await browser.newContext({ javaScriptEnabled: false });
		try {
			const page = await context.newPage();
			await signIn(page, 'alice');
			await page.goto('/orgs/planetary');
			const hint = page.getByRole('region', { name: 'Create a catalog in this organization' });
			await expect(hint.locator('code')).toHaveText('huron catalog create planetary <name>');
			await expect(hint.getByRole('button')).toHaveCount(0);
			// The server's links are relative to the page, and Catalogs still says it leads here.
			await expect(
				page.getByRole('complementary', { name: 'Sidebar' }).getByRole('link', { name: 'Catalogs' })
			).toHaveAttribute('aria-current', 'page');
		} finally {
			await context.close();
		}
	});
});
