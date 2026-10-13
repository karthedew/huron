import { createServer } from 'node:http';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Disposable, stateful protocol peer: grants determine every browser-test operation.
const principals = new Map([
	['root', { name: 'root', clientId: 'browser-admin', properties: {}, entityVersion: 1 }]
]);
const credentials = new Map([['browser-admin', { secret: 'browser-secret', principal: 'root' }]]);
const principalRoles = new Map([
	['service_admin', { name: 'service_admin', properties: {}, entityVersion: 1 }]
]);
const memberships = new Map([['root', new Set(['service_admin'])]]);
const catalogs = new Map();
const catalogRoles = new Map();
const assignments = new Map();
const namespaces = new Map();
const tables = new Map();
const genericTables = new Map();
const icebergTables = new Map();
const grantRecords = new Map();
const key = (...parts) => JSON.stringify(parts);
const named = (value) => ({ properties: {}, ...value, entityVersion: value.entityVersion ?? 1 });

for (const name of ['huron-local', 'ocean-data']) {
	const location =
		name === 'ocean-data'
			? 's3://browser-test/ocean-data/'
			: `${pathToFileURL(join(process.env.HURON_E2E_STORAGE_ROOT ?? '/tmp/huron-browser-test', name)).href}/`;
	catalogs.set(name, {
		name,
		type: 'INTERNAL',
		properties: {
			'default-base-location': location,
			description: name === 'huron-local' ? 'Earth observations' : 'Ocean temperatures'
		},
		storageConfigInfo: {
			storageType: name === 'ocean-data' ? 'S3' : 'FILE',
			allowedLocations: [location]
		},
		entityVersion: 1
	});
	namespaces.set(key(name, ['science']), { location: `${location}science/` });
	tables.set(key(name, ['science'], 'temperature'), {
		name: 'temperature',
		location: `${location}science/temperature`,
		properties: { description: `${name} repository` }
	});
	catalogRoles.set(
		key(name, 'huron_catalog_admin'),
		named({
			name: 'huron_catalog_admin',
			properties: { 'huron.managed-role': 'admin' }
		})
	);
	assignments.set(key('service_admin', name), new Set(['huron_catalog_admin']));
	grantRecords.set(
		key(name, 'huron_catalog_admin'),
		['CATALOG_MANAGE_ACCESS', 'CATALOG_MANAGE_METADATA', 'CATALOG_MANAGE_CONTENT'].map(
			(privilege) => ({ type: 'catalog', privilege })
		)
	);
}

// Native Iceberg metadata fixture used only by this disposable protocol peer.
const icebergFixture = {
	metadata: {
		'format-version': 2,
		'table-uuid': 'browser-iceberg-table',
		location: 's3://browser-test/observations/',
		'current-schema-id': 0,
		'current-snapshot-id': 42,
		properties: { description: 'Iceberg measurements' },
		schemas: [
			{
				'schema-id': 0,
				type: 'struct',
				fields: [
					{ id: 1, name: 'station', required: true, type: 'string' },
					{
						id: 2,
						name: 'temperature',
						required: false,
						type: 'double',
						doc: 'Air temperature in Kelvin'
					}
				]
			}
		],
		snapshots: [
			{
				'snapshot-id': 42,
				'timestamp-ms': 1704067200000,
				'schema-id': 0,
				summary: { operation: 'append', 'added-records': '2' }
			}
		],
		refs: { main: { type: 'branch', 'snapshot-id': 42 } },
		'snapshot-log': [{ 'timestamp-ms': 1704067200000, 'snapshot-id': 42 }],
		'metadata-log': []
	}
};
icebergFixture.metadata.properties['huron.layer'] = 'gold';
icebergTables.set(key('huron-local', ['science'], 'observations'), icebergFixture);
genericTables.set(key('huron-local', ['science'], 'source_files'), {
	name: 'source_files',
	format: 'raw',
	'base-location': 'file:///tmp/huron-browser-test/raw/',
	doc: 'Protocol-test source collection',
	properties: { 'huron.dataset-type': 'raw', 'huron.layer': 'bronze' }
});
genericTables.set(key('huron-local', ['science'], 'external_delta'), {
	name: 'external_delta',
	format: 'delta',
	'base-location': 's3://browser-test/delta/',
	properties: {}
});

