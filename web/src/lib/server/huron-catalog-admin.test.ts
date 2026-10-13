import { describe, expect, it } from 'vitest';
import type { HuronUser, PolarisCatalog, PolarisGrant, PolarisRole } from '$api/types';
import { object, PolarisClient } from './polaris-client';
import {
	catalogMembers,
	CATALOG_MEMBERSHIP_ROLES,
	createHuronCatalog,
	deleteHuronCatalog,
	ensureCatalogRoles,
	setCatalogMembership
} from './huron-catalog-admin';

const admin: HuronUser = {
	id: 'admin',
	username: 'admin',
	displayName: 'Administrator',
	isAdmin: true,
	disabled: false,
	polarisPrincipal: 'root',
	polarisPrincipalRole: 'service_admin',
	createdAt: '2026-10-12'
};
const alice: HuronUser = {
	...admin,
	id: 'alice',
	username: 'alice',
	displayName: 'Alice',
	isAdmin: false,
	polarisPrincipal: 'huron_alice',
	polarisPrincipalRole: 'huron_user_alice'
};
const bob: HuronUser = {
	...alice,
	id: 'bob',
	username: 'bob',
	displayName: 'Bob',
	polarisPrincipal: 'huron_bob',
	polarisPrincipalRole: 'huron_user_bob'
};

function upstream() {
	const roles = new Map<string, PolarisRole>();
	const grants = new Map<string, PolarisGrant[]>();
	const assigned = new Map<string, Set<string>>();
	const mutations: string[] = [];
	let denied = false;
	let interruptAssignment = false;
	let catalog: PolarisCatalog | null = null;
	let children: string[][] = [];
	const client = new PolarisClient(
		{
			url: 'http://polaris.test',
			realm: 'POLARIS',
			clientId: 'caller',
			clientSecret: 'server-secret'
		},
		async (input, options) => {
			const url = new URL(String(input));
			if (url.pathname.endsWith('/oauth/tokens')) return Response.json({ access_token: 'token' });
			const path = url.pathname.replace('/api/management/v1/', '');
			const method = options?.method ?? 'GET';
			const body: unknown = options?.body ? JSON.parse(String(options.body)) : {};
			if (denied) return new Response(null, { status: 403 });
			if (url.pathname === '/api/catalog/v1/science/namespaces')
				return Response.json({ namespaces: children });
			if (method !== 'GET') mutations.push(`${method} ${path}`);
			if (path === 'catalogs' && method === 'POST') {
				if (catalog) return new Response(null, { status: 409 });
				const entry = object(object(body).catalog);
				const storage = object(entry.storageConfigInfo);
				if (typeof entry.name !== 'string' || storage.storageType !== 'FILE')
					throw new Error('Invalid test catalog');
				catalog = {
					name: entry.name,
					type: 'INTERNAL',
					properties: Object.fromEntries(
						Object.entries(object(entry.properties)).map(([key, value]) => [key, String(value)])
					),
					storageConfigInfo: { storageType: 'FILE', allowedLocations: ['file:///space/'] }
				};
				return new Response(null, { status: 201 });
			}
			if (path === 'catalogs/science' && method === 'DELETE') {
				catalog = null;
				return new Response(null, { status: 204 });
			}
			const deletedRole = path.match(/^catalogs\/science\/catalog-roles\/([^/]+)$/);
			if (deletedRole && method === 'DELETE') {
				roles.delete(deletedRole[1]);
				return new Response(null, { status: 204 });
			}
			if (path === 'catalogs/science' && method === 'GET')
				return catalog ? Response.json(catalog) : new Response(null, { status: 404 });
			if (path === 'catalogs/science/catalog-roles') {
				if (method === 'GET') return Response.json({ roles: [...roles.values()] });
				const entry = object(object(body).catalogRole);
				if (typeof entry.name !== 'string') throw new Error('Invalid role');
				if (roles.has(entry.name)) return new Response(null, { status: 409 });
				roles.set(entry.name, {
					name: entry.name,
					properties: {
						'huron.managed-role': String(object(entry.properties)['huron.managed-role'])
					}
				});
				return new Response(null, { status: 201 });
			}
			const roleMatch = path.match(
				/^catalogs\/science\/catalog-roles\/([^/]+)\/(grants|principal-roles)$/
			);
			if (roleMatch) {
				const name = roleMatch[1];
				if (roleMatch[2] === 'principal-roles')
					return Response.json({
						roles: [...(assigned.get(name) ?? [])].map((name) => ({ name, properties: {} }))
					});
				if (method === 'GET') return Response.json({ grants: grants.get(name) ?? [] });
				const entry = object(object(body).grant);
				if (typeof entry.privilege !== 'string' || entry.type !== 'catalog')
					throw new Error('Invalid grant');
				const existing = grants.get(name) ?? [];
				grants.set(
					name,
					method === 'PUT'
						? [
								...existing.filter((grant) => grant.privilege !== entry.privilege),
								{ type: entry.type, privilege: entry.privilege }
							]
						: existing.filter((grant) => grant.privilege !== entry.privilege)
				);
				return new Response(null, { status: 204 });
			}
			const assignment = path.match(
				/^principal-roles\/([^/]+)\/catalog-roles\/science(?:\/([^/]+))?$/
			);
			if (assignment) {
				if (method === 'PUT') {
					if (interruptAssignment) {
						interruptAssignment = false;
						return new Response(null, { status: 503 });
					}
					const roleName = object(object(body).catalogRole).name;
					if (typeof roleName !== 'string') throw new Error('Invalid assignment');
					const current = assigned.get(roleName) ?? new Set<string>();
					current.add(assignment[1]);
					assigned.set(roleName, current);
				} else if (method === 'DELETE') assigned.get(assignment[2])?.delete(assignment[1]);
				return new Response(null, { status: 204 });
			}
			throw new Error(`Unexpected upstream request ${method} ${path}`);
		}
	);
	return {
		client,
		roles,
		grants,
		assigned,
		mutations,
		deny: () => {
			denied = true;
		},
		interrupt: () => {
			interruptAssignment = true;
		},
		nonempty: () => {
			children = [['science']];
		}
	};
}

