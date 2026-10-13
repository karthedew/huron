import type { PolarisActionResult } from '$api/types';
import { namespacePath, type PolarisClient } from './polaris-client';
import { field, namespace, PolarisInputError, required } from './polaris-forms';
import { validateStorageLocator } from './polaris-storage-locator';

/** Register existing Iceberg metadata through the caller's Polaris identity without replacement. */
export async function registerIcebergTable(
	client: PolarisClient,
	form: FormData
): Promise<PolarisActionResult> {
	const catalog = required(form, 'catalog');
	const levels = namespace(form);
	const name = required(form, 'name');
	const metadataLocation = field(form, 'metadataLocation');
	if (!metadataLocation) throw new PolarisInputError('metadataLocation is required.');
	validateStorageLocator(metadataLocation, 'metadataLocation');
	await client.request(`${namespacePath(catalog, levels)}/register`, 'POST', {
		name,
		'metadata-location': metadataLocation,
		overwrite: false
	});
	return {
		action: 'registerIcebergTable',
		success: true,
		message: `Iceberg table ${name} registered in Polaris from its existing metadata. Its data and snapshots were not modified.`
	};
}
