import { expect, type Locator, type Page } from '@playwright/test';
import { drawnInsideBorder, drawnLines } from './support/cues.ts';
import { searchMatches, titleOf, type FixtureSearch } from './support/fixture.mjs';
import { VIEWPORTS, signIn, test } from './support/harness.ts';

const HELIOPHYSICS = '/catalogs/heliophysics/search';

/** The parts of a catalog's search page. */
function searchPage(page: Page) {
	const main = page.getByRole('main');
	const form = main.getByRole('search', { name: 'Catalog search' });
	const results = main.getByRole('list', { name: 'Results' });
	return {
		main,
		form,
		text: form.getByRole('searchbox', { name: 'Search text' }),
		addLabel: form.getByRole('textbox', { name: 'Add a label filter' }),
		submit: form.getByRole('button', { name: 'Search', exact: true }),
		results,
		// The rows themselves, not the items of the label lists inside them.
		rows: results.locator(':scope > li'),
		exact: main.getByRole('region', { name: 'Exact match' }),
		hint: main.getByRole('region', { name: 'Run this search with the CLI' })
	};
}

/** The titles of the fixture's matches for a search, in the API's order. */
function expectedTitles(catalog: string, search: FixtureSearch): string[] {
	return searchMatches(catalog, search).map(titleOf);
}

/** The title of each row: a heading of its own. */
function titles(rows: Locator): Locator {
	return rows.getByRole('heading', { level: 3 });
}

/** The row of a result by its title. */
function row(rows: Locator, title: string): Locator {
	return rows.filter({ has: rows.page().getByRole('heading', { level: 3, name: title }) });
}

