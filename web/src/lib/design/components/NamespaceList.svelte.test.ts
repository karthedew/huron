import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { namespaceFixture } from '$lib/testing/api-fixtures';
import { resetAppState } from '$lib/testing/app-state.svelte';
import NamespaceList from './NamespaceList.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(resetAppState);

describe('namespace table', () => {
	it('shows a compact linked name with separate counts, creator and creation time', () => {
		render(NamespaceList, {
			label: 'Namespaces',
			namespaces: [
				namespaceFixture({
					name: 'ace',
					path: 'solar-wind.ace',
					collections_allowed: true,
					collection_count: 4
				})
			],
			sort: { sort: 'name', order: 'asc' }
		});
		const table = screen.getByRole('table', { name: 'Namespaces' });
		const row = within(table).getByRole('rowheader');
		expect(within(row).getByRole('link', { name: 'ace' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind.ace'
		);
		expect(row).toHaveTextContent(/^ace$/);
		expect(
			within(table)
				.getAllByRole('columnheader')
				.map((head) => head.textContent?.trim())
		).toEqual(['Name', 'Namespaces', 'Collections', 'Created by', 'Created at']);
		expect(
			within(table)
				.getAllByRole('cell')
				.slice(0, 2)
				.map((cell) => cell.textContent)
		).toEqual(['2', '4']);
		expect(within(table).getByRole('cell', { name: 'sub-carol' })).toBeInTheDocument();
		expect(table.querySelector('time')).toHaveAttribute('datetime', '2026-10-01T09:00:00.000Z');
		expect(table.querySelector('time')).toHaveTextContent('2026-10-01 09:00 UTC');
	});
	it('handles an empty list and bounds unusually long creator text', () => {
		const { rerender } = render(NamespaceList, {
			label: 'Namespaces',
			namespaces: [],
			sort: { sort: 'name', order: 'asc' }
		});
		expect(screen.queryByRole('rowheader')).toBeNull();
		return rerender({
			label: 'Namespaces',
			namespaces: [namespaceFixture({ created_by: 'x'.repeat(500) })],
			sort: { sort: 'name', order: 'asc' }
		}).then(() => {
			expect(screen.getByRole('cell', { name: 'x'.repeat(200) + '…' })).toBeInTheDocument();
		});
	});
});
