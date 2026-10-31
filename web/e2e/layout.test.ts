import { expect, type Locator, type Page } from '@playwright/test';
import { VIEWPORTS, horizontalOverflow, signIn, test } from './support/harness.ts';

/**
 * The pages of a platform admin, who sees everything, with what each shows once loaded. The
 * walks sign in as paula, whom no other test uses: they take long, and a user's oldest session
 * ends once she holds ten. The descriptions of planetary and exoplanets hold long unbroken paths,
 * which must wrap; so must share paths and identifiers, the key no line can break that
 * swe-2023's metadata holds in an object and in a list's item, and a search's text and labels,
 * however long.
 */
const PAGES = [
	{ path: '/', heading: 'Organizations' },
	{ path: '/orgs', heading: 'All organizations' },
	{ path: '/orgs/helio', heading: 'Heliophysics Division' },
	{ path: '/orgs/planetary', heading: 'Planetary Science' },
	{ path: '/orgs/astro', heading: 'Astrophysics' },
	{ path: '/account', heading: 'Account' },
	{ path: '/orgs/nope', heading: "Not found, or you don't have access." },
	{ path: '/catalogs/heliophysics', heading: 'Heliophysics' },
	{ path: '/catalogs/heliophysics/access', heading: 'Heliophysics' },
	{ path: '/catalogs/heliophysics/activity', heading: 'Heliophysics' },
	{ path: '/catalogs/heliophysics/schema', heading: 'Heliophysics' },
	{ path: '/catalogs/space-weather/schema', heading: 'Space Weather' },
	{ path: '/catalogs/space-weather/activity', heading: 'Space Weather' },
	{ path: '/catalogs/exoplanets', heading: 'Exoplanets' },
	{ path: '/catalogs/exoplanets/namespaces/surveys', heading: 'surveys' },
	{ path: '/catalogs/heliophysics/namespaces/solar-wind', heading: 'solar-wind' },
	{ path: '/catalogs/heliophysics/namespaces/solar-wind.ace', heading: 'ace' },
	{ path: '/catalogs/heliophysics/namespaces/empty', heading: 'empty' },
	{ path: '/catalogs/heliophysics/namespaces/fields', heading: 'fields' },
	{ path: '/catalogs/heliophysics/namespaces/deep.a.b.c', heading: 'c' },
	{ path: '/catalogs/space-weather/namespaces/stations.station-55', heading: 'station-55' },
	{
		path: '/catalogs/heliophysics/namespaces/nope',
		heading: "Not found, or you don't have access."
	},
	{ path: '/catalogs/nope', heading: "Not found, or you don't have access." },
	...[
		'?q=wind&label=mission%3Dwind',
		'?q=heliophysics.solar-wind.ace.mag-l2-2024',
		'?q=run',
		'?q=solar%20storm%20xyz&label=mission%3Dace&state=incomplete',
		// One long unbroken label, in the form, in the suggestions and in the CLI hint.
		`?label=${encodeURIComponent('faradayCupEffectiveAreaCalibrationCoefficientsRevisionForSensorUnitB=rev-7')}`,
		// The longest key and value a label filter holds.
		`?label=${'k'.repeat(100)}%3D${'v'.repeat(100)}`,
		`?q=${'w'.repeat(201)}`,
		// A label filter too long to search for, given back in the field for adding one.
		`?label=k%3D${'v'.repeat(101)}`
	].map((query) => ({ path: `/catalogs/heliophysics/search${query}`, heading: 'Heliophysics' })),
	// An organization without catalogs, which has nothing to search.
	{ path: '/orgs/planetary/search?q=wind', heading: 'Planetary Science' },
	...['', '/files', '/commits', '/activity', '/schema'].map((tab) => ({
		path: `/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024${tab}`,
		heading: 'ACE MAG level 2, 2024'
	})),
	...['', '/files', '/commits'].map((tab) => ({
		path: `/catalogs/heliophysics/collections/solar-wind.ace.mag-l1-draft${tab}`,
		heading: 'ACE MAG level 1 (draft)'
	})),
	{
		path: '/catalogs/space-weather/collections/alerts.flare-list-2024',
		heading: 'Flare list 2024'
	},
	...['', '/schema'].map((tab) => ({
		path: `/catalogs/heliophysics/collections/solar-wind.wind.swe-2023${tab}`,
		heading: 'Wind SWE ion moments, 2023'
	})),
	{
		path: '/catalogs/heliophysics/collections/fields.run001/files',
		heading: 'Encounter 17 run 001'
	},
	{ path: '/catalogs/heliophysics/collections/deep.a.b.c.leaf', heading: 'Deeply nested leaf' },
	{
		path: '/catalogs/heliophysics/collections/solar-wind.ace.nope',
		heading: "Not found, or you don't have access."
	}
];

