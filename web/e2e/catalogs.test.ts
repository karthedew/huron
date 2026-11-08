import { expect, type Locator } from '@playwright/test';
import {
	CATALOGS,
	COLLECTIONS,
	MOUNT_PREFIX,
	NAMESPACES,
	SCHEMAS,
	USERS,
	collectionIdentifier,
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

/** The users who see heliophysics, from reader up to platform administrator. */
const BROWSERS: Username[] = ['erin', 'dave', 'carol', 'alice'];

/** Who may change heliophysics with the CLI: its catalog administrators and those above. */
const ADMINISTRATORS: ReadonlySet<Username> = new Set(['carol', 'alice']);

/** Whether a user sees drafts in heliophysics: contributors and everyone above. */
function seesDrafts(username: Username): boolean {
	return username !== 'erin';
}

/** The fixture's namespaces directly below `parent` ('' for the root), by name. */
function childNamespaces(catalog: string, parent: string) {
	return NAMESPACES.filter(
		(namespace) =>
			namespace.catalog === catalog && namespace.path.split('.').slice(0, -1).join('.') === parent
	).sort((a, b) => (a.path < b.path ? -1 : 1));
}

/** The fixture's collections directly in a namespace that a user can see. */
function collectionsIn(catalog: string, namespace: string, username: Username) {
	return COLLECTIONS.filter(
		(collection) =>
			collection.catalog === catalog &&
			collection.namespace === namespace &&
			(collection.state !== 'draft' || seesDrafts(username))
	);
}

/** "N namespaces" / "N collections", as the namespace overview counts what it holds. */
function count(value: number, noun: string): string {
	return `${value} ${value === 1 ? noun : `${noun}s`}`;
}

function rows(list: Locator): Locator {
	return list.locator('tbody').getByRole('row');
}

test.describe('a catalog', () => {
	for (const username of BROWSERS) {
		test(`shows heliophysics to ${username} with its top-level namespaces`, async ({ page }) => {
			await signIn(page, username);
			await page.goto('/catalogs/heliophysics');
			await expect(page).toHaveTitle('Heliophysics · Heliophysics Division · Huron');
			const main = page.getByRole('main');
			const catalog = CATALOGS.find(({ name }) => name === 'heliophysics');
			await expect(main.getByRole('heading', { name: 'Heliophysics', level: 1 })).toBeVisible();
			await expect(main.getByText(catalog?.description ?? '')).toBeVisible();
			await expect(
				main.getByRole('link', { name: 'Heliophysics Division' }).last()
			).toHaveAttribute('href', '/orgs/helio');
			await expect(main.getByRole('link', { name: 'huron-base v1' })).toHaveAttribute(
				'href',
				'/catalogs/heliophysics/schema'
			);
			const total = NAMESPACES.filter((namespace) => namespace.catalog === 'heliophysics').length;
			await expect(main.getByText(`${total} namespaces in total`)).toBeVisible();
			const tabs = main.getByRole('navigation', { name: 'Catalog' });
			await expect(tabs.getByRole('link')).toHaveText([
				'Overview',
				'Access',
				'Activity',
				'Schema',
				'CLI'
			]);
			await expect(tabs.getByRole('link', { name: 'Overview' })).toHaveAttribute(
				'aria-current',
				'page'
			);

			const list = rows(main.getByRole('table', { name: 'Top-level namespaces' }));
			const root = childNamespaces('heliophysics', '');
			await expect(list).toHaveCount(root.length);
			for (const [index, namespace] of root.entries()) {
				const row = list.nth(index);
				await expect(row.getByRole('link', { name: namespace.path })).toHaveAttribute(
					'href',
					`/catalogs/heliophysics/namespaces/${namespace.path}`
				);
				await expect(row.getByRole('cell').nth(0)).toHaveText(
					String(childNamespaces('heliophysics', namespace.path).length)
				);
				await expect(row.getByRole('cell').nth(1)).toHaveText(
					String(collectionsIn('heliophysics', namespace.path, username).length)
				);
			}
			await tabs.getByRole('link', { name: 'CLI', exact: true }).click();
			const hint = main.getByRole('region', { name: 'Create a namespace here' });
			await expect(hint).toHaveCount(ADMINISTRATORS.has(username) ? 1 : 0);
			// The shell follows the catalog's organization.
			await expect(page.getByRole('banner')).toContainText('Heliophysics Division');
		});
	}

	test('is concealed inside the shell from a user who cannot see it', async ({ page }) => {
		const [alice, erin] = await Promise.all([ApiSession.as('alice'), ApiSession.as('erin')]);
		expect((await alice.get('catalogs/exoplanets')).status).toBe(200);
		expect((await erin.get('catalogs/exoplanets')).status).toBe(404);

		await signIn(page, 'erin');
		const visible = await page.goto('/catalogs/heliophysics');
		expect(visible?.status()).toBe(200);
		const hidden = await page.goto('/catalogs/exoplanets');
		expect(hidden?.status()).toBe(404);
		await expect(page.getByRole('banner')).toBeVisible();
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { level: 1 })).toHaveText(
			"Not found, or you don't have access."
		);
		await expect(main.getByRole('link', { name: 'Back to Heliophysics Division' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
		await expect(page.getByRole('navigation', { name: 'Explorer' })).toHaveCount(0);

		await logOut(page);
		await signIn(page, 'alice');
		expect((await page.goto('/catalogs/exoplanets'))?.status()).toBe(200);
		await expect(page.getByRole('heading', { name: 'Exoplanets', level: 1 })).toBeVisible();
	});

	test('keeps its place and its organization when a page inside it is missing', async ({
		page
	}) => {
		// dave sees two organizations and, just signed in, has none remembered.
		await signIn(page, 'dave');
		const response = await page.goto('/catalogs/heliophysics/namespaces/solar-wind.nope');
		expect(response?.status()).toBe(404);
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { level: 1 })).toHaveText(
			"Not found, or you don't have access."
		);
		await expect(main.getByRole('link', { name: 'Back to Heliophysics Division' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
		await expect(page).toHaveTitle('Not found · Huron');
		// The namespace may not exist: the breadcrumbs and the explorer stop at the catalog.
		await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toBeHidden();
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		await expect(tree.getByRole('link', { name: 'Heliophysics', exact: true })).toHaveAttribute(
			'aria-current',
			'true'
		);
		await expect(tree.getByRole('link', { name: 'nope' })).toHaveCount(0);
		await expect(page.getByRole('banner')).toContainText('Heliophysics Division');
	});

	test('is reached from its organization and leads back to it', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/helio');
		await page.getByRole('main').getByRole('link', { name: 'space-weather', exact: true }).click();
		await expect(page).toHaveURL('/catalogs/space-weather');
		await expect(page.getByRole('heading', { name: 'Space Weather', level: 1 })).toBeVisible();
		await page
			.getByRole('main')
			.getByRole('link', { name: 'Heliophysics Division', exact: true })
			.last()
			.click();
		await expect(page).toHaveURL('/orgs/helio');
	});
});

test.describe('namespaces', () => {
	test('lead down a deep tree, with the way back in mobile breadcrumbs', async ({ page }) => {
		await page.setViewportSize(VIEWPORTS.tablet);
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		const main = page.getByRole('main');
		let list = main.getByRole('table', { name: 'Top-level namespaces' });
		for (const path of ['deep', 'deep.a', 'deep.a.b', 'deep.a.b.c']) {
			const name = path.split('.').at(-1) ?? path;
			await list.getByRole('link', { name, exact: true }).click();
			list = main.getByRole('table', { name: `Namespaces in ${name}` });
			await expect(page).toHaveURL(`/catalogs/heliophysics/namespaces/${path}`);
			await expect(main.getByRole('heading', { name, level: 1 })).toBeVisible();
			await expect(main.getByRole('button', { name: 'Copy full path' })).toBeVisible();
		}
		await expect(page).toHaveTitle('deep.a.b.c · Heliophysics · Huron');
		await expect(main).toContainText('Holds collections');
		await expect(main).toContainText('1 collection');
		await expect(main).toContainText(`${MOUNT_PREFIX}/helio/heliophysics/deep/a/b/c`);
		const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link');
		await expect(crumbs).toHaveText([
			'Heliophysics Division',
			'Heliophysics',
			'deep',
			'a',
			'b',
			'c'
		]);
		await expect(crumbs.last()).toHaveAttribute('aria-current', 'page');
		const leaf = collectionIdentifier(
			COLLECTIONS.find(({ namespace }) => namespace === 'deep.a.b.c') ?? COLLECTIONS[0]
		);
		await expect(main.getByRole('link', { name: 'leaf', exact: true })).toHaveAttribute(
			'href',
			`/catalogs/${leaf.replace('.', '/collections/')}`
		);
		await crumbs.filter({ hasText: /^a$/ }).click();
		await expect(page).toHaveURL('/catalogs/heliophysics/namespaces/deep.a');
		await expect(main.getByRole('heading', { name: 'a', level: 1 })).toBeVisible();
		await expect(main.getByRole('heading', { name: 'Collections' })).toHaveCount(0);
	});

	test('page a namespace of 60 collections by its own cursor', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/fields');
		const main = page.getByRole('main');
		const list = rows(main.getByRole('table', { name: 'Collections in fields' }));
		const expected = collectionsIn('heliophysics', 'fields', 'erin');
		await expect(list).toHaveCount(20);
		await expect(list.first().getByRole('link')).toHaveText(expected[0].name);
		await expect(list.first().getByRole('link')).toHaveAttribute(
			'title',
			titleOf(collectionIdentifier(expected[0]))
		);
		await expect(list.first().getByRole('cell').nth(0)).toHaveText(
			String(recordedFiles(expected[0]).length)
		);
		await expect(list.last().getByRole('link')).toHaveText(expected[19].name);
		const pages = main.getByRole('navigation', { name: 'Collection pages' });
		await expect(pages.getByRole('link', { name: 'First page' })).toHaveCount(0);
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(page).toHaveURL(
			/\/catalogs\/heliophysics\/namespaces\/fields\?collections_cursor=/
		);
		await expect(list).toHaveCount(20);
		await expect(list.first().getByRole('link')).toHaveText(expected[20].name);
		await expect(list.last().getByRole('link')).toHaveText(expected[39].name);
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(list).toHaveCount(20);
		await expect(list.first().getByRole('link')).toHaveText(expected[40].name);
		await expect(list.last().getByRole('link')).toHaveText(expected[59].name);
		await expect(pages.getByRole('link', { name: 'Next page' })).toHaveCount(0);
		await pages.getByRole('link', { name: 'First page' }).click();
		await expect(page).toHaveURL('/catalogs/heliophysics/namespaces/fields');
		await expect(list).toHaveCount(20);
	});

	test('start over when a page link expired, and say so', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/fields?collections_cursor=not-a-cursor');
		await expect(page).toHaveURL('/catalogs/heliophysics/namespaces/fields?notice=page_expired');
		await expect(page.getByRole('main').getByRole('note')).toHaveText(
			'That page link expired; showing the first page.'
		);
		await expect(
			rows(page.getByRole('main').getByRole('table', { name: 'Collections in fields' }))
		).toHaveCount(20);
	});

	test('show drafts to contributors only', async ({ page }) => {
		for (const username of ['erin', 'dave'] satisfies Username[]) {
			await signIn(page, username);
			await page.goto('/catalogs/heliophysics/namespaces/solar-wind.ace');
			const main = page.getByRole('main');
			const expected = collectionsIn('heliophysics', 'solar-wind.ace', username);
			await expect(main).toContainText(count(expected.length, 'collection'));
			const list = rows(main.getByRole('table', { name: 'Collections in ace' }));
			await expect(list).toHaveCount(expected.length);
			const draft = list.filter({
				has: page.getByRole('link', { name: 'mag-l1-draft', exact: true })
			});
			await expect(draft).toHaveCount(seesDrafts(username) ? 1 : 0);
			if (seesDrafts(username)) await expect(draft).toContainText('Draft');
			await logOut(page);
		}
	});

	test('hold the copy and hints that fit what they hold and who looks', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/catalogs/heliophysics/namespaces/empty');
		const main = page.getByRole('main');
		await expect(main.getByText('No collections yet.')).toBeVisible();
		await main
			.getByRole('navigation', { name: 'Namespace', exact: true })
			.getByRole('link', { name: 'CLI', exact: true })
			.click();
		await expect(
			main.getByRole('region', { name: 'Create a collection here' }).getByText(/create collection/)
		).toHaveText('huron --catalog heliophysics create collection heliophysics.empty.<name>');
		await page.goto('/catalogs/heliophysics/namespaces/solar-wind');
		await expect(main.getByRole('region', { name: /^Create a/ })).toHaveCount(0);

		await logOut(page);
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/namespaces/solar-wind');
		await expect(main).toContainText('Structure only');
		await expect(
			main
				.getByRole('table', { name: 'Namespaces in solar-wind' })
				.getByRole('rowheader')
				.getByRole('link')
		).toHaveText(['ace', 'wind']);
		await main
			.getByRole('navigation', { name: 'Namespace', exact: true })
			.getByRole('link', { name: 'CLI', exact: true })
			.click();
		await expect(
			main.getByRole('region', { name: 'Create a namespace here' }).getByText(/create namespace/)
		).toHaveText(
			'huron --catalog heliophysics create namespace heliophysics.solar-wind.<name> --allow-collections'
		);

		await logOut(page);
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/empty');
		await expect(main.getByText('No collections yet.')).toBeVisible();
		await expect(main.getByRole('region', { name: /^Create a/ })).toHaveCount(0);
	});

	test('copy their share path', async ({ page, context }) => {
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/solar-wind.ace');
		// The header's own status; the explorer, also in main, has one for its folders.
		const copy = page.getByRole('main').getByRole('button', { name: 'Copy share path' });
		await copy.click();
		await expect(page.getByRole('status').filter({ hasText: 'Copied' })).toBeVisible();
		expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
			`${MOUNT_PREFIX}/helio/heliophysics/solar-wind/ace`
		);
	});
});