describe('Huron catalog membership in Polaris', () => {
	it('grants exact reader privileges and reads membership from Polaris rather than local state', async () => {
		const api = upstream();
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'reader');
		expect(
			api.grants
				.get('huron_reader')
				?.map((grant) => grant.privilege)
				.sort()
		).toEqual([...CATALOG_MEMBERSHIP_ROLES.reader.privileges].sort());
		expect((await catalogMembers(api.client, 'science', [alice]))[0].roles).toEqual(['reader']);
		api.assigned.get('huron_reader')?.clear();
		expect((await catalogMembers(api.client, 'science', [alice]))[0].roles).toEqual([]);
	});

	it('downgrades and removes only managed roles in the selected catalog', async () => {
		const api = upstream();
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'writer');
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'reader');
		expect(api.assigned.get('huron_writer')?.has(alice.polarisPrincipalRole)).toBe(false);
		expect(api.assigned.get('huron_reader')?.has(alice.polarisPrincipalRole)).toBe(true);
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'none');
		expect((await catalogMembers(api.client, 'science', [alice]))[0].roles).toEqual([]);
	});

	it('retries an interrupted downgrade without retaining writer authority', async () => {
		const api = upstream();
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'writer');
		api.interrupt();
		await expect(
			setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'reader')
		).rejects.toThrow('Refresh, then retry');
		expect(api.assigned.get('huron_writer')?.has(alice.polarisPrincipalRole)).toBe(false);
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'reader');
		await setCatalogMembership(api.client, [admin, alice], 'science', alice.id, 'reader');
		expect((await catalogMembers(api.client, 'science', [alice]))[0].roles).toEqual(['reader']);
	});

	it('requires upstream catalog authority before exposing user decisions or mutating grants', async () => {
		const api = upstream();
		api.deny();
		await expect(
			setCatalogMembership(api.client, [admin, alice], 'science', admin.id, 'none')
		).rejects.toMatchObject({ status: 404 });
		expect(api.mutations).toEqual([]);
	});

	it('preserves the default administrator and the last active catalog administrator', async () => {
		const api = upstream();
		await setCatalogMembership(api.client, [alice, bob], 'science', alice.id, 'admin');
		await expect(
			setCatalogMembership(api.client, [alice, bob], 'science', alice.id, 'reader')
		).rejects.toThrow('at least one active catalog administrator');
		await setCatalogMembership(api.client, [alice, bob], 'science', bob.id, 'admin');
		await setCatalogMembership(api.client, [alice, bob], 'science', alice.id, 'reader');
		await expect(
			setCatalogMembership(api.client, [admin], 'science', admin.id, 'none')
		).rejects.toThrow('default Huron administrator');
	});

	it('refuses collisions with unmanaged role names and prevents privilege drift in presets', async () => {
		const api = upstream();
		api.roles.set('huron_reader', { name: 'huron_reader', properties: {} });
		await expect(ensureCatalogRoles(api.client, 'science')).rejects.toThrow('managed-role marker');
		api.roles.set('huron_reader', {
			name: 'huron_reader',
			properties: { 'huron.managed-role': 'reader' }
		});
		api.grants.set('huron_reader', [{ type: 'catalog', privilege: 'CATALOG_MANAGE_ACCESS' }]);
		await ensureCatalogRoles(api.client, 'science');
		expect(
			api.grants.get('huron_reader')?.some((grant) => grant.privilege === 'CATALOG_MANAGE_ACCESS')
		).toBe(false);
	});

	it('serializes concurrent local removals so one active administrator remains', async () => {
		const api = upstream();
		await setCatalogMembership(api.client, [alice, bob], 'science', alice.id, 'admin');
		await setCatalogMembership(api.client, [alice, bob], 'science', bob.id, 'admin');
		const results = await Promise.allSettled([
			setCatalogMembership(api.client, [alice, bob], 'science', alice.id, 'none'),
			setCatalogMembership(api.client, [alice, bob], 'science', bob.id, 'none')
		]);
		expect(results.filter((result) => result.status === 'fulfilled')).toHaveLength(1);
		expect(api.assigned.get('huron_catalog_admin')?.size).toBe(1);
	});

	it('resumes catalog creation with the same configuration and gives the administrator content access', async () => {
		const api = upstream();
		const form = new FormData();
		form.set('name', 'science');
		form.set('defaultBaseLocation', 'file:///space/science/');
		form.set(
			'storageConfigInfo',
			JSON.stringify({ storageType: 'FILE', allowedLocations: ['file:///space/'] })
		);
		api.interrupt();
		await expect(createHuronCatalog(api.client, admin, form)).rejects.toThrow(
			'Retry creation with exactly the same configuration'
		);
		expect(await createHuronCatalog(api.client, admin, form)).toMatchObject({ success: true });
		expect(api.grants.get('huron_catalog_admin')).toContainEqual({
			type: 'catalog',
			privilege: 'CATALOG_MANAGE_CONTENT'
		});
		expect(api.assigned.get('huron_catalog_admin')?.has(admin.polarisPrincipalRole)).toBe(true);
		form.set('defaultBaseLocation', 'file:///space/different/');
		await expect(createHuronCatalog(api.client, admin, form)).rejects.toThrow(
			'different configuration'
		);
	});

	it('denies creation to an ordinary Huron user before contacting Polaris', async () => {
		const api = upstream();
		await expect(createHuronCatalog(api.client, alice, new FormData())).rejects.toMatchObject({
			status: 403
		});
		expect(api.mutations).toEqual([]);
	});

	it('drops an empty catalog with its managed and custom roles while preserving the built-in role', async () => {
		const api = upstream();
		await ensureCatalogRoles(api.client, 'science');
		api.roles.set('custom', { name: 'custom', properties: {} });
		api.roles.set('catalog_admin', { name: 'catalog_admin', properties: {} });
		const form = new FormData();
		form.set('catalog', 'science');
		form.set('confirmation', 'science');
		expect(await deleteHuronCatalog(api.client, admin, form)).toMatchObject({ success: true });
		expect([...api.roles.keys()]).toEqual(['catalog_admin']);
		expect(api.mutations.at(-1)).toBe('DELETE catalogs/science');
	});

	it('does not remove catalog grants when a namespace remains or confirmation is incorrect', async () => {
		const api = upstream();
		const form = new FormData();
		form.set('catalog', 'science');
		await expect(deleteHuronCatalog(api.client, admin, form)).rejects.toThrow('confirm deletion');
		form.set('confirmation', 'science');
		api.nonempty();
		await expect(deleteHuronCatalog(api.client, admin, form)).rejects.toThrow(
			'repositories and namespaces'
		);
		expect(api.mutations).toEqual([]);
	});
});
