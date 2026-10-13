import { describe, expect, it, vi } from 'vitest';
import type { HuronUser, PolarisDatasetTarget, PolarisGrant } from '$api/types';
import { PolarisClient } from './polaris-client';
import {
	grantAppliesToDataset,
	loadDatasetGovernance,
	loadDatasetPermissions,
	loadDatasetPolicies
} from './polaris-dataset-governance';

const user: HuronUser = {
	id: 'alice',
	username: 'alice',
	displayName: 'Alice',
	isAdmin: false,
	disabled: false,
	polarisPrincipal: 'huron_alice',
	polarisPrincipalRole: 'huron_alice_role',
	createdAt: '2026-10-12'
};
const target: PolarisDatasetTarget = {
	catalog: 'science',
	namespace: ['ocean', 'monthly'],
	table: 'energy',
	format: 'icechunk'
};
const table = { name: 'energy', location: 's3://science/energy/', properties: {} };

function client(handler: (url: URL) => Response | Promise<Response>) {
	const calls: string[] = [];
	const fetcher = vi.fn<typeof fetch>(async (input) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens')) return Response.json({ access_token: 'token' });
		calls.push(url.pathname + url.search);
		return handler(url);
	});
	return {
		api: new PolarisClient(
			{
				url: 'http://polaris.test',
				realm: 'POLARIS',
				clientId: 'identity',
				clientSecret: 'secret'
			},
			fetcher
		),
		calls
	};
}

function directory(grants: PolarisGrant[]) {
	return client((url) => {
		if (url.pathname === '/api/management/v1/principals/huron_alice/principal-roles')
			return Response.json({ roles: [{ name: 'huron_alice_role', properties: {} }] });
		if (
			url.pathname === '/api/management/v1/principal-roles/huron_alice_role/catalog-roles/science'
		)
			return Response.json({ roles: [{ name: 'reader', properties: {} }] });
		if (url.pathname === '/api/management/v1/catalogs/science/catalog-roles/reader/grants')
			return Response.json({ grants });
		throw new Error('Unexpected trusted-directory operation.');
	});
}

describe('dataset-scoped Polaris access facts', () => {
	it('reads Raw permission facts through the caller’s generic-table endpoint and reports unsupported policies', async () => {
		const own = client(() => Response.json({ table: { name: 'energy', format: 'raw' } }));
		const facts = directory([{ type: 'catalog', privilege: 'TABLE_READ_DATA' }]);
		const data = await loadDatasetGovernance(
			own.api,
			user,
			{ ...target, format: 'raw' },
			async () => facts.api
		);
		expect(data.permissions.capabilities.readData).toBe(true);
		expect(own.calls).toHaveLength(2);
		expect(own.calls.every((path) => path.includes('/generic-tables/energy'))).toBe(true);
		expect(data.policies.supported).toBe(false);
		expect(data.policies.message).toContain('generic-table assets');
	});

	it('rechecks Raw discovery after permission lookup so revoked generic metadata is not disclosed', async () => {
		let reads = 0;
		const own = client(() =>
			++reads === 1
				? Response.json({ table: { name: 'energy', format: 'raw' } })
				: new Response(null, { status: 403 })
		);
		const facts = directory([{ type: 'catalog', privilege: 'TABLE_READ_DATA' }]);
		await expect(
			loadDatasetGovernance(own.api, user, { ...target, format: 'raw' }, async () => facts.api)
		).rejects.toMatchObject({ status: 404 });
	});

	it('matches exact namespace levels and table names while retaining inherited grants', () => {
		expect(grantAppliesToDataset({ type: 'catalog', privilege: 'TABLE_READ_DATA' }, target)).toBe(
			true
		);
		expect(
			grantAppliesToDataset(
				{ type: 'namespace', privilege: 'TABLE_READ_DATA', namespace: ['ocean'] },
				target
			)
		).toBe(true);
		expect(
			grantAppliesToDataset(
				{ type: 'namespace', privilege: 'TABLE_READ_DATA', namespace: ['oceans'] },
				target
			)
		).toBe(false);
		expect(
			grantAppliesToDataset(
				{ type: 'table', privilege: 'TABLE_READ_DATA', namespace: ['ocean'], tableName: 'energy' },
				target
			)
		).toBe(false);
		expect(
			grantAppliesToDataset(
				{
					type: 'table',
					privilege: 'TABLE_READ_DATA',
					namespace: target.namespace,
					tableName: 'other'
				},
				target
			)
		).toBe(false);
	});

	it('returns only the ordinary reader’s own applicable grant facts and never root data reads', async () => {
		const own = client(() => Response.json({ table }));
		const facts = directory([
			{ type: 'namespace', namespace: ['ocean'], privilege: 'TABLE_READ_DATA' },
			{
				type: 'table',
				namespace: target.namespace,
				tableName: 'energy',
				privilege: 'TABLE_READ_PROPERTIES'
			},
			{
				type: 'table',
				namespace: ['private'],
				tableName: 'secret_dataset',
				privilege: 'TABLE_WRITE_DATA'
			}
		]);
		const data = await loadDatasetGovernance(own.api, user, target, async () => facts.api);
		expect(data.permissions.visibility).toBe('self');
		expect(data.permissions.capabilities).toEqual({
			readMetadata: true,
			readData: true,
			writeData: false,
			manageAccess: false
		});
		expect(data.permissions.applicableGrants).toHaveLength(2);
		expect(data.permissions.applicableGrants[0].inherited).toBe(true);
		expect(data.permissions.applicableGrants[1].inherited).toBe(false);
		expect(JSON.stringify(data)).not.toContain('secret_dataset');
		expect(facts.calls.every((path) => path.startsWith('/api/management/v1/'))).toBe(true);
		expect(own.calls.every((path) => path.includes('/icechunk-tables/energy'))).toBe(true);
		expect(data.policies.supported).toBe(false);
	});

	it('requires the caller’s own discovery before consulting the trusted permission directory', async () => {
		const own = client(() => new Response(null, { status: 403 }));
		const facts = directory([]);
		const factory = vi.fn(async () => facts.api);
		await expect(loadDatasetPermissions(own.api, user, target, factory)).rejects.toMatchObject({
			status: 404
		});
		expect(factory).not.toHaveBeenCalled();
	});

	it('rechecks the caller’s own table read before disclosing facts after access is revoked', async () => {
		let read = 0;
		const own = client(() =>
			++read === 1 ? Response.json({ table }) : new Response(null, { status: 403 })
		);
		const facts = directory([{ type: 'catalog', privilege: 'TABLE_READ_DATA' }]);
		await expect(
			loadDatasetPermissions(own.api, user, target, async () => facts.api)
		).rejects.toMatchObject({ status: 404 });
	});

	it('allows managers to inspect applicable role grants through their own authorized client', async () => {
		const own = client((url) => {
			if (url.pathname.includes('/icechunk-tables/')) return Response.json({ table });
			if (url.pathname.endsWith('/catalog-roles'))
				return Response.json({
					roles: [
						{ name: 'reader', properties: {} },
						{ name: 'writer', properties: {} }
					]
				});
			if (url.pathname.endsWith('/grants'))
				return Response.json({
					grants: [
						{
							type: 'catalog',
							privilege: url.pathname.includes('/writer/')
								? 'TABLE_WRITE_DATA'
								: 'CATALOG_MANAGE_ACCESS'
						}
					]
				});
			if (url.pathname.endsWith('/principal-roles'))
				return Response.json({ roles: [{ name: 'actual_team_role', properties: {} }] });
			throw new Error('Unexpected own-client operation.');
		});
		const facts = directory([{ type: 'catalog', privilege: 'CATALOG_MANAGE_ACCESS' }]);
		const permissions = await loadDatasetPermissions(own.api, user, target, async () => facts.api);
		expect(permissions.visibility).toBe('catalog');
		expect(
			permissions.applicableGrants.some(
				(entry) =>
					entry.catalogRole === 'writer' && entry.principalRoles.includes('actual_team_role')
			)
		).toBe(true);
		// Inspecting a writer's grant must not grant that capability to the manager.
		expect(permissions.capabilities.writeData).toBe(false);
	});

	it('does not mistake a Huron administrator flag for a Polaris data grant', async () => {
		const own = client((url) =>
			url.pathname.includes('/icechunk-tables/')
				? Response.json({ table })
				: new Response(null, { status: 403 })
		);
		const permissions = await loadDatasetPermissions(
			own.api,
			{ ...user, isAdmin: true },
			target,
			async () => directory([]).api
		);
		expect(permissions.capabilities.readData).toBe(false);
		expect(permissions.capabilities.writeData).toBe(false);
	});
});