/**
 * The organization search, its results of each kind, drafts among them, and the page that asks
 * which organization to search: a walk of its own, as long again.
 */
const SEARCH_PAGES = [
	...[
		'',
		'?q=run',
		'?q=2024',
		'?q=heliophysics.solar-wind.ace.mag-l2-2024',
		'?state=draft',
		'?q=solar%20storm%20xyz&label=mission%3Dace&state=incomplete',
		`?label=${encodeURIComponent('faradayCupEffectiveAreaCalibrationCoefficientsRevisionForSensorUnitB=rev-7')}`,
		`?label=${'k'.repeat(100)}%3D${'v'.repeat(100)}`,
		`?q=${'w'.repeat(201)}`
	].map((query) => ({ path: `/orgs/helio/search${query}`, heading: 'Heliophysics Division' })),
	{ path: '/orgs/geo/search?q=ocean', heading: 'Earth Science' },
	{ path: '/search?q=wind', heading: 'Search' },
	{ path: '/search', heading: 'Search' },
	{ path: `/search?q=${'w'.repeat(201)}&label=k%3D${'v'.repeat(100)}`, heading: 'Search' }
];

for (const [name, viewport] of Object.entries(VIEWPORTS)) {
	test.describe(`at ${name} width`, () => {
		test.use({ viewport });

		test('the login and start pages never scroll sideways', async ({ page }) => {
			await page.goto('/login?error=idp_unavailable&returnTo=%2Forgs%2Fhelio');
			await expect(page.getByRole('alert')).toBeVisible();
			expect(await horizontalOverflow(page)).toBe(0);

			await signIn(page, 'paula');
			await expect(page.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();
			expect(await horizontalOverflow(page)).toBe(0);
		});

		test('no page of the shell scrolls sideways', async ({ page }) => {
			await signIn(page, 'paula');
			for (const { path, heading } of PAGES) {
				await page.goto(path);
				await expect(page.getByRole('heading', { name: heading, level: 1 }), path).toBeVisible();
				expect(await horizontalOverflow(page), path).toBe(0);
			}
		});

		test('no search page scrolls sideways', async ({ page }) => {
			await signIn(page, 'paula');
			for (const { path, heading } of SEARCH_PAGES) {
				await page.goto(path);
				await expect(page.getByRole('heading', { name: heading, level: 1 }), path).toBeVisible();
				expect(await horizontalOverflow(page), path).toBe(0);
			}
		});
	});
}

/**
 * How a page's section navigation draws its links: in how many rows, whether the current one is
 * framed on every side, and whether its bottom sits on its header's bottom border, as a tab's
 * underline does.
 */
function sectionsDrawn(navigation: Locator) {
	return navigation.evaluate((nav) => {
		const links = [...nav.querySelectorAll('a')];
		const current = nav.querySelector('[aria-current="page"]');
		const header = nav.closest('header');
		if (current === null || header === null) throw new Error('no current section or header');
		const style = getComputedStyle(current);
		return {
			rows: new Set(links.map((link) => Math.round(link.getBoundingClientRect().top))).size,
			framed: ['top', 'right', 'bottom', 'left'].every(
				(side) => parseFloat(style.getPropertyValue(`border-${side}-width`)) >= 2
			),
			onBorder:
				Math.abs(current.getBoundingClientRect().bottom - header.getBoundingClientRect().bottom) < 1
		};
	});
}

/** Pages with section navigation, and the rows it takes on a phone. */
const SECTIONS = [
	{ path: '/orgs/helio', navigation: 'Organization', phoneRows: 1 },
	{ path: '/orgs/helio/search', navigation: 'Organization', phoneRows: 1 },
	{ path: '/catalogs/heliophysics/schema', navigation: 'Catalog', phoneRows: 2 },
	{
		path: '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/schema',
		navigation: 'Collection',
		phoneRows: 2
	}
];

for (const [name, viewport] of Object.entries(VIEWPORTS)) {
	test(`a page's sections mark the current one where it is drawn at ${name} width`, async ({
		page
	}) => {
		await page.setViewportSize(viewport);
		await signIn(page, 'paula');
		for (const { path, navigation, phoneRows } of SECTIONS) {
			await page.goto(path);
			const drawn = await sectionsDrawn(
				page.getByRole('main').getByRole('navigation', { name: navigation })
			);
			// On a phone the links wrap as pills, the current one framed wherever it falls; with
			// room, they are tabs in one row, the current one underlined on the header's border.
			expect(drawn, path).toEqual(
				name === 'phone'
					? { rows: phoneRows, framed: true, onBorder: false }
					: { rows: 1, framed: false, onBorder: true }
			);
		}
	});
}

test("the error page's link back to a long-named organization wraps on a phone", async ({
	page
}) => {
	await page.setViewportSize(VIEWPORTS.phone);
	await signIn(page, 'erin');
	await page.goto('/orgs/nope');
	const back = page.getByRole('main').getByRole('link', { name: 'Back to Heliophysics Division' });
	await expect(back).toBeVisible();
	// An organization without a display name shows its name, up to 63 characters without a
	// space. No fixture organization has one, as it would change every count of the fixture, so
	// the link is given one.
	await back.evaluate((link) => (link.textContent = `Back to ${'n'.repeat(63)}`));
	expect(await horizontalOverflow(page)).toBe(0);
});

/** The accessible name of the focused element, or `null` once focus has left the page. */
function focusedName(page: Page): Promise<string | null> {
	return page.evaluate(() => {
		const focused = document.activeElement;
		if (!(focused instanceof HTMLElement) || focused === document.body) return null;
		return (focused.getAttribute('aria-label') ?? focused.textContent ?? '').trim();
	});
}

/**
 * How many pixels of the focused element lie under the fixed header or the bottom navigation, or
 * outside the viewport. The bars' own controls and the skip link, which shows above them, count
 * as uncovered.
 */
function coveredPixels(page: Page): Promise<number> {
	return page.evaluate(() => {
		const focused = document.activeElement;
		if (!(focused instanceof HTMLElement)) return 0;
		const banner = document.querySelector('header:not(main *)');
		const bottomNavigation = document.querySelector('nav[aria-label="Primary"]:not(aside *)');
		const bars = [banner, document.querySelector('aside'), bottomNavigation];
		if (focused.matches('.skip-link') || bars.some((bar) => bar?.contains(focused))) return 0;
		const box = focused.getBoundingClientRect();
		const top = banner?.getBoundingClientRect().bottom ?? 0;
		const navigation = bottomNavigation?.getBoundingClientRect();
		const bottom = navigation !== undefined && navigation.height > 0 ? navigation.top : innerHeight;
		const above = Math.max(0, Math.min(box.bottom, top) - box.top);
		const below = Math.max(0, box.bottom - Math.max(box.top, bottom));
		return Math.round(above + below);
	});
}

/** Press `key` until focus leaves the page; each element it reaches must stay uncovered. */
async function walkFocus(page: Page, key: 'Tab' | 'Shift+Tab'): Promise<string[]> {
	const reached: string[] = [];
	for (let step = 0; step < 40; step += 1) {
		await page.keyboard.press(key);
		const name = await focusedName(page);
		if (name === null) return reached;
		reached.push(name);
		// Polled: the page may still be scrolling the element into view.
		await expect.poll(() => coveredPixels(page), { message: `${key} to "${name}"` }).toBe(0);
	}
	throw new Error(`${key} never left the page`);
}

for (const viewport of [VIEWPORTS.phone, { width: 1440, height: 500 }]) {
	const size = `${viewport.width}x${viewport.height}`;

	test(`keyboard focus is never hidden by the fixed bars at ${size}`, async ({ page }) => {
		await page.setViewportSize(viewport);
		await signIn(page, 'dave');
		await page.goto('/account');
		await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
		const forward = await walkFocus(page, 'Tab');
		expect(forward).toEqual(expect.arrayContaining(['Geoscience', 'Space Weather']));
		const backward = await walkFocus(page, 'Shift+Tab');
		expect(backward).toEqual([...forward].reverse());
	});

	test(`focus moving up onto a button under the header brings it out at ${size}`, async ({
		page
	}) => {
		await page.setViewportSize(viewport);
		await signIn(page, 'dave');
		await page.goto('/account');
		const main = page.getByRole('main');
		const signOut = main.getByRole('button', { name: 'Sign out', exact: true });
		// Focus starts on the element after the button.
		await main
			.getByRole('region', { name: 'Roles' })
			.getByRole('link', { name: 'Geoscience' })
			.focus();
		// Scrolled until the button is inside the viewport but partly under the 64px header:
		// browsers scroll a focused element only when it leaves the viewport less its scroll
		// padding.
		const top = await signOut.evaluate((button) => {
			window.scrollBy({ top: button.getBoundingClientRect().top - 40, behavior: 'instant' });
			return button.getBoundingClientRect().top;
		});
		expect(top).toBeGreaterThanOrEqual(39);
		expect(top).toBeLessThanOrEqual(41);
		await page.keyboard.press('Shift+Tab');
		await expect(signOut).toBeFocused();
		await expect.poll(() => coveredPixels(page)).toBe(0);
	});
}
