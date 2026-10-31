import { expect, type Locator, type Page } from '@playwright/test';
import { expectMarkedCurrent } from './support/cues.ts';
import { CATALOGS, searchMatches, titleOf } from './support/fixture.mjs';
import { organizationSwitcher, signIn, test } from './support/harness.ts';

const HELIO = '/orgs/helio/search';

/** The parts of an organization's search page. */
function searchPage(page: Page) {
	const main = page.getByRole('main');
	const form = main.getByRole('search', { name: 'Organization search' });
	return {
		main,
		form,
		text: form.getByRole('searchbox', { name: 'Search text' }),
		addLabel: form.getByRole('textbox', { name: 'Add a label filter' }),
		submit: form.getByRole('button', { name: 'Search', exact: true }),
		exact: main.getByRole('region', { name: 'Exact match' }),
		/** The section of one catalog's results, named by the catalog. */
		group: (name: string) => main.getByRole('region', { name, exact: true })
	};
}

/** The display name of a fixture catalog. */
function displayNameOf(catalog: string): string {
	const found = CATALOGS.find(({ name }) => name === catalog);
	if (found === undefined) throw new Error(`no fixture catalog ${catalog}`);
	return found.displayName;
}

/** The titles of the results a group shows: each a heading of its own. */
function titles(group: Locator): Locator {
	return group.getByRole('list').first().locator(':scope > li').getByRole('heading', { level: 3 });
}