test.describe('the access tab', () => {
	const MARKED: Record<string, string> = {
		erin: 'Reader',
		dave: 'Contributor',
		carol: 'Catalog administrator',
		bob: 'Organization administrator',
		alice: 'Platform administrator'
	};

	/** The list of a role's groups granted at `scope`, as the tab names it. */
	const SOURCE_NAMES: Record<string, string> = {
		platform: 'Inherited from the platform',
		organization: 'Inherited from Heliophysics Division',
		catalog: 'Granted on this catalog'
	};
	const ROLE_HEADINGS: Record<string, string> = {
		platform_admin: 'Platform administrator',
		org_admin: 'Organization administrator',
		catalog_admin: 'Catalog administrator',
		contributor: 'Contributor',
		reader: 'Reader'
	};

	for (const username of ['erin', 'dave', 'carol', 'bob', 'alice'] satisfies Username[]) {
		test(`shows ${username} the groups per role, where each was granted, and marks theirs`, async ({
			page
		}) => {
			const answer = (
				await (await ApiSession.as(username)).get('catalogs/heliophysics/grants/sources')
			).body;
			const sources: { role: string; group: string; scope: string }[] =
				typeof answer === 'object' &&
				answer !== null &&
				'items' in answer &&
				Array.isArray(answer.items)
					? answer.items
					: [];
			// helio's organization-wide groups are also granted on the catalog: both show.
			expect(sources).toEqual(
				expect.arrayContaining([
					{ role: 'reader', group: 'helio-readers', scope: 'organization' },
					{ role: 'reader', group: 'helio-readers', scope: 'catalog' }
				])
			);
			await signIn(page, username);
			await page.goto('/catalogs/heliophysics/access');
			await expect(page).toHaveTitle('Access · Heliophysics · Huron');
			const main = page.getByRole('main');
			const roles = main.getByRole('list', { name: 'Roles' });
			await expect(roles.getByRole('heading', { level: 3 })).toHaveText(
				Object.values(ROLE_HEADINGS)
			);
			for (const [role, name] of Object.entries(ROLE_HEADINGS)) {
				const item = roles
					.getByRole('listitem')
					.filter({ has: page.getByRole('heading', { name, exact: true, level: 3 }) });
				const held = sources.filter((source) => source.role === role);
				for (const scope of ['platform', 'organization', 'catalog']) {
					const groups = held.filter((source) => source.scope === scope).map(({ group }) => group);
					const list = item.getByRole('list', { name: SOURCE_NAMES[scope], exact: true });
					if (groups.length === 0) {
						await expect(list, `${role} ${scope}`).toHaveCount(0);
						continue;
					}
					await expect(list.getByRole('listitem').locator('code'), `${role} ${scope}`).toHaveText(
						groups
					);
				}
				const mine = held.filter(({ group }) => USERS[username].groups.includes(group));
				await expect(item.getByText('You', { exact: true })).toHaveCount(mine.length);
			}
			const yours = roles
				.getByRole('listitem')
				.filter({ has: page.getByText('You', { exact: true }) })
				.getByRole('heading', { level: 3 });
			await expect(yours).toHaveText([MARKED[username]]);
			await expect(
				roles.getByRole('link', { name: 'Heliophysics Division' }).first()
			).toHaveAttribute('href', '/orgs/helio/access');
			await main
				.getByRole('navigation', { name: 'Catalog', exact: true })
				.getByRole('link', { name: 'CLI', exact: true })
				.click();
			const hint = main.getByRole('region', { name: 'Grant a role' });
			await expect(hint).toHaveCount(['carol', 'bob', 'alice'].includes(username) ? 1 : 0);
		});
	}
});

