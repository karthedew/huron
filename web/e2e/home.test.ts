import { expect } from '@playwright/test';
import { ORGANIZATIONS, visibleOrganizations } from './support/fixture.mjs';
import {
	ApiSession,
	COOKIES,
	organizationSwitcher,
	rememberOrganization,
	signIn,
	test,
	webCookie
} from './support/harness.ts';

/** The fixture organization of that name. */
function organization(name: string) {
	const found = ORGANIZATIONS.find((candidate) => candidate.name === name);
	if (found === undefined) throw new Error(`no fixture organization ${name}`);
	return found;
}

test.describe('the start page', () => {
	test('a user with one organization goes straight to it', async ({ page }) => {
		expect(visibleOrganizations('erin')).toEqual(['helio']);
		await signIn(page, 'erin');
		await expect(page).toHaveURL('/orgs/helio');
		await expect(
			page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
	});

	test('a user with several organizations chooses from the list', async ({ page }) => {
		expect(visibleOrganizations('dave')).toEqual(['geo', 'helio']);
		await signIn(page, 'dave');
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();
		await expect(page).toHaveTitle('Organizations · Huron');

		const catalogs: Record<string, string> = { helio: '2 catalogs', geo: '1 catalog' };
		for (const name of visibleOrganizations('dave')) {
			const { displayName, description } = organization(name);
			const card = page.getByRole('link', { name: new RegExp(`^${displayName}`) });
			await expect(card).toContainText(name);
			await expect(card).toContainText(description);
			await expect(card).toContainText(catalogs[name]);
		}
		await expect(
			page.getByRole('link', { name: new RegExp(`^${organization('astro').displayName}`) })
		).toHaveCount(0);

		await page.getByRole('link', { name: /^Earth Science/ }).click();
		await expect(page).toHaveURL('/orgs/geo');
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
	});

	test('the browser remembers the organization it last showed', async ({ page, context }) => {
		await signIn(page, 'dave');
		await expect(page).toHaveURL('/');
		expect(await webCookie(context, COOKIES.organization)).toBeUndefined();

		await page.getByRole('link', { name: /^Earth Science/ }).click();
		await expect(page.getByRole('heading', { name: 'Earth Science', level: 1 })).toBeVisible();
		await expect
			.poll(async () => (await webCookie(context, COOKIES.organization))?.value)
			.toBe('geo');
		const remembered = await webCookie(context, COOKIES.organization);
		expect(remembered).toMatchObject({ httpOnly: false, sameSite: 'Lax', path: '/' });
		const yearFromNow = Date.now() / 1000 + 365 * 24 * 3600;
		expect(Math.abs((remembered?.expires ?? 0) - yearFromNow)).toBeLessThan(120);

		await page.goto('/');
		await expect(page).toHaveURL('/orgs/geo');
		await expect(organizationSwitcher(page).summary).toContainText(
			'Organization: Earth Science, switch'
		);
	});

	test('a remembered organization that is hidden, unknown or malformed is ignored', async ({
		page,
		context
	}) => {
		await signIn(page, 'dave');
		// Values the browser never writes itself: only a hand-made cookie holds them.
		for (const remembered of ['astro', 'gone', 'Not%20a%20name']) {
			await rememberOrganization(context, remembered);
			await page.goto('/');
			await expect(page, `huron_org=${remembered}`).toHaveURL('/');
			await expect(page.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();
			await expect(organizationSwitcher(page).summary).toHaveText('Choose organization');
		}
	});

	test('a user without organizations learns why and can sign in again', async ({ page }) => {
		await signIn(page, 'mallory');
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('banner')).toBeVisible();
		await expect(page.getByRole('banner').getByText('No organizations')).toBeVisible();
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();
		await expect(main.getByText("You don't have access to any organization yet.")).toBeVisible();
		await expect(main.getByText('Huron received no groups for your account.')).toBeVisible();
		await expect(
			main.getByText(
				'Groups are read when you sign in; if you were just added to a group, sign out and sign in again.'
			)
		).toBeVisible();

		await main.getByRole('button', { name: 'Sign out', exact: true }).click();
		await expect(page).toHaveURL('/login?status=signed-out');
	});
});

test('an organization the user cannot see is concealed as not found', async ({ page }) => {
	const [alice, erin] = await Promise.all([ApiSession.as('alice'), ApiSession.as('erin')]);
	expect((await alice.get('organizations/astro')).status).toBe(200);
	expect((await erin.get('organizations/astro')).status).toBe(404);

	await signIn(page, 'erin');
	const visible = await page.goto('/orgs/helio');
	expect(visible?.status()).toBe(200);
	await expect(
		page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
	).toBeVisible();

	const concealed = await page.goto('/orgs/astro');
	expect(concealed?.status()).toBe(404);
	await expect(page.getByRole('banner')).toBeVisible();
	const main = page.getByRole('main');
	await expect(main.getByRole('heading', { level: 1 })).toHaveText(
		"Not found, or you don't have access."
	);
	await expect(main.getByText('Groups are read when you sign in')).toBeVisible();
	await expect(main.getByRole('link', { name: 'Back to Heliophysics Division' })).toHaveAttribute(
		'href',
		'/orgs/helio'
	);
	await expect(page.getByText(/^Reference /)).toHaveCount(0);
	await expect(page).toHaveTitle('Not found · Huron');
});

test('a page that fails keeps the organization the user was in', async ({ page }) => {
	expect(visibleOrganizations('dave')).toEqual(['geo', 'helio']);
	await signIn(page, 'dave');
	await page.goto('/orgs/helio');
	await expect(
		page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
	).toBeVisible();
	await expect
		.poll(async () => (await webCookie(page.context(), COOKIES.organization))?.value)
		.toBe('helio');

	const expectStillInHelio = async () => {
		await expect(page).toHaveURL('/orgs/astro');
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { level: 1 })).toHaveText(
			"Not found, or you don't have access."
		);
		await expect(main.getByRole('link', { name: 'Back to Heliophysics Division' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
		await expect(organizationSwitcher(page).summary).toContainText(
			'Organization: Heliophysics Division, switch'
		);
		await expect(
			page.getByRole('complementary', { name: 'Sidebar' }).getByRole('link', { name: 'Catalogs' })
		).toHaveAttribute('href', '/orgs/helio');
	};

	// The client router renders the error page without the failed page's data; a value set on
	// `window` survives only such a navigation.
	await page.evaluate(() => Reflect.set(window, 'huronClientNavigation', true));
	await page.getByRole('main').evaluate((main) => {
		const link = document.createElement('a');
		link.href = '/orgs/astro';
		link.textContent = 'A concealed organization';
		main.append(link);
	});
	await page.getByRole('link', { name: 'A concealed organization' }).click();
	await expectStillInHelio();
	expect(await page.evaluate(() => Reflect.get(window, 'huronClientNavigation'))).toBe(true);

	await page.reload();
	await expectStillInHelio();
});
