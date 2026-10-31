import { expect, type Locator, type Page } from '@playwright/test';
import { searchMatches, titleOf } from '../support/fixture.mjs';
import { COOKIES, faults, signIn, test, webCookie } from '../support/harness.ts';

const SEARCH = '/orgs/helio/search?q=2024';

test.afterEach(async () => {
	await faults('oscar', null);
});

/** The section of one catalog's results, named by the catalog. */
function group(page: Page, name: string): Locator {
	return page.getByRole('main').getByRole('region', { name, exact: true });
}

/** The titles of the fixture's matches of `q=2024` in a catalog, in the API's order. */
function titles(catalog: string): string[] {
	return searchMatches(catalog, { q: '2024' }).map(titleOf);
}

/** The titles a group shows: each a heading of its own. */
function shown(section: Locator): Locator {
	return section
		.getByRole('list')
		.first()
		.locator(':scope > li')
		.getByRole('heading', { level: 3 });
}

test.describe("the organization search when a catalog's search fails", () => {
	test('says so under its name, without the API’s words, and shows the others', async ({
		page
	}) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'error500', { path: '/api/v1/catalogs/heliophysics/search' });
		const response = await page.goto(SEARCH);
		expect(response?.status()).toBe(200);
		const failed = group(page, 'Heliophysics');
		await expect(failed).toContainText("Couldn't search this catalog.");
		await expect(failed.getByRole('list')).toHaveCount(0);
		await expect(failed.getByRole('link', { name: 'Search only Heliophysics' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=2024'
		);
		await expect(shown(group(page, 'Space Weather'))).toHaveText(titles('space-weather'));
		await expect(page.getByRole('main')).not.toContainText('fault injected');
		await expect(page.getByText(/^Reference /)).toHaveCount(0);

		// Once the catalog answers again, so does the page.
		await faults('oscar', null);
		await page.reload();
		await expect(shown(group(page, 'Heliophysics'))).toHaveText(titles('heliophysics'));
	});

	test('ends the session when a catalog no longer accepts the token', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'unauthorized', { path: '/api/v1/catalogs/space-weather/search' });
		await page.goto(SEARCH);
		await expect(page).toHaveURL(`/login?status=expired&returnTo=${encodeURIComponent(SEARCH)}`);
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();
	});
});

test.describe('the organization search at its deadline', () => {
	// The page waits for the deadline, 8 seconds.
	test.setTimeout(60_000);

	test('shows what answered in time and counts the catalogs that did not', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'hang', { path: '/api/v1/catalogs/space-weather/search' });
		const started = Date.now();
		await page.goto(SEARCH);
		const waited = Date.now() - started;
		const main = page.getByRole('main');
		await expect(main.getByText('1 catalog did not answer in time.')).toBeVisible();
		expect(waited).toBeGreaterThanOrEqual(8_000);
		await expect(
			main
				.getByRole('list', { name: 'Catalogs that did not answer in time' })
				.getByRole('link', { name: 'Search only Space Weather' })
		).toHaveAttribute('href', '/catalogs/space-weather/search?q=2024');
		await expect(group(page, 'Space Weather')).toHaveCount(0);
		await expect(shown(group(page, 'Heliophysics'))).toHaveText(titles('heliophysics'));
		// The hung request was given up, not answered later: the session and the page live on.
		await faults('oscar', null);
		await page.reload();
		await expect(main.getByText(/did not answer in time/)).toHaveCount(0);
		await expect(shown(group(page, 'Space Weather'))).toHaveText(titles('space-weather'));
	});
});
