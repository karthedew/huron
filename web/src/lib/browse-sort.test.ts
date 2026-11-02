import { describe, expect, it } from 'vitest';
import { browseSortHref, readBrowseSort } from './browse-sort';

describe('readBrowseSort', () => {
	it('defaults missing or unknown options to name ascending', () => {
		for (const query of ['', '?sort=&order=', '?sort=metadata&order=up']) {
			expect(readBrowseSort(new URL('http://x/list' + query))).toEqual({
				sort: 'name',
				order: 'asc'
			});
		}
	});
	it.each(['name', 'created_by', 'created_at'])('reads %s in either direction', (sort) => {
		for (const order of ['asc', 'desc']) {
			expect(readBrowseSort(new URL('http://x/list?sort=' + sort + '&order=' + order))).toEqual({
				sort,
				order
			});
		}
	});
	it('keeps each list independent', () => {
		const url = new URL(
			'http://x/list?namespaces_sort=created_at&namespaces_order=desc&collections_sort=created_by&collections_order=asc'
		);
		expect(readBrowseSort(url, 'namespaces')).toEqual({ sort: 'created_at', order: 'desc' });
		expect(readBrowseSort(url, 'collections')).toEqual({ sort: 'created_by', order: 'asc' });
	});
});

describe('browseSortHref', () => {
	it('toggles the current column and starts a new column ascending', () => {
		const url = new URL('http://x/catalogs/a?sort=name&order=asc&cursor=second');
		expect(browseSortHref(url, 'name')).toBe('/catalogs/a?sort=name&order=desc');
		expect(browseSortHref(url, 'created_by')).toBe('/catalogs/a?sort=created_by&order=asc');
		expect(browseSortHref(new URL('http://x/catalogs/a?sort=name&order=desc'), 'name')).toBe(
			'/catalogs/a?sort=name&order=asc'
		);
	});
	it('restarts only its list and clears a stale notice', () => {
		const url = new URL(
			'http://x/catalogs/a/namespaces/n?namespaces_cursor=n2&collections_cursor=c2&collections_sort=created_at&collections_order=desc&notice=page_expired'
		);
		const target = new URL(browseSortHref(url, 'created_by', 'namespaces'), url);
		expect(target.searchParams.get('namespaces_cursor')).toBeNull();
		expect(target.searchParams.get('notice')).toBeNull();
		expect(target.searchParams.get('namespaces_sort')).toBe('created_by');
		expect(target.searchParams.get('namespaces_order')).toBe('asc');
		expect(target.searchParams.get('collections_cursor')).toBe('c2');
		expect(target.searchParams.get('collections_sort')).toBe('created_at');
		expect(target.searchParams.get('collections_order')).toBe('desc');
		expect(url.searchParams.get('namespaces_cursor')).toBe('n2');
	});
});
