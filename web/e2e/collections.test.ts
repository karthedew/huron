import { expect, type Locator, type Page } from '@playwright/test';
import { drawnLines, expectMarkedCurrent } from './support/cues.ts';
import {
	COLLECTIONS,
	MOUNT_PREFIX,
	RUN001_FILE_COUNT,
	collection,
	collectionIdentifier,
	fileSha256,
	recordedFiles,
	titleOf,
	type Username
} from './support/fixture.mjs';
import {
	ApiSession,
	VIEWPORTS,
	horizontalOverflow,
	logOut,
	signIn,
	test
} from './support/harness.ts';

/*
 * Checks that do not depend on the role sign in as users other tests seldom use: the web keeps
 * at most 10 sessions per user and ends the oldest, so a burst of parallel sign-ins as one user
 * could end the session of a test still running.
 */

const MAG = 'heliophysics.solar-wind.ace.mag-l2-2024';
const DRAFT = 'heliophysics.solar-wind.ace.mag-l1-draft';
const FLARES = 'space-weather.alerts.flare-list-2024';
const STORMS = 'space-weather.alerts.storm-count-2024';
const RUN001 = 'heliophysics.fields.run001';
const SWE = 'heliophysics.solar-wind.wind.swe-2023';
const LEAF = 'heliophysics.deep.a.b.c.leaf';

/** The address of a collection's page, by its full identifier: `/catalogs/<catalog>/collections/<rest>`. */
function collectionPath(identifier: string, tab = ''): string {
	const [catalog, ...rest] = identifier.split('.');
	return `/catalogs/${catalog}/collections/${rest.join('.')}${tab}`;
}

/** The value a definition list gives for a term, inside `scope`. */
function definition(scope: Locator, term: string): Locator {
	return scope.locator(`xpath=.//dt[normalize-space()="${term}"]/following-sibling::dd[1]`);
}

function main(page: Page): Locator {
	return page.getByRole('main');
}

function metadata(page: Page): Locator {
	return main(page).getByRole('region', { name: 'Metadata' });
}

function details(page: Page): Locator {
	return main(page).getByRole('complementary', { name: 'Details' });
}

function tabs(page: Page): Locator {
	return main(page).getByRole('navigation', { name: 'Collection' });
}

/** A field of the API's own answer for a collection, as some user sees it. */
async function apiCollection(username: Username, identifier: string) {
	const [catalog, ...rest] = identifier.split('.');
	const { status, body } = await (
		await ApiSession.as(username)
	).get(`catalogs/${catalog}/collections/${rest.join('.')}`);
	return { status, body: typeof body === 'object' && body !== null ? body : {} };
}