function assetExists(catalog, namespace, name) {
	const id = key(catalog, namespace, name);
	return tables.has(id) || genericTables.has(id) || icebergTables.has(id);
}

function assignedRoles(principal, catalog) {
	return [...(memberships.get(principal) ?? [])].flatMap((principalRole) => [
		...(assignments.get(key(principalRole, catalog)) ?? [])
	]);
}

function permits(principal, catalog, privilege, namespace = [], table = '') {
	if (principal === 'root' && privilege.startsWith('CATALOG_')) return true;
	const all = assignedRoles(principal, catalog).flatMap(
		(role) => grantRecords.get(key(catalog, role)) ?? []
	);
	return all.some((grant) => {
		const scope =
			grant.type === 'catalog' ||
			(grant.type === 'namespace' &&
				grant.namespace.every((level, index) => namespace[index] === level)) ||
			(grant.type === 'table' &&
				JSON.stringify(grant.namespace) === JSON.stringify(namespace) &&
				grant.tableName === table);
		if (!scope) return false;
		if (grant.privilege === privilege) return true;
		if (grant.privilege === 'CATALOG_MANAGE_ACCESS') return privilege === 'CATALOG_MANAGE_ACCESS';
		if (grant.privilege === 'CATALOG_MANAGE_METADATA')
			return [
				'CATALOG_READ_PROPERTIES',
				'CATALOG_MANAGE_METADATA',
				'NAMESPACE_READ_PROPERTIES',
				'NAMESPACE_WRITE_PROPERTIES',
				'NAMESPACE_CREATE',
				'NAMESPACE_DROP',
				'NAMESPACE_LIST',
				'TABLE_READ_PROPERTIES',
				'TABLE_CREATE',
				'TABLE_DROP',
				'TABLE_LIST'
			].includes(privilege);
		if (grant.privilege === 'CATALOG_MANAGE_CONTENT') return privilege !== 'CATALOG_MANAGE_ACCESS';
		if (grant.privilege === 'TABLE_WRITE_DATA')
			return ['TABLE_READ_DATA', 'TABLE_READ_PROPERTIES', 'TABLE_LIST'].includes(privilege);
		if (grant.privilege === 'TABLE_READ_DATA')
			return ['TABLE_READ_PROPERTIES', 'TABLE_LIST'].includes(privilege);
		return false;
	});
}

