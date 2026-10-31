import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoleGrant } from '$api/types';
import {
	emptySearch,
	searchResult,
	type Search,
	type SearchErrors,
	type SearchResult
} from '$lib/search';
import { collectionFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const NO_ERRORS: SearchErrors = { q: null, label: null, form: null };
const MAG = searchResult(
	collectionFixture({
		id: 'c-mag',
		metadata: { title: 'ACE MAG level 2, 2024', labels: { mission: 'ace' } }
	})
);
const SWEPAM = searchResult(
	collectionFixture({
		id: 'c-swepam',
		identifier: 'heliophysics.solar-wind.ace.swepam-2024',
		metadata: { title: 'ACE SWEPAM 2024' }
	})
);

async function show({
	search = emptySearch(),
	errors = NO_ERRORS,
	pendingLabel = '',
	exact = null,
	results = [MAG, SWEPAM],
	nextCursor = null,
	roles = [],
	query = ''
}: {
	search?: Search;
	errors?: SearchErrors;
	pendingLabel?: string;
	exact?: SearchResult | null;
	results?: SearchResult[] | null;
	nextCursor?: string | null;
	roles?: RoleGrant[];
	query?: string;
} = {}) {
	page.url = new URL(`http://localhost:4173/catalogs/heliophysics/search${query}`);
	page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)/search' };
	const shown = render(Page, {
		props: {
			data: {
				...catalogPageData({ roles }),
				search,
				errors,
				pendingLabel,
				exact,
				results,
				nextCursor
			},
			params: { catalog: 'heliophysics' },
			form: undefined
		}
	});
	await tick();
	return shown;
}