test.describe('an active collection', () => {
	test('heads its pages with its title, identifier, state and description', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(collectionPath(MAG));
		await expect(page).toHaveTitle(`${titleOf(MAG)} · Heliophysics · Huron`);
		const header = main(page).locator('header');
		await expect(header.getByRole('heading', { level: 1 })).toHaveText(titleOf(MAG));
		await expect(header.getByText(MAG, { exact: true })).toBeVisible();
		await expect(header.getByText('Active', { exact: true })).toBeVisible();
		await expect(header).toContainText(String(collection(MAG).metadata.description));
		await expect(tabs(page).getByRole('link')).toHaveText([
			'Overview',
			`Files${recordedFiles(collection(MAG)).length}`,
			'Commits',
			'Activity',
			'Schema'
		]);
		await expect(tabs(page).getByRole('link', { name: 'Overview' })).toHaveAttribute(
			'aria-current',
			'page'
		);
		const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link');
		await expect(crumbs).toHaveText([
			'Heliophysics Division',
			'Heliophysics',
			'solar-wind',
			'ace',
			'mag-l2-2024'
		]);
		await expect(crumbs.last()).toHaveAttribute('aria-current', 'page');
		await expect(crumbs.last()).toHaveAttribute('href', collectionPath(MAG));
	});

	test('shows its metadata against the catalog schema', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(collectionPath(MAG));
		const fields = metadata(page);
		await expect(fields.locator('xpath=./dl/div/dt')).toHaveText([
			'Contacts',
			'End time',
			'Instrument',
			'Keywords',
			'Labels',
			'Start time'
		]);
		const start = definition(fields, 'Start time').locator('time');
		await expect(start).toHaveText('2024-01-01 00:00 UTC');
		await expect(start).toHaveAttribute('datetime', '2024-01-01T00:00:00.000Z');
		await expect(definition(fields, 'End time')).toHaveText('2024-12-31 23:59 UTC');
		const keywords = definition(fields, 'Keywords');
		await expect(keywords.getByRole('listitem')).toHaveText(['magnetic field', 'solar wind', 'L1']);
		await expect(keywords.getByRole('link')).toHaveCount(0);
		const contacts = definition(fields, 'Contacts').getByRole('listitem');
		await expect(contacts).toHaveCount(2);
		await expect(
			contacts.first().getByRole('link', { name: 'ace-mag@example.org' })
		).toHaveAttribute('href', 'mailto:ace-mag@example.org');
		await expect(contacts.last()).toContainText('Science data center');
		await expect(contacts.last().getByRole('link')).toHaveCount(0);
		const labels = definition(fields, 'Labels').getByRole('link');
		await expect(labels).toHaveText(['instrument: mag', 'level: l2', 'mission: ace']);
		await expect(labels.last()).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?label=mission%3Dace'
		);
		// The name starts with what the chip shows and says that it searches.
		await expect(labels.last()).toHaveAccessibleName(
			'mission: ace, search the catalog for this label'
		);
		await expect(main(page).getByRole('region', { name: /problems? in the metadata/ })).toHaveCount(
			0
		);
	});

	test('gives its details: share path, files, times, metadata file and record revision', async ({
		page,
		context
	}) => {
		const { body } = await apiCollection('erin', MAG);
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		await signIn(page, 'bob');
		await page.goto(collectionPath(MAG));
		const aside = details(page);
		const share = `${MOUNT_PREFIX}/helio/heliophysics/solar-wind/ace/mag-l2-2024`;
		await expect(definition(aside, 'Share path')).toContainText(share);
		await aside.getByRole('button', { name: 'Copy share path' }).click();
		// The aside's own status; the explorer, also in main, has one for its folders.
		await expect(definition(aside, 'Share path').getByRole('status')).toHaveText('Copied');
		expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(share);
		await expect(definition(aside, 'Files').getByRole('link')).toHaveText('3 files');
		await expect(definition(aside, 'Created')).toContainText('by dave');
		await expect(definition(aside, 'Activated').locator('time')).toHaveText(
			/^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$/
		);
		await expect(definition(aside, 'Schema').getByRole('link')).toHaveText('huron-base v1');
		await expect(
			definition(aside, 'Metadata file').getByRole('link', { name: 'metadata.json' })
		).toHaveAttribute('href', collectionPath(MAG, '/metadata.json'));
		await aside.getByText('Technical details').click();
		const version = 'version' in body ? String(body.version) : '';
		await expect(aside).toContainText(`Record revision ${version}`);
		await expect(aside).toContainText('id' in body ? String(body.id) : 'no id');
	});

	test('lists its files in a scroll region with their sizes, hashes and recording', async ({
		page
	}) => {
		await signIn(page, 'alice');
		await page.goto(collectionPath(MAG, '/files'));
		await expect(page).toHaveTitle(`Files · ${titleOf(MAG)} · Huron`);
		await expect(tabs(page).getByRole('link', { name: /^Files/ })).toHaveAttribute(
			'aria-current',
			'page'
		);
		const files = recordedFiles(collection(MAG));
		await expect(
			main(page).getByText(`${files.length} files recorded, sorted by path.`)
		).toBeVisible();
		const region = main(page).getByRole('region', { name: `Files of ${titleOf(MAG)}` });
		await expect(region).toHaveAttribute('tabindex', '0');
		const paths = region.getByRole('rowheader');
		await expect(paths).toHaveText([
			'data/ace_mag_l2_2024-01.cdf',
			'data/ace_mag_l2_2024-02.cdf',
			'RELEASE_NOTES.md'
		]);
		const first = region
			.getByRole('row')
			.filter({ has: page.getByRole('rowheader', { name: 'data/ace_mag_l2_2024-01.cdf' }) });
		const size = first.locator('data');
		await expect(size).toHaveText('48.2 MB');
		await expect(size).toHaveAttribute('value', '48234496');
		await expect(size).toHaveAttribute('title', '48,234,496 bytes');
		const hash = fileSha256(MAG, 'data/ace_mag_l2_2024-01.cdf');
		await expect(first.locator('summary')).toHaveText(`${hash.slice(0, 12)}…`);
		await first.locator('summary').click();
		await expect(first.locator('details')).toContainText(hash);
		await expect(first).toContainText('by dave');
	});

	test('keeps paths whole and columns still, and fits beside the explorer', async ({ page }) => {
		await signIn(page, 'carol');
		const region = main(page).getByRole('region', { name: `Files of ${titleOf(MAG)}` });
		const columns = () =>
			region
				.locator('thead th')
				.evaluateAll((cells) => cells.map((cell) => cell.getBoundingClientRect().width));
		for (const width of [390, 816, 1024, 1440]) {
			await page.setViewportSize({ width, height: 900 });
			await page.goto(collectionPath(MAG, '/files'));
			for (const { relPath } of recordedFiles(collection(MAG))) {
				const path = region.getByRole('rowheader', { name: relPath, exact: true });
				expect(await drawnLines(path), `${relPath} at ${width}px`).toEqual([relPath]);
			}
			// On a phone the region scrolls; from 816px, also beside the explorer, it has no need to.
			if (width >= 816) {
				const sideways = await region.evaluate(
					(element) => element.scrollWidth - element.clientWidth
				);
				expect(sideways, `sideways scroll at ${width}px`).toBe(0);
			}
			const closed = await columns();
			await region.locator('summary').first().click();
			await expect(region.locator('details').first()).toHaveAttribute('open');
			expect(await columns(), `columns at ${width}px`).toEqual(closed);
		}
	});

	test('lists its commits, newest first, with what each changed', async ({ page }) => {
		const { body } = await apiCollection('erin', MAG);
		const id = 'id' in body ? String(body.id) : '';
		const commits = await (await ApiSession.as('erin')).get(`collections/${id}/commits`);
		const items =
			typeof commits.body === 'object' && commits.body !== null && 'items' in commits.body
				? commits.body.items
				: [];
		const latestId =
			Array.isArray(items) && typeof items[0] === 'object' && items[0] !== null && 'id' in items[0]
				? String(items[0].id)
				: '';
		await signIn(page, 'carol');
		await page.goto(collectionPath(MAG, '/commits'));
		const list = main(page)
			.getByRole('list', { name: `Commits of ${titleOf(MAG)}` })
			.getByRole('listitem');
		await expect(list).toHaveCount(2);
		const [initial, replace] = collection(MAG).commits;
		await expect(list.first()).toContainText(String(replace.message));
		await expect(list.first()).toContainText('+1 / −1');
		await expect(list.first()).toContainText('revision 3 → 4');
		await expect(list.first()).toContainText(`from ${replace.host}`);
		await expect(list.first()).toContainText('by dave');
		await expect(list.last()).toContainText(String(initial.message));
		await expect(list.last()).toContainText('+3 / −0');
		await expect(list.last()).toContainText('revision 2 → 3');
		const short = list.first().getByText(latestId.replaceAll('-', '').slice(-12), { exact: true });
		await expect(short).toHaveAttribute('title', latestId);
	});

	test('lists what happened to it, without links back to itself', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(collectionPath(MAG, '/activity'));
		const entries = main(page)
			.getByRole('list', { name: 'Collection activity' })
			.getByRole('listitem');
		await expect(entries).toHaveCount(4);
		await expect(entries.nth(0)).toContainText('Committed files');
		await expect(entries.nth(0)).toContainText('1 added, 1 removed');
		await expect(entries.nth(2)).toContainText('Activated (revision 2)');
		await expect(entries.nth(3)).toContainText('Created a collection');
		await expect(entries.getByRole('link')).toHaveCount(0);
	});

	test("shows its catalog's schema when it has no override", async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(collectionPath(MAG, '/schema'));
		await expect(main(page).getByRole('heading', { level: 2, name: /^Schema/ })).toHaveText(
			'Schema huron-base v1'
		);
		await expect(main(page).getByText('Huron base metadata', { exact: true })).toBeVisible();
		await expect(
			main(page)
				.getByRole('table', { name: "Fields of the collection's schema" })
				.getByRole('rowheader')
				.first()
		).toHaveText(/^Title/);
		await expect(main(page).getByRole('heading', { name: 'Schema override' })).toHaveCount(0);
	});

	test('serves its metadata.json as it is, inline and sandboxed', async ({ page }) => {
		await signIn(page, 'carol');
		const response = await page.request.get(collectionPath(MAG, '/metadata.json'));
		expect(response.status()).toBe(200);
		expect(response.headers()).toMatchObject({
			'content-type': 'application/json',
			'content-disposition': 'inline',
			'content-security-policy': "default-src 'none'; sandbox",
			'cache-control': 'private, no-store',
			'x-content-type-options': 'nosniff'
		});
		const sidecar: unknown = await response.json();
		expect(sidecar).toMatchObject({
			huron: 1,
			identifier: MAG,
			organization: 'helio',
			catalog: 'heliophysics',
			schema: { name: 'huron-base', version: 1 },
			metadata: collection(MAG).metadata,
			created_by: 'dave'
		});
		expect((await response.text()).endsWith('\n')).toBe(true);
	});
});

