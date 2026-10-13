import { test, expect, type Page } from '@playwright/test';
import { randomUUID, createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { signIn } from './helpers';
const destination = '/ingestion?catalog=huron-local&namespace=%5B%22science%22%5D';
async function start(page: Page, name = `raw-${randomUUID().slice(0, 8)}`) {
	await signIn(page, 'admin', undefined, destination);
	await page.getByRole('textbox', { name: 'Dataset name', exact: true }).fill(name);
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	return name;
}
async function metadata(page: Page) {
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await page
		.getByRole('textbox', { name: 'Revision title', exact: true })
		.fill('Mission observations');
	await page.getByRole('textbox', { name: 'Creators', exact: true }).fill('Mission science team');
	await page
		.getByRole('textbox', { name: 'Description', exact: true })
		.fill('Complete calibrated source submission.');
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
}
async function publish(page: Page) {
	await page.getByRole('button', { name: 'Upload and commit', exact: true }).click();
	await expect(page.getByText(/Revision \d+ committed and registered/)).toBeVisible();
	await page.getByRole('link', { name: 'Browse uploaded files' }).click();
}

test('uploads real bytes, browses the immutable manifest and downloads exact contents', async ({
	page
}) => {
	await start(page);
	const contents = Buffer.from('time,value\n0,42\n'.repeat(80000));
	await page.getByLabel('Add files', { exact: true }).setInputFiles({
		name: 'observations.csv',
		mimeType: 'text/csv',
		buffer: contents
	});
	await metadata(page);
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'Revision title', exact: true })).toHaveValue(
		'Mission observations'
	);
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await publish(page);
	await expect(page.getByRole('heading', { name: 'Revision 1 files' })).toBeVisible();
	const download = page.getByRole('link', {
		name: 'Download payload/observations.csv',
		exact: true
	});
	const url = await download.getAttribute('href');
	expect(url).toBeTruthy();
	const response = await page.request.get(url!);
	expect(response.status()).toBe(200);
	expect(await response.body()).toEqual(contents);
	await page.getByText('SHA-256', { exact: true }).click();
	await expect(
		page.getByText(createHash('sha256').update(contents).digest('hex'), { exact: true })
	).toBeVisible();
	await page.getByRole('link', { name: 'History', exact: true }).click();
	await expect(page.getByRole('link', { name: 'Revision 1', exact: true })).toBeVisible();
});

test('directory paths survive, and a new revision contains only its own files', async ({
	page
}) => {
	const directory = await mkdtemp(join(tmpdir(), 'huron-upload-'));
	try {
		await mkdir(join(directory, 'north'));
		await mkdir(join(directory, 'south'));
		await writeFile(join(directory, 'north', 'same.csv'), 'north');
		await writeFile(join(directory, 'south', 'same.csv'), 'south');
		const name = await start(page);
		await page.getByLabel('Add directory', { exact: true }).setInputFiles(directory);
		await expect(page.getByRole('list', { name: 'Selected files' })).toContainText(
			'/north/same.csv'
		);
		await expect(page.getByRole('list', { name: 'Selected files' })).toContainText(
			'/south/same.csv'
		);
		await metadata(page);
		await publish(page);
		await expect(page.getByRole('list', { name: 'Revision files' })).toContainText(
			'/north/same.csv'
		);
		await page.getByRole('link', { name: 'Upload revision', exact: true }).click();
		await expect(page.getByRole('textbox', { name: 'Dataset name', exact: true })).toHaveValue(
			name
		);
		await page.getByRole('button', { name: 'Continue', exact: true }).click();
		await page.getByLabel('Add files', { exact: true }).setInputFiles({
			name: 'replacement.txt',
			mimeType: 'text/plain',
			buffer: Buffer.from('second independent revision')
		});
		await metadata(page);
		await publish(page);
		await expect(page.getByRole('heading', { name: 'Revision 2 files' })).toBeVisible();
		await expect(page.getByRole('list', { name: 'Revision files' })).toContainText(
			'replacement.txt'
		);
		await expect(page.getByRole('list', { name: 'Revision files' })).not.toContainText('same.csv');
		await page.getByRole('link', { name: 'History', exact: true }).click();
		await page.getByRole('link', { name: 'Revision 1', exact: true }).click();
		await expect(page.getByRole('list', { name: 'Revision files' })).toContainText(
			'/south/same.csv'
		);
	} finally {
		await rm(directory, { recursive: true, force: true });
	}
});

