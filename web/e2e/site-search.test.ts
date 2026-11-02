import { expect, type Page } from '@playwright/test';
import { expectMarkedCurrent } from './support/cues.ts';
import { COOKIES, VIEWPORTS, signIn, test, webCookie } from './support/harness.ts';

/** The search box of the banner. */
function siteSearch(page: Page) {
	const form = page.getByRole('banner').getByRole('search', { name: 'Site search' });
	return { form, field: form.getByRole('searchbox') };
}

test.describe('the single Search workspace', () => {
	test('opens from a catalog page through the global search box', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/namespaces/fields');
		const box = siteSearch(page);
		await expect(box.form).toMatchAriaSnapshot(`
			- search "Site search":
			  - searchbox "Search"
		`);
		await expect(box.field).toHaveAttribute('maxlength', '200');
		await box.field.fill('run');
		await box.field.press('Enter');
		await expect(page).toHaveURL('/search?q=run');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { level: 1, name: 'Search' })).toBeVisible();
		await expect(main.getByRole('combobox', { name: 'Catalog' })).toHaveValue('');
		await expect(siteSearch(page).field).toHaveValue('run');
	});

	test('keeps text typed in the header while skipping to the content', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto('/search?catalog=heliophysics&q=mag');
		await siteSearch(page).field.fill('typed, not sent');
		await page.getByRole('link', { name: 'Skip to content' }).focus();
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL('/search?catalog=heliophysics&q=mag#main');
		await expect(page.getByRole('main')).toBeFocused();
		await expect(siteSearch(page).field).toHaveValue('typed, not sent');
	});

	test('trims header text and uses the remembered organization', async ({ page, context }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/geo');
		await expect
			.poll(async () => (await webCookie(context, COOKIES.organization))?.value)
			.toBe('geo');
		await page.goto('/account');
		const box = siteSearch(page);
		await expect(box.field).toHaveAccessibleName('Search');
		await box.field.fill('  ocean ');
		await box.field.press('Enter');
		await expect(page).toHaveURL('/search?q=ocean');
		await expect(page.getByRole('combobox', { name: 'Organization' })).toHaveValue('geo');
		await expect(
			page.getByRole('main').getByRole('region', { name: 'Geoscience', exact: true })
		).toBeVisible();
		await siteSearch(page).field.fill('   ');
		await siteSearch(page).field.press('Enter');
		await expect(page).toHaveURL('/search');
	});

	test('changes organization on the same Search page and preserves the text', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/search?organization=geo&q=wind');
		const main = page.getByRole('main');
		await main.getByRole('combobox', { name: 'Organization' }).selectOption('helio');
		await main.getByRole('button', { name: 'Choose organization' }).click();
		await expect(page).toHaveURL(
			/\/search\?(?:q=wind&organization=helio|organization=helio&q=wind)$/
		);
		await expect(main.getByRole('region', { name: 'Heliophysics', exact: true })).toBeVisible();
		await expect(main.getByRole('combobox', { name: 'Catalog' })).toHaveValue('');
	});

	test('keeps invalid search fields in the form with an explanation', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto(`/search?organization=helio&q=${'w'.repeat(201)}&label=mission`);
		const main = page.getByRole('main');
		await expect(main.getByText('Use at most 200 characters; this text has 201.')).toBeVisible();
		await expect(
			main.getByText('Write a label filter as key=value, for example mission=ace.')
		).toBeVisible();
		await expect(main.getByRole('searchbox', { name: 'Search text' })).toHaveValue('w'.repeat(201));
	});

	test('keeps a single-organization account on the central page', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto('/search?q=wind&label=mission%3Dwind');
		await expect(page).toHaveURL('/search?q=wind&label=mission%3Dwind');
		await expect(page.getByRole('combobox', { name: 'Organization' })).toHaveValue('helio');
	});

	test('redirects saved catalog and organization search addresses with their filters', async ({
		page
	}) => {
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/search?q=wind&label=mission%3Dwind');
		await expect(page).toHaveURL('/search?catalog=heliophysics&q=wind&label=mission%3Dwind');
		await page.goto('/orgs/helio/search?q=wind');
		await expect(page).toHaveURL('/search?organization=helio&q=wind');
	});

	test('explains why an account without organizations has nothing to search', async ({ page }) => {
		await signIn(page, 'mallory');
		await page.goto('/search?q=wind');
		await expect(page.getByText("You don't have access to any organization yet.")).toBeVisible();
		await expect(page.getByRole('main').getByRole('combobox')).toHaveCount(0);
	});
});

test.describe('on a phone', () => {
	test.use({ viewport: VIEWPORTS.phone });
	test('opens the same Search workspace from the bottom navigation', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/namespaces/fields');
		await expect(siteSearch(page).form).toBeHidden();
		const navigation = page.getByRole('navigation', { name: 'Primary' });
		await expect(navigation.getByRole('link', { name: 'Search' })).toHaveAttribute(
			'href',
			'/search'
		);
		await navigation.getByRole('link', { name: 'Search' }).click();
		await expect(page).toHaveURL('/search');
		await expectMarkedCurrent(
			navigation.getByRole('link', { name: 'Search' }),
			navigation.getByRole('link', { name: 'Catalog', exact: true })
		);
		await expect(page.getByRole('main').getByRole('combobox', { name: 'Catalog' })).toBeVisible();
	});
});