test.describe('a draft', () => {
	test('answers its metadata.json with a page of its own that fits a phone', async ({ page }) => {
		// An endpoint's error is the static page, `src/error.html`, without the shell.
		await page.setViewportSize(VIEWPORTS.phone);
		await signIn(page, 'bob');
		const response = await page.goto(collectionPath(DRAFT, '/metadata.json'));
		expect(response?.status()).toBe(404);
		await expect(
			page.getByRole('heading', { name: "Huron can't show this page (404)", level: 1 })
		).toBeVisible();
		expect(await horizontalOverflow(page)).toBe(0);
		const card = await page.getByRole('main').boundingBox();
		expect(card !== null && card.x >= 0 && card.x + card.width <= VIEWPORTS.phone.width).toBe(true);
	});

	test('is not found for a reader, inside its catalog', async ({ page }) => {
		expect((await apiCollection('erin', DRAFT)).status).toBe(404);
		await signIn(page, 'erin');
		const response = await page.goto(collectionPath(DRAFT));
		expect(response?.status()).toBe(404);
		await expect(main(page).getByRole('heading', { level: 1 })).toHaveText(
			"Not found, or you don't have access."
		);
		await expect(
			main(page).getByRole('link', { name: 'Back to Heliophysics Division' })
		).toHaveAttribute('href', '/orgs/helio');
		const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link');
		await expect(crumbs).toHaveText(['Heliophysics Division', 'Heliophysics']);
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		await expect(tree.getByRole('link', { name: 'mag-l1-draft' })).toHaveCount(0);
		expect((await page.request.get(collectionPath(DRAFT, '/metadata.json'))).status()).toBe(404);
	});

	for (const username of ['dave', 'carol'] satisfies Username[]) {
		test(`shows ${username} what it lacks and how to activate it`, async ({ page }) => {
			await signIn(page, username);
			await page.goto(collectionPath(DRAFT));
			const header = main(page).locator('header');
			await expect(header.getByRole('heading', { level: 1 })).toHaveText(titleOf(DRAFT));
			await expect(header.getByText('Draft', { exact: true })).toBeVisible();
			await expect(header).toContainText(
				'Reserved, not yet activated: no directory or files on the share; visible to contributors only.'
			);
			await expect(tabs(page).getByRole('link', { name: 'Files' })).toHaveText('Files');
			const problems = main(page).getByRole('region', { name: '1 problem in the metadata' });
			await expect(problems).toContainText("'description' is a required property");
			await expect(definition(metadata(page), 'Description')).toHaveText('Missing');
			await expect(definition(details(page), 'Share path')).toHaveText('No directory yet');
			await expect(details(page).getByRole('link', { name: 'metadata.json' })).toHaveCount(0);
			await expect(definition(details(page), 'Files')).toHaveCount(0);
			const activate = main(page).getByRole('region', { name: 'Activate this draft' });
			await expect(activate.locator('pre')).toHaveText(
				`huron --catalog heliophysics collection activate ${DRAFT}`
			);
			await expect(
				main(page).getByRole('region', { name: 'Add files to this collection' })
			).toHaveCount(0);
		});
	}

	test('explains on its files and commits tabs that it has none yet', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto(collectionPath(DRAFT, '/files'));
		await expect(main(page).getByText(/A draft has no directory on the share/)).toBeVisible();
		await expect(main(page).getByRole('table')).toHaveCount(0);
		await page.goto(collectionPath(DRAFT, '/commits'));
		await expect(main(page).getByText(/nothing has been committed to it yet/)).toBeVisible();
		expect((await page.request.get(collectionPath(DRAFT, '/metadata.json'))).status()).toBe(404);
	});
});

