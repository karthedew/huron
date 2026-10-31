import { expect, type Locator } from '@playwright/test';
import { drawnOnTop, drawsLabelInside, expectMarkedCurrent } from './support/cues.ts';
import {
	ApiSession,
	VIEWPORTS,
	accountMenu,
	organizationSwitcher,
	signIn,
	test
} from './support/harness.ts';

test.describe('the shell', () => {
	test('frames a page with the banner, the sidebar and the content', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/helio');
		await expect(page).toHaveTitle('Catalogs · Heliophysics Division · Huron');
		await expect(page.getByRole('banner')).toMatchAriaSnapshot(`
			- banner:
			  - search "Site search":
			    - searchbox "Search Heliophysics Division"
			  - group: "Organization: Heliophysics Division, switch"
			  - button "Use dark mode"
			  - group: "Account: Dave Diaz"
		`);
		const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
		await expect(sidebar).toMatchAriaSnapshot(`
			- complementary "Sidebar":
			  - link "Huron":
			    - /url: /
			  - navigation "Primary":
			    - link "Catalogs":
			      - /url: /orgs/helio
			    - link "Search":
			      - /url: /orgs/helio/search
			  - link "Account":
			    - /url: /account
			  - paragraph: Read-only · changes are made with the huron CLI
		`);
		await expect(sidebar.getByRole('link', { name: 'Catalogs' })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await expect(sidebar.getByRole('link', { name: 'Search' })).not.toHaveAttribute('aria-current');
		await expect(
			page.getByRole('main').getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
	});

	test('the skip link moves focus to the page content', async ({ page }) => {
		await signIn(page, 'erin');
		await page.keyboard.press('Tab');
		const skip = page.getByRole('link', { name: 'Skip to content' });
		await expect(skip).toBeFocused();
		await expect(skip).toBeInViewport();
		await page.keyboard.press('Enter');
		await expect(page.getByRole('main')).toBeFocused();
		await page.keyboard.press('Tab');
		await expect(
			page
				.getByRole('main')
				.getByRole('navigation', { name: 'Organization' })
				.getByRole('link', { name: /^Catalogs/ })
		).toBeFocused();
	});

	test('a slow navigation shows the loading bar and says it is loading', async ({ page }) => {
		await signIn(page, 'dave');
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		await page.route(/\/__data\.json/, async (route) => {
			await held;
			await route.continue();
		});
		await page.getByRole('link', { name: /^Earth Science/ }).click();
		await expect(page.getByRole('main')).toHaveAttribute('aria-busy', 'true');
		await expect(page.getByRole('status').filter({ hasText: 'Loading…' })).toHaveCount(1);
		release();
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
		await expect(page.getByRole('main')).not.toHaveAttribute('aria-busy');
		await expect(page.getByText('Loading…')).toHaveCount(0);
	});

	test('one header menu is open at a time and a click outside closes it', async ({ page }) => {
		await signIn(page, 'dave');
		const switcher = organizationSwitcher(page);
		const account = accountMenu(page);
		await switcher.summary.click();
		await expect(switcher.panel).toBeVisible();
		await account.summary.click();
		await expect(account.panel).toBeVisible();
		await expect(switcher.panel).toBeHidden();
		await page.getByRole('heading', { name: 'Organizations', level: 1 }).click();
		await expect(account.panel).toBeHidden();

		await account.summary.click();
		await page.keyboard.press('Escape');
		await expect(account.panel).toBeHidden();
		await expect(account.summary).toBeFocused();
	});

	test('the account menu names the user and leads to the account page', async ({ page }) => {
		await signIn(page, 'dave');
		const account = accountMenu(page);
		await account.summary.click();
		await expect(account.details).toMatchAriaSnapshot(`
			- group:
			  - text: "Account: Dave Diaz"
			  - paragraph: Dave Diaz
			  - paragraph: dave
			  - link "Account":
			    - /url: /account
			  - button "Sign out"
			  - paragraph: Read-only · changes are made with the huron CLI
		`);
		await account.panel.getByRole('link', { name: 'Account' }).click();
		await expect(page).toHaveURL('/account');
		await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
		await expect(account.panel).toBeHidden();
	});

	test('the account menu works with the keyboard alone', async ({ page }) => {
		await signIn(page, 'dave');
		const account = accountMenu(page);
		const link = account.panel.getByRole('link', { name: 'Account' });
		const logOut = account.panel.getByRole('button', { name: 'Sign out' });
		await account.summary.focus();
		await page.keyboard.press('Enter');
		await expect(account.panel).toBeVisible();
		await page.keyboard.press('ArrowDown');
		await expect(link).toBeFocused();
		await page.keyboard.press('ArrowDown');
		await expect(logOut).toBeFocused();
		await page.keyboard.press('ArrowDown');
		await expect(link).toBeFocused();
		await page.keyboard.press('End');
		await expect(logOut).toBeFocused();
		await page.keyboard.press('Home');
		await expect(link).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(account.panel).toBeHidden();
		await expect(account.summary).toBeFocused();
	});
});

test.describe('the theme toggle', () => {
	test('is left out without scripts, where it could do nothing', async ({ browser }) => {
		const context = await browser.newContext({ javaScriptEnabled: false });
		try {
			const page = await context.newPage();
			await signIn(page, 'bob');
			await expect(accountMenu(page).summary).toBeVisible();
			await expect(page.getByRole('banner').getByRole('button')).toHaveCount(0);
		} finally {
			await context.close();
		}
	});

	test("shows the icon of the page's theme before the page's scripts run", async ({ browser }) => {
		const context = await browser.newContext({ colorScheme: 'dark' });
		try {
			const page = await context.newPage();
			await signIn(page, 'bob');
			// The page as the server drew it, with only app.html's own script, which sets the theme.
			await page.route(/\/_app\/immutable\/.*\.js$/, (route) => route.abort());
			await page.goto('/account');
			const toggle = page.getByRole('banner').getByRole('button', { name: /mode$/ });
			await expect(toggle).toBeVisible();
			await expect(toggle.locator('svg.lucide-sun')).toBeVisible();
			await expect(toggle.locator('svg.lucide-moon')).toBeHidden();
		} finally {
			await context.close();
		}
	});
});

test.describe('the keyboard', () => {
	test('brings what Tab reaches from below the screen into view with its whole focus ring', async ({
		page
	}) => {
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/search?q=mag&label=mission%3Dace');
		const wider = page
			.getByRole('main')
			.getByRole('link', { name: 'Search all of Heliophysics Division' });
		const before = await wider.boundingBox();
		const height = VIEWPORTS.desktop.height;
		// It starts below the screen, so Tab scrolls it into view.
		expect(before !== null && before.y + before.height > height).toBe(true);
		for (let presses = 0; presses < 80; presses += 1) {
			if (await wider.evaluate((link) => link === document.activeElement)) break;
			await page.keyboard.press('Tab');
		}
		await expect(wider).toBeFocused();
		// The page scrolls smoothly: measure where it settles.
		await expect.poll(() => ringBottom(wider)).toBeLessThanOrEqual(height);
	});
});

test.describe('the organization switcher', () => {
	test('lists the organizations and switches with the mouse', async ({ page }) => {
		await signIn(page, 'alice');
		await expect(page).toHaveURL('/');
		const switcher = organizationSwitcher(page);
		await expect(switcher.summary).toHaveText('Choose organization');
		await switcher.summary.click();
		await expect(switcher.details).toMatchAriaSnapshot(`
			- group:
			  - text: Choose organization
			  - list "Organizations":
			    - listitem:
			      - link "Astrophysics astro":
			        - /url: /orgs/astro
			    - listitem:
			      - link "Earth Science geo":
			        - /url: /orgs/geo
			    - listitem:
			      - link "Heliophysics Division helio":
			        - /url: /orgs/helio
			    - listitem:
			      - link "Planetary Science planetary":
			        - /url: /orgs/planetary
			  - link "All organizations":
			    - /url: /orgs
		`);
		await switcher.panel.getByRole('link', { name: 'Earth Science geo' }).click();
		await expect(page).toHaveURL('/orgs/geo');
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
		await expect(switcher.panel).toBeHidden();
		await expect(switcher.summary).toContainText('Organization: Earth Science, switch');

		await switcher.summary.click();
		await expect(switcher.panel.getByRole('link', { name: 'Earth Science geo' })).toHaveAttribute(
			'aria-current',
			'true'
		);
		await switcher.panel.getByRole('link', { name: 'All organizations' }).click();
		await expect(page).toHaveURL('/orgs');
		await expect(switcher.summary).toContainText('Organization: Earth Science, switch');
		// Catalogs leads to Earth Science, not to this page, which is in its section.
		const catalogs = page
			.getByRole('complementary', { name: 'Sidebar' })
			.getByRole('link', { name: 'Catalogs' });
		await expect(catalogs).toHaveAttribute('href', '/orgs/geo');
		await expect(catalogs).toHaveAttribute('aria-current', 'true');
	});

	test('works with the keyboard alone', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/helio');
		const switcher = organizationSwitcher(page);
		const link = (name: string) => switcher.panel.getByRole('link', { name });

		await switcher.summary.focus();
		await page.keyboard.press('Enter');
		await expect(switcher.panel).toBeVisible();
		await page.keyboard.press('ArrowDown');
		await expect(link('Earth Science geo')).toBeFocused();
		await page.keyboard.press('ArrowDown');
		await expect(link('Heliophysics Division helio')).toBeFocused();
		await page.keyboard.press('ArrowDown');
		await expect(link('All organizations')).toBeFocused();
		await page.keyboard.press('ArrowDown');
		await expect(link('Earth Science geo')).toBeFocused();
		await page.keyboard.press('End');
		await expect(link('All organizations')).toBeFocused();
		await page.keyboard.press('Home');
		await expect(link('Earth Science geo')).toBeFocused();

		await page.keyboard.press('Escape');
		await expect(switcher.panel).toBeHidden();
		await expect(switcher.summary).toBeFocused();

		await page.keyboard.press('Space');
		await expect(switcher.panel).toBeVisible();
		await page.keyboard.press('ArrowDown');
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL('/orgs/geo');
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
		await expect(switcher.panel).toBeHidden();
	});

	test("leaves a catalogs list's query behind, and keeps of a search what it reads", async ({
		page
	}) => {
		const dave = await ApiSession.as('dave');
		const first = await dave.get('catalogs?organization=helio&limit=1');
		const cursor =
			typeof first.body === 'object' && first.body !== null && 'next_cursor' in first.body
				? first.body.next_cursor
				: null;
		if (typeof cursor !== 'string') throw new Error('helio has a single catalog');

		await signIn(page, 'dave');
		await page.goto(`/orgs/helio?view=compact&cursor=${encodeURIComponent(cursor)}`);
		await expect(page.getByRole('link', { name: 'Space Weather' })).toBeVisible();
		await expect(page.getByRole('link', { name: 'Heliophysics', exact: true })).toHaveCount(0);

		const switcher = organizationSwitcher(page);
		await switcher.summary.click();
		const geo = switcher.panel.getByRole('link', { name: 'Earth Science geo' });
		// The list reads only its cursor and a notice, which belong to the page that shows them;
		// one link per organization would repeat anything else the address holds.
		await expect(geo).toHaveAttribute('href', '/orgs/geo');

		await page.goto(`/orgs/helio/search?junk=${'Z'.repeat(2000)}&q=wind&cursor=x`);
		await switcher.summary.click();
		await expect(geo).toHaveAttribute('href', '/orgs/geo/search?q=wind');
		await geo.click();
		await expect(page).toHaveURL('/orgs/geo/search?q=wind');
		await expect(page.getByRole('search', { name: 'Organization search' })).toBeVisible();
	});

	test('a single organization is a label with the link to all', async ({ page }) => {
		await signIn(page, 'erin');
		const banner = page.getByRole('banner');
		await expect(banner.locator('details').filter({ hasText: 'Organization:' })).toHaveCount(0);
		await expect(banner.getByText('Organization: Heliophysics Division')).toBeAttached();
		await banner.getByRole('link', { name: 'All organizations' }).click();
		await expect(page).toHaveURL('/orgs');
		await expect(page.getByRole('heading', { name: 'All organizations', level: 1 })).toBeVisible();
	});
});