test.describe('the activity tab', () => {
	test('lists the newest entries with links to what they are about', async ({ page }) => {
		const erin = await ApiSession.as('erin');
		const leaf = (await erin.get('catalogs/heliophysics/collections/deep.a.b.c.leaf')).body;
		const leafId = typeof leaf === 'object' && leaf !== null && 'id' in leaf ? String(leaf.id) : '';
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/activity');
		await expect(page).toHaveTitle('Activity · Heliophysics · Huron');
		const entries = page
			.getByRole('main')
			.getByRole('list', { name: 'Catalog activity' })
			.getByRole('listitem');
		await expect(entries).toHaveCount(50);
		// The leaf was created and activated last.
		await expect(entries.nth(0)).toContainText('Activated (revision 2)');
		await expect(entries.nth(0).getByRole('link')).toHaveAttribute(
			'href',
			`/collections/${leafId}`
		);
		await expect(entries.nth(0).getByRole('link')).toHaveText(
			`collection ${leafId.replaceAll('-', '').slice(-12)}`
		);
		await expect(entries.nth(1)).toContainText('Created a collection');
		await expect(
			entries.nth(1).getByRole('link', { name: 'heliophysics.deep.a.b.c.leaf' })
		).toHaveAttribute('href', '/catalogs/heliophysics/collections/deep.a.b.c.leaf');
		await expect(entries.nth(1).locator('time')).toHaveText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$/);
		await entries.nth(1).getByText('Details').click();
		await expect(entries.nth(1).locator('pre')).toContainText(
			'"identifier": "heliophysics.deep.a.b.c.leaf"'
		);

		const pages = page.getByRole('main').getByRole('navigation', { name: 'Activity pages' });
		await pages.getByRole('link', { name: 'Next page' }).click();
		await expect(page).toHaveURL(/\/catalogs\/heliophysics\/activity\?cursor=/);
		await expect(entries.first()).toBeVisible();
		await expect(pages.getByRole('link', { name: 'First page' })).toBeVisible();
	});

	test("names the schemas of a catalog's schema assignment", async ({ page }) => {
		const schema = SCHEMAS[0];
		const api = await ApiSession.as('erin');
		const idOf = async (rest: string) => {
			const { body } = await api.get(`catalogs/space-weather/collections/${rest}`);
			return typeof body === 'object' && body !== null && 'id' in body ? String(body.id) : '';
		};
		// The assignment made both incomplete: one lacks a field, the other's override no longer fits.
		const marked = [
			`/collections/${await idOf('alerts.flare-list-2024')}`,
			`/collections/${await idOf('alerts.storm-count-2024')}`
		];
		await signIn(page, 'erin');
		await page.goto('/catalogs/space-weather/activity');
		const entries = page
			.getByRole('main')
			.getByRole('list', { name: 'Catalog activity' })
			.getByRole('listitem');
		const assigned = entries.filter({ hasText: 'Assigned schema' });
		await expect(assigned).toContainText(
			`Assigned schema ${schema.name} v1 (was ${schema.extends} v1)`
		);
		await expect(assigned).toContainText(schema.assignedBy);
		const incomplete = entries.filter({ hasText: 'Marked incomplete' });
		await expect(incomplete).toHaveCount(2);
		const links = await incomplete
			.getByRole('link')
			.evaluateAll((found) => found.map((link) => link.getAttribute('href')));
		expect(links.toSorted()).toEqual(marked.toSorted());
	});
});

