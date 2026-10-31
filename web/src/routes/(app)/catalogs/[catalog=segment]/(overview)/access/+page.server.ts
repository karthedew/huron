import { api, fail } from '$lib/server/guard';
import { HuronApiError } from '$lib/server/huron-api';
import type { PageServerLoad } from './$types';

/**
 * The groups holding each role on the catalog, the inherited ones included. The API lets every
 * role that can see a catalog read them (`CATALOG_READ`); should it refuse, the tab says so and
 * the rest of the catalog's page stays.
 */
export const load = (async (event) => {
	try {
		return { groups: await api(event).catalogGrants(event.params.catalog) };
	} catch (failure) {
		if (failure instanceof HuronApiError && failure.status === 403) return { groups: null };
		fail(event, failure);
	}
}) satisfies PageServerLoad;
