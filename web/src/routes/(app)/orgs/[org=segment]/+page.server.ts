import { api, guarded } from '$lib/server/guard';
import { readBrowseSort } from '$lib/browse-sort';
import { BROWSE_PAGE_SIZE, cursorParam } from '$lib/paging';
import type { PageServerLoad } from './$types';

/** The organization's catalogs that the user can see, a page at a time. */
export const load = (async (event) => {
	const catalogSort = readBrowseSort(event.url);
	const list = await guarded(
		event,
		api(event).catalogs({
			organization: event.params.org,
			cursor: cursorParam(event.url),
			limit: BROWSE_PAGE_SIZE,
			...catalogSort
		})
	);
	return { catalogs: list.items, nextCursor: list.next_cursor ?? null, catalogSort };
}) satisfies PageServerLoad;