test.describe('the schema tab', () => {
	test('shows the resolved huron-base schema of heliophysics as a table', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/schema');
		await expect(page).toHaveTitle('Schema · Heliophysics · Huron');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: /^Schema /, level: 2 })).toHaveText(
			'Schema huron-base v1'
		);
		const table = main.getByRole('table', { name: "Fields of the catalog's schema" });
		await expect(table.getByRole('rowheader')).toHaveText([
			/^Title/,
			/^Description/,
			/^Campaign/,
			/^Contacts/,
			/^Contacts › name/,
			/^Contacts › email/,
			/^End time/,
			/^Instrument/,
			/^Keywords/,
			/^Labels/,
			/^Start time/
		]);
		const title = table
			.getByRole('row')
			.filter({ has: page.getByRole('rowheader', { name: /^Title/ }) });
		await expect(title).toContainText('Required');
		await expect(title).toContainText('1 to 200 characters');
		await main.getByText('Raw JSON').click();
		await expect(main.locator('details pre')).toContainText('"title": "Huron base metadata"');
	});

	test('shows the organization schema of space-weather, which requires a mission', async ({
		page
	}) => {
		const schema = SCHEMAS[0];
		await signIn(page, 'erin');
		await page.goto('/catalogs/space-weather/schema');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: /^Schema /, level: 2 })).toHaveText(
			`Schema ${schema.name} v1`
		);
		await expect(main.getByText(String(schema.document.title), { exact: true })).toBeVisible();
		const table = main.getByRole('table');
		await expect(table.getByRole('rowheader').nth(2)).toHaveText(/^Mission/);
		const mission = table
			.getByRole('row')
			.filter({ has: page.getByRole('rowheader', { name: /^Mission/ }) });
		await expect(mission).toContainText('Required');
		await expect(mission).toContainText('at least 1 character');
	});
});

