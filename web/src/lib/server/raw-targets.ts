import type { HuronUser, RawTargetBranch } from '$api/types';
import { requireOrganizationCatalog } from './huron-organizations';
import { PolarisApiError, type PolarisClient } from './polaris-client';
import { managedRawDatasetId } from './raw-registration';

/** Browse the caller's own namespace metadata; external Raw registrations remain unselectable. */
export async function loadRawTargetBranch(
	client: PolarisClient,
	user: HuronUser,
	selection: {
		catalog: string;
		namespace: string[];
		namespacePageToken?: string;
		datasetPageToken?: string;
	}
): Promise<RawTargetBranch> {
	await requireOrganizationCatalog(user, client, selection.catalog);
	if (selection.namespace.length)
		await client.namespaceProperties(selection.catalog, selection.namespace);
	const folders = await client.namespaces(
		selection.catalog,
		selection.namespace,
		selection.namespacePageToken
	);
	const tables = selection.namespace.length
		? await client.rawTables(selection.catalog, selection.namespace, selection.datasetPageToken)
		: { tables: [], nextPageToken: null };
	const datasets = await Promise.all(
		tables.tables
			.filter((table) => table.isRaw === true)
			.map(async (table) => {
				let datasetId: string | null = null;
				try {
					datasetId = await managedRawDatasetId(client, {
						catalog: selection.catalog,
						namespace: selection.namespace,
						name: table.name
					});
				} catch (error) {
					if (!(error instanceof PolarisApiError) || error.status !== 409) throw error;
				}
				return { name: table.name, datasetId };
			})
	);
	return {
		catalog: selection.catalog,
		namespace: selection.namespace,
		folders: folders.namespaces,
		datasets,
		nextNamespacePageToken: folders.nextPageToken,
		nextDatasetPageToken: tables.nextPageToken
	};
}
