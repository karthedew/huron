import { afterEach, describe, expect, it, vi } from 'vitest';
import { executePolarisAction, type PolarisActionName } from './polaris-actions';
import { credentialSummary, PolarisClient } from './polaris-client';
import { formProperties, namespace, required, version } from './polaris-forms';
import { loadPolarisWorkspace } from './polaris-workspace';

const connection = {
	url: 'http://127.0.0.1:8181',
	realm: 'POLARIS',
	clientId: 'scientist',
	clientSecret: 'principal-secret'
};
const settings = { url: connection.url, realm: connection.realm };
const loaded = {
	name: 'measurements',
	location: 's3://science/repo/',
	properties: { owner: 'science' }
};

function form(values: Record<string, string> = {}): FormData {
	const result = new FormData();
	for (const [key, value] of Object.entries({
		catalog: 'science',
		namespace: '["one","two"]',
		name: 'measurements',
		properties: '{}',
		...values
	}))
		result.set(key, value);
	return result;
}

function mockClient(handler: (url: URL, init: RequestInit) => Response | Promise<Response>) {
	const fetcher = vi.fn<typeof fetch>(async (input, init) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens'))
			return Response.json({ access_token: 'oauth-secret', expires_in: 3600 });
		return handler(url, init ?? {});
	});
	return { client: new PolarisClient(connection, fetcher), fetcher };
}

afterEach(() => {
	vi.useRealTimers();
});

describe('Polaris protocol and credential projections', () => {
	it('shares OAuth refresh for simultaneous requests and forwards realm and bearer headers', async () => {
		const { client, fetcher } = mockClient((url, init) => {
			expect(new Headers(init.headers).get('Authorization')).toBe('Bearer oauth-secret');
			expect(new Headers(init.headers).get('Polaris-Realm')).toBe('POLARIS');
			return Response.json(
				url.pathname.endsWith('/principals') ? { principals: [] } : { roles: [] }
			);
		});
		await Promise.all([client.principals(), client.principalRoles()]);
		expect(
			fetcher.mock.calls.filter(([url]) => String(url).includes('/oauth/tokens'))
		).toHaveLength(1);
		const oauth = fetcher.mock.calls[0][1];
		expect(String(oauth?.body)).toContain('scope=PRINCIPAL_ROLE%3AALL');
		expect(oauth?.redirect).toBe('error');
	});

	it('exchanges an expired token and retries an upstream unauthorized response once', async () => {
		vi.useFakeTimers();
		let reads = 0;
		const { client, fetcher } = mockClient(() =>
			++reads === 1 ? Response.json({}, { status: 401 }) : Response.json({ principals: [] })
		);
		await client.principals();
		expect(
			fetcher.mock.calls.filter(([url]) => String(url).includes('/oauth/tokens'))
		).toHaveLength(2);
		vi.advanceTimersByTime(3600 * 1000);
		await client.principals();
		expect(
			fetcher.mock.calls.filter(([url]) => String(url).includes('/oauth/tokens'))
		).toHaveLength(3);
	});

	it('uses exact spec query names and encoded multipart namespaces for both list endpoints', async () => {
		const { client } = mockClient((url) => {
			expect(url.searchParams.get('pageSize')).toBe('100');
			expect(url.searchParams.get('pageToken')).toBe('next/token');
			expect(url.searchParams.has('page-size')).toBe(false);
			if (url.pathname.endsWith('/namespaces')) {
				expect(url.searchParams.get('parent')).toBe('one\x1ftwo');
				return Response.json({ namespaces: [['one', 'two', 'child']], 'next-page-token': 'third' });
			}
			expect(url.pathname).toContain('/one%1Ftwo/icechunk-tables');
			return Response.json({
				identifiers: [{ namespace: ['one', 'two'], name: 'measurements' }],
				'next-page-token': 'third'
			});
		});
		expect(await client.namespaces('science', ['one', 'two'], 'next/token')).toEqual({
			namespaces: [['one', 'two', 'child']],
			nextPageToken: 'third'
		});
		expect((await client.tables('science', ['one', 'two'], 'next/token')).nextPageToken).toBe(
			'third'
		);
	});

	it('renders discovery refusals as missing and retains action permission denials without upstream messages', async () => {
		const { client } = mockClient(() =>
			Response.json({ error: { message: 'SECRET resource exists' } }, { status: 403 })
		);
		await expect(client.catalog('hidden')).rejects.toMatchObject({
			status: 404,
			message: 'Resource not found.'
		});
		await expect(executePolarisAction(client, 'loadTable', form())).rejects.toMatchObject({
			status: 404
		});
		await expect(executePolarisAction(client, 'tableCredentials', form())).rejects.toMatchObject({
			status: 403
		});
	});

	it('discards vended S3, GCS and Azure secret values while retaining presence and expiry', () => {
		const summary = credentialSummary(
			{
				'storage-access-configs': [
					{
						prefix: 's3://bucket/repo/',
						config: {
							's3.access-key-id': 'aws-id',
							's3.secret-access-key': 'aws-secret',
							's3.session-token': 'aws-token',
							's3.session-token-expires-at-ms': '2000000000000'
						}
					},
					{ prefix: 'gs://bucket/repo/', config: { 'gcs.oauth2.token': 'gcs-secret' } },
					{
						prefix: 'abfss://container/repo/',
						config: { 'adls.sas-token.storage': 'azure-secret' }
					}
				]
			},
			'read-write',
			true
		);
		expect(summary.configurations).toHaveLength(3);
		expect(summary.configurations.every((entry) => entry.hasCredentials)).toBe(true);
		expect(summary.configurations[0].expiresAt).toBe(new Date(2000000000000).toISOString());
		for (const secret of ['aws-id', 'aws-secret', 'aws-token', 'gcs-secret', 'azure-secret'])
			expect(JSON.stringify(summary)).not.toContain(secret);
		expect(credentialSummary({ 'storage-access-configs': [] }, 'read', true).message).toContain(
			'FILE'
		);
	});
});