test('retries an uncertain committed response without creating a second revision', async ({
	page
}) => {
	await start(page);
	await page.getByLabel('Add files', { exact: true }).setInputFiles({
		name: 'retry.txt',
		mimeType: 'text/plain',
		buffer: Buffer.from('retained upload')
	});
	await metadata(page);
	let interrupted = false;
	const keys: string[] = [];
	await page.route('**/ingestion/api/uploads/*/commit?*', async (route) => {
		keys.push(route.request().headers()['idempotency-key']);
		if (!interrupted) {
			interrupted = true;
			await route.fetch();
			await route.abort('connectionreset');
		} else await route.continue();
	});
	await page.getByRole('button', { name: 'Upload and commit', exact: true }).click();
	await expect(page.getByRole('alert')).toBeVisible();
	await page.getByRole('button', { name: 'Retry upload', exact: true }).click();
	await expect(page.getByText('Revision 1 committed and registered')).toBeVisible();
	expect(keys).toHaveLength(2);
	expect(keys[0]).toBe(keys[1]);
	await page.getByRole('link', { name: 'Browse uploaded files' }).click();
	await page.getByRole('link', { name: 'History', exact: true }).click();
	await expect(page.getByRole('link', { name: 'Revision 1', exact: true })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Revision 2', exact: true })).toHaveCount(0);
});

test('rejects conflicting file paths and requires revision metadata', async ({ page }) => {
	await start(page);
	const file = { name: 'same.csv', mimeType: 'text/csv', buffer: Buffer.from('1') };
	await page.getByLabel('Add files', { exact: true }).setInputFiles(file);
	await page.getByLabel('Add files', { exact: true }).setInputFiles({ ...file, name: 'SAME.csv' });
	await expect(page.getByText(/Duplicate source path:/)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: 'Remove payload/SAME.csv', exact: true }).click();
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled();
	await page.getByRole('textbox', { name: 'Revision title', exact: true }).fill('Title');
	await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled();
});

for (const width of [390, 816, 1440])
	test(`ingestion stays usable at ${width}px in both themes`, async ({ page }) => {
		await page.setViewportSize({ width, height: 1000 });
		await signIn(page, 'admin', undefined, destination);
		for (const theme of ['light', 'dark']) {
			await page.evaluate((mode) => {
				document.documentElement.dataset.theme = mode;
			}, theme);
			await expect(page.getByRole('navigation', { name: 'Organization catalogs' })).toBeVisible();
			await expect(page.getByRole('button', { name: 'huron-local', exact: true })).toBeVisible();
			expect(
				await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
			).toBe(true);
			await page
				.getByRole('textbox', { name: 'Dataset name', exact: true })
				.fill('responsive-example');
			await page.getByRole('button', { name: 'Continue', exact: true }).click();
			await expect(page.getByLabel('Add directory', { exact: true })).toBeVisible();
			expect(
				await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
			).toBe(true);
			await page.getByRole('button', { name: 'Back', exact: true }).click();
		}
	});

test('a confirmed preflight rejection preserves files and metadata for editing', async ({
	page
}) => {
	await start(page);
	await page.getByLabel('Add files', { exact: true }).setInputFiles({
		name: 'retained.csv',
		mimeType: 'text/csv',
		buffer: Buffer.from('retained source')
	});
	await metadata(page);
	await page.route(
		'**/ingestion/api/uploads',
		(route) =>
			route.fulfill({
				status: 409,
				contentType: 'application/json',
				body: JSON.stringify({
					message: 'The selected catalog path changed.',
					uploadNotStarted: true
				})
			}),
		{ times: 1 }
	);
	await page.getByRole('button', { name: 'Upload and commit', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('The selected catalog path changed.');
	await expect(page.getByRole('button', { name: 'Back', exact: true })).toBeEnabled();
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'Revision title', exact: true })).toHaveValue(
		'Mission observations'
	);
	await expect(page.getByRole('textbox', { name: 'Creators', exact: true })).toHaveValue(
		'Mission science team'
	);
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByRole('list', { name: 'Selected files' })).toContainText(
		'payload/retained.csv'
	);
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'Dataset name', exact: true })).toBeEditable();
});

test('cannot advance while a newly selected destination is still loading', async ({ page }) => {
	await signIn(page, 'admin', undefined, destination);
	await page
		.getByRole('textbox', { name: 'Dataset name', exact: true })
		.fill('pending-destination');
	let release = () => {};
	const pending = new Promise<void>((resolve) => (release = resolve));
	await page.route('**/ingestion/api/targets?*', async (route) => {
		await pending;
		await route.continue();
	});
	try {
		await page
			.getByRole('navigation', { name: 'Organization catalogs' })
			.getByRole('button', { name: 'huron-local', exact: true })
			.click();
		await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled();
		await expect(page.getByText('Loading the destination…', { exact: true })).toBeVisible();
	} finally {
		release();
	}
	await expect(page.getByRole('button', { name: 'science', exact: true })).toBeVisible();
	await expect(page.getByRole('textbox', { name: 'Dataset name', exact: true })).toHaveValue('');
});
