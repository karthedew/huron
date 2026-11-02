import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { MAX_ITEMS, MAX_LABEL_LENGTH } from '$lib/metadata';
import {
	MAX_RESULT_LABELS,
	emptySearch,
	searchQuery,
	searchResult,
	type Search,
	type SearchResult
} from '$lib/search';
import { collectionFixture } from '$lib/testing/api-fixtures';
import SearchResults from './SearchResults.svelte';

const MAG = searchResult(
	collectionFixture({
		id: 'c-mag',
		identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
		file_count: 3,
		updated_at: '2026-10-03T09:00:00+00:00',
		metadata: {
			title: 'ACE MAG level 2, 2024',
			description: 'Magnetic field vectors from the ACE magnetometer, 16-second averages.',
			labels: { mission: 'ace', level: 'l2', encounter: 17 }
		}
	})
);
const DRAFT = searchResult(
	collectionFixture({
		id: 'c-draft',
		identifier: 'heliophysics.solar-wind.ace.mag-l1-draft',
		state: 'draft',
		file_count: 0,
		metadata: {}
	})
);

function show(results: SearchResult[], search: Search = emptySearch()) {
	return render(SearchResults, {
		props: {
			label: 'Results',
			results,
			search,
			href: (other: Search) => `/catalogs/heliophysics/search${searchQuery(other)}`
		}
	});
}

/** The rows of the list, not the items of the lists inside them. */
function rows(): HTMLElement[] {
	return [...screen.getByRole('list', { name: 'Results' }).children].filter(
		(element): element is HTMLElement => element instanceof HTMLElement
	);
}

/** The paragraph of a row that reads as `text`, marks and all. */
function paragraph(row: HTMLElement, text: string): HTMLElement {
	return within(row).getByText(
		(_, element) => element?.tagName === 'P' && element.textContent?.trim() === text
	);
}

/** An element's text with each `<mark>` in brackets. */
function marked(element: Element): string {
	return [...element.childNodes]
		.map((node) =>
			node instanceof HTMLElement && node.tagName === 'MARK'
				? `[${node.textContent}]`
				: node instanceof Element
					? marked(node)
					: (node.textContent ?? '')
		)
		.join('');
}