test.describe('an incomplete collection', () => {
	test('names what the schema now requires and marks it missing', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto(collectionPath(FLARES));
		const header = main(page).locator('header');
		await expect(header.getByText('Incomplete', { exact: true })).toBeVisible();
		await expect(header).toContainText(
			"The catalog's schema now requires fields this collection lacks. Its files are unaffected."
		);
		const problems = main(page).getByRole('region', { name: '1 problem in the metadata' });
		await expect(problems.getByRole('listitem')).toHaveText(["'mission' is a required property"]);
		await expect(definition(metadata(page), 'Mission')).toHaveText('Missing');
		await expect(details(page).getByRole('link', { name: 'metadata.json' })).toBeVisible();
		await expect(definition(details(page), 'Schema')).toHaveText('space-weather v1');
		await expect(main(page).getByRole('region', { name: /^Complete the metadata/ })).toHaveCount(0);
	});

	test('shows contributors how to edit and publish its metadata', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto(collectionPath(FLARES));
		const hint = main(page).getByRole('region', { name: 'Complete the metadata, then publish it' });
		await expect(hint.locator('pre')).toHaveText(
			`huron --catalog space-weather meta edit ${FLARES}\n` +
				`huron --catalog space-weather meta publish ${FLARES}`
		);
		await expect(
			main(page).getByRole('region', { name: 'Add files to this collection' })
		).toBeVisible();
	});
});

