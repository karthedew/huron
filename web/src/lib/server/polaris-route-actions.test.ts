// @vitest-environment node
import type { Cookies } from '@sveltejs/kit';
import type { HuronUser } from '$api/types';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PolarisActionName } from './polaris-actions';
import { PolarisApiError, PolarisClient } from './polaris-client';
import { createPolarisActions, guardManagedEntities } from './polaris-route-actions';
import { requireOrganizationCatalog } from './huron-organizations';

const mocks = vi.hoisted(() => ({ listUsers: vi.fn() }));
vi.mock('./huron-accounts', () => ({ accountStore: () => ({ listUsers: mocks.listUsers }) }));
vi.mock('./huron-organizations', () => ({ requireOrganizationCatalog: vi.fn() }));

const admin: HuronUser = {
	id: 'admin',
	username: 'admin',
	displayName: 'Administrator',
	isAdmin: true,
	disabled: false,
	polarisPrincipal: 'root',
	polarisPrincipalRole: 'service_admin',
	createdAt: '2026-10-12T00:00:00Z'
};
const scientist: HuronUser = {
	...admin,
	id: 'alice',
	username: 'alice',
	displayName: 'Alice',
	isAdmin: false,
	polarisPrincipal: 'huron-user-alice',
	polarisPrincipalRole: 'huron-member-alice'
};
const users = [admin, scientist];

function form(values: Record<string, string>): FormData {
	const data = new FormData();
	for (const [key, value] of Object.entries(values)) data.set(key, value);
	return data;
}

function event(values: Record<string, string>, user = admin) {
	const cookies: Cookies = {
		get: () => undefined,
		getAll: () => [],
		set: () => undefined,
		delete: () => undefined,
		serialize: () => ''
	};
	const fetcher = vi.fn<typeof fetch>(async (input) =>
		String(input).endsWith('/oauth/tokens')
			? Response.json({ access_token: 'private-server-token', expires_in: 3600 })
			: new Response(null, { status: 201 })
	);
	const client = new PolarisClient(
		{
			url: 'http://localhost:8181',
			realm: 'POLARIS',
			clientId: 'admin-client',
			clientSecret: 'admin-secret'
		},
		fetcher
	);
	return {
		fetcher,
		value: {
			locals: { user, polaris: client },
			cookies,
			url: new URL('http://localhost/admin'),
			setHeaders: vi.fn<(headers: Record<string, string>) => void>(),
			request: new Request('http://localhost/admin', { method: 'POST', body: form(values) })
		}
	};
}

afterEach(() => vi.clearAllMocks());

