import { error as httpError } from '@sveltejs/kit';
import { PolarisApiError } from '$lib/server/polaris-client';
import { loadRawTargetBranch } from '$lib/server/raw-targets';
import { managedRawDatasetId } from '$lib/server/raw-registration';
import { rawBridgeConfiguration } from '$lib/server/raw-bridge';
import type { RawTargetBranch } from '$api/types';
import type { PageServerLoad } from './$types';
export const load: PageServerLoad = async ({ locals, parent, url }) => {
	const workspace = await parent();
	let namespace: string[] = [];
	const query = url.searchParams.get('namespace');
	if (query) {
		try {
			const parsed: unknown = JSON.parse(query);
			if (
				!Array.isArray(parsed) ||
				!parsed.every((entry): entry is string => typeof entry === 'string')
			)
				httpError(400, 'Invalid namespace.');
			namespace = parsed;
		} catch {
			httpError(400, 'Invalid namespace.');
		}
	}
	const initialDataset = url.searchParams.get('table') ?? '';
	let initialDatasetId: string | null = null;
	let initialBranch: RawTargetBranch | null = null;
	let ingestError: string | null = null;
	if (locals.polaris && locals.user && workspace.selectedCatalog) {
		try {
			initialBranch = await loadRawTargetBranch(locals.polaris, locals.user, {
				catalog: workspace.selectedCatalog,
				namespace
			});
			if (initialDataset) {
				initialDatasetId = await managedRawDatasetId(locals.polaris, {
					catalog: workspace.selectedCatalog,
					namespace,
					name: initialDataset
				});
				if (!initialDatasetId) throw new PolarisApiError(404);
			}
		} catch (error) {
			if (error instanceof PolarisApiError && error.status === 404) httpError(404, 'Not found');
			ingestError = error instanceof Error ? error.message : 'Unable to load the destination.';
		}
	}
	try {
		rawBridgeConfiguration();
	} catch (error) {
		ingestError = error instanceof Error ? error.message : 'Raw storage is not configured.';
	}
	return { initialBranch, initialDataset, initialDatasetId, ingestError };
};