describe('search results', () => {
	it("link each row's title to the collection, with its identifier, description and details", () => {
		show([MAG]);
		const [row] = rows();
		const heading = within(row).getByRole('heading', { level: 3, name: 'ACE MAG level 2, 2024' });
		expect(within(heading).getByRole('link', { name: 'ACE MAG level 2, 2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		expect(row).toHaveTextContent('heliophysics.solar-wind.ace.mag-l2-2024');
		expect(
			paragraph(row, 'Magnetic field vectors from the ACE magnetometer, 16-second averages.')
		).toHaveClass('line-clamp-2');
		expect(row).toHaveTextContent('3 files');
		const updated = row.querySelector('time');
		expect(updated).toHaveAttribute('datetime', '2026-10-03T09:00:00.000Z');
		expect(updated).toHaveTextContent('2026-10-03 09:00 UTC');
		// A row is no link itself: the title is.
		expect(row.closest('a')).toBeNull();
		expect(within(row).queryByText('Active')).toBeNull();
	});

	it('names a collection without a title by its identifier, once, and badges a draft', () => {
		show([DRAFT]);
		const [row] = rows();
		expect(
			within(row).getByRole('heading', {
				level: 3,
				name: 'heliophysics.solar-wind.ace.mag-l1-draft'
			})
		).toHaveClass('mono');
		expect(
			within(row).getByRole('link', { name: 'heliophysics.solar-wind.ace.mag-l1-draft' })
		).toHaveAttribute('href', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l1-draft');
		expect(within(row).getAllByText('heliophysics.solar-wind.ace.mag-l1-draft')).toHaveLength(1);
		expect(within(row).getByText('Draft')).toBeInTheDocument();
		expect(row).toHaveTextContent('0 files');
		expect(within(row).queryByRole('list', { name: 'Labels' })).toBeNull();
	});

	it('marks the search text in the title, the identifier and the description', () => {
		show([MAG], { ...emptySearch(), q: 'Mag' });
		const [row] = rows();
		const title = within(row).getByRole('link', { name: 'ACE MAG level 2, 2024' });
		expect(marked(title)).toBe('ACE [MAG] level 2, 2024');
		expect(marked(paragraph(row, 'heliophysics.solar-wind.ace.mag-l2-2024')).trim()).toBe(
			'heliophysics.solar-wind.ace.[mag]-l2-2024'
		);
		expect(
			marked(
				paragraph(row, 'Magnetic field vectors from the ACE magnetometer, 16-second averages.')
			).trim()
		).toBe('[Mag]netic field vectors from the ACE [mag]netometer, 16-second averages.');
		const mark = row.querySelector('mark');
		expect(mark).toHaveClass('bg-app-mark', 'text-inherit');
		// The marks change nothing of the text itself.
		expect(title).toHaveTextContent(/^ACE MAG level 2, 2024$/);
	});

	it('marks nothing without a search text', () => {
		show([MAG]);
		expect(rows()[0].querySelector('mark')).toBeNull();
	});

	it("adds a label to the search from the row's chips, except labels it cannot find", () => {
		const search: Search = { ...emptySearch(), q: 'ace', states: ['incomplete'], cursor: 'c2' };
		show([MAG], search);
		const labels = within(within(rows()[0]).getByRole('list', { name: 'Labels' }));
		const links = labels.getAllByRole('link');
		expect(links.map((link) => link.textContent)).toEqual(['level: l2', 'mission: ace']);
		const mission = labels.getByRole('link', {
			name: 'mission: ace, add this label to the search'
		});
		expect(mission).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=ace&label=mission%3Dace&state=incomplete'
		);
		// A number is no text: the search cannot find it.
		expect(labels.getByText('encounter: 17').tagName).toBe('SPAN');
	});

	it('shows a label the search already filters by as such, not as a link', () => {
		show([MAG], { ...emptySearch(), labels: [{ key: 'mission', value: 'ace' }] });
		const labels = within(within(rows()[0]).getByRole('list', { name: 'Labels' }));
		expect(labels.queryByRole('link', { name: /^mission: ace/ })).toBeNull();
		expect(labels.getByText('mission: ace')).toHaveTextContent('mission: ace, in this search');
		expect(
			labels.getByRole('link', { name: 'level: l2, add this label to the search' })
		).toHaveAttribute('href', '/catalogs/heliophysics/search?label=mission%3Dace&label=level%3Dl2');
	});

	it('shows every label as text where it leads to no search, a filter it has with a check', () => {
		render(SearchResults, {
			props: {
				label: 'Results',
				results: [MAG],
				search: { ...emptySearch(), labels: [{ key: 'mission', value: 'ace' }] }
			}
		});
		const labels = within(within(rows()[0]).getByRole('list', { name: 'Labels' }));
		expect(labels.queryAllByRole('link')).toEqual([]);
		expect(labels.getByText('level: l2').tagName).toBe('SPAN');
		expect(labels.getByText('mission: ace')).toHaveTextContent('mission: ace, in this search');
		// The title still leads to the collection.
		expect(within(rows()[0]).getByRole('link', { name: 'ACE MAG level 2, 2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
	});

	it('shows the first labels of a row and counts the rest', () => {
		const many = searchResult(
			collectionFixture({
				metadata: {
					labels: Object.fromEntries(
						Array.from({ length: MAX_ITEMS + 2 }, (_, index) => [`k${index}`, 'v'])
					)
				}
			})
		);
		show([many]);
		const labels = within(rows()[0]).getByRole('list', { name: 'Labels' });
		expect(within(labels).getAllByRole('link')).toHaveLength(MAX_RESULT_LABELS);
		expect(labels).toHaveTextContent(`and ${MAX_ITEMS + 2 - MAX_RESULT_LABELS} more labels`);
	});

	it('shows a shortened label as plain text, also where two read alike after shortening', () => {
		const long = 'k'.repeat(MAX_LABEL_LENGTH);
		const result = searchResult(
			collectionFixture({
				metadata: { labels: { [`${long}a`]: 'v', [`${long}b`]: 'v', mission: 'ace' } }
			})
		);
		show([result]);
		const labels = within(within(rows()[0]).getByRole('list', { name: 'Labels' }));
		expect(labels.getAllByText(`${long}…: v`)).toHaveLength(2);
		expect(labels.getAllByRole('link').map((link) => link.textContent)).toEqual(['mission: ace']);
	});

	it('lists every result in order, each titled by a heading', () => {
		show([MAG, DRAFT]);
		expect(
			screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
		).toEqual(['ACE MAG level 2, 2024', 'heliophysics.solar-wind.ace.mag-l1-draft']);
		expect(rows()).toHaveLength(2);
	});
});
