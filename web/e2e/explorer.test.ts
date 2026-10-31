import { expect, type Locator, type Page } from '@playwright/test';
import { drawnLines, expectMarkedCurrent } from './support/cues.ts';
import { STATION_COUNT } from './support/fixture.mjs';
import { VIEWPORTS, signIn, test } from './support/harness.ts';

function explorer(page: Page) {
	return page.getByRole('navigation', { name: 'Explorer' });
}

test.describe('the explorer', () => {
	test('opens a folder through the tree endpoint and keeps focus on its toggle', async ({
		page
	}) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		const tree = explorer(page);
		const toggle = tree.getByRole('button', { name: 'Contents of solar-wind' });
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await expect(tree.getByRole('link', { name: 'ace', exact: true })).toHaveCount(0);

		const answer = page.waitForResponse((response) =>
			response.url().endsWith('/catalogs/heliophysics/tree?parent=solar-wind')
		);
		await toggle.focus();
		await page.keyboard.press('Enter');
		const response = await answer;
		expect(response.status()).toBe(200);
		expect(response.request().headers()['x-huron-fetch']).toBe('1');
		expect(response.headers()['cache-control']).toBe('private, no-store');
		await expect(tree.getByRole('link', { name: 'ace', exact: true })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind.ace'
		);
		await expect(tree.getByRole('link', { name: 'wind', exact: true })).toBeVisible();
		await expect(toggle).toHaveAttribute('aria-expanded', 'true');
		await expect(toggle).toBeFocused();

		await page.keyboard.press('Enter');
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await expect(tree.getByRole('link', { name: 'ace', exact: true })).toHaveCount(0);
		await expect(toggle).toBeFocused();
	});

	test('shows the way to the current namespace and marks it', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/solar-wind.ace');
		const tree = explorer(page);
		await expect(tree).toMatchAriaSnapshot(`
			- navigation "Explorer":
			  - heading "Explorer" [level=2]
			  - list:
			    - listitem:
			      - button "Contents of Heliophysics" [expanded]
			      - link "Heliophysics":
			        - /url: /catalogs/heliophysics
			      - list:
			        - listitem:
			          - button "Contents of deep"
			          - link "deep":
			            - /url: /catalogs/heliophysics/namespaces/deep
			        - listitem:
			          - link "empty":
			            - /url: /catalogs/heliophysics/namespaces/empty
			        - listitem:
			          - button "Contents of fields"
			          - link "fields":
			            - /url: /catalogs/heliophysics/namespaces/fields
			        - listitem:
			          - button "Contents of solar-wind" [expanded]
			          - link "solar-wind":
			            - /url: /catalogs/heliophysics/namespaces/solar-wind
			          - list:
			            - listitem:
			              - button "Contents of ace" [expanded]
			              - link "ace":
			                - /url: /catalogs/heliophysics/namespaces/solar-wind.ace
			              - list:
			                - listitem:
			                  - link "mag-l2-2024":
			                    - /url: /catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024
			                - listitem:
			                  - link "swepam-2024":
			                    - /url: /catalogs/heliophysics/collections/solar-wind.ace.swepam-2024
			            - listitem:
			              - button "Contents of wind"
			              - link "wind":
			                - /url: /catalogs/heliophysics/namespaces/solar-wind.wind
			    - listitem:
			      - link "Space Weather":
			        - /url: /catalogs/space-weather
		`);
		await expectMarkedCurrent(
			tree.getByRole('link', { name: 'ace', exact: true }),
			tree.getByRole('link', { name: 'wind', exact: true })
		);
		await expect(tree.getByRole('link', { name: 'ace', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
	});

	test('marks the catalog on its overview', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		const tree = explorer(page);
		await expectMarkedCurrent(
			tree.getByRole('link', { name: 'Heliophysics', exact: true }),
			tree.getByRole('link', { name: 'Space Weather', exact: true })
		);
		await expect(tree.getByRole('link', { name: 'Heliophysics', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
	});

	test('pins the current namespace when it is beyond the first page of its level', async ({
		page
	}) => {
		const last = `station-${String(STATION_COUNT).padStart(2, '0')}`;
		await signIn(page, 'erin');
		await page.goto(`/catalogs/space-weather/namespaces/stations.${last}`);
		const tree = explorer(page);
		// The innermost item that holds the folder's toggle is the folder's own.
		const stations = tree
			.getByRole('listitem')
			.filter({ has: page.getByRole('button', { name: 'Contents of stations' }) })
			.last();
		const links = stations.getByRole('list').first().getByRole('link');
		// The first page of 50, More…, then the current station.
		await expect(links).toHaveCount(52);
		await expect(links.nth(49)).toHaveText('station-50');
		await expect(links.nth(50)).toHaveText('More…');
		await expect(links.nth(51)).toHaveText(last);
		await expect(links.nth(51)).toHaveAttribute('aria-current', 'page');
		await expectMarkedCurrent(links.nth(51), links.nth(0));

		await tree.getByRole('link', { name: 'More namespaces in stations' }).click();
		await expect(page).toHaveURL(
			/\/catalogs\/space-weather\/namespaces\/stations\?namespaces_cursor=/
		);
		const rest = page.getByRole('main').getByRole('list', { name: 'Namespaces in stations' });
		await expect(rest.getByRole('listitem')).toHaveCount(STATION_COUNT - 50);
		await expect(rest.getByRole('listitem').first()).toContainText('station-51');
	});

	test('is drawn beside the content from lg and left out on narrower screens', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		await expect(explorer(page)).toBeVisible();
		const [content, tree] = await Promise.all([
			page.getByRole('heading', { name: 'Heliophysics', level: 1 }).boundingBox(),
			explorer(page).boundingBox()
		]);
		expect(tree && content && tree.x + tree.width <= content.x).toBe(true);
		for (const viewport of [VIEWPORTS.tablet, VIEWPORTS.phone]) {
			await page.setViewportSize(viewport);
			await expect(explorer(page)).toBeHidden();
		}
	});

	test('comes after the page content for the keyboard', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/empty');
		await page.keyboard.press('Tab');
		await page.keyboard.press('Enter');
		await expect(page.getByRole('main')).toBeFocused();
		await page.keyboard.press('Tab');
		await expect(
			page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link').first()
		).toBeFocused();
	});

	test('shows that a folder is loading while its answer is on its way', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		await page.route(/\/tree\?parent=solar-wind$/, async (route) => {
			await held;
			await route.continue();
		});
		await tree.getByRole('button', { name: 'Contents of solar-wind' }).click();
		const folder = tree
			.getByRole('listitem')
			.filter({ has: page.getByRole('button', { name: 'Contents of solar-wind' }) })
			.last();
		await expect(folder).toHaveAttribute('aria-busy', 'true');
		await expect(folder.getByText('Loading…')).toBeVisible();
		// One live region for the whole explorer, outside the busy folder.
		await expect(tree.getByRole('status')).toHaveText('Loading solar-wind…');
		release();
		await expect(tree.getByRole('link', { name: 'wind', exact: true })).toBeVisible();
		await expect(folder).not.toHaveAttribute('aria-busy');
		await expect(tree.getByRole('status')).toHaveText('Loaded solar-wind.');
	});

	test('never leaves a folder open with nothing in it after a navigation', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/solar-wind.ace');
		const tree = explorer(page);
		const fetches: string[] = [];
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.pathname.endsWith('/tree')) fetches.push(url.search);
		});
		// Closed and opened again over the contents the page brought: nothing is fetched.
		const ace = tree.getByRole('button', { name: 'Contents of ace' });
		await ace.click();
		await expect(ace).toHaveAttribute('aria-expanded', 'false');
		await ace.click();
		await expect(tree.getByRole('link', { name: 'mag-l2-2024' })).toBeVisible();

		await tree.getByRole('link', { name: 'wind', exact: true }).click();
		await expect(page).toHaveURL('/catalogs/heliophysics/namespaces/solar-wind.wind');
		await expect(tree.getByRole('link', { name: 'wind', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
		// The wind page does not bring ace's contents: ace closes instead of showing nothing.
		await expect(ace).toHaveAttribute('aria-expanded', 'false');
		await expect(tree.getByRole('link', { name: 'mag-l2-2024' })).toHaveCount(0);
		expect(fetches).toEqual([]);

		await ace.click();
		await expect(tree.getByRole('link', { name: 'mag-l2-2024' })).toBeVisible();
		expect(fetches).toEqual(['?parent=solar-wind.ace']);
	});

	test('starts afresh in another catalog, and again on coming back', async ({ page }) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		const tree = explorer(page);
		const fetches: string[] = [];
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.pathname.endsWith('/tree')) fetches.push(`${url.pathname}${url.search}`);
		});
		const fields = tree.getByRole('button', { name: 'Contents of fields' });
		const run = tree.getByRole('link', { name: 'run001', exact: true });
		await fields.click();
		await expect(run).toBeVisible();

		await tree.getByRole('link', { name: 'Space Weather', exact: true }).click();
		await expect(page).toHaveURL('/catalogs/space-weather');
		await expect(tree.getByRole('link', { name: 'Space Weather', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await expect(fields).toHaveCount(0);

		await tree.getByRole('link', { name: 'Heliophysics', exact: true }).click();
		await expect(page).toHaveURL('/catalogs/heliophysics');
		// What was opened and fetched in a catalog stays behind with it: two catalogs may hold
		// namespaces of the same path.
		await expect(fields).toHaveAttribute('aria-expanded', 'false');
		await expect(run).toHaveCount(0);
		await fields.click();
		await expect(run).toBeVisible();
		expect(fetches).toEqual([
			'/catalogs/heliophysics/tree?parent=fields',
			'/catalogs/heliophysics/tree?parent=fields'
		]);
	});

	for (const viewport of [VIEWPORTS.desktop, { width: 1024, height: 768 }]) {
		test(`shows the page's node on load without scrolling the window at ${viewport.width}`, async ({
			page
		}) => {
			await page.setViewportSize(viewport);
			await signIn(page, 'erin');
			const last = `station-${String(STATION_COUNT).padStart(2, '0')}`;
			for (const path of [
				`/catalogs/space-weather/namespaces/stations.${last}`,
				'/catalogs/heliophysics/collections/fields.run055/files'
			]) {
				await page.goto(path);
				// The node lies far below the explorer's top on these trees of over 50 rows.
				await expect.poll(() => currentNodeShown(page), { message: path }).toBe(true);
				expect(await page.evaluate(() => scrollY), path).toBe(0);
				// The page stays about a screen tall, not as tall as the tree.
				expect(await page.evaluate(() => document.documentElement.scrollHeight), path).toBeLessThan(
					2 * viewport.height
				);
			}
		});
	}

	test('keeps the focus rings of rows at its edges inside it while it scrolls', async ({
		page
	}) => {
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/collections/fields.run055/files');
		const tree = explorer(page);
		await expect.poll(() => currentNodeShown(page)).toBe(true);
		for (const control of [
			tree.getByRole('button', { name: 'Contents of Heliophysics' }),
			tree.getByRole('link', { name: 'run055' })
		]) {
			await control.focus();
			expect(await ringInside(control)).toBe(true);
		}
	});

	test('keeps a deep tree inside its column, beside the content', async ({ page }) => {
		// Identifiers may nest a hundred namespaces deep; the fixture's deepest has four, so the
		// levels below deep are answered here, each holding the next and a collection.
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		await page.route(/\/catalogs\/heliophysics\/tree\?parent=deep/, (route) => {
			const parent = new URL(route.request().url()).searchParams.get('parent') ?? '';
			const depth = parent.split('.').length;
			const child = `level-${String(depth).padStart(2, '0')}`;
			return route.fulfill({
				json: {
					parent,
					namespaces: depth < 16 ? [{ name: child, path: `${parent}.${child}`, empty: false }] : [],
					namespacesNext: null,
					collections: [
						{ name: `leaf-${depth}`, identifier: `heliophysics.${parent}.leaf-${depth}` }
					],
					collectionsNext: null
				}
			});
		});
		const tree = explorer(page);
		await tree.getByRole('button', { name: 'Contents of deep' }).click();
		for (let depth = 1; depth < 16; depth += 1) {
			const name = `level-${String(depth).padStart(2, '0')}`;
			await tree.getByRole('button', { name: `Contents of ${name}` }).click();
		}
		await expect(tree.getByRole('link', { name: 'leaf-16' })).toBeAttached();
		for (const viewport of [VIEWPORTS.desktop, { width: 1024, height: 768 }]) {
			await page.setViewportSize(viewport);
			const content = await page
				.getByRole('heading', { name: 'Heliophysics', level: 1 })
				.boundingBox();
			const drawn = await tree.evaluate((nav) => ({
				right: Math.max(
					...[...nav.querySelectorAll('a, button')].map((row) => row.getBoundingClientRect().right)
				),
				sideways: nav.scrollWidth - nav.clientWidth
			}));
			expect(content && drawn.right <= content.x, `${viewport.width}`).toBe(true);
			expect(drawn.sideways, `${viewport.width}`).toBe(0);
		}
	});

	test('breaks a long name at its hyphens, not inside a word', async ({ page }) => {
		// No name of the fixture is wider than the column, so the level below deep is answered
		// here: names wider than the column whose parts between hyphens each fit.
		const folder = 'magnetometer-observations-calibrated';
		const leaf = 'solar-wind-magnetometer-calibrated-2024';
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics');
		await page.route(/\/catalogs\/heliophysics\/tree\?parent=deep$/, (route) =>
			route.fulfill({
				json: {
					parent: 'deep',
					namespaces: [{ name: folder, path: `deep.${folder}`, empty: true }],
					namespacesNext: null,
					collections: [{ name: leaf, identifier: `heliophysics.deep.${leaf}` }],
					collectionsNext: null
				}
			})
		);
		const tree = explorer(page);
		await tree.getByRole('button', { name: 'Contents of deep' }).click();
		for (const name of [folder, leaf]) {
			const link = tree.getByRole('link', { name, exact: true });
			await expect(link).toBeVisible();
			const lines = await drawnLines(link);
			expect(lines.join(''), name).toBe(name);
			expect(lines.length, name).toBeGreaterThan(1);
			for (const line of lines.slice(0, -1)) expect(line, name).toMatch(/-$/);
		}
	});
});

/** Whether the explorer draws the page's node inside its own view and the window's. */
function currentNodeShown(page: Page): Promise<boolean> {
	return explorer(page).evaluate((nav) => {
		const node = nav.querySelector('[aria-current]');
		if (node === null) return false;
		const view = nav.getBoundingClientRect();
		const row = node.getBoundingClientRect();
		return (
			row.top >= view.top &&
			row.bottom <= view.bottom &&
			row.top >= 0 &&
			row.bottom <= window.innerHeight
		);
	});
}

/** Whether a focused control's focus ring, drawn outside it, lies inside the explorer. */
function ringInside(control: Locator): Promise<boolean> {
	return control.evaluate((element) => {
		const nav = element.closest('nav');
		if (nav === null) throw new Error('not in the explorer');
		const style = getComputedStyle(element);
		const ring = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
		if (!(ring > 0)) throw new Error('no focus ring');
		const box = element.getBoundingClientRect();
		const view = nav.getBoundingClientRect();
		return (
			box.left - ring >= view.left &&
			box.right + ring <= view.right &&
			box.top - ring >= view.top &&
			box.bottom + ring <= view.bottom
		);
	});
}