describe('Polaris form validation and actions', () => {
	it.each(['null', '[]', '{"flag":true}', '{broken'])(
		'rejects invalid string-map properties %s',
		(value) => {
			expect(() => formProperties(form({ properties: value }))).toThrow();
		}
	);

	it('rejects malformed namespace, missing versions and path traversal names', () => {
		for (const value of ['[]', '["one",""]', '["one\\u001ftwo"]', '[".."]', '{}'])
			expect(() => namespace(form({ namespace: value }))).toThrow();
		for (const value of ['', '-1', '1.5', 'NaN'])
			expect(() => version(form({ currentEntityVersion: value }))).toThrow();
		expect(() => required(form({ name: '..' }), 'name')).toThrow();
	});

	it.each(['createTable', 'loadTable', 'tableCredentials'] as const)(
		'supports %s with explicit read/write delegation and safe action receipts',
		async (action) => {
			const { client } = mockClient((url, init) => {
				expect(url.pathname).toContain(
					'/api/catalog/polaris/v1/science/namespaces/one%1Ftwo/icechunk-tables'
				);
				if (action !== 'createTable')
					expect(url.searchParams.get('access-mode')).toBe('read-write');
				if (action !== 'tableCredentials')
					expect(new Headers(init.headers).get('Polaris-Icechunk-Table-Access-Delegation')).toBe(
						'vended-credentials'
					);
				if (action === 'createTable')
					expect(JSON.parse(String(init.body))).toEqual({
						name: 'measurements',
						location: 's3://science/repo/',
						properties: {}
					});
				return Response.json({
					table: loaded,
					'storage-access-configs': [
						{ prefix: loaded.location, config: { 's3.secret-access-key': 'storage-secret' } }
					]
				});
			});
			const result = await executePolarisAction(
				client,
				action,
				form({ location: loaded.location, accessMode: 'read-write', delegate: 'on' })
			);
			expect(result.success).toBe(true);
			expect(result.credentialSummary?.accessMode).toBe('read-write');
			expect(JSON.stringify(result)).not.toContain('storage-secret');
		}
	);

	it('explains possible registration after delegated create credential vending fails', async () => {
		const { client } = mockClient(() => Response.json({}, { status: 400 }));
		await expect(
			executePolarisAction(
				client,
				'createTable',
				form({ location: loaded.location, delegate: 'on' })
			)
		).rejects.toThrow('may already have registered');
	});

	it('requires exact deletion confirmation and drops only the registration', async () => {
		const { client, fetcher } = mockClient((url, init) => {
			expect(url.pathname.endsWith('/icechunk-tables/measurements')).toBe(true);
			expect(init.method).toBe('DELETE');
			return new Response(null, { status: 204 });
		});
		await expect(
			executePolarisAction(client, 'deleteTable', form({ confirmation: 'wrong' }))
		).rejects.toThrow('confirm deletion');
		expect(fetcher).not.toHaveBeenCalled();
		expect(
			(await executePolarisAction(client, 'deleteTable', form({ confirmation: 'measurements' })))
				.message
		).toContain('remain untouched');
	});

	it('uses table grants for Icechunk and preserves cascade revocation semantics', async () => {
		const { client } = mockClient((url, init) => {
			expect(url.pathname.endsWith('/catalog-roles/reader/grants')).toBe(true);
			expect(url.searchParams.get('cascade')).toBe('true');
			expect(init.method).toBe('POST');
			expect(JSON.parse(String(init.body))).toEqual({
				grant: {
					type: 'table',
					privilege: 'TABLE_READ_DATA',
					namespace: ['one', 'two'],
					tableName: 'measurements'
				}
			});
			return new Response(null, { status: 201 });
		});
		await executePolarisAction(
			client,
			'revokeGrant',
			form({
				catalogRole: 'reader',
				type: 'table',
				privilege: 'TABLE_READ_DATA',
				tableName: 'measurements',
				cascade: 'on'
			})
		);
	});

	it.each(['createPrincipal', 'rotatePrincipal', 'resetPrincipal'] as const)(
		'shows newly generated principal credentials only for explicit %s responses',
		async (action) => {
			const { client } = mockClient(() =>
				Response.json({
					principal: { name: 'measurements' },
					credentials: { clientId: 'new-id', clientSecret: 'new-secret' }
				})
			);
			expect((await executePolarisAction(client, action, form())).credentials).toEqual({
				principal: 'measurements',
				clientId: 'new-id',
				clientSecret: 'new-secret'
			});
		}
	);

	const cases: {
		action: PolarisActionName;
		path: string;
		method: string;
		values?: Record<string, string>;
		body?: unknown;
	}[] = [
		{
			action: 'createCatalog',
			path: '/catalogs',
			method: 'POST',
			values: { defaultBaseLocation: 'file:///data/', storageConfigInfo: '{"storageType":"FILE"}' },
			body: {
				catalog: {
					name: 'measurements',
					type: 'INTERNAL',
					properties: { 'default-base-location': 'file:///data/' },
					storageConfigInfo: { storageType: 'FILE' }
				}
			}
		},
		{
			action: 'updateCatalog',
			path: '/catalogs/science',
			method: 'PUT',
			body: { currentEntityVersion: 3, properties: {} }
		},
		{
			action: 'deleteCatalog',
			path: '/catalogs/science',
			method: 'DELETE',
			values: { confirmation: 'science' }
		},
		{
			action: 'createNamespace',
			path: '/v1/science/namespaces',
			method: 'POST',
			body: { namespace: ['one', 'two'], properties: {} }
		},
		{
			action: 'updateNamespace',
			path: '/namespaces/one%1Ftwo/properties',
			method: 'POST',
			values: { updates: '{"owner":"alice"}', removals: 'old\nolder' },
			body: { updates: { owner: 'alice' }, removals: ['old', 'older'] }
		},
		{
			action: 'deleteNamespace',
			path: '/namespaces/one%1Ftwo',
			method: 'DELETE',
			values: { confirmation: 'one.two' }
		},
		{
			action: 'updatePrincipal',
			path: '/principals/measurements',
			method: 'PUT',
			body: { currentEntityVersion: 3, properties: {} }
		},
		{ action: 'deletePrincipal', path: '/principals/measurements', method: 'DELETE' },
		{
			action: 'createPrincipalRole',
			path: '/principal-roles',
			method: 'POST',
			body: { principalRole: { name: 'measurements', properties: {}, federated: false } }
		},
		{
			action: 'updatePrincipalRole',
			path: '/principal-roles/measurements',
			method: 'PUT',
			body: { currentEntityVersion: 3, properties: {} }
		},
		{ action: 'deletePrincipalRole', path: '/principal-roles/measurements', method: 'DELETE' },
		{
			action: 'assignPrincipalRole',
			path: '/principals/alice/principal-roles',
			method: 'PUT',
			body: { principalRole: { name: 'member' } }
		},
		{
			action: 'revokePrincipalRole',
			path: '/principals/alice/principal-roles/member',
			method: 'DELETE'
		},
		{
			action: 'createCatalogRole',
			path: '/catalog-roles',
			method: 'POST',
			body: { catalogRole: { name: 'measurements', properties: {} } }
		},
		{
			action: 'updateCatalogRole',
			path: '/catalog-roles/measurements',
			method: 'PUT',
			body: { currentEntityVersion: 3, properties: {} }
		},
		{ action: 'deleteCatalogRole', path: '/catalog-roles/measurements', method: 'DELETE' },
		{
			action: 'assignCatalogRole',
			path: '/principal-roles/member/catalog-roles/science',
			method: 'PUT',
			body: { catalogRole: { name: 'reader' } }
		},
		{
			action: 'revokeCatalogRole',
			path: '/principal-roles/member/catalog-roles/science/reader',
			method: 'DELETE'
		},
		{
			action: 'addGrant',
			path: '/catalog-roles/reader/grants',
			method: 'PUT',
			values: { type: 'catalog', privilege: 'TABLE_LIST' },
			body: { grant: { type: 'catalog', privilege: 'TABLE_LIST' } }
		}
	];
	it.each(cases)(
		'uses the OpenAPI management contract for $action',
		async ({ action, path, method, values, body }) => {
			const { client } = mockClient((url, init) => {
				expect(url.pathname.endsWith(path)).toBe(true);
				expect(init.method).toBe(method);
				if (body) expect(JSON.parse(String(init.body))).toEqual(body);
				return new Response(null, { status: method === 'DELETE' ? 204 : 201 });
			});
			await executePolarisAction(
				client,
				action,
				form({
					principal: 'alice',
					principalRole: 'member',
					catalogRole: 'reader',
					currentEntityVersion: '3',
					confirmation: 'measurements',
					...values
				})
			);
		}
	);
});

