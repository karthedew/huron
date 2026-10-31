import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ExplorerLevel } from '$lib/explorer';
import { catalogFixture, fakeFetch, jsonResponse } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData } from '$lib/testing/catalog-data';
import Layout from './+layout.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
vi.mock('$app/navigation', () => ({ afterNavigate: () => undefined }));

afterEach(() => {
	resetAppState();
	vi.unstubAllGlobals();
});

const DEEP: ExplorerLevel = {
	parent: 'deep',
	namespaces: [{ name: 'a', path: 'deep.a', empty: false }],
	namespacesNext: null,
	collections: [],
	collectionsNext: null
};

const FIELDS: ExplorerLevel = {
	parent: 'fields',
	namespaces: [],
	namespacesNext: null,
	collections: [{ name: 'run001', identifier: 'heliophysics.fields.run001' }],
	collectionsNext: null
};

/** Another catalog of the organization, without a `fields` namespace. */
function spaceWeatherData() {
	return {
		...catalogPageData(),
		catalog: catalogFixture({
			id: '0192f2a4-0000-7000-8000-000000000102',
			name: 'space-weather',
			display_name: 'Space Weather'
		}),
		root: {
			parent: '',
			namespaces: [{ name: 'alerts', path: 'alerts', empty: false }],
			namespacesNext: null,
			collections: [],
			collectionsNext: null
		}
	};
}

async function show(data = catalogPageData()) {
	const shown = render(Layout, {
		props: {
			data,
			params: { catalog: data.catalog.name },
			children: createRawSnippet(() => ({ render: () => '<h1>The page</h1>' }))
		}
	});
	await tick();
	return shown;
}

function crumbs() {
	return within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getAllByRole('link');
}

