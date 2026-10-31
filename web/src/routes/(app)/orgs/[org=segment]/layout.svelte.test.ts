import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { fakeUser } from '$lib/testing/events';
import Layout from './+layout.svelte';

const state = vi.hoisted(() => {
	const route: { id: string | null } = { id: '/(app)/orgs/[org=segment]' };
	return { page: { route, url: new URL('http://localhost:4173/orgs/helio') } };
});
vi.mock('$app/state', () => state);

function show(organization: Organization) {
	return render(Layout, {
		props: {
			data: {
				user: fakeUser(),
				organizations: [organization],
				organizationsUnavailable: false,
				roles: [],
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: organization.name,
				organizationDetails: organization
			},
			params: { org: organization.name },
			children: createRawSnippet(() => ({ render: () => '<p>The page</p>' }))
		}
	});
}

describe('/orgs/[org] layout', () => {
	it("heads the organization's pages with its names, description and sections", () => {
		show(organizationFixture());
		expect(
			screen.getByRole('heading', { level: 1, name: 'Heliophysics Division' })
		).toBeInTheDocument();
		expect(screen.getByText('helio')).toBeInTheDocument();
		expect(screen.getByText('Sun and solar wind.')).toBeInTheDocument();
		const sections = screen.getByRole('navigation', { name: 'Organization' });
		const [catalogs, search] = within(sections).getAllByRole('link');
		expect(catalogs).toHaveTextContent('Catalogs2');
		expect(catalogs).toHaveAttribute('href', '/orgs/helio');
		expect(catalogs).toHaveAttribute('aria-current', 'page');
		expect(search).toHaveTextContent(/^Search$/);
		expect(search).toHaveAttribute('href', '/orgs/helio/search');
		expect(search).not.toHaveAttribute('aria-current');
		expect(screen.getByText('The page')).toBeInTheDocument();
	});

	it('marks Search as the section of the organization search', () => {
		state.page.route.id = '/(app)/orgs/[org=segment]/search';
		try {
			show(organizationFixture());
			const sections = screen.getByRole('navigation', { name: 'Organization' });
			expect(within(sections).getByRole('link', { name: 'Search' })).toHaveAttribute(
				'aria-current',
				'page'
			);
			expect(within(sections).getByRole('link', { name: /^Catalogs/ })).not.toHaveAttribute(
				'aria-current'
			);
		} finally {
			state.page.route.id = '/(app)/orgs/[org=segment]';
		}
	});

	it('shows the name only once when there is no display name', () => {
		show(organizationFixture({ display_name: '', description: '' }));
		expect(screen.getByRole('heading', { level: 1, name: 'helio' })).toBeInTheDocument();
		expect(screen.getAllByText('helio')).toHaveLength(1);
	});
});
