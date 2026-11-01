import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Catalog, RoleGrant } from '$api/types';
import { catalogFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ page: { url: new URL('http://localhost:4173/orgs/helio') } }));
vi.mock('$app/state', () => state);

afterEach(() => {
	state.page.url = new URL('http://localhost:4173/orgs/helio');
});

const HELIO = organizationFixture();

async function show(
	catalogs: Catalog[],
	{ roles = [], nextCursor = null, path = '/orgs/helio' }: ShowOptions = {}
) {
	state.page.url = new URL(`http://localhost:4173${path}`);
	render(Page, {
		props: {
			data: {
				user: fakeUser(),
				organizations: [HELIO],
				organizationsUnavailable: false,
				roles,
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: 'helio',
				organizationDetails: HELIO,
				organizationPath: '/projects/huron/helio',
				catalogs,
				catalogSort: { sort: 'name', order: 'asc' },
				nextCursor
			},
			params: { org: 'helio' },
			form: undefined
		}
	});
	await tick();
}

interface ShowOptions {
	roles?: RoleGrant[];
	nextCursor?: string | null;
	path?: string;
}

describe('/orgs/[org] page', () => {
	it('lists the catalogs with their names and separate namespace counts', async () => {
		await show([
			catalogFixture({ description: 'Solar wind and fields.', namespace_count: 9 }),
			catalogFixture({
				id: 'c2',
				name: 'space-weather',
				display_name: '',
				namespace_count: 1,
				schema: { id: 's2', name: 'space-weather', version: 1 }
			})
		]);
		const [heliophysics, spaceWeather] = within(screen.getByRole('table', { name: 'Catalogs' }))
			.getAllByRole('row')
			.slice(1);
		expect(within(heliophysics).getByRole('link', { name: 'heliophysics' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics'
		);
		expect(within(heliophysics).getByText('heliophysics')).toBeInTheDocument();
		expect(within(heliophysics).getByRole('cell', { name: '9' })).toBeInTheDocument();
		expect(within(spaceWeather).getAllByText('space-weather')).toHaveLength(1);
		expect(within(spaceWeather).getByRole('cell', { name: '1' })).toBeInTheDocument();
		expect(document.title).toBe('Catalogs · Heliophysics Division · Huron');
	});

	it('pages through the catalogs', async () => {
		await show([catalogFixture()], { nextCursor: 'c2', path: '/orgs/helio?cursor=c1' });
		const pages = screen.getByRole('navigation', { name: 'Catalog pages' });
		expect(within(pages).getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/orgs/helio?cursor=c2'
		);
		expect(within(pages).getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
	});

	it('says when a later page is empty', async () => {
		await show([], { path: '/orgs/helio?cursor=c9' });
		expect(screen.getByText('No catalogs on this page.')).toBeInTheDocument();
	});
});