describe('/catalogs/[catalog] layout', () => {
	it('leads from the organization to the catalog on the overview', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)' };
		page.params = { catalog: 'heliophysics' };
		await show();
		const [organization, catalog] = crumbs();
		expect(organization).toHaveTextContent('Heliophysics Division');
		expect(organization).toHaveAttribute('href', '/orgs/helio');
		expect(organization).not.toHaveAttribute('aria-current');
		expect(catalog).toHaveTextContent('Heliophysics');
		expect(catalog).toHaveAttribute('href', '/catalogs/heliophysics');
		expect(catalog).toHaveAttribute('aria-current', 'page');
		expect(crumbs()).toHaveLength(2);
	});

	it('marks no crumb on the catalog tabs, whose sub-navigation marks them', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)/activity' };
		page.params = { catalog: 'heliophysics' };
		await show();
		expect(crumbs().filter((link) => link.hasAttribute('aria-current'))).toEqual([]);
	});

	it('marks the catalog in the explorer as the section of its search, and no crumb', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)/search' };
		page.params = { catalog: 'heliophysics' };
		page.url = new URL('http://localhost:4173/catalogs/heliophysics/search?q=wind');
		await show();
		expect(crumbs().map((link) => link.textContent)).toEqual([
			'Heliophysics Division',
			'Heliophysics'
		]);
		expect(crumbs().filter((link) => link.hasAttribute('aria-current'))).toEqual([]);
		const explorer = screen.getByRole('navigation', { name: 'Explorer' });
		expect(within(explorer).getByRole('link', { name: 'Heliophysics' })).toHaveAttribute(
			'aria-current',
			'true'
		);
	});

	it('adds every namespace on the way on a namespace page', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]' };
		page.params = { catalog: 'heliophysics', path: 'deep.a' };
		page.data = { trail: [DEEP] };
		await show();
		expect(crumbs().map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Heliophysics Division', '/orgs/helio'],
			['Heliophysics', '/catalogs/heliophysics'],
			['deep', '/catalogs/heliophysics/namespaces/deep'],
			['a', '/catalogs/heliophysics/namespaces/deep.a']
		]);
		expect(crumbs().at(-1)).toHaveAttribute('aria-current', 'page');
		// The page's trail reaches the explorer: the current namespace is in the tree.
		expect(
			within(screen.getByRole('navigation', { name: 'Explorer' })).getByRole('link', {
				name: 'a'
			})
		).toHaveAttribute('aria-current', 'page');
	});

	it('ends with the collection on a collection page', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]' };
		page.params = { catalog: 'heliophysics', identifier: 'deep.a.leaf' };
		page.data = { trail: [DEEP] };
		await show();
		expect(crumbs().map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Heliophysics Division', '/orgs/helio'],
			['Heliophysics', '/catalogs/heliophysics'],
			['deep', '/catalogs/heliophysics/namespaces/deep'],
			['a', '/catalogs/heliophysics/namespaces/deep.a'],
			['leaf', '/catalogs/heliophysics/collections/deep.a.leaf']
		]);
		expect(crumbs().filter((link) => link.hasAttribute('aria-current'))).toEqual([crumbs()[4]]);
	});

	it("marks no crumb on a collection's other tabs, whose sub-navigation marks them", async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/files' };
		page.params = { catalog: 'heliophysics', identifier: 'deep.a.leaf' };
		page.data = { trail: [DEEP] };
		await show();
		expect(crumbs().at(-1)).toHaveTextContent('leaf');
		expect(crumbs().filter((link) => link.hasAttribute('aria-current'))).toEqual([]);
	});

	it('stands in the catalog alone on an error page, whose address may name nothing', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]' };
		page.params = { catalog: 'heliophysics', path: 'solar-wind.nope' };
		page.error = { message: "Not found, or you don't have access." };
		page.status = 404;
		await show();
		expect(crumbs().map((link) => link.textContent)).toEqual([
			'Heliophysics Division',
			'Heliophysics'
		]);
		expect(crumbs().filter((link) => link.hasAttribute('aria-current'))).toEqual([]);
		const explorer = screen.getByRole('navigation', { name: 'Explorer' });
		expect(within(explorer).queryByRole('link', { name: 'nope' })).toBeNull();
		expect(within(explorer).getByRole('link', { name: 'Heliophysics' })).toHaveAttribute(
			'aria-current',
			'true'
		);
		expect(
			within(explorer).getByRole('button', { name: 'Contents of solar-wind' })
		).toHaveAttribute('aria-expanded', 'false');
	});

	it("starts a new explorer in another catalog, leaving the last one's folders behind", async () => {
		const fake = fakeFetch(jsonResponse(FIELDS));
		vi.stubGlobal('fetch', fake.fetch);
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)' };
		page.params = { catalog: 'heliophysics' };
		const heliophysics = catalogPageData();
		const shown = await show(heliophysics);
		const explorer = () => within(screen.getByRole('navigation', { name: 'Explorer' }));
		const fields = () => explorer().getByRole('button', { name: 'Contents of fields' });
		await fireEvent.click(fields());
		expect(await explorer().findByRole('link', { name: 'run001' })).toBeInTheDocument();

		page.params = { catalog: 'space-weather' };
		await shown.rerender({ data: spaceWeatherData(), params: { catalog: 'space-weather' } });
		await tick();
		expect(explorer().getByRole('link', { name: 'alerts' })).toBeInTheDocument();
		expect(explorer().queryByRole('button', { name: 'Contents of fields' })).toBeNull();

		page.params = { catalog: 'heliophysics' };
		await shown.rerender({ data: heliophysics, params: { catalog: 'heliophysics' } });
		await tick();
		// Two catalogs may hold namespaces of the same path: what was opened and fetched in one
		// never shows in another, nor when coming back to it.
		expect(fields()).toHaveAttribute('aria-expanded', 'false');
		expect(explorer().queryByRole('link', { name: 'run001' })).toBeNull();
		await fireEvent.click(fields());
		expect(await explorer().findByRole('link', { name: 'run001' })).toBeInTheDocument();
		expect(fake.calls.map(({ url }) => url)).toEqual([
			'/catalogs/heliophysics/tree?parent=fields',
			'/catalogs/heliophysics/tree?parent=fields'
		]);
	});

	it('puts the content before the explorer', async () => {
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)' };
		await show();
		const heading = screen.getByRole('heading', { name: 'The page', level: 1 });
		const explorer = screen.getByRole('navigation', { name: 'Explorer' });
		expect(heading.compareDocumentPosition(explorer) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
			Node.DOCUMENT_POSITION_FOLLOWING
		);
		expect(within(explorer).getByRole('link', { name: 'Space Weather' })).toBeInTheDocument();
	});
});