describe('Polaris workspace projections', () => {
	it('treats an undiscoverable direct table selection as missing while other read panels stay independent', async () => {
		const { client } = mockClient((url) => {
			if (url.pathname.endsWith('/icechunk-tables/hidden'))
				return Response.json({}, { status: 403 });
			return Response.json({}, { status: 403 });
		});
		await expect(
			loadPolarisWorkspace(
				client,
				{ clientId: 'reader' },
				new URL('http://localhost/polaris?catalog=science&namespace=%5B%22one%22%5D&table=hidden'),
				settings
			)
		).rejects.toMatchObject({ status: 404, message: 'Resource not found.' });
	});

	it('keeps reader browsing functional when principal and role management are forbidden', async () => {
		const { client } = mockClient((url) => {
			if (url.pathname.includes('/api/management/'))
				return Response.json({ message: 'private' }, { status: 403 });
			if (url.pathname.endsWith('/icechunk-tables'))
				return Response.json({
					identifiers: [{ namespace: ['one', 'two'], name: 'measurements' }]
				});
			if (url.pathname.endsWith('/namespaces')) return Response.json({ namespaces: [] });
			if (url.pathname.endsWith('/measurements'))
				return Response.json({
					table: loaded,
					'storage-access-configs': [
						{ prefix: loaded.location, config: { 's3.secret-access-key': 'never-serialize' } }
					]
				});
			return Response.json({ namespace: ['one', 'two'], properties: { owner: 'science' } });
		});
		const url = new URL(
			'http://localhost/polaris?catalog=science&namespace=%5B%22one%22%2C%22two%22%5D&table=measurements'
		);
		const data = await loadPolarisWorkspace(client, { clientId: 'reader' }, url, settings);
		expect(data.tables[0].name).toBe('measurements');
		expect(data.loadedTable?.location).toBe(loaded.location);
		expect(data.errors.principals).toBe('Resource not found.');
		expect(data.errors.catalogRoles).toBe('Resource not found.');
		expect(JSON.stringify(data)).not.toContain('never-serialize');
		expect(JSON.stringify(data)).not.toContain('oauth-secret');
		expect(data.privileges.table).not.toContain('TABLE_ADD_SNAPSHOT');
	});

	it('renders a disconnected workspace without requesting any data', async () => {
		const data = await loadPolarisWorkspace(
			null,
			null,
			new URL('http://localhost/polaris'),
			settings
		);
		expect(data.connected).toBe(false);
		expect(data.session).toBeNull();
		expect(data.catalogs).toEqual([]);
	});

	it('treats empty optional query selections as unset when browsing a namespace', async () => {
		const { client } = mockClient((url) => {
			if (url.pathname.endsWith('/catalogs')) return Response.json({ catalogs: [] });
			if (url.pathname.endsWith('/principals')) return Response.json({ principals: [] });
			return Response.json({ roles: [] });
		});
		const data = await loadPolarisWorkspace(
			client,
			{ clientId: 'reader' },
			new URL('http://localhost/polaris?catalog=&table=&principal=&principalRole=&catalogRole='),
			settings
		);
		expect(data.errors.selection).toBeUndefined();
		expect(data.selected.table).toBe('');
	});
});
