import { render, screen, within, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { emptySearch, searchResult } from '$lib/search';
import { catalogFixture, collectionFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { catalogPageData } from '$lib/testing/catalog-data';
import Page from './+page.svelte';
import type { PageData } from './$types';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });
const NO_ERRORS = { q: null, label: null, form: null };
const scope = {
	organization: 'helio',
	catalog: null,
	catalogs: [{ name: 'heliophysics', display_name: 'Heliophysics' }]
};
function show(catalog = false, noOrganizations = false) {
	const search = { ...emptySearch(), q: 'wind' };
	const common = {
		...catalogPageData(),
		organizationList: [HELIO, GEO],
		moreOrganizations: false,
		selectedOrganization: HELIO,
		scope,
		search
	};
	const data: PageData = noOrganizations
		? {
				...common,
				organization: null,
				organizationList: [],
				selectedOrganization: null,
				scope: null,
				catalogSearch: null,
				organizationSearch: null
			}
		: catalog
			? {
					...common,
					catalogSearch: {
						catalog: catalogFixture(),
						scope: { ...scope, catalog: 'heliophysics' },
						search,
						errors: NO_ERRORS,
						pendingLabel: '',
						exact: null,
						results: [searchResult(collectionFixture())],
						nextCursor: 'c2'
					},
					organizationSearch: null
				}
			: {
					...common,
					catalogSearch: null,
					organizationSearch: {
						organizationDetails: HELIO,
						scope,
						search,
						errors: NO_ERRORS,
						pendingLabel: '',
						drafts: false,
						catalogCount: 1,
						truncated: false,
						results: null
					}
				};
	return render(Page, { props: { data, params: {}, form: undefined } });
}
describe('the central Search workspace', () => {
	it('has explicit organization and catalog selectors beside metadata filters', () => {
		show();
		expect(screen.getByRole('heading', { level: 1, name: 'Search' })).toBeInTheDocument();
		expect(screen.getByRole('combobox', { name: 'Organization' })).toHaveValue('helio');
		expect(screen.getByRole('combobox', { name: 'Catalog' })).toHaveValue('');
		expect(screen.getByRole('option', { name: 'Heliophysics' })).toBeInTheDocument();
		expect(screen.getByRole('textbox', { name: 'Add a label filter' })).toBeInTheDocument();
		expect(screen.getByRole('checkbox', { name: 'Active' })).toBeInTheDocument();
	});
	it('submits selected scope with the text and label filters', async () => {
		show();
		const form = screen.getByRole('search', { name: 'Organization search' });
		await fireEvent.change(within(form).getByRole('combobox', { name: 'Catalog' }), {
			target: { value: 'heliophysics' }
		});
		const data = new FormData(form as HTMLFormElement);
		expect(data.get('organization')).toBe('helio');
		expect(data.get('catalog')).toBe('heliophysics');
		expect(data.get('q')).toBe('wind');
		expect(form).toHaveAttribute('action', '/search');
	});
	it('keeps the CLI hint and pages a selected catalog', () => {
		show(true);
		expect(screen.getByRole('combobox', { name: 'Catalog' })).toHaveValue('heliophysics');
		expect(screen.getByText('Run this search with the CLI')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/search?catalog=heliophysics&q=wind&cursor=c2'
		);
	});
	it('states the API search limits without offering unavailable schema filters', () => {
		show();
		expect(
			screen.getByText(/Schema fields and other metadata properties are not searchable yet/)
		).toBeInTheDocument();
	});
	it('explains why an account has no collections to search', () => {
		show(false, true);
		expect(screen.getByText("You don't have access to any organization yet.")).toBeInTheDocument();
		expect(screen.queryByRole('combobox')).toBeNull();
	});
});
