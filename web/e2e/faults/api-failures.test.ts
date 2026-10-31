import { expect } from '@playwright/test';
import {
	COOKIES,
	SIGN_IN_LINK,
	chooseUser,
	faults,
	signIn,
	test,
	webCookie
} from '../support/harness.ts';

test.afterEach(async () => {
	await faults('oscar', null);
});

test.describe('when the API stops accepting the Huron token', () => {
	test('a page load ends the session and signing in again resumes', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'unauthorized');
		await page.goto('/?from=bookmark');
		await expect(page).toHaveURL('/login?status=expired&returnTo=%2F%3Ffrom%3Dbookmark');
		await expect(page.getByRole('status')).toHaveText(
			'Your session ended. Sign in again to continue.'
		);
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();

		await faults('oscar', null);
		await page.getByRole('link', { name: SIGN_IN_LINK }).click();
		await chooseUser(page, 'oscar');
		await expect(page).toHaveURL('/orgs/helio');
		await expect(
			page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
	});

	test('a data request gets the redirect the client router follows', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'unauthorized');
		const response = await page.request.get('/__data.json');
		expect(await response.json()).toEqual({
			type: 'redirect',
			location: '/login?status=expired&returnTo=%2F'
		});
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();
	});
});

test.describe('when the API fails', () => {
	test('an outage keeps the shell, shows the 503 page and recovers', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'unavailable');
		const response = await page.goto('/');
		expect(response?.status()).toBe(503);
		const main = page.getByRole('main');
		await expect(main.getByRole('heading', { level: 1 })).toHaveText(
			"The Huron service isn't responding."
		);
		const banner = page.getByRole('banner');
		await expect(banner).toBeVisible();
		await expect(banner.getByText('Organizations unavailable')).toBeVisible();
		await expect(banner.getByRole('link', { name: 'Try again' })).toBeVisible();
		await expect(page.getByText(/^Reference /)).toHaveCount(0);
		await expect(page).toHaveTitle('Service unavailable · Huron');
		expect(await webCookie(page.context(), COOKIES.session)).toBeDefined();

		await faults('oscar', null);
		await main.getByRole('link', { name: 'Try again' }).click();
		await expect(page).toHaveURL('/orgs/helio');
		await expect(
			page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
		await expect(banner.getByText('Organizations unavailable')).toHaveCount(0);
	});

	test('the account page still shows who is signed in during an outage', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'unavailable');
		const response = await page.goto('/account');
		expect(response?.status()).toBe(200);
		const main = page.getByRole('main');
		await expect(main.getByRole('region', { name: 'Signed in' })).toContainText('Oscar Ortiz');
		await expect(main.getByRole('region', { name: 'Roles' })).toContainText(
			"Your roles couldn't be loaded."
		);
		await expect(page.getByRole('banner').getByText('Organizations unavailable')).toBeVisible();
		await main.getByRole('button', { name: 'Sign out', exact: true }).click();
		await expect(page).toHaveURL('/login?status=signed-out');
	});

	test('an internal error shows the API request id as its reference', async ({ page }) => {
		await signIn(page, 'oscar');
		const { requestId } = await faults('oscar', 'error500');
		const response = await page.goto('/');
		expect(response?.status()).toBe(500);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Something went wrong.');
		await expect(page.getByText(`Reference ${requestId}`)).toBeVisible();
		await expect(page.getByRole('banner')).toBeVisible();
	});

	test('a dropped connection counts as an outage', async ({ page }) => {
		await signIn(page, 'oscar');
		await faults('oscar', 'reset');
		const response = await page.goto('/');
		expect(response?.status()).toBe(503);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(
			"The Huron service isn't responding."
		);
		await expect(page.getByText(/^Reference /)).toHaveCount(0);
	});
});