const server = createServer(async (request, response) => {
	const json = (value, status = 200) => {
		response.writeHead(status, { 'Content-Type': 'application/json' });
		response.end(JSON.stringify(value));
	};
	const empty = () => {
		response.writeHead(204);
		response.end();
	};
	const denied = () =>
		json({ error: { message: 'PRIVATE upstream details must never leak' } }, 403);
	const missing = () => json({}, 404);
	try {
		const url = new URL(request.url, 'http://127.0.0.1:8189');
		const path = url.pathname.split('/').filter(Boolean).map(decodeURIComponent);
		let body = '';
		for await (const chunk of request) body += chunk;
		const method = request.method;
		if (url.pathname === '/health') return json({ ok: true });
		if (url.pathname === '/api/catalog/v1/oauth/tokens') {
			const form = new URLSearchParams(body);
			const client = credentials.get(form.get('client_id'));
			if (!client || form.get('client_secret') !== client.secret)
				return json({ error: 'invalid_client' }, 400);
			return json({ access_token: form.get('client_id'), token_type: 'bearer', expires_in: 3600 });
		}
		const identity = credentials.get(
			request.headers.authorization?.replace('Bearer ', '')
		)?.principal;
		if (!identity) return json({}, 401);
		const payload = body ? JSON.parse(body) : {};
		if (path[1] === 'management') {
			const [resource, name, child, target, leaf, item] = path.slice(3);
			const root = identity === 'root';
			if (resource === 'principals') {
				if (!root) return denied();
				if (!name) {
					if (method === 'GET') return json({ principals: [...principals.values()] });
					const principal = named(payload.principal);
					if (principals.has(principal.name)) return json({}, 409);
					principal.clientId = `${principal.name}-client`;
					const secret = `${principal.name}-secret`;
					principals.set(principal.name, principal);
					credentials.set(principal.clientId, { secret, principal: principal.name });
					return json(
						{ principal, credentials: { clientId: principal.clientId, clientSecret: secret } },
						201
					);
				}
				if (!principals.has(name)) return missing();
				if (child === 'principal-roles') {
					const current = memberships.get(name) ?? new Set();
					if (method === 'PUT') current.add(payload.principalRole.name);
					if (method === 'DELETE') current.delete(target);
					memberships.set(name, current);
					return method === 'GET'
						? json({ roles: [...current].map((role) => principalRoles.get(role)).filter(Boolean) })
						: empty();
				}
				if (child === 'rotate' || child === 'reset') {
					const principal = principals.get(name);
					const secret = `${name}-${Date.now()}-secret`;
					credentials.set(principal.clientId, { secret, principal: name });
					return json({
						principal,
						credentials: { clientId: principal.clientId, clientSecret: secret }
					});
				}
				if (method === 'DELETE') {
					principals.delete(name);
					memberships.delete(name);
					return empty();
				}
				if (method === 'PUT')
					principals.set(name, {
						...principals.get(name),
						properties: payload.properties,
						entityVersion: principals.get(name).entityVersion + 1
					});
				return json(principals.get(name));
			}
			if (resource === 'principal-roles') {
				if (child === 'catalog-roles') {
					if (!root && !permits(identity, target, 'CATALOG_MANAGE_ACCESS')) return denied();
					const current = assignments.get(key(name, target)) ?? new Set();
					if (method === 'PUT') current.add(payload.catalogRole.name);
					if (method === 'DELETE') current.delete(leaf);
					assignments.set(key(name, target), current);
					return method === 'GET'
						? json({
								roles: [...current]
									.map((role) => catalogRoles.get(key(target, role)))
									.filter(Boolean)
							})
						: empty();
				}
				if (!root) return denied();
				if (!name) {
					if (method === 'GET') return json({ roles: [...principalRoles.values()] });
					const role = named(payload.principalRole);
					if (principalRoles.has(role.name)) return json({}, 409);
					principalRoles.set(role.name, role);
					return empty();
				}
				if (!principalRoles.has(name)) return missing();
				if (method === 'DELETE') {
					principalRoles.delete(name);
					return empty();
				}
				if (method === 'PUT')
					principalRoles.set(name, {
						...principalRoles.get(name),
						properties: payload.properties,
						entityVersion: principalRoles.get(name).entityVersion + 1
					});
				return json(principalRoles.get(name));
			}
			if (resource === 'catalogs') {
				if (!name) {
					if (!root) return denied();
					if (method === 'GET') return json({ catalogs: [...catalogs.values()] });
					const catalog = named(payload.catalog);
					if (catalogs.has(catalog.name)) return json({}, 409);
					catalogs.set(catalog.name, catalog);
					return empty();
				}
				const catalog = catalogs.get(name);
				if (!catalog) return missing();
				if (child === 'catalog-roles') {
					if (!permits(identity, name, 'CATALOG_MANAGE_ACCESS')) return denied();
					if (!target) {
						if (method === 'GET')
							return json({
								roles: [...catalogRoles]
									.filter(([id]) => JSON.parse(id)[0] === name)
									.map(([, role]) => role)
							});
						const role = named(payload.catalogRole);
						if (catalogRoles.has(key(name, role.name))) return json({}, 409);
						catalogRoles.set(key(name, role.name), role);
						return empty();
					}
					const role = catalogRoles.get(key(name, target));
					if (!role) return missing();
					if (leaf === 'grants') {
						const current = grantRecords.get(key(name, target)) ?? [];
						if (
							method === 'PUT' &&
							!current.some((grant) => JSON.stringify(grant) === JSON.stringify(payload.grant))
						)
							current.push(payload.grant);
						const next =
							method === 'POST'
								? current.filter((grant) => JSON.stringify(grant) !== JSON.stringify(payload.grant))
								: current;
						grantRecords.set(key(name, target), next);
						return method === 'GET' ? json({ grants: next }) : empty();
					}
					if (leaf === 'principal-roles')
						return json({
							roles: [...assignments]
								.filter(([id, roles]) => {
									const [principalRole, catalogName] = JSON.parse(id);
									return (
										catalogName === name && roles.has(target) && principalRoles.has(principalRole)
									);
								})
								.map(([id]) => principalRoles.get(JSON.parse(id)[0]))
						});
					if (method === 'DELETE') {
						catalogRoles.delete(key(name, target));
						return empty();
					}
					if (method === 'PUT')
						catalogRoles.set(key(name, target), {
							...role,
							properties: payload.properties,
							entityVersion: role.entityVersion + 1
						});
					return json(catalogRoles.get(key(name, target)));
				}
				if (
					!permits(
						identity,
						name,
						method === 'GET' ? 'CATALOG_READ_PROPERTIES' : 'CATALOG_MANAGE_METADATA'
					)
				)
					return denied();
				if (method === 'DELETE') {
					if ([...namespaces.keys()].some((id) => JSON.parse(id)[0] === name)) return json({}, 409);
					catalogs.delete(name);
					return empty();
				}
				if (method === 'PUT')
					catalogs.set(name, {
						...catalog,
						properties: payload.properties,
						storageConfigInfo: payload.storageConfigInfo ?? catalog.storageConfigInfo,
						entityVersion: catalog.entityVersion + 1
					});
				return json(catalogs.get(name));
			}
		}
		const icechunk = path[2] === 'polaris';
		const catalogName = path[icechunk ? 4 : 3];
		const namespace = path[icechunk ? 6 : 5]?.split('\x1f') ?? [];
		const tableName = icechunk ? path[8] : undefined;
		const catalog = catalogs.get(catalogName);
		if (!catalog) return missing();
		if (path[2] === 'polaris' && path[5] === 'applicable-policies') {
			const policyNamespace = url.searchParams.get('namespace')?.split('\x1f') ?? [];
			if (
				!permits(
					identity,
					catalogName,
					'TABLE_READ_PROPERTIES',
					policyNamespace,
					url.searchParams.get('target-name') ?? ''
				)
			)
				return denied();
			return json({ 'applicable-policies': [], 'next-page-token': null });
		}
		if (icechunk && ['icechunk-tables', 'generic-tables'].includes(path[7])) {
			const tableStore = path[7] === 'generic-tables' ? genericTables : tables;
			if (!namespaces.has(key(catalogName, namespace))) return missing();
			const required =
				method === 'POST'
					? 'TABLE_CREATE'
					: method === 'DELETE'
						? 'TABLE_DROP'
						: !tableName
							? 'TABLE_LIST'
							: path[9] === 'credentials' ||
								  request.headers['polaris-icechunk-table-access-delegation'] ===
										'vended-credentials'
								? url.searchParams.get('access-mode') === 'read-write'
									? 'TABLE_WRITE_DATA'
									: 'TABLE_READ_DATA'
								: 'TABLE_READ_PROPERTIES';
			if (
				tableName === 'concealed' ||
				!permits(identity, catalogName, required, namespace, tableName)
			)
				return denied();
			if (!tableName) {
				if (method === 'POST') {
					if (assetExists(catalogName, namespace, payload.name)) return json({}, 409);
					tableStore.set(key(catalogName, namespace, payload.name), payload);
					return json({ table: payload, 'storage-access-configs': [] });
				}
				return json({
					identifiers: [...tableStore.keys()]
						.map(JSON.parse)
						.filter(
							([name, levels]) =>
								name === catalogName && JSON.stringify(levels) === JSON.stringify(namespace)
						)
						.map(([, levels, name]) => ({ namespace: levels, name })),
					'next-page-token': null
				});
			}
			const table = tableStore.get(key(catalogName, namespace, tableName));
			if (!table) return missing();
			if (method === 'DELETE') {
				tableStore.delete(key(catalogName, namespace, tableName));
				return empty();
			}
			const delegated =
				path[9] === 'credentials' ||
				request.headers['polaris-icechunk-table-access-delegation'] === 'vended-credentials';
			return json({
				...(path[9] === 'credentials' ? {} : { table }),
				'storage-access-configs':
					delegated && catalog.storageConfigInfo.storageType !== 'FILE'
						? [
								{
									prefix: table.location,
									config: {
										's3.access-key-id': 'NEVER_RENDER_ACCESS_KEY',
										's3.secret-access-key': 'NEVER_RENDER_STORAGE_SECRET',
										's3.session-token': 'NEVER_RENDER_STORAGE_TOKEN',
										's3.session-token-expires-at-ms': '1900000000000'
									}
								}
							]
						: []
			});
		}
		if (path[4] === 'namespaces' && path[6] === 'register' && method === 'POST') {
			if (!namespaces.has(key(catalogName, namespace))) return missing();
			if (!permits(identity, catalogName, 'TABLE_CREATE', namespace, payload.name)) return denied();
			if (assetExists(catalogName, namespace, payload.name)) return json({}, 409);
			// This fixed fixture stands in for a readable existing metadata file, never arbitrary invented rows.
			if (payload['metadata-location'] !== 's3://browser-test/existing/metadata/v1.metadata.json')
				return json({}, 400);
			const registered = {
				...structuredClone(icebergFixture),
				'metadata-location': payload['metadata-location']
			};
			icebergTables.set(key(catalogName, namespace, payload.name), registered);
			return json(registered);
		}
		if (path[4] === 'namespaces' && path[6] === 'tables') {
			if (!namespaces.has(key(catalogName, namespace))) return missing();
			if (
				!permits(
					identity,
					catalogName,
					path[7] ? 'TABLE_READ_PROPERTIES' : 'TABLE_LIST',
					namespace,
					path[7]
				)
			)
				return denied();
			if (!path[7])
				return json({
					identifiers: [...icebergTables.keys()]
						.map(JSON.parse)
						.filter(
							([name, levels]) =>
								name === catalogName && JSON.stringify(levels) === JSON.stringify(namespace)
						)
						.map(([, levels, name]) => ({ namespace: levels, name })),
					'next-page-token': null
				});
			const registered = icebergTables.get(key(catalogName, namespace, path[7]));
			return registered ? json(registered) : missing();
		}

		if (path[4] === 'namespaces') {
			const required =
				method === 'POST' && !namespace.length
					? 'NAMESPACE_CREATE'
					: method === 'DELETE'
						? 'NAMESPACE_DROP'
						: method === 'POST'
							? 'NAMESPACE_WRITE_PROPERTIES'
							: namespace.length
								? 'NAMESPACE_READ_PROPERTIES'
								: 'NAMESPACE_LIST';
			if (!permits(identity, catalogName, required, namespace)) return denied();
			if (!namespace.length) {
				if (method === 'POST') {
					const id = key(catalogName, payload.namespace);
					if (namespaces.has(id)) return json({}, 409);
					namespaces.set(id, payload.properties ?? {});
					return json({ namespace: payload.namespace, properties: payload.properties ?? {} }, 201);
				}
				const parent = url.searchParams.get('parent')?.split('\x1f') ?? [];
				return json({
					namespaces: [...namespaces.keys()]
						.map(JSON.parse)
						.filter(
							([name, levels]) =>
								name === catalogName &&
								levels.length === parent.length + 1 &&
								parent.every((level, index) => levels[index] === level)
						)
						.map(([, levels]) => levels),
					'next-page-token': null
				});
			}
			const id = key(catalogName, namespace);
			const properties = namespaces.get(id);
			if (!properties) return missing();
			if (method === 'DELETE') {
				if (
					[...tables.keys(), ...genericTables.keys(), ...icebergTables.keys()]
						.map(JSON.parse)
						.some(
							([name, levels]) =>
								name === catalogName && JSON.stringify(levels) === JSON.stringify(namespace)
						)
				)
					return json({}, 409);
				namespaces.delete(id);
				return empty();
			}
			if (method === 'POST') {
				for (const removal of payload.removals ?? []) delete properties[removal];
				Object.assign(properties, payload.updates ?? {});
				return json({
					updated: Object.keys(payload.updates ?? {}),
					removed: payload.removals ?? [],
					missing: []
				});
			}
			return json({ namespace, properties });
		}
		return missing();
	} catch (error) {
		console.error(error);
		return json({ error: 'Mock protocol failure' }, 500);
	}
});
server.listen(8189, '127.0.0.1');
process.on('SIGTERM', () => server.close());