/** The words of a code block (runs of text between white space) that are drawn on two lines. */
function wordsBrokenAcrossLines(block: Locator): Promise<string[]> {
	return block.evaluate((element) => {
		const characters: { node: Text; offset: number; text: string }[] = [];
		const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
		for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
			if (!(node instanceof Text)) continue;
			for (let offset = 0; offset < node.data.length; offset += 1) {
				characters.push({ node, offset, text: node.data[offset] });
			}
		}
		const broken: string[] = [];
		let start = 0;
		while (start < characters.length) {
			if (/\s/.test(characters[start].text)) {
				start += 1;
				continue;
			}
			let end = start;
			while (end < characters.length && !/\s/.test(characters[end].text)) end += 1;
			const range = document.createRange();
			range.setStart(characters[start].node, characters[start].offset);
			range.setEnd(characters[end - 1].node, characters[end - 1].offset + 1);
			const lines = new Set([...range.getClientRects()].map(({ top }) => Math.round(top)));
			const word = characters
				.slice(start, end)
				.map(({ text }) => text)
				.join('');
			if (lines.size > 1) broken.push(word);
			start = end;
		}
		return broken;
	});
}

/**
 * Where each line a code block draws starts, from the leftmost of them, grouped by the line of
 * text (the command) it belongs to.
 */
