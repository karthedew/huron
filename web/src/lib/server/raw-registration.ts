import type { HuronUser } from '$api/types';
import { genericTablePath, object, PolarisApiError, type PolarisClient } from './polaris-client';
import { requireRawPermissions, type RawTarget } from './raw-authorization';

export const RAW_DATASET_ID_PROPERTY = 'huron.raw.dataset-id';
export const RAW_SERVICE_PROPERTY = 'huron.raw.service';
export const RAW_SERVICE_ID = 'huron-raw-v1';

/** Only a registration owned by this bridge can point at its immutable Raw revisions. */
export async function managedRawDatasetId(
	client: PolarisClient,
	target: RawTarget
): Promise<string | null> {
	let value: unknown;
	try {
		value = await client.request(
			genericTablePath(target.catalog, target.namespace, target.name),
			'GET',
			undefined,
			undefined,
			true
		);
	} catch (error) {
		if (error instanceof PolarisApiError && error.status === 404) return null;
		throw error;
	}
	const table = object(object(value).table);
	const properties = object(table.properties ?? {});
	const datasetId = properties[RAW_DATASET_ID_PROPERTY];
	if (
		table.name !== target.name ||
		table.format !== 'raw' ||
		properties[RAW_SERVICE_PROPERTY] !== RAW_SERVICE_ID ||
		typeof datasetId !== 'string' ||
		!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(datasetId)
	)
		throw new PolarisApiError(
			409,
			'This catalog entry is not a Raw dataset managed by this Huron service.'
		);
	return datasetId;
}

/** Refuse native-format collisions before receiving files; Polaris also enforces this on create. */
export async function preflightRawTarget(
	client: PolarisClient,
	user: HuronUser,
	target: RawTarget
): Promise<string | null> {
	const existing = await managedRawDatasetId(client, target);
	if (existing) return existing;
	await requireRawPermissions(client, user, target, 'create');
	for (const load of [
		() => client.table(target.catalog, target.namespace, target.name),
		() => client.icebergTable(target.catalog, target.namespace, target.name)
	]) {
		try {
			await load();
		} catch (error) {
			if (error instanceof PolarisApiError && error.status === 404) continue;
			throw error;
		}
		throw new PolarisApiError(409, 'An existing dataset already uses this catalog path.');
	}
	return null;
}

/** Create once with the actor's own Polaris authority, then read back its stable identity. */
export async function registerCommittedRawDataset(
	client: PolarisClient,
	user: HuronUser,
	target: RawTarget,
	datasetId: string
): Promise<void> {
	await requireRawPermissions(client, user, target, 'write');
	const existing = await managedRawDatasetId(client, target);
	if (existing && existing !== datasetId)
		throw new PolarisApiError(409, 'The Polaris entry belongs to a different Raw dataset.');
	if (!existing) {
		await requireRawPermissions(client, user, target, 'create');
		try {
			await client.request(genericTablePath(target.catalog, target.namespace), 'POST', {
				name: target.name,
				format: 'raw',
				properties: {
					'huron.dataset-type': 'raw',
					[RAW_SERVICE_PROPERTY]: RAW_SERVICE_ID,
					[RAW_DATASET_ID_PROPERTY]: datasetId
				}
			});
		} catch (error) {
			if (!(error instanceof PolarisApiError) || error.status !== 409) throw error;
		}
	}
	if ((await managedRawDatasetId(client, target)) !== datasetId)
		throw new PolarisApiError(409, 'Polaris did not confirm the committed Raw dataset identity.');
	await requireRawPermissions(client, user, target, 'write');
}
