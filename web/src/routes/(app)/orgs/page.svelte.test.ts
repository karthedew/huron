import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ page: { url: new URL('http://localhost:4173/orgs') } }));
vi.mock('$app/state', () => state);

afterEach(() => {
	state.page.url = new URL('http://localhost:4173/orgs');
});

const HELIO = organizationFixture();
const GEO = organizationFixture({
	id: 'o-geo',
	name: 'geo',
	display_name: 'Earth Science',
	description: '',
	catalog_count: 1
});

function show(
	organizationList: Organization[],
	nextCursor: string | null = null,
	path = '/orgs',
	groups = ['helio-readers']
) {
	state.page.url = new URL(`http://localhost:4173${path}`);
	return render(Page, {
		props: {
			data: {
				user: fakeUser({ groups }),
				organizations: organizationList,
				organizationsUnavailable: false,
				roles: [],
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: null,
				organizationList,
				nextCursor
			},
			params: {},
			form: undefined
		}
	});
}

describe('/orgs page', () => {
	it('shows a card per organization', () => {
		show([GEO, HELIO]);
		expect(
			screen.getByRole('heading', { level: 1, name: 'All organizations' })
		).toBeInTheDocument();
		const [geo, helio] = screen.getAllByRole('link');
		expect(geo).toHaveAttribute('href', '/orgs/geo');
		expect(within(geo).getByText('Earth Science')).toBeInTheDocument();
		expect(within(geo).getByText('geo')).toBeInTheDocument();
		expect(within(geo).getByText('1 catalog')).toBeInTheDocument();
		expect(within(helio).getByText('Sun and solar wind.')).toBeInTheDocument();
		expect(within(helio).getByText('2 catalogs')).toBeInTheDocument();
		expect(document.title).toBe('All organizations · Huron');
	});

	it('names an organization without a display name once', () => {
		show([organizationFixture({ display_name: '' })]);
		const card = screen.getByRole('link');
		expect(within(card).getAllByText('helio')).toHaveLength(1);
	});

	it('pages through the organizations', () => {
		show([GEO], 'c2');
		const pages = screen.getByRole('navigation', { name: 'Organization pages' });
		expect(within(pages).getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/orgs?cursor=c2'
		);
	});

	it('explains an empty first page with the groups and a sign-out button', () => {
		show([], null, '/orgs', ['helio-readers', 'lab-members']);
		expect(screen.getByText("You don't have access to any organization yet.")).toBeInTheDocument();
		expect(screen.getByText('helio-readers')).toBeInTheDocument();
		expect(screen.getByText('lab-members')).toBeInTheDocument();
		expect(
			screen.getByText(/Groups are read when you sign in; if you were just added to a group/)
		).toBeInTheDocument();
		const form = screen.getByRole('button', { name: 'Sign out' }).closest('form');
		expect(form).toHaveAttribute('action', '/logout');
		expect(form).toHaveAttribute('method', 'POST');
	});

	it('says on an empty first page when Huron received no groups', () => {
		show([], null, '/orgs', []);
		expect(screen.getByText('Huron received no groups for your account.')).toBeInTheDocument();
	});

	it('says an empty later page holds no organizations', () => {
		show([], null, '/orgs?cursor=c9');
		expect(screen.getByText('No organizations on this page.')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
	});

	it('says when an expired page link brought the user back to the first page', () => {
		show([HELIO], null, '/orgs?notice=page_expired');
		expect(screen.getByRole('note')).toHaveTextContent(
			'That page link expired; showing the first page.'
		);
	});
});
