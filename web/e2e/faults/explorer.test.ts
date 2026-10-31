import { expect } from '@playwright/test';
import { COOKIES, faults, signIn, test, webCookie } from '../support/harness.ts';

test.afterEach(async () => {
	await faults('oscar', null);
});

test.describe("the explorer's tree fetch", () => {
	test('sends the user to sign in again when the API no longer accepts the token', async ({
		page
	}) => {
		await signIn(page, 'oscar');
		await page.goto('/catalogs/heliophysics?from=bookmark');
		const toggle = page
			.getByRole('navigation', { name: 'Explorer' })
			.getByRole('button', { name: 'Contents of solar-wind' });
		await expect(toggle).toBeVisible();
		await faults('oscar', 'unauthorized');
		const answer = page.waitForResponse((response) => response.url().includes('/tree?parent='));
		await toggle.click();
		expect((await answer).status()).toBe(401);
		await expect(page).toHaveURL(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics%3Ffrom%3Dbookmark'
		);
		await expect(page.getByRole('status')).toHaveText(
			'Your session ended. Sign in again to continue.'
		);
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();
	});

	test('says when a folder could not load and loads it on Retry', async ({ page }) => {
		await signIn(page, 'oscar');
		await page.goto('/catalogs/heliophysics');
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		const toggle = tree.getByRole('button', { name: 'Contents of solar-wind' });
		await expect(toggle).toBeVisible();
		await faults('oscar', 'unavailable');
		await toggle.click();
		const retry = tree.getByRole('button', { name: 'Retry loading solar-wind' });
		await expect(retry).toBeVisible();
		await expect(tree.getByText("Couldn't load ·")).toBeVisible();
		await expect(tree.getByRole('status')).toHaveText("Couldn't load solar-wind.");
		await expect(toggle).toHaveAttribute('aria-expanded', 'true');

		await faults('oscar', null);
		await retry.click();
		await expect(tree.getByRole('link', { name: 'ace', exact: true })).toBeVisible();
		await expect(retry).toHaveCount(0);
		await expect(toggle).toBeFocused();
		// The page itself never failed: the session lives on.
		await expect(page).toHaveURL('/catalogs/heliophysics');
	});

	test("forgets a folder's failure once the page brings its contents", async ({ page }) => {
		await signIn(page, 'oscar');
		await page.goto('/catalogs/heliophysics');
		const tree = page.getByRole('navigation', { name: 'Explorer' });
		const toggle = tree.getByRole('button', { name: 'Contents of solar-wind' });
		await expect(toggle).toBeVisible();
		await faults('oscar', 'unavailable');
		await toggle.click();
		await expect(tree.getByRole('button', { name: 'Retry loading solar-wind' })).toBeVisible();

		await faults('oscar', null);
		await page
			.getByRole('main')
			.getByRole('list', { name: 'Top-level namespaces' })
			.getByRole('link', { name: 'solar-wind' })
			.click();
		await expect(page).toHaveURL('/catalogs/heliophysics/namespaces/solar-wind');
		await expect(tree.getByRole('link', { name: 'ace', exact: true })).toBeVisible();
		await expect(tree.getByText("Couldn't load ·")).toHaveCount(0);
		await expect(tree.getByRole('button', { name: 'Retry loading solar-wind' })).toHaveCount(0);
	});
});
