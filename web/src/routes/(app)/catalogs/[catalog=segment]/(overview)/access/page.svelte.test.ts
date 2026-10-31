import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import type { EffectiveGroups, RoleGrant } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

const GROUPS: EffectiveGroups = {
	platform_admin: ['huron-platform-admins'],
	org_admin: ['helio-org-admins'],
	catalog_admin: ['helio-catalog-admins'],
	contributor: ['helio-contributors'],
	reader: ['geo-readers', 'helio-readers']
};

async function show(
	groups: EffectiveGroups | null,
	{ roles = [], mine = ['helio-readers'] }: { roles?: RoleGrant[]; mine?: string[] } = {}
) {
	render(Page, {
		props: {
			data: { ...catalogPageData({ roles, groups: mine }), groups },
			params: { catalog: 'heliophysics' },
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

describe('the catalog access tab', () => {
	it('shows the groups of every role with what the role can do', async () => {
		await show(GROUPS);
		const roles = within(screen.getByRole('list', { name: 'Roles' })).getAllByRole('heading');
		expect(roles.map((heading) => heading.textContent)).toEqual([
			'Platform administrator',
			'Organization administrator',
			'Catalog administrator',
			'Contributor',
			'Reader'
		]);
		expect(role('Reader')).toHaveTextContent(
			'Can browse namespaces, collections, files and activity.'
		);
		const readers = within(role('Reader')).getAllByRole('listitem');
		expect(readers.map((item) => item.textContent?.trim())).toEqual([
			'geo-readers',
			'helio-readers You'
		]);
		expect(role('Platform administrator')).toHaveTextContent('Inherited from the platform.');
		expect(role('Organization administrator')).toHaveTextContent(
			'Inherited from Heliophysics Division.'
		);
		expect(document.title).toBe('Access · Heliophysics · Huron');
	});

	it('marks every group the signed-in user belongs to', async () => {
		await show(GROUPS, { mine: ['helio-contributors', 'geo-readers'] });
		expect(screen.getAllByText('You')).toHaveLength(2);
		expect(within(role('Contributor')).getByText('You')).toBeInTheDocument();
		expect(within(role('Catalog administrator')).queryByText('You')).toBeNull();
	});

	it('says when a role has no groups', async () => {
		await show({ ...GROUPS, contributor: [] });
		expect(role('Contributor')).toHaveTextContent('No groups.');
	});

	it('shows catalog administrators and above how to grant a role', async () => {
		await show(GROUPS, { roles: [catalogRole('catalog_admin')] });
		const hint = screen.getByRole('region', {
			name: 'Grant a role, then apply the directory ACLs'
		});
		expect(within(hint).getByRole('textbox')).toHaveValue(
			[
				'huron --catalog heliophysics catalog grant heliophysics <role> <ldap-group>',
				'huron --catalog heliophysics acl apply heliophysics --recursive'
			].join('\n')
		);
		document.body.innerHTML = '';
		await show(GROUPS, {
			roles: [{ scope: 'organization', scope_id: organizationFixture().id, role: 'org_admin' }]
		});
		expect(screen.getByRole('region', { name: /Grant a role/ })).toBeInTheDocument();
	});

	it('shows contributors and readers no hint', async () => {
		await show(GROUPS, { roles: [catalogRole('contributor')] });
		expect(screen.queryByRole('region', { name: /Grant a role/ })).toBeNull();
	});

	it("says so when the API refuses the catalog's groups", async () => {
		await show(null);
		expect(screen.getByText("You don't have permission to see this.")).toBeInTheDocument();
		expect(screen.queryByRole('list', { name: 'Roles' })).toBeNull();
	});
});
