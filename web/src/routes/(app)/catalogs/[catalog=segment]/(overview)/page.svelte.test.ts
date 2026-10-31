import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Namespace, RoleGrant } from '$api/types';
import { namespaceFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const ROOT = [
	namespaceFixture({
		id: 'n1',
		name: 'fields',
		path: 'fields',
		collections_allowed: true,
		namespace_count: 0,
		collection_count: 60
	}),
	namespaceFixture({ id: 'n2', name: 'solar-wind', path: 'solar-wind', namespace_count: 2 })
];

async function show(
	namespaces: Namespace[],
	{
		roles = [],
		nextCursor = null,
		path = '/catalogs/heliophysics'
	}: { roles?: RoleGrant[]; nextCursor?: string | null; path?: string } = {}
) {
	page.url = new URL(`http://localhost:4173${path}`);
	render(Page, {
		props: {
			data: { ...catalogPageData({ roles }), namespaces, nextCursor },
			params: { catalog: 'heliophysics' },
			form: undefined
		}
	});
	await tick();
}

describe('the catalog overview', () => {
	it('lists the top-level namespaces with their kind and what they hold', async () => {
		await show(ROOT);
		const [fields, solarWind] = within(
			screen.getByRole('list', { name: 'Top-level namespaces' })
		).getAllByRole('listitem');
		expect(within(fields).getByRole('link', { name: 'fields' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/fields'
		);
		expect(fields).toHaveTextContent('Holds collections');
		expect(fields).toHaveTextContent('60 collections');
		expect(solarWind).toHaveTextContent('Structure only');
		expect(solarWind).toHaveTextContent('2 namespaces');
		expect(document.title).toBe('Heliophysics · Heliophysics Division · Huron');
		expect(screen.queryByRole('region', { name: /Create/ })).toBeNull();
	});

	it('shows catalog administrators how to add a namespace', async () => {
		await show(ROOT, { roles: [catalogRole('catalog_admin')] });
		const hint = screen.getByRole('region', { name: 'Create a namespace here' });
		expect(within(hint).getByRole('textbox')).toHaveValue(
			'huron --catalog heliophysics namespace create heliophysics.<name> --allow-collections'
		);
		expect(screen.getByText(/the new namespace holds only other namespaces/)).toBeInTheDocument();
	});

	it('shows contributors no hint', async () => {
		await show(ROOT, { roles: [catalogRole('contributor')] });
		expect(screen.queryByRole('region', { name: /Create/ })).toBeNull();
	});

	it('says when the catalog has no namespaces, with the hint for administrators', async () => {
		await show([], { roles: [catalogRole('catalog_admin')] });
		expect(screen.getByText('No namespaces yet.')).toBeInTheDocument();
		expect(screen.getByRole('region', { name: 'Create a namespace here' })).toBeInTheDocument();
	});

	it('pages through the namespaces and says when a later page is empty', async () => {
		await show(ROOT, { nextCursor: 'n3' });
		expect(
			within(screen.getByRole('navigation', { name: 'Namespace pages' })).getByRole('link', {
				name: 'Next page'
			})
		).toHaveAttribute('href', '/catalogs/heliophysics?cursor=n3');
		document.body.innerHTML = '';
		await show([], { path: '/catalogs/heliophysics?cursor=n9' });
		expect(screen.getByText('No namespaces on this page.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics'
		);
	});

	it('says when the page link it came from expired', async () => {
		await show(ROOT, { path: '/catalogs/heliophysics?notice=page_expired' });
		expect(screen.getByRole('note')).toHaveTextContent(
			'That page link expired; showing the first page.'
		);
	});
});
