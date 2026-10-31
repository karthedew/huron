import { redirect } from '@sveltejs/kit';
import type { Organization, Page } from '$api/types';
import { ORGANIZATION_LIMIT } from '$lib/organizations';
import { requestCookies } from '$lib/server/cookies';
import { api, fail } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * `/`: the remembered organization when it is visible, else the only visible one; otherwise
 * the list of organizations, or the empty state when there are none.
 */
export const load = (async (event) => {
	const remembered = requestCookies(event).rememberedOrganization();
	let page: Page<Organization>;
	try {
		page = await api(event).organizations({ limit: ORGANIZATION_LIMIT });
	} catch (failure) {
		fail(event, failure);
	}
	const visible = page.items;
	if (remembered !== null && visible.some((organization) => organization.name === remembered)) {
		redirect(303, organizationPath(remembered));
	}
	if (visible.length === 1 && !page.next_cursor) redirect(303, organizationPath(visible[0].name));
	return { organization: remembered, organizationList: visible };
}) satisfies PageServerLoad;

function organizationPath(name: string): string {
	return `/orgs/${encodeURIComponent(name)}`;
}
