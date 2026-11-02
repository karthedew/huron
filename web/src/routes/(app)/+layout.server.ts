import { ORGANIZATION_LIMIT, shellOrganization } from '$lib/organizations';
import { requestCookies } from '$lib/server/cookies';
import { api, degrade, requireUser, settled } from '$lib/server/guard';
import type { LayoutServerLoad } from './$types';

/**
 * What the shell needs on every page. API failures degrade to the `…Unavailable` flags so the
 * shell still renders, and are logged; only an expired Huron token (401) leaves, through the
 * login redirect. The remembered organization is what an error page, which has no data of its
 * own, shows when the shell loads with it; the shell checks it against the visible list.
 */
export const load = (async (event) => {
	const user = requireUser(event);
	const client = api(event);
	const [organizations, whoami] = await Promise.all([
		settled(client.organizations({ limit: ORGANIZATION_LIMIT })),
		settled(client.whoami())
	]);
	for (const outcome of [organizations, whoami]) {
		if (!outcome.ok) degrade(event, outcome.failure);
	}
	return {
		user,
		organizations: organizations.ok ? organizations.value.items.map(shellOrganization) : [],
		organizationsUnavailable: !organizations.ok,
		roles: whoami.ok ? whoami.value.roles : [],
		rolesUnavailable: !whoami.ok,
		rememberedOrganization: requestCookies(event).rememberedOrganization()
	};
}) satisfies LayoutServerLoad;
