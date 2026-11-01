import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { schemaSummary } from '$lib/schemas';
import { schemaFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { catalogPageData } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(resetAppState);

function show({ empty = false, platform = false, cursor = false } = {}) {
	page.url = new URL(
		`http://localhost:4173/schemas?organization=${platform ? '' : 'helio'}${cursor ? '&cursor=second' : ''}`
	);
	render(Page, {
		props: {
			data: {
				...catalogPageData(),
				schemaOrganization: platform ? null : organizationFixture(),
				organizationChoices: [organizationFixture()],
				moreOrganizations: false,
				schemas: empty
					? []
					: [schemaSummary(schemaFixture({ extends_id: '0192f2a4-0000-7000-8000-000000000202' }))],
				nextCursor: empty ? null : 'next'
			},
			params: {},
			form: undefined
		}
	});
}

describe('the schema registry', () => {
	it('shows published versions, parent links, publication data and a GET scope selector', () => {
		show();
		expect(screen.getByRole('heading', { name: 'Schemas', level: 1 })).toBeInTheDocument();
		expect(screen.getByRole('combobox', { name: 'Schema source' })).toHaveValue('helio');
		expect(screen.getByRole('button', { name: 'Browse schemas' }).closest('form')).toHaveAttribute(
			'method',
			'GET'
		);
		const table = screen.getByRole('table', { name: 'Published schema versions' });
		expect(within(table).getByRole('link', { name: 'huron-base' })).toHaveAttribute(
			'href',
			`/schemas/${schemaFixture().id}?organization=helio`
		);
		expect(within(table).getByRole('link', { name: 'View parent schema' })).toHaveAttribute(
			'href',
			'/schemas/0192f2a4-0000-7000-8000-000000000202'
		);
		expect(table).toHaveTextContent('v1');
		expect(table).toHaveTextContent('2026-10-01 09:00 UTC');
		expect(table).toHaveTextContent('sub-alice');
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/schemas?organization=helio&cursor=next'
		);
	});

	it('explains platform scope and keeps its explicit empty organization in paging', () => {
		show({ platform: true });
		expect(screen.getByRole('heading', { name: 'Platform schemas' })).toBeInTheDocument();
		expect(
			screen.getByText('Platform schemas are available to every organization.')
		).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/schemas?organization=&cursor=next'
		);
	});

	it('explains an empty first page', () => {
		show({ empty: true });
		expect(screen.getByText('No schema versions have been published here.')).toBeInTheDocument();
		expect(screen.queryByRole('table')).toBeNull();
	});

	it('offers the first page when a later page has no versions', () => {
		show({ empty: true, cursor: true });
		expect(screen.getByText('No schema versions on this page.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/schemas?organization=helio'
		);
	});
});
