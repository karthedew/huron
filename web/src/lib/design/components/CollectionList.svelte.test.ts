import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { collectionRow } from '$lib/collections';
import { collectionFixture } from '$lib/testing/api-fixtures';
import { resetAppState } from '$lib/testing/app-state.svelte';
import CollectionList from './CollectionList.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(resetAppState);

describe('collection table', () => {
	it('links the name used for sorting and retains the metadata title, files and creation details', () => {
		render(CollectionList, {
			label: 'Collections',
			collections: [collectionRow(collectionFixture())],
			sort: { sort: 'name', order: 'asc' }
		});
		const table = screen.getByRole('table', { name: 'Collections' });
		const row = within(table).getByRole('rowheader');
		expect(within(row).getByRole('link', { name: 'mag-l2-2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		expect(within(row).getByRole('link')).toHaveAttribute(
			'title',
			'ACE magnetometer level 2, 2024'
		);
		expect(within(table).getByRole('columnheader', { name: 'Files' })).toBeInTheDocument();
		expect(within(table).getByRole('cell', { name: '3' })).toBeInTheDocument();
		expect(within(table).getByRole('cell', { name: 'sub-dave' })).toBeInTheDocument();
		expect(table.querySelector('time')).toHaveAttribute('datetime', '2026-10-02T09:00:00.000Z');
	});
	it('shows a draft without repeating a missing metadata title', () => {
		render(CollectionList, {
			label: 'Collections',
			collections: [collectionRow(collectionFixture({ state: 'draft', metadata: {} }))],
			sort: { sort: 'name', order: 'asc' }
		});
		expect(screen.getByRole('rowheader')).toHaveTextContent('Draft');
		expect(screen.getAllByText('mag-l2-2024')).toHaveLength(1);
	});
	it('renders no rows for an empty list', () => {
		render(CollectionList, {
			label: 'Collections',
			collections: [],
			sort: { sort: 'name', order: 'asc' }
		});
		expect(screen.queryByRole('rowheader')).toBeNull();
	});
});
