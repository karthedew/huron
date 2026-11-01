import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import type { RoleGrant } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { catalogPageData } from '$lib/testing/catalog-data';
import Page from './+page.svelte';
const organization = organizationFixture();
async function show(roles: RoleGrant[], declared = false) {
	render(Page, {
		props: {
			data: {
				...catalogPageData({ roles }),
				organizationDetails: { ...organization, declared },
				organizationPath: '/projects/huron/helio'
			},
			params: { org: 'helio' }
		}
	});
	await tick();
}
describe('organization CLI', () => {
	it.each([
		{ scope: 'organization', scope_id: organization.id, role: 'org_admin' },
		{ scope: 'platform', scope_id: null, role: 'platform_admin' }
	] satisfies RoleGrant[])(
		'gives $role catalog creation and grants for undeclared organizations',
		async (role) => {
			await show([role]);
			expect(
				within(
					screen.getByRole('region', { name: 'Create a catalog in this organization' })
				).getByRole('textbox')
			).toHaveValue('huron create catalog <name> --org helio');
			expect(
				within(screen.getByRole('region', { name: 'Grant a role on the organization' })).getByRole(
					'textbox'
				)
			).toHaveValue('huron adm grant <role> <ldap-group> --org helio');
		}
	);
	it('keeps declared groups in service configuration, while permitting catalog creation', async () => {
		await show([{ scope: 'organization', scope_id: organization.id, role: 'org_admin' }], true);
		expect(screen.queryByRole('region', { name: 'Grant a role on the organization' })).toBeNull();
		expect(
			screen.getByRole('region', { name: 'Create a catalog in this organization' })
		).toBeInTheDocument();
		expect(screen.getByText(/role groups are declared/)).toBeInTheDocument();
	});
	it('gives no mutation commands to readers or administrators of another organization', async () => {
		await show([{ scope: 'organization', scope_id: 'other', role: 'org_admin' }]);
		expect(screen.queryByRole('region', { name: /Create|Grant/ })).toBeNull();
		expect(screen.getByText(/Open a catalog or collection/)).toBeInTheDocument();
	});
});