test.describe('a collection whose schema override no longer fits', () => {
	// The space-weather schema, assigned after its activation, types mission as text.
	test('says so, shows its fields by their keys, and gives a reader its checkout', async ({
		page
	}) => {
		await signIn(page, 'erin');
		await page.goto(collectionPath(STORMS));
		const header = main(page).locator('header');
		await expect(header.getByText('Incomplete', { exact: true })).toBeVisible();
		await expect(header).toContainText(
			"Its schema override no longer fits the catalog's schema. Its files are unaffected."
		);
		await expect(header).not.toContainText("The catalog's schema now requires fields");
		const problems = main(page).getByRole('region', { name: '1 problem with the schema override' });
		await expect(problems).toContainText(
			'The collection is active again once its schema override is fixed or removed and its metadata is valid.'
		);
		await expect(problems.getByRole('listitem')).toHaveCount(1);
		await expect(metadata(page)).toContainText(
			"Its schema override no longer fits the catalog's schema, so the fields show by their keys."
		);
		await expect(definition(metadata(page), 'Mission')).toHaveText('7');
		await expect(
			main(page).getByRole('region', { name: 'With the CLI' }).getByRole('region')
		).toHaveCount(1);
		await expect(
			main(page).getByRole('region', { name: 'Check out this collection' }).locator('pre')
		).toHaveText(`huron --catalog space-weather checkout ${STORMS}`);
	});

	test('shows a contributor how to replace or remove the override, not to edit the metadata', async ({
		page
	}) => {
		await signIn(page, 'dave');
		await page.goto(collectionPath(STORMS));
		await expect(
			main(page)
				.getByRole('region', { name: 'Replace the schema override with one that fits' })
				.locator('pre')
		).toHaveText(`huron --catalog space-weather meta override set <override.json> ${STORMS}`);
		await expect(
			main(page).getByRole('region', { name: 'Remove the schema override' }).locator('pre')
		).toHaveText(`huron --catalog space-weather meta override clear ${STORMS}`);
		await expect(
			main(page).getByRole('region', { name: 'Complete the metadata, then publish it' })
		).toHaveCount(0);
		await expect(
			main(page).getByRole('region', { name: 'Add files to this collection' })
		).toBeVisible();
	});

	test('shows its override alone on the Schema tab, and why there is no composed schema', async ({
		page
	}) => {
		await signIn(page, 'carol');
		await page.goto(collectionPath(STORMS, '/schema'));
		await expect(
			main(page).getByText(
				"The override below no longer fits the catalog's schema, so there is no composed schema to show until the override changes."
			)
		).toBeVisible();
		await expect(
			main(page).getByRole('table', { name: "Fields of the collection's schema" })
		).toHaveCount(0);
		const override = main(page).getByRole('region', { name: 'Schema override', exact: true });
		await expect(
			override.getByRole('table', { name: 'Fields of the schema override' }).getByRole('rowheader')
		).toHaveText([/^Network number/]);
		await expect(override.getByText('Storm count additions', { exact: true })).toBeVisible();
	});
});

