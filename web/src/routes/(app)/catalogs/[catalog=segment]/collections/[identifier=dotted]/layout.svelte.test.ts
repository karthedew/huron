import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, collectionOf } from '$lib/testing/catalog-data';
import Layout from './+layout.svelte';
vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(() => {
	resetAppState();
	Reflect.deleteProperty(navigator, 'clipboard');
});
async function show(
	route = '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]',
	collection = collectionOf()
) {
	page.route = { id: route };
	render(Layout, {
		props: {
			data: { ...catalogPageData(), collection, trail: [] },
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			children: createRawSnippet(() => ({ render: () => '<p>The tab</p>' }))
		}
	});
	await tick();
}
describe('Collection header', () => {
	it('shows the name and copies the complete logical path', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		await show();
		const header = screen.getByRole('banner');
		expect(
			within(header).getByRole('heading', { level: 1, name: 'ACE magnetometer level 2, 2024' })
		).toBeInTheDocument();
		await within(header).getByRole('button', { name: 'Copy full path' }).click();
		expect(writeText).toHaveBeenCalledWith('heliophysics.solar-wind.ace.mag-l2-2024');
		expect(within(header).queryByText('Share path')).toBeNull();
		expect(screen.getByText('The tab')).toBeInTheDocument();
	});
	it('links every section and marks CLI as the current page', async () => {
		await show('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/cli');
		const links = within(screen.getByRole('navigation', { name: 'Collection' })).getAllByRole(
			'link'
		);
		expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Overview', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'],
			['Metadata', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/metadata'],
			['Files3', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/files'],
			['Commits', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/commits'],
			['Activity', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/activity'],
			['Schema', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/schema'],
			['CLI', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/cli']
		]);
		expect(links.filter((link) => link.getAttribute('aria-current') === 'page')).toEqual([
			links.at(-1)
		]);
	});

	it('says nothing of a commit while no commit holds the collection', async () => {
		await show();
		expect(within(screen.getByRole('banner')).queryByText(/A commit is/)).toBeNull();
	});

	it.each([
		['accepted', 'A commit is in progress since 2026-10-04 09:00 UTC.'],
		['blocked', 'A commit is blocked since 2026-10-04 09:00 UTC.']
	])('shows a %s commit as read-only text in the header', async (state, sentence) => {
		const since = '2026-10-04T09:00:00+00:00';
		await show(undefined, collectionOf({ pending_request: { state, since } }));
		const text = within(screen.getByRole('banner')).getByText(/A commit is/);
		expect(text.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			`${sentence} The files and the version show the last completed commit.`
		);
		expect(text.querySelector('time')?.getAttribute('datetime')).toBe('2026-10-04T09:00:00.000Z');
		expect(within(text).queryByRole('button')).toBeNull();
		expect(within(text).queryByRole('link')).toBeNull();
	});
});
