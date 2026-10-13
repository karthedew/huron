import { describe, expect, it, vi } from 'vitest';
import type { HuronUser, PolarisGrant } from '$api/types';
import { PolarisApiError, PolarisClient } from './polaris-client';
import { parseRawTarget, rawGrantPermissions, requireRawPermissions } from './raw-authorization';

const user: HuronUser = {
	id: 'alice',
	username: 'alice',
	displayName: 'Alice',
	isAdmin: false,
	disabled: false,
	polarisPrincipal: 'alice-principal',
	polarisPrincipalRole: 'alice-role',
	createdAt: '2026-10-13'
};
const target = { catalog: 'science', namespace: ['earth', 'daily'], name: 'rain' };

function fixture(initialGrants: PolarisGrant[]) {
	let grants = initialGrants;
	let disabled = false;
	let failing = false;
	const calls: string[] = [];
	const client = new PolarisClient(
		{ url: 'http://polaris.test', realm: 'POLARIS', clientId: 'alice', clientSecret: 'secret' },
		async (input) => {
			const path = new URL(String(input)).pathname;
			if (path.endsWith('/oauth/tokens')) return Response.json({ access_token: 'token' });
			calls.push(path);
			if (path.includes('/namespaces/')) return Response.json({ properties: {} });
			if (failing) return new Response(null, { status: 503 });
			if (path.endsWith('/principals/alice-principal/principal-roles'))
				return Response.json({ roles: [{ name: 'alice-role', properties: {} }] });
			if (path.endsWith('/principal-roles/alice-role/catalog-roles/science'))
				return Response.json({ roles: [{ name: 'data-writer', properties: {} }] });
			if (path.endsWith('/catalogs/science/catalog-roles/data-writer/grants'))
				return Response.json({ grants });
			throw new Error(`Unexpected directory access: ${path}`);
		}
	);
	const authority = {
		mode: () => 'rbac',
		users: async () => [{ ...user, disabled }],
		organization: vi.fn(async () => ({
			id: 'org',
			slug: 'org',
			name: 'Organization',
			description: '',
			createdAt: '',
			role: 'member' as const,
			catalogNames: ['science']
		})),
		directory: async () => client
	};
	return {
		client,
		authority,
		calls,
		setGrants: (value: PolarisGrant[]) => {
			grants = value;
		},
		disable: () => {
			disabled = true;
		},
		fail: () => {
			failing = true;
		}
	};
}

describe('Raw data authority', () => {
	it('honors exact target and ancestor namespace data grants without metadata escalation', () => {
		expect(
			rawGrantPermissions([{ type: 'catalog', privilege: 'CATALOG_MANAGE_METADATA' }], target)
		).toEqual({ read: false, write: false, create: true });
		expect(
			rawGrantPermissions(
				[{ type: 'namespace', namespace: ['earth'], privilege: 'TABLE_WRITE_DATA' }],
				target
			)
		).toEqual({ read: true, write: true, create: false });
		expect(
			rawGrantPermissions(
				[{ type: 'namespace', namespace: ['earthly'], privilege: 'CATALOG_MANAGE_CONTENT' }],
				target
			)
		).toEqual({ read: false, write: false, create: false });
		expect(
			rawGrantPermissions(
				[
					{
						type: 'table',
						namespace: target.namespace,
						tableName: target.name,
						privilege: 'TABLE_FULL_METADATA'
					}
				],
				target
			)
		).toEqual({ read: false, write: false, create: false });
		expect(
			rawGrantPermissions(
				[
					{
						type: 'table',
						namespace: ['earth'],
						tableName: target.name,
						privilege: 'TABLE_WRITE_DATA'
					}
				],
				target
			).write
		).toBe(false);
		expect(
			rawGrantPermissions(
				[
					{
						type: 'table',
						namespace: target.namespace,
						tableName: 'other',
						privilege: 'TABLE_READ_DATA'
					}
				],
				target
			).read
		).toBe(false);
		expect(rawGrantPermissions([{ type: 'catalog', privilege: 'UNKNOWN_ADMIN' }], target)).toEqual({
			read: false,
			write: false,
			create: false
		});
	});

	it('re-reads own assignments and rejects a revoked writer even after earlier authorization', async () => {
		const setup = fixture([{ type: 'catalog', privilege: 'TABLE_WRITE_DATA' }]);
		expect(
			(await requireRawPermissions(setup.client, user, target, 'write', setup.authority)).write
		).toBe(true);
		setup.setGrants([{ type: 'catalog', privilege: 'TABLE_READ_PROPERTIES' }]);
		await expect(
			requireRawPermissions(
				setup.client,
				{ ...user, isAdmin: true },
				target,
				'write',
				setup.authority
			)
		).rejects.toMatchObject({ status: 403 });
		expect(setup.calls.filter((path) => path.endsWith('/grants'))).toHaveLength(2);
		expect(setup.calls.filter((path) => path.includes('generic-tables'))).toHaveLength(2);
	});

	it('denies disabled users, cross-organization targets and unavailable authority facts', async () => {
		const setup = fixture([{ type: 'catalog', privilege: 'CATALOG_MANAGE_CONTENT' }]);
		setup.disable();
		await expect(
			requireRawPermissions(setup.client, user, target, 'write', setup.authority)
		).rejects.toMatchObject({ status: 401 });
		expect(setup.authority.organization).not.toHaveBeenCalled();
		const other = fixture([{ type: 'catalog', privilege: 'CATALOG_MANAGE_CONTENT' }]);
		other.authority.organization.mockRejectedValueOnce(new PolarisApiError(404));
		await expect(
			requireRawPermissions(other.client, user, target, 'write', other.authority)
		).rejects.toMatchObject({ status: 404 });
		expect(other.calls).toHaveLength(0);
		other.fail();
		await expect(
			requireRawPermissions(other.client, user, target, 'write', other.authority)
		).rejects.toMatchObject({ status: 503 });
	});

	it('refuses an unrecognized authorization implementation and malformed target components', async () => {
		const setup = fixture([{ type: 'catalog', privilege: 'CATALOG_MANAGE_CONTENT' }]);
		await expect(
			requireRawPermissions(setup.client, user, target, 'write', {
				...setup.authority,
				mode: () => 'opa'
			})
		).rejects.toMatchObject({ status: 503 });
		expect(() => parseRawTarget({ ...target, namespace: ['earth\x1fdaily'] })).toThrow();
		expect(() => parseRawTarget({ ...target, name: '../other' })).toThrow();
		expect(parseRawTarget(target)).toEqual(target);
	});

	it('admits an exact table data grant without demanding parent namespace metadata rights', async () => {
		const setup = fixture([
			{
				type: 'table',
				namespace: target.namespace,
				tableName: target.name,
				privilege: 'TABLE_READ_DATA'
			}
		]);
		const namespaceRead = vi
			.spyOn(setup.client, 'namespaceProperties')
			.mockRejectedValue(new PolarisApiError(403));
		expect(
			(await requireRawPermissions(setup.client, user, target, 'read', setup.authority)).read
		).toBe(true);
		expect(namespaceRead).not.toHaveBeenCalled();
		setup.setGrants([
			{
				type: 'table',
				namespace: target.namespace,
				tableName: target.name,
				privilege: 'TABLE_READ_PROPERTIES'
			}
		]);
		await expect(
			requireRawPermissions(setup.client, user, target, 'read', setup.authority)
		).rejects.toMatchObject({ status: 403 });
	});
});