test.describe('on a phone', () => {
	test.use({ viewport: VIEWPORTS.phone });

	test('the bottom navigation replaces the sidebar', async ({ page }) => {
		await signIn(page, 'erin');
		await expect(page.getByRole('complementary', { name: 'Sidebar' })).toBeHidden();
		await expect(page.getByRole('navigation', { name: 'Primary' })).toMatchAriaSnapshot(`
			- navigation "Primary":
			  - link "Catalogs":
			    - /url: /orgs/helio
			  - link "Search":
			    - /url: /orgs/helio/search
			  - link "Account":
			    - /url: /account
		`);
		// The search box of the banner gives way to the navigation's Search.
		await expect(page.getByRole('banner').getByRole('search')).toBeHidden();
		await page
			.getByRole('navigation', { name: 'Primary' })
			.getByRole('link', { name: 'Account' })
			.click();
		await expect(page).toHaveURL('/account');
	});

	test('the header menus open inside the screen', async ({ page }) => {
		await signIn(page, 'dave');
		for (const menu of [organizationSwitcher(page), accountMenu(page)]) {
			await menu.summary.click();
			await expect(menu.panel).toBeVisible();
			const box = await menu.panel.boundingBox();
			expect(box?.x).toBeGreaterThanOrEqual(0);
			expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(VIEWPORTS.phone.width);
			await page.keyboard.press('Escape');
		}
	});

	test('the current section stands out by more than its color', async ({ page }) => {
		await signIn(page, 'erin');
		const navigation = page.getByRole('navigation', { name: 'Primary' });
		await expectMarkedCurrent(
			navigation.getByRole('link', { name: 'Catalogs' }),
			navigation.getByRole('link', { name: 'Account' })
		);
	});

	test('each link of the bottom navigation has room for its whole focus ring on screen', async ({
		page
	}) => {
		await signIn(page, 'bob');
		const navigation = page.getByRole('navigation', { name: 'Primary' });
		for (const name of ['Catalogs', 'Search', 'Account']) {
			const link = navigation.getByRole('link', { name });
			await link.focus();
			expect(await ringBottom(link), name).toBeLessThanOrEqual(VIEWPORTS.phone.height);
		}
	});
});

