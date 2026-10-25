import { error as httpError } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { loadPolarisBrowse } from '$lib/server/polaris-browse';
import { PolarisApiError } from '$lib/server/polaris-client';
import { getAuthenticatedPolaris } from '$lib/server/huron-auth';
import { consumePolarisNotice } from '$lib/server/polaris-session';
import { createPolarisActions } from '$lib/server/polaris-route-actions';
import { inspectIcechunk } from '$lib/server/icechunk-inspector';
import { loadDatasetGovernance } from '$lib/server/polaris-dataset-governance';

export const load: PageServerLoad = async (event) => {
	const client = getAuthenticatedPolaris(event);
	const { catalogs } = await event.parent();
	try {
		const data = await loadPolarisBrowse(client, catalogs, event.url, client.connection);
		data.notice = consumePolarisNotice(event.cookies);
		const user = event.locals.user;
		if (user && (data.loadedTable || data.loadedIcebergTable || data.loadedRawTable)) {
			const [inspection, governance] = await Promise.all([
				data.loadedTable
					? inspectIcechunk(
							client,
							data.selected.catalog,
							data.selected.namespace,
							data.selected.table,
							event.url.searchParams.get('branch') || '',
							event.url.searchParams.get('snapshot') || ''
						)
					: Promise.resolve(null),
				loadDatasetGovernance(
					client,
					user,
					{
						catalog: data.selected.catalog,
						namespace: data.selected.namespace,
						table: data.selected.table,
						format: data.loadedRawTable ? 'raw' : data.loadedIcebergTable ? 'iceberg' : 'icechunk'
					},
					undefined,
					event.url.searchParams.get('policiesPageToken') || ''
				)
			]);
			data.inspection = inspection;
			data.governance = governance;
		}
		return data;
	} catch (error) {
		if (error instanceof PolarisApiError) httpError(error.status, error.message);
		throw error;
	}
};

export const actions = createPolarisActions({
	path: '/browse',
	allowedActions: [
		'createNamespace',
		'updateNamespace',
		'deleteNamespace',
		'createTable',
		'registerIcebergTable',
		'loadTable',
		'deleteTable',
		'tableCredentials'
	]
});