test.describe('the hints of a collection', () => {
	test('show a reader the share path and how to check it out, and a contributor how to push', async ({
		page
	}) => {
		const regions = (page: Page) =>
			main(page).getByRole('region', { name: 'With the CLI' }).getByRole('region');
		await signIn(page, 'erin');
		await page.goto(collectionPath(MAG));
		await expect(definition(details(page), 'Share path')).toContainText(
			`${MOUNT_PREFIX}/helio/heliophysics/solar-wind/ace/mag-l2-2024`
		);
		await expect(regions(page)).toHaveCount(1);
		await expect(
			main(page).getByRole('region', { name: 'Check out this collection' }).locator('pre')
		).toHaveText(`huron --catalog heliophysics checkout ${MAG}`);

		await logOut(page);
		await signIn(page, 'dave');
		await page.goto(collectionPath(MAG));
		await expect(regions(page)).toHaveCount(2);
		// `add` and `push` act on the collection checked out last, so the hint checks this one out.
		await expect(
			main(page).getByRole('region', { name: 'Add files to this collection' }).locator('pre')
		).toHaveText(
			`huron --catalog heliophysics checkout ${MAG}\n` +
				'huron --catalog heliophysics add <file>…\n' +
				'huron --catalog heliophysics push -m "<message>"'
		);
		await page.goto(collectionPath(LEAF, '/files'));
		await expect(main(page).getByText('No files yet.')).toBeVisible();
		await expect(
			main(page).getByRole('region', { name: 'Add files to this collection' }).locator('pre')
		).toHaveText(
			`huron --catalog heliophysics checkout ${LEAF}\n` +
				'huron --catalog heliophysics add <file>…\n' +
				'huron --catalog heliophysics push -m "<message>"'
		);
	});
});

test.describe('a collection of many files', () => {
	test('pages its files 50 at a time', async ({ page }) => {
		// Without smooth scrolling no click waits for the page to settle: a long test holds its
		// session longer, and the web keeps only so many sessions per user.
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await signIn(page, 'bob');
		await page.goto(collectionPath(RUN001, '/files'));
		await expect(
			main(page).getByText(`${RUN001_FILE_COUNT} files recorded, sorted by path.`)
		).toBeVisible();
		const region = main(page).getByRole('region', { name: `Files of ${titleOf(RUN001)}` });
		const rows = region.getByRole('rowheader');
		const pages = main(page).getByRole('navigation', { name: 'File pages' });
		await expect(rows).toHaveCount(50);
		await expect(rows.first()).toHaveText('frames/frame-0001.dat');
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(page).toHaveURL(/\/collections\/fields\.run001\/files\?cursor=/);
		await expect(rows.first()).toHaveText('frames/frame-0051.dat');
		await expect(rows).toHaveCount(50);
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(rows).toHaveCount(RUN001_FILE_COUNT - 100);
		await expect(rows.last()).toHaveText(`frames/frame-0${RUN001_FILE_COUNT}.dat`);
		await expect(pages.getByRole('link', { name: 'Next page' })).toHaveCount(0);
		await pages.getByRole('link', { name: 'First page' }).click();
		await expect(page).toHaveURL(collectionPath(RUN001, '/files'));
		await expect(rows.first()).toHaveText('frames/frame-0001.dat');
	});

	test('starts its files over when a page link expired, and says so', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(collectionPath(RUN001, '/files?cursor=not-a-cursor'));
		await expect(page).toHaveURL(collectionPath(RUN001, '/files?notice=page_expired'));
		await expect(main(page).getByRole('note')).toHaveText(
			'That page link expired; showing the first page.'
		);
		await expect(
			main(page)
				.getByRole('region', { name: `Files of ${titleOf(RUN001)}` })
				.getByRole('rowheader')
		).toHaveCount(50);
	});

	test('says its commit has no message', async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(collectionPath(RUN001, '/commits'));
		const commit = main(page)
			.getByRole('list', { name: `Commits of ${titleOf(RUN001)}` })
			.getByRole('listitem');
		await expect(commit).toHaveCount(1);
		await expect(commit).toContainText('No message');
		await expect(commit).toContainText(`+${RUN001_FILE_COUNT} / −0`);
	});

	test('is pinned in the explorer where it lies beyond the first page of its namespace', async ({
		page
	}) => {
		const later = COLLECTIONS.filter(({ namespace }) => namespace === 'fields')[54];
		await signIn(page, 'bob');
		await page.goto(collectionPath(collectionIdentifier(later)));
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		const fields = tree
			.getByRole('listitem')
			.filter({ has: page.getByRole('button', { name: 'Contents of fields' }) })
			.last();
		const links = fields.getByRole('list').first().getByRole('link');
		// The first page of 50, More…, then the current collection.
		await expect(links).toHaveCount(52);
		await expect(links.nth(50)).toHaveText('More…');
		await expect(links.nth(51)).toHaveText(later.name);
		await expect(links.nth(51)).toHaveAttribute('aria-current', 'page');
		await expectMarkedCurrent(links.nth(51), links.nth(0));
	});
});

