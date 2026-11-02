import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import BrowseTable from './BrowseTable.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(resetAppState);
const children = createRawSnippet(() => ({
	render: () => '<tr><th scope="row">alpha</th><td>alice</td><td>2026-11-01</td></tr>'
}));

describe('browse table', () => {
	it('names its table and scroll region, with only the current column marked sorted', () => {
		page.url = new URL('http://localhost:4173/orgs/helio?sort=created_at&order=desc&cursor=next');
		render(BrowseTable, {
			label: 'Catalogs',
			sort: { sort: 'created_at', order: 'desc' },
			children
		});
		expect(screen.getByRole('region', { name: 'Catalogs table' })).toHaveAttribute('tabindex', '0');
		const table = screen.getByRole('table', { name: 'Catalogs' });
		const heads = within(table).getAllByRole('columnheader');
		expect(heads).toHaveLength(3);
		expect(heads[0]).not.toHaveAttribute('aria-sort');
		expect(heads[1]).not.toHaveAttribute('aria-sort');
		expect(heads[2]).toHaveAttribute('aria-sort', 'descending');
		expect(within(table).getByRole('rowheader', { name: 'alpha' })).toHaveAttribute('scope', 'row');
		expect(
			within(heads[2]).getByRole('link', { name: 'Sort by Created at ascending' })
		).toHaveAttribute('href', '/orgs/helio?sort=created_at&order=asc');
	});
	it('renders GET navigation links that change one list without losing the other cursor', () => {
		page.url = new URL(
			'http://localhost:4173/catalogs/a/namespaces/n?namespaces_cursor=n2&collections_cursor=c2'
		);
		render(BrowseTable, {
			label: 'Namespaces',
			sort: { sort: 'name', order: 'asc' },
			prefix: 'namespaces',
			children
		});
		const link = screen.getByRole('link', { name: 'Sort by Name descending' });
		expect(link).toHaveAttribute(
			'href',
			'/catalogs/a/namespaces/n?collections_cursor=c2&namespaces_sort=name&namespaces_order=desc'
		);
	});
});
