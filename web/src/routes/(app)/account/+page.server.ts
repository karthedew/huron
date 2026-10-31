import { describeRoles } from '$lib/roles';
import { requestCookies } from '$lib/server/cookies';
import { api, degrade, settled } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/** Enough organizations and catalogs to name the scope of every role. */
const SCOPE_LIMIT = 500;

/**
 * `/account`: who the user is comes from the session; the roles come from `whoami`, with their
 * scopes named through the visible organizations and catalogs. The page still shows the
 * identity and the sign-out button when the API fails.
 */
export const load = (async (event) => {
	const client = api(event);
	const [whoami, organizations, catalogs] = await Promise.all([
		settled(client.whoami()),
		settled(client.organizations({ limit: SCOPE_LIMIT })),
		settled(client.catalogs({ limit: SCOPE_LIMIT }))
	]);
	for (const outcome of [whoami, organizations, catalogs]) {
		if (!outcome.ok) degrade(event, outcome.failure);
	}
	const scopes = {
		organizations: organizations.ok ? organizations.value.items : [],
		catalogs: catalogs.ok ? catalogs.value.items : []
	};
	return {
		organization: requestCookies(event).rememberedOrganization(),
		roleSentences: whoami.ok ? describeRoles(whoami.value.roles, scopes) : null
	};
}) satisfies PageServerLoad;
