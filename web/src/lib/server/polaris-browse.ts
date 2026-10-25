import type { PolarisBrowseBranch, PolarisBrowseData, PolarisCatalog } from '$api/types';
import { PolarisApiError, type PolarisClient } from './polaris-client';
import { namespace, required } from './polaris-forms';

/** Searches only catalog metadata already disclosed by the authenticated upstream. */
export function searchCatalogs(catalogs: PolarisCatalog[], query: string): PolarisCatalog[] {
	const term = query.trim().toLocaleLowerCase();
	if (!term) return catalogs;
	return catalogs.filter((catalog) =>
		[
			catalog.name,
			catalog.type,
			catalog.storageConfigInfo.storageType,
			...Object.entries(catalog.properties).flat()
		]
			.join(' ')
			.toLocaleLowerCase()
			.includes(term)
	);
}

/** Projects the browse hierarchy without requesting realm-wide access-control records. */
export async function loadPolarisBrowse(
	client: PolarisClient,
	catalogs: PolarisCatalog[],
	url: URL,
	settings: { url: string; realm: string }
): Promise<PolarisBrowseData> {
	const fields = new FormData();
	const catalogName = url.searchParams.get('catalog') || '';
	const selectedNamespace = url.searchParams.get('namespace');
	const tableName = url.searchParams.get('table') || '';
	const format = url.searchParams.get('format') ?? 'icechunk';
	if (format !== 'icechunk' && format !== 'iceberg' && format !== 'generic')
		throw new PolarisApiError(400, 'Choose a supported table format.');
	if (catalogName) fields.set('catalog', catalogName);
	if (selectedNamespace !== null) fields.set('namespace', selectedNamespace);
	if (tableName) fields.set('table', tableName);
	const selected = {
		catalog: catalogName ? required(fields, 'catalog') : '',
		namespace: selectedNamespace !== null ? namespace(fields, true) : [],
		table: tableName ? required(fields, 'table') : '',
		principal: '',
		principalRole: '',
		catalogRole: ''
	};
	if ((selected.table || selected.namespace.length) && !selected.catalog)
		throw new PolarisApiError(404);
	if (selected.table && !selected.namespace.length) throw new PolarisApiError(404);
	const catalog = catalogs.find((entry) => entry.name === selected.catalog) ?? null;
	if (selected.catalog && !catalog) throw new PolarisApiError(404);
	const data: PolarisBrowseData = {
		connected: true,
		upstream: settings.url,
		realm: settings.realm,
		session: null,
		notice: null,
		catalogs,
		catalog,
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
		selected,
		privileges: { catalog: [], namespace: [], table: [] },
		branches: [],
		inspection: null,
		governance: null,
		icebergTables: [],
		nextIcebergPageToken: null,
		loadedIcebergTable: null,
		genericTables: [],
		nextGenericPageToken: null,
		loadedGenericTable: null
	};
	if (!catalog) return data;
	if (selected.table) {
		if (format === 'iceberg')
			data.loadedIcebergTable = await client.icebergTable(
				selected.catalog,
				selected.namespace,
				selected.table
			);
		else if (format === 'generic')
			data.loadedGenericTable = await client.genericTable(
				selected.catalog,
				selected.namespace,
				selected.table
			);
		else
			data.loadedTable = await client.table(selected.catalog, selected.namespace, selected.table);
	}
	if (
		data.loadedGenericTable &&
		(url.searchParams.has('branch') || url.searchParams.has('snapshot'))
	)
		throw new PolarisApiError(404);
	if (data.loadedIcebergTable) {
		const branch = url.searchParams.get('branch');
		const snapshot = url.searchParams.get('snapshot');
		if (branch && data.loadedIcebergTable.refs[branch]?.type !== 'branch')
			throw new PolarisApiError(404);
		if (
			snapshot &&
			!data.loadedIcebergTable.snapshots.some((entry) => entry.snapshotId === snapshot)
		)
			throw new PolarisApiError(404);
	}
	const capture = async <T>(
		key: string,
		read: () => Promise<T>,
		accept: (value: T) => void,
		optional = false
	) => {
		try {
			accept(await read());
		} catch (error) {
			// An exact repository grant need not include namespace metadata or listing rights.
			if (!optional && !data.loadedTable && !data.loadedIcebergTable && !data.loadedGenericTable)
				throw error;
			data.errors[key] =
				error instanceof PolarisApiError ? error.message : 'Unable to load Polaris data.';
		}
	};
	const reads = [
		capture(
			'namespaces',
			() =>
				client.namespaces(
					selected.catalog,
					selected.namespace,
					url.searchParams.get('namespacePageToken') ?? ''
				),
			(result) => {
				data.namespaces = result.namespaces;
				data.nextNamespacePageToken = result.nextPageToken;
			}
		)
	];
	if (selected.namespace.length) {
		reads.push(
			capture(
				'namespaceProperties',
				() => client.namespaceProperties(selected.catalog, selected.namespace),
				(properties) => {
					data.namespaceProperties = properties;
				}
			)
		);
		reads.push(
			capture(
				'tables',
				() =>
					client.tables(
						selected.catalog,
						selected.namespace,
						url.searchParams.get('pageToken') ?? ''
					),
				(result) => {
					data.tables = result.tables;
					data.nextPageToken = result.nextPageToken;
				},
				true
			)
		);
		reads.push(
			capture(
				'icebergTables',
				() =>
					client.icebergTables(
						selected.catalog,
						selected.namespace,
						url.searchParams.get('icebergPageToken') ?? ''
					),
				(result) => {
					data.icebergTables = result.tables;
					data.nextIcebergPageToken = result.nextPageToken;
				},
				true
			)
		);
		reads.push(
			capture(
				'genericTables',
				() =>
					client.genericTables(
						selected.catalog,
						selected.namespace,
						url.searchParams.get('genericPageToken') ?? ''
					),
				(result) => {
					data.genericTables = result.tables;
					data.nextGenericPageToken = result.nextPageToken;
				},
				true
			)
		);
	}
	await Promise.all(reads);
	const ancestors = selected.namespace.map((_, index) => selected.namespace.slice(0, index));
	data.branches = await Promise.all(
		ancestors.map((levels) => loadAncestorBranch(client, selected.catalog, levels))
	);
	data.branches.push({
		namespace: selected.namespace,
		folders: data.namespaces,
		repositories: [...data.tables, ...data.icebergTables, ...data.genericTables],
		namespacePageToken: url.searchParams.get('namespacePageToken'),
		repositoryPageToken: url.searchParams.get('pageToken'),
		icebergPageToken: url.searchParams.get('icebergPageToken'),
		genericPageToken: url.searchParams.get('genericPageToken'),
		nextNamespacePageToken: data.nextNamespacePageToken,
		nextRepositoryPageToken: data.nextPageToken,
		nextIcebergPageToken: data.nextIcebergPageToken,
		nextGenericPageToken: data.nextGenericPageToken,
		errors: data.errors
	});
	return data;
}