function drawnLineStarts(block: Locator): Promise<number[][]> {
	return block.evaluate((element) => {
		const commands: number[][] = [[]];
		let top: number | null = null;
		const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
		for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
			if (!(node instanceof Text)) continue;
			for (let offset = 0; offset < node.data.length; offset += 1) {
				const character = node.data[offset];
				if (character === '\n') {
					commands.push([]);
					top = null;
				}
				if (/\s/.test(character)) continue;
				const range = document.createRange();
				range.setStart(node, offset);
				range.setEnd(node, offset + 1);
				const box = range.getBoundingClientRect();
				if (top === null || box.top > top + 1) {
					commands[commands.length - 1].push(box.left);
					top = box.top;
				}
			}
		}
		const edge = Math.min(...commands.flat());
		return commands.map((starts) => starts.map((start) => Math.round(start - edge)));
	});
}

test.describe('a CLI hint', () => {
	for (const [name, viewport] of Object.entries(VIEWPORTS)) {
		test(`breaks commands between words and indents what wraps at ${name} width`, async ({
			page
		}) => {
			await page.setViewportSize(viewport);
			await signIn(page, 'alice');
			for (const path of [
				'/catalogs/heliophysics/cli',
				'/catalogs/heliophysics/namespaces/solar-wind/cli',
				'/catalogs/heliophysics/namespaces/empty/cli',
				'/catalogs/heliophysics/cli'
			]) {
				await page.goto(path);
				const hints = page
					.getByRole('main')
					.getByRole('region', { name: /^(Create a|Grant a role)/ });
				await expect(hints.first(), path).toBeVisible();
				for (const hint of await hints.all()) {
					const block = hint.locator('pre');
					expect(await wordsBrokenAcrossLines(block), path).toEqual([]);
					// Every command starts at the edge; the lines it wraps onto start further in.
					const commands = await drawnLineStarts(block);
					for (const [start, ...wrapped] of commands) {
						expect(start, path).toBe(0);
						for (const indent of wrapped) expect(indent, path).toBeGreaterThan(8);
					}
					// A phone is narrower than any of these commands: each of them wraps.
					if (name === 'phone') {
						const wrapping = commands.filter((lines) => lines.length > 1);
						expect(wrapping, path).toHaveLength(commands.length);
					}
				}
			}
		});
	}

	test('without a clipboard, shows each command whole on a phone, and as a field with room', async ({
		browser
	}) => {
		const context = await browser.newContext({ viewport: VIEWPORTS.phone });
		try {
			// As on a plain-http origin other than loopback, where browsers offer no clipboard API.
			await context.addInitScript(() => {
				Object.defineProperty(Navigator.prototype, 'clipboard', { get: () => undefined });
			});
			const page = await context.newPage();
			await signIn(page, 'dave');
			await page.goto('/catalogs/space-weather/collections/alerts.flare-list-2024/cli');
			const title = 'Complete the metadata, then publish it';
			const hint = page.getByRole('main').getByRole('region', { name: title });
			const command =
				'huron --catalog space-weather edit meta space-weather.alerts.flare-list-2024\n' +
				'huron --catalog space-weather publish meta space-weather.alerts.flare-list-2024';
			// On a phone the commands are read rather than run: the code block shows every word of
			// them, where a field would cut each one off at its edge.
			const block = hint.locator('pre');
			await expect(block).toBeVisible();
			await expect(block).toHaveText(command);
			await expect(hint.getByRole('textbox')).toHaveCount(0);
			expect(await block.evaluate((element) => element.scrollWidth - element.clientWidth)).toBe(0);
			expect(await horizontalOverflow(page)).toBe(0);

			await page.setViewportSize(VIEWPORTS.desktop);
			const field = hint.getByRole('textbox', { name: title });
			await expect(field).toHaveValue(command);
			await expect(block).toBeHidden();
			const drawn = await field.evaluate((element) => {
				const style = getComputedStyle(element);
				const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
				return {
					rows: Math.round((element.clientHeight - padding) / parseFloat(style.lineHeight)),
					hidden: element.scrollHeight - element.clientHeight
				};
			});
			// A field cannot indent what wraps, so the commands do not wrap into rows that would read
			// as commands of their own: two commands, two rows, none hidden.
			expect(drawn).toEqual({ rows: 2, hidden: 0 });
			expect(await horizontalOverflow(page)).toBe(0);
		} finally {
			await context.close();
		}
	});
});

test('a catalog page works without scripts, its explorer as plain links', async ({ browser }) => {
	const context = await browser.newContext({ javaScriptEnabled: false });
	try {
		const page = await context.newPage();
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/solar-wind.ace');
		const explorer = page.getByRole('navigation', { name: 'Explorer' });
		await expect(explorer.getByRole('button')).toHaveCount(0);
		await expect(explorer.getByRole('link', { name: 'ace', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await explorer.getByRole('link', { name: 'wind', exact: true }).click();
		await expect(page).toHaveURL('/catalogs/heliophysics/namespaces/solar-wind.wind');
		await expect(page.getByRole('heading', { name: 'wind', level: 1 })).toBeVisible();
	} finally {
		await context.close();
	}
});