test.describe('in forced colors', () => {
	test.use({ colorScheme: 'light' });

	test('filled controls keep their outline where the colors drop their fill', async ({ page }) => {
		await page.emulateMedia({ forcedColors: 'active' });
		await page.goto('/login');
		const controls = [page.getByRole('link', { name: 'Sign in with your company account' })];
		expect(await borderWidths(controls)).toEqual(['1px']);
		await signIn(page, 'bob');
		await page.goto('/catalogs/heliophysics/search');
		expect(
			await borderWidths([
				accountMenu(page).summary,
				page.getByRole('search', { name: 'Catalog search' }).getByRole('button', { name: 'Search' })
			])
		).toEqual(['1px', '1px']);
	});

	test('only the current tab of a sub-navigation is underlined', async ({ page }) => {
		// Forced colors draw every border in the text's color, a transparent one included.
		await page.emulateMedia({ forcedColors: 'active' });
		await signIn(page, 'carol');
		await page.goto('/catalogs/heliophysics/access');
		const tabs = page.getByRole('navigation', { name: 'Catalog' }).getByRole('link');
		await expect(tabs).toHaveCount(5);
		const underlines = await tabs.evaluateAll((links) =>
			links.map((link) => ({
				current: link.getAttribute('aria-current'),
				lines: [link, ...link.querySelectorAll('*')].filter((element) => {
					const style = getComputedStyle(element);
					return (
						style.display !== 'none' &&
						style.borderBottomStyle !== 'none' &&
						parseFloat(style.borderBottomWidth) > 0
					);
				}).length
			}))
		);
		expect(underlines.filter(({ lines }) => lines > 0)).toEqual([{ current: 'page', lines: 1 }]);
	});
});

