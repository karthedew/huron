import { api, fail } from '$lib/server/guard';
import { HuronApiError } from '$lib/server/huron-api';
import type { PageServerLoad } from './$types';

/**
 * The groups granted each role on the organization itself: `org_admin`, and the catalog roles,
 * which hold in every catalog of the organization. The API lets anyone holding a role at the
 * organization, and platform admins, read them (`ORGANIZATION_READ`); someone with roles on
 * single catalogs only is refused, and the tab says so.
 */
export const load = (async (event) => {
	try {
		return { groups: await api(event).organizationGrants(event.params.org) };
	} catch (failure) {
		if (failure instanceof HuronApiError && failure.status === 403) return { groups: null };
		fail(event, failure);
	}
}) satisfies PageServerLoad;
