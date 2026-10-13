import type { PolarisWorkspaceData } from '$api/types';
import type { PolarisClient } from './polaris-client';
import { PolarisApiError } from './polaris-client';
import { namespace, required } from './polaris-forms';
import { POLARIS_PRIVILEGES } from './polaris-privileges';

export async function loadPolarisWorkspace(
	client: PolarisClient | null,
	identity: { clientId: string } | null,
	url: URL,
	settings: { url: string; realm: string }
): Promise<PolarisWorkspaceData> {
	const data: PolarisWorkspaceData = {
		connected: client !== null,
		upstream: settings.url,
		realm: settings.realm,
		session: identity,
		notice: null,
		catalogs: [],
		catalog: null,
		namespaces: [],
		nextNamespacePageToken: null,
		namespaceProperties: null,
		tables: [],
		nextPageToken: null,
		principals: [],
		principalRoles: [],
		catalogRoles: [],
		principalMemberships: [],
		catalogAssignments: [],
		grants: [],
		loadedTable: null,
		errors: {},
		selected: {
			catalog: '',
			namespace: [],
			principal: '',
			principalRole: '',
			catalogRole: '',
			table: ''
		},
		privileges: {
			catalog: POLARIS_PRIVILEGES.catalog.filter(icechunkPrivilege),
			namespace: POLARIS_PRIVILEGES.namespace.filter(icechunkPrivilege),
			table: POLARIS_PRIVILEGES.table.filter(icechunkPrivilege)
		}
	};
	if (!client) return data;
	let missingTable = false;
	const capture = async <T>(
		key: string,
		operation: () => Promise<T>,
		accept: (value: T) => void
	) => {
		try {
			accept(await operation());
		} catch (error) {
			if (key === 'table' && error instanceof PolarisApiError && error.status === 404)
				missingTable = true;
			data.errors[key] =
				error instanceof PolarisApiError ? error.message : 'Unable to load Polaris data.';
		}
	};
	const selections = new FormData();
	for (const key of [
		'catalog',
		'namespace',
		'principal',
		'principalRole',
		'catalogRole',
		'table'
	] as const) {
		const value = url.searchParams.get(key);
		if (value === null) continue;
		if (key !== 'namespace' && value.trim() === '') continue;
		selections.set(key, value);
		try {
			if (key === 'namespace') data.selected.namespace = namespace(selections, true);
			else data.selected[key] = required(selections, key);
		} catch (error) {
			data.errors.selection = error instanceof Error ? error.message : 'Invalid selection.';
		}
	}
	await Promise.all([
		capture(
			'catalogs',
			() => client.catalogs(),
			(value) => {
				data.catalogs = value;
			}
		),
		capture(
			'principals',
			() => client.principals(),
			(value) => {
				data.principals = value;
			}
		),
		capture(
			'principalRoles',
			() => client.principalRoles(),
			(value) => {
				data.principalRoles = value;
			}
		)
	]);
	if (!data.selected.catalog) data.selected.catalog = data.catalogs[0]?.name ?? '';
	const selected = data.selected;
	const operations: Promise<void>[] = [];
	if (selected.catalog) {
		operations.push(
			capture(
				'catalog',
				() => client.catalog(selected.catalog),
				(value) => {
					data.catalog = value;
				}
			)
		);
		operations.push(
			capture(
				'namespaces',
				() =>
					client.namespaces(
						selected.catalog,
						selected.namespace,
						url.searchParams.get('namespacePageToken') ?? ''
					),
				(value) => {
					data.namespaces = value.namespaces;
					data.nextNamespacePageToken = value.nextPageToken;
				}
			)
		);
		operations.push(
			capture(
				'catalogRoles',
				() => client.catalogRoles(selected.catalog),
				(value) => {
					data.catalogRoles = value;
				}
			)
		);
		if (selected.namespace.length) {
			operations.push(
				capture(
					'namespaceProperties',
					() => client.namespaceProperties(selected.catalog, selected.namespace),
					(value) => {
						data.namespaceProperties = value;
					}
				)
			);
			operations.push(
				capture(
					'tables',
					() =>
						client.tables(
							selected.catalog,
							selected.namespace,
							url.searchParams.get('pageToken') ?? ''
						),
					(value) => {
						data.tables = value.tables;
						data.nextPageToken = value.nextPageToken;
					}
				)
			);
			if (selected.table)
				operations.push(
					capture(
						'table',
						() => client.table(selected.catalog, selected.namespace, selected.table),
						(value) => {
							data.loadedTable = value;
						}
					)
				);
		}
		if (selected.principalRole)
			operations.push(
				capture(
					'catalogAssignments',
					() => client.assignments(selected.principalRole, selected.catalog),
					(value) => {
						data.catalogAssignments = value;
					}
				)
			);
		if (selected.catalogRole)
			operations.push(
				capture(
					'grants',
					() => client.grants(selected.catalog, selected.catalogRole),
					(value) => {
						data.grants = value;
					}
				)
			);
	}
	if (selected.principal)
		operations.push(
			capture(
				'principalMemberships',
				() => client.memberships(selected.principal),
				(value) => {
					data.principalMemberships = value;
				}
			)
		);
	await Promise.all(operations);
	if (missingTable) throw new PolarisApiError(404);
	return data;
}

function icechunkPrivilege(privilege: string): boolean {
	return (
		privilege.startsWith('CATALOG_') ||
		privilege.startsWith('NAMESPACE_') ||
		[
			'TABLE_LIST',
			'TABLE_CREATE',
			'TABLE_READ_PROPERTIES',
			'TABLE_READ_DATA',
			'TABLE_WRITE_DATA',
			'TABLE_DROP',
			'TABLE_FULL_METADATA'
		].includes(privilege)
	);
}
