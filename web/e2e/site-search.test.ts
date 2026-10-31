import { expect, type Page } from '@playwright/test';
import { expectMarkedCurrent } from './support/cues.ts';
import { ORGANIZATIONS, visibleOrganizations } from './support/fixture.mjs';
import { COOKIES, VIEWPORTS, signIn, test, webCookie } from './support/harness.ts';

/** The search box of the banner. */
function siteSearch(page: Page) {
	const form = page.getByRole('banner').getByRole('search', { name: 'Site search' });
	return { form, field: form.getByRole('searchbox') };
}

/** The display name of a fixture organization. */
function displayNameOf(organization: string): string {
	const found = ORGANIZATIONS.find(({ name }) => name === organization);
	if (found === undefined) throw new Error(`no fixture organization ${organization}`);
	return found.displayName;
}

test.describe("the banner's search box", () => {
	test("searches a catalog from the catalog's pages", async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/namespaces/fields');
		const box = siteSearch(page);
		await expect(box.form).toMatchAriaSnapshot(`
			- search "Site search":
			  - searchbox "Search Heliophysics"
		`);
		await expect(box.field).toHaveAttribute('maxlength', '200');
		await box.field.fill('run');
		await box.field.press('Enter');
		await expect(page).toHaveURL('/catalogs/heliophysics/search?q=run');
		const main = page.getByRole('main');
		await expect(
			main.getByRole('search', { name: 'Catalog search' }).getByRole('searchbox')
		).toHaveValue('run');
		// On a search page it holds the text of the search shown.
		await expect(siteSearch(page).field).toHaveValue('run');
	});

	test('keeps what was typed while the page stays, as when skipping to the content', async ({
		page
	}) => {
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/search?q=mag');
		const box = siteSearch(page);
		await expect(box.field).toHaveValue('mag');
		await box.field.fill('typed, not sent');
		await page.getByRole('link', { name: 'Skip to content' }).focus();
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL('/catalogs/heliophysics/search?q=mag#main');
		await expect(page.getByRole('main')).toBeFocused();
		await expect(siteSearch(page).field).toHaveValue('typed, not sent');
	});

	test('searches an organization from its pages, the text trimmed', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto('/orgs/helio');
		const box = siteSearch(page);
		await expect(box.field).toHaveAccessibleName('Search Heliophysics Division');
		await box.field.fill('  wind ');
		await box.field.press('Enter');
		await expect(page).toHaveURL('/orgs/helio/search?q=wind');
		await expect(
			page.getByRole('main').getByRole('region', { name: 'Heliophysics', exact: true })
		).toBeVisible();
		// No text: the search page itself.
		await siteSearch(page).field.fill('   ');
		await siteSearch(page).field.press('Enter');
		await expect(page).toHaveURL('/orgs/helio/search');
	});

	test('searches the remembered organization from the account page', async ({ page, context }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/geo');
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
		await expect
			.poll(async () => (await webCookie(context, COOKIES.organization))?.value)
			.toBe('geo');
		await page.goto('/account');
		const box = siteSearch(page);
		await expect(box.field).toHaveAccessibleName('Search Earth Science');
		await box.field.fill('ocean');
		await box.field.press('Enter');
		await expect(page).toHaveURL('/orgs/geo/search?q=ocean');
		await expect(
			page.getByRole('main').getByRole('region', { name: 'Geoscience', exact: true })
		).toBeVisible();
	});

	test('asks which organization to search where none is remembered', async ({ page }) => {
		// Two organizations, and none remembered yet.
		await signIn(page, 'dave');
		await page.goto('/account');
		const box = siteSearch(page);
		await expect(box.field).toHaveAccessibleName('Search');
		await box.field.fill('wind');
		await box.field.press('Enter');
		await expect(page).toHaveURL('/search?q=wind');
		await expect(page).toHaveTitle('“wind” · Search · Huron');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: 'Search', level: 1 })).toBeVisible();
		await expect(main.getByText('Search “wind” in:')).toBeVisible();
		const offered = main.getByRole('list', { name: 'Organizations' }).getByRole('link');
		await expect(offered).toHaveText(visibleOrganizations('dave').map(displayNameOf));
		await expect(siteSearch(page).field).toHaveValue('wind');
		const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
		await expect(sidebar.getByRole('link', { name: 'Search' })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await offered.filter({ hasText: 'Heliophysics Division' }).click();
		await expect(page).toHaveURL('/orgs/helio/search?q=wind');
		await expect(
			page.getByRole('main').getByRole('region', { name: 'Heliophysics', exact: true })
		).toBeVisible();
	});

	test('says why it leaves each part of the address out that it cannot search', async ({
		page
	}) => {
		await signIn(page, 'dave');
		await page.goto(`/search?q=${'w'.repeat(201)}&label=mission`);
		await expect(page).toHaveTitle('Error: Search · Huron');
		const main = page.getByRole('main');
		await expect(main.getByText('Use at most 200 characters; this text has 201.')).toBeVisible();
		await expect(
			main.getByText('Write a label filter as key=value, for example mission=ace.')
		).toBeVisible();
		await expect(main.getByText('Choose the organization to search:')).toBeVisible();
		const offered = main.getByRole('list', { name: 'Organizations' }).getByRole('link');
		await expect(offered).toHaveText(visibleOrganizations('dave').map(displayNameOf));
		for (const organization of visibleOrganizations('dave')) {
			await expect(offered.filter({ hasText: displayNameOf(organization) })).toHaveAttribute(
				'href',
				`/orgs/${organization}/search`
			);
		}
	});

	test('goes straight to the search of the only organization the user can see', async ({
		page
	}) => {
		await signIn(page, 'bob');
		expect(visibleOrganizations('bob')).toEqual(['helio']);
		await page.goto('/search?q=wind&label=mission%3Dwind');
		await expect(page).toHaveURL('/orgs/helio/search?q=wind&label=mission%3Dwind');
	});

	test('tells someone without organizations why there is nothing to search', async ({ page }) => {
		await signIn(page, 'mallory');
		await page.goto('/search?q=wind');
		const main = page.getByRole('main');
		await expect(main.getByText("You don't have access to any organization yet.")).toBeVisible();
		await expect(main.getByRole('list', { name: 'Organizations' })).toHaveCount(0);
	});
});

test.describe('on a phone', () => {
	test.use({ viewport: VIEWPORTS.phone });

	test("the bottom navigation's Search opens the search of where the user is", async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/namespaces/fields');
		await expect(siteSearch(page).form).toBeHidden();
		const navigation = page.getByRole('navigation', { name: 'Primary' });
		await expect(navigation).toMatchAriaSnapshot(`
			- navigation "Primary":
			  - link "Catalogs":
			    - /url: /orgs/helio
			  - link "Search":
			    - /url: /catalogs/heliophysics/search
			  - link "Account":
			    - /url: /account
		`);
		await navigation.getByRole('link', { name: 'Search' }).click();
		await expect(page).toHaveURL('/catalogs/heliophysics/search');
		await expectMarkedCurrent(
			navigation.getByRole('link', { name: 'Search' }),
			navigation.getByRole('link', { name: 'Catalogs' })
		);
		await page.goto('/orgs/helio');
		await navigation.getByRole('link', { name: 'Search' }).click();
		await expect(page).toHaveURL('/orgs/helio/search');
		await expect(
			page.getByRole('main').getByRole('search', { name: 'Organization search' })
		).toBeVisible();
	});
});
