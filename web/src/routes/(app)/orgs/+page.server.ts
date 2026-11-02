import { requestCookies } from '$lib/server/cookies';
import { api, guarded } from '$lib/server/guard';
import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import type { PageServerLoad } from './$types';

/** `/orgs`: every organization the user can see, a page at a time. */
export const load = (async (event) => {
	const list = await guarded(
		event,
		api(event).organizations({ cursor: cursorParam(event.url), limit: LIST_PAGE_SIZE })
	);
	return {
		organization: requestCookies(event).rememberedOrganization(),
		organizationList: list.items,
		nextCursor: list.next_cursor ?? null
	};
}) satisfies PageServerLoad;