/** Where a focused control's focus ring ends below it: 2px of outline, 2px away. */
async function ringBottom(control: Locator): Promise<number> {
	const box = await control.boundingBox();
	if (box === null) throw new Error('the control is not drawn');
	return box.y + box.height + 4;
}

/** The top border width of each control, as forced colors draw it. */
function borderWidths(controls: readonly Locator[]): Promise<string[]> {
	return Promise.all(
		controls.map((control) =>
			control.evaluate((element) => {
				const style = getComputedStyle(element);
				return style.borderTopStyle === 'none' ? '0px' : style.borderTopWidth;
			})
		)
	);
}

test.describe('on a phone held sideways', () => {
	// Below md, so the bottom navigation shows, with little height left for a menu.
	test.use({ viewport: { width: 667, height: 375 } });

	test("the switcher's last link stays clear of the bottom navigation", async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto('/orgs/helio');
		const switcher = organizationSwitcher(page);
		await switcher.summary.focus();
		await page.keyboard.press('Enter');
		await page.keyboard.press('End');
		const all = switcher.panel.getByRole('link', { name: 'All organizations' });
		await expect(all).toBeFocused();
		const link = await all.boundingBox();
		const navigation = await page.getByRole('navigation', { name: 'Primary' }).boundingBox();
		if (link === null || navigation === null) {
			throw new Error('the link or the navigation is hidden');
		}
		expect(link.y + link.height).toBeLessThanOrEqual(navigation.y);
		expect(await drawnOnTop(all)).toBe(true);
	});
});