test.describe('the catalog search', () => {
	test('finds the collections whose identifier, title or description holds the text', async ({
		page
	}) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIOPHYSICS}?q=wind`);
		const search = searchPage(page);
		await expect(page).toHaveTitle('“wind” · Search · Heliophysics · Huron');
		await expect(search.text).toHaveValue('wind');
		const expected = expectedTitles('heliophysics', { q: 'wind' });
		expect(expected.length).toBeGreaterThan(1);
		await expect(titles(search.rows)).toHaveText(expected);
		// solar-wind: the identifier holds the text, and the mark shows where, in the text's color.
		const marks = search.rows.first().locator('mark');
		await expect(marks).toHaveText(['wind']);
		expect(
			await marks.evaluate(
				(mark) =>
					getComputedStyle(mark).color === getComputedStyle(mark.parentElement ?? mark).color
			)
		).toBe(true);
		await expect(search.hint.locator('pre code')).toHaveText('huron search heliophysics -q wind');
		// The catalog's sub-navigation marks the page; the explorer the catalog, as its section.
		await expect(
			search.main.getByRole('navigation', { name: 'Catalog' }).getByRole('link', { name: 'Search' })
		).toHaveAttribute('aria-current', 'page');
		await expect(
			page.getByRole('navigation', { name: 'Explorer' }).getByRole('link', { name: 'Heliophysics' })
		).toHaveAttribute('aria-current', 'true');
		// Searching is a section of its own: the shell marks Search, which leads here.
		const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
		await expect(sidebar.getByRole('link', { name: 'Catalogs' })).not.toHaveAttribute(
			'aria-current'
		);
		await expect(sidebar.getByRole('link', { name: 'Search' })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await expect(search.exact).toHaveCount(0);
		// Under the results, the same text and labels in all of the organization.
		await expect(
			search.main
				.getByRole('region', { name: 'Results' })
				.getByRole('link', { name: 'Search all of Heliophysics Division' })
		).toHaveAttribute('href', '/orgs/helio/search?q=wind');
	});

	for (const [key, value] of [
		['mission', 'wind'],
		['level', 'l2']
	] as const) {
		const labels = { [key]: value };
		test(`filters by the label ${key}=${value}`, async ({ page }) => {
			await signIn(page, 'carol');
			await page.goto(`${HELIOPHYSICS}?label=${encodeURIComponent(`${key}=${value}`)}`);
			const search = searchPage(page);
			await expect(titles(search.rows)).toHaveText(expectedTitles('heliophysics', { labels }));
			await expect(
				search.form.getByRole('link', { name: `Remove filter ${key} = ${value}` })
			).toBeVisible();
			// Each row shows the filter as one the search has, not as a link to add it.
			for (const row of await search.rows.all()) {
				const chips = row.getByRole('list', { name: 'Labels' });
				await expect(chips.getByText(`${key}: ${value}`)).toBeVisible();
				await expect(chips.getByRole('link', { name: new RegExp(`^${key}: `) })).toHaveCount(0);
			}
			await expect(search.hint.locator('pre code')).toHaveText(
				`huron search heliophysics -l ${key}=${value}`
			);
		});
	}

	test('combines the text with label filters', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(`${HELIOPHYSICS}?q=ace&label=level%3Dl2`);
		const search = searchPage(page);
		const expected = expectedTitles('heliophysics', { q: 'ace', labels: { level: 'l2' } });
		expect(expected).toHaveLength(1);
		expect(expected.length).toBeLessThan(expectedTitles('heliophysics', { q: 'ace' }).length);
		expect(expected.length).toBeLessThan(
			expectedTitles('heliophysics', { labels: { level: 'l2' } }).length
		);
		await expect(titles(search.rows)).toHaveText(expected);
	});

	test('takes filters away and adds labels from result chips', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIOPHYSICS}?q=wind&label=mission%3Dwind&label=level%3Dl2`);
		const search = searchPage(page);
		await expect(titles(search.rows)).toHaveText(
			expectedTitles('heliophysics', { q: 'wind', labels: { mission: 'wind', level: 'l2' } })
		);
		await search.form.getByRole('link', { name: 'Remove filter level = l2' }).click();
		await expect(page).toHaveURL(`${HELIOPHYSICS}?q=wind&label=mission%3Dwind`);
		const narrowed = expectedTitles('heliophysics', { q: 'wind', labels: { mission: 'wind' } });
		await expect(titles(search.rows)).toHaveText(narrowed);
		// A result's chip adds its label to the search as it is.
		await row(search.rows, 'Wind SWE ion moments, 2023')
			.getByRole('link', { name: 'instrument: swe, add this label to the search' })
			.click();
		await expect(page).toHaveURL(
			`${HELIOPHYSICS}?q=wind&label=mission%3Dwind&label=instrument%3Dswe`
		);
		await expect(titles(search.rows)).toHaveText(
			expectedTitles('heliophysics', {
				q: 'wind',
				labels: { mission: 'wind', instrument: 'swe' }
			})
		);
		await expect(search.form.getByRole('link', { name: /^Remove filter / })).toHaveText([
			'mission = wind',
			'instrument = swe'
		]);
	});

	test("starts from a collection's label chip", async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024');
		await page
			.getByRole('main')
			.getByRole('link', { name: 'mission: ace, search the catalog for this label' })
			.click();
		await expect(page).toHaveURL(`${HELIOPHYSICS}?label=mission%3Dace`);
		const search = searchPage(page);
		await expect(titles(search.rows)).toHaveText(
			expectedTitles('heliophysics', { labels: { mission: 'ace' } })
		);
	});

	test('submits the form at its canonical address', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(HELIOPHYSICS);
		const search = searchPage(page);
		await search.text.fill('  wind ');
		await search.addLabel.fill('mission:wind');
		await search.submit.click();
		// Trimmed, the label as key=value, and the default states left out.
		await expect(page).toHaveURL(`${HELIOPHYSICS}?q=wind&label=mission%3Dwind`);
		await expect(titles(search.rows)).toHaveText(
			expectedTitles('heliophysics', { q: 'wind', labels: { mission: 'wind' } })
		);
		await expect(search.addLabel).toHaveValue('');
		await expect(search.text).toHaveValue('wind');
	});

	test('searches the incomplete collections alone', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto('/catalogs/space-weather/search');
		const search = searchPage(page);
		await search.form.getByRole('checkbox', { name: 'Active' }).uncheck();
		await search.submit.click();
		await expect(page).toHaveURL('/catalogs/space-weather/search?state=incomplete');
		const expected = searchMatches('space-weather', { states: ['incomplete'] });
		// One lacks a field the catalog's schema requires; the other's override no longer fits it.
		expect(expected).toEqual([
			'space-weather.alerts.flare-list-2024',
			'space-weather.alerts.storm-count-2024'
		]);
		await expect(titles(search.rows)).toHaveText(expected.map(titleOf));
		for (const row of await search.rows.all()) await expect(row).toContainText('Incomplete');
		await expect(search.form.getByRole('checkbox', { name: 'Active' })).not.toBeChecked();
		await expect(search.form.getByRole('checkbox', { name: 'Incomplete' })).toBeChecked();
		await expect(search.hint.locator('pre code')).toHaveText(
			'huron search space-weather --state incomplete'
		);
	});

	for (const username of ['dave', 'carol'] as const) {
		test(`shows drafts to ${username}, who may create collections`, async ({ page }) => {
			await signIn(page, username);
			await page.goto(`${HELIOPHYSICS}?state=draft`);
			const search = searchPage(page);
			await expect(search.form.getByRole('checkbox', { name: 'Draft' })).toBeChecked();
			const drafts = searchMatches('heliophysics', { states: ['draft'] });
			expect(drafts).toEqual(['heliophysics.solar-wind.ace.mag-l1-draft']);
			await expect(titles(search.rows)).toHaveText(drafts.map(titleOf));
			await expect(search.rows.first()).toContainText('Draft');
			await expect(search.hint.locator('pre code')).toHaveText(
				'huron search heliophysics --state draft'
			);
		});
	}

	test('never shows erin a draft, nor offers her drafts', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto(`${HELIOPHYSICS}?q=ace&state=draft`);
		const search = searchPage(page);
		await expect(search.form.getByRole('checkbox', { name: 'Draft' })).toHaveCount(0);
		// The address's draft is ignored: the default states, as the form shows.
		await expect(search.form.getByRole('checkbox', { name: 'Active' })).toBeChecked();
		await expect(search.form.getByRole('checkbox', { name: 'Incomplete' })).toBeChecked();
		// The draft's title holds the text too: only the settled collections show.
		const settled = expectedTitles('heliophysics', { q: 'ace' });
		expect(expectedTitles('heliophysics', { q: 'ace', states: ['draft'] })).toEqual([
			'ACE MAG level 1 (draft)'
		]);
		await expect(titles(search.rows)).toHaveText(settled);
		await expect(search.hint.locator('pre code')).toHaveText('huron search heliophysics -q ace');
		// Nor by its identifier: the API conceals it.
		await page.goto(`${HELIOPHYSICS}?q=heliophysics.solar-wind.ace.mag-l1-draft`);
		await expect(search.exact).toHaveCount(0);
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
	});

	test('shows the collection a full identifier names first, and not again', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIOPHYSICS}?q=heliophysics.solar-wind.ace.mag-l2-2024`);
		const search = searchPage(page);
		await expect(search.exact.getByRole('link', { name: 'ACE MAG level 2, 2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		// It is the search's only result, which the list does not repeat.
		expect(searchMatches('heliophysics', { q: 'heliophysics.solar-wind.ace.mag-l2-2024' })).toEqual(
			['heliophysics.solar-wind.ace.mag-l2-2024']
		);
		await expect(search.rows).toHaveCount(0);
		await expect(search.main.getByText('No other collections match this search.')).toBeVisible();
		// Inside the catalog the identifier may leave out the catalog's name, in any case.
		await page.goto(`${HELIOPHYSICS}?q=Solar-Wind.ACE.Mag-L2-2024`);
		await expect(search.exact.getByRole('link', { name: 'ACE MAG level 2, 2024' })).toBeVisible();
		await expect(search.exact.locator('mark')).toHaveText(['solar-wind.ace.mag-l2-2024']);
	});

	test('shows a draft named exactly only when the search includes drafts', async ({ page }) => {
		await signIn(page, 'dave');
		const draft = 'heliophysics.solar-wind.ace.mag-l1-draft';
		await page.goto(`${HELIOPHYSICS}?q=${draft}`);
		const search = searchPage(page);
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
		await expect(search.exact).toHaveCount(0);
		await search.form.getByRole('checkbox', { name: 'Draft' }).check();
		await search.submit.click();
		await expect(page).toHaveURL(
			`${HELIOPHYSICS}?q=${draft}&state=active&state=incomplete&state=draft`
		);
		await expect(search.exact.getByRole('link', { name: 'ACE MAG level 1 (draft)' })).toBeVisible();
		await expect(search.exact).toContainText('Draft');
	});

	test('offers ways out when nothing matches', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(`${HELIOPHYSICS}?q=solar%20storm%20xyz&label=mission%3Dace`);
		const search = searchPage(page);
		expect(
			searchMatches('heliophysics', { q: 'solar storm xyz', labels: { mission: 'ace' } })
		).toEqual([]);
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
		await expect(search.rows).toHaveCount(0);
		const filters = search.main
			.getByRole('list', { name: 'Filters', exact: true })
			.getByRole('link');
		await expect(filters).toHaveText(['“solar storm xyz”', 'mission = ace']);
		await expect(
			search.main.getByRole('list', { name: 'Filters', exact: true }).getByRole('link', {
				name: 'Remove filter mission = ace'
			})
		).toHaveAttribute('href', `${HELIOPHYSICS}?q=solar+storm+xyz`);
		const words = search.main.getByRole('list', { name: 'Words' }).getByRole('link');
		await expect(words).toHaveText(['solar', 'storm', 'xyz']);
		await expect(
			search.main.getByRole('link', { name: 'Search all of Heliophysics Division' })
		).toHaveAttribute('href', '/orgs/helio/search?q=solar+storm+xyz&label=mission%3Dace');
		await words.first().click();
		await expect(page).toHaveURL(`${HELIOPHYSICS}?q=solar&label=mission%3Dace`);
		await expect(titles(search.rows)).toHaveText(
			expectedTitles('heliophysics', { q: 'solar', labels: { mission: 'ace' } })
		);
	});

	test('pages through many results, 25 at a time', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(`${HELIOPHYSICS}?q=run`);
		const search = searchPage(page);
		const all = expectedTitles('heliophysics', { q: 'run' });
		expect(all).toHaveLength(60);
		const pages = search.main.getByRole('navigation', { name: 'Result pages' });
		await expect(titles(search.rows)).toHaveText(all.slice(0, 25));
		await expect(pages.getByRole('link', { name: 'First page' })).toHaveCount(0);
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(page).toHaveURL(/\?q=run&cursor=/);
		await expect(titles(search.rows)).toHaveText(all.slice(25, 50));
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(titles(search.rows)).toHaveText(all.slice(50));
		await expect(pages.getByRole('link', { name: 'Next page' })).toHaveCount(0);
		await pages.getByRole('link', { name: 'First page' }).click();
		await expect(page).toHaveURL(`${HELIOPHYSICS}?q=run`);
		await expect(titles(search.rows)).toHaveText(all.slice(0, 25));
	});

	test('starts again at the first page when a page link expired', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIOPHYSICS}?q=run&cursor=not-a-cursor`);
		await expect(page).toHaveURL(`${HELIOPHYSICS}?q=run&notice=page_expired`);
		const search = searchPage(page);
		await expect(search.main.getByRole('note')).toHaveText(
			'That page link expired; showing the first page.'
		);
		await expect(titles(search.rows)).toHaveText(
			expectedTitles('heliophysics', { q: 'run' }).slice(0, 25)
		);
	});

	test('explains a text longer than the API accepts at its field', async ({ page }) => {
		await signIn(page, 'carol');
		const long = 'w'.repeat(201);
		await page.goto(`${HELIOPHYSICS}?q=${long}`);
		const search = searchPage(page);
		await expect(page).toHaveTitle('Error: Search · Heliophysics · Huron');
		await expect(search.text).toHaveAttribute('aria-invalid', 'true');
		await expect(search.text).toHaveAccessibleDescription(
			/^Use at most 200 characters; this text has 201\./
		);
		await expect(search.results).toHaveCount(0);
		await expect(search.hint).toHaveCount(0);
		// The browser lets no more than 200 be typed.
		await expect(search.text).toHaveAttribute('maxlength', '200');
	});

	test('explains a label filter it cannot read at the field for adding one', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(`${HELIOPHYSICS}?q=wind`);
		const search = searchPage(page);
		await search.addLabel.fill('mission');
		await search.submit.click();
		await expect(search.addLabel).toHaveAttribute('aria-invalid', 'true');
		await expect(search.addLabel).toHaveValue('mission');
		await expect(search.addLabel).toHaveAccessibleDescription(
			'Write a label filter as key=value, for example mission=ace.'
		);
		await expect(search.results).toHaveCount(0);
		await search.addLabel.fill('mission=wind');
		await search.submit.click();
		await expect(page).toHaveURL(`${HELIOPHYSICS}?q=wind&label=mission%3Dwind`);
		await expect(search.addLabel).not.toHaveAttribute('aria-invalid');
	});

	test('explains label filters it will not search for at the field for adding one', async ({
		page
	}) => {
		await signIn(page, 'alice');
		// Longer than a label chip searches for.
		const long = `mission=${'v'.repeat(101)}`;
		await page.goto(`${HELIOPHYSICS}?q=wind&label=${encodeURIComponent(long)}`);
		const search = searchPage(page);
		await expect(page).toHaveTitle('Error: Search · Heliophysics · Huron');
		await expect(search.addLabel).toHaveAttribute('aria-invalid', 'true');
		await expect(search.addLabel).toHaveValue(long);
		await expect(search.addLabel).toHaveAccessibleDescription(
			"Use at most 100 characters in a label filter's key and in its value."
		);
		await expect(search.results).toHaveCount(0);
		// More filters than a search may have: the first ones stay, to search with.
		const labels = Array.from({ length: 11 }, (_, index) => `k${index}=v`);
		await page.goto(
			`${HELIOPHYSICS}?${new URLSearchParams(labels.map((label) => ['label', label]))}`
		);
		await expect(search.addLabel).toHaveAccessibleDescription(
			'Use at most 10 label filters; this search has 11.'
		);
		await expect(search.form.getByRole('link', { name: /^Remove filter / })).toHaveCount(10);
		await expect(search.results).toHaveCount(0);
		await search.submit.click();
		await expect(page).toHaveURL(
			`${HELIOPHYSICS}?${new URLSearchParams(labels.slice(0, 10).map((label) => ['label', label]))}`
		);
		await expect(search.addLabel).not.toHaveAttribute('aria-invalid');
		await expect(search.main.getByText('No collections match this search.')).toBeVisible();
	});

	test("keeps a long filter's text inside its chip on a phone", async ({ page }) => {
		await page.setViewportSize(VIEWPORTS.phone);
		await signIn(page, 'carol');
		const [key, value] = ['k'.repeat(100), 'v'.repeat(100)];
		await page.goto(`${HELIOPHYSICS}?label=${key}%3D${value}`);
		const search = searchPage(page);
		const name = `Remove filter ${key} = ${value}`;
		const chip = search.form.getByRole('link', { name });
		expect((await drawnLines(chip)).length).toBeGreaterThan(2);
		expect(await drawnInsideBorder(chip)).toBe(true);
		// As it is in the list of filters to remove, since nothing has the label.
		const listed = search.main
			.getByRole('list', { name: 'Filters', exact: true })
			.getByRole('link', { name });
		expect((await drawnLines(listed)).length).toBeGreaterThan(2);
		expect(await drawnInsideBorder(listed)).toBe(true);
	});

	test('keeps a label filter with a line break when the form is sent without scripts', async ({
		browser
	}) => {
		const context = await browser.newContext({ javaScriptEnabled: false });
		try {
			const page = await context.newPage();
			await signIn(page, 'bob');
			const query = new URLSearchParams({ q: 'wind', label: 'note=two\nlines' });
			await page.goto(`${HELIOPHYSICS}?${query}`);
			const search = searchPage(page);
			const command = "huron search heliophysics -q wind -l $'note=two\\nlines'";
			await expect(search.hint.locator('pre code')).toHaveText(command);
			await search.submit.click();
			// A browser writes each line break of a field as CR LF, so the form keeps it as JSON.
			await expect(page).toHaveURL(/[?&]label_json=/);
			await expect(search.hint.locator('pre code')).toHaveText(command);
			await expect(
				search.form.getByRole('link', { name: /^Remove filter note = two\slines$/ })
			).toBeVisible();
		} finally {
			await context.close();
		}
	});

	test('copies a command of visible characters only, whatever the address holds', async ({
		page,
		context
	}) => {
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		await signIn(page, 'alice');
		// Pasted as they are, Ctrl-U would erase the line typed so far and a carriage return would
		// run what follows; a right-to-left override would redraw the label backwards.
		const query = new URLSearchParams({ q: 'x\u0015rm -rf ~ #\ry', label: 'note=\u202eevil' });
		await page.goto(`${HELIOPHYSICS}?${query}`);
		const search = searchPage(page);
		const command =
			"huron search heliophysics -q $'x\\025rm -rf ~ #\\ry' -l $'note=\\342\\200\\256evil'";
		await expect(search.hint.locator('pre code')).toHaveText(command);
		await search.hint.getByRole('button', { name: 'Copy: Run this search with the CLI' }).click();
		await expect(search.hint.getByRole('status')).toHaveText('Copied');
		expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(command);
	});

	test('has the form a search needs', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(`${HELIOPHYSICS}?q=wind&label=mission%3Dwind`);
		await expect(searchPage(page).form).toMatchAriaSnapshot(`
			- search "Catalog search":
			  - text: Search text
			  - searchbox "Search text": wind
			  - paragraph: Matches the exact text in identifiers, titles and descriptions. Use labels for exact key=value filters. Sorted by identifier.
			  - group "Labels":
			    - text: Labels
			    - list "Label filters":
			      - listitem:
			        - link "Remove filter mission = wind":
			          - /url: /catalogs/heliophysics/search?q=wind
			          - text: mission = wind
			    - text: Add a label filter
			    - textbox "Add a label filter":
			      - /placeholder: key=value
			  - group "States":
			    - text: States
			    - checkbox "Active" [checked]
			    - text: Active
			    - checkbox "Incomplete" [checked]
			    - text: Incomplete
			    - checkbox "Draft"
			    - text: Draft
			  - button "Search"
		`);
	});

	test('works without scripts', async ({ browser }) => {
		const context = await browser.newContext({ javaScriptEnabled: false });
		try {
			const page = await context.newPage();
			await signIn(page, 'alice');
			await page.goto(HELIOPHYSICS);
			const search = searchPage(page);
			// As the server writes it: Search leads to this very page, which it says.
			await expect(
				page.getByRole('complementary', { name: 'Sidebar' }).getByRole('link', { name: 'Search' })
			).toHaveAttribute('aria-current', 'page');
			await search.text.fill('wind');
			await search.addLabel.fill('level=l2');
			await search.submit.click();
			// The browser's own encoding of the form, which reads as the same search.
			await expect(page).toHaveURL(
				`${HELIOPHYSICS}?q=wind&label=level%3Dl2&state=active&state=incomplete`
			);
			await expect(titles(search.rows)).toHaveText(
				expectedTitles('heliophysics', { q: 'wind', labels: { level: 'l2' } })
			);
			await search.form.getByRole('link', { name: 'Remove filter level = l2' }).click();
			await expect(page).toHaveURL(`${HELIOPHYSICS}?q=wind`);
			await expect(titles(search.rows)).toHaveText(expectedTitles('heliophysics', { q: 'wind' }));
		} finally {
			await context.close();
		}
	});
});
