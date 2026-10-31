import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Namespace, RoleGrant } from '$api/types';
import { collectionRow, type CollectionRow } from '$lib/collections';
import { collectionFixture, namespaceFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
	Reflect.deleteProperty(navigator, 'clipboard');
});

const ACE = namespaceFixture({
	id: 'n-ace',
	name: 'ace',
	path: 'solar-wind.ace',
	parent: 'solar-wind',
	identifier: 'heliophysics.solar-wind.ace',
	collections_allowed: true,
	namespace_count: 0,
	collection_count: 3,
	disk_path: 'helio/heliophysics/solar-wind/ace'
});
const SOLAR_WIND = namespaceFixture();
const MAG = collectionRow(collectionFixture({ updated_at: '2026-10-03T09:00:00+00:00' }));
const DRAFT = collectionRow(
	collectionFixture({
		id: 'c-draft',
		name: 'mag-l1-draft',
		identifier: 'heliophysics.solar-wind.ace.mag-l1-draft',
		state: 'draft',
		file_count: 0,
		metadata: { title: 'ACE MAG level 1 (draft)' }
	})
);

interface ShowOptions {
	namespaces?: Namespace[];
	collections?: CollectionRow[];
	namespacesNext?: string | null;
	collectionsNext?: string | null;
	roles?: RoleGrant[];
	path?: string;
}

async function show(
	namespace: Namespace,
	{
		namespaces = [],
		collections = [],
		namespacesNext = null,
		collectionsNext = null,
		roles = [],
		path = `/catalogs/heliophysics/namespaces/${namespace.path}`
	}: ShowOptions = {}
) {
	page.url = new URL(`http://localhost:4173${path}`);
	render(Page, {
		props: {
			data: {
				...catalogPageData({ roles }),
				namespace,
				sharePath: `/projects/huron/${namespace.disk_path}`,
				namespaces,
				namespacesNext,
				collections,
				collectionsNext,
				trail: []
			},
			params: { catalog: 'heliophysics', path: namespace.path },
			form: undefined
		}
	});
	await tick();
}

