import { expect } from '@playwright/test';
import { USERS } from './support/fixture.mjs';
import { signIn, stack, test } from './support/harness.ts';

/** `YYYY-MM-DD HH:mm UTC`, as the web formats timestamps. */
const TIMESTAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$/;

test.describe('the account page', () => {
	test("shows a contributor's identity, groups and roles", async ({ page }) => {
		await signIn(page, 'dave');
		await page.goto('/account');
		await expect(page).toHaveTitle('Account · Huron');
		const main = page.getByRole('main');

		const you = main.getByRole('region', { name: 'Signed in' });
		await expect(you.getByRole('definition').nth(0)).toHaveText(USERS.dave.name);
		await expect(you.getByRole('definition').nth(1)).toHaveText('dave');
		await expect(you.locator('time')).toHaveText(TIMESTAMP);

		const groups = main.getByRole('region', { name: 'Groups' });
		await expect(groups.locator('time')).toHaveText(TIMESTAMP);
		await expect(groups.getByRole('listitem')).toHaveText([...USERS.dave.groups].sort());
		await expect(groups).toContainText(
			'Groups are read when you sign in; if you were just added to a group, sign out and sign in again.'
		);

		const roles = main.getByRole('region', { name: 'Roles' });
		await expect(roles.getByRole('listitem').locator('p').first()).toHaveText(
			'You are a reader of Geoscience in Earth Science.'
		);
		await expect(roles.getByRole('listitem')).toHaveCount(3);
		await expect(roles).toContainText(
			'You are a contributor to Heliophysics in Heliophysics Division.'
		);
		await expect(roles).toContainText(
			'You are a contributor to Space Weather in Heliophysics Division.'
		);
		const geoscience = roles.getByRole('link', { name: 'Geoscience' });
		await expect(geoscience).toHaveAttribute('href', '/catalogs/geoscience');
		// Within a sentence, color alone would not set the link apart.
		await expect(geoscience).toHaveCSS('text-decoration-line', 'underline');

		const cli = main.getByRole('region', { name: 'Sign in and see what Huron knows about you' });
		await expect(cli.locator('code')).toHaveText('huron login\nhuron whoami');
		expect(await main.textContent()).not.toContain(stack.apiUrl);
	});

	test('names the scope of administrator roles', async ({ page }) => {
		await signIn(page, 'alice');
		await page.goto('/account');
		const roles = page.getByRole('main').getByRole('region', { name: 'Roles' });
		await expect(roles.getByRole('listitem')).toHaveCount(1);
		await expect(roles).toContainText('You are a platform administrator.');
		await expect(roles).toContainText('You can create organizations');
	});

	test("links an organization administrator's organization", async ({ page }) => {
		await signIn(page, 'bob');
		await page.goto('/account');
		const roles = page.getByRole('main').getByRole('region', { name: 'Roles' });
		await expect(roles).toContainText(
			'You are an organization administrator of Heliophysics Division.'
		);
		await roles.getByRole('link', { name: 'Heliophysics Division' }).click();
		await expect(page).toHaveURL('/orgs/helio');
	});

	test('explains an account without groups or roles, and signs out', async ({ page }) => {
		await signIn(page, 'mallory');
		await page.goto('/account');
		const main = page.getByRole('main');
		await expect(main.getByText('Huron received no groups for your account.')).toBeVisible();
		await expect(main.getByText('Your groups hold no roles in Huron.')).toBeVisible();
		await main.getByRole('button', { name: 'Sign out', exact: true }).click();
		await expect(page).toHaveURL('/login?status=signed-out');
	});
});