test.describe('a deep collection', () => {
	test('shows the way down to it in the breadcrumbs and the explorer', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(collectionPath(LEAF));
		await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link')).toHaveText(
			['Heliophysics Division', 'Heliophysics', 'deep', 'a', 'b', 'c', 'leaf']
		);
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		for (const name of ['deep', 'a', 'b', 'c']) {
			await expect(tree.getByRole('button', { name: `Contents of ${name}` })).toHaveAttribute(
				'aria-expanded',
				'true'
			);
		}
		await expect(tree.getByRole('link', { name: 'leaf' })).toHaveAttribute('aria-current', 'page');
		await expect(metadata(page)).toContainText('Nothing beyond the title and description.');
	});

	test("marks its section, not the page, on the collection's other tabs", async ({ page }) => {
		await signIn(page, 'carol');
		await page.goto(collectionPath(LEAF, '/commits'));
		await expect(main(page).getByText('No commits yet.')).toBeVisible();
		await expect(
			page.getByRole('navigation', { name: 'Explorer' }).getByRole('link', { name: 'leaf' })
		).toHaveAttribute('aria-current', 'true');
		await expect(
			page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'leaf' })
		).not.toHaveAttribute('aria-current');
		await page.goto(collectionPath(LEAF, '/files'));
		await expect(main(page).getByText('No files yet.')).toBeVisible();
	});
});

