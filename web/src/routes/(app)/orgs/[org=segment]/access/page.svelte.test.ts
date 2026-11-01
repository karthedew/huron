import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import type { Organization, OrganizationGroups, RoleGrant } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

const HELIO = organizationFixture();

const GROUPS: OrganizationGroups = {
	org_admin: ['helio-org-admins'],
	catalog_admin: ['helio-catalog-admins'],
	contributor: [],
	reader: ['geo-readers', 'helio-readers']
};

interface ShowOptions {
	roles?: RoleGrant[];
	mine?: string[];
	organization?: Organization;
}

async function show(
	groups: OrganizationGroups | null,
	{ roles = [], mine = ['helio-readers'], organization = HELIO }: ShowOptions = {}
) {
	render(Page, {
		props: {
			data: {
				user: fakeUser({ groups: mine }),
				organizations: [organization],
				organizationsUnavailable: false,
				roles,
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: organization.name,
				organizationDetails: organization,
				organizationPath: `/projects/huron/${organization.name}`,
				groups
			},
			params: { org: organization.name },
			form: undefined
		}
	});
	await tick();
}

function role(name: string) {
	const heading = screen.getByRole('heading', { level: 3, name });
	const item = heading.closest('li');
	if (item === null) throw new Error(`no list item for ${name}`);
	return item;
}

const ORG_ADMIN: RoleGrant = { scope: 'organization', scope_id: HELIO.id, role: 'org_admin' };
const HINT = 'Grant a role on the organization';

describe('the organization access tab', () => {
	it('shows the groups of the four organization roles and marks the user’s', async () => {
		await show(GROUPS);
		const roles = within(screen.getByRole('list', { name: 'Roles' })).getAllByRole('heading');
		expect(roles.map((heading) => heading.textContent)).toEqual([
			'Organization administrator',
			'Catalog administrator',
			'Contributor',
			'Reader'
		]);
		expect(role('Reader')).toHaveTextContent(
			'Can browse namespaces, collections, files and activity, in every catalog of the organization.'
		);
		expect(role('Organization administrator')).not.toHaveTextContent(
			'in every catalog of the organization.'
		);
		const readers = within(role('Reader')).getAllByRole('listitem');
		expect(readers.map((item) => item.textContent?.trim())).toEqual([
			'geo-readers',
			'helio-readers You'
		]);
		expect(role('Contributor')).toHaveTextContent('No groups.');
		expect(document.title).toBe('Access · Heliophysics Division · Huron');
	});

	it('shows readers no hint', async () => {
		await show(GROUPS, {
			roles: [{ scope: 'organization', scope_id: HELIO.id, role: 'reader' }]
		});
		expect(screen.queryByRole('region', { name: HINT })).toBeNull();
	});

	it("says that a declared organization's groups are changed in the service configuration", async () => {
		const declared = organizationFixture({ declared: true });
		await show(GROUPS, { roles: [ORG_ADMIN], organization: declared });
		expect(screen.queryByRole('region', { name: HINT })).toBeNull();
		expect(screen.getByText(/declared in the service configuration, as/)).toHaveTextContent(
			'These groups are declared in the service configuration, as groups.<role> of the organization'
		);
	});

	it("says so when the API refuses the organization's groups", async () => {
		await show(null);
		expect(screen.getByText("You don't have permission to see this.")).toBeInTheDocument();
		expect(screen.queryByRole('list', { name: 'Roles' })).toBeNull();
	});
});