test.describe('the organization search', () => {
	test("shows each catalog's first five results under its name, with a way to all of them", async ({
		page
	}) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIO}?q=run`);
		const search = searchPage(page);
		await expect(page).toHaveTitle('“run” · Search · Heliophysics Division · Huron');
		await expect(search.text).toHaveValue('run');
		const matches = searchMatches('heliophysics', { q: 'run' });
		expect(matches.length).toBeGreaterThan(5);
		const heliophysics = search.group('Heliophysics');
		await expect(heliophysics.getByRole('heading', { level: 2 })).toHaveText('Heliophysics');
		await expect(
			heliophysics.getByRole('link', { name: 'Heliophysics', exact: true })
		).toHaveAttribute('href', '/catalogs/heliophysics');
		await expect(titles(heliophysics)).toHaveText(matches.slice(0, 5).map(titleOf));
		// The text is marked where it matched.
		await expect(heliophysics.locator('mark').first()).toHaveText(/^run$/i);
		const all = heliophysics.getByRole('link', { name: 'See all results in Heliophysics' });
		await expect(all).toHaveAttribute('href', '/catalogs/heliophysics/search?q=run');
		// Space Weather found nothing, which a line says instead of an empty section.
		expect(searchMatches('space-weather', { q: 'run' })).toEqual([]);
		await expect(search.group('Space Weather')).toHaveCount(0);
		await expect(search.main.getByText('No collections match in Space Weather.')).toBeVisible();
		// Organization search is its own section: the sub-navigation and the sidebar mark it.
		await expect(
			search.main
				.getByRole('navigation', { name: 'Organization' })
				.getByRole('link', { name: 'Search' })
		).toHaveAttribute('aria-current', 'page');
		const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
		await expectMarkedCurrent(
			sidebar.getByRole('link', { name: 'Search' }),
			sidebar.getByRole('link', { name: 'Catalogs' })
		);

		await all.click();
		await expect(page).toHaveURL('/catalogs/heliophysics/search?q=run');
		await expect(
			page.getByRole('main').getByRole('list', { name: 'Results' }).locator(':scope > li')
		).toHaveCount(25);
	});

	test('shows every catalog that found something, each with a link to search it alone', async ({
		page
	}) => {
		await signIn(page, 'carol');
		await page.goto(`${HELIO}?q=2024`);
		const search = searchPage(page);
		for (const catalog of ['heliophysics', 'space-weather']) {
			const matches = searchMatches(catalog, { q: '2024' });
			expect(matches.length).toBeGreaterThan(0);
			expect(matches.length).toBeLessThanOrEqual(5);
			const name = displayNameOf(catalog);
			const group = search.group(name);
			await expect(titles(group)).toHaveText(matches.map(titleOf));
			await expect(group.getByRole('link', { name: `Search only ${name}` })).toHaveAttribute(
				'href',
				`/catalogs/${catalog}/search?q=2024`
			);
		}
		// An incomplete collection says so, as in a catalog's search.
		await expect(
			search
				.group('Space Weather')
				.locator('li')
				.filter({
					has: page.getByRole('heading', { name: titleOf('space-weather.alerts.flare-list-2024') })
				})
		).toContainText('Incomplete');
		// Label chips are text here; a catalog's own search adds them to the search.
		await expect(
			search.group('Heliophysics').getByRole('list', { name: 'Labels' }).first()
		).toBeVisible();
		await expect(
			search.group('Heliophysics').getByRole('list', { name: 'Labels' }).getByRole('link')
		).toHaveCount(0);
	});

	test('shows the collection a full identifier names first, and not again', async ({ page }) => {
		await signIn(page, 'bob');
		const identifier = 'heliophysics.solar-wind.ace.mag-l2-2024';
		await page.goto(`${HELIO}?q=${identifier}`);
		const search = searchPage(page);
		await expect(search.exact.getByRole('link', { name: titleOf(identifier) })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		expect(searchMatches('heliophysics', { q: identifier })).toEqual([identifier]);
		await expect(search.group('Heliophysics')).toHaveCount(0);
		await expect(
			search.main.getByText('No other collections match in Heliophysics and Space Weather.')
		).toBeVisible();
	});

	test("never looks for an identifier of another organization's catalog", async ({ page }) => {
		// dave sees geoscience too, in Earth Science.
		await signIn(page, 'dave');
		const geo = searchMatches('geoscience', { q: 'ocean' });
		expect(geo).toEqual(['geoscience.ocean.sst-2024']);
		await page.goto(`${HELIO}?q=geoscience.ocean.sst-2024`);
		const search = searchPage(page);
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
		await expect(search.exact).toHaveCount(0);
	});

	test('shows drafts to a contributor where the search asks for them', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto(`${HELIO}?state=draft`);
		const search = searchPage(page);
		await expect(search.form.getByRole('checkbox', { name: 'Draft' })).toBeChecked();
		const drafts = searchMatches('heliophysics', { states: ['draft'] });
		expect(drafts).toEqual(['heliophysics.solar-wind.ace.mag-l1-draft']);
		await expect(titles(search.group('Heliophysics'))).toHaveText(drafts.map(titleOf));
		await expect(search.group('Heliophysics')).toContainText('Draft');
		await expect(
			search.group('Heliophysics').getByRole('link', { name: 'Search only Heliophysics' })
		).toHaveAttribute('href', '/catalogs/heliophysics/search?state=draft');
	});

	test('never offers erin drafts, nor shows her one', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto(`${HELIO}?q=ace&state=draft`);
		const search = searchPage(page);
		await expect(search.form.getByRole('checkbox', { name: 'Draft' })).toHaveCount(0);
		await expect(search.form.getByRole('checkbox', { name: 'Active' })).toBeChecked();
		await expect(titles(search.group('Heliophysics'))).toHaveText(
			searchMatches('heliophysics', { q: 'ace' }).slice(0, 5).map(titleOf)
		);
		await expect(
			search.main.getByText(titleOf('heliophysics.solar-wind.ace.mag-l1-draft'))
		).toHaveCount(0);
	});

	test('offers ways out when nothing matches, all within the organization', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(`${HELIO}?q=solar%20storm%20xyz&label=mission%3Dace`);
		const search = searchPage(page);
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
		const filters = search.main.getByRole('list', { name: 'Filters', exact: true });
		await expect(filters.getByRole('link')).toHaveText(['“solar storm xyz”', 'mission = ace']);
		await expect(
			filters.getByRole('link', { name: 'Remove filter mission = ace' })
		).toHaveAttribute('href', `${HELIO}?q=solar+storm+xyz`);
		const words = search.main.getByRole('list', { name: 'Words' }).getByRole('link');
		await expect(words).toHaveText(['solar', 'storm', 'xyz']);
		await expect(search.main.getByRole('link', { name: /^Search all of/ })).toHaveCount(0);
		await words.first().click();
		await expect(page).toHaveURL(`${HELIO}?q=solar&label=mission%3Dace`);
		await expect(titles(search.group('Heliophysics'))).toHaveText(
			searchMatches('heliophysics', { q: 'solar', labels: { mission: 'ace' } }).map(titleOf)
		);
	});

	test("is where a catalog's search that found nothing leads, with its text and labels", async ({
		page
	}) => {
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/search?q=solar%20storm%20xyz&label=mission%3Dace');
		await page
			.getByRole('main')
			.getByRole('link', { name: 'Search all of Heliophysics Division' })
			.click();
		await expect(page).toHaveURL(`${HELIO}?q=solar+storm+xyz&label=mission%3Dace`);
		const search = searchPage(page);
		await expect(search.text).toHaveValue('solar storm xyz');
		await expect(
			search.form.getByRole('link', { name: 'Remove filter mission = ace' })
		).toBeVisible();
	});

	test("is where a catalog's search leads from under its results too", async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/search?q=wind&state=active');
		const results = page.getByRole('main').getByRole('region', { name: 'Results' });
		const found = searchMatches('heliophysics', { q: 'wind', states: ['active'] });
		expect(found.length).toBeGreaterThan(0);
		await expect(results.getByRole('list', { name: 'Results' }).locator(':scope > li')).toHaveCount(
			found.length
		);
		await results.getByRole('link', { name: 'Search all of Heliophysics Division' }).click();
		// The text and labels go along; each catalog decides who sees its drafts, so not the states.
		await expect(page).toHaveURL(`${HELIO}?q=wind`);
		await expect(titles(searchPage(page).group('Heliophysics'))).toHaveText(
			searchMatches('heliophysics', { q: 'wind' }).slice(0, 5).map(titleOf)
		);
	});

	test('submits the form at its canonical address', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(HELIO);
		const search = searchPage(page);
		await expect(
			search.main.getByText(
				'Searches the 2 catalogs of Heliophysics Division that you can see, and shows the first 5 results of each.'
			)
		).toBeVisible();
		await search.text.fill('  wind ');
		await search.addLabel.fill('mission:wind');
		await search.submit.click();
		await expect(page).toHaveURL(`${HELIO}?q=wind&label=mission%3Dwind`);
		await expect(titles(search.group('Heliophysics'))).toHaveText(
			searchMatches('heliophysics', { q: 'wind', labels: { mission: 'wind' } }).map(titleOf)
		);
	});

	test('explains a search it cannot run at its field, and runs none', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIO}?q=${'w'.repeat(201)}`);
		const search = searchPage(page);
		await expect(page).toHaveTitle('Error: Search · Heliophysics Division · Huron');
		await expect(search.text).toHaveAccessibleDescription(
			/^Use at most 200 characters; this text has 201\./
		);
		await expect(search.main.getByRole('region')).toHaveCount(0);
		await expect(search.main.getByText(/collections match/)).toHaveCount(0);
	});

	test('keeps the search when switching organizations, but not a cursor', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto(`${HELIO}?q=wind&cursor=c2`);
		await expect(searchPage(page).text).toHaveValue('wind');
		const switcher = organizationSwitcher(page);
		await switcher.summary.click();
		const geo = switcher.panel.getByRole('link', { name: 'Earth Science geo' });
		await expect(geo).toHaveAttribute('href', '/orgs/geo/search?q=wind');
		await geo.click();
		await expect(page).toHaveURL('/orgs/geo/search?q=wind');
		const search = searchPage(page);
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
		await expect(search.text).toHaveValue('wind');
		expect(searchMatches('geoscience', { q: 'wind' })).toEqual([]);
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
		await expect(page.getByRole('banner').getByRole('searchbox')).toHaveValue('wind');
	});

	test('conceals an organization the user cannot see as not found', async ({ page }) => {
		await signIn(page, 'erin');
		const visible = await page.goto(`${HELIO}?q=wind`);
		expect(visible?.status()).toBe(200);
		const concealed = await page.goto('/orgs/astro/search?q=wind');
		expect(concealed?.status()).toBe(404);
		await expect(page.getByRole('banner')).toBeVisible();
		await expect(page.getByRole('main').getByRole('heading', { level: 1 })).toHaveText(
			"Not found, or you don't have access."
		);
	});

	test("is a section of the organization's pages", async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto('/orgs/helio');
		const sections = page.getByRole('main').getByRole('navigation', { name: 'Organization' });
		await expect(sections).toMatchAriaSnapshot(`
			- navigation "Organization":
			  - link "Catalogs 2":
			    - /url: /orgs/helio
			  - link "Search":
			    - /url: /orgs/helio/search
		`);
		await sections.getByRole('link', { name: 'Search' }).click();
		await expect(page).toHaveURL(HELIO);
		await expect(page).toHaveTitle('Search · Heliophysics Division · Huron');
		await expect(sections.getByRole('link', { name: 'Search' })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await expect(sections.getByRole('link', { name: /^Catalogs/ })).not.toHaveAttribute(
			'aria-current'
		);
	});

	test('works without scripts', async ({ browser }) => {
		const context = await browser.newContext({ javaScriptEnabled: false });
		try {
			const page = await context.newPage();
			await signIn(page, 'bob');
			await page.goto(HELIO);
			const search = searchPage(page);
			// As the server writes it: Search leads to this very page, which it says.
			const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
			await expect(sidebar.getByRole('link', { name: 'Search' })).toHaveAttribute(
				'aria-current',
				'page'
			);
			await expect(sidebar.getByRole('link', { name: 'Catalogs' })).not.toHaveAttribute(
				'aria-current'
			);
			await search.text.fill('wind');
			await search.submit.click();
			await expect(page).toHaveURL(`${HELIO}?q=wind&label=&state=active&state=incomplete`);
			await expect(titles(search.group('Heliophysics'))).toHaveText(
				searchMatches('heliophysics', { q: 'wind' }).slice(0, 5).map(titleOf)
			);
			await expect(sidebar.getByRole('link', { name: 'Search' })).toHaveAttribute(
				'aria-current',
				'page'
			);
		} finally {
			await context.close();
		}
	});
});
