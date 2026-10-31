import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { catalogFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData } from '$lib/testing/catalog-data';
import Layout from './+layout.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

function show(data = catalogPageData()) {
	render(Layout, {
		props: {
			data,
			params: { catalog: 'heliophysics' },
			children: createRawSnippet(() => ({ render: () => '<p>The tab</p>' }))
		}
	});
}

describe('the catalog overview layout', () => {
	it('heads the tabs with the catalog, its organization, schema and size', () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)' };
		show();
		const header = screen.getByRole('banner');
		expect(within(header).getByRole('heading', { level: 1, name: 'Heliophysics' })).toBeVisible();
		expect(within(header).getByText('heliophysics')).toBeInTheDocument();
		expect(
			within(header).getByText('Solar wind, fields and energetic particles.')
		).toBeInTheDocument();
		expect(within(header).getByRole('link', { name: 'Heliophysics Division' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
		expect(within(header).getByRole('link', { name: 'huron-base v1' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/schema'
		);
		expect(within(header).getByText('4 namespaces in total')).toBeInTheDocument();
		expect(screen.getByText('The tab')).toBeInTheDocument();
	});

	it('links the five tabs and marks the current one', () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)/access' };
		show();
		const tabs = within(screen.getByRole('navigation', { name: 'Catalog' })).getAllByRole('link');
		expect(tabs.map((tab) => [tab.textContent, tab.getAttribute('href')])).toEqual([
			['Overview', '/catalogs/heliophysics'],
			['Search', '/catalogs/heliophysics/search'],
			['Access', '/catalogs/heliophysics/access'],
			['Activity', '/catalogs/heliophysics/activity'],
			['Schema', '/catalogs/heliophysics/schema']
		]);
		expect(tabs.filter((tab) => tab.getAttribute('aria-current') === 'page')).toEqual([tabs[2]]);
	});

	it('marks Search on the catalog search, whatever its query', () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)/search' };
		page.url = new URL('http://localhost:4173/catalogs/heliophysics/search?q=wind&cursor=c2');
		show();
		const tabs = within(screen.getByRole('navigation', { name: 'Catalog' })).getAllByRole('link');
		expect(tabs.filter((tab) => tab.getAttribute('aria-current') === 'page')).toEqual([tabs[1]]);
		expect(tabs[1]).toHaveAttribute('href', '/catalogs/heliophysics/search');
	});

	it('names an organization the list does not hold by its name', () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)' };
		show({
			...catalogPageData(),
			organizations: [],
			catalog: catalogFixture({ display_name: '', namespace_count: 1 })
		});
		expect(screen.getByRole('link', { name: 'helio' })).toHaveAttribute('href', '/orgs/helio');
		expect(screen.getByRole('heading', { level: 1, name: 'heliophysics' })).toBeInTheDocument();
		expect(screen.getAllByText('heliophysics')).toHaveLength(1);
		expect(screen.getByText('1 namespace in total')).toBeInTheDocument();
	});
});
