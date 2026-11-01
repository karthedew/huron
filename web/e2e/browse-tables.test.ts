import { expect, type Locator } from '@playwright/test';
import { COLLECTIONS } from './support/fixture.mjs';
import { ApiSession, signIn, test } from './support/harness.ts';

interface BrowseRecord {
	name: string;
	created_by: string;
	created_at: string;
}

type Column = keyof BrowseRecord;

const COLUMNS: readonly { key: Column; label: string }[] = [
	{ key: 'name', label: 'Name' },
	{ key: 'created_by', label: 'Created by' },
	{ key: 'created_at', label: 'Created at' }
];

const LISTS = [
	{
		label: 'Catalogs',
		path: '/orgs/helio',
		api: 'catalogs?organization=helio&limit=100',
		prefix: '',
		pager: 'Catalog pages'
	},
	{
		label: 'Namespaces in stations',
		path: '/catalogs/space-weather/namespaces/stations',
		api: 'catalogs/space-weather/namespaces?parent=stations&limit=100',
		prefix: 'namespaces_',
		pager: 'Namespace pages'
	},
	{
		label: 'Collections in fields',
		path: '/catalogs/heliophysics/namespaces/fields',
		api: 'catalogs/heliophysics/namespaces/fields/collections?limit=100',
		prefix: 'collections_',
		pager: 'Collection pages'
	}
];

/** Only the fields these table assertions use, checked at the network boundary. */
function records(body: unknown): BrowseRecord[] {
	if (
		typeof body !== 'object' ||
		body === null ||
		!('items' in body) ||
		!Array.isArray(body.items)
	) {
		throw new Error('Expected a list answer');
	}
	return body.items.map((item: unknown) => {
		if (
			typeof item !== 'object' ||
			item === null ||
			!('name' in item) ||
			!('created_by' in item) ||
			!('created_at' in item) ||
			typeof item.name !== 'string' ||
			typeof item.created_by !== 'string' ||
			typeof item.created_at !== 'string'
		) {
			throw new Error('Expected a browse record');
		}
		return { name: item.name, created_by: item.created_by, created_at: item.created_at };
	});
}

/** The primary link in each row, apart from secondary schema links in a catalog. */
async function names(table: Locator): Promise<string[]> {
	return table
		.getByRole('rowheader')
		.evaluateAll((headers) =>
			headers.map((header) => header.querySelector('a')?.textContent?.trim() ?? '')
		);
}

/** Expected global ordering, including the name tie-break in the selected direction. */
function ordered(items: BrowseRecord[], column: Column, order: 'asc' | 'desc'): string[] {
	const direction = order === 'asc' ? 1 : -1;
	return [...items]
		.sort((left, right) => {
			const a = left[column];
			const b = right[column];
			return (
				direction *
				(a < b ? -1 : a > b ? 1 : left.name < right.name ? -1 : left.name > right.name ? 1 : 0)
			);
		})
		.map(({ name }) => name);
}

test.describe('browse tables', () => {
	test('keyboard focus reveals every sort header and its outline on a phone', async ({
		page
	}, testInfo) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await signIn(page, 'erin');
		await page.goto('/catalogs/heliophysics/namespaces/fields');
		const region = page.getByRole('region', { name: 'Collections in fields table' });
		for (const colorScheme of ['light', 'dark'] as const) {
			if (colorScheme === 'dark') await page.getByRole('button', { name: 'Use dark mode' }).click();
			await region.focus();
			for (const column of COLUMNS) {
				await page.keyboard.press('Tab');
				const link = region.getByRole('link', {
					name: `Sort by ${column.label} ${column.key === 'name' ? 'descending' : 'ascending'}`
				});
				await expect(link).toBeFocused();
				await expect
					.poll(() =>
						link.evaluate((element) => {
							const bounds = element.getBoundingClientRect();
							const viewport = element.closest('[role="region"]')?.getBoundingClientRect();
							if (!viewport) throw new Error('The table needs a scroll region');
							return Math.min(bounds.left - viewport.left - 1, viewport.right - bounds.right - 1);
						})
					)
					.toBeGreaterThanOrEqual(4);
				if (column.key === 'created_by') {
					await page.screenshot({
						path: testInfo.outputPath(`phone-sort-focus-${colorScheme}.png`)
					});
				}
			}
		}
	});

	for (const list of LISTS) {
		test(`${list.label} sorts every page by each column in both directions`, async ({ page }) => {
			const api = await ApiSession.as('erin');
			const answer = await api.get(list.api);
			expect(answer.status).toBe(200);
			const all = records(answer.body);
			await signIn(page, 'erin');
			for (const column of COLUMNS) {
				for (const order of ['asc', 'desc'] as const) {
					const query = new URLSearchParams({
						[list.prefix + 'sort']: column.key,
						[list.prefix + 'order']: order
					});
					await page.goto(`${list.path}?${query}`);
					const table = page.getByRole('table', { name: list.label });
					const expected = ordered(all, column.key, order);
					await expect.poll(() => names(table)).toEqual(expected.slice(0, 20));
					await expect(
						table.getByRole('columnheader', {
							name: `Sort by ${column.label} ${order === 'asc' ? 'descending' : 'ascending'}`
						})
					).toHaveAttribute('aria-sort', order === 'asc' ? 'ascending' : 'descending');
					const next = page
						.getByRole('navigation', { name: list.pager })
						.getByRole('link', { name: 'Next page' });
					if (expected.length > 20) {
						await next.click();
						await expect.poll(() => names(table)).toEqual(expected.slice(20, 40));
						const current = new URL(page.url());
						expect(current.searchParams.get(list.prefix + 'sort')).toBe(column.key);
						expect(current.searchParams.get(list.prefix + 'order')).toBe(order);
						expect(current.searchParams.get(list.prefix + 'cursor')).not.toBeNull();
					} else {
						await expect(next).toHaveCount(0);
					}
				}
			}
		});
	}

	test('sort headers and paging work without scripts and changing the sort restarts its page', async ({
		browser
	}) => {
		const context = await browser.newContext({ javaScriptEnabled: false });
		try {
			const runs = COLLECTIONS.filter(
				({ catalog, namespace, state }) =>
					catalog === 'heliophysics' && namespace === 'fields' && state !== 'draft'
			)
				.map(({ name }) => name)
				.sort();
			const page = await context.newPage();
			await signIn(page, 'erin');
			await page.goto('/catalogs/heliophysics/namespaces/fields');
			const table = page.getByRole('table', { name: 'Collections in fields' });
			await table.getByRole('link', { name: 'Sort by Name descending' }).click();
			await expect(table.getByRole('rowheader').first().getByRole('link')).toHaveText(
				runs[runs.length - 1]
			);
			await page
				.getByRole('navigation', { name: 'Collection pages' })
				.getByRole('link', { name: 'Next page' })
				.click();
			await expect(table.getByRole('rowheader').first().getByRole('link')).toHaveText(
				runs[runs.length - 21]
			);
			await table.getByRole('link', { name: 'Sort by Name ascending' }).click();
			await expect(table.getByRole('rowheader').first().getByRole('link')).toHaveText(runs[0]);
			expect(new URL(page.url()).searchParams.get('collections_cursor')).toBeNull();
			await expect(table.getByRole('rowheader')).toHaveCount(20);
		} finally {
			await context.close();
		}
	});
});