test.describe('at tablet width', () => {
	test.use({ viewport: VIEWPORTS.tablet });

	test('the rail shows its labels and marks the current section', async ({ page }) => {
		await signIn(page, 'erin');
		const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
		const catalogs = sidebar.getByRole('link', { name: 'Catalogs' });
		const search = sidebar.getByRole('link', { name: 'Search' });
		const account = sidebar.getByRole('link', { name: 'Account' });
		// Nothing hover-only: not a tooltip, a label under each icon.
		for (const link of [catalogs, search, account]) {
			expect(await drawsLabelInside(link)).toBe(true);
		}
		await expectMarkedCurrent(catalogs, account);
		await search.click();
		await expect(page).toHaveURL('/orgs/helio/search');
		await expectMarkedCurrent(search, catalogs);
	});

	test('the search box shares the banner with the switcher', async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/orgs/helio');
		const box = await page.getByRole('banner').getByRole('search').boundingBox();
		const switcher = await page
			.getByRole('banner')
			.locator('details')
			.filter({ hasText: 'Organization:' })
			.boundingBox();
		if (box === null || switcher === null) throw new Error('the box or the switcher is hidden');
		expect(box.width).toBeGreaterThanOrEqual(200);
		expect(box.x + box.width).toBeLessThanOrEqual(switcher.x);
		expect(Math.abs(box.y + box.height / 2 - (switcher.y + switcher.height / 2))).toBeLessThan(2);
	});

	test("a single organization's name shows in full where the header has room", async ({ page }) => {
		await signIn(page, 'erin');
		const name = page.getByRole('banner').getByText('Heliophysics Division', { exact: true });
		await expect(name).toBeVisible();
		expect(await name.evaluate((element) => element.scrollWidth - element.clientWidth)).toBe(0);
	});
});
