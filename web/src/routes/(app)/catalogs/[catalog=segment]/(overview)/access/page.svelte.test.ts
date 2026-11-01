import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import type { GrantSource, RoleGrant } from '$api/types';
import { catalogAccess, type RoleAccess } from '$lib/access';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

const SOURCES: GrantSource[] = [
	{ role: 'platform_admin', group: 'huron-platform-admins', scope: 'platform' },
	{ role: 'org_admin', group: 'helio-org-admins', scope: 'organization' },
	{ role: 'catalog_admin', group: 'helio-catalog-admins', scope: 'catalog' },
	{ role: 'contributor', group: 'helio-contributors', scope: 'organization' },
	{ role: 'reader', group: 'geo-readers', scope: 'catalog' },
	{ role: 'reader', group: 'helio-readers', scope: 'organization' },
	{ role: 'reader', group: 'helio-readers', scope: 'catalog' }
];
const ACCESS = catalogAccess(SOURCES);

async function show(
	access: RoleAccess[] | null,
	{ roles = [], mine = ['helio-readers'] }: { roles?: RoleGrant[]; mine?: string[] } = {}
) {
	render(Page, {
		props: {
			data: { ...catalogPageData({ roles, groups: mine }), access },
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
		await show(ACCESS);
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
			'helio-readers You',
			'geo-readers',
			'helio-readers You'
		]);
		expect(document.title).toBe('Access · Heliophysics · Huron');
	});

	it('says where each group was granted, linking the organization', async () => {
		await show(ACCESS);
		const inherited = within(role('Reader')).getByRole('list', {
			name: 'Inherited from Heliophysics Division'
		});
		expect(
			within(inherited)
				.getAllByRole('listitem')
				.map((item) => item.textContent?.trim())
		).toEqual(['helio-readers You']);
		const granted = within(role('Reader')).getByRole('list', { name: 'Granted on this catalog' });
		expect(
			within(granted)
				.getAllByRole('listitem')
				.map((item) => item.textContent?.trim())
		).toEqual(['geo-readers', 'helio-readers You']);
		expect(
			within(role('Reader')).getByRole('link', { name: 'Heliophysics Division' })
		).toHaveAttribute('href', '/orgs/helio/access');
		expect(
			within(role('Platform administrator')).getByRole('list', {
				name: 'Inherited from the platform'
			})
		).toHaveTextContent('huron-platform-admins');
		expect(
			within(role('Contributor')).getByRole('list', {
				name: 'Inherited from Heliophysics Division'
			})
		).toHaveTextContent('helio-contributors');
		expect(
			within(role('Catalog administrator')).getByRole('list', { name: 'Granted on this catalog' })
		).toHaveTextContent('helio-catalog-admins');
		expect(within(role('Catalog administrator')).queryByText(/Inherited/)).toBeNull();
	});

	it('names an organization it cannot see by its name', async () => {
		render(Page, {
			props: {
				data: { ...catalogPageData(), organizations: [], access: ACCESS },
				params: { catalog: 'heliophysics' },
				form: undefined
			}
		});
		await tick();
		expect(
			within(role('Reader')).getByRole('list', { name: 'Inherited from helio' })
		).toBeInTheDocument();
	});

	it('marks every group the signed-in user belongs to', async () => {
		await show(ACCESS, { mine: ['helio-contributors', 'geo-readers'] });
		expect(screen.getAllByText('You')).toHaveLength(2);
		expect(within(role('Contributor')).getByText('You')).toBeInTheDocument();
		expect(within(role('Catalog administrator')).queryByText('You')).toBeNull();
	});

	it('says when a role has no groups', async () => {
		await show(catalogAccess(SOURCES.filter(({ role }) => role !== 'contributor')));
		expect(role('Contributor')).toHaveTextContent('No groups.');
	});

	it('shows catalog administrators and above how to grant a role', async () => {
		await show(ACCESS, { roles: [catalogRole('catalog_admin')] });
		const hint = screen.getByRole('region', {
			name: 'Grant a role, then apply the directory ACLs'
		});
		expect(within(hint).getByRole('textbox')).toHaveValue(
			[
				'huron --catalog heliophysics adm grant <role> <ldap-group>',
				'huron --catalog heliophysics adm apply-acl heliophysics --recursive'
			].join('\n')
		);
		document.body.innerHTML = '';
		await show(ACCESS, {
			roles: [{ scope: 'organization', scope_id: organizationFixture().id, role: 'org_admin' }]
		});
		expect(screen.getByRole('region', { name: /Grant a role/ })).toBeInTheDocument();
	});

	it('shows contributors and readers no hint', async () => {
		await show(ACCESS, { roles: [catalogRole('contributor')] });
		expect(screen.queryByRole('region', { name: /Grant a role/ })).toBeNull();
	});

	it("says so when the API refuses the catalog's groups", async () => {
		await show(null);
		expect(screen.getByText("You don't have permission to see this.")).toBeInTheDocument();
		expect(screen.queryByRole('list', { name: 'Roles' })).toBeNull();
	});
});
