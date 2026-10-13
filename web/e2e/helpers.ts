import { randomUUID } from 'node:crypto';
import { expect, type Page } from '@playwright/test';

export const ADMIN_PASSWORD = 'browser-admin-password';
export const USER_PASSWORD = 'browser-user-password';
export const repositoryUrl = '/browse?catalog=huron-local&namespace=%5B%22science%22%5D';

export async function openPage(page: Page, path: string) {
	return page.goto(path, { waitUntil: 'networkidle' });
}

export async function signIn(
	page: Page,
	username = 'admin',
	password = ADMIN_PASSWORD,
	returnTo = '/'
) {
	await page.context().clearCookies();
	await openPage(page, `/login?returnTo=${encodeURIComponent(returnTo)}`);
	await page.getByLabel('Username', { exact: true }).fill(username);
	await page.getByLabel('Password', { exact: true }).fill(password);
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();
	await expect(page).toHaveURL(returnTo);
}

export async function createUser(page: Page, catalog = '', role = 'reader') {
	const username = `scientist-${randomUUID().slice(0, 8)}`;
	await openPage(page, '/admin?tab=users');
	const form = page
		.locator('form')
		.filter({ has: page.getByRole('button', { name: 'Create Huron user', exact: true }) });
	await form.getByLabel('Username', { exact: true }).fill(username);
	await form.getByLabel('Display name', { exact: true }).fill(`Scientist ${username}`);
	await form.getByLabel('Initial password').fill(USER_PASSWORD);
	await form.getByLabel('Initial catalog').selectOption(catalog);
	await form.getByLabel('Initial role').selectOption(role);
	await form.getByRole('button', { name: 'Create Huron user', exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: `User ${username} created` })
	).toBeVisible();
	return username;
}

export async function setMembership(page: Page, catalog: string, username: string, role: string) {
	await openPage(page, `/settings/catalog?catalog=${encodeURIComponent(catalog)}`);
	await page.getByLabel('Find a user').fill(username);
	const form = page.locator('form').filter({
		has: page.getByRole('button', { name: `Save access for ${username}`, exact: true })
	});
	await form.getByLabel('Catalog role').selectOption(role);
	await form.getByRole('button', { name: `Save access for ${username}`, exact: true }).click();
	await expect(
		page.getByRole('status').filter({ hasText: 'Catalog membership saved in Polaris.' })
	).toBeVisible();
}
