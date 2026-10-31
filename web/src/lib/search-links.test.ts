import { describe, expect, it } from 'vitest';
import { emptySearch, withLabel, type Search } from './search';
import {
	catalogSearchHref,
	chooserHref,
	organizationSearchHref,
	searchScope
} from './search-links';

const SEARCH: Search = {
	q: 'flare',
	labels: [{ key: 'mission', value: 'ace' }],
	states: ['incomplete'],
	cursor: null
};

describe('catalogSearchHref', () => {
	it("leads to the catalog's search page with the search's canonical query", () => {
		expect(catalogSearchHref('heliophysics', emptySearch())).toBe('/catalogs/heliophysics/search');
		expect(catalogSearchHref('space-weather', SEARCH)).toBe(
			'/catalogs/space-weather/search?q=flare&label=mission%3Dace&state=incomplete'
		);
	});

	it('searches the catalog for one label, as label chips do', () => {
		expect(
			catalogSearchHref('heliophysics', withLabel(emptySearch(), { key: 'a b', value: 'c&d#e' }))
		).toBe('/catalogs/heliophysics/search?label=a+b%3Dc%26d%23e');
	});
});

describe('organizationSearchHref', () => {
	it("leads to the organization's search page with the search's canonical query", () => {
		expect(organizationSearchHref('helio', emptySearch())).toBe('/orgs/helio/search');
		expect(organizationSearchHref('helio', SEARCH)).toBe(
			'/orgs/helio/search?q=flare&label=mission%3Dace&state=incomplete'
		);
	});
});

describe('chooserHref', () => {
	it('leads to the page that asks which organization to search', () => {
		expect(chooserHref(emptySearch())).toBe('/search');
		expect(chooserHref({ ...emptySearch(), q: 'solar wind' })).toBe('/search?q=solar+wind');
	});
});

describe('searchScope', () => {
	const catalog = { name: 'heliophysics', display_name: 'Heliophysics' };
	const organization = { name: 'helio', display_name: 'Heliophysics Division' };

	it("searches a catalog's page's catalog, whatever the organization", () => {
		expect(searchScope(catalog, organization)).toEqual({
			href: '/catalogs/heliophysics/search',
			name: 'Heliophysics'
		});
		expect(searchScope(catalog, null)).toEqual({
			href: '/catalogs/heliophysics/search',
			name: 'Heliophysics'
		});
	});

	it('searches the current organization elsewhere', () => {
		expect(searchScope(undefined, organization)).toEqual({
			href: '/orgs/helio/search',
			name: 'Heliophysics Division'
		});
		expect(searchScope(null, { name: 'geo', display_name: '' })).toEqual({
			href: '/orgs/geo/search',
			name: 'geo'
		});
	});

	it('asks which organization to search without either', () => {
		expect(searchScope(undefined, null)).toEqual({ href: '/search', name: null });
	});
});
