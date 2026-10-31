import { describe, expect, it } from 'vitest';
import type { RoleGrant } from '$api/types';
import { capabilities } from './capabilities';

const CATALOG = 'catalog-1';
const ORGANIZATION = 'organization-1';
const NONE = {
	contribute: false,
	administerCatalog: false,
	administerOrganization: false,
	platformAdmin: false
};

const grant = (role: string, scope: string, scopeId: string | null): RoleGrant => ({
	role,
	scope,
	scope_id: scopeId
});

describe('capabilities', () => {
	it('grants nothing without roles', () => {
		expect(capabilities([], { catalogId: CATALOG, organizationId: ORGANIZATION })).toEqual(NONE);
	});

	it('grants everything to a platform admin, anywhere', () => {
		expect(capabilities([grant('platform_admin', 'platform', null)])).toEqual({
			contribute: true,
			administerCatalog: true,
			administerOrganization: true,
			platformAdmin: true
		});
	});

	it('lets an org admin administer the catalogs of that organization only', () => {
		const roles = [grant('org_admin', 'organization', ORGANIZATION)];
		expect(capabilities(roles, { catalogId: CATALOG, organizationId: ORGANIZATION })).toEqual({
			contribute: true,
			administerCatalog: true,
			administerOrganization: true,
			platformAdmin: false
		});
		expect(capabilities(roles, { catalogId: CATALOG, organizationId: 'other' })).toEqual(NONE);
		expect(capabilities(roles, { catalogId: CATALOG })).toEqual(NONE);
	});

	it('lets a catalog admin administer and contribute to that catalog', () => {
		const roles = [grant('catalog_admin', 'catalog', CATALOG)];
		expect(capabilities(roles, { catalogId: CATALOG, organizationId: ORGANIZATION })).toEqual({
			...NONE,
			contribute: true,
			administerCatalog: true
		});
		expect(capabilities(roles, { catalogId: 'other' })).toEqual(NONE);
	});

	it('lets a contributor contribute to that catalog only', () => {
		const roles = [grant('contributor', 'catalog', CATALOG)];
		expect(capabilities(roles, { catalogId: CATALOG })).toEqual({ ...NONE, contribute: true });
		expect(capabilities(roles, { catalogId: 'other' })).toEqual(NONE);
	});

	it('grants nothing for reading or for roles at the wrong scope', () => {
		const roles = [
			grant('reader', 'catalog', CATALOG),
			grant('contributor', 'organization', ORGANIZATION),
			grant('org_admin', 'catalog', CATALOG),
			grant('platform_admin', 'organization', ORGANIZATION)
		];
		expect(capabilities(roles, { catalogId: CATALOG, organizationId: ORGANIZATION })).toEqual(NONE);
	});
});