async function loadAncestorBranch(
	client: PolarisClient,
	catalog: string,
	levels: string[]
): Promise<PolarisBrowseBranch> {
	const branch: PolarisBrowseBranch = {
		namespace: levels,
		folders: [],
		repositories: [],
		namespacePageToken: null,
		repositoryPageToken: null,
		icebergPageToken: null,
		genericPageToken: null,
		nextNamespacePageToken: null,
		nextRepositoryPageToken: null,
		nextIcebergPageToken: null,
		nextGenericPageToken: null,
		errors: {}
	};
	const capture = async <T>(key: string, read: () => Promise<T>, accept: (value: T) => void) => {
		try {
			accept(await read());
		} catch (error) {
			branch.errors[key] =
				error instanceof PolarisApiError ? error.message : 'Unable to load Polaris data.';
		}
	};
	const reads = [
		capture(
			'namespaces',
			() => client.namespaces(catalog, levels),
			(result) => {
				branch.folders = result.namespaces;
				branch.nextNamespacePageToken = result.nextPageToken;
			}
		)
	];
	if (levels.length)
		reads.push(
			capture(
				'tables',
				() => client.tables(catalog, levels),
				(result) => {
					branch.repositories.push(...result.tables);
					branch.nextRepositoryPageToken = result.nextPageToken;
				}
			)
		);
	if (levels.length)
		reads.push(
			capture(
				'icebergTables',
				() => client.icebergTables(catalog, levels),
				(result) => {
					branch.repositories.push(...result.tables);
					branch.nextIcebergPageToken = result.nextPageToken;
				}
			)
		);
	if (levels.length)
		reads.push(
			capture(
				'genericTables',
				() => client.genericTables(catalog, levels),
				(result) => {
					branch.repositories.push(...result.tables);
					branch.nextGenericPageToken = result.nextPageToken;
				}
			)
		);
	await Promise.all(reads);
	return branch;
}