test.describe('a collection with every kind of value', () => {
	test('shows each value as its schema override describes it', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(collectionPath(SWE));
		const fields = metadata(page);
		await expect(definition(fields, 'Release date').locator('time')).toHaveAttribute(
			'datetime',
			'2024-03-15'
		);
		const landing = definition(fields, 'Landing page').getByRole('link');
		await expect(landing).toHaveAttribute('href', 'https://data.example.org/wind/swe/2023/');
		await expect(landing).toHaveAttribute('rel', 'noopener noreferrer');
		await expect(definition(fields, 'Mirror')).toHaveText(
			'ftp://ftp.example.org/pub/wind/swe/2023/'
		);
		await expect(definition(fields, 'Mirror').getByRole('link')).toHaveCount(0);
		await expect(definition(fields, 'Cadence (s)')).toHaveText('92');
		await expect(definition(fields, 'Fill value')).toHaveText('-9999.5');
		await expect(definition(fields, 'Calibrated')).toHaveText('Yes');
		await expect(definition(fields, 'Energy bands (eV)').getByRole('listitem')).toHaveText([
			'150',
			'300',
			'600',
			'1200'
		]);
		const processing = definition(fields, 'Processing');
		await expect(definition(processing, 'Level')).toHaveText('L2');
		await expect(definition(processing, 'Reprocessed')).toHaveText('No');
		await expect(fields.getByRole('heading', { name: 'Other fields', level: 3 })).toBeVisible();
		await expect(definition(fields, 'Archive note')).toContainText('See the release notes.');
		await expect(definition(details(page), 'Schema')).toHaveText('huron-base v1 with an override');
	});

	test('shows numbers exactly, however small or large', async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto(collectionPath(SWE));
		const calibration = definition(metadata(page), 'Calibration');
		await expect(definition(calibration, 'Proton mass kg')).toHaveText('1.67262192e-27');
		await expect(definition(calibration, 'Cdf fill value')).toHaveText('-1e+31');
	});

	test('shows its schema override apart from the schema it composes', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto(collectionPath(SWE, '/schema'));
		await expect(main(page).getByRole('heading', { level: 2, name: /^Schema huron/ })).toHaveText(
			"Schema huron-base v1 with this collection's override"
		);
		const schema = main(page).getByRole('region', { name: /^Schema huron-base v1 with/ });
		const composed = schema.getByRole('table', { name: "Fields of the collection's schema" });
		await expect(composed.getByRole('rowheader').filter({ hasText: /^Release date/ })).toHaveCount(
			1
		);
		// The API gives the composed document the override's title and huron-base's description:
		// neither introduces the composed table.
		for (const words of ['Wind SWE additions', 'Fields every collection carries.']) {
			await expect(schema.getByText(words, { exact: true })).toHaveCount(0);
		}
		const override = main(page).getByRole('region', { name: 'Schema override', exact: true });
		await expect(
			override
				.getByRole('table', { name: 'Fields of the schema override' })
				.getByRole('rowheader')
				.first()
		).toHaveText(/^Release date/);
		await expect(override.getByText('Wind SWE additions', { exact: true })).toBeVisible();
	});
});

test.describe('activity links', () => {
	test('lead from the catalog log to a collection by its identifier or by its id', async ({
		page
	}) => {
		const { body } = await apiCollection('erin', LEAF);
		const leafId = 'id' in body ? String(body.id) : '';
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/activity');
		const entries = main(page)
			.getByRole('list', { name: 'Catalog activity' })
			.getByRole('listitem');
		await entries.nth(1).getByRole('link', { name: LEAF }).click();
		await expect(page).toHaveURL(collectionPath(LEAF));
		await expect(main(page).getByRole('heading', { level: 1 })).toHaveText(titleOf(LEAF));

		await page.goBack();
		await entries
			.nth(0)
			.getByRole('link', { name: `collection ${leafId.replaceAll('-', '').slice(-12)}` })
			.click();
		await expect(page).toHaveURL(collectionPath(LEAF));
		await expect(main(page).getByRole('heading', { level: 1 })).toHaveText(titleOf(LEAF));
	});

	test('by id answer 303 to the address by identifier, or say the collection may be gone', async ({
		page
	}) => {
		const { body } = await apiCollection('erin', LEAF);
		const leafId = 'id' in body ? String(body.id) : '';
		await signIn(page, 'carol');
		const moved = await page.request.get(`/collections/${leafId}`, { maxRedirects: 0 });
		expect(moved.status()).toBe(303);
		expect(moved.headers().location).toBe(collectionPath(LEAF));

		const response = await page.goto('/collections/0192f2a4-0000-7000-8000-00000000dead');
		expect(response?.status()).toBe(404);
		await expect(main(page).getByRole('heading', { level: 1 })).toHaveText(
			'Not found, deleted, or you do not have access.'
		);
		await expect(
			main(page).getByRole('link', { name: 'Back to Heliophysics Division' })
		).toBeVisible();
	});

	test('by id say a draft a reader may not see may be gone', async ({ page }) => {
		const { body } = await apiCollection('dave', DRAFT);
		const draftId = 'id' in body ? String(body.id) : '';
		await signIn(page, 'erin');
		const response = await page.goto(`/collections/${draftId}`);
		expect(response?.status()).toBe(404);
		await expect(main(page).getByRole('heading', { level: 1 })).toHaveText(
			'Not found, deleted, or you do not have access.'
		);
	});
});