describe('advanced Polaris forms protect Huron managed identities', () => {
	it.each([
		'createPrincipal',
		'updatePrincipal',
		'deletePrincipal',
		'rotatePrincipal',
		'resetPrincipal'
	] satisfies PolarisActionName[])(
		'blocks %s for both bootstrap and scientist identities',
		(action) => {
			for (const name of ['root', scientist.polarisPrincipal])
				expect(() => guardManagedEntities(action, form({ name }), users)).toThrow(
					'identities are protected'
				);
		}
	);

	it.each([
		'createPrincipalRole',
		'updatePrincipalRole',
		'deletePrincipalRole'
	] satisfies PolarisActionName[])(
		'blocks %s for bootstrap and personal principal roles',
		(action) => {
			for (const name of ['service_admin', scientist.polarisPrincipalRole])
				expect(() => guardManagedEntities(action, form({ name }), users)).toThrow(
					'principal roles are protected'
				);
		}
	);

	it.each(['assignPrincipalRole', 'revokePrincipalRole'] satisfies PolarisActionName[])(
		'blocks %s when either principal or principal role belongs to Huron',
		(action) => {
			for (const values of [
				{ principal: scientist.polarisPrincipal, principalRole: 'external-role' },
				{ principal: 'external-user', principalRole: scientist.polarisPrincipalRole },
				{ principal: 'root', principalRole: 'external-role' },
				{ principal: 'external-user', principalRole: 'service_admin' }
			])
				expect(() => guardManagedEntities(action, form(values), users)).toThrow(
					'memberships are protected'
				);
		}
	);

	it.each([
		'createCatalogRole',
		'updateCatalogRole',
		'deleteCatalogRole',
		'addGrant',
		'revokeGrant',
		'assignCatalogRole',
		'revokeCatalogRole'
	] satisfies PolarisActionName[])(
		'blocks %s for every fixed catalog membership role',
		(action) => {
			for (const name of ['huron_reader', 'huron_writer', 'huron_catalog_admin'])
				expect(() =>
					guardManagedEntities(action, form({ name, catalogRole: name }), users)
				).toThrow('roles and grants are fixed');
		}
	);

	it('retains external principals and custom roles as valid advanced operations', () => {
		for (const action of [
			'updatePrincipal',
			'rotatePrincipal',
			'deletePrincipalRole',
			'assignPrincipalRole',
			'updateCatalogRole',
			'addGrant',
			'assignCatalogRole'
		] satisfies PolarisActionName[])
			expect(() =>
				guardManagedEntities(
					action,
					form({
						name: 'external-custom',
						principal: 'external-user',
						principalRole: 'external-role',
						catalogRole: 'custom-reader'
					}),
					users
				)
			).not.toThrow();
	});

	it('rejects a forged managed-role grant before any upstream mutation', async () => {
		const { value, fetcher } = event({
			catalog: 'research',
			catalogRole: 'huron_reader',
			type: 'catalog',
			privilege: 'CATALOG_MANAGE_ACCESS'
		});
		const result = await createPolarisActions({
			path: '/admin',
			allowedActions: ['addGrant']
		}).addGrant(value);
		expect(result).toMatchObject({
			status: 400,
			data: { success: false, message: expect.stringContaining('fixed') }
		});
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('checks persisted Huron account identity before principal credential rotation', async () => {
		mocks.listUsers.mockResolvedValue(users);
		const { value, fetcher } = event({ name: scientist.polarisPrincipal, properties: '{}' });
		const result = await createPolarisActions({
			path: '/admin',
			allowedActions: ['rotatePrincipal']
		}).rotatePrincipal(value);
		expect(result).toMatchObject({
			status: 400,
			data: { success: false, message: expect.stringContaining('protected') }
		});
		expect(mocks.listUsers).toHaveBeenCalledOnce();
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('rejects ordinary users at the shared global-administration guard', async () => {
		const { value, fetcher } = event({ name: 'external-user', properties: '{}' }, scientist);
		await expect(
			createPolarisActions({ path: '/admin', allowedActions: ['createPrincipal'] }).createPrincipal(
				value
			)
		).rejects.toMatchObject({ status: 403 });
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('executes valid custom catalog roles under the authenticated user’s principal', async () => {
		const { value, fetcher } = event(
			{ catalog: 'research', name: 'custom-reader', properties: '{}' },
			scientist
		);
		const result = await createPolarisActions({
			path: '/settings/catalog',
			allowedActions: ['createCatalogRole']
		}).createCatalogRole(value);
		expect(result).toMatchObject({ success: true });
		expect(requireOrganizationCatalog).toHaveBeenCalledWith(
			scientist,
			value.locals.polaris,
			'research'
		);
		expect(
			fetcher.mock.calls.some(([url]) => String(url).endsWith('/catalogs/research/catalog-roles'))
		).toBe(true);
	});

	it('conceals catalog mutations denied by organization membership before any upstream request', async () => {
		vi.mocked(requireOrganizationCatalog).mockRejectedValueOnce(new PolarisApiError(404));
		const { value, fetcher } = event(
			{ catalog: 'other-organization', namespace: '["bronze"]', properties: '{}' },
			scientist
		);
		const result = await createPolarisActions({
			path: '/browse',
			allowedActions: ['createNamespace']
		}).createNamespace(value);
		expect(result).toMatchObject({ status: 404, data: { success: false, status: 404 } });
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('allows global administrators to configure catalogs before organization assignment', async () => {
		const { value, fetcher } = event({
			catalog: 'new-unassigned',
			name: 'custom-role',
			properties: '{}'
		});
		const result = await createPolarisActions({
			path: '/admin',
			allowedActions: ['createCatalogRole'],
			adminOnly: true
		}).createCatalogRole(value);
		expect(result).toMatchObject({ success: true });
		expect(requireOrganizationCatalog).not.toHaveBeenCalled();
		expect(fetcher).toHaveBeenCalled();
	});

	it('requires Huron administrator authority for every action on the admin route', async () => {
		const { value, fetcher } = event(
			{ catalog: 'research', name: 'custom-role', properties: '{}' },
			scientist
		);
		await expect(
			createPolarisActions({
				path: '/admin',
				allowedActions: ['createCatalogRole'],
				adminOnly: true
			}).createCatalogRole(value)
		).rejects.toMatchObject({ status: 403 });
		expect(fetcher).not.toHaveBeenCalled();
	});
});
