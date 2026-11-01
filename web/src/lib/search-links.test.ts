import { describe, expect, it } from 'vitest';
import { emptySearch, withLabel, type Search } from './search';
import {
	catalogSearchHref,
	organizationSearchHref,
	searchHref,
	legacySearchHref
} from './search-links';

const SEARCH: Search = {
	q: 'flare',
	labels: [{ key: 'mission', value: 'ace' }],
	states: ['incomplete'],
	cursor: null
};

describe('catalogSearchHref', () => {
	it("leads to the catalog's search page with the search's canonical query", () => {
		expect(catalogSearchHref('heliophysics', emptySearch())).toBe('/search?catalog=heliophysics');
		expect(catalogSearchHref('space-weather', SEARCH)).toBe(
			'/search?catalog=space-weather&q=flare&label=mission%3Dace&state=incomplete'
		);
	});

	it('searches the catalog for one label, as label chips do', () => {
		expect(
			catalogSearchHref('heliophysics', withLabel(emptySearch(), { key: 'a b', value: 'c&d#e' }))
		).toBe('/search?catalog=heliophysics&label=a+b%3Dc%26d%23e');
	});
});

describe('organizationSearchHref', () => {
	it("leads to the organization's search page with the search's canonical query", () => {
		expect(organizationSearchHref('helio', emptySearch())).toBe('/search?organization=helio');
		expect(organizationSearchHref('helio', SEARCH)).toBe(
			'/search?organization=helio&q=flare&label=mission%3Dace&state=incomplete'
		);
	});
});

describe('central search addresses', () => {
	it('opens Search with optional text and no explicit scope', () => {
		expect(searchHref(emptySearch())).toBe('/search');
		expect(searchHref({ ...emptySearch(), q: 'solar wind' })).toBe('/search?q=solar+wind');
	});
	it('combines explicit scope with a canonical paged search', () => {
		expect(
			searchHref(
				{ ...SEARCH, cursor: 'next&last' },
				{ organization: 'helio', catalog: 'space-weather' }
			)
		).toBe(
			'/search?organization=helio&catalog=space-weather&q=flare&label=mission%3Dace&state=incomplete&cursor=next%26last'
		);
	});
	it('keeps only supported legacy input, including invalid fields needing correction', () => {
		expect(
			legacySearchHref(
				new URLSearchParams(
					'q=wind&label=broken&label_json=%22a%3Db%22&state=draft&cursor=c2&notice=page_expired&other=x'
				),
				{ catalog: 'heliophysics' }
			)
		).toBe(
			'/search?catalog=heliophysics&q=wind&label=broken&label_json=%22a%3Db%22&state=draft&cursor=c2&notice=page_expired'
		);
	});
});
