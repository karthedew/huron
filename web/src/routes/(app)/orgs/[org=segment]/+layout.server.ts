import { getConfig } from '$lib/server/config';
import { api, guarded } from '$lib/server/guard';
import { sharePath } from '$lib/share';
import type { LayoutServerLoad } from './$types';

/**
 * The organization of every page below `/orgs/<org>`. An organization the user cannot see is
 * concealed by the API as not found. Its directory on the share is `<root>/<org>` when the
 * service configuration declares a root for it, else `<mount prefix>/<org>`, as the CLI resolves it.
 */
export const load = (async (event) => {
	const organization = await guarded(event, api(event).organization(event.params.org));
	return {
		organization: organization.name,
		organizationDetails: organization,
		organizationPath: sharePath(organization.root, getConfig().mountPrefix, organization.name)
	};
}) satisfies LayoutServerLoad;