describe('a namespace page', () => {
	it('keeps its Namespaces section and the way back on an empty later page, beside its collections', async () => {
		await show(ACE, {
			collections: [MAG],
			path: '/catalogs/heliophysics/namespaces/solar-wind.ace?namespaces_cursor=n'
		});
		expect(screen.getByText('No namespaces on this page.')).toBeInTheDocument();
		expect(
			within(screen.getByRole('navigation', { name: 'Namespace pages' })).getByRole('link', {
				name: 'First page'
			})
		).toBeInTheDocument();
	});

	it('heads the page with the name, identifier, kind, contents and share path', async () => {
		await show(ACE, { collections: [MAG, DRAFT] });
		expect(screen.getByRole('heading', { level: 1, name: 'ace' })).toBeInTheDocument();
		expect(screen.getByText('heliophysics.solar-wind.ace')).toBeInTheDocument();
		const header = screen.getByRole('banner');
		expect(header).toHaveTextContent('Holds collections');
		expect(header).toHaveTextContent('3 collections');
		expect(
			within(header).getByText('/projects/huron/helio/heliophysics/solar-wind/ace').tagName
		).toBe('CODE');
		expect(document.title).toBe('solar-wind.ace · Heliophysics · Huron');
	});

	it('copies the share path where the browser has a clipboard', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		await show(ACE);
		screen.getByRole('button', { name: 'Copy share path' }).click();
		await tick();
		expect(writeText).toHaveBeenCalledWith('/projects/huron/helio/heliophysics/solar-wind/ace');
		expect(await screen.findByText('Copied')).toBeInTheDocument();
	});

	it('lists collections in two lines with their state when it is not active', async () => {
		await show(ACE, { collections: [MAG, DRAFT] });
		const [mag, draft] = within(
			screen.getByRole('list', { name: 'Collections in ace' })
		).getAllByRole('listitem');
		expect(
			within(mag).getByRole('link', { name: 'ACE magnetometer level 2, 2024' })
		).toHaveAttribute('href', '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024');
		expect(mag).toHaveTextContent('heliophysics.solar-wind.ace.mag-l2-2024');
		expect(mag).toHaveTextContent('3 files');
		expect(mag).toHaveTextContent('Updated 2026-10-03 09:00 UTC');
		expect(mag).not.toHaveTextContent('Active');
		expect(draft).toHaveTextContent('Draft');
		expect(draft).toHaveTextContent('0 files');
	});

	it('pages each list on its own and keeps the other cursor', async () => {
		await show(SOLAR_WIND, {
			namespaces: [ACE],
			namespacesNext: 'n2',
			path: '/catalogs/heliophysics/namespaces/solar-wind?collections_cursor=c1'
		});
		const pages = screen.getByRole('navigation', { name: 'Namespace pages' });
		expect(within(pages).getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind?collections_cursor=c1&namespaces_cursor=n2'
		);
	});

	it('offers contributors the command to create a collection here', async () => {
		await show(ACE, { collections: [MAG], roles: [catalogRole('contributor')] });
		const hint = screen.getByRole('region', { name: 'Create a collection here' });
		expect(within(hint).getByRole('textbox')).toHaveValue(
			'huron --catalog heliophysics collection create heliophysics.solar-wind.ace.<name>'
		);
		expect(screen.queryByRole('region', { name: 'Create a namespace here' })).toBeNull();
	});

	it('says an empty namespace for collections has none yet, with the hint for contributors', async () => {
		const empty = { ...ACE, name: 'empty', path: 'empty', collection_count: 0 };
		await show(empty, { roles: [catalogRole('contributor')] });
		expect(screen.getByText('No collections yet.')).toBeInTheDocument();
		expect(screen.getByRole('region', { name: 'Create a collection here' })).toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Namespaces' })).toBeNull();
		document.body.innerHTML = '';
		await show(empty);
		expect(screen.getByText('No collections yet.')).toBeInTheDocument();
		expect(screen.queryByRole('region', { name: /Create/ })).toBeNull();
	});

	it('lists the namespaces of a structure-only namespace, with the hint for administrators', async () => {
		await show(SOLAR_WIND, { namespaces: [ACE], roles: [catalogRole('catalog_admin')] });
		expect(screen.getByRole('banner')).toHaveTextContent('Structure only');
		expect(screen.getByRole('banner')).toHaveTextContent('2 namespaces');
		const [ace] = within(
			screen.getByRole('list', { name: 'Namespaces in solar-wind' })
		).getAllByRole('listitem');
		expect(ace).toHaveTextContent('Holds collections');
		expect(ace).toHaveTextContent('3 collections');
		expect(screen.queryByRole('heading', { name: 'Collections' })).toBeNull();
		const hint = screen.getByRole('region', { name: 'Create a namespace here' });
		expect(within(hint).getByRole('textbox')).toHaveValue(
			'huron --catalog heliophysics namespace create heliophysics.solar-wind.<name> --allow-collections'
		);
		expect(screen.queryByRole('region', { name: 'Create a collection here' })).toBeNull();
	});

	it('says an empty structure-only namespace has no namespaces yet', async () => {
		const bare = { ...SOLAR_WIND, namespace_count: 0 };
		await show(bare, { roles: [catalogRole('catalog_admin')] });
		expect(screen.getByText('No namespaces yet.')).toBeInTheDocument();
		expect(screen.getByRole('region', { name: 'Create a namespace here' })).toBeInTheDocument();
		document.body.innerHTML = '';
		await show(bare, { roles: [catalogRole('contributor')] });
		expect(screen.getByText('No namespaces yet.')).toBeInTheDocument();
		expect(screen.queryByRole('region', { name: /Create/ })).toBeNull();
	});

	it('says when a later page of a list is empty', async () => {
		await show(ACE, {
			path: '/catalogs/heliophysics/namespaces/solar-wind.ace?collections_cursor=c9'
		});
		expect(screen.getByText('No collections on this page.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind.ace'
		);
	});
});