describe('the catalog search page', () => {
	it('titles the document with the search and the catalog', async () => {
		const { unmount } = await show();
		expect(document.title).toBe('Search · Heliophysics · Huron');
		unmount();
		await show({ search: { ...emptySearch(), q: 'wind' } });
		expect(document.title).toBe('“wind” · Search · Heliophysics · Huron');
	});

	it('shows the form and the results under their headings', async () => {
		await show({ search: { ...emptySearch(), q: 'ace' } });
		expect(screen.getByRole('search', { name: 'Catalog search' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { level: 2, name: 'Results' })).toBeInTheDocument();
		const results = screen.getByRole('list', { name: 'Results' });
		expect(within(results).getByRole('link', { name: 'ACE MAG level 2, 2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		expect(within(results).getByRole('link', { name: 'ACE SWEPAM 2024' })).toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Exact match' })).toBeNull();
	});

	it('offers drafts in the form to contributors only', async () => {
		const { unmount } = await show();
		expect(screen.queryByRole('checkbox', { name: 'Draft' })).toBeNull();
		unmount();
		await show({ roles: [catalogRole('contributor')] });
		expect(screen.getByRole('checkbox', { name: 'Draft' })).not.toBeChecked();
	});

	it('shows the exact match first, under its own heading', async () => {
		await show({
			search: { ...emptySearch(), q: 'solar-wind.ace.mag-l2-2024' },
			exact: MAG,
			results: [SWEPAM]
		});
		const exact = screen.getByRole('region', { name: 'Exact match' });
		expect(within(exact).getByRole('link', { name: 'ACE MAG level 2, 2024' })).toBeInTheDocument();
		const results = screen.getByRole('region', { name: 'Results' });
		expect(within(results).queryByRole('link', { name: 'ACE MAG level 2, 2024' })).toBeNull();
		expect(exact.compareDocumentPosition(results) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('says that nothing else matches when the exact match is the only result', async () => {
		await show({
			search: { ...emptySearch(), q: 'solar-wind.ace.mag-l2-2024' },
			exact: MAG,
			results: []
		});
		expect(screen.getByText('No other collections match this search.')).toBeInTheDocument();
		expect(screen.queryByText('No collections match this search.')).toBeNull();
	});

	it('suggests a wider search when nothing matches, in all of the organization', async () => {
		await show({
			search: {
				q: 'solar wind',
				labels: [{ key: 'mission', value: 'wind' }],
				states: ['incomplete'],
				cursor: null
			},
			results: []
		});
		expect(screen.getByText('No collections match this search.')).toBeInTheDocument();
		expect(within(screen.getByRole('list', { name: 'Words' })).getAllByRole('link')).toHaveLength(
			2
		);
		// The text and the labels; each catalog decides for itself who sees its drafts.
		expect(
			screen.getByRole('link', { name: 'Search all of Heliophysics Division' })
		).toHaveAttribute('href', '/orgs/helio/search?q=solar+wind&label=mission%3Dwind');
	});

	it('links the search of all of the organization under its results too', async () => {
		const search: Search = {
			q: 'ace',
			labels: [{ key: 'mission', value: 'ace' }],
			states: ['incomplete'],
			cursor: null
		};
		const wider = () =>
			within(screen.getByRole('region', { name: 'Results' })).getByRole('link', {
				name: 'Search all of Heliophysics Division'
			});
		const first = await show({ search, nextCursor: 'c2' });
		// The text and the labels, as when nothing matches.
		expect(wider()).toHaveAttribute('href', '/orgs/helio/search?q=ace&label=mission%3Dace');
		// After the results, before the page links.
		const list = screen.getByRole('list', { name: 'Results' });
		const pages = screen.getByRole('navigation', { name: 'Result pages' });
		expect(list.compareDocumentPosition(wider()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(wider().compareDocumentPosition(pages) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		first.unmount();
		// So does a page with the exact match alone, and a later page with nothing on it.
		const exactOnly = await show({ search, exact: MAG, results: [] });
		expect(wider()).toBeInTheDocument();
		exactOnly.unmount();
		await show({ search: { ...search, cursor: 'c2' }, results: [], query: '?q=ace&cursor=c2' });
		expect(wider()).toHaveAttribute('href', '/orgs/helio/search?q=ace&label=mission%3Dace');
	});

	it('says that a later page is empty rather than that nothing matches', async () => {
		await show({
			search: { ...emptySearch(), q: 'wind', cursor: 'c2' },
			results: [],
			query: '?q=wind&cursor=c2'
		});
		expect(screen.getByText('No results on this page.')).toBeInTheDocument();
		expect(screen.queryByText('No collections match this search.')).toBeNull();
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=wind'
		);
	});

	it('pages the results at their canonical address, keeping the search', async () => {
		const search: Search = {
			q: 'run',
			labels: [{ key: 'mission', value: 'psp' }],
			states: null,
			cursor: 'c2'
		};
		await show({
			search,
			nextCursor: 'c3',
			// The address as the form wrote it: the default states and an empty label.
			query: '?q=run&label=mission%3Dpsp&label=&state=active&state=incomplete&cursor=c2'
		});
		const pages = screen.getByRole('navigation', { name: 'Result pages' });
		expect(within(pages).getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=run&label=mission%3Dpsp&cursor=c3'
		);
		expect(within(pages).getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=run&label=mission%3Dpsp'
		);
	});

	it('shows how to run the search with the CLI, with states only when not the default', async () => {
		const { unmount } = await show({
			search: {
				q: 'solar wind',
				labels: [{ key: 'mission', value: 'wind' }],
				states: ['incomplete'],
				cursor: null
			}
		});
		const hint = screen.getByRole('region', { name: 'Run this search with the CLI' });
		expect(within(hint).getByRole('textbox')).toHaveValue(
			"huron search heliophysics -q 'solar wind' -l mission=wind --state incomplete"
		);
		unmount();
		await show();
		expect(
			within(screen.getByRole('region', { name: 'Run this search with the CLI' })).getByRole(
				'textbox'
			)
		).toHaveValue('huron search heliophysics');
	});

	it('shows a search it cannot run at its fields, without results or a CLI hint', async () => {
		await show({
			search: { ...emptySearch(), q: 'w'.repeat(201) },
			errors: { ...NO_ERRORS, q: 'Use at most 200 characters; this text has 201.' },
			results: null
		});
		expect(document.title).toBe('Error: Search · Heliophysics · Huron');
		expect(screen.getByRole('searchbox', { name: 'Search text' })).toHaveAttribute(
			'aria-invalid',
			'true'
		);
		expect(screen.getByText('Use at most 200 characters; this text has 201.')).toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Results' })).toBeNull();
		expect(screen.queryByRole('region', { name: 'Run this search with the CLI' })).toBeNull();
		expect(document.body).not.toHaveTextContent('No collections match');
	});

	it('says when its page link expired', async () => {
		await show({ query: '?q=run&notice=page_expired', search: { ...emptySearch(), q: 'run' } });
		expect(screen.getByRole('note')).toHaveTextContent(
			'That page link expired; showing the first page.'
		);
	});
});
