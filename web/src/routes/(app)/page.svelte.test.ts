import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Organization } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

function show(organizationList: Organization[], groups: string[] = ['helio-readers']) {
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
				organizationList
			},
			params: {},
			form: undefined
		}
	});
}

describe('/ page', () => {
	it('lists organizations with their names, descriptions and catalog counts', () => {
		show([
			organizationFixture(),
			organizationFixture({
				id: 'o2',
				name: 'geo',
				display_name: '',
				description: '',
				catalog_count: 1
			})
		]);
		expect(screen.getByRole('heading', { level: 1, name: 'Organizations' })).toBeInTheDocument();
		const links = screen.getAllByRole('link');
		expect(links.map((link) => link.getAttribute('href'))).toEqual(['/orgs/helio', '/orgs/geo']);
		expect(within(links[0]).getByText('Heliophysics Division')).toBeInTheDocument();
		expect(within(links[0]).getByText('helio')).toBeInTheDocument();
		expect(within(links[0]).getByText('2 catalogs')).toBeInTheDocument();
		expect(within(links[1]).getByText('geo')).toBeInTheDocument();
		expect(within(links[1]).getByText('1 catalog')).toBeInTheDocument();
	});

	it('explains the empty state with the groups and a sign-out button', () => {
		show([], ['helio-readers', 'lab-members']);
		expect(screen.getAllByRole('heading')).toHaveLength(1);
		expect(screen.getByRole('heading', { level: 1, name: 'Organizations' })).toBeInTheDocument();
		expect(screen.getByText("You don't have access to any organization yet.")).toBeInTheDocument();
		expect(screen.getByText('helio-readers')).toBeInTheDocument();
		expect(screen.getByText('lab-members')).toBeInTheDocument();
		expect(
			screen.getByText(/Groups are read when you sign in; if you were just added to a group/)
		).toBeInTheDocument();
		const button = screen.getByRole('button', { name: 'Sign out' });
		expect(button.closest('form')).toHaveAttribute('action', '/logout');
		expect(button.closest('form')).toHaveAttribute('method', 'POST');
	});

	it('says when Huron received no groups', () => {
		show([], []);
		expect(screen.getByText('Huron received no groups for your account.')).toBeInTheDocument();
	});
});
