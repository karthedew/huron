import { api, guarded } from '$lib/server/guard';
import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import type { PageServerLoad } from './$types';

/** The organization's catalogs that the user can see, a page at a time. */
export const load = (async (event) => {
	const list = await guarded(
		event,
		api(event).catalogs({
			organization: event.params.org,
			cursor: cursorParam(event.url),
			limit: LIST_PAGE_SIZE
		})
	);
	return { catalogs: list.items, nextCursor: list.next_cursor ?? null };
}) satisfies PageServerLoad;
