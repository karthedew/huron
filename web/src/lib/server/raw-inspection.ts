import type { HuronUser, RawInspection } from '$api/types';
import { parseRawManifest, parseRawRevision, parseRawRevisions } from '$api/raw-ingestion-client';
import { boundRawTarget, requireRawPermissions, type RawTarget } from './raw-authorization';
import { rawBridgeRequest } from './raw-bridge';
import { managedRawDatasetId } from './raw-registration';
import { PolarisApiError, type PolarisClient } from './polaris-client';
import { requireOrganizationCatalog } from './huron-organizations';

/** Read immutable revision metadata only after current organization and data-read authorization. */
export async function loadRawInspection(
	client: PolarisClient,
	user: HuronUser,
	target: RawTarget,
	revisionId: string | null = null,
	before: number | null = null
): Promise<RawInspection> {
	await requireOrganizationCatalog(user, client, target.catalog);
	let datasetId: string | null;
	try {
		if (before !== null && (!Number.isSafeInteger(before) || before < 1))
			throw new PolarisApiError(400, 'Invalid revision page cursor.');
		if (
			revisionId &&
			!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(revisionId)
		)
			throw new PolarisApiError(400, 'Invalid Raw revision identity.');
		datasetId = await managedRawDatasetId(client, target);
	} catch (error) {
		if (error instanceof PolarisApiError && error.status === 409) return { state: 'unmanaged' };
		throw error;
	}
	if (!datasetId) return { state: 'unmanaged' };
	const result: RawInspection = {
		state: 'managed',
		datasetId,
		revisions: { revisions: [], next_before: null },
		selectedRevision: null,
		manifest: null,
		error: null
	};
	try {
		async function read(path: string): Promise<unknown> {
			const permissions = await requireRawPermissions(client, user, target, 'read');
			const response = await rawBridgeRequest({
				user,
				target: boundRawTarget(target, client.connection),
				permissions,
				method: 'GET',
				path,
				body: new Uint8Array(),
				headers: {}
			});
			return response.json();
		}
		result.revisions = parseRawRevisions(
			await read(
				`/api/raw-web/datasets/${datasetId}/revisions${before === null ? '' : `?before=${before}`}`
			)
		);
		result.selectedRevision = revisionId
			? (result.revisions.revisions.find((revision) => revision.id === revisionId) ??
				parseRawRevision(await read(`/api/raw-web/revisions/${revisionId}`)))
			: (result.revisions.revisions[0] ?? null);
		if (result.selectedRevision)
			result.manifest = parseRawManifest(
				await read(`/api/raw-web/revisions/${result.selectedRevision.id}/manifest`)
			);
		await requireRawPermissions(client, user, target, 'read');
		return result;
	} catch (error) {
		return {
			...result,
			revisions: { revisions: [], next_before: null },
			selectedRevision: null,
			manifest: null,
			error: error instanceof PolarisApiError ? error.message : 'Raw revision data is unavailable.'
		};
	}
}
