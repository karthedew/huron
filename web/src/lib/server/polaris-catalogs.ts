import type { HuronUser, PolarisCatalog } from '$api/types';
import type { PolarisClient } from './polaris-client';
import { PolarisApiError } from './polaris-client';
import { getBootstrapPolarisClient } from './huron-accounts';

/** Publish only current Polaris memberships that the user's own principal can read. */
export async function visibleCatalogs(
	user: HuronUser,
	client: PolarisClient
): Promise<PolarisCatalog[]> {
	if (user.isAdmin) return client.catalogs();
	const directory = await getBootstrapPolarisClient(client.connection.realm);
	const catalogs = await directory.catalogs();
	const visible = await Promise.all(
		catalogs.map(async (catalog): Promise<PolarisCatalog | null> => {
			try {
				if (!(await directory.assignments(user.polarisPrincipalRole, catalog.name)).length)
					return null;
				return await client.catalog(catalog.name);
			} catch (error) {
				if (error instanceof PolarisApiError && (error.status === 403 || error.status === 404))
					return null;
				throw error;
			}
		})
	);
	return visible.filter((catalog): catalog is PolarisCatalog => catalog !== null);
}
