import type { PolarisActionResult } from '$api/types';
import { datasetLayer } from '$api/catalog-datasets';
import { genericTablePath, type PolarisClient } from './polaris-client';
import { field, formProperties, namespace, PolarisInputError, required } from './polaris-forms';
import { validateStorageLocator } from './polaris-storage-locator';

/** Register a Raw asset's catalog metadata; file upload and revision publication are separate. */
export async function registerRawTable(
	client: PolarisClient,
	form: FormData
): Promise<PolarisActionResult> {
	const catalog = required(form, 'catalog');
	const levels = namespace(form);
	const name = required(form, 'name');
	const properties = formProperties(form);
	properties['huron.dataset-type'] = 'raw';
	const layer = field(form, 'layer');
	if (layer) properties['huron.layer'] = layer;
	const placement = datasetLayer(levels, properties);
	if (placement.id === 'conflict') throw new PolarisInputError(placement.detail);
	if (placement.id !== 'unassigned') properties['huron.layer'] = placement.id;
	const baseLocation = field(form, 'location');
	if (baseLocation) validateStorageLocator(baseLocation, 'location');
	const doc = field(form, 'doc');
	if (doc.length > 10_000) throw new PolarisInputError('doc must be at most 10000 characters.');
	await client.request(genericTablePath(catalog, levels), 'POST', {
		name,
		format: 'raw',
		...(baseLocation ? { 'base-location': baseLocation } : {}),
		...(doc ? { doc } : {}),
		properties
	});
	return {
		action: 'registerRawTable',
		success: true,
		message: `Raw collection ${name} registered in Polaris. No files were uploaded and no Raw revision was published.`
	};
}
