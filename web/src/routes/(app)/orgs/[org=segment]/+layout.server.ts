import { api, guarded } from '$lib/server/guard';
import type { LayoutServerLoad } from './$types';

/**
 * The organization of every page below `/orgs/<org>`. An organization the user cannot see is
 * concealed by the API as not found.
 */
export const load = (async (event) => {
	const organization = await guarded(event, api(event).organization(event.params.org));
	return { organization: organization.name, organizationDetails: organization };
}) satisfies LayoutServerLoad;