describe('native Polaris dataset policy capability', () => {
	it('makes unsupported Icechunk policy bindings explicit without issuing a fake query', async () => {
		const own = client(() => {
			throw new Error('No unsupported policy request is permitted.');
		});
		expect(await loadDatasetPolicies(own.api, target)).toMatchObject({
			supported: false,
			policies: [],
			error: null
		});
		expect(own.calls).toEqual([]);
	});

	it('loads actual Iceberg applicable policies and preserves backend inheritance and pagination', async () => {
		const own = client(() =>
			Response.json({
				'applicable-policies': [
					{
						name: 'compaction',
						namespace: ['management'],
						'policy-type': 'system.data-compaction',
						version: 3,
						inheritable: true,
						inherited: true,
						description: 'Nightly compaction',
						content: 'Not forwarded by the browser projection'
					}
				],
				'next-page-token': 'opaque-next'
			})
		);
		const policies = await loadDatasetPolicies(
			own.api,
			{ ...target, format: 'iceberg' },
			'opaque-current'
		);
		expect(policies).toMatchObject({
			supported: true,
			nextPageToken: 'opaque-next',
			policies: [{ name: 'compaction', inherited: true, policyType: 'system.data-compaction' }]
		});
		expect(own.calls[0]).toContain('namespace=ocean%1Fmonthly');
		expect(own.calls[0]).toContain('target-name=energy');
		expect(own.calls[0]).toContain('pageToken=opaque-current');
		expect(JSON.stringify(policies)).not.toContain('Not forwarded');
	});

	it('reports policy read failure without pretending the effective policy list is empty', async () => {
		const own = client(() => new Response(null, { status: 403 }));
		const policies = await loadDatasetPolicies(own.api, { ...target, format: 'iceberg' });
		expect(policies.error).toBe('Resource not found.');
		expect(policies.message).toContain('could not be read');
	});

	it('reports a disabled native policy service as a deployment capability limitation', async () => {
		const own = client(() => new Response(null, { status: 406 }));
		const policies = await loadDatasetPolicies(own.api, { ...target, format: 'iceberg' });
		expect(policies.supported).toBe(false);
		expect(policies.message).toContain('has not enabled');
		expect(policies.error).toContain('not enabled');
	});
});
