import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { catalogFixture } from '$lib/testing/api-fixtures';
import { resetAppState } from '$lib/testing/app-state.svelte';
import CatalogList from './CatalogList.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(resetAppState);

describe('catalog table', () => {
	it('links its sortable name with separate namespace count and creation details', () => {
		render(CatalogList, {
			catalogs: [catalogFixture({ namespace_count: 9 })],
			sort: { sort: 'name', order: 'asc' }
		});
		const table = screen.getByRole('table', { name: 'Catalogs' });
		const row = within(table).getByRole('rowheader');
		expect(within(row).getByRole('link', { name: 'heliophysics' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics'
		);
		expect(within(row).getByRole('link')).toHaveAttribute('title', 'Heliophysics');
		expect(within(table).getByRole('columnheader', { name: 'Namespaces' })).toBeInTheDocument();
		expect(within(table).getByRole('cell', { name: '9' })).toBeInTheDocument();
		expect(within(table).getByRole('cell', { name: 'sub-bob' })).toBeInTheDocument();
		expect(table.querySelector('time')).toHaveTextContent('2026-10-01 09:00 UTC');
	});
	it('has no data rows for an empty list', () => {
		render(CatalogList, { catalogs: [], sort: { sort: 'name', order: 'asc' } });
		expect(screen.queryByRole('rowheader')).toBeNull();
	});
});
