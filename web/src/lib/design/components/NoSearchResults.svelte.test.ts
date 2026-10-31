import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { emptySearch, searchQuery, type Search } from '$lib/search';
import NoSearchResults from './NoSearchResults.svelte';

function show(search: Search, wider: { label: string; href: string } | null = null) {
	return render(NoSearchResults, {
		props: {
			search,
			href: (other: Search) => `/catalogs/heliophysics/search${searchQuery(other)}`,
			wider
		}
	});
}

const SEARCH: Search = {
	q: 'solar wind 2024',
	labels: [
		{ key: 'mission', value: 'wind' },
		{ key: 'level', value: 'l2' }
	],
	states: ['incomplete'],
	cursor: null
};

describe('no search results', () => {
	it('offers to remove each filter of the search', () => {
		show(SEARCH);
		expect(screen.getByText('No collections match this search.')).toBeInTheDocument();
		const filters = within(screen.getByRole('list', { name: 'Filters' })).getAllByRole('link');
		expect(
			filters.map((link) => [
				link.getAttribute('aria-label'),
				link.textContent,
				link.getAttribute('href')
			])
		).toEqual([
			[
				'Remove text “solar wind 2024”',
				'“solar wind 2024”',
				'/catalogs/heliophysics/search?label=mission%3Dwind&label=level%3Dl2&state=incomplete'
			],
			[
				'Remove filter mission = wind',
				'mission = wind',
				'/catalogs/heliophysics/search?q=solar+wind+2024&label=level%3Dl2&state=incomplete'
			],
			[
				'Remove filter level = l2',
				'level = l2',
				'/catalogs/heliophysics/search?q=solar+wind+2024&label=mission%3Dwind&state=incomplete'
			],
			[
				'Remove state filter Incomplete',
				'States: Incomplete',
				'/catalogs/heliophysics/search?q=solar+wind+2024&label=mission%3Dwind&label=level%3Dl2'
			]
		]);
	});

	it('offers to search for each word of a text of several, keeping the other filters', () => {
		show(SEARCH);
		const words = within(screen.getByRole('list', { name: 'Words' })).getAllByRole('link');
		expect(words.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			[
				'solar',
				'/catalogs/heliophysics/search?q=solar&label=mission%3Dwind&label=level%3Dl2&state=incomplete'
			],
			[
				'wind',
				'/catalogs/heliophysics/search?q=wind&label=mission%3Dwind&label=level%3Dl2&state=incomplete'
			],
			[
				'2024',
				'/catalogs/heliophysics/search?q=2024&label=mission%3Dwind&label=level%3Dl2&state=incomplete'
			]
		]);
	});

	it('offers the first ten words of a long text', () => {
		// Each link repeats the search's label filters: forty words made forty such links.
		const words = Array.from({ length: 40 }, (_, index) => `w${index}`);
		show({ ...SEARCH, q: words.join(' ') });
		expect(
			within(screen.getByRole('list', { name: 'Words' }))
				.getAllByRole('link')
				.map((link) => link.textContent)
		).toEqual(words.slice(0, 10));
	});

	it('offers no words for a text of one, and nothing to remove from the empty search', () => {
		show({ ...emptySearch(), q: 'wind' });
		expect(screen.queryByRole('list', { name: 'Words' })).toBeNull();
		expect(within(screen.getByRole('list', { name: 'Filters' })).getAllByRole('link')).toHaveLength(
			1
		);
	});

	it('says that there is nothing yet for the empty search', () => {
		show(emptySearch());
		expect(screen.getByText('No collections yet.')).toBeInTheDocument();
		expect(screen.queryByRole('list', { name: 'Filters' })).toBeNull();
		expect(screen.queryByRole('list', { name: 'Words' })).toBeNull();
	});

	it('says what it is told where nothing matching would claim too much', () => {
		render(NoSearchResults, {
			props: {
				search: SEARCH,
				href: (other: Search) => `/orgs/helio/search${searchQuery(other)}`,
				wider: null,
				title: 'No collections match in the catalogs that answered.'
			}
		});
		expect(
			screen.getByText('No collections match in the catalogs that answered.')
		).toBeInTheDocument();
		expect(screen.queryByText('No collections match this search.')).toBeNull();
		expect(screen.getByRole('list', { name: 'Filters' })).toBeInTheDocument();
	});

	it('offers the wider search it is given', () => {
		show(SEARCH, {
			label: 'Search all of Heliophysics Division',
			href: '/orgs/helio/search?q=solar+wind+2024'
		});
		expect(
			screen.getByRole('link', { name: 'Search all of Heliophysics Division' })
		).toHaveAttribute('href', '/orgs/helio/search?q=solar+wind+2024');
	});
});
