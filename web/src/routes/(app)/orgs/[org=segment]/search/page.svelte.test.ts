import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CatalogAnswer, OrganizationResults, SearchedCatalog } from '$lib/server/org-search';
import { emptySearch, searchResult, type Search, type SearchErrors } from '$lib/search';
import { collectionFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const HELIO = organizationFixture();
const NO_ERRORS: SearchErrors = { q: null, label: null, form: null };
const WIND: Search = { ...emptySearch(), q: 'wind' };
const MAG = searchResult(
	collectionFixture({
		id: 'c-mag',
		metadata: { title: 'ACE MAG level 2, 2024', labels: { mission: 'ace', level: 'l2' } }
	})
);
const KP = searchResult(
	collectionFixture({
		id: 'c-kp',
		identifier: 'space-weather.alerts.kp-index-2024',
		catalog: 'space-weather',
		metadata: { title: 'Kp index 2024' }
	})
);

function catalog(name: string, displayName: string, search: Search = WIND): SearchedCatalog {
	return { name, displayName, search };
}

const HELIOPHYSICS = catalog('heliophysics', 'Heliophysics');
const SPACE_WEATHER = catalog('space-weather', 'Space Weather');

function answer(
	searched: SearchedCatalog,
	results: ReturnType<typeof searchResult>[],
	more = false
): CatalogAnswer {
	return { ...searched, status: 'answered', results, more };
}

async function show({
	search = WIND,
	errors = NO_ERRORS,
	drafts = false,
	catalogCount = 2,
	truncated = false,
	results = { exact: null, answers: [], late: [], skipped: [] }
}: {
	search?: Search;
	errors?: SearchErrors;
	drafts?: boolean;
	catalogCount?: number;
	truncated?: boolean;
	results?: Omit<OrganizationResults, 'refused'> | null;
} = {}) {
	page.url = new URL('http://localhost:4173/orgs/helio/search');
	page.route = { id: '/(app)/orgs/[org=segment]/search' };
	const shown = render(Page, {
		props: {
			data: {
				user: fakeUser(),
				organizations: [HELIO],
				organizationsUnavailable: false,
				roles: [],
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: 'helio',
				organizationDetails: HELIO,
				search,
				errors,
				pendingLabel: '',
				drafts,
				catalogCount,
				truncated,
				results
			},
			params: { org: 'helio' },
			form: undefined
		}
	});
	await tick();
	return shown;
}

describe('the organization search page', () => {
	it('titles the document with the search and the organization', async () => {
		const { unmount } = await show({ search: emptySearch(), results: null });
		expect(document.title).toBe('Search · Heliophysics Division · Huron');
		unmount();
		await show();
		expect(document.title).toBe('“wind” · Search · Heliophysics Division · Huron');
	});

	it('groups the results by catalog, each under its name, which leads to the catalog', async () => {
		await show({
			results: {
				exact: null,
				answers: [answer(HELIOPHYSICS, [MAG], true), answer(SPACE_WEATHER, [KP])],
				late: [],
				skipped: []
			}
		});
		expect(screen.getByRole('search', { name: 'Organization search' })).toHaveAttribute(
			'action',
			'/orgs/helio/search'
		);
		const helio = screen.getByRole('region', { name: 'Heliophysics' });
		expect(within(helio).getByRole('heading', { level: 2 })).toHaveTextContent('Heliophysics');
		expect(within(helio).getByRole('link', { name: 'Heliophysics' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics'
		);
		const results = within(helio).getByRole('list', { name: 'Results in Heliophysics' });
		expect(within(results).getByRole('heading', { level: 3 })).toHaveTextContent(
			'ACE MAG level 2, 2024'
		);
		// It has more than it shows: its own search shows them all, for the same search.
		expect(
			within(helio).getByRole('link', { name: 'See all results in Heliophysics' })
		).toHaveAttribute('href', '/catalogs/heliophysics/search?q=wind');
		const space = screen.getByRole('region', { name: 'Space Weather' });
		expect(within(space).getByRole('link', { name: 'Search only Space Weather' })).toHaveAttribute(
			'href',
			'/catalogs/space-weather/search?q=wind'
		);
		expect(helio.compareDocumentPosition(space) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it("shows a result's labels as text, and a filter the search has with a check", async () => {
		await show({
			search: { ...WIND, labels: [{ key: 'mission', value: 'ace' }] },
			results: { exact: null, answers: [answer(HELIOPHYSICS, [MAG])], late: [], skipped: [] }
		});
		const labels = within(screen.getByRole('region', { name: 'Heliophysics' })).getByRole('list', {
			name: 'Labels'
		});
		expect(within(labels).queryAllByRole('link')).toEqual([]);
		expect(within(labels).getByText('level: l2')).toBeInTheDocument();
		expect(labels).toHaveTextContent('mission: ace, in this search');
	});

	it('lists the catalogs that found nothing in a line of their own', async () => {
		await show({
			results: {
				exact: null,
				answers: [answer(HELIOPHYSICS, [MAG]), answer(SPACE_WEATHER, [])],
				late: [],
				skipped: []
			}
		});
		expect(screen.queryByRole('region', { name: 'Space Weather' })).toBeNull();
		expect(screen.getByText('No collections match in Space Weather.')).toBeInTheDocument();
	});

	it('shows the exact match first, under its own heading', async () => {
		await show({
			search: { ...emptySearch(), q: 'heliophysics.solar-wind.ace.mag-l2-2024' },
			results: {
				exact: MAG,
				answers: [answer(HELIOPHYSICS, []), answer(SPACE_WEATHER, [])],
				late: [],
				skipped: []
			}
		});
		const exact = screen.getByRole('region', { name: 'Exact match' });
		expect(within(exact).getByRole('link', { name: 'ACE MAG level 2, 2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		expect(
			screen.getByText('No other collections match in Heliophysics and Space Weather.')
		).toBeInTheDocument();
		expect(screen.queryByText('No collections match this search.')).toBeNull();
	});

	it('says how many catalogs did not answer in time, and leads to each one on its own', async () => {
		await show({
			results: {
				exact: null,
				answers: [answer(HELIOPHYSICS, [MAG])],
				late: [SPACE_WEATHER, catalog('geomagnetism', 'Geomagnetism')],
				skipped: []
			}
		});
		const note = screen.getByText('2 catalogs did not answer in time.').closest('[role="note"]');
		if (!(note instanceof HTMLElement)) throw new Error('no note');
		const links = within(note).getAllByRole('link');
		expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Search only Space Weather', '/catalogs/space-weather/search?q=wind'],
			['Search only Geomagnetism', '/catalogs/geomagnetism/search?q=wind']
		]);
		expect(
			within(screen.getByRole('region', { name: 'Heliophysics' })).getByRole('list', {
				name: 'Results in Heliophysics'
			})
		).toBeInTheDocument();
	});

	it("shows a catalog's failure under its name, in words of its own", async () => {
		await show({
			results: {
				exact: null,
				answers: [{ ...HELIOPHYSICS, status: 'failed' }, answer(SPACE_WEATHER, [KP])],
				late: [],
				skipped: []
			}
		});
		const failed = screen.getByRole('region', { name: 'Heliophysics' });
		expect(failed).toHaveTextContent("Couldn't search this catalog.");
		expect(within(failed).queryByRole('list')).toBeNull();
		expect(within(failed).getByRole('link', { name: 'Search only Heliophysics' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=wind'
		);
	});

	it('says which catalogs a search for drafts left out', async () => {
		const drafts: Search = { ...emptySearch(), states: ['draft'] };
		await show({
			search: drafts,
			drafts: true,
			results: {
				exact: null,
				answers: [answer(catalog('heliophysics', 'Heliophysics', drafts), [MAG])],
				late: [],
				skipped: [{ name: 'space-weather', displayName: 'Space Weather' }]
			}
		});
		expect(screen.getByRole('note')).toHaveTextContent(
			'Not searched, because only those who may create collections there see drafts: Space Weather.'
		);
		expect(screen.getByRole('checkbox', { name: 'Draft' })).toBeChecked();
	});

	it('says when the organization has more catalogs than its search covers', async () => {
		await show({ truncated: true, catalogCount: 50 });
		expect(screen.getByRole('note')).toHaveTextContent(
			'This organization has more than 50 catalogs; its search covers the first 50, by name.'
		);
	});

	it('offers ways out when nothing matches, all within the organization', async () => {
		await show({
			search: { ...emptySearch(), q: 'solar storm', labels: [{ key: 'mission', value: 'ace' }] },
			results: {
				exact: null,
				answers: [answer(HELIOPHYSICS, []), answer(SPACE_WEATHER, [])],
				late: [],
				skipped: []
			}
		});
		expect(screen.getByText('No collections match this search.')).toBeInTheDocument();
		const filters = screen.getByRole('list', { name: 'Filters' });
		expect(
			within(filters).getByRole('link', { name: 'Remove filter mission = ace' })
		).toHaveAttribute('href', '/orgs/helio/search?q=solar+storm');
		const words = within(screen.getByRole('list', { name: 'Words' })).getAllByRole('link');
		expect(words.map((link) => link.getAttribute('href'))).toEqual([
			'/orgs/helio/search?q=solar&label=mission%3Dace',
			'/orgs/helio/search?q=storm&label=mission%3Dace'
		]);
		expect(screen.queryByRole('link', { name: /^Search all of/ })).toBeNull();
		expect(screen.queryByText(/collections match in/)).toBeNull();
	});

	it('claims no more than the catalogs that answered when some did not', async () => {
		const { unmount } = await show({
			results: {
				exact: null,
				answers: [answer(HELIOPHYSICS, []), { ...SPACE_WEATHER, status: 'failed' }],
				late: [],
				skipped: []
			}
		});
		expect(
			screen.getByText('No collections match in the catalogs that answered.')
		).toBeInTheDocument();
		expect(screen.queryByText('No collections match this search.')).toBeNull();
		unmount();
		// With none answering, the notes say it all.
		await show({
			results: {
				exact: null,
				answers: [{ ...HELIOPHYSICS, status: 'failed' }],
				late: [SPACE_WEATHER],
				skipped: []
			}
		});
		expect(screen.queryByText(/No collections match/)).toBeNull();
		expect(screen.getByText('1 catalog did not answer in time.')).toBeInTheDocument();
	});

	it('says what the search covers before anything is searched', async () => {
		const { unmount } = await show({ search: emptySearch(), results: null });
		expect(
			screen.getByText(
				'Searches the 2 catalogs of Heliophysics Division that you can see, and shows the first 5 results of each.'
			)
		).toBeInTheDocument();
		expect(screen.queryByRole('region')).toBeNull();
		unmount();
		await show({ search: emptySearch(), results: null, catalogCount: 1 });
		expect(
			screen.getByText(/^Searches the catalog of Heliophysics Division that you can see/)
		).toBeInTheDocument();
	});

	it('says that an organization without catalogs has nothing to search', async () => {
		await show({ catalogCount: 0, results: null });
		expect(screen.getByText('No catalogs you can see in this organization.')).toBeInTheDocument();
		expect(screen.queryByText(/^Searches/)).toBeNull();
	});

	it('offers drafts in the form only where the user may see them', async () => {
		const { unmount } = await show();
		expect(screen.queryByRole('checkbox', { name: 'Draft' })).toBeNull();
		unmount();
		await show({ drafts: true });
		expect(screen.getByRole('checkbox', { name: 'Draft' })).not.toBeChecked();
	});

	it('shows a search it cannot run at its fields, without results', async () => {
		await show({
			search: { ...emptySearch(), q: 'w'.repeat(201) },
			errors: { ...NO_ERRORS, q: 'Use at most 200 characters; this text has 201.' },
			results: null
		});
		expect(document.title).toBe('Error: Search · Heliophysics Division · Huron');
		expect(screen.getByRole('searchbox', { name: 'Search text' })).toHaveAttribute(
			'aria-invalid',
			'true'
		);
		expect(screen.queryByText(/^Searches/)).toBeNull();
		expect(screen.queryByRole('region')).toBeNull();
	});
});
